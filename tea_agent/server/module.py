"""
HotReloadModule — 热重载模块系统核心。

提供：
  - HotReloadModule 基类：统一的 load/unload/reload/health 接口
  - ModuleRegistry：模块注册、依赖管理、文件监控
  - FileWatcher：基于 polling 的 .py 文件变更检测

所有业务模块（Agent/Toolkit/Pipeline/Storage）都是 HotReloadModule 的子类，
通过 ModuleRegistry 统一管理，修改代码后调用 reload_module() 即可热生效。
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger("hot_reload")


# ═══════════════════════════════════════════════════════════════
# HotReloadModule 基类
# ═══════════════════════════════════════════════════════════════

class HotReloadModule:
    """热重载模块基类。

    所有业务模块继承此类，实现 load/unload 两个核心方法。
    reload() 由基类提供：unload → importlib.reload → load。

    子类只需定义：
      name         — 模块名称（全局唯一）
      dependencies — 依赖模块名称列表（加载顺序保证）
      _load()      — 实际初始化逻辑（返回 bool）
      _unload()    — 清理逻辑
    """

    name: str = ""
    dependencies: list[str] = []

    _loaded: bool = False
    _version: int = 0
    _module_path: str = ""  # 对应源码文件路径（用于文件监控）
    _error: str = ""

    @classmethod
    def load(cls, registry: 'ModuleRegistry') -> bool:
        """加载模块。自动设置 _loaded / _version / _error。"""
        try:
            ok = cls._load(registry)
            cls._loaded = ok
            if ok:
                # 版本号由 registry 统一管理，跨重载持续递增
                ver = registry._inc_version(cls.name)
                cls._version = ver
                cls._error = ""
                logger.info(f"🔄 Module [{cls.name}] loaded v{ver}")
            else:
                cls._error = "_load() returned False"
                logger.warning(f"⚠️ Module [{cls.name}] load returned False")
            return ok
        except Exception as e:
            cls._loaded = False
            cls._error = f"{type(e).__name__}: {e}"
            logger.exception(f"❌ Module [{cls.name}] load failed: {e}")
            return False

    @classmethod
    def unload(cls) -> bool:
        """卸载模块。"""
        try:
            if cls._loaded:
                cls._unload()
                cls._loaded = False
                logger.info(f"🔄 Module [{cls.name}] unloaded")
            return True
        except Exception as e:
            logger.exception(f"❌ Module [{cls.name}] unload failed: {e}")
            return False

    @classmethod
    def reload(cls, registry: 'ModuleRegistry') -> type['HotReloadModule'] | None:
        """热重载模块：unload → importlib.reload → load。

        Returns:
            新的类对象（可能不同于 cls），成功时返回新类，失败返回 None。
            registry._modules 已更新指向新类。
        """
        old_version = cls._version
        name = cls.name
        cls.unload()
        mod_name = cls.__module__
        if mod_name in sys.modules:
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception as e:
                logger.exception(f"importlib.reload failed: {e}")
                cls._error = f"importlib.reload failed: {e}"
                return None
        new_class = _resolve_class(mod_name, cls.__name__)
        if new_class is None:
            cls._error = f"Class {cls.__name__} not found after reload"
            return None
        ok = new_class.load(registry)
        if ok:
            logger.info(f"✅ Module [{name}] hot-reloaded v{old_version}→{new_class._version}")
            # 更新 registry 中的引用指向新类
            registry._modules[name] = new_class
        return new_class if ok else None

    @classmethod
    def health(cls) -> dict[str, Any]:
        """返回模块健康状态。"""
        return {
            "name": cls.name,
            "loaded": cls._loaded,
            "version": cls._version,
            "error": cls._error,
            "dependencies": cls.dependencies,
            "module_path": cls._module_path,
        }

    @classmethod
    def _load(cls, registry: 'ModuleRegistry') -> bool:
        """子类实现：加载模块逻辑。"""
        raise NotImplementedError

    @classmethod
    def _unload(cls) -> None:
        """子类实现：卸载清理逻辑。"""
        raise NotImplementedError


def _resolve_class(module_name: str, class_name: str) -> type[HotReloadModule] | None:
    """在 reload 后的模块中重新找到类对象。"""
    mod = sys.modules.get(module_name)
    if mod is None:
        return None
    cls = getattr(mod, class_name, None)
    if cls is None or not isinstance(cls, type) or not issubclass(cls, HotReloadModule):
        return None
    return cls


# ═══════════════════════════════════════════════════════════════
# ModuleRegistry — 模块注册与生命周期管理
# ═══════════════════════════════════════════════════════════════

class ModuleRegistry:
    """模块注册表。

    负责：
    - 注册模块类
    - 按依赖顺序加载
    - 热重载单个/全部模块
    - 文件变更自动重载（FileWatcher）
    - 导出模块状态
    """

    def __init__(self):
        self._modules: dict[str, type[HotReloadModule]] = {}
        self._loaded: dict[str, type[HotReloadModule]] = {}
        self._lock = threading.Lock()
        self._watcher: 'FileWatcher | None' = None
        self._loaded_order: list[str] = []
        self._versions: dict[str, int] = {}  # 跨重载持续递增的版本号

    def _inc_version(self, name: str) -> int:
        """递增并返回模块版本号。"""
        v = self._versions.get(name, 0) + 1
        self._versions[name] = v
        return v

    def register(self, module_cls: type[HotReloadModule]) -> None:
        """注册一个模块类。"""
        name = module_cls.name
        if not name:
            raise ValueError(f"Module class {module_cls.__name__} has empty 'name'")
        self._modules[name] = module_cls
        logger.debug(f"Module registered: {name} ({module_cls.__module__})")

    def get(self, name: str) -> type[HotReloadModule] | None:
        """按名称获取模块类。"""
        return self._modules.get(name)

    def get_loaded(self, name: str) -> type[HotReloadModule] | None:
        """按名称获取已加载的模块类。"""
        return self._loaded.get(name)

    def all_modules(self) -> dict[str, type[HotReloadModule]]:
        """返回所有已注册模块的副本。"""
        return dict(self._modules)

    def load_all(self) -> dict[str, bool]:
        """按依赖顺序加载所有模块。"""
        results: dict[str, bool] = {}
        order = self._resolve_load_order()
        for name in order:
            cls = self._modules.get(name)
            if cls is None:
                continue
            success = cls.load(self)
            with self._lock:
                if success:
                    self._loaded[name] = cls
                    self._loaded_order.append(name)
                else:
                    self._loaded.pop(name, None)
            results[name] = success
        return results

    def reload_module(self, name: str, cascade: bool = True,
                      _reloaded: set[str] | None = None) -> bool:
        """热重载指定模块。

        cascade=True 时，自动找出依赖此模块的其他模块并级重重载。
        使用 _reloaded set 跟踪已重载模块，避免循环/重复重载。

        Args:
            name: 模块名称
            cascade: 是否级联重载依赖此模块的其他模块
            _reloaded: 内部使用，追踪本次级联链中已重载的模块名集合
        """
        if _reloaded is None:
            _reloaded = set()
        if name in _reloaded:
            return True  # 已重载过，跳过
        _reloaded.add(name)

        cls = self._modules.get(name)
        if cls is None:
            logger.warning(f"Module not found: {name}")
            return False

        with self._lock:
            old = self._loaded.pop(name, None)
        try:
            new_cls = cls.reload(self)  # 返回新类对象 or None
            success = new_cls is not None
            with self._lock:
                if success:
                    self._loaded[name] = new_cls
                    cls = new_cls  # 使用新类
                elif old:
                    self._loaded[name] = old
        except Exception as e:
            logger.exception(f"Reload module [{name}] failed: {e}")
            with self._lock:
                if old:
                    self._loaded[name] = old
            return False

        # 级联：找出依赖此模块的其他模块并重载
        if cascade and success:
            dependents = [
                other_name for other_name, other_cls in self._modules.items()
                if other_name != name and name in other_cls.dependencies
            ]
            if dependents:
                logger.info(f"📦 Cascade reloading dependents of [{name}]: {dependents}")
                for dep_name in dependents:
                    try:
                        # cascade=True 但共享 _reloaded set 避免重复
                        self.reload_module(dep_name, cascade=True, _reloaded=_reloaded)
                    except Exception as e:
                        logger.error(f"Cascade reload [{dep_name}] failed: {e}")

        return success

    def reload_all(self) -> dict[str, bool]:
        """重载所有已加载模块。"""
        results: dict[str, bool] = {}
        for name in reversed(self._loaded_order):
            cls = self._modules.get(name)
            if cls and cls._loaded:
                cls.unload()
        self._loaded.clear()
        self._loaded_order.clear()
        return self.load_all()

    def _resolve_load_order(self) -> list[str]:
        """拓扑排序：按依赖顺序排列模块。"""
        visited: set[str] = set()
        result: list[str] = []

        def dfs(name: str, path: set[str]) -> None:
            if name in visited:
                return
            if name in path:
                logger.warning(f"Dependency cycle detected: {name}")
                return
            cls = self._modules.get(name)
            if cls is None:
                return
            path.add(name)
            for dep in cls.dependencies:
                if dep in self._modules:
                    dfs(dep, path)
            path.remove(name)
            visited.add(name)
            result.append(name)

        for name in self._modules:
            dfs(name, set())
        return result

    def status(self) -> list[dict[str, Any]]:
        """返回所有模块的状态列表。"""
        result = []
        for name, cls in self._modules.items():
            info = cls.health()
            info["loaded"] = name in self._loaded
            result.append(info)
        return result

    def is_all_loaded(self) -> bool:
        """检查是否所有模块都已加载。"""
        return all(cls._loaded for name, cls in self._modules.items())

    def start_watcher(self, interval: float = 2.0,
                      paths: list[str] | None = None,
                      server=None) -> None:
        """启动文件监控线程（polling 模式）。

        Args:
            interval: 轮询间隔（秒）
            paths: 额外监控的文件路径
            server: MinimalServer 实例（传此参数后，server.py/
                    route_handlers.py 变更自动触发 rebuild_routes）
        """
        if self._watcher is not None:
            logger.warning("Watcher already running")
            return
        watch_paths: list[str] = []
        if paths:
            watch_paths.extend(paths)
        else:
            for cls in self._modules.values():
                mod_path = getattr(cls, '_module_path', '')
                if mod_path and os.path.isfile(mod_path):
                    watch_paths.append(mod_path)
            tea_agent_dir = str(Path(__file__).parent.parent)
            # 核心 Agent 模块文件（变更时触发模块级热重载）
            for sub in [
                'agent.py', 'onlinesession.py', 'tlk.py',
                'config.py', 'store.py', 'agent_pipeline.py',
                'basesession.py', 'session_pipeline.py',
                'session/context.py', 'session/history_builder.py',
                'session/os_info_injector.py', 'session/params.py',
                'session/prompts.py', 'session/tool_loop_runner.py',
            ]:
                fp = os.path.join(tea_agent_dir, sub)
                if os.path.isfile(fp):
                    watch_paths.append(fp)
            watch_paths = list(set(watch_paths))

        # If server reference provided, set up route hot-reload callback
        on_route_change = None
        if server and hasattr(server, 'rebuild_routes'):
            on_route_change = server.rebuild_routes
            # Also watch server.py and route_handlers.py
            server_dir = str(Path(__file__).parent)
            for f in ['server.py', 'route_handlers.py']:
                fp = os.path.join(server_dir, f)
                if os.path.isfile(fp) and fp not in watch_paths:
                    watch_paths.append(fp)

        self._watcher = FileWatcher(self, watch_paths, interval,
                                    on_route_change=on_route_change)
        self._watcher.start()
        logger.info(f"File watcher started ({len(watch_paths)} files)")

    def stop_watcher(self) -> None:
        """停止文件监控。"""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def add_paths_to_watch(self, paths: list[str]) -> None:
        """动态添加需要监控的文件路径。"""
        if self._watcher:
            self._watcher.add_paths(paths)


# ═══════════════════════════════════════════════════════════════
# _ModuleVersionManager — 模块文件版本管理 + 自动回退
# ═══════════════════════════════════════════════════════════════

class _ModuleVersionManager:
    """模块文件版本管理器 — 在热重载前自动备份、失败时自动回退。

    工作原理：
    - 每次 reload 前自动备份当前文件内容（新版本）
    - reload 成功后标记该版本为 last_good
    - reload 失败时从 last_good 恢复文件并重试
    - 每个文件保留 MAX_VERSIONS 个版本历史

    版本备份存储在 .tea_agent_run/module_versions/ 目录。
    """

    _backup_dir: ClassVar[str] = ""
    _last_good: ClassVar[dict[str, int]] = {}
    MAX_VERSIONS: ClassVar[int] = 5

    @classmethod
    def _ensure_dir(cls) -> str:
        if not cls._backup_dir:
            cls._backup_dir = os.path.join(
                str(Path(__file__).parent.parent.parent),
                ".tea_agent_run", "module_versions"
            )
            os.makedirs(cls._backup_dir, exist_ok=True)
        return cls._backup_dir

    @classmethod
    def _safe_name(cls, filepath: str) -> str:
        """将文件路径转换为安全的备份文件名。"""
        tea_agent_dir = str(Path(__file__).parent.parent.parent)
        try:
            rel = os.path.relpath(filepath, tea_agent_dir)
        except ValueError:
            rel = os.path.basename(filepath)
        return rel.replace("\\", "_").replace("/", "_").replace(".py", "")

    @classmethod
    def _get_version_files(cls, filepath: str) -> list[int]:
        """获取文件的所有已备份版本号（排序后）。"""
        safe = cls._safe_name(filepath)
        bdir = cls._ensure_dir()
        versions = []
        for f in Path(bdir).glob(f"{safe}.v*.bak"):
            try:
                v = int(f.name.split('.v')[1].split('.')[0])
                versions.append(v)
            except (ValueError, IndexError):
                pass
        return sorted(versions)

    @classmethod
    def backup_new_version(cls, filepath: str) -> int | None:
        """备份当前文件内容为新版本。返回版本号，无变化时返回 None。"""
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.debug(f"Cannot read {filepath} for backup: {e}")
            return None

        existing = cls._get_version_files(filepath)
        new_ver = (existing[-1] if existing else 0) + 1

        safe = cls._safe_name(filepath)
        bdir = cls._ensure_dir()
        backup_path = os.path.join(bdir, f"{safe}.v{new_ver}.bak")

        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logger.warning(f"Backup write failed for {filepath}: {e}")
            return None

        # 限制版本数量，删除最旧的
        while len(existing) >= cls.MAX_VERSIONS:
            old_ver = existing.pop(0)
            old_path = os.path.join(bdir, f"{safe}.v{old_ver}.bak")
            try:
                os.remove(old_path)
            except OSError:
                pass

        return new_ver

    @classmethod
    def mark_last_good(cls, filepath: str, version: int) -> None:
        """标记指定版本为最后可用版本。"""
        cls._last_good[filepath] = version
        safe = cls._safe_name(filepath)
        bdir = cls._ensure_dir()
        marker = os.path.join(bdir, f"{safe}.last_good")
        try:
            with open(marker, 'w') as f:
                f.write(str(version))
        except Exception:
            pass

    @classmethod
    def get_last_good_version(cls, filepath: str) -> int | None:
        """获取最后可用版本号（先查内存，再查磁盘标记）。"""
        v = cls._last_good.get(filepath)
        if v is not None:
            return v
        safe = cls._safe_name(filepath)
        bdir = cls._ensure_dir()
        marker = os.path.join(bdir, f"{safe}.last_good")
        try:
            with open(marker, 'r') as f:
                v = int(f.read().strip())
                cls._last_good[filepath] = v
                return v
        except (FileNotFoundError, ValueError):
            # 没有 last_good → 如果有备份版本，取最新版本
            versions = cls._get_version_files(filepath)
            if versions:
                v = versions[-1]
                cls._last_good[filepath] = v
                return v
            return None

    @classmethod
    def get_last_good_path(cls, filepath: str) -> str | None:
        """获取最后可用版本的备份文件路径。"""
        v = cls.get_last_good_version(filepath)
        if v is None:
            return None
        safe = cls._safe_name(filepath)
        bdir = cls._ensure_dir()
        return os.path.join(bdir, f"{safe}.v{v}.bak")

    @classmethod
    def restore_last_good(cls, filepath: str) -> bool:
        """将文件恢复到最后可用版本。"""
        last_good_path = cls.get_last_good_path(filepath)
        if last_good_path is None or not os.path.isfile(last_good_path):
            logger.warning(f"Cannot rollback {filepath}: no last_good backup")
            return False

        try:
            with open(last_good_path, 'r', encoding='utf-8') as f:
                content = f.read()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.warning(f"🔄 Rolled back {os.path.basename(filepath)} → "
                          f"v{cls.get_last_good_version(filepath)}")
            return True
        except Exception as e:
            logger.error(f"Rollback failed for {filepath}: {e}")
            return False

    @classmethod
    def list_versions(cls, filepath: str) -> list[dict]:
        """列出文件的所有可回退版本。"""
        versions = cls._get_version_files(filepath)
        last_good = cls.get_last_good_version(filepath)
        result = []
        for v in versions:
            safe = cls._safe_name(filepath)
            bdir = cls._ensure_dir()
            path = os.path.join(bdir, f"{safe}.v{v}.bak")
            result.append({
                "version": v,
                "path": path,
                "exists": os.path.isfile(path),
                "is_last_good": v == last_good,
            })
        return result

    @classmethod
    def is_rollback_version(cls, filepath: str) -> bool:
        """检查文件当前内容是否与 last_good 一致（即已处于回退状态）。"""
        if not os.path.isfile(filepath):
            return False
        last_good_v = cls.get_last_good_version(filepath)
        if last_good_v is None:
            return False
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                current = f.read()
            safe = cls._safe_name(filepath)
            bdir = cls._ensure_dir()
            backup_path = os.path.join(bdir, f"{safe}.v{last_good_v}.bak")
            if not os.path.isfile(backup_path):
                return False
            with open(backup_path, 'r', encoding='utf-8') as f:
                good = f.read()
            return current == good
        except Exception:
            return False

    @classmethod
    def init_backup(cls, filepath: str) -> None:
        """初始化备份（首次启动时调用）：备份当前文件并标记为 last_good。"""
        if not os.path.isfile(filepath):
            return
        # 检查是否已有备份
        existing = cls._get_version_files(filepath)
        if existing:
            # 已经有备份，只确保有 last_good 标记
            if cls.get_last_good_version(filepath) is None:
                cls.mark_last_good(filepath, existing[-1])
            return
        # 首次备份
        v = cls.backup_new_version(filepath)
        if v is not None:
            cls.mark_last_good(filepath, v)

class FileWatcher:
    """基于 polling 的文件变更检测器。"""

    def __init__(self, registry: ModuleRegistry,
                 file_paths: list[str], interval: float = 2.0,
                 on_route_change=None):
        self._registry = registry
        self._file_paths: list[str] = list(file_paths)
        self._interval = interval
        self._mtimes: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._on_route_change = on_route_change  # callback for server.py/route_handlers.py changes
        # 核心 session 文件 → 目标模块名映射（文件变更时不经过 module_path 匹配，直接映射）
        self._core_file_map: dict[str, str] = self._build_core_file_map()

        # ── 启动时初始化版本备份（确保每个监控文件有至少一个 last_good 版本） ──
        for fp in file_paths:
            if fp.endswith('.py') and os.path.isfile(fp):
                _ModuleVersionManager.init_backup(fp)

    def _build_core_file_map(self) -> dict[str, str]:
        """构建核心 session 文件到目标模块的映射。

        当开发者在 basesession.py / session/context.py 等文件中修改代码时，
        FileWatcher 通过此映射直接触发对应 HotReloadModule 的 reload。
        避免这些"非模块类文件"被忽略。
        """
        tea_agent_dir = os.path.normcase(os.path.normpath(
            str(Path(__file__).parent.parent)))
        mapping: dict[str, str] = {}
        # key=相对路径, value=目标模块名（必须在 ModuleRegistry 中注册过）
        _rel_map = {
            'basesession.py': 'agent',
            'session_pipeline.py': 'agent',
            'session/context.py': 'agent',
            'session/history_builder.py': 'agent',
            'session/os_info_injector.py': 'agent',
            'session/params.py': 'agent',
            'session/prompts.py': 'agent',
            'session/tool_loop_runner.py': 'agent',
        }
        for rel_path, module_name in _rel_map.items():
            full = os.path.normcase(os.path.normpath(
                os.path.join(tea_agent_dir, rel_path)))
            mapping[full] = module_name
        return mapping

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="FileWatcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def add_paths(self, paths: list[str]) -> None:
        for fp in paths:
            if fp not in self._file_paths:
                self._file_paths.append(fp)
                try:
                    self._mtimes[fp] = os.path.getmtime(fp)
                except OSError:
                    pass

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._check()
            self._stop_event.wait(timeout=self._interval)

    def _check(self) -> None:
        for fp in self._file_paths:
            try:
                new_mtime = os.path.getmtime(fp)
                old_mtime = self._mtimes.get(fp)
                if old_mtime is not None and new_mtime > old_mtime:
                    self._mtimes[fp] = new_mtime
                    self._on_file_change(fp)
            except OSError:
                pass

    def _on_file_change(self, file_path: str) -> None:
        file_path = os.path.normcase(os.path.normpath(file_path))

        # ── Route file change → hot-reload routes (no restart) ──
        if self._on_route_change:
            server_dir = os.path.dirname(os.path.abspath(__file__))
            route_files = [
                os.path.normcase(os.path.normpath(os.path.join(server_dir, f)))
                for f in ['server.py', 'route_handlers.py']
            ]
            if file_path in route_files:
                logger.info(f"Route file changed: {os.path.basename(file_path)} → rebuilding routes")
                try:
                    self._on_route_change()
                except Exception as e:
                    logger.error(f"Route rebuild failed: {e}")
                return

        # ── 所有 .py 文件变更 → 自动备份（reload 前确保有回退能力） ──
        new_ver = None
        if file_path.endswith('.py') and os.path.isfile(file_path):
            new_ver = _ModuleVersionManager.backup_new_version(file_path)

        # ── 辅助函数：带版本管理的 reload ──
        def _reload_with_version(name: str) -> bool:
            """执行 reload + 成功时标记/good，失败时自动回退。"""
            basename = os.path.basename(file_path)
            ok = self._registry.reload_module(name)
            if ok:
                if new_ver is not None:
                    _ModuleVersionManager.mark_last_good(file_path, new_ver)
                logger.info(f"✅ Hot-reload [{name}] ← {basename} (v{new_ver}) OK")
                return True
            # ── 失败：自动回退 ──
            logger.warning(f"❌ Hot-reload [{name}] ← {basename} failed → rolling back")
            if _ModuleVersionManager.restore_last_good(file_path):
                logger.info(f"🔄 Retrying [{name}] reload after rollback...")
                retry_ok = self._registry.reload_module(name)
                if retry_ok:
                    # 恢复成功后的版本也作为 last_good
                    _ModuleVersionManager.mark_last_good(file_path, new_ver or 0)
                    logger.info(f"✅ [{name}] recovered after rollback")
                    return True
                logger.error(f"🚨 [{name}] still broken after rollback!")
            else:
                logger.error(f"🚨 [{name}] rollback failed (no last_good backup)")
            return False

        # ── 核心 session 文件 → 映射到热重载模块 ──
        target_module = self._core_file_map.get(file_path)
        if target_module:
            _reload_with_version(target_module)
            return

        for name, cls in self._registry._modules.items():
            mod_path = getattr(cls, '_module_path', '')
            if mod_path and os.path.normcase(os.path.normpath(mod_path)) == file_path:
                _reload_with_version(name)
                return
        for name, cls in self._registry._modules.items():
            mod_name = cls.__module__
            try:
                spec = importlib.util.find_spec(mod_name)
                if spec and spec.origin:
                    spec_path = os.path.normcase(os.path.normpath(spec.origin))
                    if spec_path == file_path:
                        _reload_with_version(name)
                        return
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

_registry: ModuleRegistry | None = None


def get_registry() -> ModuleRegistry:
    """获取全局 ModuleRegistry 单例。"""
    global _registry
    if _registry is None:
        _registry = ModuleRegistry()
    return _registry


def reset_registry() -> None:
    """重置全局单例（主要用于测试）。"""
    global _registry
    if _registry:
        _registry.stop_watcher()
    _registry = None


def _module_path_for(cls: type) -> str:
    """获取类定义所在的 .py 文件路径。"""
    import sys
    try:
        mod = sys.modules.get(cls.__module__)
        if mod and hasattr(mod, '__file__') and mod.__file__:
            return os.path.abspath(mod.__file__)
    except Exception:
        pass
    return ""

"""审计日志 — 自进化动作的 append-only 可信记录（tamper-evident hash 链）。

设计目标（对齐 DeepSeek Harness「可追溯性即基础设施」哲学）：
- **append-only**：只追加、不修改、不删除；一天一个 JSONL 文件
- **hash 链**：每条记录携带前一条哈希与自身哈希，任何篡改都能被 verify() 检出
- **脱敏**：密钥类字段/值在写入前统一掩码，审计日志自身不成为泄密源
- **零依赖**：仅标准库；审计不可用时静默降级，绝不阻断主流程

用法::

    from tea_agent.audit_log import audit_log

    audit_log.record("tool/call", tool="toolkit_exec", detail={"app": "git"})
    audit_log.record("tool/result", tool="toolkit_exec", status="ok", duration_ms=120)
    audit_log.verify()      # {'ok': True, 'records': 12, ...}
    audit_log.tail(5)

存储位置（按优先级）：TEA_AUDIT_DIR > <项目>/.tea_agent_run/audit > <临时目录>/tea_agent_audit
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from typing import Any

try:  # POSIX 跨进程文件锁
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # Windows 跨进程文件锁
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None

logger = logging.getLogger("tea_agent.audit")

__all__ = ["AuditLog", "audit_log", "mask_secrets", "GENESIS_HASH"]


def _file_size(path: str) -> int:
    """文件当前字节数；不存在/不可访问返回 -1（作为「不可比较」的哨兵值）。"""
    try:
        return os.path.getsize(path)
    except OSError:
        return -1


@contextlib.contextmanager
def _cross_process_lock(path: str, timeout: float = 3.0):
    """对 ``<path>.lock`` 加互斥，使「读末行 → 追加」在进程间原子。

    取不到锁时**仍然继续写入**：审计的可用性优先于链的绝对严格，
    为写日志而阻塞主流程的代价远高于偶发链断裂（且下一条记录会自愈式恢复链头）。
    """
    handle = None
    try:
        handle = open(path + ".lock", "a+", encoding="utf-8")
    except OSError as e:  # 锁文件都建不了 → 退化为无锁
        logger.debug("audit: 锁文件不可用(%s)，按无锁继续: %s", path, e)
        yield
        return

    acquired = False
    deadline = time.time() + timeout
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - 无可用锁机制
                    break
                acquired = True
                break
            except OSError:
                if time.time() >= deadline:
                    logger.debug("audit: 等待锁超时，无锁继续写入: %s", path)
                    break
                time.sleep(0.01)
        yield
    finally:
        try:
            if acquired:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as e:
            logger.debug("audit: 释放锁失败: %s", e)
        with contextlib.suppress(OSError):
            handle.close()

# 链首哈希（每条链的第一条记录以此为 prev）
GENESIS_HASH = "0" * 64

_MASK = "***MASKED***"
_MAX_STR = 500

# 键名命中 → 值整体掩码
_SECRET_KEY_RE = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE)",
    re.IGNORECASE,
)
# 值形态命中 → 掩码（常见密钥前缀）
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,})"
)


def mask_secrets(value: Any, _depth: int = 0) -> Any:
    """递归脱敏：dict 键命中敏感词则整体掩码，字符串命中密钥形态则替换。

    Args:
        value: 任意可 JSON 化的值
        _depth: 内部递归深度保护

    Returns:
        脱敏后的同构值
    """
    if _depth > 6:
        return "<max-depth>"
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = _MASK
            else:
                out[k] = mask_secrets(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [mask_secrets(v, _depth + 1) for v in value]
    if isinstance(value, str):
        s = _SECRET_VALUE_RE.sub(_MASK, value)
        if len(s) > _MAX_STR:
            s = s[:_MAX_STR] + f"...(+{len(s) - _MAX_STR} chars)"
        return s
    return value


def _canonical(obj: Any) -> str:
    """稳定序列化（键排序 + 紧凑分隔符），保证哈希可复现。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    """append-only 审计日志（线程安全 + 进程间加锁）。

    链规则：**每条链对应一个日文件**，链首用 GENESIS_HASH。
    同一天内跨进程追加时，凭「文件尺寸是否变化」判断内存链头是否过期，
    过期则回读文件末行恢复链头；读末行与追加由 <文件>.lock 互斥保护。
    """

    def __init__(self, directory: str | None = None, enabled: bool = True,
                 max_entries_scan: int = 20000) -> None:
        self._dir_override = directory
        self._enabled = enabled
        self._max_scan = max_entries_scan
        self._lock = threading.RLock()
        self._resolved_dir: str | None = None
        self._last_hash: str | None = None
        self._last_day: str | None = None
        # 上次由**本进程**写入后的文件字节数：用于判断链头缓存是否仍可信。
        self._last_size: int = -1

    # ── 开关与目录 ──

    def set_enabled(self, enabled: bool) -> None:
        """启停审计（关闭后 record 直接返回 None）。"""
        with self._lock:
            self._enabled = bool(enabled)

    def is_enabled(self) -> bool:
        """当前是否生效（含环境变量 TEA_AUDIT_DISABLED 覆盖）。"""
        if not self._enabled:
            return False
        return os.environ.get("TEA_AUDIT_DISABLED", "").strip().lower() not in ("1", "true", "yes")

    def directory(self) -> str | None:
        """解析（必要时创建）审计目录；全部候选不可写时返回 None。"""
        with self._lock:
            if self._resolved_dir and os.path.isdir(self._resolved_dir):
                return self._resolved_dir
            candidates: list[str] = []
            if self._dir_override:
                candidates.append(self._dir_override)
            env = os.environ.get("TEA_AUDIT_DIR", "").strip()
            if env:
                candidates.append(env)
            try:
                from tea_agent.storage_scope import project_run_dir

                prd = project_run_dir()
                if prd:
                    candidates.append(os.path.join(prd, "audit"))
            except Exception:  # noqa: BLE001 — 存储作用域不可用时回退
                candidates.append(os.path.join(os.getcwd(), ".tea_agent_run", "audit"))
            candidates.append(os.path.join(tempfile.gettempdir(), "tea_agent_audit"))

            for cand in candidates:
                if self._probe_writable(cand):
                    self._resolved_dir = cand
                    return cand
            logger.debug("audit: 无可用审计目录，审计静默关闭")
            return None

    @staticmethod
    def _probe_writable(cand: str) -> bool:
        """探测目录是否可创建/可写。

        ⚠️ 探测文件名必须**按进程唯一**。旧实现所有进程共用同一个 `.write_probe`：
        并发启动时 A 建完删掉，B 的 ``os.remove`` 随即抛 FileNotFoundError，被
        ``except OSError`` 误判为「该目录不可写」→ B 静默改写到下一个候选目录。
        实测多进程压测下稳定丢整段记录（90 条只剩 75），而审计日志一旦落到意外
        目录就等于丢失 —— verify() 还看不出问题（两处各自成链）。

        同理，探测本身的失败才是唯一需要换目录的信号；清理失败不该影响判定。
        """
        probe = os.path.join(cand, f".write_probe.{os.getpid()}.{id(cand) & 0xFFFF:04x}")
        try:
            os.makedirs(cand, exist_ok=True)
            with open(probe, "a", encoding="utf-8"):
                pass
        except OSError as e:
            logger.debug("audit: 目录不可写(%s): %s", cand, e)
            return False
        finally:
            # 清理失败只是留个临时文件，不代表目录不可用 → 不得影响判定
            with contextlib.suppress(OSError):
                os.remove(probe)
        return True

    # ── 写入 ──

    def record(self, event: str, tool: str = "", phase: str = "", status: str = "",
               detail: Any = None, session_id: str = "", actor: str = "agent",
               duration_ms: int | None = None, **extra: Any) -> dict | None:
        """追加一条审计记录。

        Args:
            event: 事件类型，如 tool/call、tool/result、approval/deny、self_evolve/apply
            tool: 工具名（可选）
            phase: 阶段标记，如 pre/post（可选）
            status: 结果状态，如 ok/error/denied（可选）
            detail: 任意细节（自动脱敏 + 截断）
            session_id: 会话标识（可选）
            actor: 触发者（agent/user/system）
            duration_ms: 耗时毫秒（可选）
            **extra: 其他附加字段

        Returns:
            写入的记录（含 prev/h 链字段）；审计不可用时返回 None
        """
        if not self.is_enabled():
            return None

        rec: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "event": str(event),
            "actor": actor,
        }
        if tool:
            rec["tool"] = str(tool)
        if phase:
            rec["phase"] = str(phase)
        if status:
            rec["status"] = str(status)
        if session_id:
            rec["session_id"] = str(session_id)
        if duration_ms is not None:
            rec["duration_ms"] = int(duration_ms)
        if detail is not None:
            rec["detail"] = mask_secrets(detail)
        for k, v in extra.items():
            if v is not None:
                rec[k] = mask_secrets(v)

        directory = self.directory()
        if directory is None:
            return None
        day = datetime.now().strftime("%Y%m%d")
        path = os.path.join(directory, f"audit-{day}.jsonl")

        # 进程间互斥：必须让「读链头 → 算哈希 → 追加」成为跨进程原子操作，
        # 否则两个并发进程会读到同一个末行、各自算出相同的 prev，追加后直接断链。
        # 先释放进程内锁再拿 OS 锁（OS 锁会阻塞，不可持 Python 锁等待）。
        with _cross_process_lock(path):
            with self._lock:
                prev = self._chain_head(path, day)
                rec["prev"] = prev
                rec["h"] = hashlib.sha256((prev + _canonical(rec)).encode("utf-8")).hexdigest()
                line = json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str)
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                        # flush 即可让其它进程读到这行（写入 OS 页缓存）；
                        # 刻意不用 fsync —— 审计在每次工具调用都会写，强制落盘会把
                        # 崩溃级持久性保证的成本摊到热路径上，而链完整性并不需要它。
                        f.flush()
                except OSError as e:  # 审计失败绝不阻断主流程
                    logger.debug("audit: 写入失败 %s: %s", path, e)
                    self._last_size = _file_size(path)
                    return None
                self._last_hash = rec["h"]
                self._last_day = day
                # 必须与 _chain_head 里的 _file_size() 同源取值：若改用 f.tell()
                # 之类不同口径，两者永不相等 → 每次写入都退化成全文件扫描，
                # 在千条级审计文件上会把热路径拖成 O(n)。
                self._last_size = _file_size(path)
        return rec

    def _chain_head(self, path: str, day: str) -> str:
        """取当前日文件的链头 —— 必须是**文件真实末行**的哈希。

        缓存不可直接信：本进程写入后，其它进程可能又追加过记录，此时内存里的
        `_last_hash` 已过期，继续沿用会让新记录的 `prev` 回指旧哈希（跳过中间
        记录），从而把 append-only 可信链判定为「被删除/插入/重排」。

        判定方式很轻量：比较文件当前字节数与上次写入后记录的字节数。只有完全
        一致才说明链头仍可信；一旦变大（他进程追加）或读不到（被轮转/清空）
        就回读末行。稳态下这只是一次 getsize + 一次 open-append，无额外读盘。
        """
        if self._last_day == day and self._last_hash and self._last_size == _file_size(path):
            return self._last_hash
        last = GENESIS_HASH
        try:
            if os.path.exists(path):
                tail = self._read_last_line(path)
                if tail is not None:
                    try:
                        last = json.loads(tail).get("h") or GENESIS_HASH
                    except ValueError:
                        # 末行残缺（写入中断）：退回全量扫描找最后一条完整记录
                        with open(path, encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if not line:
                                    continue
                                with contextlib.suppress(ValueError):
                                    last = json.loads(line).get("h") or GENESIS_HASH
        except (OSError, ValueError):
            return GENESIS_HASH
        self._last_hash = last
        self._last_day = day
        # 同步尺寸：否则 _last_size 停留在旧值，下一次写入又会误判「链头已过期」
        # 而重复回读末行（正确但不必要）。
        self._last_size = _file_size(path)
        return last

    @staticmethod
    def _read_last_line(path: str) -> str | None:
        """倒序读最后一个非空行（避免 O(n) 全文件扫描），不做解码替换。

        Returns:
            末行文本；文件为空返回 ""；无法可靠定位单行起点（块内不足或首行
            仍未找到换行）返回 None，交调用方退回全量扫描。
        """
        try:
            size = os.path.getsize(path)
        except OSError:
            return None
        if size == 0:
            return ""
        block = 8192
        with open(path, "rb") as f:
            offset = size
            buf = b""
            while offset > 0:
                read = min(block, offset)
                offset -= read
                try:
                    f.seek(offset)
                    chunk = f.read(read)
                except OSError:
                    return None
                if not chunk:
                    break
                # 用 rstrip 只处理块右端（含文件末尾换行），不吞行内空白
                buf = chunk + buf
                if b"\n" in buf.rstrip():
                    stripped = buf.rstrip()
                    lines = stripped.split(b"\n")
                    candidate = stripped if len(lines) == 1 else lines[-1]
                    try:
                        return candidate.decode("utf-8")
                    except UnicodeDecodeError:
                        # 跨块切到多字节字符中间：退回全量扫描
                        return None
            if buf.strip():
                try:
                    return buf.strip().split(b"\n")[-1].decode("utf-8")
                except UnicodeDecodeError:
                    return None
            return ""

    # ── 读取与校验 ──

    def files(self) -> list[str]:
        """返回审计目录下全部日文件（按名排序）。"""
        directory = self.directory()
        if not directory:
            return []
        try:
            names = [n for n in os.listdir(directory) if n.startswith("audit-") and n.endswith(".jsonl")]
        except OSError:
            return []
        return [os.path.join(directory, n) for n in sorted(names)]

    def _read(self, path: str, limit: int | None = None, from_end: bool = False) -> list[dict]:
        """读取记录（容错：坏行跳过）。"""
        out: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        if from_end:
            out = out[-limit:] if limit else out
        elif limit:
            out = out[:limit]
        return out

    def tail(self, n: int = 20) -> list[dict]:
        """返回最近 n 条记录（跨日文件，按时间顺序）。"""
        files = self.files()
        if not files:
            return []
        collected: list[dict] = []
        for path in reversed(files):
            collected = self._read(path) + collected
            if len(collected) >= n:
                break
        return collected[-n:]

    def verify(self, path: str | None = None) -> dict:
        """校验 hash 链完整性（检出篡改/插入/删除）。

        Returns:
            {'ok': bool, 'files': int, 'records': int, 'broken_at': str|None, 'reason': str}
        """
        targets = [path] if path else self.files()
        total = 0
        for p in targets:
            recs = self._read(p)
            prev = GENESIS_HASH
            for idx, rec in enumerate(recs):
                total += 1
                stored_h = rec.get("h")
                stored_prev = rec.get("prev")
                if stored_prev != prev:
                    return {
                        "ok": False, "files": len(targets), "records": total,
                        "broken_at": f"{os.path.basename(p)}#{idx + 1}",
                        "reason": "prev 链断裂（记录被删除/插入/重排）",
                    }
                body = {k: v for k, v in rec.items() if k != "h"}
                expect = hashlib.sha256((prev + _canonical(body)).encode("utf-8")).hexdigest()
                if stored_h != expect:
                    return {
                        "ok": False, "files": len(targets), "records": total,
                        "broken_at": f"{os.path.basename(p)}#{idx + 1}",
                        "reason": "记录内容哈希不匹配（记录被篡改）",
                    }
                prev = stored_h
        return {
            "ok": True, "files": len(targets), "records": total,
            "broken_at": None, "reason": "链路完整",
        }

    def stats(self) -> dict:
        """审计状态概览。"""
        files = self.files()
        records = 0
        size = 0
        last_ts = None
        for p in files:
            try:
                size += os.path.getsize(p)
            except OSError as e:
                logger.warning("audit_log.py.stats: OSError 已忽略: %s", e)
            recs = self._read(p, limit=None)
            records += len(recs)
            if recs:
                last_ts = recs[-1].get("ts")
        return {
            "enabled": self.is_enabled(),
            "directory": self.directory(),
            "files": len(files),
            "records": records,
            "bytes": size,
            "last_ts": last_ts,
        }


# ── 模块级单例（全局共享）──
audit_log = AuditLog()

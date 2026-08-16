"""
Skill 按需加载评估器 (Skill Load Evaluator)

设计理念（借鉴 Codex skill 自动发现 / Pi available_skills，但加"必要性/充分性"双维评估）：
    不预载技能，而是在对话过程中动态评估"是否值得加载某个 skill"。

评估双维度：
    必要性 (Necessity)   — 对话任务与 skill 能力描述的相关度 (0~1)
    充分性 (Sufficiency) — 现有工具对任务领域的覆盖度 (0~1)

决策矩阵：
    necessity >= N_THRESHOLD 且 sufficiency <  S_THRESHOLD → LOAD（skill 提供现有工具缺失的方法论/工作流）
    necessity >= N_THRESHOLD 且 sufficiency >= S_THRESHOLD → NO_LOAD（现有工具已够用，避免冗余注入）
    necessity <  N_THRESHOLD                              → NO_LOAD（与当前任务无关）

触发时机（"经过几轮对话后"评估）：
    收集最近 M 轮用户消息作为证据（默认 3 轮），证据不足（<2 轮）不评估，避免首轮误判。
    已加载的 skill 记录在 SessionContext._skill_loaded，不重复注入。

废除说明：
    本模块取代旧的"知识结晶"机制（SkillCrystallizer + SkillRegistry.recommend 自动推荐注入）。
    不再把任务执行过程自动结晶为 JSON 技能，改为按需加载静态 SKILL.md 技能包。

用法（history_builder 集成）：
    from tea_agent.skill_loader import evaluate_and_load
    skill_text = evaluate_and_load(context)   # 返回需注入的 SKILL.md 文本，无需注入则返回 None
    if skill_text:
        inject_parts.append(skill_text)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("skill_loader")

__all__ = [
    "SkillDecision",
    "SkillLoadEvaluator",
    "get_evaluator",
    "evaluate_and_load",
    "clear_cache",
]

# ── 阈值（可调） ──
NECESSITY_THRESHOLD = 0.30    # 必要性阈值：低于此视为"无关"
SUFFICIENCY_THRESHOLD = 0.55  # 充分性阈值：高于此视为"现有工具已够用"
MAX_LOAD_PER_ROUND = 2        # 每轮最多加载的 skill 数
EVIDENCE_ROUNDS = 3           # 用最近几轮用户消息作为评估证据
MIN_EVIDENCE_ROUNDS = 2       # 至少几轮证据才评估
MAX_INJECT_CHARS = 4000       # 单个 skill 最大注入字符数（防膨胀）
SCAN_CACHE_TTL = 60           # 扫描缓存秒数

# 内置 skills 目录（相对本文件）
_DEFAULT_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


@dataclass
class SkillDecision:
    """单个 skill 的评估决策。

    Attributes:
        name: skill 名称（目录名）
        necessity: 必要性得分 0~1
        sufficiency: 充分性得分 0~1
        action: "load" 或 "no_load"
        reason: 决策原因（irrelevant / already_covered / load）
    """

    name: str
    necessity: float = 0.0
    sufficiency: float = 0.0
    action: str = "no_load"
    reason: str = "irrelevant"


# ═══ 内置 skill 领域映射：keywords（强词权重2 / 弱词权重1）+ covered_by（现有替代工具）═══

@dataclass
class SkillDomain:
    """skill 领域元数据。

    Attributes:
        strong_keywords: 强关键词（命中即高度相关，权重 2）
        weak_keywords: 弱关键词（权重 1）
        covered_by: 现有工具（充分性来源，命中比例高 → 无需加载 skill）
    """

    strong_keywords: list[str] = field(default_factory=list)
    weak_keywords: list[str] = field(default_factory=list)
    covered_by: list[str] = field(default_factory=list)


SKILL_DOMAINS: dict[str, SkillDomain] = {
    "agent-browser": SkillDomain(
        strong_keywords=["浏览器自动化", "browser automation", "填表", "表单", "点击按钮", "爬取网页",
                         "scrape", "网页截图", "自动化浏览器", "登录网站", "web 测试", "网页测试"],
        weak_keywords=["浏览器", "browser", "网页", "website", "web", "网址", "form", "click"],
        covered_by=["toolkit_browser_tab", "toolkit_js_fetch", "toolkit_screen_read",
                    "toolkit_input", "toolkit_screenshot", "toolkit_ocr"],
    ),
    "ai-elements": SkillDomain(
        strong_keywords=["聊天界面组件", "chat ui", "shadcn", "消息组件", "对话组件"],
        weak_keywords=["界面", "组件", "ui", "前端", "frontend", "聊天界面", "聊天框"],
        covered_by=["toolkit_save_file", "toolkit_file", "toolkit_exec"],
    ),
    "analyze-pdf": SkillDomain(
        strong_keywords=["pdf 报表", "pdf 提取", "报表提取", "表格提取", "提取表格", "pdf 分析"],
        weak_keywords=["pdf", "报表", "图表", "表格", "报告"],
        covered_by=["toolkit_ocr", "toolkit_exec", "toolkit_file"],
    ),
    "autoresearch": SkillDomain(
        strong_keywords=["自主迭代", "autoresearch", "迭代实验", "指标优化循环", "自动实验"],
        weak_keywords=["迭代", "实验", "指标", "优化循环", "自动研究", "调参"],
        covered_by=["toolkit_exec", "toolkit_run_tests", "toolkit_file"],
    ),
    "browser-trace": SkillDomain(
        strong_keywords=["浏览器追踪", "browser trace", "devtools", "cdp", "调试失败用例"],
        weak_keywords=["追踪", "trace", "调试浏览器", "dom 转储"],
        covered_by=["toolkit_browser_tab", "toolkit_screenshot", "toolkit_screen_read"],
    ),
    "caveman": SkillDomain(
        strong_keywords=["省 token", "省token", "原始人模式", "caveman", "极简回复", "压缩回复"],
        weak_keywords=["简短回答", "少说废话", "简洁一点", "别啰嗦", "精简"],
        covered_by=[],
    ),
    "codebase-design": SkillDomain(
        strong_keywords=["模块设计", "接口设计", "架构设计", "代码设计词汇", "可测试设计"],
        weak_keywords=["设计", "架构", "模块", "接口", "重构设计", "代码组织"],
        covered_by=["toolkit_explr", "toolkit_lsp", "toolkit_code_review"],
    ),
    "debug-incident": SkillDomain(
        strong_keywords=["生产事故", "根因分析", "事故排查", "incident", "崩溃排查", "线上故障"],
        weak_keywords=["调试", "debug", "根因", "崩溃", "错误分析", "日志分析", "故障"],
        covered_by=["toolkit_exec", "toolkit_lsp", "toolkit_search", "toolkit_code_review"],
    ),
    "manage-docker": SkillDomain(
        strong_keywords=["dockerfile 优化", "镜像瘦身", "docker 构建", "容器化部署", "镜像优化"],
        weak_keywords=["docker", "镜像", "容器", "container", "image"],
        covered_by=["toolkit_exec", "toolkit_file", "toolkit_pkg"],
    ),
    "manage-monorepo": SkillDomain(
        strong_keywords=["monorepo 依赖", "多仓同步", "workspace 冲突", "依赖版本同步"],
        weak_keywords=["monorepo", "多仓", "workspace", "依赖同步", "依赖管理"],
        covered_by=["toolkit_exec", "toolkit_file", "toolkit_search"],
    ),
    "optimize-sql": SkillDomain(
        strong_keywords=["慢查询", "sql 优化", "索引优化", "sql 重写", "查询性能"],
        weak_keywords=["sql", "查询", "索引", "数据库", "database", "query"],
        covered_by=["toolkit_exec", "toolkit_file"],
    ),
    "output-format-constraint": SkillDomain(
        # 小模型专用 — 由 is_small_model 自动触发，评估器跳过
        strong_keywords=["小模型输出规范", "output-format-constraint"],
        weak_keywords=[],
        covered_by=[],
    ),
    "process-excel": SkillDomain(
        strong_keywords=["excel 清洗", "合并单元格", "多表合并", "excel 报表", "数据清洗 excel"],
        weak_keywords=["excel", "表格", "xlsx", "csv", "数据清洗", "电子表格", "sku"],
        covered_by=["toolkit_exec", "toolkit_file", "toolkit_pkg"],
    ),
    "test-api-endpoints": SkillDomain(
        strong_keywords=["接口测试", "api 测试", "endpoint 测试", "rest api 验证", "401", "500"],
        weak_keywords=["api", "接口", "rest", "endpoint", "请求测试", "postman"],
        covered_by=["toolkit_exec", "toolkit_js_fetch"],
    ),
    "validate-etl": SkillDomain(
        strong_keywords=["etl 校验", "数据管道校验", "数据质量检查", "脏数据拦截"],
        weak_keywords=["etl", "数据管道", "数据质量", "校验", "pipeline"],
        covered_by=["toolkit_exec", "toolkit_file"],
    ),
    "write-better-commits": SkillDomain(
        strong_keywords=["提交信息优化", "commit message", "规范提交", "写提交信息"],
        weak_keywords=["提交", "commit", "git 提交", "changelog"],
        covered_by=["toolkit_git_commit", "toolkit_git_push_all_remotes"],
    ),
    "writing-style": SkillDomain(
        strong_keywords=["写作风格", "语气调整", "风格模板", "文风", "文章风格"],
        weak_keywords=["写作", "风格", "语气", "文章", "文案", "tone"],
        covered_by=[],
    ),
}


class SkillLoadEvaluator:
    """Skill 按需加载评估器。"""

    def __init__(
        self,
        skills_dir: str | None = None,
        necessity_threshold: float = NECESSITY_THRESHOLD,
        sufficiency_threshold: float = SUFFICIENCY_THRESHOLD,
    ):
        """
        Args:
            skills_dir: skills 目录，默认 tea_agent/skills/
            necessity_threshold: 必要性阈值
            sufficiency_threshold: 充分性阈值
        """
        self.skills_dir = Path(skills_dir or _DEFAULT_SKILLS_DIR)
        self.necessity_threshold = necessity_threshold
        self.sufficiency_threshold = sufficiency_threshold
        self._scan_cache: list[dict] | None = None
        self._scan_cache_time: float = 0.0
        self._content_cache: dict[str, str] = {}

    # ── 扫描 ──

    def scan(self, force: bool = False) -> list[dict]:
        """扫描 skills 目录，返回 skill 元数据列表。

        Returns:
            [{name, description, path, has_validate}] 列表
        """
        now = __import__("time").time()
        if not force and self._scan_cache and (now - self._scan_cache_time) < SCAN_CACHE_TTL:
            return self._scan_cache

        items: list[dict] = []
        if not self.skills_dir.is_dir():
            logger.debug(f"skills 目录不存在: {self.skills_dir}")
            self._scan_cache, self._scan_cache_time = items, now
            return items

        for d in sorted(self.skills_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("__"):
                continue
            md_file = d / "SKILL.md"
            if not md_file.is_file():
                continue
            meta = self._parse_front_matter(md_file)
            if meta is None:
                meta = {}
            # 统一用目录名作为 skill 标识（front matter 的 name 可能不同，如 writing-style-skill）
            meta["display_name"] = meta.pop("name", d.name) if "name" in meta else d.name
            meta["name"] = d.name
            meta["path"] = str(md_file)
            items.append(meta)

        self._scan_cache, self._scan_cache_time = items, now
        return items

    @staticmethod
    def _parse_front_matter(path: Path) -> dict | None:
        """解析 SKILL.md 的 YAML front matter（简化版，只取 name/description/hidden）。"""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if not text.startswith("---"):
            return None
        end = text.find("\n---", 3)
        if end < 0:
            return None
        block = text[3:end]
        meta: dict[str, Any] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key in ("name", "description"):
                meta[key] = value
            elif key == "hidden":
                meta[key] = value.lower() == "true"
        return meta

    # ── 评估 ──

    def _necessity(self, skill_name: str, dialogue_text: str) -> float:
        """计算必要性：对话文本对 skill 关键词的加权命中率。"""
        domain = SKILL_DOMAINS.get(skill_name)
        if domain is None:
            return 0.0
        text_lower = dialogue_text.lower()
        hits = 0.0
        for kw in domain.strong_keywords:
            if kw.lower() in text_lower:
                hits += 2
        for kw in domain.weak_keywords:
            if kw.lower() in text_lower:
                hits += 1
        # 1 个强词或 2 个弱词命中即视为高度相关（除以 4 个权重单位）
        return min(1.0, hits / 4.0)

    def _sufficiency(self, skill_name: str, available_tools: set[str]) -> float:
        """计算充分性：现有工具对 skill 领域的覆盖比例。"""
        domain = SKILL_DOMAINS.get(skill_name)
        if domain is None or not domain.covered_by:
            return 0.0
        covered = sum(1 for t in domain.covered_by if t in available_tools)
        return covered / len(domain.covered_by)

    def evaluate(
        self,
        dialogue_text: str,
        available_tools: set[str] | None = None,
    ) -> list[SkillDecision]:
        """评估所有 skill，返回决策列表（按必要性降序）。

        Args:
            dialogue_text: 评估证据文本（最近几轮用户消息拼接）
            available_tools: 当前可用工具名集合；None 视为空集（充分性=0）

        Returns:
            决策列表，已按必要性降序排序
        """
        tools = available_tools or set()
        decisions: list[SkillDecision] = []
        for meta in self.scan():
            name = meta["name"]
            if name == "output-format-constraint":
                # 小模型专用，由 is_small_model 自动触发，不参与评估
                continue
            necessity = self._necessity(name, dialogue_text)
            sufficiency = self._sufficiency(name, tools)
            if necessity >= self.necessity_threshold and sufficiency < self.sufficiency_threshold:
                decisions.append(SkillDecision(
                    name=name, necessity=necessity, sufficiency=sufficiency,
                    action="load", reason="load",
                ))
            elif necessity >= self.necessity_threshold:
                decisions.append(SkillDecision(
                    name=name, necessity=necessity, sufficiency=sufficiency,
                    action="no_load", reason="already_covered",
                ))
            else:
                decisions.append(SkillDecision(
                    name=name, necessity=necessity, sufficiency=sufficiency,
                    action="no_load", reason="irrelevant",
                ))
        decisions.sort(key=lambda d: d.necessity, reverse=True)
        return decisions

    def load_skill_content(self, name: str, max_chars: int = MAX_INJECT_CHARS) -> str | None:
        """读取 SKILL.md 全文（带缓存 + 长度截断）。

        Returns:
            SKILL.md 内容（截断到 max_chars），失败返回 None
        """
        if name in self._content_cache:
            return self._content_cache[name]
        path = self.skills_dir / name / "SKILL.md"
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning(f"读取 SKILL.md 失败 {path}: {e}")
            return None
        if len(text) > max_chars:
            text = text[:max_chars] + "\n…(已按预算截断)"
        self._content_cache[name] = text
        return text

    # ── 一站式：供 history_builder 调用 ──

    def evaluate_and_load(self, context: Any) -> str | None:
        """根据会话上下文评估并按需加载 skill。

        Args:
            context: SessionContext（需含 messages；可选 toolkit）

        Returns:
            需要注入 system prompt 的 SKILL.md 文本（多个 skill 拼接），
            无需加载或证据不足返回 None。
        """
        evidence = self._collect_evidence(context)
        if evidence is None:
            return None

        tools = self._collect_tools(context)
        decisions = self.evaluate(evidence, tools)

        # 已加载的 skill（记录在 context，避免重复注入）
        loaded: set[str] = set(getattr(context, "_skill_loaded", None) or set())
        parts: list[str] = []
        count = 0
        for dec in decisions:
            if dec.action != "load" or count >= MAX_LOAD_PER_ROUND:
                continue
            if dec.name in loaded:
                continue
            content = self.load_skill_content(dec.name)
            if not content:
                continue
            parts.append(
                f"<loaded_skill name=\"{dec.name}\" "
                f"necessity={dec.necessity:.0%} sufficiency={dec.sufficiency:.0%}>\n"
                f"{content}\n</loaded_skill>"
            )
            loaded.add(dec.name)
            count += 1
            logger.info(f"🎯 按需加载 skill: {dec.name} "
                        f"(necessity={dec.necessity:.0%}, sufficiency={dec.sufficiency:.0%})")

        if loaded:
            context._skill_loaded = loaded

        return "\n\n".join(parts) if parts else None

    @staticmethod
    def _collect_evidence(context: Any) -> str | None:
        """收集最近 EVIDENCE_ROUNDS 轮用户消息作为评估证据。"""
        messages = getattr(context, "messages", None) or []
        user_msgs: list[str] = []
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content if p.get("type") == "text"
                )
            content = str(content).strip()
            if content:
                user_msgs.append(content)
            if len(user_msgs) >= EVIDENCE_ROUNDS:
                break
        if len(user_msgs) < MIN_EVIDENCE_ROUNDS:
            return None
        return "\n".join(reversed(user_msgs))

    @staticmethod
    def _collect_tools(context: Any) -> set[str]:
        """从 context.toolkit 收集可用工具名。"""
        toolkit = getattr(context, "toolkit", None)
        if toolkit is None:
            return set()
        for attr in ("func_map", "_tools", "tools"):
            obj = getattr(toolkit, attr, None)
            if isinstance(obj, dict):
                return set(obj.keys())
        # 尝试 get_all_tools 方法
        getter = getattr(toolkit, "get_all_tools", None)
        if callable(getter):
            try:
                result = getter()
                if isinstance(result, dict):
                    return set(result.keys())
            except Exception as e:
                logger.debug(f"获取工具列表失败: {e}")
        return set()


# ═══ 模块级单例 ═══

_evaluator: SkillLoadEvaluator | None = None


def get_evaluator() -> SkillLoadEvaluator:
    """获取全局评估器单例。"""
    global _evaluator
    if _evaluator is None:
        _evaluator = SkillLoadEvaluator()
    return _evaluator


def evaluate_and_load(context: Any) -> str | None:
    """按需加载 skill 的便捷入口（供 history_builder 调用）。

    Args:
        context: SessionContext

    Returns:
        需注入的 SKILL.md 文本，或 None
    """
    return get_evaluator().evaluate_and_load(context)


def clear_cache() -> None:
    """清空扫描与内容缓存（测试用 / 技能变更后调用）。"""
    global _evaluator
    if _evaluator is not None:
        _evaluator._scan_cache = None
        _evaluator._content_cache.clear()

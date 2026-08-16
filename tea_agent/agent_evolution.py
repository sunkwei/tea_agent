"""
自进化流水线 — 事件驱动的 Trigger → Analyze → Act 闭环。

设计原则：
- Trigger: 轻量信号采集，不调 LLM，在每次工具调用后同步执行
- Analyze: 会话结束时串行调一次廉价 LLM，产出行动建议
- Act: 调用已有 toolkit_* 工具执行进化
- 不自建循环，不搞后台线程，不阻塞主交互流程
"""

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("agent.evolution")

# 进化日志：可用环境变量 TEA_AGENT_EVOLUTION_LOG 覆盖路径（测试/自定义用）
_EVOLUTION_LOG_DEFAULT = os.path.join(
    os.path.expanduser("~"), ".tea_agent", "evolution_log.json")
_EVOLUTION_LOG_MAX = 100  # 日志保留条数上限


def _evolution_log_path() -> str:
    return os.environ.get("TEA_AGENT_EVOLUTION_LOG", _EVOLUTION_LOG_DEFAULT)


def _load_evolution_log() -> list[dict]:
    path = _evolution_log_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _append_evolution_log(entry: dict) -> None:
    """追加一条进化记录（带保留条数上限裁剪），失败抛异常交给调用方。"""
    path = _evolution_log_path()
    log = _load_evolution_log()
    log.append(entry)
    log = log[-_EVOLUTION_LOG_MAX:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def _prune_evolution_log(keep: int) -> dict:
    """裁剪进化日志到最近 keep 条。keep<=0 或 keep>=len 时不做删除。"""
    log = _load_evolution_log()
    if not log:
        return {"ok": True, "pruned": 0, "detail": "进化日志为空"}
    keep = max(0, keep or 0)
    if keep >= len(log) or keep == 0:
        return {"ok": True, "pruned": 0, "detail": f"无需裁剪 ({len(log)} 条)"}
    trimmed = log[-keep:]
    path = _evolution_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2, ensure_ascii=False)
    return {"ok": True, "pruned": len(log) - keep, "detail": f"裁到最近 {keep} 条"}


def _rmtree(path: str) -> None:
    """递归删除目录（跨平台）。"""
    import shutil
    shutil.rmtree(path)


# ═══════════════════════════════════════════════════════════════
#  Trigger — 轻量信号采集
# ═══════════════════════════════════════════════════════════════

class EvolutionTrigger:
    """自进化触发器 — 采集工具调用信号，不调 LLM。

    用法：在每次 Toolkit.call_tool() 返回后调用 on_tool_result()。
    """

    def __init__(self, max_log: int = 50, consecutive_failure_threshold: int = 3):
        self.tool_call_log: list[dict] = []
        self.evolution_events: list[dict] = []
        self.max_log = max_log
        # 连续失败阈值：同一工具连续 N 次失败触发事件
        self.consecutive_failure_threshold = consecutive_failure_threshold

    def on_tool_result(self, tool_name: str, result: Any, duration: float):
        """每次工具调用后采集信号。"""
        ok = True
        error = ""
        if isinstance(result, dict):
            ok = result.get("ok", True)
            error = result.get("error", "") or result.get("stderr", "") or ""
        elif isinstance(result, tuple) and len(result) >= 2:
            ok = result[0] == 0
            error = str(result[-1]) if not ok else ""

        entry = {
            "tool": tool_name,
            "ok": ok,
            "error": error[:200],
            "duration": duration,
            "ts": time.time(),
        }
        self.tool_call_log.append(entry)
        if len(self.tool_call_log) > self.max_log:
            self.tool_call_log.pop(0)

        if ok:
            return

        recent = [e for e in self.tool_call_log if e["tool"] == tool_name][-self.consecutive_failure_threshold:]
        if len(recent) >= self.consecutive_failure_threshold and all(not e["ok"] for e in recent):
            self.evolution_events.append({
                "type": "tool_failure",
                "tool": tool_name,
                "recent_errors": [e["error"] for e in recent],
                "count": len(recent),
                "ts": time.time(),
            })
            logger.info(f"evolution: 检测到 {tool_name} 连续 {self.consecutive_failure_threshold} 次失败")

    def get_pending_events(self) -> list[dict]:
        return self.evolution_events

    def clear_events(self):
        self.evolution_events.clear()


# ═══════════════════════════════════════════════════════════════
#  Analyze — 用廉价 LLM 分析信号，产出行动建议
# ═══════════════════════════════════════════════════════════════

class EvolutionAnalyzer:
    """进化分析器 — 会话结束后分析信号，输出行动建议。"""

    ANALYZE_PROMPT = """你是一个 Agent 自进化分析器。分析以下进化信号和记忆上下文，输出 JSON 行动建议。

进化信号：{events_json}
记忆上下文：{memory_summary}

可能的行动类型：
- evolve_code: 修复高频报错的工具代码。target 填工具文件路径，reason 说明修复方向
- evolve_prompt: 优化系统提示词。target 填 "system_prompt"，reason 填优化建议
- solidify: 记录成功模式为技能。target 填技能名，reason 填任务描述
- create_tool: 出现反复无法满足的能力缺口时，自主生成新工具。target 填 "auto"，reason 填能力缺口描述（如「需要工具解析 XML」）
- prune: 清理废弃/超龄的自进化产物。target 填 "skills" 或 "evolution_log"，reason 填 keep=N（保留份数，默认 3）
- none: 无需行动

可选评估字段（rubric）：若行动可量化评估（如 evolve_code），可附加 rubric 规则列表，
系统会用它执行"改进前评分→改进→改进后重评→仅分数提升才保留"的闭环。
rubric 格式（规则项支持 match: regex/contains/line/line_contains）：
[{"pattern": "...", "match": "regex", "description": "检查点说明"}]
示例：检查代码包含函数签名和文档字符串、避免硬编码路径等。
不提供 rubric 则跳过评估，保持原流程。

返回格式：
{{"actions": [{{"action": "evolve_code", "target": "tea_agent/toolkit/toolkit_xxx.py", "reason": "...", "rubric": [], "threshold": 0.0}}]}}

只输出 JSON，不要额外说明。"""

    def __init__(self, cheap_client=None, cheap_model: str = ""):
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model or "gpt-4o-mini"

    def analyze(self, events: list[dict], memory_summary: str = "") -> list[dict]:
        """分析信号 → 输出行动建议列表。"""
        if not events:
            return []
        if not self._cheap_client:
            return []

        try:
            from tea_agent.api_retry import call_with_retry

            prompt = self.ANALYZE_PROMPT.format(
                events_json=json.dumps(events, ensure_ascii=False),
                memory_summary=memory_summary or "(无)",
            )
            resp = call_with_retry(
                self._cheap_client.chat.completions.create,
                model=self._cheap_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            data = json.loads(content)
            actions = data.get("actions", [])
            logger.info(f"evolution: 分析完成，建议 {len(actions)} 个行动: {[a.get('action') for a in actions]}")
            return actions
        except Exception as e:
            logger.warning(f"evolution: 分析失败: {e}")
            return []


# ═══════════════════════════════════════════════════════════════
#  Act — 执行进化行动
# ═══════════════════════════════════════════════════════════════

class EvolutionActor:
    """进化执行器 — 调用已有 toolkit_* 工具执行分析建议。

    evolve_code 用廉价 LLM 生成修复后的新代码，经 toolkit_self_evolve 的
    5 层安全护栏（git 快照 → .bak → 语法 → 编译 → LSP → 测试）执行，
    把「AI 写 AI」真正闭环：缺了 LLM 就保守跳过，绝不提交占位符。
    """

    def __init__(self, toolkit, cheap_client=None, cheap_model: str = ""):
        self.tk = toolkit
        self._cheap_client = cheap_client
        self._cheap_model = cheap_model or "gpt-4o-mini"

    def execute(self, actions: list[dict]) -> list[dict]:
        """执行行动列表，返回执行结果。"""
        results = []
        for act in actions:
            action_type = act.get("action", "none")
            target = act.get("target", "")
            reason = act.get("reason", "")

            if action_type == "none" or not action_type:
                continue

            try:
                result = self._execute_one(action_type, target, reason)
                ok = bool(result.get("ok", False))
            except Exception as e:
                result = {"ok": False, "error": str(e)}
                ok = False
                logger.warning(f"evolution: 执行 {action_type} 失败: {e}")
            # B: 记录每次进化行动到持久化日志（可审查）
            self._record_evolution({
                "timestamp": time.time(),
                "action": action_type,
                "target": target,
                "reason": reason[:120],
                "ok": ok,
                "error": result.get("error", "")[:200],
                "detail": result.get("detail", ""),
                "decision": result.get("decision", ""),
                "delta": result.get("delta"),
            })
            results.append({"action": action_type, "target": target, "ok": ok,
                            "error": result.get("error", "")[:200]})
            logger.info(f"evolution: 执行 {action_type} -> {target}: ok={ok}")

        return results

    def _execute_one(self, action_type: str, target: str, reason: str) -> dict:
        if action_type == "evolve_code":
            return self._evolve_code(target, reason)
        elif action_type == "evolve_prompt":
            return self._evolve_prompt(reason)
        elif action_type == "solidify":
            return self._solidify(reason)
        elif action_type == "create_tool":
            return self._create_tool(reason)
        elif action_type == "prune":
            return self._prune(target, reason)
        return {"ok": False, "error": f"unknown_action:{action_type}"}

    # ── LLM 修代码 — 生成修复后的新代码全文 ──
    EVOLVE_PROMPT = """你是一个自进化 Agent 修码器。下面是一个工具源的当前全文，它被报告反复失败。
请修复根本问题，输出**修复后的完整新文件内容**（保持其余代码不变，仅做必要修改）。

当前文件 {file_path}：
```python
{content}
```

修复目标：{reason}

要求：
- 只输出新文件的 Python 代码全文，不要 Markdown 围栏，不要任何解释。
- 保持原有函数签名、参数名、返回结构不变（避免破坏调用方）。
- 若 {file_path} 不是 .py 文件，或无法确定修复点，输出原样内容。"""

    def _generate_new_code(self, file_path: str, content: str, reason: str) -> str | None:
        """用廉价 LLM 生成修复后的完整文件内容；不可用/失败返回 None。"""
        if not self._cheap_client:
            return None
        try:
            from tea_agent.api_retry import call_with_retry

            prompt = self.EVOLVE_PROMPT.format(file_path=file_path, content=content, reason=reason)
            resp = call_with_retry(
                self._cheap_client.chat.completions.create,
                model=self._cheap_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            new_code = resp.choices[0].message.content
            if not new_code or not new_code.strip():
                logger.warning(f"evolution: LLM 未返回修复代码 for {file_path}")
                return None
            # 去掉可能的 Markdown 围栏
            lines = new_code.strip().splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"evolution: LLM 生成修复代码失败 {file_path}: {e}")
            return None

    def _evolve_code(self, file_path: str, reason: str) -> dict:
        """修复工具代码 — LLM 生成新代码 + toolkit_self_evolve 5 层护栏。

        从文件全文 diff：把旧全文替换为新全文交给 self_evolve 的护栏执行，
        直到满足最小变化量（绝不提交含义不变的占位符）。
        """
        if not self.tk or "toolkit_self_evolve" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_self_evolve 不可用"}
        try:
            content = self.tk.call_tool("toolkit_file", action="read", filename=file_path)
        except Exception:
            content = ""
        if not isinstance(content, str) or not content.strip():
            return {"ok": False, "error": f"读取文件失败或内容为空: {file_path}"}
        if content.startswith("Error:") or content.startswith("❌"):
            return {"ok": False, "error": f"读取文件失败: {content[:200]}"}

        # 缺 LLM → 保守跳过，绝不提交占位符（HTML 注释非合法 Python）
        if not self._cheap_client:
            return {"ok": False, "error": "evolve_code 需要 cheap LLM 生成 new_code，当前无客户端，已跳过"}

        new_code = self._generate_new_code(file_path, content, reason)
        if not new_code or new_code.strip() == content.strip():
            return {"ok": False, "error": "LLM 未产出有效变更，已跳过（避免无效自改）"}

        return self.tk.call_tool(
            "toolkit_self_evolve",
            file_path=file_path,
            description=f"self-evolve: {reason}",
            old_code=content,
            new_code=new_code,
            run_tests=True,
            symbol=None,
            lsp_checks=True,
        )

    def _evolve_prompt(self, suggestion: str) -> dict:
        """优化提示词 — 委托给 toolkit_prompt_evolve。"""
        if not self.tk or "toolkit_prompt_evolve" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_prompt_evolve 不可用"}
        return self.tk.call_tool("toolkit_prompt_evolve",
            action="evolve",
        )

    def _solidify(self, task: str) -> dict:
        """固化经验 — 委托给 toolkit_experience_solidify。"""
        if not self.tk or "toolkit_experience_solidify" not in self.tk.func_map:
            return {"ok": False, "error": "toolkit_experience_solidify 不可用"}
        return self.tk.call_tool("toolkit_experience_solidify",
            action="auto",
            task=task,
            success=True,
        )

    # ── A: 自主造工具 — 缺能力缺口 → LLM 生成新工具 → 验证 → 注册 ──
    CREATE_TOOL_PROMPT = """你是一个自进化 Agent 的造工具器。当前有未满足的能力缺口，请生成一个新的 toolkit 工具。
缺能力缺口：{gap}

输出 **JSON**，schema：
{{
  "name": "toolkit_<snake_case动作名>",
  "description": "一句话工具说明",
  "properties": {{ "参数名": {{"type": "string", "description": "说明"}} }},
  "required": ["参数名"],
  "pycode": "完整可运行的工具函数源码"
}}

要求：
- name 以 toolkit_ 前缀，小写下划线
- pycode 是一个纯 Python 文件，内含 `def toolkit_<名>(...)` 函数返回结构化 dict
  （成功 {"ok": true, ...}，失败 {"ok": false, "error": "..."}），以及 `def meta_toolkit_<名>()` 注册函数
- 不准 import 外部非标准可执行文件；参数用 JSON Schema 描述
- 只输出 JSON 本身，不要 Markdown 围栏，不要解释"""

    def _create_tool(self, capability_gap: str) -> dict:
        """自主造工具闭环：LLM 生成新工具源码 + meta → toolkit.save 落盘注册。

        验证护栏：ast.parse 语法校验 → save（含 meta 校验/写入/注册）。
        缺 LLM 或解析失败则保守跳过，绝不污染工具目录。
        """
        if not self._cheap_client or not self.tk:
            return {"ok": False, "error": "create_tool 需要 cheap LLM 与 toolkit"}
        if not capability_gap:
            return {"ok": False, "error": "缺少能力缺口描述"}
        # toolkit.save 是否可用（动态注册通道）
        if not hasattr(self.tk, "save"):
            return {"ok": False, "error": "toolkit 无 save 方法，无法造工具"}

        try:
            import ast as _ast
            import json as _json

            from tea_agent.api_retry import call_with_retry

            prompt = self.CREATE_TOOL_PROMPT.replace("{gap}", capability_gap)
            resp = call_with_retry(
                self._cheap_client.chat.completions.create,
                model=self._cheap_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            text = resp.choices[0].message.content
            if not text:
                return {"ok": False, "error": "LLM 未返回工具定义"}
            # 去掉可能的围栏
            t = text.strip()
            if t.startswith("```"):
                t = t.split("\n", 1)[1] if "\n" in t else t
                if t.rstrip().endswith("```"):
                    t = t.rstrip()[:-3]
            data = _json.loads(t)
        except Exception as e:
            return {"ok": False, "error": f"create_tool 生成/解析失败: {e}"}

        name = str(data.get("name", "")).strip()
        pycode = str(data.get("pycode", "")).strip()
        desc = str(data.get("description", "")).strip()
        if not name.startswith("toolkit_") or not name.isidentifier():
            return {"ok": False, "error": f"非法工具名: {name!r}"}
        if not pycode:
            return {"ok": False, "error": "LLM 未生成 pycode"}

        # Layer 1.5: 语法校验（复用 self_evolve 的严格校验思路）
        try:
            _ast.parse(pycode)
        except SyntaxError as e:
            return {"ok": False, "error": f"新工具语法错误: {e.msg} (L{e.lineno})"}

        # 组装 meta（JSON Schema）
        props = data.get("properties") if isinstance(data.get("properties"), dict) else {}
        req = data.get("required") if isinstance(data.get("required"), list) else []
        meta = {
            "type": "function",
            "function": {
                "name": name,
                "description": desc or f"由自进化生成的工具：{capability_gap[:60]}",
                "parameters": {
                    "type": "object",
                    "properties": props or {},
                    "required": req,
                },
            },
        }

        try:
            code, msg = self.tk.save(name, meta, pycode)
            if code != 0:
                return {"ok": False, "error": f"toolkit.save 失败 ({code}): {msg}"}
        except Exception as e:
            return {"ok": False, "error": f"toolkit.save 异常: {e}"}

        return {"ok": True, "tool": name, "message": f"新工具已创建并注册: {name}"}

    # ── C: 自进化修剪 — 清理废弃/超龄的自进化产物 ──
    def _prune(self, target: str, reason: str) -> dict:
        """运行时修剪：清理长期不用的自进化产物。

        目标：
        - "skills": 清理 user 技能目录里超龄的自动打断技能（interrupt-avoid-*）
                  与空目录，保留最近 keep 份（默认 3）
        - "evolution_log": 清理进化日志超出保留条数的旧条目（默认保留 100）
        - 其它 target：不删除，返回 ok（避免误删）
        """
        keep = 3
        try:
            keep = max(0, int(reason.split("keep=")[1].split()[0])) if "keep=" in reason else keep  # type: ignore[union-attr]
        except Exception:
            keep = 3

        if target == "skills":
            return self._prune_skills(keep, reason)
        elif target == "evolution_log":
            return _prune_evolution_log(keep)
        return {"ok": True, "pruned": 0, "detail": f"target={target} 无需修剪"}

    def _prune_skills(self, keep: int, reason: str) -> dict:
        """删除用户技能目录 `~/.tea_agent/skills/` 中由打断闭环自动生成的
        `interrupt-avoid-*` 技能（超龄），并清理空目录。

        幂等安全：仅删自动生成的前缀目录，不碰人工/历史 SKILL.md，
        不删未匹配目录。可用 TEA_AGENT_SKILLS_DIR 覆盖目录（测试/自定义）。
        """
        import os

        skills_dir = os.environ.get(
            "TEA_AGENT_SKILLS_DIR",
            os.path.join(os.path.expanduser("~"), ".tea_agent", "skills"))
        if not os.path.isdir(skills_dir):
            return {"ok": True, "pruned": 0, "detail": "技能目录不存在"}
        removed = 0
        removed_names = []
        try:
            auto_dirs = sorted(
                d for d in os.listdir(skills_dir)
                if d.startswith("interrupt-avoid-")
                and os.path.isdir(os.path.join(skills_dir, d)))
            if not auto_dirs:
                return {"ok": True, "pruned": 0, "detail": "无自动打断技能"}
            # 保留最近 keep 个（按名字序 = 创建序近似），删除更早的
            for old in auto_dirs[:-keep] if len(auto_dirs) > keep else []:
                target = os.path.join(skills_dir, old)
                try:
                    _rmtree(target)
                    removed += 1
                    removed_names.append(old)
                except OSError:
                    logger.debug(f"prune: 删除技能失败 {old}")
            # 清理空目录
            for d in os.listdir(skills_dir):
                full = os.path.join(skills_dir, d)
                if os.path.isdir(full) and not os.listdir(full):
                    try:
                        os.rmdir(full)
                    except OSError:
                        pass
        except Exception as e:
            return {"ok": False, "error": f"prune_skills 失败: {e}"}
        return {"ok": True, "pruned": removed, "removed": removed_names,
                "detail": f"清理自动打断技能保留最近 {keep} 份"}

    # ── B: 进化可观测 — 结构化记录每次进化行动 ──
    def _record_evolution(self, entry: dict) -> dict:
        """把一次进化行动写入持久化进化日志（B 数据层）。

        写 ~/.tea_agent/evolution_log.json（追加，附带保留条数上限）。
        失败仅记日志，不影响主流程。
        """
        try:
            _append_evolution_log(entry)
            return {"ok": True}
        except Exception as e:
            logger.warning(f"evolution: 记录日志失败: {e}")
            return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  Evaluate — 评分闭环（借鉴 PenguinHarness self-evolve 机制）
# ═══════════════════════════════════════════════════════════════

class EvolutionEvaluator:
    """进化评估器 — 在 Analyze → Act 之间插入 Evaluate 阶段。

    借鉴 penguin-harness examples/self-improving-agent/self-evolve.ts：
    改进前打基线分 → 执行改进 → 改进后重评 → 平均分提升才保留，否则回滚。

    设计原则：
    - 可选参与：仅当 Analyze 输出的 action 带 rubric 规则时才启用，
      无 rubric 的流程行为完全不变（向后兼容）
    - 轻量确定性：委托 toolkit_eval_loop（纯代码评分，无 LLM 参与）
    - 决策：compare 返回 keep / rollback / no_change；rollback 用 git 恢复
    """

    def __init__(self, toolkit):
        self.tk = toolkit

    def available(self) -> bool:
        """toolkit_eval_loop 是否已注册可用。"""
        return bool(self.tk and "toolkit_eval_loop" in self.tk.func_map)

    def _call_eval_loop(self, **kwargs) -> dict | None:
        """调用 toolkit_eval_loop，失败返回 None（不阻断主流程）。"""
        if not self.available():
            return None
        try:
            return self.tk.call_tool("toolkit_eval_loop", **kwargs)
        except Exception as e:
            logger.warning(f"evolution: evaluate 调用失败: {e}")
            return None

    def extract_eval_actions(self, actions: list[dict]) -> list[dict]:
        """从行动列表中提取带 rubric 的可评估行动（有 target + rubric）。"""
        return [
            a for a in actions
            if a.get("action") not in ("none", "") and a.get("target") and a.get("rubric")
        ]

    def evaluate_target(self, target: str, rules, runs: int = 3) -> dict | None:
        """读取目标文件内容并用 rubric 评分（改进前后通用）。

        runs 轮文本重复取平均（对抗评分抖动）；实际改进前后各读一次文件。
        """
        try:
            with open(target, encoding="utf-8") as f:
                artifact = f.read()
        except Exception as e:
            logger.warning(f"evolution: 读取评估目标失败 {target}: {e}")
            return None
        return self._call_eval_loop(action="evaluate", texts=[artifact] * runs, rules=rules)

    def decide(self, baseline: dict | None, candidate: dict | None, threshold: float = 0.0) -> dict:
        """keep-or-rollback 决策。基线/候选不可用时保守返回 no_change。"""
        if not baseline or not candidate or not baseline.get("ok") or not candidate.get("ok"):
            return {"ok": False, "decision": "no_change", "verdict": "评估数据不可用，保持现状"}
        r = self._call_eval_loop(
            action="compare",
            baseline={"mean_score": baseline.get("mean_score", 0.0)},
            candidate={"mean_score": candidate.get("mean_score", 0.0)},
            threshold=threshold,
        )
        return r or {"ok": False, "decision": "no_change", "verdict": "决策调用失败，保持现状"}

    def rollback(self, target: str) -> bool:
        """回滚目标文件到改进前（git checkout）。优先当前目录，失败则尝试目标目录。"""
        try:
            import subprocess
            r = subprocess.run(
                ["git", "checkout", "--", target],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                import os
                d = os.path.dirname(os.path.abspath(target))
                r = subprocess.run(
                    ["git", "checkout", "--", os.path.basename(target)],
                    capture_output=True, text=True, timeout=30, cwd=d,
                )
            return r.returncode == 0
        except Exception as e:
            logger.warning(f"evolution: 回滚失败 {target}: {e}")
            return False

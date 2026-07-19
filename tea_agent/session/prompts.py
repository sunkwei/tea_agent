"""
@2026-07-07 gen by tea_agent, 会话 Prompt 模板常量
从 onlinesession.py 提取

扩展：
  SMALL_MODEL_CONSTRAINT — 小模型输出规范模板，自动注入 system prompt。
  _is_small_model() — 根据模型名判断是否为小模型。
  _get_skill_validate_rules() — 解析 SKILL.md 的 validate: 字段。
"""

import re
from pathlib import Path

# ── 历史摘要 Prompt ──

HISTORY_SUMMARIZE_SYSTEM = (
    "将对话压缩为摘要，保留关键信息（决策、结论、事实、用户需求），"
    "忽略寒暄和过程细节。200字以内。"
)

HISTORY_SUMMARIZE_USER = (
    "{existing}新增对话内容：\n{old_text}\n\n"
    "请输出合并后的精炼摘要（200字以内）："
)

# ── Topic 摘要 Prompt ──

TOPIC_SUMMARY_SYSTEM = (
    "你是一个极简标题生成器。"
    "看一条用户消息，提炼成不超过20字的摘要标题。\n"
    "规则（严格遵守）：\n"
    "1. 禁止出现：我们、用户、您、对话、消息、上文、根据、以下、主题、这个、输入、生成\n"
    "2. 禁止描述任务：不能说'根据xxx生成'、'关于xxx的'等元描述\n"
    "3. 禁止无意义词：禁止输出'主题'，禁止只输出时间戳\n"
    "4. 直接输出标题本身，不要任何前缀、后缀、解释\n"
    "5. 控制在20字以内\n\n"
    "好的示例：'重构Session模块'、'修改标题生成规则'、'Cursor类设计讨论'\n"
    "坏的示例：'我们根据用户消息生成摘要'、'主题 06-08 20:03'、'这个项目的进展'"
)

TOPIC_SUMMARY_USER_TEMPLATE = (
    "用户最新消息：\n\n{user_msgs}\n\n"
    "直接输出不超过20字的摘要标题，禁止任何解释："
)

# ── 系统提示词 ──

COMPACT_SYSTEM_PROMPT = (
    "你是可自我扩展的智能Agent，拥有大量工具。"
    "核心工具：toolkit_exec(命令)、toolkit_file(r/w/list)、toolkit_self_evolve、"
    "toolkit_memory(记忆管理)、toolkit_kb(知识库)、toolkit_reflection(元认知)、"
    "toolkit_prompt_evolve(提示词进化)等。"
    "通过toolkit_save 保存新建新工具、toolkit_reload重载。\n\n"
    "行为准则：主动分析需求，优先专用工具，修改前备份(.bak)，关键步骤验证，"
    "减少无效迭代。所有工具调用参数严格JSON双引号格式。"
    "宽进严出——出口管线严格校验，不假定模型宽容。\n\n"
    "【Plan-first 模式】借鉴 opencode/codex 最佳实践：\n"
    "1. 对于复杂/多步骤任务（修改多个文件、重构、新功能开发），"
    "先调用 toolkit_plan 创建结构化计划，展示给用户后再执行。\n"
    "2. 计划应包含：目标、涉及文件、执行步骤、预期结果。\n"
    "3. 简单任务（单文件修改、查询信息）可直接执行，无需规划。\n"
    "4. 执行完成后调用 toolkit_experience_solidify 固化经验。"
)

# ── 小模型输出规范（自动注入 system prompt） ──

SMALL_MODEL_CONSTRAINT = (
    "【输出规范】（严格遵守）\n\n"
    "1. 每次回复必须按「分析→方案→执行」三段落组织：\n"
    "   【分析】一句话问题本质 + 关键约束 + 可能陷阱\n"
    "   【方案】最多 3 个，每行一个「- [方案名]: 一句话说明」\n"
    "   【执行】只调必要工具，调完后检查结果，达标即停\n\n"
    "2. 工具规范：\n"
    "   - 一次只调 1-2 个工具，不要一次性调 4 个以上\n"
    "   - 不要连续两次调同一工具而不检查结果\n"
    "   - 优先用 toolkit_file(read) 确认文件存在再修改\n"
    "   - 执行命令先加 --help 确认语法\n\n"
    "3. 禁止行为：\n"
    "   - ❌ 猜测不存在的文件路径\n"
    "   - ❌ 输出'根据我的分析'、'基于以上内容'等废话前缀\n"
    "   - ❌ 连续 3 次相同工具调用（会被循环检测打断）\n"
    "   - ❌ 假设命令成功而不验证\n\n"
    "4. 失败处理：\n"
    "   - 工具出错 → 换个方法重试，最多 3 次\n"
    "   - 3 次都失败 → 告知用户并建议替代方案\n"
    "   - 不要重复重试同一参数"
)

# ── 小模型识别 ──

# 匹配模式：模型名含以下关键词时视为小模型
_SMALL_MODEL_PATTERNS = [
    "1.3b", "1.5b", "2.7b", "3b", "3.8b", "4b", "7b",
    "tiny", "small", "mini", "nano", "pico",
    "phi-1", "phi-2",
    "deepseek-coder-1.3b",
    "qwen-1-", "qwen-2-",  # Qwen 系列小模型 (qwen2-0.5b/1.5b/7b)，避免误匹配 qwen-2.5
    "gemma-2b", "gemma-7b",
    "llama-2-7b", "llama-3.2-1b", "llama-3.2-3b",
    "mistral-7b",
    "starcoder",
    "codegemma-2b", "codegemma-7b",
    "codellama-7b",
    "bloom-3b", "bloom-7b",
    "mpt-7b",
    "falcon-7b",
]


def is_small_model(model_name: str) -> bool:
    """根据模型名判断是否为小模型。

    匹配规则（不区分大小写）：
      - 精确匹配 _SMALL_MODEL_PATTERNS 中的关键词
      - 匹配 "b" 结尾且数字 ≤ 13 的版本号（如 7b, 13b）

    Args:
        model_name: 模型名称字符串

    Returns:
        True=小模型，False=大模型
    """
    if not model_name:
        return False
    name_lower = model_name.lower()

    # 规则 1: 精确模式匹配
    for pattern in _SMALL_MODEL_PATTERNS:
        if pattern in name_lower:
            return True

    # 规则 2: 匹配 "Nb" 模式（N < 70 视为小模型）
    m = re.search(r'(\d+\.?\d*)b', name_lower)
    if m:
        try:
            param_count = float(m.group(1))
            if param_count < 70:
                # 70B 以下视为小模型
                return True
        except ValueError:
            pass

    return False


def get_skill_validate_rules(skill_name: str) -> dict | None:
    """解析 SKILL.md 的 validate: 字段，返回校验规则。

    在 tea_agent/skills/<skill_name>/SKILL.md 中查找

    Args:
        skill_name: 技能名称（目录名）

    Returns:
        dict 包含 validate 规则，或 None
    """
    try:
        import yaml
        # 搜索路径：包内 → 用户级 → 项目级
        search_dirs = [
            Path(__file__).parent.parent / "skills" / skill_name,
            Path.home() / ".tea_agent" / "skills" / skill_name,
            Path.cwd() / ".tea_agent" / "skills" / skill_name,
        ]
        for skill_dir in search_dirs:
            for fname in ("SKILL.md", "BRIEF.md"):
                skill_file = skill_dir / fname
                if skill_file.exists():
                    raw = skill_file.read_text(encoding="utf-8")
                    if raw.startswith("---"):
                        end_idx = raw.find("\n---\n", 3)
                        if end_idx == -1:
                            continue
                        meta = yaml.safe_load(raw[3:end_idx])
                        if isinstance(meta, dict) and "validate" in meta:
                            return meta["validate"]
    except Exception:
        pass
    return None

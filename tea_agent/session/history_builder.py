"""
历史消息构建模块

从 onlinesession.py 提取的独立功能：
- build_api_messages: 三级历史拼接 (L0系统提示 + L3摘要 + L2相关 + L1最新)
- filter_level2_by_relevance: 按语义相关性筛选 Level 2 条目
- to_multimodal: 多模态消息转换
"""

import base64
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("session.history_builder")


def estimate_tokens(text: str) -> int:
    """快速估算文本的 token 数。

    启发式算法：
    - 英文：约 4 字符 = 1 token（含空格和标点）
    - 中文：约 1.5 字 = 1 token
    - 混合文本取加权平均

    Args:
        text: 输入文本

    Returns:
        估算的 token 数
    """
    if not text:
        return 0

    # 统计中文字符数
    cn_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf]', text))
    total_chars = len(text)
    non_cn_chars = total_chars - cn_chars

    # 中文约 1.5 字/token，英文约 4 字符/token
    cn_tokens = cn_chars / 1.5 if cn_chars else 0
    en_tokens = non_cn_chars / 4.0 if non_cn_chars else 0

    return int(cn_tokens + en_tokens) + 4  # +4 为消息结构开销


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。

    Args:
        messages: 消息列表

    Returns:
        估算的总 token 数
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            # 多模态消息
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += estimate_tokens(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        total += 85  # 图片固定估算 ~85 tokens
        elif isinstance(content, str):
            total += estimate_tokens(content)

        # tool_calls 结构开销
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                total += estimate_tokens(json.dumps(tc, ensure_ascii=False))

        # reasoning_content
        rc = msg.get("reasoning_content", "")
        if rc:
            total += estimate_tokens(rc)

        total += 4  # 每条消息的 role/metadata 开销

    return total


def to_multimodal(msg: dict, supports_vision: bool) -> dict:
    """如果消息包含 images 字段，将 content 转换为多模态格式。

    Args:
        msg: 消息字典（会原地修改）
        supports_vision: 模型是否支持视觉输入

    Returns:
        处理后的消息字典
    """
    images = msg.pop("images", None)
    if not images:
        return msg
    if not supports_vision:
        skipped = len(images)
        logger.warning(f"模型不支持视觉，跳过 {skipped} 张图片")
        text = msg.get("content", "")
        if not text:
            msg["content"] = "[图片]（当前模型不支持视觉，图片已跳过）"
        return msg

    text = msg.get("content", "")
    parts = []
    if text:
        parts.append({"type": "text", "text": text})
    for img_path in images:
        if not os.path.isfile(img_path):
            continue
        try:
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            ext = os.path.splitext(img_path)[1].lower()
            mime_map = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"
            }
            mime = mime_map.get(ext, "image/png")
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })
        except Exception as e:
            logger.warning(f"图片编码失败 {img_path}: {e}")
    if not parts:
        msg["content"] = ""
        return msg
    if len(parts) == 1 and parts[0]["type"] == "text":
        msg["content"] = text
        return msg
    msg["content"] = parts
    return msg


def _key_words(text: str) -> set:
    """提取文本中的关键词（中文2字+、英文3字母+）"""
    cn = re.findall(r'[一-鿿]{2,}', text)
    en = re.findall(r'[a-zA-Z_]{3,}', text.lower())
    return set(cn + en)


def _find_prune_cutoff(messages: list, tail_turns: int = 3) -> int:
    """找到最近 tail_turns 轮的分界索引。

    从后往前数 user 消息，第 tail_turns 个 user 的索引即为裁剪分界。
    此索引之前的 tool 消息可安全裁剪。
    不足 tail_turns 轮则返回 0（不裁剪）。
    """
    user_count = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_count += 1
            if user_count >= tail_turns:
                return i
    return 0


def _extract_files_from_text(text: str) -> set:
    """从文本中提取文件路径和符号引用"""
    files = set()
    for m in re.finditer(r'[\w.-]+/[\w.-]+(?:/[\w.-]+)*\.\w+', text):
        files.add(m.group())
    symbols = set(re.findall(r'\b[a-zA-Z_]\w{2,}\b', text))
    if symbols:
        try:
            idx_path = os.path.join('.tea_agent_run', 'symbol_index.json')
            if os.path.exists(idx_path):
                with open(idx_path, encoding='utf-8') as _f:
                    sym_index = json.load(_f)
                for sym in symbols:
                    if sym in sym_index:
                        for entry in sym_index[sym]:
                            fp = entry.get('path', '')
                            if fp:
                                files.add(fp)
        except Exception:
            logger.exception("operation failed")

    return files


def _get_token_budget(context: Any) -> tuple[int, int]:
    """获取 token 预算：返回 (input_budget, tool_prune_threshold)

    根据 max_context_tokens 动态计算：
    - input_budget = max_context_tokens * 0.8（预留 20% 给输出）
    - tool_prune_threshold = max(500, input_budget * 0.02)  # 动态阈值，最低 500 字符
    """
    max_ctx = getattr(context, 'max_context_tokens', 0) or 0
    if max_ctx > 0:
        input_budget = int(max_ctx * 0.8)
        # 动态工具裁剪阈值：预算的 2%，最低 500 字符
        tool_prune_threshold = max(500, int(input_budget * 0.02))
    else:
        input_budget = 0
        tool_prune_threshold = 500  # 默认值
    return input_budget, tool_prune_threshold


def _progressive_trim(messages: list[dict], budget: int, context: Any,
                      tool_prune_threshold: int = 500) -> list[dict]:
    """渐进式裁剪消息以满足 token 预算。

    裁剪策略（按优先级从高到低）：
    1. 删除 [历史记录] 等标记的 L2 条目（最旧的先删）
    2. 替换工具输出为占位符（使用动态阈值）
    3. 删除 reasoning_content
    4. 截断长文本（assistant/tool 消息）
    5. 删除 L1 旧轮次（保留最近 5 轮）

    Args:
        messages: API 消息列表
        budget: token 预算
        context: SessionContext
        tool_prune_threshold: 工具输出裁剪阈值（字符数）

    Returns:
        裁剪后的消息列表
    """
    result = list(messages)
    est = estimate_messages_tokens(result)
    if est <= budget:
        return result

    # 策略1: 删除 [历史记录] 标记的 L2 条目
    i = 0
    while i < len(result) and est > budget:
        msg = result[i]
        content = msg.get("content", "")
        if isinstance(content, str) and "[历史记录]" in content:
            est -= estimate_tokens(content) + 4
            result.pop(i)
            logger.debug(f"裁剪 L2 条目: {content[:50]}...")
        else:
            i += 1

    # 策略2: 替换工具输出为占位符（使用动态阈值）
    if est > budget:
        for i in range(len(result) - 1, -1, -1):
            if est <= budget:
                break
            msg = result[i]
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > tool_prune_threshold:
                    n_chars = len(content)
                    msg["content"] = f"[工具结果已省略: {n_chars} 字符]"
                    est -= estimate_tokens(content) - 30
                    est = max(est, 0)

    # 策略3: 删除 reasoning_content
    if est > budget:
        for msg in result:
            if est <= budget:
                break
            if "reasoning_content" in msg and msg["reasoning_content"]:
                est -= estimate_tokens(msg["reasoning_content"])
                msg["reasoning_content"] = ""
                est = max(est, 0)

    # 策略4: 截断长文本（逐步收紧截断阈值）
    if est > budget:
        for max_text_len in [8192, 4096, 2048, 1024]:
            if est <= budget:
                break
            for msg in result:
                if est <= budget:
                    break
                if msg.get("role") in ("assistant", "tool", "user"):
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > max_text_len:
                        trimmed = content[:max_text_len] + f"\n... [已截断: 原长 {len(content)} 字符]"
                        est -= estimate_tokens(content) - estimate_tokens(trimmed)
                        msg["content"] = trimmed
                        est = max(est, 0)

    # 策略5: 删除 L1 旧轮次（保留最近 5 轮 user 消息）
    if est > budget:
        user_positions = []
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                user_positions.append(i)
                if len(user_positions) >= 5:
                    break

        if len(user_positions) >= 5:
            cutoff = min(user_positions)
            new_result = [msg for msg in result[:cutoff]
                         if msg.get("role") == "system"]
            new_result.extend(result[cutoff:])
            est = estimate_messages_tokens(new_result)
            result = new_result
            logger.info(f"裁剪 L1 旧轮次: 保留最近 5 轮，估计 {est} tokens")

    # 最终保护：如果还超，强制截断最后一条消息
    if est > budget and result:
        last = result[-1]
        content = last.get("content", "")
        if isinstance(content, str):
            keep = len(content) // 3
            if keep > 256:
                last["content"] = content[:keep] + f"\n... [紧急截断: 原长 {len(content)} 字符]"
                est = estimate_messages_tokens(result)
                logger.warning(f"紧急截断最后一条消息至 {keep} 字符")

    return result


def filter_level2_by_relevance(level2: list, current_msg: str) -> list:
    """按语义相关性筛选 Level 2 条目。

    基于关键词重叠度和文件路径匹配进行评分，
    高相关(>=0.15)保留完整对话，低相关(>=0.05)保留摘要。

    Args:
        level2: Level 2 条目列表
        current_msg: 当前用户消息

    Returns:
        筛选后的条目列表
    """
    if not level2 or not current_msg:
        return [{"kind": "full", **p} for p in level2]

    k_current = _key_words(current_msg)
    current_files = _extract_files_from_text(current_msg)

    scored = []
    for pair in level2:
        k_pair = _key_words(
            pair.get("user", "") + " "
            + pair.get("thinking", "") + " "
            + pair.get("assistant", "")
        )
        if not k_current or not k_pair:
            score = 0.5
        else:
            intersection = k_current & k_pair
            union = k_current | k_pair
            score = len(intersection) / max(len(union), 1)

        pair_files = set(pair.get("files", []))
        if current_files and pair_files:
            file_overlap = len(current_files & pair_files)
            if file_overlap > 0:
                score = max(score, 0.4 + file_overlap * 0.1)

        scored.append((score, pair))

    result = []
    for score, pair in scored:
        if score >= 0.15:
            result.append({"kind": "full", **pair})
        elif score >= 0.05:
            user_brief = pair.get("user", "")[:80]
            ai_brief = pair.get("assistant", "")[:120]
            result.append({
                "kind": "summary",
                "content": f"User: {user_brief}... → Assistant: {ai_brief}..."
            })

    if not result and scored:
        _, best = max(scored, key=lambda x: x[0])
        result = [{"kind": "full", **best}]

    logger.debug(
        f"L2 filter: {len(level2)} in -> {len(result)} out "
        f"(scores: {[round(s, 3) for s, _ in scored]})"
    )
    return result


def _build_l0_enriched_system(context: Any, system_prompt: str) -> str:
    """构建 L0 富化系统提示词 — 将所有辅助上下文合并到 system prompt 尾部。

    相比之前每条注入都创建 user+assistant 假对话（浪费 2 条消息/项），
    现在所有注入合并到 system prompt 尾部，消除假对话，并做 hash 去重。

    Args:
        context: SessionContext
        system_prompt: 原始系统提示词

    Returns:
        富化后的系统提示词
    """
    enriched = system_prompt

    # 小模型自动注入输出规范约束
    try:
        from tea_agent.session.prompts import SMALL_MODEL_CONSTRAINT, get_skill_validate_rules, is_small_model
        _model_name = getattr(context, 'model', '') or ''
        if is_small_model(_model_name):
            enriched = enriched.rstrip('\n') + '\n\n' + SMALL_MODEL_CONSTRAINT
            _rules = get_skill_validate_rules("output-format-constraint")
            if _rules:
                context._skill_validate_rules = _rules
        else:
            for _msg in reversed(getattr(context, 'messages', []) or []):
                _c = _msg.get('content', '') or ''
                if isinstance(_c, str) and 'toolkit_skills' in _c and 'load' in _c:
                    _m = __import__('re').search(r'name["\']?\s*[:=]\s*["\']([^"\']+)', _c)
                    if _m:
                        _loaded_skill = _m.group(1)
                        _rules = get_skill_validate_rules(_loaded_skill)
                        if _rules:
                            context._skill_validate_rules = _rules
                    break
    except Exception as _e:
        logger.debug(f"Small model constraint injection failed: {_e}")

    # ── 收集所有注入内容 ──
    inject_parts = []

    # 1. 技能推荐注入
    try:
        _current_user_msg = ""
        for _i in range(len(context.messages) - 1, -1, -1):
            if context.messages[_i].get("role") == "user":
                _c = context.messages[_i].get("content", "")
                _current_user_msg = (
                    " ".join(_p.get("text", "") for _p in _c if _p.get("type") == "text")
                    if isinstance(_c, list) else str(_c)
                )
                break
        if _current_user_msg:
            from tea_agent.skills.skill_registry import SkillRegistry as _SkillRegistry
            _reg = _SkillRegistry()
            _recommended = _reg.recommend(_current_user_msg, top_k=3)
            if _recommended:
                _parts = ["[经验技能参考]"]
                for _idx, _sk in enumerate(_recommended, 1):
                    _tools_str = ", ".join(_sk.tools[:5])
                    _parts.append(f"{_idx}. {_sk.name} (置信度: {_sk.confidence:.0%}) 工具: {_tools_str}")
                inject_parts.append("\n".join(_parts))
    except Exception as _e:
        logger.debug(f"Skill recommendation injection failed: {_e}")

    # 2. 未完成任务检查注入
    try:
        from tea_agent.toolkit.toolkit_task_resume import toolkit_task_resume
        resume_info = toolkit_task_resume(action="check")
        if resume_info.get("has_pending"):
            parts = ["[未完成任务提醒]"]
            if resume_info.get("pending_todos"):
                todos = resume_info["pending_todos"]
                parts.append(f"有 {len(todos)} 个未完成的 TODO 项:")
                for t in todos[:5]:
                    parts.append(f"  - [{t['idx']}] {t['desc']}")
                if len(todos) > 5:
                    parts.append(f"  ... 还有 {len(todos)-5} 项")
            if resume_info.get("pending_plans"):
                plans = resume_info["pending_plans"]
                parts.append(f"有 {len(plans)} 个未完成的 Plan:")
                for p in plans[:3]:
                    parts.append(f"  - [{p['plan_id']}] {p['goal']} (进度: {p['progress']})")
            inject_parts.append("\n".join(parts))
    except Exception as e:
        logger.debug(f"task resume check failed: {e}")

    # 3. 长期记忆注入（仅当 L3 禁用时，才注入到 system prompt）
    #    如果 L3 启用，记忆会合并到 L3 块中，避免重复（见 _build_level3_block）
    disable_l3 = getattr(context, 'disable_l3', False) or context.disable_summary
    if disable_l3 and context._injected_memories_text:
        inject_parts.append(context._injected_memories_text)

    # 合并所有注入到 system prompt（带 hash 去重）
    if inject_parts:
        combined_inject = "\n\n---\n\n".join(inject_parts)
        new_hash = hash(combined_inject)
        if new_hash != getattr(context, '_last_l0_hash', 0):
            enriched = enriched.rstrip('\n') + '\n\n' + combined_inject
            context._last_l0_hash = new_hash

    return enriched


def _build_level3_block(context: Any) -> list[dict]:
    """构建 Level 3 摘要消息块。

    合并长期记忆 + 语义摘要 + 工具链摘要到一个消息中，
    避免 L0 和 L3 重复携带相同信息。

    Args:
        context: SessionContext

    Returns:
        消息列表（0~2 条：user + 可选的 assistant 占位）
    """
    result = []
    parts = []

    # 合并长期记忆到 L3（避免 L0 和 L3 重复）
    memory = context._injected_memories_text
    sem = context._semantic_summary
    tc = context._tool_chain_summary

    if memory:
        parts.append(f"## 长期记忆\n{memory}")
    if sem:
        parts.append(f"## 长期背景/偏好/关键结论\n{sem}")
    if tc:
        parts.append(f"## 历史工具调用链回顾\n{tc}")

    # 兼容旧 _history_summary
    if not parts and context._history_summary:
        result.append({
            "role": "user",
            "content": f"这是我们之前对话的摘要：\n{context._history_summary}"
        })
        return result

    if parts:
        result.append({
            "role": "user",
            "content": "[系统记忆 — 以下为需要遵循的有效信息和规则]\n\n" + "\n\n---\n\n".join(parts)
        })
        # NOTE: 不再添加假 assistant 回复，节省 token

    return result


def build_api_messages(context: Any, system_prompt: str) -> list[dict]:
    """构建 API 消息列表 — 三级历史拼接（v2 改进版）。

    Level 0: 系统提示词 + 所有辅助上下文（合并到 system prompt 尾部，消除假对话）
    Level 3: 语义摘要 + 工具链摘要 + 长期记忆（合并以避免与 L0 重复）
    Level 2: 按语义相关性筛选的 user+assistant 对（无假 assistant 回复）
    Level 1: 最新对话（含动态工具输出裁剪）

    Args:
        context: SessionContext 实例
        system_prompt: 系统提示词

    Returns:
        构建好的 API 消息列表
    """
    from tea_agent.session.json_sanitizer import sanitize_api_messages

    result: list[dict] = []

    # ═══════════════════════════════════════════════
    # Level 0: 富化系统提示词（所有注入合并到尾部）
    # ═══════════════════════════════════════════════
    enriched = _build_l0_enriched_system(context, system_prompt)
    result.append({"role": "system", "content": enriched})

    # ═══════════════════════════════════════════════
    # Level 3 + Level 2: 摘要与相关历史
    # ═══════════════════════════════════════════════
    # 向后兼容：disable_summary 等效于 disable_l3=True && disable_l2=True
    disable_l3 = getattr(context, 'disable_l3', False) or context.disable_summary
    disable_l2 = getattr(context, 'disable_l2', False) or context.disable_summary

    if not disable_l3:
        result.extend(_build_level3_block(context))

    if not disable_l2:
        level2 = context._level2
        if level2:
            current_user_msg = ""
            for i in range(len(context.messages) - 1, 0, -1):
                if context.messages[i].get("role") == "user":
                    cur_content = context.messages[i].get("content", "")
                    if isinstance(cur_content, list):
                        current_user_msg = "".join(
                            p.get("text", "") for p in cur_content if p.get("type") == "text"
                        )
                    else:
                        current_user_msg = str(cur_content)
                    break
            filtered = filter_level2_by_relevance(level2, current_user_msg)
            for item in filtered:
                kind = item.get("kind", "full")
                if kind == "summary":
                    result.append({
                        "role": "user",
                        "content": f"[历史相关对话摘要] {item['content']}"
                    })
                else:
                    user_text = item.get("user", "")
                    assistant_text = item.get("assistant", "")
                    result.append({
                        "role": "user",
                        "content": f"[历史记录]\n用户: {user_text}"
                    })
                    _msg = {"role": "assistant", "content": assistant_text}
                    if context.supports_reasoning:
                        _msg["reasoning_content"] = ""
                    result.append(_msg)

    # ═══════════════════════════════════════════════
    # Level 1: 最新对话（含动态工具输出裁剪）
    # ═══════════════════════════════════════════════
    max_turns_limit = 30
    start_idx = 1

    # 动态计算 token 预算和工具裁剪阈值
    input_budget, tool_prune_threshold = _get_token_budget(context)

    # 工具输出裁剪 — 保留最近 3 轮完整结果，更早的替换为占位符
    _tool_prune_cutoff = _find_prune_cutoff(context.messages, tail_turns=3)

    # disable_summary 时：丢弃早期历史，只保留最近 30 轮
    if context.disable_summary:
        user_msg_indices = []
        for i in range(1, len(context.messages)):
            if context.messages[i].get("role") == "user":
                user_msg_indices.append(i)
        if len(user_msg_indices) > max_turns_limit:
            start_idx = user_msg_indices[-max_turns_limit]
            logger.info(
                f"disable_summary 启用: 丢弃早期历史，保留最近 {max_turns_limit} 轮 "
                f"(共 {len(user_msg_indices)} 轮)"
            )

    for i in range(start_idx, len(context.messages)):
        msg = context.messages[i]
        msg_copy = dict(msg)

        # 动态工具输出裁剪 — 使用动态阈值而非固定 100 字符
        if msg_copy["role"] == "tool" and i < _tool_prune_cutoff:
            raw = msg_copy.get("content", "")
            n_chars = len(raw) if isinstance(raw, str) else len(str(raw))
            if n_chars > tool_prune_threshold:
                msg_copy["content"] = f"[工具结果已省略: {n_chars} 字符]"

        if (msg_copy["role"] == "assistant" and context.supports_reasoning
                and "reasoning_content" not in msg_copy):
            msg_copy["reasoning_content"] = ""
        msg_copy = to_multimodal(msg_copy, context.supports_vision)
        if isinstance(msg_copy.get("content"), list) and not context.supports_vision:
            text_parts = []
            for p in msg_copy["content"]:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        text_parts.append(p.get("text", ""))
                    elif p.get("type") == "image_url":
                        text_parts.append("[图片]")
            msg_copy["content"] = "\n".join(text_parts) if text_parts else "[图片]"
        result.append(msg_copy)

    # ── 渐进式 token 裁剪 ──
    if input_budget > 0:
        est = estimate_messages_tokens(result)
        if est > input_budget:
            logger.info(f"token 预估: {est} > 预算 {input_budget}，启动渐进式裁剪")
            result = _progressive_trim(result, input_budget, context,
                                       tool_prune_threshold=tool_prune_threshold)
            est_after = estimate_messages_tokens(result)
            logger.info(f"裁剪后: {est_after} tokens (节省 {est - est_after})")

    # JSON 完整性校验
    result = sanitize_api_messages(result)

    # Safeguard: 移除孤立 tool 消息
    valid_ids = set()
    cleaned = []
    for msg in result:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                if tc.get("id"):
                    valid_ids.add(tc["id"])
            cleaned.append(msg)
        elif msg.get("role") == "tool":
            if msg.get("tool_call_id") in valid_ids:
                cleaned.append(msg)
            else:
                logger.warning(f"build_api_messages: 移除孤立 tool 消息 (id={msg.get('tool_call_id')})")
        else:
            cleaned.append(msg)
    result = cleaned

    return result

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


def to_multimodal(msg: dict, supports_vision: bool, original: dict | None = None) -> dict:
    """如果消息包含 images 字段，将 content 转换为多模态格式。

    Args:
        msg: 消息字典（会原地修改，images 会被 pop）
        supports_vision: 模型是否支持视觉输入
        original: context.messages 中的原始消息（用于回写 base64 快照缓存；
            A6: 同一图片文件被覆盖前各请求复用同一编码，避免前缀变化）

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
    # A6: base64 快照缓存（写回原消息；图片文件未变化时复用同一编码）
    b64_cache = (msg.get("_b64_cache") or {}) if original is not None else {}
    for img_path in images:
        # 已是 data URL（如 API server 传入 data:image/...;base64,...）→ 直接透传
        if isinstance(img_path, str) and img_path.startswith("data:"):
            parts.append({"type": "image_url", "image_url": {"url": img_path}})
            continue
        if not os.path.isfile(img_path):
            continue
        b64 = b64_cache.get(img_path)
        if b64 is None:
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                if original is not None:
                    b64_cache[img_path] = b64
            except Exception as e:
                logger.warning(f"图片编码失败 {img_path}: {e}")
                continue
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
    if original is not None:
        original["_b64_cache"] = b64_cache
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
    cn = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]{2,}', text)
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


def _solidify_history(messages: list, cutoff: int, threshold: int,
                      max_text_len: int = 16384) -> int:
    """将滑出最近窗口的大消息持久化定型，确保历史前缀不再变化。

    缓存友好（DeepSeek 前缀缓存）：历史消息必须"定型"——一旦裁剪写入
    context.messages 就不再改变。否则同一消息在每次请求构建时被动态改写
    （完整→占位符 / 长文本→截断），会破坏其之后所有消息的前缀缓存命中。

    处理两类：
    1. tool 消息 content > threshold → 占位符（幂等守卫 [工具结果已省略）
    2. user/assistant 长文本 > max_text_len → 截断（幂等守卫 [已截断）

    Args:
        messages: context.messages（原地修改）
        cutoff: 裁剪分界索引（此索引之前的消息可定型）
        threshold: tool 输出字符数阈值
        max_text_len: 长文本截断阈值（字符）

    Returns:
        本次实际定型的消息数
    """
    if cutoff <= 0:
        return 0
    pruned = 0
    for i in range(1, cutoff):
        msg = messages[i]
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "tool":
            if (isinstance(content, str) and not content.startswith("[工具结果已省略")
                    and len(content) > threshold):
                msg["content"] = f"[工具结果已省略: {len(content)} 字符]"
                pruned += 1
        elif role in ("user", "assistant"):
            if (isinstance(content, str) and content
                    and "[已截断" not in content and len(content) > max_text_len):
                msg["content"] = content[:max_text_len] + f"\n... [已截断: 原长 {len(content)} 字符]"
                pruned += 1
    if pruned:
        logger.debug(f"_solidify_history: 持久化定型 {pruned} 条消息 (cutoff={cutoff})")
    return pruned


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
            logger.exception('op_failed')

    return files


def _get_token_budget(context: Any) -> tuple[int, int]:
    """获取 token 预算：返回 (input_budget, tool_prune_threshold)

    根据 max_context_tokens 动态计算：
    - input_budget = max_context_tokens * 0.8（预留 20% 给输出）
    - tool_prune_threshold = max(65536, input_budget * 0.02)  # 动态阈值，最低 64K 字符
    """
    max_ctx = getattr(context, 'max_context_tokens', 0) or 0
    if max_ctx > 0:
        input_budget = int(max_ctx * 0.8)
        # 动态工具裁剪阈值：预算的 2%，最低 64K 字符（保证读取代码/文件内容完整）
        tool_prune_threshold = max(65536, int(input_budget * 0.02))
    else:
        input_budget = 0
        tool_prune_threshold = 65536  # 默认值（与入库压缩上限对齐）
    return input_budget, tool_prune_threshold


def get_tool_prune_threshold(context: Any) -> int:
    """工具内容统一压缩/裁剪阈值（字符数）。

    缓存友好（DeepSeek 前缀缓存）核心不变式：
        入库压缩上限 == _persist_prune / _solidify_history 裁剪阈值。
    消息一旦入库即被压缩到该阈值以内 → 永不触发二次改写
    （完整→占位符翻转），保证历史前缀逐字节稳定、可命中缓存。

    取值 max(65536, input_budget * 0.02)：
    - 128K 窗口 → 65536（64KB，足够容纳完整代码文件）
    - 1M 窗口 → 65536（下限保障；更大窗口按预算 2% 上浮）
    - 更小窗口 → 不低于 65536，确保读取代码/文件时内容完整
    """
    input_budget, _ = _get_token_budget(context)
    if input_budget > 0:
        return max(65536, int(input_budget * 0.02))
    return 65536


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
    # 幂等守卫：已定型消息（含 [已截断 / [工具结果已省略 标记）不再二次改写，
    # 避免已发送前缀在后续请求中被截得更短 → 前缀缓存级联失效。
    if est > budget:
        for max_text_len in [8192, 4096, 2048, 1024]:
            if est <= budget:
                break
            for msg in result:
                if est <= budget:
                    break
                if msg.get("role") in ("assistant", "tool", "user"):
                    content = msg.get("content", "")
                    if (isinstance(content, str)
                            and not content.startswith(("[工具结果已省略", "[已截断"))
                            and "[已截断" not in content
                            and len(content) > max_text_len):
                        trimmed = content[:max_text_len] + f"\n... [已截断: 原长 {len(content)} 字符]"
                        est -= estimate_tokens(content) - estimate_tokens(trimmed)
                        msg["content"] = trimmed
                        est = max(est, 0)

    # 策略5: 删除 L1 旧轮次（保留最近 5 轮真实对话轮次）
    # A4: 只统计 L1 段真实 user 消息——L2/L3 块（[历史记录]/[历史相关对话摘要]/
    # [系统记忆/[动态上下文 前缀）是临时构造，不算轮次，避免"保留 5 轮"
    # 实际只剩更少真实轮次、且 cutoff 落在 L2 块中间造成前缀抖动。
    if est > budget:
        user_positions = []
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") != "user":
                continue
            content = result[i].get("content", "")
            if (isinstance(content, str) and content.startswith(
                    ("[历史记录]", "[历史相关对话摘要]", "[系统记忆", "[动态上下文"))):
                continue
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

    # 小模型自动注入输出规范约束（A7: 一次性固化，不依赖消息扫描。
    # 扫描结果可能随 L3 压缩/裁剪变化，导致规则在会话中途翻转。）
    if not getattr(context, "_skill_rules_set", False):
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
        context._skill_rules_set = True

    # ── 收集所有注入内容 ──
    inject_parts = []

    # 动态注入（技能加载 / 未完成任务提醒 / 长期记忆）已移至消息尾部
    # （见 _build_dynamic_context 与 build_api_messages 末尾插入），
    # 确保 system prompt 前缀稳定，最大化 DeepSeek 前缀缓存命中率。
    # 若这些内容随每轮请求变化却注入 system prompt（消息前缀首元素），
    # 会导致整条前缀缓存 100% 失效（当前会话实测命中率仅 0.8%）。

    # 3. 操作系统环境信息注入（属性注入模式）
    #    OS 信息由 pipeline 步骤检测 OS 变化后写入 context._injected_os_info_text
    #    取代了旧版注入虚假 user+assistant 消息轮次的做法
    os_text = getattr(context, '_injected_os_info_text', '') or ''
    if os_text:
        inject_parts.append(os_text)

    # 长期记忆（disable_l3 时）已移至 _build_dynamic_context（消息尾部注入）

    # 2. 上下文片段注入（借鉴 Codex Context Fragments）
    #    按需组装：token 预算 / 当前时间 / 会话模式 / AGENTS.md 等
    #    让模型感知剩余空间，自主决策"继续干活 or 先总结"
    try:
        from tea_agent.context_fragments import assemble_fragments

        # 缓存友好（DeepSeek 前缀缓存）：排除动态片段 current_time/token_budget/session_budget。
        # 它们每次请求必变（时间走秒、token 估算随 messages 增长、轮次递增），
        # 若注入 system prompt（消息前缀首元素）会导致整条前缀缓存 100% 失效。
        # 这些动态状态改由 add_user_message 在用户消息入库时一次性定格注入（见 basesession.py）。
        # A2: OS 文本已在上方直接注入，排除 environment 片段避免重复
        # （重复注入每请求浪费 ~1-2KB token，且放大缓存未命中成本）。
        frag_text = assemble_fragments(
            context,
            exclude=["session_budget", "token_budget", "current_time", "environment"],
        )
        if frag_text:
            inject_parts.append(frag_text)
    except Exception as e:
        logger.debug(f"context fragments injection failed: {e}")

    # 合并所有注入到 system prompt（将所有注入放在最前面，提高可见性）
    # 注意：enriched 每次从 system_prompt 重新初始化，因此只要存在注入就必须重新拼接，
    # 不能用 hash 去重跳过——否则"注入内容不变"的后续请求会丢失注入（system prompt
    # 在首次请求与后续请求之间不一致，同样会破坏前缀缓存命中）。
    if inject_parts:
        combined_inject = "\n\n---\n\n".join(inject_parts)
        enriched = combined_inject + '\n\n' + enriched.rstrip('\n')

    return enriched


def _build_dynamic_context(context: Any) -> str:
    """构建动态上下文文本（注入到消息尾部，不进入 system prompt）。

    缓存友好（DeepSeek 前缀缓存）：system prompt 必须保持前缀稳定。
    以下内容随对话/任务状态变化，若注入 system prompt（消息前缀首元素）
    会导致整条前缀缓存失效，实测命中率仅 0.8%（569K 未命中 vs 4.6K 命中）：
    - 按需技能加载（加载前后 system prompt 不一致）
    - 未完成任务提醒（TODO/Plan 状态变化）
    - 长期记忆（disable_l3 时，随注入时机变化）

    这些内容作为临时 user 消息插入到消息尾部（build_api_messages 末尾），
    不持久化到 context.messages，因此不影响历史前缀稳定性。

    Args:
        context: SessionContext

    Returns:
        动态上下文文本（无内容时返回空串）
    """
    inject_parts: list[str] = []

    # 1. 按需技能加载（取代已废除的"知识结晶推荐"）
    #    经过几轮对话后，评估各 skill 的必要性/充分性，决定是否注入 SKILL.md
    try:
        from tea_agent.skill_loader import evaluate_and_load as _skill_eval
        _skill_text = _skill_eval(context)
        if _skill_text:
            inject_parts.append(_skill_text)
    except Exception as _e:
        logger.debug(f"Skill on-demand loading failed: {_e}")

    # 2. 未完成任务检查
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

    # 3. 长期记忆（S3: 统一在尾部动态上下文注入，L3 块不再携带）
    #    记忆随当前用户消息每轮变化，放在消息尾部（临时 user 消息，紧随最后一个
    #    user 之前）不影响前缀稳定性，同时保持对模型的高可见性。
    memories_text = getattr(context, '_injected_memories_text', '') or ''
    if memories_text:
        inject_parts.append(f"## 长期记忆\n{memories_text}")

    if not inject_parts:
        return ""
    return "[动态上下文 — 由 tea_agent 自动注入，供参考]\n\n" + "\n\n---\n\n".join(inject_parts)


def _get_dynamic_context(context: Any) -> str:
    """获取动态上下文文本（带会话级缓存，工具循环内复用）。

    缓存友好（DeepSeek 前缀缓存）：动态上下文（skill 加载/TODO 状态/记忆）在
    工具循环内若每轮重新计算，内容变化会导致尾部插入的动态消息变动，
    其后的消息前缀无法命中缓存。因此首次构建时计算并缓存，
    仅在新用户消息入库时失效（add_user_message 清除 _dynamic_ctx_cache）。
    """
    cached = getattr(context, "_dynamic_ctx_cache", None)
    if cached is None:
        cached = _build_dynamic_context(context)
        context._dynamic_ctx_cache = cached
    return cached


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

    # S3: 长期记忆已移至尾部动态上下文（_build_dynamic_context）。
    # 记忆随当前用户消息每轮变化，若放在 L3（消息前缀 result[1]），
    # 每轮变化会导致其后全部 L1/L2 历史缓存失效；移到尾部后 L3 只含
    # 低频变化的摘要，跨轮前缀（system + L3 + L2 + L1）可稳定命中缓存。
    sem = context._semantic_summary
    tc = context._tool_chain_summary

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


def _calibrated_estimate(context: Any, estimate: int) -> int:
    """用上次 API 实际 usage 校准启发式 token 估算（A5）。

    启发式估算（中文 1.5 字/token、英文 4 字符/token）与真实 tokenizer 存在偏差。
    若上次实际 prompt_tokens 明显高于估算（低估超过 20%），按比例放大本次估算，
    使预算"越线"时机提前、贴近真实，避免裁剪在工具循环中段才触发
    （此时已发送消息可能被二次改写，破坏前缀缓存）。
    只放大不缩小（保守，避免高估触发多余裁剪）。
    """
    try:
        last = getattr(context, "_last_usage", None) or {}
        actual = last.get("prompt_tokens", 0) or 0
        if actual <= 0 or estimate <= 0:
            return estimate
        ratio = actual / estimate
        if ratio > 1.2:
            return int(estimate * ratio)
    except Exception:
        pass
    return estimate


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
    # 自适应起始索引：真实会话中 messages[0] 为 system 消息（跳过）；
    # 若调用方未提供 system 头（如部分测试/轻量场景），从 0 开始，
    # 避免首条用户消息被误跳过。
    start_idx = 1
    if not context.messages or context.messages[0].get("role") != "system":
        start_idx = 0

    # 动态计算 token 预算和工具裁剪阈值
    input_budget, tool_prune_threshold = _get_token_budget(context)

    # 工具输出裁剪 — 保留最近 3 轮完整结果，更早的替换为占位符
    _tool_prune_cutoff = _find_prune_cutoff(context.messages, tail_turns=3)

    # 缓存友好：先持久化定型（写回 context.messages），确保历史消息定型。
    # 否则每次请求构建时动态改写已发送过的 tool/长文本消息，会破坏前缀缓存命中。
    _solidify_history(context.messages, _tool_prune_cutoff, tool_prune_threshold)

    # disable_summary 时：丢弃早期历史，只保留最近 30 轮
    if context.disable_summary:
        user_msg_indices = []
        for i in range(start_idx, len(context.messages)):
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
        msg_copy = to_multimodal(msg_copy, context.supports_vision, original=msg)
        msg_copy.pop("_b64_cache", None)
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
        # A5: 用上次 API 实际 usage 校准启发式估算（低估时放大），
        # 避免预算"越线"时机与真实 tokenizer 偏差导致裁剪在循环中段才触发。
        est_check = _calibrated_estimate(context, est)
        if est_check > input_budget:
            logger.info(f"token 预估: {est_check} (>预算 {input_budget}, 原始估算 {est})，启动渐进式裁剪")
            result = _progressive_trim(result, input_budget, context,
                                       tool_prune_threshold=tool_prune_threshold)
            est_after = estimate_messages_tokens(result)
            logger.info(f"裁剪后: {est_after} tokens (节省 {est - est_after})")

    # 剥离内部字段（base64 快照缓存/图片路径），避免发送给 API
    for _m in result:
        _m.pop("_b64_cache", None)
        _m.pop("images", None)

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

    # ── 动态上下文注入（缓存友好）──
    # 技能加载 / 未完成任务提醒 / 长期记忆等动态内容作为临时 user 消息
    # 插到最后一个 user 消息之前（消息尾部），不进入 system prompt，
    # 保证前缀（system + 历史）稳定可命中。临时构造不持久化到 context.messages，
    # 因此不影响下一轮请求的历史前缀连续性。
    # 内容带会话级缓存（_get_dynamic_context），工具循环内复用同一版本，
    # 避免 TODO/skill 状态变化导致尾部动态消息频繁变动破坏前缀。
    dynamic_text = _get_dynamic_context(context)
    if dynamic_text:
        dyn_msg = {"role": "user", "content": dynamic_text}
        _last_user = -1
        for _i in range(len(result) - 1, -1, -1):
            if result[_i].get("role") == "user":
                _last_user = _i
                break
        if _last_user >= 0:
            result.insert(_last_user, dyn_msg)
        # 无 user 消息时跳过注入：避免破坏消息结构（如纯工具历史/精简场景），
        # 此时动态上下文对模型价值也有限。

    return result

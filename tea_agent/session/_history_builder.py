
"""
历史消息构建模块

从 onlinesession.py 提取的独立功能：
- build_api_messages: 三级历史拼接 (L0系统提示 + L3摘要 + L2相关 + L1最新)
- filter_level2_by_relevance: 按语义相关性筛选 Level 2 条目
- to_multimodal: 多模态消息转换
"""

import os
import re
import json
import base64
import logging
from typing import List, Dict, Optional, Any

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


def estimate_messages_tokens(messages: List[Dict]) -> int:
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


def to_multimodal(msg: Dict, supports_vision: bool) -> Dict:
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
                with open(idx_path, 'r', encoding='utf-8') as _f:
                    sym_index = json.load(_f)
                for sym in symbols:
                    if sym in sym_index:
                        for entry in sym_index[sym]:
                            fp = entry.get('path', '')
                            if fp:
                                files.add(fp)
        except Exception:
            pass
    return files


def _progressive_trim(messages: List[Dict], budget: int, context: Any) -> List[Dict]:
    """渐进式裁剪消息以满足 token 预算。
    
    裁剪策略（按优先级从高到低）：
    1. 删除 [历史记录] 等标记的 L2 条目（最旧的先删）
    2. 替换工具输出为占位符
    3. 删除 reasoning_content
    4. 截断长文本（assistant/tool 消息）
    5. 删除 L1 旧轮次（保留最近 5 轮）
    
    Args:
        messages: API 消息列表
        budget: token 预算
        context: SessionContext
        
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
    
    # 策略2: 替换工具输出为占位符
    if est > budget:
        for i in range(len(result) - 1, -1, -1):
            if est <= budget:
                break
            msg = result[i]
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 100:
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
    
    # 策略4: 截断长文本
    if est > budget:
        max_text_len = 4096  # 初始截断长度
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
        # 找到最近 5 个 user 消息的位置
        user_positions = []
        for i in range(len(result) - 1, -1, -1):
            if result[i].get("role") == "user":
                user_positions.append(i)
                if len(user_positions) >= 5:
                    break
        
        if len(user_positions) >= 5:
            cutoff = min(user_positions)
            # 删除 cutoff 之前的消息（保留 system 和记忆注入）
            new_result = [msg for msg in result[:cutoff]
                         if msg.get("role") == "system" 
                         or "[系统记忆" in msg.get("content", "")
                         or "记忆" in msg.get("content", "")[:20]]
            # 加回最近 5 轮
            new_result.extend(result[cutoff:])
            est = estimate_messages_tokens(new_result)
            result = new_result
            logger.info(f"裁剪 L1 旧轮次: 保留最近 5 轮，估计 {est} tokens")
    
    # 最终保护：如果还超，强制截断最后一条消息
    if est > budget and result:
        last = result[-1]
        content = last.get("content", "")
        if isinstance(content, str):
            # 保留最后一条消息的前 1/3
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


def build_api_messages(context: Any, system_prompt: str) -> List[Dict]:
    """构建 API 消息列表 — 三级历史拼接。
    
    Level 0: 系统提示词 + 潜意识状态 + 长期记忆注入
    Level 3: 语义摘要 + 工具链摘要
    Level 2: 按语义相关性筛选的 user+assistant 对
    Level 1: 最新一轮压缩对话
    
    Args:
        context: SessionContext 实例
        system_prompt: 系统提示词
        
    Returns:
        构建好的 API 消息列表
    """
    from tea_agent.session._json_sanitizer import sanitize_api_messages

    result: List[Dict] = []

    # ── Level 0: 系统提示词 ──
    sys_msg = {"role": "system", "content": system_prompt}
    result.append(sys_msg)

    # ── 未完成任务自动恢复检查 ──
    try:
        from tea_agent.toolkit.toolkit_task_resume import toolkit_task_resume
        resume_info = toolkit_task_resume(action="check")
        if resume_info.get("has_pending"):
            parts = ["[未完成任务提醒]"]
            if resume_info.get("pending_todos"):
                todos = resume_info["pending_todos"]
                parts.append(f"有 {len(todos)} 个未完成的 TODO 项:")
                for t in todos[:5]:  # 最多显示 5 个
                    parts.append(f"  - [{t['idx']}] {t['desc']}")
                if len(todos) > 5:
                    parts.append(f"  ... 还有 {len(todos)-5} 项")
            if resume_info.get("pending_plans"):
                plans = resume_info["pending_plans"]
                parts.append(f"有 {len(plans)} 个未完成的 Plan:")
                for p in plans[:3]:  # 最多显示 3 个
                    parts.append(f"  - [{p['plan_id']}] {p['goal']} (进度: {p['progress']})")
            parts.append("提示: 使用 toolkit_todo(action='show') 或 toolkit_plan(action='list') 查看详情")
            result.append({"role": "user", "content": "\n".join(parts)})
    except Exception as e:
        logger.debug(f"task resume check failed: {e}")

    # ── 长期记忆注入 ──
    if context._injected_memories_text:
        result.append({
            "role": "user",
            "content": context._injected_memories_text
        })

    # NOTE: disable_summary 启用时跳过 L3/L2 历史构造
    if not context.disable_summary:
        # ── Level 3: 摘要 ──
        has_level3 = False
        parts = []
        sem = context._semantic_summary
        tc = context._tool_chain_summary
        if sem:
            parts.append(f"## 长期背景/偏好/关键结论\n{sem}")
            has_level3 = True
        if tc:
            parts.append(f"## 历史工具调用链回顾\n{tc}")
            has_level3 = True

        if has_level3:
            result.append({
                "role": "user",
                "content": "[系统记忆 — 以下为需要遵循的有效信息和规则]\n\n" + "\n\n---\n\n".join(parts)
            })
            _asst = {"role": "assistant", "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"}
            if context.supports_reasoning:
                _asst["reasoning_content"] = ""
            result.append(_asst)

        # ── 兼容旧 _history_summary ──
        if not has_level3 and context._history_summary:
            result.append({
                "role": "user",
                "content": f"这是我们之前对话的摘要：\n{context._history_summary}"
            })
            _asst2 = {"role": "assistant", "content": "好的，我已经了解了之前的对话背景。请问有什么我可以帮您的？"}
            if context.supports_reasoning:
                _asst2["reasoning_content"] = ""
            result.append(_asst2)

        # ── Level 2: 按语义相关性筛选 ──
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

                    # L2 注入仅携带 user+assistant 最终问答对
                    # thinking 保留在存储中，仅用于 L3 摘要生成
                    user_content = f"[历史记录]\n用户: {user_text}"

                    result.append({"role": "user", "content": user_content})
                    _msg = {"role": "assistant", "content": assistant_text}
                    if context.supports_reasoning:
                        _msg["reasoning_content"] = ""
                    result.append(_msg)

    # ── Level 1: 最新对话（含工具输出裁剪） ──
    max_turns_limit = 30
    start_idx = 1

    # P0: 工具输出裁剪 — 保留最近 3 轮完整结果，更早的替换为占位符
    _tool_prune_cutoff = _find_prune_cutoff(context.messages, tail_turns=3)

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

        # P0: 裁剪旧工具输出 — 替换为占位符以节省 token
        if msg_copy["role"] == "tool" and i < _tool_prune_cutoff:
            raw = msg_copy.get("content", "")
            n_chars = len(raw) if isinstance(raw, str) else len(str(raw))
            if n_chars > 100:
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
    max_ctx = getattr(context, 'max_context_tokens', 0) or 0
    if max_ctx > 0:
        est = estimate_messages_tokens(result)
        # 预留 20% 给输出，实际输入预算 = 80%
        input_budget = int(max_ctx * 0.8)
        if est > input_budget:
            logger.info(f"token 预估: {est} > 预算 {input_budget}，启动渐进式裁剪")
            result = _progressive_trim(result, input_budget, context)
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

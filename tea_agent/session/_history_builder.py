"""
历史消息构建模块

从 onlinesession.py 提取的独立功能：
- build_api_messages: 三级历史拼接 (L0系统提示 + L3摘要 + L2相关 + L1最新)
- filter_level2_by_relevance: 按语义相关性筛选 Level 2 条目
- get_subconscious_context: 读取潜意识引擎状态
- to_multimodal: 多模态消息转换
"""

import os
import re
import json
import base64
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger("session.history_builder")


def get_subconscious_context(data_dir: str = "") -> Optional[str]:
    """读取潜意识引擎状态并格式化为上下文。
    
    Args:
        data_dir: 数据目录路径，为空则自动检测
        
    Returns:
        格式化的潜意识状态文本，无数据则返回 None
    """
    try:
        if not data_dir:
            try:
                from tea_agent.config import get_config
                data_dir = get_config().paths.data_dir_abs
            except Exception:
                data_dir = os.path.expanduser("~/.tea_agent")

        state_file = os.path.join(data_dir, "subconscious_state.json")
        if not os.path.exists(state_file):
            return None

        with open(state_file, 'r') as f:
            state = json.load(f)

        goals = state.get("goals", [])
        insights = state.get("insights", [])
        focus = state.get("last_focus", "mixed")

        if not goals and not insights:
            return None

        lines = [f"## 潜意识引擎状态 (场景: {focus})"]

        if goals:
            lines.append("### 🎯 当前目标 (Goals)")
            for g in goals[:3]:
                lines.append(f"- {g}")

        if insights:
            lines.append("### 💡 最新洞察 (Insights)")
            for i in insights[:3]:
                lines.append(f"- {i}")

        return "\n".join(lines)
    except Exception:
        return None


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
        k_pair = _key_words(pair.get("user", "") + " " + pair.get("assistant", ""))
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

    # ── 潜意识引擎状态注入 ──
    sub_ctx = get_subconscious_context()
    if sub_ctx:
        result.append({"role": "user", "content": sub_ctx})

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
                    result.append({"role": "user", "content": item.get("user", "")})
                    _msg = {"role": "assistant", "content": item.get("assistant", "")}
                    if context.supports_reasoning:
                        _msg["reasoning_content"] = ""
                    result.append(_msg)

    # ── Level 1: 最新一轮压缩对话 ──
    max_turns_limit = 30
    start_idx = 1

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

# Thinking 模式 reasoning_content 处理策略

## 核心问题

DeepSeek 推理模型在 thinking 模式下返回 `reasoning_content`（思维链内容）。API 要求：
- **同一 API 会话内**：后续请求必须将前一轮的 `reasoning_content` 原样传回
- **跨 API 会话**：上一会话的 `reasoning_content` 在新会话中无效，传回会导致 400 错误

> Error code: 400 - {'error': {'message': 'The reasoning_content in the thinking mode must be passed back to the API.'}}

## 当前策略：生命周期管理 + 完整回传

reasoning_content 的生命周期 = 一个 `chat_stream` 调用（即一个 API 会话）。

> **DeepSeek V4（thinking 模式）硬性要求**（官方文档 Tool Calls 章节）：
> 「for requests carrying the `tools` parameter, the `reasoning_content` must be **fully passed back** to the API in all subsequent requests. If your code does not correctly pass back `reasoning_content`, the API will return a 400 error.」
>
> 即：凡是携带 `tools` 的请求（本 Agent 工具循环内每轮都携带），所有 assistant 消息的
> `reasoning_content` 必须**逐字完整回传**。**缺失、清空、截断**都会触发
> `Error code: 400 - ...'The reasoning_content in the thinking mode must be passed back to the API.'`

### 生命周期边界

| 阶段 | 操作 | reasoning_content |
|------|------|-------------------|
| **加载历史** | `load_history()` → `_load_single_conversation()` → `_repair_incomplete_tool_chains()` | ✅ 保留（assistant 消息的 RC 全部保留） |
| **新一轮开始** | `reset_session_state()` | ✅ 保留（assistant 消息的 RC 不清除） |
| **tool_loop 期间** | `_build_api_messages()` | ✅ 保留（当前 API 会话内，必须完整回传） |
| **持久化** | `_rounds_collector` → DB | ✅ 保留（完整记录，供回放分析） |

### 关键设计说明（2026-08 修订）

`_strip_reasoning_content()` **只清除 assistant 以外角色的 reasoning_content**（非 assistant 消息本就不该有此字段），而**保留所有 assistant 消息的 reasoning_content**，原因：
- 含 `tool_calls` 的 assistant：DeepSeek V4 要求 `reasoning_content` **必须完整回传**，否则 400
- 无 `tool_calls` 的 assistant：`reasoning_content` 传入 API **会被忽略**（官网文档明确说明），保留无害

> **结论**：保留所有 assistant 的 RC 是安全的 —— 多传了 API 会忽略，少传/清空/截断了 API 会 400。

### 本次修复要点（杜绝 400 的三处来源）

1. **不再截断 RC**：`tool_loop_runner.py` / `basesession.py` 中曾用 `_cap_message_text()`
   把 RC 截断到 16K 字符并追加 `[已截断...]` 标记。截断后的 RC 与原值不一致，
   DeepSeek 判定为"未完整回传" → 400。现改为原样入库、原样回传。
2. **不再清空 RC**：`_progressive_trim` 原"策略3：删除 reasoning_content"会清空 RC 省 token。
   对 DeepSeek V4 而言这等价于未回传 → 400。已废弃该策略，压 token 改由
   策略 4/5（截断正文、删除旧轮次连同其 RC）承担。
3. **不再给 tool_calls 消息补空 RC**：`build_api_messages` L1 循环曾给缺失 RC 的
   assistant 消息补 `reasoning_content: ""`。对含 `tool_calls` 的消息，补空等价于
   未回传 → 400。现仅对无 tool_calls 的普通 assistant 消息补空字段。
   另新增防御性校验：发送前扫描含 `tool_calls` 但缺少非空 RC 的消息并告警。

### 原理

DeepSeek API 是**无状态**的，但 reasoning_content 是**会话内状态**：
- 同一 `chat_stream` 内可能多次调用 API（tool_loop），reasoning_content 必须回传
- 不同 `chat_stream` 是新 API 会话，旧的 reasoning_content 已失效

## 实现

### 1. `_strip_reasoning_content` 只清除非 assistant（basesession.py）

保留所有 assistant 消息的 reasoning_content，无论是否含 tool_calls：

```python
@staticmethod
def _strip_reasoning_content(messages):
    for msg in messages:
        if msg.get("role") == "assistant":
            continue  # ← 保留所有 assistant 的 RC
        msg.pop("reasoning_content", None)
```

被以下两个入口调用：
- `_repair_incomplete_tool_chains()`：历史加载时调用，保留 assistant 的 RC
- `reset_session_state()`：新一轮 chat_stream 前调用，同样保留 assistant 的 RC

### 2. reset_session_state 保留（onlinesession.py）

清理 usage 统计和 rounds 收集器，但**保留** assistant 消息的 reasoning_content：

```python
def reset_session_state(self):
    self.api.reset_usage()
    self.api.reset_cheap_usage()
    self._rounds_collector = []
    self._extra_iterations = 0
    self._max_iter_wait.clear()
    self._strip_reasoning_content(self.context.messages)
    # 注意：_strip_reasoning_content 只清除非 assistant 的 RC，
    # assistant 消息的 RC 全部保留，保证同一 chat_stream 内 tool_loop 正确回传
```

### 3. _build_api_messages 保留（onlinesession.py）

```python
def _build_api_messages(self):
    # 不做 reasoning_content 清除！
    # tool_loop 期间的 reasoning_content 属于当前 API 会话，必须保留
    ...
```

### 4. tool_loop 期间存储

```python
assistant_msg = {"role": "assistant", "content": content, "tool_calls": [...]}
if reasoning_content:
    assistant_msg["reasoning_content"] = reasoning_content  # ← 保留
self.messages.append(assistant_msg)
```

## 便宜模型

便宜模型（用于摘要等）不开启 thinking mode，不会产生 reasoning_content，不受影响。

## 注意事项

1. **持久化保留**：rounds_json 中保留 reasoning_content，用于调试和历史回放
2. **加载保留 assistant RC**：从 DB 加载历史时**保留** assistant 消息的 reasoning_content（同一 chat_stream 内 tool_calls 的 RC 必须回传），仅由 `_strip_reasoning_content` 清除非 assistant 消息的残留 RC；跨 API 会话的旧 RC 由 DeepSeek 本身判定失效，无需手动清除
3. **兼容性**：其他模型无 reasoning_content，pop 操作无副作用
4. **tool_loop 完整性**：同一 chat_stream 内的多轮 tool_loop 正确回传 reasoning_content

## 已知 Bug 修复记录

### Bug #1: 最终文本回复重复添加 assistant 消息（2026-04-29 修复）

**症状**：多轮对话后触发 400 错误 `reasoning_content must be passed back to the API`

**根因**：`_execute_tool_loop()` 的最终文本回复分支中，`assistant_msg` 已通过 `self.messages.append()` 添加后，又调用 `self.add_assistant_message(content)` 产生第二条无 `reasoning_content` 的重复消息。

```python
# 修复前（有 bug）：
elif content:
    assistant_msg = {"role": "assistant", "content": content}
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    self.messages.append(assistant_msg)        # 第一条：有 RC
    self.add_assistant_message(content)         # 第二条：无 RC，重复！❌
    ...

# 修复后：
elif content:
    assistant_msg = {"role": "assistant", "content": content}
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    self.messages.append(assistant_msg)        # 唯一一条：有 RC ✅
    # 不再调用 add_assistant_message（内容已在上方添加）
    ...
```

**影响范围**：每次 `chat_stream` 的最终文本回复都会产生一对相邻重复消息（一条有 RC，一条无）。经过 `reset_session_state` 清除后，两条消息内容完全相同但 DeepSeek 可能识别出第一条应携带 RC，触发 400 错误。

**修复文件**：`tea_agent/onlinesession.py` - `_execute_tool_loop` 方法中的 `elif content:` 分支

### 诊断方法

可用 `toolkit_exec` 运行一段临时 Python 脚本诊断消息列表中的 RC 问题（`toolkit_diag_reasoning` 工具不存在，勿调用）：

```python
import json

def diag_reasoning(messages: list[dict]) -> list[str]:
    """检测相邻重复 assistant 消息 / tool_calls 缺失 reasoning_content。"""
    issues = []
    for i in range(1, len(messages)):
        if messages[i].get("role") == "assistant" and messages[i-1].get("role") == "assistant":
            if messages[i].get("content") == messages[i-1].get("content"):
                issues.append(f"相邻重复 assistant 消息 @ {i}")
        tc = messages[i].get("tool_calls")
        if tc and messages[i].get("reasoning_content") is None:
            issues.append(f"tool_calls 消息缺失 reasoning_content @ {i}")
    return issues

print(json.dumps(diag_reasoning(messages), ensure_ascii=False, indent=2))
```

该工具会检测：
- 相邻重复 assistant 消息
- tool_calls 消息缺失 reasoning_content
- reasoning_content 为空值
- 消息顺序异常

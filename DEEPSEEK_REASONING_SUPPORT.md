# Thinking 模式 reasoning_content 处理策略

## 核心问题

DeepSeek 推理模型在 thinking 模式下返回 `reasoning_content`（思维链内容）。API 要求：
- **同一 API 会话内**：后续请求必须将前一轮的 `reasoning_content` 原样传回
- **跨 API 会话**：上一会话的 `reasoning_content` 在新会话中无效，传回会导致 400 错误

> Error code: 400 - {'error': {'message': 'The reasoning_content in the thinking mode must be passed back to the API.'}}

## 当前策略：生命周期管理

reasoning_content 的生命周期 = 一个 `chat_stream` 调用（即一个 API 会话）。

### 生命周期边界

| 阶段 | 操作 | reasoning_content |
|------|------|-------------------|
| **加载历史** | `load_history()` | ❌ 清除（来自旧 API 会话，已失效） |
| **新一轮开始** | `reset_session_state()` | ❌ 清除（上一轮 chat_stream 遗留） |
| **tool_loop 期间** | `_build_api_messages()` | ✅ 保留（当前 API 会话内，必须回传） |
| **持久化** | `_rounds_collector` → DB | ✅ 保留（完整记录，供回放分析） |

### 原理

DeepSeek API 是**无状态**的，但 reasoning_content 是**会话内状态**：
- 同一 `chat_stream` 内可能多次调用 API（tool_loop），reasoning_content 必须回传
- 不同 `chat_stream` 是新 API 会话，旧的 reasoning_content 已失效

## 实现

### 1. load_history 清除（basesession.py）

```python
@staticmethod
def _strip_reasoning_content(messages):
    for msg in messages:
        msg.pop("reasoning_content", None)

def load_history(self, conversations, summary=""):
    ...
    rounds = conv.get("rounds_json_parsed")
    if rounds:
        self._strip_reasoning_content(rounds)  # ← 关键：清除旧会话状态
        for rd in rounds:
            self.messages.append(rd)
```

### 2. reset_session_state 清除（onlinesession.py）

```python
def reset_session_state(self):
    ...
    self._strip_reasoning_content(self.messages)  # ← 新一轮 chat_stream 前清除
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
2. **加载清除**：从 DB 加载时自动清除，确保新会话不受旧状态影响
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

### 诊断工具

可使用 `toolkit_diag_reasoning` 诊断消息列表中的 RC 问题：

```python
from toolkit_diag_reasoning import toolkit_diag_reasoning
report = toolkit_diag_reasoning(json.dumps(messages))
print(report)
```

该工具会检测：
- 相邻重复 assistant 消息
- tool_calls 消息缺失 reasoning_content
- reasoning_content 为空值
- 消息顺序异常

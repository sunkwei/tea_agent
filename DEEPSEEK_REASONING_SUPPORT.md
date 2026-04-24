# DeepSeek 推理模型支持

## 问题描述

DeepSeek 推理模型（如 deepseek-r1, deepseek-reasoner 等）有特殊的多轮对话要求：

1. **当模型输出 `reasoning_content`（思维链内容）后**，在下一轮请求中：
   - 如果之前的 assistant 消息包含 `reasoning_content` 字段，**但该轮次未进行工具调用**，必须移除 `reasoning_content`，否则 API 返回 400 错误
   - 如果之前的 assistant 消息包含 `reasoning_content` 字段，**且该轮次进行了工具调用**，必须在后续**所有**请求中完整回传 `reasoning_content`，否则 API 也会报错

## 解决方案

### 1. 模型检测

在 `OnlineToolSession` 初始化时，自动检测是否为 DeepSeek 推理模型：

```python
self._is_deepseek_reasoning = self._check_deepseek_reasoning_model(model)
```

检测逻辑：
- 模型名称包含 "deepseek"
- 且匹配特定推理模型（deepseek-reasoner, deepseek-r1, deepseek-r2 等）
- 或模型名称包含 "-r"

### 2. reasoning_content 处理逻辑

#### 核心规则：

**判断某个轮次是否进行了工具调用：**
- assistant 消息包含 `tool_calls` 字段
- 且后续有对应的 `tool` 消息（`tool_call_id` 匹配）

**处理策略：**
- **进行了工具调用的轮次**：该 assistant 消息的 `reasoning_content` 必须在后续**所有**请求中完整保留
- **未进行工具调用的轮次**：该 assistant 消息的 `reasoning_content` 必须在下一轮请求中移除

## 技术实现

### 1. 流式响应处理

新增 `_process_stream_with_reasoning` 方法，从流式响应中收集 `reasoning_content`：

```python
content, tool_calls_data, reasoning_content = self._process_stream_with_reasoning(response, callback)
```

### 2. 消息存储

在工具调用循环中，将 `reasoning_content` 保存到 assistant 消息：

```python
assistant_msg = {
    "role": "assistant",
    "content": content,
    "tool_calls": [...]
}
if reasoning_content:
    assistant_msg["reasoning_content"] = reasoning_content

self.messages.append(assistant_msg)
```

### 3. API 请求前处理

在发送 API 请求前，调用 `_handle_deepseek_reasoning_content` 方法处理消息：

```python
api_messages = self._build_api_messages()
api_messages = self._handle_deepseek_reasoning_content(api_messages)
```

处理流程：
1. 扫描所有 assistant 消息，识别哪些轮次进行了工具调用
2. 对于进行了工具调用的轮次，标记其索引
3. 遍历消息列表：
   - 如果被标记 → 保留 `reasoning_content`
   - 如果未被标记 → 移除 `reasoning_content`

```python
from tea_agent.onlinesession import OnlineToolSession

# 使用 DeepSeek 推理模型
session = OnlineToolSession(
    toolkit=toolkit,
    api_key="your-api-key",
    api_url="https://api.deepseek.com",
    model="deepseek-r1"  # 自动识别为推理模型
)

# 正常对话，内部会自动处理 reasoning_content
response, used_tools = session.chat_stream("你好", callback=print)
```

## 修改的文件

- `tea_agent/onlinesession.py`：
  - 添加 `_is_deepseek_reasoning` 属性
  - 添加 `_check_deepseek_reasoning_model()` 方法
  - 添加 `_handle_deepseek_reasoning_content()` 方法
  - 添加 `_process_stream_with_reasoning()` 方法
  - 修改 `_execute_tool_loop()` 方法

## 测试

运行测试脚本验证功能：

```bash
python test_deepseek_reasoning.py
```

测试覆盖：
- ✓ DeepSeek 推理模型检测
- ✓ 非 DeepSeek 模型检测
- ✓ 有工具调用时保留 reasoning_content
- ✓ 无工具调用时移除 reasoning_content
- ✓ 非 DeepSeek 模型不修改消息

## 注意事项

1. **兼容性**：非 DeepSeek 推理模型不受影响，保持原有行为
2. **透明性**：处理逻辑完全自动，用户无需手动干预
3. **完整性**：`reasoning_content` 会被正确存储和传递，确保模型推理连贯性

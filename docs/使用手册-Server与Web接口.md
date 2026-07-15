# Tea Agent Server + Web 接口使用手册

> 版本：0.2.0 | 更新：2026-07-15

---

## 目录

1. [快速开始](#1-快速开始)
2. [架构概览](#2-架构概览)
3. [Web UI 聊天界面](#3-web-ui-聊天界面)
4. [OpenAI 兼容 API（/v1/\*）](#4-openai-兼容-api-v1)
5. [Web 专用 API（/api/\*）](#5-web-专用-api-api)
6. [SSE 事件流参考](#6-sse-事件流参考)
7. [配置管理](#7-配置管理)
8. [高级功能](#8-高级功能)
9. [部署与运维](#9-部署与运维)
10. [排错指南](#10-排错指南)
11. [API 速查表](#11-api-速查表)

---

## 1. 快速开始

### 1.1 启动服务器

```bash
# 最小启动
python -m tea_agent.server

# 指定主机和端口
python -m tea_agent.server --host 0.0.0.0 --port 8080

# 指定配置文件
python -m tea_agent.server --config ~/.tea_agent/my-config.yaml

# 启用 API Key 认证
python -m tea_agent.server --api-key your-secret-key-here
```

启动后输出：

```
  Tea Agent Server v0.2.0
API Server starting: http://127.0.0.1:8080
API Docs: http://127.0.0.1:8080/docs
```

### 1.2 命令行入口

| 入口 | 等价命令 |
|------|----------|
| `python -m tea_agent.server` | 直接启动 |
| `tea-agent-api` | 需安装 CLI 入口（pyproject.toml） |

### 1.3 依赖

```bash
pip install starlette uvicorn
```

---

## 2. 架构概览

### 2.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│                   浏览器 (Web UI)                        │
│  ┌──────────┐  ┌───────────┐  ┌────────────────────┐   │
│  │ 聊天面板  │  │ 设置面板  │  │ 配置管理/截图等    │   │
│  └────┬─────┘  └─────┬─────┘  └────────┬───────────┘   │
└───────┼───────────────┼─────────────────┼───────────────┘
        │ POST /api/chat │ GET /api/config │ POST /api/screenshot
        ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────┐
│              Starlette HTTP Server (单进程)              │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Route Layer (route_handlers.py)                 │   │
│  │  /v1/* — OpenAI 兼容接口                         │   │
│  │  /api/* — Web UI 专用接口                        │   │
│  │  /docs  — Swagger 文档                           │   │
│  └──────────────────────┬───────────────────────────┘   │
│                         ▼                               │
│  ┌──────────────────────────────────────────────────┐   │
│  │  APIServer (核心)                                │   │
│  │  ├─ Shared Agent (非流式管理操作)                │   │
│  │  ├─ Per-request Session (流式聊天, 每请求独立)   │   │
│  │  ├─ Shared Toolkit (只读工具注册表)              │   │
│  │  └─ Shared Storage (SQLite 持久化层)             │   │
│  └──────────────────────┬───────────────────────────┘   │
│                         ▼                               │
│  ┌──────────────────────────────────────────────────┐   │
│  │  OnlineToolSession (LLM 会话引擎)                 │   │
│  │  ├─ 流式响应用 asyncio.Queue + 后台线程           │   │
│  │  ├─ SSE 事件：token / think / tool / done         │   │
│  │  ├─ toolkit_question → Web 弹窗                   │   │
│  │  └─ max_iter 超限 → 浏览器确认提示                │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

| 原则 | 说明 |
|------|------|
| **每请求独立 Session** | 流式聊天为每个请求创建独立的 `OnlineToolSession`，天然支持并发，无需全局锁 |
| **共享只读 Toolkit** | 所有请求共享同一个工具注册表（只读），避免重复加载 |
| **共享 Storage** | 单例 `SQLite Storage` 实例，所有会话共用持久化层 |
| **SSE 驱动** | Web UI 使用 Server-Sent Events（SSE）接收实时流式事件，包括 token、思考过程、工具调用 |
| **模态交互** | `toolkit_question()` 和 `max_iter` 超限通过 SSE 事件推送到浏览器，等待用户确认后继续 |

### 2.3 数据流：一次 Web 聊天请求

```
1. 浏览器 POST /api/chat {message, topic_id?, images?}
2. Server 创建独立 Session + 获取共享 Storage
3. 后台线程运行 chat_stream_sse()
4. Session 调用 LLM API（流式）
5. 回调函数逐个推送 SSE 事件到 asyncio.Queue
6. 主协程从 Queue 读取事件，返回 StreamingResponse
7. 事件类型：think_start → think* → think_done
                → tool_start → tool_args → tool_result → tool_done
                → token*
                → done (含 usage, topic_id)
8. 浏览器 SSE 解析事件，逐字渲染到聊天面板
```

---

## 3. Web UI 聊天界面

> 访问地址：`http://<host>:<port>/`

### 3.1 界面布局

```
┌─────────────────────────────────────────────────────────┐
│ [☕ Tea Agent]  [+ 新建话题]             [⚙ 设置]      │ ← 侧边栏头部
├─────────────────────────────────────────────────────────┤
│ ● 对话1 (当前)                                          │ ← 话题列表
│ ● 对话2                                                 │
│ ● 对话3                          [...]                  │
│                                                         │
│ ┌────────────────────────────────────────┐              │
│ │ [话题标题]  [工具] [记忆] [配置]       │ ← 工具栏    │
│ ├────────────────────────────────────────┤              │
│ │                                         │              │
│ │  用户消息 💬                            │ ← 消息区域  │
│ │  ┌──────────────────────────┐           │              │
│ │  │ AI 回复 ◉ 思考中...      │           │              │
│ │  │ > 调用工具: toolkit_xxx  │           │              │
│ │  │ ✓ 工具返回结果            │           │              │
│ │  │ 最终回复...               │           │              │
│ │  └──────────────────────────┘           │              │
│ │                                         │              │
│ ├────────────────────────────────────────┤              │
│ │ [📎 附件] 输入消息...    [➤ 发送]     │ ← 输入栏    │
│ │ [🎤 语音]                              │              │
│ └────────────────────────────────────────┘              │
│ [状态栏: 模型信息 | token 统计 | 配置]                   │
└─────────────────────────────────────────────────────────┘
```

### 3.2 主要功能区域

#### 侧边栏（左侧，260px）

| 元素 | 功能 |
|------|------|
| **Logo + 标题** | 显示 "Tea Agent" |
| **+ 新建话题** | 创建新对话（调用 `POST /api/new_topic`） |
| **话题列表** | 显示所有历史对话，点击切换，`...` 菜单可重命名/删除 |
| **底部设置** | 齿轮图标打开设置面板 |

#### 主面板（中间）

| 元素 | 功能 |
|------|------|
| **工具栏** | 话题标题（可点击编辑）、工具按钮、记忆按钮、配置按钮 |
| **消息流** | 交替显示用户/AI 消息，支持 Markdown 渲染 |
| **思考过程** | AI 推理过程以折叠面板显示，带 ◉ 动画 |
| **工具调用** | 实时显示工具调用 → 参数 → 结果，颜色编码 |
| **输入栏** | 文本输入 + 图片附件 + 发送按钮 |

#### 设置面板（右侧浮层）

| 标签页 | 内容 |
|--------|------|
| **模型** | 切换主模型/便宜模型，修改 temperature、max_tokens 等 |
| **配置** | 配置文件列表，创建/上传/切换配置 |
| **工具** | 列出当前所有可用的 toolkit 及其参数 |
| **记忆** | 查看和管理长期记忆 |
| **截图** | 全屏截图、区域截图、交互式选区 |

### 3.3 消息流中的事件可视化

| SSE 事件 | UI 表现 |
|----------|---------|
| `think_start` | 显示折叠面板头部「🤔 思考中...」 |
| `think` | 面板内逐字显示推理内容 |
| `think_done` | 面板变为可折叠状态 |
| `tool_start` | 显示工具调用卡片「🔧 调用: toolkit_xxx」 |
| `tool_args` | 卡片内显示参数 JSON |
| `tool_result` | 卡片内显示返回结果 |
| `tool_done` | 卡片标记完成 |
| `token` | 直接追加到 AI 回复文本 |
| `status` | 状态栏短暂显示状态文本 |
| `max_iter_confirm` | 弹出确认对话框「AI 达到最大迭代次数，继续？」 |
| `question` | 弹出提问对话框（来自 toolkit_question） |
| `done` | 完成渲染，填充 usage 信息 |
| `error` | 显示错误提示 |

### 3.4 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送消息 |
| `Shift+Enter` | 换行 |
| `Ctrl+Enter` | 发送（同 Enter） |
| `Ctrl+Shift+Enter` | 强制换行 |

### 3.5 图片上传

支持拖拽或点击上传图片，自动转换为 base64 发送。图片参数通过 `images` 字段传递，服务端保存到 `uploads/` 目录后传递给 LLM。

---

## 4. OpenAI 兼容 API（/v1/\*）

### 4.1 Chat Completions

**`POST /v1/chat/completions`**

与 OpenAI API 完全兼容，支持流式和非流式模式。

#### 请求体

```json
{
  "model": "default",
  "messages": [
    {"role": "system", "content": "你是 Tea Agent"},
    {"role": "user", "content": "Hello"}
  ],
  "stream": false,
  "temperature": 0.7,
  "max_tokens": null,
  "topic_id": "",
  "config_path": null
}
```

#### 非流式响应（stream=false）

```json
{
  "id": "chatcmpl-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "default",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "你好！我是 Tea Agent..."
    },
    "finish_reason": "stop"
  }],
  "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
  "tools_used": []
}
```

#### 流式响应（stream=true）

返回 SSE 事件流，包含 delta 块和特殊事件：

```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"你好"},"finish_reason":null}]}

// 工具调用事件
data: {"type":"tool_call","tool_calls":[...]}

// 推理过程事件
data: {"type":"reasoning","content":"让我思考一下..."}

// 完成
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"tools_used":["toolkit_search"]}

data: [DONE]
```

#### 多模态消息（图片）

```json
{
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "这张图里有什么？"},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
    ]
  }],
  "stream": true,
  "topic_id": "xxx"
}
```

### 4.2 列出模型

**`GET /v1/models`**

```json
{
  "object": "list",
  "data": [{
    "id": "gpt-4o",
    "object": "model",
    "created": 1700000000,
    "owned_by": "tea-agent"
  }]
}
```

### 4.3 列出工具

**`GET /v1/tools`**

```json
{
  "object": "list",
  "data": [{
    "name": "toolkit_search",
    "description": "搜索工具...",
    "parameters": {"type": "object", "properties": {...}}
  }],
  "total": 42
}
```

### 4.4 运行工具

**`POST /v1/tools/{name}/run`**

```json
// 请求
{"arguments": {"query": "天气", "max_results": 5}}

// 响应
{"ok": true, "tool": "toolkit_search", "result": "{...}"}
```

### 4.5 会话管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/sessions` | GET | 列出所有会话（话题） |
| `/v1/sessions` | POST | 创建新会话 `{"title": "..."}` |
| `/v1/sessions/{topic_id}` | GET | 获取会话详情（含对话历史） |
| `/v1/sessions/{topic_id}` | DELETE | 删除会话 |
| `/v1/sessions/{topic_id}/messages` | GET | 获取消息列表 `?limit=50` |

#### 创建会话示例

```bash
curl -X POST http://localhost:8080/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "代码审查会话"}'
# → {"id": "uuid-topic-id", "title": "代码审查会话"}
```

### 4.6 配置管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/config` | GET | 获取当前配置详情 |
| `/v1/config/switch` | POST | 切换配置文件 `{"config_path": "..."}` |

### 4.7 记忆管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/memory` | GET | 列出所有记忆 `?limit=50` |
| `/v1/memory` | POST | 创建记忆 `{"content": "...", "category": "general", "priority": 2}` |
| `/v1/memory/{mem_id}` | DELETE | 删除记忆 |

### 4.8 任务管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/v1/tasks` | GET | 列出所有定时任务 |
| `/v1/tasks` | POST | 创建定时任务 `{"name": "...", "command": "...", "schedule": "..."}` |
| `/v1/tasks/{task_id}` | DELETE | 删除任务 |

### 4.9 搜索

**`GET /v1/search?q=关键词&limit=20`**

跨对话历史和记忆搜索：

```json
{
  "conversations": [...],
  "memories": [...]
}
```

### 4.10 导出 PDF

**`GET /v1/export/pdf/{topic_id}?mode=latest&filter=final`**

| 参数 | 值 | 说明 |
|------|----|------|
| `mode` | `latest` / `full_topic` | 仅最新对话 / 全部对话 |
| `filter` | `final` / `full` | 仅最终消息（无思考过程）/ 含推理过程 |

返回 `application/pdf` 文件下载。

### 4.11 文件上传

**`POST /v1/upload`**

```bash
curl -X POST http://localhost:8080/v1/upload \
  -F "file=@path/to/file.pdf"
# → {"path": "uploads/file.pdf", "url": "/uploads/file.pdf"}
```

---

## 5. Web 专用 API（/api/\*）

这些 API 专为 Web UI 设计，提供更丰富的事件和操作。

### 5.1 流式聊天

**`POST /api/chat`** — Web UI 主聊天接口

```json
{
  "message": "你好，请分析这段代码",
  "topic_id": "",        // 可选，空=新建话题
  "config_path": null,    // 可选，指定配置文件
  "images": [              // 可选，base64 图片列表
    "data:image/png;base64,..."
  ]
}
```

返回 SSE 事件流，事件类型详见[第6节](#6-sse-事件流参考)。

### 5.2 继续/确认

**`POST /api/chat/continue`** — 当 AI 达到 max_iter 上限时，用户确认是否继续

```json
{"confirm_id": "xxx", "continue": true}
```

**`POST /api/chat/question`** — 用户回答 AI 的提问

```json
{"question_id": "xxx", "answer": "使用Python"}
```

**`POST /api/chat/abort`** — 中断当前正在进行的对话

```json
{"topic_id": "xxx"}
```

### 5.3 话题管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/new_topic` | POST | 创建新话题 `{"title": "..."}` |
| `/api/sessions` | GET | 列出所有话题 `?limit=20` |
| `/api/topic/{topic_id}` | GET | 获取话题信息 |
| `/api/topic/{topic_id}` | PUT | 重命名话题 `{"title": "新名称"}` |
| `/api/topic/{topic_id}` | DELETE | 删除话题 |
| `/api/topic/{topic_id}/conversations` | GET | 获取对话历史 `?limit=0` |
| `/api/topic/{topic_id}/todos` | GET | 获取话题 TODO 清单 |
| `/api/topic/{topic_id}/todos/{idx}` | PUT | 更新 TODO 完成状态 `{"done": true}` |
| `/api/topic/{topic_id}/plans` | GET | 获取话题执行计划列表 |

### 5.4 截图

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/screenshot/full` | GET | 全屏截图，返回 base64 |
| `/api/screenshot/region` | POST | 区域截图 `{"x":0, "y":0, "w":800, "h":600}` |
| `/api/screenshot/interactive` | POST | 交互式选区（系统级 tkinter 界面） |

交互式选区的响应：

```json
{
  "ok": true,
  "image_base64": "data:image/png;base64,...",
  "width": 800,
  "height": 600,
  "x": 100,
  "y": 200,
  "w": 800,
  "h": 600
}
```

### 5.5 配置与工具

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/config` | GET | 获取配置详情（含便宜模型） |
| `/api/config` | PUT | 更新运行时配置 `{"max_iterations": 100}` |
| `/api/configs` | GET | 列出 ~/.tea_agent/ 下所有配置文件 |
| `/api/config/create` | POST | 创建新配置文件 |
| `/api/config/upload` | POST | 上传 .yaml 配置文件 |
| `/api/tools` | GET | 列出所有可用工具 |

**`PUT /api/config` 可更新字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `max_iterations` | int | 最大工具调用轮数 |
| `max_history` | int | 最大历史消息数 |
| `keep_turns` | int | 保留最新轮数 |
| `max_tool_output` | int | 工具输出最大字符数 |
| `max_assistant_content` | int | AI 回复最大字符数 |
| `extra_iterations_on_continue` | int | 用户确认后续加轮数 |
| `memory_extraction_threshold` | float | 记忆提取阈值 |
| `memory_dedup_threshold` | float | 记忆去重阈值 |
| `chat_page_size` | int | 聊天分页大小 |
| `history_l2_max` | int | L2 摘要最大数 |
| `history_l3_batch` | int | L3 批处理大小 |
| `enable_thinking` | bool | 是否显示推理过程 |

### 5.6 模型切换

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/model` | GET | 获取当前模型信息（同 /api/config） |
| `/api/model` | POST | 热切换模型 |
| `/api/model/config` | POST | 从文件切换配置 |

**模型热切换 POST /api/model：**

```json
{
  "api_key": "sk-xxx",
  "api_url": "https://api.openai.com/v1",
  "model_name": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 131072,
  "top_p": 1.0,
  "max_context_tokens": 128000,
  "options": {"supports_vision": true, "supports_reasoning": true},
  "cheap_api_key": "sk-xxx",
  "cheap_api_url": "https://api.deepseek.com",
  "cheap_model_name": "deepseek-chat",
  "cheap_temperature": 0.3,
  "cheap_max_tokens": 8192
}
```

---

## 6. SSE 事件流参考

Web UI 聊天（`POST /api/chat`）返回 SSE 事件流，每行 `data: <json>\n\n`。

### 6.1 事件类型一览

| 事件 type | 方向 | 说明 | 关键字段 |
|-----------|------|------|----------|
| `think_start` | → | AI 开始推理 | — |
| `think` | → | 推理内容片段 | `text` |
| `think_done` | → | 推理结束 | — |
| `tool_start` | → | 开始调用工具 | `name` |
| `tool_args` | → | 工具参数 JSON | `args` |
| `tool_result` | → | 工具返回结果 | `result` |
| `tool_done` | → | 工具调用完成 | — |
| `token` | → | AI 回复文本片段 | `text` |
| `status` | → | 状态信息 | `text` |
| `max_iter_confirm` | → | 达到迭代上限，需确认 | `confirm_id`, `text` |
| `question` | → | AI 向用户提问 | `question_id`, `title`, `question`, `options`, `default` |
| `done` | → | 对话完成 | `ai_msg`, `used_tools`, `topic_id`, `usage` |
| `error` | → | 发生错误 | `error` |

### 6.2 典型事件序列

```
无工具调用（纯对话）:
  think_start → think* → think_done → token* → done

有工具调用:
  think_start → think* → think_done
  → tool_start → tool_args → tool_result → tool_done
  → think_start → think* → think_done
  → token* → done

需要用户确认:
  ... → max_iter_confirm → (用户确认) → tool_start → ...
  ... → question → (用户回答) → token* → done

多种工具连续调用:
  think_start → think* → think_done
  → tool_start(a) → tool_args(a) → tool_result(a) → tool_done
  → think* → think_done
  → tool_start(b) → tool_args(b) → tool_result(b) → tool_done
  → token* → done
```

### 6.3 done 事件字段

```json
{
  "type": "done",
  "ai_msg": "最终回复文本",
  "used_tools": ["toolkit_search", "toolkit_exec"],
  "topic_id": "uuid",
  "usage": {
    "total_tokens": 1500,
    "prompt_tokens": 800,
    "completion_tokens": 700
  }
}
```

### 6.4 max_iter_confirm 事件

当 AI 工具调用轮数达到 `max_iterations` 上限时触发。浏览器需弹出确认框：

```json
{
  "type": "max_iter_confirm",
  "confirm_id": "a1b2c3d4e5f6",
  "text": "!MAX_ITER: AI 已达到最大迭代次数 (100)"
}
```

用户操作后调用 `POST /api/chat/continue`：

```json
{"confirm_id": "a1b2c3d4e5f6", "continue": true}
```

### 6.5 question 事件

当 AI 调用 `toolkit_question()` 向用户提问时触发：

```json
{
  "type": "question",
  "question_id": "a1b2c3d4e5f6",
  "title": "选择答案",
  "question": "您希望使用哪种编程语言？",
  "options": ["Python", "JavaScript", "Go"],
  "default": "Python"
}
```

用户回答后调用 `POST /api/chat/question`：

```json
{"question_id": "a1b2c3d4e5f6", "answer": "Python"}
```

---

## 7. 配置管理

### 7.1 配置文件位置

默认路径：`~/.tea_agent/*.yaml`

启动时可以指定：`--config ~/.tea_agent/my-config.yaml`

### 7.2 配置文件结构

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  temperature: 0.65
  max_tokens: 131072
  options:
    supports_vision: false
    supports_reasoning: true

cheap_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com"
  model_name: "deepseek-chat"
  max_tokens: 8192
  options:
    supports_vision: false
    supports_reasoning: true

embedding_model:  # 可选，用于记忆语义搜索
  api_url: "https://api.siliconflow.cn"
  model_name: "Qwen/Qwen3-Embedding-4B"
  api_key: "sk-xxx"
  dimension: 2560

# 运行时参数
max_history: 10
max_iterations: 100
enable_thinking: true
keep_turns: 5
max_tool_output: 128000
max_assistant_content: 128000
extra_iterations_on_continue: 25
memory_extraction_threshold: 2
memory_dedup_threshold: 0.3
chat_page_size: 50
history_l2_max: 30
history_l3_batch: 10
```

### 7.3 配置管理方式

| 方式 | 说明 |
|------|------|
| **Web UI 设置面板** | 可视化创建/上传/切换配置 |
| **API 热切换** | `POST /api/model` 或 `POST /api/model/config` |
| **配置文件切换** | `POST /v1/config/switch {"config_path": "..."}` |
| **CLI 参数** | `--config` 启动时指定 |
| **运行时更新** | `PUT /api/config` 更新单字段 |

### 7.4 配置文件管理 API

**列出配置文件** `GET /api/configs`：

```json
{
  "configs": [{
    "filename": "my-config.yaml",
    "path": "C:/Users/xxx/.tea_agent/my-config.yaml",
    "is_valid": true,
    "main_model": {
      "model_name": "gpt-4o",
      "api_url": "https://api.openai.com/v1",
      "api_key_masked": "sk-xxx...xxxx"
    },
    "cheap_model": {
      "model_name": "deepseek-chat",
      "api_url": "https://api.deepseek.com",
      "api_key_masked": "sk-xxx...xxxx"
    }
  }],
  "count": 3,
  "any_valid": true,
  "active_config_path": "C:/Users/xxx/.tea_agent/config.yaml",
  "active_config_filename": "config.yaml"
}
```

**创建配置文件** `POST /api/config/create`：

```json
{
  "filename": "my-config",
  "main_model_name": "gpt-4o",
  "main_api_url": "https://api.openai.com/v1",
  "main_api_key": "sk-xxx",
  "cheap_model_name": "deepseek-chat",
  "cheap_api_url": "https://api.deepseek.com",
  "cheap_api_key": "sk-xxx"
}
```

**上传配置文件** `POST /api/config/upload`（multipart/form-data）：

上传 `.yaml` 文件后自动验证配置有效性，若有效则自动切换。

---

## 8. 高级功能

### 8.1 截图功能

三种截图方式：

| 方式 | 端点 | 说明 |
|------|------|------|
| 全屏截图 | `GET /api/screenshot/full` | 一键截取整个屏幕 |
| 区域截图 | `POST /api/screenshot/region` | 指定坐标和尺寸 `{x,y,w,h}` |
| 交互式选区 | `POST /api/screenshot/interactive` | 系统级 tkinter 界面，拖动选择区域 |

返回均为包含 `image_base64` 的 JSON，可直接嵌入 `<img>` 标签。

### 8.2 长期记忆

记忆分为多个类别：

| 类别 | 说明 |
|------|------|
| `instruction` | 用户指令/偏好 |
| `preference` | 用户偏好设置 |
| `fact` | 事实信息 |
| `reminder` | 提醒事项 |
| `general` | 通用记忆 |

优先级：`0=CRITICAL > 1=HIGH > 2=MEDIUM > 3=LOW`

### 8.3 定时任务

创建定时任务后，Tea Agent 会在后台按计划执行命令。

schedule 格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| `once:ISO` | `once:2026-07-15T10:00:00` | 单次执行 |
| `daily:HH:MM` | `daily:09:00` | 每天执行 |
| `hourly:MM` | `hourly:30` | 每小时执行 |
| `interval:SEC` | `interval:3600` | 每隔 N 秒执行 |
| `weekly:DAY:HH:MM` | `weekly:mon:09:00` | 每周某天执行 |
| `cron:M H D Mon W` | `cron:0 9 * * 1-5` | 标准 cron 表达式 |

### 8.4 中断机制

当 AI 响应时间过长或进入循环时，用户可以随时中断：

- **Web UI**：发送 `POST /api/chat/abort` + `topic_id`
- **原理**：调用 `session.interrupt()` 设置中断标志，后台线程在下次检查时优雅退出

### 8.5 健康检查

**`GET /health`**

```json
{
  "status": "ok",
  "version": "0.2.0",
  "uptime_seconds": 3600.0,
  "agent_initialized": true
}
```

---

## 9. 部署与运维

### 9.1 生产部署

使用 `uvicorn` 直接启动（更稳定）：

```bash
# 直接运行
python -m tea_agent.server --host 0.0.0.0 --port 8080

# 或通过 uvicorn
uvicorn tea_agent.server:create_app --host 0.0.0.0 --port 8080
```

### 9.2 环境变量

| 变量 | 说明 |
|------|------|
| `TEA_API_KEY` | API Key 认证（可选） |

### 9.3 API Key 认证

当指定 `--api-key` 或设置 `TEA_API_KEY` 环境变量时，所有 API 请求需要在 Header 中包含：

```
Authorization: Bearer <your-api-key>
```

### 9.4 存储

所有数据存储在 SQLite 数据库中，默认路径为 `tea_agent/chat_history.db`。

主要表：

| 表 | 说明 |
|----|------|
| `topics` | 话题/会话 |
| `conversations` | 对话记录（含用户消息、AI 回复、工具调用轮次） |
| `topic_tokens` | Token 使用统计 |
| `level2_summaries` | L2 级别摘要 |
| `memories` | 长期记忆 |
| `tasks` | 定时任务 |
| `todo_items` | TODO 清单 |

### 9.5 日志

| 日志源 | 级别 | 说明 |
|--------|------|------|
| `api_server` | INFO | 服务器核心日志 |
| `uvicorn.access` | WARNING | HTTP 访问日志（默认静音） |
| `uvicorn.error` | WARNING | Uvicorn 错误日志 |

### 9.6 并发与性能

| 特性 | 说明 |
|------|------|
| 并发聊天 | ✅ 支持（每请求独立 Session）|
| 并发工具调用 | ✅ 支持（共享只读 Toolkit）|
| 流式响应 | ✅ SSE 流式输出 |
| 中断支持 | ✅ POST /api/chat/abort |
| 连接数 | 默认无限制（依赖 uvicorn 配置）|

---

## 10. 排错指南

### 10.1 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `"Agent not configured"` | 配置文件无效或缺失 | 检查 `~/.tea_agent/` 下的配置文件 |
| `ModuleNotFoundError: starlette` | 缺少依赖 | `pip install starlette uvicorn` |
| `SSE 连接断开` | 后台线程异常 | 查看服务端日志，检查 API Key |
| `max_iter_confirm` 频繁触发 | `max_iterations` 太小 | `PUT /api/config` 增大 |
| `截图返回空` | Wayland 下截图方式不支持 | 使用交互式选区 `POST /api/screenshot/interactive` |
| `"confirm_id not found"` | 请求超时（默认无超时）| 确认请求未过期 |

### 10.2 调试技巧

```bash
# 检查服务状态
curl http://localhost:8080/health

# 测试配置
curl http://localhost:8080/api/config | python -m json.tool

# 测试简单对话
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}' \
  --no-buffer

# 查看所有工具
curl http://localhost:8080/api/tools | python -m json.tool
```

### 10.3 重置

```bash
# 删除聊天历史（谨慎）
rm tea_agent/chat_history.db

# 重置 Agent
# 重启服务器即可自动重新初始化
```

---

## 11. API 速查表

### Web UI API（/api/*）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/chat` | 流式聊天（SSE） |
| POST | `/api/chat/continue` | 确认继续 |
| POST | `/api/chat/question` | 回答问题 |
| POST | `/api/chat/abort` | 中断对话 |
| POST | `/api/new_topic` | 新建话题 |
| GET | `/api/sessions` | 话题列表 |
| GET | `/api/topic/{id}` | 话题详情 |
| PUT | `/api/topic/{id}` | 重命名 |
| DELETE | `/api/topic/{id}` | 删除 |
| GET | `/api/topic/{id}/conversations` | 对话历史 |
| GET | `/api/topic/{id}/todos` | TODO 清单 |
| PUT | `/api/topic/{id}/todos/{idx}` | 更新 TODO |
| GET | `/api/topic/{id}/plans` | 执行计划 |
| GET | `/api/config` | 配置详情 |
| PUT | `/api/config` | 更新配置 |
| GET | `/api/configs` | 配置文件列表 |
| POST | `/api/config/create` | 创建配置 |
| POST | `/api/config/upload` | 上传配置 |
| GET | `/api/model` | 模型信息 |
| POST | `/api/model` | 切换模型 |
| POST | `/api/model/config` | 切换配置文件 |
| GET | `/api/tools` | 工具列表 |
| GET | `/api/screenshot/full` | 全屏截图 |
| POST | `/api/screenshot/region` | 区域截图 |
| POST | `/api/screenshot/interactive` | 交互式选区 |

### OpenAI 兼容 API（/v1/*）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | 聊天（流式/非流式） |
| GET | `/v1/models` | 模型列表 |
| GET | `/v1/tools` | 工具列表 |
| POST | `/v1/tools/{name}/run` | 运行工具 |
| GET | `/v1/sessions` | 会话列表 |
| POST | `/v1/sessions` | 创建会话 |
| GET | `/v1/sessions/{id}` | 会话详情 |
| DELETE | `/v1/sessions/{id}` | 删除会话 |
| GET | `/v1/sessions/{id}/messages` | 消息列表 |
| GET | `/v1/config` | 配置详情 |
| POST | `/v1/config/switch` | 切换配置 |
| GET | `/v1/memory` | 记忆列表 |
| POST | `/v1/memory` | 创建记忆 |
| DELETE | `/v1/memory/{id}` | 删除记忆 |
| GET | `/v1/tasks` | 任务列表 |
| POST | `/v1/tasks` | 创建任务 |
| DELETE | `/v1/tasks/{id}` | 删除任务 |
| GET | `/v1/search` | 搜索 |
| GET | `/v1/export/pdf/{id}` | 导出 PDF |
| POST | `/v1/upload` | 文件上传 |

### 系统端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/docs` | Swagger API 文档 |
| GET | `/openapi.json` | OpenAPI 规范 |
| GET | `/` | Web UI 主页 |
| GET | `/static/*` | 静态文件 |

---

> — 完 —

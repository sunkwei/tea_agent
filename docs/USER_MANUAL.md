# Tea Agent 用户手册

> 版本 0.2.0 | 最后更新: 2026-07-17

---

## 目录

1. [项目概述](#1-项目概述)
2. [启动入口与使用模式](#2-启动入口与使用模式)
3. [系统架构总览](#3-系统架构总览)
4. [Server 与 Web 接口详解](#4-server-与-web-接口详解)
5. [Multi-Agent 多智能体协作](#5-multi-agent-多智能体协作)
6. [核心模块详解](#6-核心模块详解)
7. [模块间依赖关系](#7-模块间依赖关系)
8. [配置系统](#8-配置系统)
9. [工具系统 (Toolkit)](#9-工具系统-toolkit)
10. [FAQ](#10-faq)

---

## 1. 项目概述

Tea Agent 是一个可自我扩展的智能 Agent 框架，核心理念是 **"Agent 不仅使用工具，还能创造工具"**。

### 核心能力

| 能力 | 说明 |
|------|------|
| 🛠 工具自创建 | Agent 可动态创建/修改/组合 Python 工具函数 |
| 💬 多会话管理 | Topic 级别的对话历史、摘要、记忆 |
| 🤖 Multi-Agent | 角色化 Agent + 事件驱动 Flow + 工作流 DAG |
| 🔄 自我进化 | 运行时优化提示词、记录经验、反思改进 |
| 🌐 Web UI | 浏览器聊天界面 + 实时 SSE 流 |
| 📡 REST API | OpenAI 兼容接口 + 管理 API |

### 技术栈

```
Python 3.11+ / Starlette + Uvicorn / OpenAI SDK / SQLite / Tkinter (可选)
```

---

## 2. 启动入口与使用模式

### 2.1 九种启动入口一览

```
┌──────────────────────────────────────────────────────────────┐
│                    Tea Agent 启动方式                         │
├──────────────┬──────────────────┬────────────────────────────┤
│   类型       │   命令            │   说明                     │
├──────────────┼──────────────────┼────────────────────────────┤
│ CLI 脚本     │ tea-agent-cli    │ 命令行交互模式              │
│              │ tea_agent        │ 老 GUI (tkinter)           │
│              │ tea-agent-api    │ HTTP API 服务               │
│              │ tea-agent-mini   │ 迷你版 Agent               │
│              │ tea-agent-acp    │ ACP 协议服务器              │
├──────────────┼──────────────────┼────────────────────────────┤
│ -m 模块      │ python -m tea_agent.server    │ API 服务       │
│              │ python -m tea_agent.gui2      │ Web 桌面(推荐) │
│              │ python -m tea_agent.protocol  │ ACP 协议       │
│              │ python -m tea_agent_mini      │ 迷你版         │
└──────────────┴──────────────────┴────────────────────────────┘
```

### 2.2 推荐使用模式

**快速开始（Web UI）**:
```bash
python -m tea_agent.server
# 浏览器访问 http://127.0.0.1:8080
```

**带 API Key 认证**:
```bash
python -m tea_agent.server --api-key YOUR_SECRET_KEY
# 接口需 Header: Authorization: Bearer YOUR_SECRET_KEY
```

**指定配置文件**:
```bash
python -m tea_agent.server --config ~/.tea_agent/my_config.yaml --port 9090
```

**CLI 交互模式**:
```bash
tea-agent-cli
# 进入终端交互式对话
```

---

## 3. 系统架构总览

### 3.1 分层架构图

```
                    ┌─────────────────────────────────┐
                    │         用户界面层               │
                    │   Web UI (static/)  │  CLI/GUI   │
                    └────────────┬────────────────────┘
                                 │ HTTP / stdin
                    ┌────────────▼────────────────────┐
                    │         接入层                   │
                    │  Starlette Router (route_handlers)│
                    │  + OpenAI API + SSE Stream        │
                    │  + Auth Middleware                │
                    └────────────┬────────────────────┘
                                 │
                    ┌────────────▼────────────────────┐
                    │         服务层                   │
                    │  APIServer (server.py)           │
                    │  · 会话工厂 (create_session)     │
                    │  · 流式调度 (chat_stream_sse)    │
                    │  · 配置管理 (switch_model)       │
                    └────────────┬────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
    ┌─────────▼──────┐ ┌────────▼────────┐ ┌──────▼───────┐
    │  Agent 层      │ │  Session 层     │ │  Storage 层  │
    │  (agent.py)    │ │  (onlinesession)│ │  (store/)    │
    │  · 3 种模式    │ │  · API 通信     │ │  · SQLite    │
    │  · 后处理管道  │ │  · 工具循环     │ │  · 9 个组件   │
    │  · 异步摘要    │ │  · 历史构建     │ │  · 向量存储   │
    └────────┬───────┘ └────────┬────────┘ └──────┬───────┘
             │                  │                  │
    ┌────────▼──────────────────▼──────────────────▼───────┐
    │                    Toolkit 层                         │
    │  tlk.py (工具引擎) ── toolkit/ (70+ 工具函数)        │
    │  · 动态加载/注册/执行  · 版本管理  · self-evolve      │
    └─────────────────────┬────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────┐
    │               Multi-Agent 层                         │
    │  multi_agent/ (6 Phase 架构)                         │
    │  · RoleAgent  · FlowEngine  · MessageBus             │
    │  · WorkflowDAG  · ExecutionPool  · PatternMarket     │
    └──────────────────────────────────────────────────────┘
```

### 3.2 核心数据流

```
用户输入
  │
  ▼
route_handlers.handle_web_chat()
  │
  ▼
APIServer.chat_stream_sse()  ── 创建独立 Session
  │
  ▼
OnlineToolSession.chat_stream()  ── 调用 LLM API
  │
  ├── LLM 返回文本 → SSE token 事件 → 前端渲染
  │
  ├── LLM 请求工具调用 → execute_tool_loop()
  │   │
  │   ├── toolkit.func_map[name](**args)  ── 执行工具
  │   │
  │   ├── 结果注入 messages → 继续 LLM 对话
  │   │
  │   └── 循环直到 LLM 停止调用工具
  │
  └── 对话完成 → _save_chat_result() → Storage
                    └── do_async_summaries()  ── 后台摘要
```", "## 4. Server 与 Web 接口详解

### 4.1 服务架构

Server 基于 **Starlette + Uvicorn** 构建，支持并发流式连接。

```python
# 核心类关系
class APIServer:
    """HTTP API Server for Tea Agent"""
    
    # 共享资源（跨请求复用）
    _toolkit: Toolkit        # 工具库单例
    _storage: Storage        # 数据库单例
    _agent: Agent            # 非流式操作用（admin/config）
    
    # 每请求独立
    def create_session() -> (OnlineToolSession, Storage)
    def chat_stream_sse()  # Web UI SSE 流式对话
    def chat_completion_stream()  # OpenAI 兼容流式
```

**并发设计**：
- 非流式操作（配置查询/工具列表）：使用共享 `_agent`
- 流式操作（SSE 对话）：每请求创建独立 `OnlineToolSession`
- `Toolkit` 和 `Storage` 跨请求共享（只读），Session 完全隔离

### 4.2 Web UI 接口 (HTTP API)

#### 4.2.1 对话相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | SSE 流式对话（Web UI 主通道） |
| POST | `/api/chat/continue` | 继续生成（max_iter 确认后） |
| POST | `/api/chat/question` | 回答 Agent 的提问 |
| POST | `/api/chat/abort` | 中断当前对话 |
| POST | `/api/new_topic` | 创建新主题 |

**SSE 流式对话 (`POST /api/chat`)**

请求体:
```json
{
  "message": "请分析这个项目的架构",
  "topic_id": "abc123"  // 可选，空则创建新主题
}
```

SSE 事件流:
```
data: {"type": "token", "text": "正在"}
data: {"type": "token", "text": "分析"}
data: {"type": "think", "text": "让我看看..."}
data: {"type": "tool_start", "name": "toolkit_file"}
data: {"type": "tool_args", "args": "..."}
data: {"type": "tool_result", "result": "..."}
data: {"type": "tool_done"}
data: {"type": "done", "ai_msg": "...", "usage": {...}}
data: [DONE]
```

SSE 事件类型:

| 类型 | 说明 |
|------|------|
| `token` | 文本输出片段 |
| `think_start` / `think` / `think_done` | 思考推理过程 |
| `tool_start` | 工具开始调用 |
| `tool_args` | 工具参数 |
| `tool_result` | 工具返回结果 |
| `tool_done` | 工具执行完成 |
| `status` | 状态消息 |
| `max_iter_confirm` | 达到迭代上限，请求确认 |
| `question` | Agent 向用户提问 |
| `dag_viz` | DAG 可视化嵌入 |
| `done` | 对话完成（含 usage 统计） |
| `error` | 错误 |

**中断请求 (`POST /api/chat/abort`)**

请求体:
```json
{
  "topic_id": "abc123"
}
```

中断机制: 通过 `_active_sessions` 找到对应的 `session` 实例，调用 `session.interrupt()` 设置中断标志，下一轮工具循环检测到标志后退出。

**重启服务器 (`POST /api/restart`)**

请求体: `{}` (空)

响应:
```json
{
  "ok": true,
  "message": "Server restart initiated"
}
```

机制: spawn 新进程（相同参数）→ 1.5s 后 graceful shutdown 当前进程。

#### 4.2.2 主题/会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 列出所有主题 |
| GET | `/api/topic/{topic_id}` | 获取主题详情 |
| PUT | `/api/topic/{topic_id}` | 重命名主题 |
| DELETE | `/api/topic/{topic_id}` | 删除主题 |
| GET | `/api/topic/{topic_id}/conversations` | 获取主题对话记录 |
| GET | `/api/topic/{topic_id}/todos` | 获取主题 TODO 列表 |
| PUT | `/api/topic/{topic_id}/todos/{idx}` | 更新 TODO 状态 |
| GET | `/api/topic/{topic_id}/plans` | 获取主题计划列表 |

#### 4.2.3 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前配置 |
| PUT | `/api/config` | 更新运行时配置 |
| GET | `/api/configs` | 列出所有配置文件 |
| POST | `/api/config/create` | 创建新配置文件 |
| POST | `/api/config/upload` | 上传配置文件 |
| GET | `/api/model` | 获取模型信息 |
| POST | `/api/model` | 切换模型（热切换） |
| POST | `/api/model/config` | 切换配置文件 |

**模型热切换 (`POST /api/model`)**:
```json
{
  "api_key": "sk-xxx",
  "api_url": "https://api.deepseek.com",
  "model_name": "deepseek-chat"
}
```

切换过程: 保存当前 topic_id → 关闭旧 session → 更新配置 → 重新初始化 session → 恢复 topic。无需重启服务器。

#### 4.2.4 截图功能

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/screenshot/region` | 区域截图 (base64) |
| GET | `/api/screenshot/full` | 全屏截图 (base64) |
| POST | `/api/screenshot/interactive` | 交互式截图选择 |

### 4.3 OpenAI 兼容接口 (v1 API)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/completions` | 标准 Chat Completion |
| GET | `/v1/models` | 模型列表 |
| GET | `/v1/tools` | 工具列表 |
| POST | `/v1/tools/{name}/run` | 执行工具 |
| GET/POST | `/v1/sessions` | 会话管理 |
| GET | `/v1/config` | 配置查询 |
| POST | `/v1/config/switch` | 切换配置 |
| GET/POST/DELETE | `/v1/memory` | 记忆管理 |
| GET/POST/DELETE | `/v1/tasks` | 定时任务 |
| GET | `/v1/search` | 全文搜索 |

**Chat Completion 使用示例**:

```python
import requests

response = requests.post(
    "http://localhost:8080/v1/chat/completions",
    json={
        "model": "default",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": False,
        "topic_id": "my-topic"  # 可选，控制会话
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

**流式 Chat Completion**:

```python
import requests

with requests.post(
    "http://localhost:8080/v1/chat/completions",
    json={"model": "default", "messages": [...], "stream": True},
    stream=True
) as r:
    for line in r.iter_lines():
        if line.startswith(b"data: "):
            data = line[6:].decode()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            content = chunk["choices"][0]["delta"].get("content")
            if content:
                print(content, end="")
```

### 4.4 API Key 认证

如果启动时设置 `--api-key`，中间件自动拦截所有非公开路径:

```bash
# 启动
tea-agent-api --api-key my-secret

# 请求需要认证
curl -H "Authorization: Bearer my-secret" http://localhost:8080/v1/models
# 或
curl -H "X-API-Key: my-secret" http://localhost:8080/v1/models
```

公开路径（不需要认证）: `/health`, `/docs`, `/openapi.json`, `/`, `/static/*`

### 4.5 前端 Web UI

Web UI 位于 `tea_agent/server/static/`，由 `index.html` + `app.js` + `style.css` 组成，采用纯原生 JavaScript（无框架依赖）。

功能特性:
- 暗色/亮色主题切换
- 实时流式对话（SSE）
- 多主题管理（创建/切换/删除）
- 工具调用过程可视化
- 思考推理过程展示
- 模型热切换
- 配置文件管理
- DAG 可视化嵌入

", "## 5. Multi-Agent 多智能体协作

### 5.1 架构总览（6 Phase）

Multi-Agent 系统采用渐进式架构，分 6 个 Phase 逐步增强:

```
Phase 1: 核心架构          Phase 2: Agent 间通信
┌──────────────────┐     ┌──────────────────────┐
│ RoleAgent        │     │ MessageBus           │
│ (角色化 Agent)    │     │ (发布/订阅消息队列)   │
│                  │     │                      │
│ FlowEngine       │     │ AgentTool            │
│ (事件驱动流程)    │     │ (Agent → 可调用工具)  │
│                  │     │                      │
│ RoleDispatcher   │     │ ToolRegistry         │
│ (调度器)         │     │ (统一工具发现)        │
└──────────────────┘     └──────────────────────┘
         │                        │
         ▼                        ▼
Phase 3: 持久化+可观测    Phase 4: 管理+市场
┌──────────────────┐     ┌──────────────────────┐
│ CheckpointManager│     │ PatternMarket        │
│ (执行状态持久化)  │     │ (可复用模式仓库)      │
│                  │     │                      │
│ TraceEngine      │     │ AdminPanel           │
│ (Span-based 追踪)│     │ (统一管理界面)        │
└──────────────────┘     └──────────────────────┘
         │                        │
         ▼                        ▼
Phase 5: 并行执行引擎    Phase 6: 高级编排
┌──────────────────┐     ┌──────────────────────┐
│ ExecutionPool    │     │ WorkflowDAG          │
│ (双通道并行池)    │     │ (6种节点类型)        │
│                  │     │                      │
│ LoadBalancer     │     │ WorkflowExec         │
│ (智能负载均衡)    │     │ (状态机执行器)        │
│                  │     │                      │
│ ResourceGuard    │     │ WorkflowVisualizer   │
│ (资源隔离保护)    │     │ (Mermaid 可视化)      │
└──────────────────┘     └──────────────────────┘
```

### 5.2 RoleAgent — 角色化 Agent

借鉴 CrewAI 的角色设计理念，每个 Agent 有明确的 **身份 (role)**、**目标 (goal)** 和 **背景故事 (backstory)**。

```python
from tea_agent.multi_agent import RoleAgent

analyst = RoleAgent(
    role="资深代码审查员",
    goal="分析代码质量问题并给出改进建议",
    backstory="你有 15 年后端架构经验，擅长发现代码坏味道",
    tools=["toolkit_file", "toolkit_search", "toolkit_lsp"],  # 工具白名单
    max_iterations=20,
)

# 执行任务
result = analyst.execute("审查 dispatcher.py 的设计")

# 带结构化输出
result = analyst.execute(
    "审查代码",
    output_model=CodeReview  # Pydantic 模型
)
```

**内置角色工厂**:
```python
from tea_agent.multi_agent import create_analyst, create_coder, create_tester, create_reviewer

analyst = create_analyst("代码质量分析")
coder = create_coder("实现新功能")
tester = create_tester("单元测试编写")
reviewer = create_reviewer("代码审查")
```

### 5.3 FlowEngine — 事件驱动流程引擎

借鉴 CrewAI Flows + LangGraph StateGraph，实现声明式工作流:

```python
from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

class RefactorFlow(FlowEngine):
    @flow_start()
    def analyze(self):
        """步骤1: 分析代码"""
        agent = create_analyst()
        result = agent.execute("分析项目结构")
        self.state["analysis"] = result.output
        return result.output

    @flow_listen(analyze)
    def plan(self):
        """步骤2: 制定计划（依赖 analyze 完成后自动触发）"""
        analysis = self.state.get("analysis")
        agent = create_coder()
        result = agent.execute(f"基于分析结果制定计划: {analysis}")
        return result.output

    @flow_listen(plan)
    def implement(self):
        """步骤3: 执行实现"""
        plan = self.state.get("plan")
        agent = create_coder()
        return agent.execute(f"执行计划: {plan}")

# 执行流程
flow = RefactorFlow()
result = flow.run()
```

**核心概念**:
- `@flow_start()`: 流程入口步骤
- `@flow_listen(step)`: 监听前置步骤完成后自动触发
- `@flow_route(step)`: 条件路由（根据状态选择分支）
- `FlowState`: 跨步骤共享状态字典（带变更历史）

### 5.4 RoleDispatcher — 智能调度器

根据任务类型自动选择合适的 Flow 和 Agent 组合:

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()

# 自动识别任务模式并调度
result = dispatcher.dispatch("重构项目添加类型注解")
# → 自动选择 TypeAnnotationFlow → analyst + coder + tester

print(result["summary"])
print(dispatcher.visualize("重构项目添加类型注解"))  # Mermaid 图
```

**支持的任务模式**:

| 模式 | 关键词 | Flow |
|------|--------|------|
| REFACTOR | 重构、refactor、优化 | 分析→规划→执行→验证 |
| TYPE_ANNOTATION | 类型注解、type hint | 分析→标注→验证 |
| TEST | 测试、test、pytest | 分析→设计→编写→验证 |
| FIX | 修复、bug、错误 | 定位→分析→修复→验证 |
| FEATURE | 新增、create、功能 | 需求→设计→实现→测试 |
| REVIEW | 审查、review、检查 | 全面审查→报告 |
| DOC | 文档、readme | 分析→生成→审查 |

### 5.5 MessageBus — 发布/订阅消息

跨 Agent 的主题式消息队列:

```python
from tea_agent.multi_agent import MessageBus, get_message_bus

bus = get_message_bus()

# Agent A 订阅主题
bus.subscribe("agent-A", "task:update")
bus.subscribe("agent-A", "task:result")

# Agent B 发布消息
bus.publish("task:update", {"status": "running"}, sender="coordinator")

# Agent A 收取消息
messages = bus.consume("agent-A")
for msg in messages:
    print(f"[{msg.topic}] {msg.payload}")
```

**与 toolkit_subagent_msg 的关系**:
- `toolkit_subagent_msg` = Agent-to-Agent 点对点通信
- `MessageBus` = Topic-based Pub/Sub（一对多广播）

### 5.6 Agent-as-Tool — Agent 工具化

将任何 RoleAgent 包装为可调用工具，其他 Agent 可以像调用普通工具一样调用它:

```python
from tea_agent.multi_agent import AgentTool, AgentToolManager

# 创建专家 Agent
analyst = create_analyst("深度代码分析")

# 包装为工具
tool = AgentTool(
    agent=analyst,
    name="senior_analyst",
    description="深度代码分析专家，输入代码文件路径，输出分析报告",
    max_concurrent=3,
    timeout=120,
)

# 调用
result = tool.call("分析 server.py 的并发安全性")
```

**工作流**:
```
RoleAgent
  │
  ▼ AgentTool 包装
AgentTool (name, description, parameters)
  │
  ▼ 注册到 ToolRegistry
全局可发现
  │
  ▼ 注入其他 Agent 的 toolkit
其他 Agent 可调用
```

### 5.7 WorkflowDAG — 高级工作流编排

支持 6 种节点类型，构建复杂 DAG 工作流:

```python
from tea_agent.multi_agent import WorkflowDAG, WorkflowNode, NodeType, WorkflowExec

dag = WorkflowDAG(name="代码审查流程")

# 添加节点
dag.add_node(WorkflowNode("analyze",   NodeType.TASK,      fn=analyze_fn))
dag.add_node(WorkflowNode("check",     NodeType.CONDITION, fn=check_fn))
dag.add_node(WorkflowNode("fix",       NodeType.TASK,      fn=fix_fn))
dag.add_node(WorkflowNode("test",      NodeType.PARALLEL,  fn=test_fn))
dag.add_node(WorkflowNode("done",      NodeType.END))

# 定义边（含条件路由）
dag.add_edge("analyze", "check")
dag.add_edge("check", "fix",     condition_key="has_issues")
dag.add_edge("check", "test",    condition_key="no_issues")
dag.add_edge("fix", "test")
dag.add_edge("test", "done")

# 执行
wf = WorkflowExec(dag)
result = wf.run()
```

**节点类型**:

| 类型 | 说明 |
|------|------|
| TASK | 普通任务节点 |
| CONDITION | 条件分支（if/elif/else） |
| LOOP | 循环（for-each / while） |
| PARALLEL | 并行扇出（fan-out + fan-in） |
| WAIT | 等待（定时 / 条件满足后继续） |
| END | 工作流终止节点 |

### 5.8 ExecutionPool — 并行执行引擎

双通道并行执行池，支持线程池和异步通道:

```python
from tea_agent.multi_agent import ExecutionPool, get_execution_pool

pool = get_execution_pool()

# 提交同步任务
future = pool.submit(my_func, arg1, arg2=value)
result = future.result(timeout=30)

# 提交异步任务
future = pool.submit_async(my_async_func, arg1)

# 批量执行
results = pool.map(my_func, [item1, item2, item3])

# 状态监控
stats = pool.status()
print(f"活跃: {stats['active']}, 等待: {stats['pending']}")
```

**配套机制**:
- `LoadBalancer`: 轮询/最少连接/加权负载均衡
- `ResourceGuard`: CPU/内存/并发限制保护
- `CircuitBreaker`: 熔断器（连续失败后自动断开）
- `RetryPolicy`: 自动重试策略

### 5.9 Multi-Agent 交互原理

#### 完整交互链路

```
用户: "重构项目添加类型注解"
  │
  ▼
主 Agent (OnlineToolSession)
  │
  ├── 调用 toolkit_parallel_subtasks()
  │   │
  │   ▼
  │   RoleDispatcher.dispatch("重构项目添加类型注解")
  │   │
  │   ├── 识别: TaskPattern.TYPE_ANNOTATION
  │   │
  │   ▼
  │   TypeAnnotationFlow (FlowEngine)
  │   │
  │   ├── @flow_start analyze()
  │   │   └── RoleAgent(analyst).execute()
  │   │       └── LiteSession → LLM API → 工具调用
  │   │
  │   ├── @flow_listen(plan)
  │   │   └── RoleAgent(architect).execute()
  │   │       └── 使用 state["analysis"] 作为上下文
  │   │
  │   ├── @flow_listen(implement)
  │   │   └── RoleAgent(coder).execute()
  │   │
  │   └── @flow_listen(verify)
  │       └── RoleAgent(tester).execute()
  │
  └── 返回结果给用户
```

#### 关键设计原则

1. **Session 隔离**: 每个子 Agent 有独立的 `LiteSession`，不共享历史
2. **工具权限控制**: 通过 `allowed_tools` / `denied_tools` 白名单限制每个 Agent 的能力边界
3. **结构化输出**: 子 Agent 可输出 Pydantic 模型，便于后续步骤解析
4. **状态透传**: `FlowState` 在 Flow 步骤间共享数据
5. **断点恢复**: `CheckpointManager` 可在崩溃后恢复执行
6. **执行追踪**: `TraceEngine` 记录每个 Agent 的 Span 级执行轨迹

", "## 6. 核心模块详解

### 6.1 Agent (`agent.py`)

统一 Agent 类，支持 3 种运行模式:

| 模式 | 存储 | 后台服务 | Session 类 | 用途 |
|------|------|---------|-----------|------|
| `lightweight` | ❌ | ❌ | OnlineToolSession | 孤立任务 |
| `full` | ✅ | ✅ | OnlineToolSession | CLI/GUI/Server |
| `lite` | ❌ | ❌ | LiteSession | 子 Agent |

```python
# full 模式（Server 使用）
agent = Agent(mode="full", config_path="config.yaml")

# lightweight 模式（轻量任务）
agent = Agent(mode="lightweight")

# lite 模式（子 Agent）
agent = Agent(mode="lite")
```

### 6.2 Session 层

#### BaseSession (`basesession.py`)
抽象基类，提供聊天会话接口定义。

#### OnlineToolSession (`onlinesession.py`)
完整功能的在线会话:
- OpenAI Function Calling 工具调用
- Token 优化的历史压缩
- 多模态支持（图片）
- 模式检测（pragmatic/creative）
- Thinking 推理支持

#### LiteSession (`litesession.py`)
轻量级无状态会话:
- 无历史、无存储、单轮执行
- 工具权限过滤
- 适用于子 Agent 和临时任务

#### Session 组件化设计
```
OnlineToolSession
  ├── SessionContext (session/context.py)     # 上下文状态
  ├── APIComponent (onlinesession.py)         # LLM API 通信
  ├── build_api_messages (session/history_builder.py)  # 历史构建
  ├── execute_tool_loop (session/tool_loop_runner.py)  # 工具循环
  └── SessionPipeline (session_pipeline.py)   # 可配置处理链
```

### 6.3 Toolkit 层 (`tlk.py` + `toolkit/`)

工具引擎负责:
1. 从 `toolkit/*.py` 加载工具定义（名称/描述/参数/代码）
2. 编译代码 → 动态注册为全局 `toolkit_*()` 函数
3. 构建 `func_map`（name→function_ref）供 LLM 调用
4. 版本管理（save/reload/rollback/list_versions）

**工具生命周期**:
```
toolkit/*.py 文件
  │
  ▼ Toolkit.__init__() 加载
meta_map (工具元数据) + func_map (函数引用)
  │
  ▼ 序列化为 OpenAI tool schema
注入 LLM 的 tools 参数
  │
  ▼ LLM 请求调用 → func_map[name](**args)
执行结果注入 messages
  │
  ▼ toolkit_save() 动态创建新工具
写入 toolkit/*.py → toolkit_reload() 重载
```

### 6.4 Storage 层 (`store/`)

基于 SQLite 的持久化存储，包含 8 个子组件:

| 组件 | 职责 |
|------|------|
| `ConversationStore` | 对话记录 CRUD |
| `TopicStore` | 主题管理 |
| `MemoryStore` | 长期记忆 |
| `SummaryStore` | 摘要 (L1/L2/L3) |
| `ScheduledTaskStore` | 定时任务 |
| `VectorStore` | 向量存储 |
| `ConfigHistoryStore` | 配置变更历史 |
| `SemanticSearch` | 语义搜索 |

### 6.5 Agent Pipeline (`agent_pipeline.py`)

后处理流水线，在后台线程执行:
- **auto_summary**: 标题自动生成
- **l2_to_l3_summary**: L2 溢出条目 → L3 语义摘要
- **do_async_summaries**: 异步摘要入口

### 6.6 Session Pipeline (`session_pipeline.py`)

可配置的对话处理步骤链:
```python
pipeline = SessionPipeline()
pipeline.register_step("os_info", inject_os_info, position=0)
pipeline.register_step("mode_detect", detect_mode, position=1)
pipeline.register_step("history_build", build_history, position=2)
# ... 按 position 顺序执行
```

## 7. 模块间依赖关系

### 7.1 依赖图

```
                    ┌─────────────┐
                    │  config.py  │
                    └──────┬──────┘
                           │ 加载配置
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐
  │  tlk.py     │  │ store/_core  │  │ providers.py│
  │  (Toolkit)  │  │  (Storage)   │  │  (Provider) │
  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘
         │                │                  │
         └────────┬───────┘                  │
                  │                          │
                  ▼                          │
         ┌────────────────┐                  │
         │ session_ref.py │◄─────────────────┘
         │ (全局会话引用)  │
         └────────┬───────┘
                  │
       ┌──────────┼──────────┐
       │          │          │
       ▼          ▼          ▼
┌─────────┐ ┌──────────┐ ┌──────────────┐
│basesession│ │litesession│ │onlinesession │
│(抽象基类) │ │(轻量会话) │ │(完整会话)    │
└─────┬────┘ └────┬─────┘ └──────┬───────┘
      │           │              │
      │    ┌──────┘              │
      │    │                     │
      ▼    ▼                     ▼
┌─────────────────────────────────────┐
│           agent.py                  │
│    (Agent: 3种模式统一入口)          │
└────────────────┬────────────────────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌──────────┐
│ gui.py  │ │ server/ │ │ multi_   │
│ (Tkinter)│ │ (HTTP)  │ │ agent/   │
└─────────┘ └─────────┘ └──────────┘
```

### 7.2 关键依赖关系

| 依赖方 | 被依赖方 | 关系 |
|--------|---------|------|
| Agent | config, tlk, store, session_ref | Agent 依赖配置、工具、存储、会话引用 |
| OnlineToolSession | basesession, session/*, openai | Session 依赖基类、组件、LLM SDK |
| APIServer | Agent, Storage, route_handlers | Server 依赖 Agent、存储、路由 |
| route_handlers | server.get_server() | 路由通过全局单例访问 Server |
| toolkit_* | session_ref, tlk | 工具函数通过全局引用访问会话和工具库 |
| RoleAgent | LiteSession, tlk.toolkit | 子 Agent 依赖轻量会话和工具库 |
| FlowEngine | RoleAgent | Flow 步骤使用 RoleAgent 执行 |
| WorkflowDAG | ExecutionPool | 工作流使用执行池并行执行 |

## 8. 配置系统

### 8.1 配置文件结构

```yaml
# ~/.tea_agent/config.yaml

main_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com"
  model_name: "deepseek-chat"
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

embedding_model:
  api_url: "https://api.siliconflow.cn"
  model_name: "Qwen/Qwen3-Embedding-4B"
  api_key: "sk-xxx"
  dimension: 2560

max_history: 10
max_iterations: 100
enable_thinking: true
keep_turns: 5
max_tool_output: 128000
max_assistant_content: 128000
extra_iterations_on_continue: 25
memory_extraction_threshold: 2
```

### 8.2 配置优先级

```
1. 显式指定路径 (--config)
2. $HOME/.tea_agent/config.yaml
3. tea_agent/config.yaml (包内置回退)
```

### 8.3 运行时热切换

```python
# 通过 API 切换模型
PUT /api/model
{"api_key": "sk-new", "api_url": "https://api.openai.com", "model_name": "gpt-4o"}

# 切换整个配置文件
POST /api/model/config
{"config_path": "~/.tea_agent/other.yaml"}
```

## 9. 工具系统 (Toolkit)

### 9.1 内置工具分类

| 类别 | 工具 | 说明 |
|------|------|------|
| 文件操作 | `toolkit_file`, `toolkit_save_file`, `toolkit_edit` | 读写编辑文件 |
| 代码智能 | `toolkit_lsp`, `toolkit_search`, `toolkit_code_review` | LSP/搜索/审查 |
| 系统操作 | `toolkit_exec`, `toolkit_os_info`, `toolkit_screenshot` | 命令执行/截图 |
| 版本控制 | `toolkit_git_commit`, `toolkit_diff`, `toolkit_diff_edit` | Git 操作 |
| 知识管理 | `toolkit_kb`, `toolkit_memory`, `toolkit_skills` | 知识库/记忆/技能 |
| 自我进化 | `toolkit_self_evolve`, `toolkit_reflection`, `toolkit_prompt_evolve` | 自我优化 |
| 任务管理 | `toolkit_todo`, `toolkit_plan`, `toolkit_scheduler` | TODO/计划/调度 |
| Multi-Agent | `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_parallel_subtasks` | 子 Agent |
| 构建发布 | `toolkit_build`, `toolkit_release_version`, `toolkit_format_code` | 构建/发布 |

### 9.2 动态工具创建

```python
# LLM 可以在对话中创建新工具
toolkit_save(
    name="my_analyzer",
    meta={
        "type": "function",
        "function": {
            "name": "my_analyzer",
            "description": "分析 Python 文件的复杂度",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"}
                }
            }
        }
    },
    pycode="""
def my_analyzer(filepath):
    import ast
    with open(filepath) as f:
        tree = ast.parse(f.read())
    functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    return {"functions": len(functions), "names": functions}
"""
)

toolkit_reload()  # 重载后立即可用
```

## 10. FAQ

**Q: 如何选择启动方式？**

| 场景 | 推荐方式 |
|------|----------|
| 日常使用 | `python -m tea_agent.server` (Web UI) |
| 终端交互 | `tea-agent-cli` |
| 集成到其他系统 | `tea-agent-api` + `/v1/chat/completions` |
| 嵌入式/轻量 | `tea-agent-mini` |

**Q: 重启功能如何工作？**

`POST /api/restart` 会 spawn 新进程（相同参数），1.5s 后当前进程 graceful shutdown。无需手动重启。

**Q: Multi-Agent 会消耗更多 Token 吗？**

是的。每个子 Agent 独立调用 LLM，Token 消耗 ≈ 子任务数 × 单次对话 Token。可通过 `allowed_tools` 和 `max_iterations` 限制。

**Q: 如何扩展工具？**

1. 在 `toolkit/` 目录下创建 `toolkit_xxx.py`
2. 定义函数 `toolkit_xxx()` 和元数据 `meta_toolkit_xxx()`
3. 重启服务或调用 `toolkit_reload()`

**Q: 数据存储在哪里？**

默认: `~/.tea_agent/chat_history.db` (SQLite)。可通过配置文件 `paths.db_path` 自定义。


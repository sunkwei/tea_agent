# TeaAgent

TeaAgent 是一个**自主进化型智能助手**，基于 OpenAI 兼容接口的 Function Calling 功能实现。它不仅能够调用预设的工具，还具备动态创建、加载和管理工具的能力，实现能力的自我扩展。

## 核心特性

- **自主进化 (Self-Evolution)**: 智能体可以根据任务需求，自动编写 Python 代码并调用 `toolkit_save` 创建新工具，随后通过 `toolkit_reload` 立即获得新能力。
- **动态工具库 (Dynamic Toolkit)**: 支持工具的热加载与卸载，所有工具均以独立的 Python 文件形式存储在 `toolkit` 目录中。
- **长期记忆 (Long-term Memory)**: 集成了 LLM 驱动的记忆提取机制，能从对话中自动识别并提取用户偏好、技术决策、事实等有价值的信息，并进行持久化存储。
- **流式对话与思考过程**: 支持流式输出，并可选展示模型的思考过程（Thinking Process）。
- **GUI 交互界面**: 提供基于 Tkinter 的图形界面，支持多主题管理、历史记录查询及工具状态实时监控。
- **持久化存储 (Persistent Storage)**: 所有对话、记忆及主题均保存在 SQLite 数据库中，支持历史记录查询, 数据库存储在 $HOME/.tea_agent/ 下，自动创建的工具保存在 `toolkit` 目录中。

## 快速开始

### 环境要求
- Python 3.10+
- OpenAI 兼容的 API 密钥（如 Qwen, GLM 等）

### 安装依赖
```bash
pip install -e .
```

### 运行
```bash
export TEA_AGENT_API=<YOUR API KEY>
export TEA_AGENT_URL=<YOUR API URL>
export TEA_AGENT_MODEL=<YOUR MODEL NAME>
python -m tea_agent.main_db_gui main
```

## 项目结构
- `tea_agent/`: 核心包目录
  - `onlinesession.py`: 处理 LLM 对话流、工具调用循环及流式输出。
  - `memory.py`: 记忆提取与管理逻辑。
  - `store.py`: 基于 SQLite 的持久化存储（对话历史、记忆、主题）。
  - `tlk.py`: 工具库 (Toolkit) 的加载、校验与保存逻辑。
  - `toolkit/`: 存放动态生成的工具函数 (.py 文件)。
  - `main_db_gui.py`: 基于 Tkinter 的 GUI 实现。

## 配置
项目支持通过环境变量或 GUI 界面配置 API_KEY、API_URL 和 MODEL。

## 开源协议
MIT License

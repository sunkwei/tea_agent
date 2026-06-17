# Tea Agent v0.9.30

> ⚠️ **这是一个 AI 写 AI 的实验项目，自行承担责任。**

> 一个自进化 AI 编程助手 — 工具驱动、自我进化、多界面形态

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Tea Agent 是一款**会自我进化的 AI 编程助手**，拥有 60+ 可调用的工具，能自主编写代码、调试、搜索、文件操作、浏览器操控，并能在运行中动态加载新工具。支持 GUI / TUI / CLI 三种界面。

---

## ✨ 核心特性

- 🧠 **自进化引擎** — Agent 可以修改自身代码、创建新工具、优化提示词，实现自主进化
- 🧰 **60+ 内置工具** — 涵盖文件操作、代码编辑、搜索、截图、OCR、包管理、Git 等
- 🖥️ **三态界面** — GUI（Tkinter）、TUI（Textual）、CLI，按需切换
- 📚 **项目知识库** — 自动构建符号索引、调用图，支持代码影响分析
- 🔄 **断点续聊** — 聊天记录持久化，重启后恢复上下文
- 📋 **Plan / TODO** — 内置任务规划与追踪系统
- 🌐 **MCP 协议** — 支持连接外部 MCP Server，扩展第三方工具
- 🎯 **模式切换** — design / develop / test / review / docs / devops 六阶段工作流
- 🤖 **多 Agent 协作** — 任务分解 + 并行执行，子 Agent 独立完成子任务
- 📊 **任务评估** — 自动评估任务质量，记录成功/失败经验
- 💎 **技能结晶** — 从成功经验中提取可复用技能模式

---

## 📦 安装

```bash
# 从 PyPI 安装
pip install tea_agent

# 或从源码
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
pip install -e .
```

Playwright 浏览器（可选，用于 JS 渲染页面抓取）：
```bash
playwright install chromium
```

---

## 🚀 快速开始

```bash
# 启动 GUI（默认）
tea_agent

# 启动 TUI
tea-agent-tui

# 启动 CLI
tea-agent-cli
```

---

## 🧰 工具概览（60+）

| 类别 | 工具 |
|------|------|
| 📁 文件操作 | `toolkit_file`, `toolkit_save_file`, `toolkit_explr` |
| ✏️ 代码编辑 | `toolkit_edit`, `toolkit_diff`, `toolkit_self_evolve` |
| 🔍 搜索 | `toolkit_search`, `toolkit_lsp`, `toolkit_query_chat_history` |
| 📸 截图/OCR | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_screen_read` |
| 🖱️ 操控 | `toolkit_input`, `toolkit_browser_tab`, `toolkit_js_fetch` |
| 📦 包管理 | `toolkit_pkg`, `toolkit_build`, `toolkit_format_code` |
| 🧪 测试 | `toolkit_run_tests`, `toolkit_test_gui` |
| 🗓️ 工具 | `toolkit_lunar`, `toolkit_weather_my`, `toolkit_gettime` |
| 🔧 系统 | `toolkit_exec`, `toolkit_config`, `toolkit_os_info` |
| 🧠 记忆/知识 | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection` |
| 🤖 多 Agent | `Dispatcher`, `LiteAgent`, 并行任务执行 |

> 完整列表见 [`docs/TOOLS.md`](docs/TOOLS.md)（每小时自动更新）

---

## 🤖 多 Agent 协作

```python
from tea_agent.multi_agent import Dispatcher, LiteAgent

# 一步到位：分解 + 执行
dispatcher = Dispatcher()
result = dispatcher.dispatch("重构项目添加类型注解")
print(result["summary"])

# 可视化执行计划（不执行）
print(dispatcher.visualize("为 gui.py 添加类型注解"))

# 单独使用 LiteAgent
agent = LiteAgent()
result = agent.execute_sync("读取 README.md 并总结")
```

### 架构

```
Dispatcher.dispatch(goal)
  │
  ├─ _identify_pattern()     → 识别任务模式
  ├─ _generate_tasks()       → 生成 SubTask 列表
  ├─ _topological_sort()     → 拓扑排序（分层）
  │
  ├─ _execute_layers()       → 逐层执行
  │   ├─ 第 1 层: [task_1] ─── LiteAgent.execute_sync()
  │   │              ↓ 结果写入 accumulated_context
  │   ├─ 第 2 层: [task_2] ─── LiteAgent.execute_sync()  ← 带前置上下文
  │   │              ↓
  │   └─ ...
  │
  └─ _merge_results()        → 整合结果
```

---

## 🏗️ 项目结构

```
tea_agent/
├── gui.py              # GUI 主界面（Tkinter）
├── tui.py              # TUI 界面（Textual）
├── cli.py / tlk.py     # CLI 交互
├── agent.py            # Agent 核心引擎
├── config.py           # 配置管理
├── memory.py           # 长期记忆
├── prompt_manager.py   # 提示词版本管理
├── toolkit/            # 60+ 工具模块
├── session/            # 会话管理（Tool/Schemata）
├── multi_agent/        # 多 Agent 协作
├── lsp/                # LSP 语言服务
├── store/              # 数据存储
├── evaluation/         # 任务评估
├── skills/             # 技能结晶
└── _gui/               # GUI 资源（图标、字体）
```

---

## 🔧 配置

配置文件 `~/.tea_agent/config.yaml`：

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  max_context_tokens: 0   # 0=不限制，>0 时启用渐进式 token 裁剪
cheap_model:
  api_key: ""
  api_url: ""
  model_name: ""
  max_context_tokens: 0   # 独立配置，适用于本地小模型
embedding:
  provider: openai
  model: text-embedding-3-small
```

### 上下文窗口控制

`max_context_tokens` 用于限制发送给 LLM 的最大上下文 token 数：

- **0**（默认）= 不限制，发送全部历史
- **32000** = 适合 32K 窗口模型
- **128000** = 适合 GPT-4o / Claude 等大窗口模型

启用后，系统会自动预估 token 数，超出预算时按优先级渐进裁剪：
1. 删除旧的 `[历史记录]` 条目
2. 替换旧工具输出为占位符
3. 清空 thinking 内容
4. 截断长文本
5. 删除旧轮次（保留最近 5 轮）

> 主模型和便宜模型独立配置，互不影响。

Agent 可在运行时通过 `toolkit_config` 自主调优参数。

---

## 📄 许可证

MIT License © 2024-2026 sunkw

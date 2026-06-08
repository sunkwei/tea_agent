# Tea Agent v0.9.21

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

> 完整列表见 [`docs/TOOLS.md`](docs/TOOLS.md)（每小时自动更新）

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
└── _gui/               # GUI 资源（图标、字体）
```

---

## 🔧 配置

配置文件 `~/.tea_agent/config.yaml`：

```yaml
model:
  provider: openai
  model: gpt-4o
embedding:
  provider: openai
  model: text-embedding-3-small
```

Agent 可在运行时通过 `toolkit_config` 自主调优参数。

---

## 📄 许可证

MIT License © 2024-2026 sunkw

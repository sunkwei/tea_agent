# Tea Agent v0.9.32

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
- 💎 **技能结晶** — Plan 执行后自动结晶 → 新对话按语义匹配注入 → 技能自进化闭环

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

## 🧠 长期记忆系统

Tea Agent 的记忆系统模拟人类记忆的工作方式：优先级分层、相关性检索、自然衰减。

### 核心机制

| 机制 | 说明 |
|------|------|
| **四级优先级** | `CRITICAL`(指令) > `HIGH`(偏好) > `MEDIUM`(经验) > `LOW`(参考) |
| **年龄衰减** | CRITICAL→HIGH(30天) → MEDIUM(60天) → LOW(90天)，模拟遗忘曲线 |
| **相关性检索** | jieba 中文分词 + 关键词匹配 + 文件路径关联，计算相关性分数 |
| **分层保底** | 每次注入上限 30 条，按优先级保底分配（HIGH≥3, MEDIUM≥2, LOW≥1） |
| **去重机制** | 新记忆与已有记忆计算相似度，超过阈值(0.3)则合并 |

### 选择算法

```
score = 相关性(关键词匹配) × 重要度(importance/5) × 时效因子 × 优先级因子

时效因子: 1天内=1.0, 7天=0.9, 30天=0.7, 90天=0.5, >90天=0.3
优先级因子: (4 - priority) / 4
```

### 自动提取

对话结束后，系统自动从用户消息中提取记忆（基于 jieba 分词），存入 SQLite 持久化。Agent 也可通过 `toolkit_memory` 工具手动管理记忆。

---

## 📜 四级历史压缩 (L0 → L3 → L2 → L1)

Tea Agent 使用**四级分层**构建发送给 LLM 的上下文，在有限的 token 窗口内最大化信息密度：

```
┌─────────────────────────────────────────────────┐
│  Level 0: 系统层                                 │
│  ├─ 系统提示词                                   │
│  ├─ 技能推荐注入 (SkillRegistry 语义匹配)          │
│  ├─ 未完成任务自动恢复 (TODO/Plan)                │
│  └─ 长期记忆注入 (MemoryManager 选取)             │
├─────────────────────────────────────────────────┤
│  Level 3: 摘要层 (LLM 生成)                      │
│  └─ L2 溢出时生成：保留关键结论，丢弃细节          │
├─────────────────────────────────────────────────┤
│  Level 2: 历史对列表 (SQLite 持久化)              │
│  └─ user + AI final msg 对，按相关性动态筛选注入   │
├─────────────────────────────────────────────────┤
│  Level 1: 最新对话 (当前 session)                 │
│  ├─ 压缩工具链 (中间工具调用→摘要，保留最终回复)   │
│  ├─ 旧工具输出 → 占位符                           │
│  └─ 工具输出截断 (首尾各半，按换行对齐)            │
└─────────────────────────────────────────────────┘
```

### Level 2 (L2) — 历史对列表

L2 是一个**固定大小的环形缓冲区**，存储在 SQLite 中，容量 50 条。

每个条目包含：

```json
{
  "user": "用户的原始消息",
  "assistant": "AI 的最终回复（不含工具调用中间过程）",
  "thinking": "工具调用轮的 assistant content + reasoning（可选）",
  "files": ["涉及的文件路径（可选）"]
}
```

**流转机制**：

```
每轮对话结束
  → push_to_level2() 追加新条目
  → L2 count ≥ 50?
      是 → 取最老 30 条 → generate_l2_to_l3_summary()
      → 合并现有 L3 摘要 → LLM 生成新 L3 → L2 裁剪到 20 条
```

**注入策略**：每次构建上下文时，L2 全部条目按**语义相关性**筛选：

| 相关度 | 处理 |
|--------|------|
| ≥ 0.15 | 保留完整 user+assistant 对（作为 `[历史记录]` 注入） |
| ≥ 0.05 | 仅保留摘要片段（User: xxx... → Assistant: yyy...） |
| < 0.05 | **不注入**（节省 token） |

> 相关性基于关键词重叠度（Jaccard）+ 文件路径匹配计算。

### Level 1 (L1) — 最新对话

L1 是**当前 session 的原始消息**，经多层压缩后传入 API。

#### 工具链压缩

加载历史时，`_compress_tool_rounds` 对工具调用链做 L1 智能压缩：

```
原始 rounds:  [user] → [asst+tool_call] → [tool_result] → [asst+tool_call] → [tool_result] → [final_asst]
                                              ↓ 压缩                  ↓ 压缩
压缩后 rounds: [user] → [asst+tool_call(参数截断)] → [tool_result(首尾各半)] → [final_asst(完整保留)]
```

- **中间 assistant**（含 tool_calls）：保留 reasoning_content，工具参数 >2048 字节则截断
- **tool 消息**：`_compress_tool_content()` 首尾各 1024 字节，按换行边界对齐
- **最终 assistant**（末尾无 tool_calls）：**完整保留**，不压缩

#### 实时工具输出截断

每个工具调用返回时，`session_tool_component` 立即截断：

```python
# 默认 max_tool_output = 128KB (131072 字节)
if result_bytes > max_output:
    # 首尾各保留一半，按换行对齐
    result_str = f"{head_text}\n\n... [工具输出截断] ...\n\n{tail_text}"
```

> 这是**第一道防线**，确保单个工具输出不会撑爆 token 窗口。

#### 多轮工具调用的 token 膨胀处理

当 Agent 执行读取大日志等场景时，可能在**同一轮 user 消息**内产生多次工具调用。处理流程：

```
第 1 轮工具调用:
  toolkit_exec("cat huge.log") → 10MB 输出 → max_tool_output 截断到 128KB
  toolkit_edit(...) → 小输出

第 2 轮工具调用:
  toolkit_exec("grep pattern huge.log") → 5MB 输出 → 截断到 128KB

... (最多 max_iterations=50 轮)

── 每轮 API 调用前 ──

1. _build_api_messages() 构建上下文
2. _tool_prune_cutoff = 最近 3 轮 user 消息分界
3. 3 轮外的 tool 消息 → "[工具结果已省略: N 字符]"
4. 如 max_context_tokens > 0 → _progressive_trim() 5 级渐进裁剪
```

### 渐进式裁剪策略

当 `max_context_tokens > 0` 时，超出预算按以下优先级裁剪：

| 策略 | 操作 | 说明 |
|------|------|------|
| 1 | 删除 `[历史记录]` L2 条目 | 最旧的先删 |
| 2 | 替换旧工具输出为占位符 | `[工具结果已省略: N 字符]` |
| 3 | 清空 reasoning_content | 释放 thinking token |
| 4 | 截断长文本 | 限制 4096 字符 |
| 5 | 删除 L1 旧轮次 | 保留最近 5 轮 user 消息 |
| 兜底 | 截断最后一条消息 | 仅保留前 1/3 |

### Token 估算

使用启发式算法快速估算 token 数（无需 tiktoken）：
- 英文：约 4 字符 = 1 token
- 中文：约 1.5 字 = 1 token
- 图片：固定 ~85 tokens

---

## 🔄 自进化基础：toolkit_save / toolkit_reload

Tea Agent 的核心进化能力建立在**工具热插拔**机制上：Agent 可以在运行时创建新工具、修改现有工具，并立即生效。

### 工作流程

```
Agent 发现需要新能力
  │
  ├─ 1. 编写 Python 函数代码
  ├─ 2. 定义 OpenAI function schema (参数/描述)
  │
  ├─ 3. toolkit_save(name, meta, pycode)
  │     ├─ 存储到 tea_agent/toolkit/{name}.py
  │     ├─ 自动版本管理 (v1.0.0 → v1.1.0 → ...)
  │     ├─ 保存历史版本到 .versions/ 目录
  │     └─ 自动生成 SKILL.md 文档
  │
  ├─ 4. toolkit_reload()
  │     ├─ 扫描 toolkit/ 目录所有 .py 文件
  │     ├─ 动态 import 模块
  │     ├─ 注册 meta 函数 → 生成 tool schema
  │     └─ 所有 toolkit_* 函数 → 全局可用
  │
  └─ 5. 新工具立即可用于后续对话
```

### 关键实现

| 特性 | 说明 |
|------|------|
| **版本管理** | 每次 save 自动生成版本号，保留完整历史 |
| **安全回滚** | `toolkit_rollback(name, version)` 可回退到任意历史版本 |
| **Schema 自动生成** | `meta_toolkit_*()` 函数返回 OpenAI function calling schema |
| **热加载** | `toolkit_reload()` 无需重启进程，importlib 动态加载 |
| **技能文档** | 保存后自动生成 `skills/{name}/SKILL.md`，便于知识沉淀 |

### Agent 自进化的例子

```python
# Agent 可以这样调用（内部实现）

# 创建一个新工具
toolkit_save(
    name="toolkit_count_lines",
    meta={
        "type": "function",
        "function": {
            "name": "toolkit_count_lines",
            "description": "统计文件行数",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"]
            }
        }
    },
    pycode="""
def toolkit_count_lines(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = len(f.readlines())
    return {"path": path, "lines": lines}
"""
)

# 重新加载工具集
toolkit_reload()

# 新工具立即可用
toolkit_count_lines(path="tea_agent/agent.py")
# → {"path": "tea_agent/agent.py", "lines": 520}
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

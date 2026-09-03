# Tea Agent v0.15.0

> ⚠️ **AI 写 AI 的实验项目，自行承担责任。**

> 🌐 **[English Version](README.en.md)**

> **会自我进化的 AI 编程助手** — 不只是完成编码任务，还能修改自己的代码、创造新工具、优化自己的提示词，越用越强。

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.15.1-blue)](https://pypi.org/project/tea-agent)

---

## 🎯 一句话看懂 Tea Agent

| | |
|---|---|
| 🧠 **自进化** | AI 写 AI —— 能改自己的代码、造新工具、优化提示词，任务越多越强 |
| 🧰 **工具驱动** | 75+ 内置工具（文件/代码/搜索/截图/浏览器/包管理/Git），运行时热插拔 |
| 🖥️ **多形态** | Web V2 / REST API / ACP / Telegram / 微信 界面，一套引擎 |
| 🧠 **真记忆** | 类人长期记忆：分层优先级、语义检索、自然衰减、去重合并，跨会话不忘 |
| 🤖 **多 Agent** | 6 阶段全栈协作：角色化 Agent + 事件流 + 消息总线 + 并行执行 + DAG 编排 |
| 📡 **远程协同** | `toolkit_remote_agent` 连接边缘设备（RK3588/BM1688），主机 ↔ 设备协同 |

---

## ✨ 核心特点

### 1. 🧠 自进化引擎（AI 写 AI）— 本项目灵魂

Agent 在运行中**改造自己**，全程五层安全防护：

```
toolkit_save          → 运行时创建/更新工具，即时生效，自动版本管理
toolkit_self_evolve   → 五层安全修改源码：Git 快照 → .bak → 语法检查 → 编译 → LSP → 测试
toolkit_prompt_evolve → 基于反思 + 记忆，自我优化系统提示词
toolkit_experience_solidify → 成功→技能，失败→教训，自动结晶复用
```

> ⚠️ **上下文感知**：自进化能力**只在 tea_agent 自身项目内激活**；在外部项目中自动禁用，专注完成你的任务，不做有害改动。

### 2. 🧰 工具驱动 — 75+ 内置工具

| 类别 | 代表工具 |
|------|---------|
| 📁 文件 / 代码 | `toolkit_file`, `toolkit_edit`, `toolkit_diff`, `toolkit_code_review`, `toolkit_format_code` |
| 🔍 搜索 / 智能 | `toolkit_search`, `toolkit_lsp`, `toolkit_explr`, `toolkit_query_chat_history` |
| 🖥️ 屏幕 / 浏览器 | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_input`, `toolkit_js_fetch`, `toolkit_browser_tab` |
| 🧠 记忆 / 反思 | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 多 Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_remote_agent` |
| 📋 规划 / 调度 | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume` |
| 🔧 系统 / 工程 | `toolkit_exec`, `toolkit_pkg`, `toolkit_build`, `toolkit_git_commit`, `toolkit_config` |

工具引擎（`tlk.py`）支持**动态加载/卸载/重载** — 对话中创建一个新工具，下一轮就能用。

### 3. 🧠 类人长期记忆系统

模拟人类记忆的工作方式，底层 SQLite + 语义向量：

- **优先级分层**：`CRITICAL / HIGH / MEDIUM / LOW`，关键指令优先注入
- **语义检索**：embedding 余弦相似度，从 ≤30 条活跃记忆中选最相关
- **自然衰减**：Ebbinghaus 遗忘曲线，旧记忆逐步降级，`pinned` 豁免
- **去重合并**：Jaccard + embedding 双通道，相似记忆自动合并提权
- **跨主题汇总**（v0.13.3+）：每 3 轮后台分析，发现跨会话模式

### 4. 🤖 多 Agent 系统（v0.11+）

6 阶段全栈协作框架：

```
RoleAgent（角色化） + FlowEngine（事件流） + MessageBus（消息总线）
+ Agent-as-Tool（Agent 即工具） + ExecutionPool（并行执行）
+ WorkflowDAG（DAG 编排） + PatternMarket（模式市场） + TraceEngine（调用追踪）
```

零代码触发：对话中直接说「并行分析这几个文件」，自动拆分子任务并发执行。内置**双 AI 辩论赛 Demo**，左右分屏实时交锋。

### 5. 📡 远程设备 Agent（v0.13.10+）

通过 `toolkit_remote_agent` 连接边缘设备上的 `tea_agent.server`：

```
register → exec（下发任务，session_id 控制上下文） → status（心跳） → unregister
```

适用于**嵌入式调试**（RK3588/BM1688/X3）、**边缘节点管理**、**分布式协同**。

### 6. 🏎️ Token 经济 — 四级历史压缩 + 前缀缓存稳定化

`L0 系统层 → L3 语义摘要 → L2 历史对 → L1 当前对话` 四级组装上下文，在有限 token 窗口内最大化信息密度，长对话不爆上下文。

**v0.15.0 缓存前缀稳定化**（对齐 DeepSeek Harness「派生只依赖事件流」哲学）— 深度优化 LLM 前缀缓存命中率：

- **入库定型**：消息一旦入库即决定最终形态（截断/占位符/清空），绝不逐轮重算
- **L2 入库定型**：相关性过滤只在「新消息边界」重算一次，工具循环内多轮请求复用同一版本，消除 L2 条目翻转
- **裁剪决策固化**：reasoning 清空 / 紧急截断等形态决策回写 `context.messages`，预算波动不再导致「完整版↔截断版」翻转
- **动态内容尾部注入**：时间/token 预算/技能/记忆全部放消息尾部，不进 system prompt，保护最长最贵的前缀段
- **可观测**：`cache_report.py` 输出 `prompt_cache_hit_tokens` 命中率，端到端可见

### 7. 👁️ 视觉模型自动切换（v0.13.16+）

主模型不支持视觉？配置一个 `vision_model`，Agent 自动切换：

- **请求级切换**：检测请求消息含图（当前轮或历史轮）→ 自动使用视觉模型
- **回合级兜底**：覆盖「上一轮发图、本轮纯文本追问」场景，主模型不再收到无法处理的 `image_url` 内容
- **`toolkit_vision_analyze`**：主模型「灵机一动」委托能力 — 遇到图片路径 / URL / data URL 主动调用视觉模型分析，返回文本结果继续推理
- **无感恢复**：回合结束自动恢复主模型，零配置零打扰

---

## 🚀 30 秒快速开始

```bash
# 1. 安装
pip install tea_agent

# 2. 启动（Web V2 全功能界面）
tea-agent-api
# 或 python -m tea_agent.server

# 3. 打开浏览器
# http://127.0.0.1:8282
```

首次启动自动弹出配置窗口，填入 LLM API Key 即可对话。

---

## 💻 界面形态

| 界面 | 启动方式 | 适用场景 |
|------|---------|---------|
| **Web V2**（推荐） | `tea-agent-api` | 单页应用 SPA，全功能浏览器体验：聊天 + 记忆 + 调度 + 历史 |
| **REST API** | `python -m tea_agent.server --port 8081` | OpenAI 兼容接口，第三方集成 |
| **ACP 协议** | `tea-agent-acp` | VS Code / IDE 集成（JSON-RPC 2.0） |
| **Telegram** | `tea-agent-telegram` | 手机远程对话 |
| **微信** | `tea-agent-wechat` | 微信个人号接入（iLink Bot，扫码登录） |
| **Mini 版** | `tea-agent-mini` | 嵌入式 / Docker / 低配 VPS |

---

## 🗺️ 深度能力地图

> 想深入了解某一项？展开对应章节。

<details>
<summary><b>🧠 长期记忆系统 — 工作原理</b></summary>

**存储结构**：每条记忆含 `content / priority(0-3) / importance(1-5) / category / tags / embedding / expires_at / pinned`。

**选择算法**（每次对话注入 ≤30 条）：
```
score = 关键词相关性 × 重要度 × 时效因子 × 优先级因子
```
分层保底：CRITICAL 优先（上限 10）→ HIGH ≥3 → MEDIUM ≥2 → LOW ≥1 → 剩余按分竞争。

**年龄衰减**（Ebbinghaus）：CRITICAL>30天→HIGH，HIGH>60天→MEDIUM，MEDIUM>90天→LOW。

**提取分类**：`instruction→CRITICAL`、`preference/reminder→HIGH`、`fact→MEDIUM`、`general→LOW`，LLM 自动提取 + 4 级容错解析。

**去重合并**：Jaccard ≥0.6 合并（保留长内容、低优先级、高重要度）；embedding 余弦 ≥0.92 批量去重。

**CRITICAL FIFO**：上限 30 条，超出软删除最旧，防指令记忆膨胀。

</details>

<details>
<summary><b>📜 四级历史压缩 — Token 效率</b></summary>

```
L0 系统层   系统提示词 + 任务恢复 + 记忆注入
L3 语义摘要 L2 溢出时 LLM 生成关键结论（50→20 裁剪）
L2 历史对   SQLite 环形缓冲（50 条），Jaccard 相关性筛选注入
L1 当前对话 128KB 截断 + 旧工具输出占位 + 5 级渐进裁剪
```

```python
# L0 组装顺序
result.append({"role": "system", "content": system_prompt})
if has_pending_tasks:
    result.append({"role": "user", "content": resume_info})
if memories:
    result.append({"role": "user", "content": memories})
```

L3 注入格式（`[System Memory]` 区）包含**长期背景/偏好/关键结论** + **历史工具链回顾**两块。

</details>

<details>
<summary><b>🔄 自进化引擎 — 安全机制</b></summary>

修改自身代码时五层防护，任一层失败自动回滚：

```
Layer 0  Git 快照（仅工作区干净时）
Layer 1  时间戳 .bak（永不覆盖）
Layer 1.5  语法严格检查（换行/缩进/括号/冒号）
Layer 2  py_compile 编译验证 → 失败回滚
Layer 2.5  LSP 智能检查（影响分析 + lint 对比 + 签名对比）
Layer 3  pytest 测试验证 → 失败 git reset --hard
```

| 能力 | 工具 | 安全 |
|------|------|------|
| 创建新工具 | `toolkit_save` + `toolkit_reload` | 版本回滚 |
| 修改源码 | `toolkit_self_evolve` | 五层安全 |
| 优化提示词 | `toolkit_prompt_evolve` | 版本回滚 |
| 固化经验 | `toolkit_experience_solidify` | 分类标签 |
| 代码智能 | `toolkit_lsp` | 只读 |

</details>

<details>
<summary><b>🤖 多 Agent — 核心组件</b></summary>

**四种协作方式**：

| 方式 | 说明 |
|------|------|
| FlowEngine | 事件驱动流：`@flow_start` / `@flow_listen` / `@flow_route`，Mermaid 可视化 |
| Agent-as-Tool | 把子 Agent 包装成 `toolkit_xxx`，对话中直接调用 |
| MessageBus | 发布/订阅 + 点对点，Agent 间自由通信 |
| ExecutionPool | 线程池并行执行，批量 + 超时 + 状态查询 |

**WorkflowDAG 节点**：`TASK / CONDITION / LOOP / PARALLEL / WAIT / END` 六种类型，静态编排复杂流程。

**内置模式市场（4 个预制）**：代码审查专家 / 高级工程师 / 测试工程师 / 分析专家，一键实例化。

✅ **优势**：并行快、专注高、可组合、可观测、零代码触发
⚠️ **限制**：Token 成本高（子任务×每任务）、协调开销、上下文隔离、并发改文件需串行化

</details>

<details>
<summary><b>📡 远程设备 Agent — 使用示例</b></summary>

```python
# ① 注册设备
toolkit_remote_agent(action="register", device_id="bm1688-1",
    host="172.16.1.49", port=8282, working_path="/app/zkfs/")

# ② 下发任务（不传 session_id → 自动新建远程主题）
r = toolkit_remote_agent(action="exec", device_id="terminal-49",
    goal="分析 /record/dbs/log/ 今日日志")

# ③ 同一 session_id → 追加上下文继续对话
r2 = toolkit_remote_agent(action="exec", device_id="terminal-49",
    goal="继续排查网络问题", session_id=r["session_id"])

# ④ 任务完成 → 断开
toolkit_remote_agent(action="unregister", device_id="terminal-49")
```

</details>

---

## 📦 Mini 版（tea_agent_mini）

针对**嵌入式设备 / 资源受限 / 仅需 Web** 场景的瘦身版 —— 只依赖 7 个核心包（~5 MB vs Full 版 ~80 MB），保留 Agent 核心、Web V2、REST API、记忆、多 Agent 全部能力。

```bash
pip install tea_agent_mini        # 独立包
python build_mini.py              # 或从源码构建
python build_nuitka.py            # 或编译为单文件可执行文件（无需 Python 环境）
```

| 剔除内容 | 说明 |
|---------|------|
| ACP / Telegram | 协议与渠道层 |
| NumPy 向量 | 替换为纯 Python `math+struct` |
| Playwright / PyAutoGUI / MSS | 可选自行安装 |
| 12 个重型工具 | JS 渲染、截图、OCR、LSP 等按需启用 |

---

## 🔧 配置

配置文件 `~/.tea_agent/config.yaml`：

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  max_context_tokens: 0    # 0=默认 1M(1048576)，>0 显式指定窗口上限并启用渐进式 token 裁剪
cheap_model:               # 独立配置，用于摘要/记忆等廉价任务
  max_context_tokens: 0
embedding:
  provider: openai
  model: text-embedding-3-small
vision_model:             # 视觉模型（可选）：会话含图片时自动切换
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o-mini"    # 示例：也支持 mimo-v2.5 等视觉模型
```

- **上下文窗口控制**：`max_context_tokens` 作为"上下文已用"百分比的分母（窗口上限），超预算时按 5 级渐进裁剪（删旧历史 → 工具输出占位 → 清 thinking → 截长文 → 删旧轮）。未显式配置时默认 1M（1048576），**不做模型名推断**，避免模型名不匹配导致窗口上限误判。输入预算与 `max_tokens` 联动求解（窗口 − 输出请求 − 2% 安全余量），从源头防止"输入+输出 > 窗口"的 400 溢出；API 真返回 400 时自动修正窗口、激进压缩历史、钳制 max_tokens 后重试。
- **视觉模型自动切换**：配置 `vision_model` 后，会话输入含图片时自动使用视觉模型（回合结束恢复主模型）；另提供 `toolkit_vision_analyze` 工具供主模型委托图片分析
- **运行时调优**：Agent 可用 `toolkit_config` 自主调整参数
- **Ruff 规范**：内置 `pyproject.toml` Ruff 配置（E/F/W/I/N/UP/B/C4/SIM），Python 3.10 类型注解

---

## 🧪 测试

```bash
pytest                    # 全部单元测试（870+ 用例）
python tests/test_server_api.py --port 8282   # Server API 黑盒测试（8 套件 30+ 测试点）
```

测试覆盖：会话、工具、存储、多 Agent、LSP、ACP 协议、Server 路由、记忆系统。

---

## 🏗️ 项目结构

```
tea_agent/
├── agent.py           # Agent 统一入口
├── onlinesession.py   # 在线会话（工具循环 + 流式）
├── litesession.py     # 轻量会话
├── tlk.py             # 工具加载/注册/执行引擎（75+ 工具）
├── memory.py          # 长期记忆系统
├── config.py          # 配置管理
├── providers.py       # 50+ LLM 提供商适配
├── server/            # REST API + Web V2（Starlette + SSE）
├── protocol/          # ACP 协议
├── channel/           # Telegram / 微信适配器
├── toolkit/           # 75+ 工具模块
├── session/           # 历史压缩 / L1/L2/L3 / JSON 校验
├── store/             # 数据存储（10 子模块）
├── multi_agent/       # 多 Agent 系统
├── lsp/               # 代码智能（Jedi + Tree-sitter）
├── skills/            # 技能结晶
├── tests/             # 870+ 测试用例
└── demo/              # 演示应用（辩论赛 / 钢琴 / DAG）
```

---

## 📄 许可证

MIT License © 2024-2026 sunkw

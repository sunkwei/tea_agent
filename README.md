# Tea Agent v0.12.3

> ⚠️ **这是一个 AI 写 AI 的实验项目，自行承担责任。**

> 一个自进化 AI 编程助手 — 工具驱动、自我进化、多界面形态

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.12.3-blue)](https://pypi.org/project/tea-agent)

Tea Agent 是一款**会自我进化的 AI 编程助手**，拥有 75+ 可调用的工具，能自主编写代码、调试、搜索、文件操作、浏览器操控，并能在运行中动态加载新工具。支持 **GUI / Web / REST API / ACP Protocol** 四种界面形态。

---


## ✨ 核心特性

- 🧠 **自进化引擎** — Agent 可以修改自身代码、创建新工具、优化提示词，实现自主进化
- 🧭 **上下文感知** — 自动检测当前项目身份：在 tea_agent 自身项目中启用全部自进化能力，在外部项目中自动禁用自进化行为，专注完成用户任务
- 🧰 **75+ 内置工具** — 涵盖文件操作、代码编辑、搜索、截图、OCR、包管理、Git 等
- ⏱️ **智能命令超时** — 后台监控进程 CPU/MEM/IO，活跃进程自动延长超时至 4x，空闲进程及时终止
- 🖥️ **多种界面** — GUI（Tkinter）、Web（Starlette + SSE）、REST API、ACP Protocol，按需选择
- 🌐 **Web V2 实时流式界面** — 单页应用(SPA)，内存搜索、记忆管理、任务调度、历史会话，全部功能浏览器内完成
- 📚 **项目知识库** — 自动构建符号索引、调用图，支持代码影响分析
- 🔄 **断点续聊** — 聊天记录持久化，重启后恢复上下文
- 📋 **Plan / TODO** — 内置任务规划与追踪系统
- 🌐 **MCP 协议** — 支持连接外部 MCP Server，扩展第三方工具
- 🎯 **模式切换** — design / develop / test / review / docs / devops 六阶段工作流
- 🤖 **多 Agent 系统** — 6 阶段全栈协作：RoleAgent 角色化 + FlowEngine 事件驱动 + MessageBus 通信 + Agent-as-Tool 互调 + ExecutionPool 并行 + WorkflowDAG 编排
- 📊 **任务评估** — 自动评估任务质量，记录成功/失败经验
- 💎 **技能结晶** — Plan 执行后自动结晶 → 新对话按语义匹配注入 → 技能自进化闭环
- 🛡️ **LLM JSON 容错** — 智能修复截断JSON、控制字符、单引号、尾逗号等常见LLM输出问题

---

## 📦 安装

```bash
# 从 PyPI 安装
pip install tea_agent

# 或从源码
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
pip install -e .

# Web 界面依赖（可选）
pip install starlette uvicorn python-multipart
```

Playwright 浏览器（可选，用于 JS 渲染页面抓取）：
```bash
playwright install chromium
```

---

## 📦 Mini 版（tea_agent_mini）

对于**嵌入式设备、资源受限环境或仅需 Web 界面**的场景，Tea Agent 提供 **Mini 版**（`tea_agent_mini`）—— 在保留核心功能的同时大幅缩减体积和依赖。

### ✨ 特性对比

| 能力 | Full 版 | Mini 版 |
|------|---------|---------|
| Agent 核心引擎 | ✅ | ✅ 完整保留 |
| Web V2 界面（SPA） | ✅ | ✅ 完整保留 |
| REST API Server | ✅ | ✅ 完整保留 |
| 内存搜索 / 记忆管理 | ✅ | ✅ 完整保留 |
| 任务评估 / 技能结晶 | ✅ | ✅ 完整保留 |
| 任务调度 / PDF 导出 | ✅ | ✅ 完整保留 |
| 配置切换 | ✅ | ✅ 完整保留 |
| GUI 桌面界面 | ✅ | ❌ |
| ACP Protocol | ✅ | ❌ |
| 文件上传配置 (Drag & Drop) | ✅ | ✅ `python-multipart` 支持 |
| NumPy 向量操作 | ✅ | ❌ 替换为纯 Python `math+struct` |
| Playwright (JS 渲染) | ✅ | ❌ 可选自行安装 |
| PyAutoGUI / MSS (截图) | ✅ | ❌ 可选自行安装 |
| TkinterWeb（富文本） | ✅ | ❌ |

### 📐 打包原理

`build_mini.py` 从 `tea_agent/` 源码中智能筛选文件：

```
build_mini.py 工作流程
  │
  ├─ 1. 复制核心模块:
  │     ├─ 顶层 .py: agent.py, config.py, memory.py 等 20 个核心文件
  │     ├─ session/ — 会话管理 (历史压缩/Token 裁剪)
  │     ├─ store/   — 数据存储 (10 子模块)
  │     ├─ toolkit/ — 排除 12 个重型工具 (见下方)
  │     ├─ server/  — Web 服务器 (路由 + 静态资源)
  │     ├─ multi_agent/ — 多 Agent 协作
  │     ├─ evaluation/ — 任务评估
  │     └─ skills/  — 技能结晶 (.md 文档 + 注册表)
  │
  ├─ 2. 排除的包和文件:
  │     ├─ _gui/     — Tkinter 桌面 GUI
  │     ├─ gui.py / gui_dialogs.py — GUI 桌面入口
  │     └─ demo/ / tests/ / scripts/
  │
  ├─ 3. 排除的重型工具 (HEAVY_TOOLS):
  │     toolkit_js_fetch   (Playwright)
  │     toolkit_input      (PyAutoGUI)
  │     toolkit_screenshot (mss/PIL)
  │     toolkit_screen_read (OCR)
  │     toolkit_ocr        (OCR)
  │     toolkit_lsp        (Jedi/Tree-sitter)
  │     toolkit_browser_tab (Playwright)
  │     toolkit_clipboard  (GUI 依赖)
  │     toolkit_sudo_gui   (提权)
  │     toolkit_test_gui   (GUI 测试)
  │     toolkit_explr      (符号索引)
  │     toolkit_pkg        (包管理)
  │
  ├─ 4. 去除 NumPy 依赖:
  │     store/_vectors.py         numpy → math+struct
  │     store/_memories.py        numpy → math+struct
  │     store/_semantic_search.py numpy → math+struct
  │     store/_conversations.py   numpy → math+struct
  │
  └─ 5. 生成独立 wheel:
        ├─ pyproject.toml (仅 mini 依赖)
        ├─ README.mini.md
        └─ 打包 → tea_agent_mini-{version}-py3-none-any.whl
```

### 📦 安装

```bash
# 方法一：从 PyPI 安装（Mini 版已发布为独立包，待上架）
pip install tea_agent_mini

# 方法二：从源码构建
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
python build_mini.py

# 构建产物位于 build_mini_dist/dist/
pip install build_mini_dist/dist/tea_agent_mini-*.whl
```

### 🔨 编译为单文件可执行文件

`build_nuitka.py` 将 Mini 版进一步编译为**单文件可执行文件**（`.exe` / ELF），无需 Python 环境即可运行。

```bash
# 单文件模式（适合分发给无 Python 环境的用户）
python build_nuitka.py

# standalone 目录模式（调试用，编译更快）
python build_nuitka.py --standalone

# 输出：build_nuitka_dist/tea-agent-mini[.exe]  (~60 MB)
```

> ⚠️ 编译耗时较长（5-30 分钟），需要安装 Nuitka 和 C 编译器。
> 日常使用推荐 `pip install` 方式。

### 🚀 使用

Mini 版安装后与 Full 版的 Web 界面使用方式完全一致：

```bash
# 启动 Web V2 界面（推荐）
python -m tea_agent.server

# 或通过入口命令
tea-agent-mini    # 等效于 python -m tea_agent_mini.__main__
```

浏览器访问 `http://127.0.0.1:8080` 即可使用完整的 Web 界面（对话、记忆管理、任务调度、搜索、PDF 导出等全部功能）。

### 🧩 Mini 版依赖清单

Mini 版仅依赖 **7 个核心包**，合计安装体积约 **5 MB**（Full 版约 80 MB）：

```
openai>=1.0.0           # LLM API 调用
httpx>=0.25.0           # HTTP 客户端
PyYAML>=6.0             # 配置文件
requests>=2.30.0        # HTTP 请求
starlette>=0.37.0       # Web 框架
uvicorn>=0.27.0         # ASGI 服务器
python-multipart>=0.0.7 # 文件上传解析
```

> 💡 Mini 版不包含 NumPy（~15 MB）、Playwright（~30 MB）、PyAutoGUI（~3 MB）等重型依赖，非常适合 **Docker 镜像、树莓派、低配 VPS、CI/CD 管道**等场景。

### 📊 体积对比

| 维度 | Full 版 | Mini 版 |
|------|---------|---------|
| 安装包大小 | ~600 KB | ~250 KB |
| 解压后体积 | ~3 MB | ~1.2 MB |
| 运行时依赖 | ~80 MB | ~5 MB |
| Python 文件数 | ~420 | ~280 |
| 工具数 | 75+ | 50+ |

---

## 🚀 快速开始

```bash
# Web V2 界面 — 单页应用，全功能浏览器体验（推荐）
python -m tea_agent.server

# GUI 桌面界面（Tkinter）
tea_agent

# ACP Protocol Server（VS Code 集成）
python -m tea_agent.protocol --port 9090
```

---

## 💻 界面形态

Tea Agent 提供 **五种界面形态**，覆盖从桌面到 Web、从命令行到 API 的全部使用场景。

---

### 1. GUI 桌面界面 (`tea_agent`)

基于 **Tkinter** 的原生桌面客户端，支持 Windows / Linux / macOS。

**启动方式：**
```bash
tea_agent                         # 入口命令
python -m tea_agent.gui           # 模块方式
```

**功能特性：**
- 🔄 实时流式对话，Markdown 渲染，工具调用可视化
- 📋 左侧会话列表，支持搜索、切换、新建、删除
- 🧠 长期记忆管理面板（查看/搜索/添加/删除）
- ⏱️ 定时任务管理（scheduler 增删改查）
- 📤 PDF 导出、聊天记录导出
- 🌙 系统托盘常驻，全局热键唤出
- 🎨 主题切换 + 字体缩放

---

### 2. Web V2 界面 (`python -m tea_agent.server`)

新一代单页应用（SPA），纯前端 HTML/JS + 后端 Starlette API，所有功能在浏览器中完成。

> **注意**：`python -m tea_agent.server` 同时启动 REST API 和 Web V2 前端。
> 浏览器访问 `http://127.0.0.1:8080` 即可使用完整 Web 界面。

**启动方式：**
```bash
python -m tea_agent.server           # 默认端口 8080
tea-agent-api                        # PyPI 入口
python -m tea_agent.server --port 8099 --host 0.0.0.0
```

**界面特性：**

| 功能 | 说明 |
|------|------|
| 💬 **流式对话** | SSE 实时推送，逐 token 输出 |
| 📋 **会话管理** | 左侧列表面板，点击切换历史会话，自动加载消息 |
| 🧠 **记忆管理** | 弹窗面板，查看/搜索/添加/删除长期记忆 |
| ⏱️ **任务调度** | 定时任务 CRUD，cron / interval / daily 等 |
| 🔍 **全局搜索** | 搜索聊天记录、记忆、任务 |
| 📤 **PDF 导出** | 导出当前会话为 PDF |
| 🌙 **主题切换** | 深色/浅色主题 + 强调色定制 |
| ⚡ **配置切换** | 底部下拉框一键切换 `~/.tea_agent/*.yaml` 配置文件 |
| 📎 **图片预览** | 消息中图片点击放大 |

**技术架构：**
```
前端: 纯 HTML5 + CSS3 + Vanilla JS（无框架依赖）
后端: Starlette + SSE 流式
API:  /v1/chat/completions（OpenAI 兼容）
      /v1/sessions（CRUD）
      /v1/memory（记忆管理）
      /v1/tasks（任务调度）
      /v1/search（全局搜索）
      /v1/export/pdf（PDF 导出）
```

**并发流式架构（v0.10.0+）：**

```
请求 A ─→ create_session() → OnlineToolSession A 🔓（独立配置 X）
请求 B ─→ create_session() → OnlineToolSession B 🔓（独立配置 Y）
请求 C ─→ create_session() → OnlineToolSession C 🔓（独立配置 Z）

共享资源: Toolkit（只读）+ Storage（线程安全）
流式操作: 每请求独立 Session，无需全局锁，真正并发
非流式操作: 共享 Agent + 锁（管理/配置类接口）
```

**指定配置文件** — 流式请求可通过 `config_path` 参数使用不同配置：

```bash
# Web UI 自动发送当前选中配置；API 可手动指定
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true,"config_path":"/home/user/.tea_agent/config_prod.yaml"}'
```

不同 Web 实例可使用不同配置文件，各自独立运行不同模型。

---

### 3. REST API Server (`python -m tea_agent.server`)

OpenAI 兼容的 HTTP API 服务器，方便第三方应用集成。

**启动方式：**
```bash
tea-agent-api                        # PyPI 入口
python -m tea_agent.server           # 模块方式
python -m tea_agent.server --port 8081 --host 0.0.0.0
```

**API 路由：**

| 方法 | 路由 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/v1/chat/completions` | OpenAI 兼容聊天（支持 stream、config_path） |
| `GET` | `/v1/models` | 当前模型信息 |
| `GET` | `/v1/tools` | 所有可用工具列表 |
| `POST` | `/v1/tools/{name}/run` | 直接调用指定工具 |
| `GET/POST` | `/v1/sessions` | 列出/创建会话 |
| `GET/DELETE` | `/v1/sessions/{id}` | 获取/删除会话 |
| `GET` | `/v1/sessions/{id}/messages` | 获取会话消息 |
| `GET` | `/v1/config` | 获取配置 |
| `POST` | `/v1/config/switch` | 切换配置文件 |
| `GET/POST/DELETE` | `/v1/memory` | 记忆管理 |
| `GET/POST/DELETE` | `/v1/tasks` | 定时任务管理 |
| `GET` | `/v1/search` | 全局搜索 |
| `POST` | `/v1/export/pdf` | 导出 PDF |
| `GET` | `/docs` | OpenAPI 文档 |
| `GET` | `/openapi.json` | OpenAPI Schema |

**示例：**
```bash
# 流式聊天
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true}'

# 非流式聊天
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'

# 列出会话
curl http://127.0.0.1:8080/v1/sessions

# 搜索
curl "http://127.0.0.1:8080/v1/search?q=keyword"
```

---

### 4. ACP Protocol Server (`python -m tea_agent.protocol`)

Agent Communication Protocol 服务器，提供标准化的 Agent-to-Agent 通信，可用于 VS Code / Cursor 等 IDE 集成。

**启动方式：**
```bash
python -m tea_agent.protocol --port 9090
```

**API 路由：**

| 方法 | 路由 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/v1/agents` | 发现所有可用 Agent |
| `GET` | `/v1/agents/tea-agent` | Tea Agent 详情（含工具列表） |
| `POST` | `/v1/agents/tea-agent/chat` | 发送消息（支持 stream） |
| `GET/POST` | `/v1/sessions` | 列出/创建会话 |
| `GET/DELETE` | `/v1/sessions/{id}` | 获取/删除会话 |
| `GET` | `/v1/sessions/{id}/messages` | 获取会话消息 |

**特性：**
- 🧰 **工具发现** — 客户端可查询 Agent 的完整工具列表和 JSON Schema
- 📡 **SSE 流式** — 实时推送对话内容，支持逐 token 输出
- 🧵 **会话管理** — 多会话隔离，可获取历史消息
- 🔗 **IDE 集成** — 标准 ACP 协议，可对接任何 ACP 客户端
- 🔒 **配置隔离** — 使用独立配置文件 `~/.tea_agent/config_acp.yaml` 和数据库 `chat_acp.db`，不影响主应用配置

---

---

## 🧠 长期记忆系统

Tea Agent 的记忆系统模拟人类记忆的工作方式：**优先级分层**、**相关性检索**、**自然衰减**、**去重合并**。底层基于 SQLite 持久化 + embedding 语义向量，由 `MemoryManager` 统一管理。

---

### 1. 记忆存储结构

每条记忆包含以下核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `content` | TEXT | 记忆内容（精简摘要） |
| `priority` | INT (0-3) | 优先级：`0=CRITICAL` / `1=HIGH` / `2=MEDIUM` / `3=LOW` |
| `importance` | INT (1-5) | 重要度：5=关键，忽略会导致严重问题；1=琐碎 |
| `category` | TEXT | 分类：`instruction`(指令) / `preference`(偏好) / `fact`(事实) / `reminder`(提醒) / `general`(通用) |
| `tags` | TEXT | 逗号分隔标签，用于快速匹配 |
| `content_hash` | TEXT | SHA256 前 16 位，快速去重指纹 |
| `embedding` | BLOB | `numpy.float32` 向量，用于余弦相似度语义搜索 |
| `expires_at` | DATETIME | 过期时间，NULL=永不过期 |
| `pinned` | INT | 是否钉住（豁免年龄衰减） |
| `created_at` | DATETIME | 创建时间（用于年龄衰减计算） |

---

### 2. 选择算法

每次对话开始时，`MemoryManager.select_memories()` 从活跃记忆池中选出最相关的 **≤30 条** 注入上下文：

```
score = 相关性(关键词匹配) × 重要度(importance/5) × 时效因子 × 优先级因子

时效因子: 1天内=1.0, 7天=0.9, 30天=0.7, 90天=0.5, >90天=0.3
优先级因子: (4 - priority) / 4
```

**分层保底策略**（确保不会全选 CRITICAL）：

```
1. CRITICAL 优先入选（上限 10 条，FIFO 取最新）
2. 非 CRITICAL 按 score 排序
3. 分层保底配额：
   - HIGH   ≥ 3 条
   - MEDIUM ≥ 2 条
   - LOW    ≥ 1 条
4. 剩余名额自由竞争（score 最高的先选）
5. 入选记忆更新 last_accessed_at
```

---

### 3. 年龄衰减

模拟 Ebbinghaus 遗忘曲线。每次选择前自动执行 `degrade_by_age()`，**pinned=true 的记忆豁免**：

| 原始优先级 | 衰减条件 | 降级为 |
|-----------|---------|--------|
| CRITICAL | 创建 > 30 天 | HIGH |
| HIGH | 创建 > 60 天 | MEDIUM |
| MEDIUM | 创建 > 90 天 | LOW |

---

### 4. LLM 优先级精调

`MemoryManager.llm_adjust_priorities()` 使用便宜 LLM 评估近期对话主题，微调记忆优先级：

```
输入：近期对话主题摘要 (≤2000字符) + 当前活跃记忆列表 (≤100条, 每条≤80字符预览)
规则：
  - 只能 ±1 级调整（不允许跳级）
  - 每次最多调整 3 条
  - 升级时重置 created_at（重新计时衰减）
  - 仅输出 JSON 数组，无额外文本
```

---

### 5. 记忆提取

对话结束后，`MemoryManager` 通过 LLM 从用户消息中自动提取记忆：

```
提取分类：
  instruction → 用户明确要求"记住"的规则   → priority=0 (CRITICAL)
  preference  → 用户表达的习惯/偏好          → priority=1 (HIGH)
  reminder    → 有时效性的提醒（含 expires_at）→ priority=1 (HIGH)
  fact        → 技术事实/架构决策             → priority=2 (MEDIUM)
  general     → 其他参考信息                 → priority=3 (LOW)

容错解析：
  1. 直接 JSON.parse
  2. 提取 markdown ```json 代码块
  3. 提取 JSON 数组正则匹配
  4. 对象型 -> 从常见键名 (memories/items/results/data) 提取数组
```

---

### 6. 去重合并

提取结果写入前，`ingest_extracted()` 执行去重合并流水线：

```
每条新记忆：
  1. jieba 分词 → 关键词 Jaccard 相似度计算
  2. 同分类加权 10%
  3. 相似度 ≥ 0.3 → 合并更新已有记忆：
     - content: 保留更长的，或拼接
     - priority: 取较小值（更关键）
     - importance: 取较高值
     - tags: 并集去重
     - expires_at: 保留更早的过期时间
  4. < 0.3 → 新增记录
```

**批量去重** (`detect_duplicates` / `auto_dedup`)：通过 embedding 余弦相似度（阈值 0.92）扫描全部活跃记忆，发现近似重复对自动合并提权。

---

### 7. CRITICAL FIFO 淘汰

CRITICAL 记忆上限 15 条，超出时软删除最旧的（FIFO），防止指令记忆无限膨胀。

---

### 8. 反思归纳

`reflect_and_summarize()` 按类别聚类近期记忆，生成摘要并归档：

```
类别聚类 (instruction/preference/fact/reminder/general)
  → 每类 ≥ 2 条 → 关键词频率生成摘要
  → 摘要作为 CRITICAL/importance=5 存储
  → 原始记忆 importance -1（降级）
```

---

### 格式化注入

入选记忆按优先级格式化注入系统提示区：

```python
def _prefix_for(memory):
    if priority == CRITICAL:  return "!!! 必须遵循:"
    if category == "reminder": return "⏰ 提醒:"
    if category == "preference": return "💡 偏好:"
    if category == "fact":      return "📌 事实:"
    return "📎"
```

> Agent 可通过 `toolkit_memory` 工具手动管理记忆（增删查改）。见 [`docs/TOOLS.md`](docs/TOOLS.md)

---

## 📜 四级历史压缩 (L0 → L3 → L2 → L1)

Tea Agent 使用**四级分层**构建发送给 LLM 的上下文，在有限的 token 窗口内最大化信息密度。四大层级由 `session/_history_builder.py` 的 `build_api_messages()` 统一组装。

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

---

### Level 0: 系统层

```python
# build_api_messages() 中的 L0 组装顺序
result = []

# 1. 系统提示词
result.append({"role": "system", "content": system_prompt})

# 2. 未完成任务自动恢复 (toolkit_task_resume)
resume_info = toolkit_task_resume(action="check")
if resume_info["has_pending"]:
    result.append({"role": "user", "content": format_resume(resume_info)})

# 3. 长期记忆注入
if context._injected_memories_text:
    result.append({"role": "user", "content": context._injected_memories_text})
```

---

### Level 3 (L3) — 语义摘要

`SummaryStore` 管理两种 L3 摘要：

| 摘要类型 | 存储位置 | 生成时机 | 内容 |
|---------|----------|---------|------|
| **语义摘要** | `topics.semantic_summary` | L2 溢出时（50→20 裁剪） | 项目背景 / 已完成修改 / 关键决策 / 错误修复 / 架构约束 / 用户偏好 / 待办事项 |
| **工具链摘要** | `topics.tool_chain_summary` | 后台异步线程 | 最近一轮工具调用链回顾 |

**L2→L3 摘要生成** (`generate_l2_to_l3_summary`)：

```
触发条件: push_to_level2() 返回 should_summarize=True
          (即 L2 count ≥ 50 → 最老 30 条溢出)

摘要流程:
  1. 取溢出 30 条 L2 条目（含 user + thinking + assistant）
  2. 合并现有 L3 摘要（如有）
  3. 用 cheap model 生成新摘要（参数: temperature=0.3, max_tokens=4096）
  4. 存入 topics.semantic_summary
  5. L2 裁剪到最新 20 条

压缩比: 30 轮对话 (≈20K tokens) → ~500 tokens 摘要
```

**L3 注入格式**：

```
[系统记忆 — 以下为需要遵循的有效信息和规则]

##### 长期背景/偏好/关键结论
{semantic_summary}

---

##### 历史工具调用链回顾
{tool_chain_summary}
```

---

### Level 2 (L2) — 历史对列表

L2 是一个**固定大小的环形缓冲区**，存储在 SQLite `topics.level2_json` 列中，容量 50 条。

**条目结构**：

```json
{
  "user": "用户的原始消息",
  "assistant": "AI 的最终回复（不含工具调用中间过程）",
  "thinking": "工具调用轮的 assistant content + reasoning（从 rounds 中提取）",
  "files": ["涉及的文件路径（可选）"]
}
```

**写入流程** (`push_to_level2`)：

```python
def push_to_level2(topic_id, user_msg, ai_msg, files, rounds):
    # 从 rounds 中提取 thinking：所有带 tool_calls 的 assistant 消息
    thinking = extract_thinking_from_rounds(rounds)
    entry = {"user": user_msg, "assistant": ai_msg, "thinking": thinking, "files": files}
    level2.append(entry)

    overflow = []
    should_summarize = False
    if len(level2) >= 50:
        overflow = level2[:30]      # 最老 30 条 → 送给 L3 摘要
        level2 = level2[-20:]        # 保留最新 20 条
        should_summarize = True

    return len(level2), overflow, should_summarize
```

**相关性筛选** (`filter_level2_by_relevance`)：

```
对每条 L2 条目，用当前 user 消息的关键词做 Jaccard 相似度匹配：
  - 提取 user 消息的 2字中文 + 3字母英文关键词
  - 提取 L2 条目的 user + thinking + assistant 中的关键词
  - 计算 Jaccard 系数: |交集| / |并集|
  - 文件路径额外加权 (file_overlap ≥ 1 → min(score, 0.4 + count × 0.1))

筛选规则:
  ≥ 0.15   →  保留完整 user+assistant 对（注入为 [历史记录]）
  ≥ 0.05   →  仅保留摘要片段（"User: xxx... → Assistant: yyy..."）
  < 0.05   →  不注入（节省 token）
 全部<0.05 →  保底注入最高分的一条（完整对）
```

---

### Level 1 (L1) — 最新对话

L1 是**当前 session 的原始消息**（`context.messages`），经多层压缩后传入 API。

#### 第一道防线：实时工具输出截断

每个工具调用返回时立即截断，防止单个输出超大：

```python
max_tool_output = 128 * 1024  # 128KB
if len(result_bytes) > max_tool_output:
    # 首尾各保留一半，按换行边界对齐
    head = result_bytes[:max_tool_output // 2]  # 64KB
    tail = result_bytes[-max_tool_output // 2:] # 64KB
    result_str = f"{head.decode()}\n\n... [工具输出截断] ...\n\n{tail.decode()}"
```

#### 第二道防线：旧工具输出占位符化

`_find_prune_cutoff()` 找到最近 3 个 user 消息的分界线：

```
3 轮外的 tool 消息 → "[工具结果已省略: N 字符]"
3 轮内的 tool 消息 → 完整保留
```

#### 第三道防线：渐进式 token 裁剪

当 `max_context_tokens > 0` 时，触发 `_progressive_trim()` 5 级裁剪：

| 策略 | 操作 | 说明 |
|------|------|------|
| 1 | 删除 `[历史记录]` L2 条目 | 最旧的先删 |
| 2 | 替换旧工具输出为占位符 | `[工具结果已省略: N 字符]` |
| 3 | 清空 reasoning_content | 释放 thinking token |
| 4 | 截断长文本 | 限制 4096 字符 |
| 5 | 删除 L1 旧轮次 | 保留最近 5 轮 user 消息 |
| 兜底 | 截断最后一条消息 | 仅保留前 1/3 |

---

### 组装流程总览

```
build_api_messages(context, system_prompt) 完整流程:

1. Level 0: 系统提示词 + TODO 恢复 + 记忆注入
2. Level 3: 语义摘要 + 工具链摘要 (注入后加 assistant "好的，已了解...")
3. Level 2: 相关性筛选 → [历史记录] user + assistant 对
4. Level 1: 截断边界计算 → tool 占位符 → 消息遍历:
   - tool_calls 完整性检查
   - 多模态格式转换
   - reasoning_content 补齐
5. 渐进式裁剪: estimate_messages_tokens() > 80% budget → _progressive_trim()
6. JSON 完整性校验 + 孤立 tool 消息移除
```

### Token 估算

使用启发式算法快速估算 token 数（无需 tiktoken）：
- 英文：约 4 字符 = 1 token
- 中文：约 1.5 字 = 1 token
- 图片：固定 ~85 tokens
- 消息结构开销：每条 +4 tokens

### 异步摘要

每轮对话结束后，`do_async_summaries()` 在后台线程执行：
1. **标题摘要** (`auto_summary`): 用 cheap model 为 topic 生成一句话标题
2. **L2→L3 摘要** (`l2_to_l3_summary`): 仅在 L2 溢出时触发

便宜模型产生的 token 消耗通过 `agent._pending_cheap_tokens` 合并到下一轮 GUI 显示。

---

## 🔄 自进化引擎

Tea Agent 的自进化体系由**五个层次**构成：工具热插拔（基础）→ 安全自修改 → 提示词进化 → 经验固化 → 后台进化线程。

---

### 0. 上下文感知规则（前置约束）

> **核心设计原则：自进化能力只在 tea_agent 自身项目内激活。**

自进化是一把双刃剑——在开发 tea_agent 自身时是核心优势，但在修改其他项目时会变成有害噪声。因此系统提示词内建了**项目身份检测**逻辑：

```
每次任务开始前，检测当前项目身份：
1. 如果是 tea_agent 项目自身（特征：当前目录或父目录存在 tea_agent/agent.py）
   → 启用全部自进化能力：可创建工具、修改源码、优化提示词
2. 如果是外部项目（非 tea_agent 自身）
   → 禁用自进化行为：不创建新工具、不修改源码框架、不优化提示词
   → 专注于完成用户的外部任务，仅使用通用文件读写/搜索/编辑工具
```

这个规则写入 `prompt_manager.py` 和 `litesession.py` 的默认系统提示词中，所有会话模式（OnlineToolSession / LiteSession / Sub-agent）一视同仁。

此外，**AGENTS.md**（如果存在）可以进一步细化项目级约束。详见 [`AGENTS.md`](AGENTS.md)。

---

### 1. 工具热插拔：`toolkit_save` / `toolkit_reload`

Agent 可以在运行时创建新工具、修改现有工具，并**立即生效**，无需重启。

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
  │     └─ 自动生成 skills/{name}/SKILL.md 文档
  │
  ├─ 4. toolkit_reload()
  │     ├─ 扫描 toolkit/ 目录所有 .py 文件
  │     ├─ 动态 importlib 加载模块
  │     ├─ 注册 meta 函数 → 生成 tool schema
  │     └─ 所有 toolkit_* 函数 → 全局可用
  │
  └─ 5. 新工具立即可用于后续对话
```

**版本管理**：

| 特性 | 说明 |
|------|------|
| **自动版本号** | 每次 save 自动递增 `v1.0.0 → v1.0.1 → v1.1.0` |
| **安全回滚** | `toolkit_rollback(name, version)` 可回退到任意历史版本 |
| **版本列表** | `toolkit_list_versions(name)` 查看所有历史版本 |
| **SKILL.md** | 保存后自动生成技能文档，参数表 + 示例代码 |

---

### 2. 五层安全自修改：`toolkit_self_evolve`

Agent 修改自身代码时，通过**五层安全机制**确保不会自毁：

```
┌──────────────────────────────────────────────┐
│  Layer 0: Git 快照                              │
│  git add + git commit "snapshot: pre-evolve"   │
│  仅在工作区干净时执行                            │
├──────────────────────────────────────────────┤
│  Layer 1: 时间戳 .bak 文件                       │
│  {file}.bak.{YYYYMMDD_HHMMSS}                 │
│  永不覆盖历史备份                                │
├──────────────────────────────────────────────┤
│  Layer 1.5: Python 语法严格检查                  │
│  换行符 / 缩进 / 括号匹配 / 冒号缺失 / 分号      │
│  失败 → 立即回滚                                 │
├──────────────────────────────────────────────┤
│  Layer 2: py_compile 编译验证                   │
│  失败 → 自动回滚 tmp_bak + git reset --hard    │
├──────────────────────────────────────────────┤
│  Layer 2.5: LSP 智能检查                        │
│  ├─ 影响分析 (ts_analyzer): 调用者/依赖/风险    │
│  ├─ ruff lint 对比: 新旧 lint 数量差异          │
│  ├─ 函数签名对比: 参数是否变更                   │
│  └─ jedi 语义诊断: 未定义/未使用的符号           │
│  非阻塞：lint 新增 > 0 或签名变更仅警告          │
├──────────────────────────────────────────────┤
│  Layer 3: pytest 测试验证                       │
│  失败（passed < total）→ git reset --hard 回滚  │
└──────────────────────────────────────────────┘
```

回滚链：Layer 1.5 失败 → 恢复 tmp_bak；Layer 2 失败 → 恢复 git；Layer 3 失败 → git reset --hard。

---

### 3. 提示词进化：`toolkit_prompt_evolve`

Agent 可以**自我优化系统提示词**，由 `SystemPromptManager` 管理多版本：

```
版本管理流程:
  配置表 system_prompts (is_active, version, content, created_at)

进化操作:
  action='list'     → 查看所有版本历史
  action='current'  → 查看当前活跃版本
  action='evolve'   → 基于反思建议 + 长期记忆 → LLM 生成新版本 → 设为活跃
  action='rollback' → 回滚到指定版本（旧版设为活跃）
  action='set'      → 手动设置新版本

进化输入:
  - 当前提示词 (≤500字要求)
  - 最近的反思建议 (ReflectionManager.last_prompt_suggestion)
  - 相关长期记忆 (MemoryManager 选取)
```

---

### 4. 经验固化：`toolkit_experience_solidify`

任务完成后自动复盘，转化为可复用模式：

```
action='auto':
  analyze → 分析任务执行过程
  ├─ 成功 → solidify → 固化到技能库 (toolkit_dynamic_skill)
  └─ 失败 → lesson   → 记录到经验库 (toolkit_evolution_exp)

分类标签:
  dependency / architecture / ui / performance / testing / deployment
```

**动态技能系统** (`toolkit_dynamic_skill`)：

```
record     → 记录成功的 agent 组合模式（task + agents[]）
recommend  → 根据任务推荐 agent 组合
search     → 搜索相似技能模式
list       → 列出所有技能模式
```

---

### 5. 后台进化线程：`toolkit_self_evolve_thread`

每小时自动运行一轮三合一巡检：

```
1. 工具使用率分析 → 优化建议
   - 统计各工具调用次数
   - 识别低使用率工具（建议删除或合并）
   - 识别高频组合（建议合并为复合工具）

2. docs/TOOLS.md 同步
   - 扫描 toolkit/ 目录
   - 根据 meta 信息生成工具文档
   - 按类别分组 + 参数表格

3. 技能模式整理
   - 清理过时技能
   - 合并相似模式
   - 更新模式评分
```

---

### 自进化能力全景

| 能力 | 工具 | 安全层级 | 说明 |
|------|------|---------|------|
| 创建新工具 | `toolkit_save` + `toolkit_reload` | 版本回滚 | 热插拔，无需重启 |
| 修改源文件 | `toolkit_self_evolve` | 5层安全 | Git↔Bak↔编译↔LSP↔测试 |
| 优化提示词 | `toolkit_prompt_evolve` | 版本回滚 | 基于反思+记忆 |
| 固化经验 | `toolkit_experience_solidify` | 分类标签 | 成功→技能，失败→教训 |
| 后台进化 | `toolkit_self_evolve_thread` | 每小时 | 工具分析+文档同步+技能整理 |
| 代码智能 | `toolkit_lsp` | 只读 | diagnose/completion/definition/references |

---

## 🧰 工具概览（75+）

| 类别 | 工具 |
|------|------|
| 📁 文件操作 | `toolkit_file`, `toolkit_save_file`, `toolkit_explr` |
| ✏️ 代码编辑 | `toolkit_edit`, `toolkit_diff_edit`, `toolkit_diff`, `toolkit_self_evolve`, `toolkit_clean_comments`, `toolkit_format_code`, `toolkit_auto_fix`, `toolkit_comment` |
| 🔍 搜索 | `toolkit_search`, `toolkit_lsp`, `toolkit_query_chat_history` |
| 📸 截图/OCR | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_screen_read` |
| 🖱️ 操控 | `toolkit_input`, `toolkit_browser_tab`, `toolkit_js_fetch` |
| 📦 包管理 | `toolkit_pkg`, `toolkit_build`, `toolkit_read_pyproject` |
| 🧪 测试 | `toolkit_run_tests`, `toolkit_test_gui` |
| 🗓️ 工具 | `toolkit_lunar`, `toolkit_weather_my`, `toolkit_gettime`, `toolkit_date_diff` |
| 🔧 系统 | `toolkit_exec`, `toolkit_config`, `toolkit_os_info`, `toolkit_sudo_gui` |
| 🧠 记忆/知识 | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 多 Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_auto_pipeline` |
| 📋 计划/任务 | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume` |
| 🔌 MCP 集成 | `toolkit_mcp` |
| 🌐 Web/GUI | `toolkit_browser_tab`, `toolkit_dump_topic`, `toolkit_export_last_pdf`, `toolkit_notify` |
| 📤 导出 | `toolkit_dump_topic`, `toolkit_export_last_pdf` |
| 🧬 自进化 | `toolkit_self_evolve`, `toolkit_self_evolve_thread`, `toolkit_prompt_evolve`, `toolkit_evolution_exp` |
| 🛠️ 其他 | `toolkit_question`, `toolkit_stream_save`, `toolkit_set_topic_title`, `toolkit_self_report`, `toolkit_comment`, `toolkit_toggle_reasoning`, `toolkit_get_config_path`, `toolkit_get_models`, `toolkit_list_provider_models`, `toolkit_ip_location_my`, `toolkit_custom_commands`, `toolkit_scheduler_storage`, `toolkit_mode` |

> 完整工具列表见 [`docs/TOOLS.md`](docs/TOOLS.md)（每小时自动更新）


## 🤖 多 Agent 系统（v0.11+）

Tea Agent 的 Multi-Agent 系统是一个**从简单到复杂、从对话到编程**的全栈协作框架。覆盖 6 个发展阶段：

```
Phase 1: 核心架构        RoleAgent + FlowEngine + RoleDispatcher
Phase 2: Agent 间通信    MessageBus + Agent-as-Tool + ToolRegistry
Phase 3: 可观测性        CheckpointManager + TraceEngine
Phase 4: 管理模式市场    PatternMarket + AdminPanel
Phase 5: 并行执行引擎    ExecutionPool + LoadBalancer + CircuitBreaker
Phase 6: 高级编排        WorkflowDAG（条件/循环/并行/等待）
```

---

### 🚀 快速上手

#### 方式一：对话中直接使用（零代码）

无需写 Python，直接在对话中调用工具：

| 工具 | 用途 |
|------|------|
| `toolkit_parallel_subtasks` | 分解复杂任务 → 并行执行 → 自动汇总 |
| `toolkit_subagent` | 生成独立子 Agent 执行任务（sync/async） |
| `toolkit_subagent_msg` | 子 Agent 间点对点通信 |

**示例** — 并行分析多个文件：
```
直接告诉 Agent：「帮我并行审查 src/ 下所有 .py 文件」
Agent 会自动调用 toolkit_parallel_subtasks 分解 + 执行 + 汇总。
```

**子 Agent 通信示例：**
```
# Agent A 发送消息给 Agent B
toolkit_subagent_msg(action="send", to="agent-B", message="分析结果已就绪")

# Agent B 接收
toolkit_subagent_msg(action="check_inbox", agent_id="agent-B")
```

---

#### 方式二：Python API（编程集成）

##### RoleDispatcher — 一步到位

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()

# 自动识别任务模式（重构/审查/测试/修复/文档/功能开发）
result = dispatcher.dispatch("重构项目添加类型注解")
print(result["summary"])
# → ✅ 全部完成: 重构项目添加类型注解 (4 步, 12.3s)

# 可视化执行计划（不执行）
print(dispatcher.visualize("为 gui.py 添加类型注解"))
```

##### RoleAgent — 角色化 Agent

```python
from tea_agent.multi_agent import RoleAgent

analyst = RoleAgent(
    role="资深代码审查员",
    goal="审查代码质量，识别设计问题和代码坏味道",
    backstory="你拥有 15 年软件架构经验，精通各种设计模式和重构技术。",
)
result = analyst.execute("审查 dispatcher.py 的设计")
print(result.structured)  # Pydantic 结构化输出
```

预制角色快捷创建：
```python
from tea_agent.multi_agent import (
    create_analyst, create_coder, create_tester, create_reviewer,
)

coder = create_coder(goal="实现用户登录模块")
tester = create_tester(goal="为登录模块编写测试")
reviewer = create_reviewer(goal="审查登录模块代码")
```

##### FlowEngine — 事件驱动工作流

```python
from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

class ReviewFlow(FlowEngine):
    @flow_start()
    def scan(self):
        """步骤1: 代码扫描"""
        return self.call_agent("reviewer", "全面审查代码")

    @flow_listen(scan)
    def report(self):
        """步骤2: 生成报告（scan 完成后自动触发）"""
        issues = self.state.get("scan_result", {})
        return f"发现 {len(issues)} 个问题"

flow = ReviewFlow()
result = flow.run()
```

**内置 Flow 模式：**

| 模式 | Flow 类 | 执行步骤 |
|------|---------|---------|
| 重构 | `RefactorFlow` | 分析 → 规划 → 执行 → 验证 |
| 审查 | `ReviewFlow` | 扫描 → 报告 |
| 测试 | `TestFlow` | 规划测试 → 编写 → 运行 |
| 修复 | `FixFlow` | 诊断 → 修复 → 验证 |
| 功能开发 | `FeatureFlow` | 分析 → 实现 → 测试 |
| 文档 | `DocFlow` | 分析 → 编写 → 格式化 |

#### 方式三：自定义 Flow（高级编排）

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()

# 使用自定义 Flow
class MyPipeline(FlowEngine):
    @flow_start()
    def fetch_data(self): ...
    @flow_listen(fetch_data)
    def process(self): ...
    @flow_listen(process)
    @flow_route(lambda ctx: "fast" if ctx["size"] < 100 else "full")
    def fast_path(self): ...
    @flow_listen(process)
    def full_path(self): ...

result = dispatcher.dispatch_with_flow(MyPipeline, "数据处理")
```

#### 方式四：SubAgentManager（通信 + 发现 + 注册）

```python
from tea_agent.multi_agent import SubAgentManager

mgr = SubAgentManager()

# 创建并注册子 Agent（自动注册到 MessageBus + ToolRegistry）
analyst = mgr.create_analyst_agent(goal="审查代码架构")
coder = mgr.create_coder_agent(goal="实现功能模块")

# 调用子 Agent（Agent-as-Tool）
result = mgr.call_agent(analyst.agent_id, "审查 dispatcher.py")

# 跨 Agent 发布消息
mgr.publish(analyst.agent_id, "task:complete", {"status": "done"})

# 查看所有活跃 Agent
agents = mgr.list_agents()
```

---

### 🧩 核心组件详解

#### 1. FlowEngine — 事件驱动流程引擎

借鉴 CrewAI Flows + LangGraph StateGraph 设计：

```
@flow_start()          → 起始步骤（无依赖）
@flow_listen(step_a)   → 监听步骤（step_a 完成后自动触发）
@flow_route(cond_fn)   → 条件路由（根据状态选择分支）
```

**特性：**
- 📊 Mermaid 可视化：`flow.visualize()` 生成流程图
- 🔄 循环检测 + 分支执行
- 📦 跨步骤状态共享（`FlowState`）
- ⏱️ 步骤级超时 + 错误隔离

#### 2. RoleAgent — 角色化 Agent

每个 Agent 有明确的**身份、目标、背景故事**：

```python
RoleAgent(
    role="高级工程师",       # 身份标签
    goal="实现功能需求",      # 执行目标
    backstory="...",         # 背景故事（影响行为风格）
)
```

**内置角色：**
- `create_analyst()` — 分析专家
- `create_coder()` — 高级工程师
- `create_tester()` — 测试工程师
- `create_reviewer()` — 代码审查员

**特性：**
- 🎯 工具白名单 — 限定子 Agent 能调用的工具
- 📐 结构化输出 — 支持 Pydantic 模型（`AnalysisReport` / `CodeChangePlan` / `TestPlan` / `CodeReview`）
- 🧵 基于 `LiteSession` 的真实 LLM 调用

#### 3. MessageBus — 跨 Agent 发布/订阅

```python
from tea_agent.multi_agent import MessageBus, MessagePriority

bus = MessageBus()
bus.subscribe("agent-A", "task:update")
bus.subscribe("agent-B", "task:update")

# 发布（自动广播给所有订阅者）
bus.publish("task:update", {"progress": 50}, priority=MessagePriority.HIGH)

# 消费
messages = bus.consume("agent-A")
```

| 特性 | 说明 |
|------|------|
| **Topic 发布/订阅** | 一对多广播（区别于 toolkit_subagent_msg 的点对点） |
| **优先级队列** | LOW / NORMAL / HIGH / CRITICAL |
| **消息持久化** | 可选 SQLite 存储 |
| **线程安全** | 内置锁，支持并发读写 |

#### 4. Agent-as-Tool — Agent 即工具

**核心模式**：任意 RoleAgent 可注册为「工具」，被其他 Agent 像调用普通工具一样调用。

```python
from tea_agent.multi_agent import AgentTool, AgentToolManager

# 包装 Agent 为工具
tool = AgentTool(analyst, name="code_analyst",
                 description="分析代码架构质量问题")

# 调用（像调用 toolkit_xxx 一样）
result = tool.call(task="审查 dispatcher.py 的设计")

# 批量管理
mgr = AgentToolManager()
mgr.register(tool)
mgr.list_tools()
```

**优势：**
- 🔌 调用方无需知道被调用 Agent 的内部实现
- 🛡️ 并发控制（`max_concurrent` + 超时）
- 📊 调用统计（成功/失败/耗时）

#### 5. ExecutionPool — 高性能并行执行引擎

```
ExecutionPool (统一入口)
    ├── ThreadPoolChannel  ── 同步/IO/CPU 密集型任务
    ├── AsyncChannel       ── async/await 协程任务
    ├── PriorityQueue      ── 优先级调度
    └── Monitor            ── 健康监控 + 统计
```

**特性：**
- ⚡ 双通道并发（线程池 + 异步）
- ⚖️ 智能负载均衡（轮询 / 最少连接 / 加权）
- 🛡️ 资源隔离（CPU/内存/并发上限）
- 🔌 熔断器 + 自动重试 + 容错
- 📊 任务元数据追踪

```python
from tea_agent.multi_agent import ExecutionPool

pool = ExecutionPool(max_workers=8)
future = pool.submit(func, arg1, arg2=value)
result = future.result(timeout=30)

# 批量 + 超时
results = pool.map(func, items, timeout=30)

# 查看状态
print(pool.status())
# → {"running": 2, "queued": 5, "completed": 100, ...}
```

#### 6. WorkflowDAG — 高级工作流编排

DAG 定义引擎，支持 6 种节点类型：

| 节点类型 | 说明 |
|---------|------|
| `TASK` | 普通任务 |
| `CONDITION` | 条件分支（if/elif/else） |
| `LOOP` | 循环（for-each / while） |
| `PARALLEL` | 并行扇出（fan-out → fan-in） |
| `WAIT` | 等待（定时 / 条件满足后继续） |
| `END` | 终止节点 |

```python
from tea_agent.multi_agent import WorkflowDAG, WorkflowExec, WorkflowNode, NodeType

dag = WorkflowDAG()
dag.add_node(WorkflowNode("start", NodeType.TASK, fn=lambda ctx: {"data": 42}))
dag.add_node(WorkflowNode("check", NodeType.CONDITION, fn=lambda ctx: ctx["data"] > 10))
dag.add_node(WorkflowNode("process", NodeType.TASK, fn=lambda ctx: {"result": ctx["data"] * 2}))
dag.add_edge("start", "check")
dag.add_edge("check", "process", condition_key="true")

wf = WorkflowExec(dag)
result = wf.run({"start": {}})
```

#### 7. PatternMarket — 模式市场

可复用的 Agent 配置模板仓库（CRUD + 搜索 + 推荐 + 实例化）：

```python
from tea_agent.multi_agent import get_pattern_market

market = get_pattern_market()

# 搜索模式
patterns = market.search("代码审查")

# 从模式创建 Agent
agent = market.instantiate("高级工程师")

# 自定义模式
market.register({
    "name": "性能优化专家",
    "role": "性能优化工程师",
    "goal": "分析和优化代码性能",
    "backstory": "你精通各类性能分析和优化技术。",
    "tools": ["toolkit_exec", "toolkit_lsp", "toolkit_explr"],
    "tags": ["performance", "optimization"],
})
```

**内置模式（4 个预制）：** 代码审查专家 / 高级工程师 / 测试工程师 / 分析专家

#### 8. CheckpointManager + TraceEngine

| 组件 | 用途 |
|------|------|
| `CheckpointManager` | 执行状态持久化与崩溃恢复，故障时从检查点恢复 |
| `TraceEngine` | Span-based 执行轨迹追踪，可视化 Agent 调用链 |

---

### ⚔️ Multi-Agent 辩论赛 Demo

`demo/multi_agent/` — 双 AI Agent 对抗辩论，50 轮实时交替。

**快速启动：**
```bash
python demo/multi_agent/server.py --port 8083
# 浏览器打开 http://127.0.0.1:8083
```

**功能特性：**
- 🔵🔴 左右分屏：甲乙双方各持不同配置文件、不同模型
- ✍️ 甲方先开篇立论 → 乙方反驳 → 甲方回击 → ... 共 50 轮
- 📡 SSE 实时流式推送每轮发言
- 📊 进度条 + 打字动画 + 双方面板独立滚动
- 🛑 支持中途停止
- ⚙️ 双方独立选择配置文件（下拉列表自动发现 `~/.tea_agent/*.yaml`）

```
┌────────────────────┬────────────────────┐
│    🔵 甲方          │    🔴 乙方          │
│  config_prod.yaml   │  config_local.yaml │
│    GPT-4o           │    Qwen 2.5        │
├────────────────────┼────────────────────┤
│ 第1轮: 开篇立论      │                    │
│        ↓            │ 第2轮: 反驳         │
│ 第3轮: 回击          │        ↓           │
│        ↓            │ 第4轮: 再次反驳     │
│       ...50轮       │       ...50轮      │
└────────────────────┴────────────────────┘
```

> 技术实现：复用 `server.py` 中的 `_create_session_from_cfg()` + `_load_config_cached()`，每个辩论方拥有独立的 `OnlineToolSession`，完全隔离。

---

### ✅ 优势

- 🚀 **速度快** — 大任务分解为多个子任务并行执行，充分利用并发
- 🎯 **专注力高** — 每个子 Agent 只关注自己的角色领域，不受无关信息干扰
- 🧩 **可组合** — Agent 即工具（Agent-as-Tool），像搭积木一样组合能力
- 🔄 **流程可控** — FlowEngine 事件驱动 + WorkflowDAG 静态编排，灵活选择
- 📢 **可通信** — MessageBus 发布/订阅 + 点对点消息，Agent 间自由协作
- 🛡️ **容错强** — 熔断器 + 自动重试 + Checkpoint 恢复 + 错误隔离
- 📊 **可观测** — TraceEngine 追踪每次 Agent 调用链，便于调试
- ♻️ **可复用** — PatternMarket 存储模式模板，一键实例化
- 🔌 **零代码可触发** — 对话中直接使用 `toolkit_parallel_subtasks` / `toolkit_subagent`

### ⚠️ 限制

- 💰 **Token 成本高** — 每个子 Agent 独立调用 LLM，总 token 消耗 = 子任务数 × 每任务消耗
- 🐌 **协调开销** — 子任务间依赖需要序列化等待（Flow / DAG），非全部可并行
- 🔍 **调试困难** — 分布式 Agent 行为不如单 Agent 可预测，追责较复杂
- 🧠 **上下文隔离** — 子 Agent 间默认不共享记忆，需要显式透传上下文
- 💥 **修改冲突** — 多个子 Agent 并发修改同一文件可能导致冲突（可通过 Flow 串行化避免）
- ⚙️ **依赖 LLM 质量** — 子 Agent 的任务理解能力取决于底层模型，小模型可能误解任务

---

## 🏗️ 项目结构

```
tea_agent/
├── gui.py                 # GUI 桌面入口（Tkinter）
├── server/                # REST API + Web V2 界面（Starlette + SSE）
│   ├── server.py          # Starlette 路由 + SSE
│   ├── route_handlers.py  # API 路由处理
│   ├── static/            # HTML/CSS/JS 单页应用
│   └── __main__.py        # python -m tea_agent.server
├── protocol/              # ACP Protocol Server
│   ├── acp_server.py      # ACP 协议实现
│   └── __main__.py        # python -m tea_agent.protocol
├── memory.py              # 长期记忆
├── prompt_manager.py      # 提示词版本管理
├── toolkit/               # 75+ 工具模块
├── session/               # 会话管理（历史压缩/Token 裁剪）
├── multi_agent/           # 多 Agent 系统（6阶段：角色/流程/通信/并行/编排/市场）
├── lsp/                   # 代码智能（Jedi + Tree-sitter）
├── store/                 # 数据存储（12 子模块）
├── evaluation/            # 任务评估
├── skills/                # 技能结晶（17+ 个 .md 技能）
├── _gui/                  # GUI 组件（12 模块）
├── tests/                 # 29 个测试文件（546+ 用例）
└── demo/                  # 演示：蛇/俄罗斯方块/沪深300
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

- **0** = 不限制，发送全部历史
- **64000**（默认）= 适合 64K~128K 窗口的主流模型
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

### 🎯 Ruff 代码规范（v0.10.11+）

`pyproject.toml` 内置 Ruff 配置，确保代码风格统一：

```toml
[tool.ruff]
line-length = 150
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]
```

| 规则集 | 说明 |
|--------|------|
| `E` / `W` | pycodestyle 错误/警告 |
| `F` | pyflakes 逻辑错误 |
| `I` | isort 导入排序 |
| `N` | pep8-naming 命名规范 |
| `UP` | pyupgrade Python 3.10+ 语法升级 |
| `B` | flake8-bugbear 常见 bug 检测 |
| `C4` | 化简代码 |
| `SIM` | 简化表达式 |

所有源码已通过 Ruff 检查，采用 Python 3.10 现代类型注解（`str | None` 替代 `Optional[str]`）。

---

## 📄 许可证

MIT License © 2024-2026 sunkw

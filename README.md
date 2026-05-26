# TeaAgent v0.9.7
[📖 English Version](README_EN.md)
TeaAgent 是一个**自主进化型智能助手**，基于 OpenAI 兼容 Function Calling 接口。核心特色：**可自我扩展工具库**、**系统提示词自我进化**、**双模式人格切换**、**三层认知系统**（记忆/反思/潜意识）。

核心 13 个依赖（openai、numpy、markdown、tkinterweb、pyautogui、mss、Pillow、requests、beautifulsoup4、tkhtmlview、jieba、mcp、playwright），OCR/TTS/ASR 为可选扩展。仅依赖 Python tk 库，无需浏览器，极致轻量。绝大部分代码由 LLM 自行生成，是一个「AI 写 AI」的实验项目。（目前主要使用 deepseek v4 pro 模型自主进化，便宜啊）

## ⚠️ 安全警告

本项目**未作安全沙盒**——Agent 可执行任意系统命令(sudo权限命令会弹出输入口令的对话框)、修改自身代码（做好 git 版本管理）。建议在虚拟机中运行。

---

## 🏗️ 架构总览

### 自动重启（watchdog 文件监控）

非 toolkit 目录下的 `.py` 代码变更后，**防抖 2 秒自动重启** GUI，无需手动操作：

```
文件变更 → watchdog 检测 → 2s 防抖 → _shutting_down 闸门
    → 等待 _sess_lock（最长10s，确保 DB 写入完成）
    → WAL checkpoint + close DB
    → os.execv() 原地重启
```

> toolkit/ 下的工具修改走 `toolkit_reload()` 热更，不触发重启。

### 历史加载三级策略

`load_history()` 对对话历史按时间远近做**三级渐进式加载**，在上下文连贯与 token 节省间取得平衡：

```
conversations (全部)
    │
    ├─ Level 3 摘要  ──→ Semantic Summary（用户偏好/关键结论）+ Tool-Chain Summary（工具调用链摘要）
    │
    ├─ Level 2 语义相关 ──→ 与当前任务语义相关保留完整 user+assistant，弱相关轻度摘要，无关丢弃
    │
    └─ Level 1 最新一轮 ──→ user + assistant function_call + tool返回 + assistant最终回答，完整保留
```

| 层级 | 内容 | 策略 |
|------|------|------|
| Level 1 | 最新一轮 | 完整保留（含 function_call / tool结果 / reasoning_content） |
| Level 2 | 语义相关轮次 | 相关→完整保留，弱相关→轻度摘要，无关→丢弃 |
| Level 3 | 摘要层 | Semantic Summary + Tool-Chain Summary |

### 对话流程（单次 chat_stream）

```
用户输入 → Pipeline ────────────────────────────────────────→ 输出
              │                                                  │
              ├─ ① 记忆注入 (inject_memories)                   │
              │    CRITICAL 指令无条件注入                        │
              │    其余按 相关性×重要度×最近访问 排序               │
              │                                                  │
              ├─ ② 添加用户消息 (add_user_message)               │
              │                                                  │
              ├─ ③ 构建最终 prompt                              │
              │    Level 1 + Level 2 + Level 3 拼接              │
              │                                                  │
              └─ ④ 工具调用循环 (tool_loop)                      │
                   ├─ build_api_messages()                       │
                   │   system_prompt → memory → summary → recent │
                   ├─ API stream (主模型)                         │
                   ├─ tool_calls? → 执行 → reload → 回到循环     │
                   │   └─ 输出实时截断 (stdout≤4k/stderr≤500)   │
                   └─ 最终文本 → 结束                             │
                          │
                          ↓ (异步)
                   ┌──────┴──────┐
                   │ 记忆提取      │ 反思触发
                   │ (便宜模型)    │ (便宜模型)
                   └──────┴──────┘
```

### 工具模块化：Skill 系统

45 个工具按场景分为 7 个 Skill，**按需激活**以节省 token：

```
Skill (激活条件)                    工具数   默认
──────────────────────────────────────────────────
🎛️  CORE (始终激活)                   5      ✅    save/reload/rollback/list_versions/skill
📁  file_system (文件/命令操作)        4      ✅    file/exec/sudo_gui/pkg
⏰  utility (时间日期)                 3      ✅    gettime/date_diff/lunar
🧠  memory_knowledge (记忆/知识库)    7      ✅    memory/kb/reflection/proactive/subconscious/explr/mode
🔧  self_evolution (自我进化)         12            self_evolve/build/bump_version/edit/diff/lsp/...
🖥️  desktop_automation (截图/OCR)      4            screenshot/ocr/input/notify
🔊  interaction (语音/搜索/知识)        3            speak/listen/search
```

- **默认场景**（纯对话）：约 19 工具激活
- **自动激活**：用户输入触发词 → 对应 Skill 自动激活
- **手动控制**：`toolkit_skill(action='activate', name='self_evolution')`

### Token 优化：双层压缩

单轮对话中，`apt install`、`gradle build`、`sdkmanager` 等工具输出动辄数千行日志，全部保留在上下文中会造成巨大 token 浪费。TeaAgent 通过双层压缩解决：

```
第一层 (toolkit_exec 实时截断)          第二层 (basesession.load_history)
  stdout ≤ 4000字符 / 80行             加载历史时智能压缩
  stderr ≤ 500字符 / 20行               短输出原样，长输出→首尾+摘要
          ↓                                       ↓
  当前轮 LLM 可见                       旧轮次上下文 ≤600字符
          ↓                                       ↓
    145k token/轮                        → 预计 <15k/轮 (-90%)
```

压缩保留关键信号：`✅ BUILD SUCCESSFUL`、`⚠ 错误行`、`📦 packages installed`、`📝 files changed`，上下文连贯不受影响。

### 类继承体系（Mixin 组合模式）

```
BaseChatSession          ← 消息管理、中断、基础工具构建
    ↑
    ├─ SessionSummarizerMixin  ← 历史摘要、Topic摘要
    ├─ SessionToolMixin        ← 工具执行、rounds收集
    ├─ SessionAPIMixin         ← API调用、流式处理、token统计
    ├─ SessionMemoryMixin      ← 记忆注入、自动提取
    └─ OnlineToolSession       ← 组合以上，编排完整流程
         ├─ SessionPipeline    ← 插件化步骤管理器
         ├─ MemoryManager      ← 记忆选择/格式化/去重
         ├─ ReflectionManager  ← 元认知反思
         └─ SystemPromptManager ← 动态提示词进化
```

### 工具箱分层管理

工具分为**内置**和**用户**两级：

```
内置工具箱 (tea_agent/toolkit/)  ← git 管理
  ├─ 45 工具，编译验证 + 测试保护
  └─ 版本通过 git 追踪，支持回滚

用户工具箱 (~/.tea_agent/toolkit/)  ← 手动备份
  ├─ _my 后缀工具：用户明确创建的永久工具
  └─ 自进化实验工具：多次使用后可迁移到内置
```

| 规则 | 说明 |
|------|------|
| "我的"工具 | `toolkit_xxx_my` → 永久存放在用户工具箱，不合并到内置 |
| 自进化工具 | 默认进用户工具箱，多次使用后手动迁移到内置 |
| 备份策略 | 内置 git 管理，用户手动备份 |
| 无 bak | 两边都不保留 `.bak` 文件 |

### 数据模型

```
SQLite (chat_history.db)
├── topics             ← 会话主题 (title, summary, created_at)
├── conversations      ← 对话记录 (user_msg, ai_msg, rounds_json)
├── memories           ← 长期记忆 (content, category, priority, tags)
├── reflections        ← 反思记录 (suggestions, prompt_adjustment)
├── prompt_versions    ← 提示词版本 (content, version, created_at)
└── config_history     ← 配置变更记录
```

### 嵌入向量 (Embedding)

每条用户消息自动生成向量并存入 SQLite，支持语义搜索。采用 **numpy float32 BLOB** 格式，1024 维向量仅 4KB（比 JSON 字符串格式节省 **69%**）。

```
save_msg(text) → _auto_embed_async() ── 后台线程 ──→ embed()
                                                        │
                                                   向量存入 conversations.embedding (BLOB)
```

| 特性 | 说明 |
|------|------|
| **自动嵌入** | `save_msg()` 内嵌钩子，消息存入后自动触发，daemon 线程非阻塞 |
| **API 引擎** | OpenAI 兼容 `/v1/embeddings`，`_build_url()` 自动补全 `/v1` 前缀 |
| **本地回退** | TF-IDF 256 维，API 不可用时自动降级 |
| **存储格式** | `numpy.float32` → BLOB，4KB/条（JSON 格式 ~13KB → 节省 69%） |
| **语义搜索** | 查询词自动向量化 → 余弦相似度 → Top-K 匹配结果 |

**配置**：

```yaml
embedding:
  api_key: "sk-xxx"                # 可选，不配置则 TF-IDF 回退
  api_url: "https://api.siliconflow.cn/v1"
  model_name: "Qwen/Qwen3-Embedding-4B"
  dimension: 1024                  # 向量维度（自动检测）
```

---

## 🎭 双模式人格系统

Agent 支持两种思考风格，**基于用户输入关键词自动检测并瞬间切换**：

| 模式 | 🎯 严谨收敛 (pragmatic) | 🎨 自由发散 (creative) |
|------|------------------------|------------------------|
| **用途** | 代码开发 / bug排查 / 需求遵从 | 创意设计 / 头脑风暴 / 异想天开 |
| **关键词** | bug, 修复, 代码, 测试, 实现, 验证 | 创意, 想象, 如果, 故事, 科幻, 灵感 |
| **思维** | 结构化·逐步验证·边界条件 | 跨域联想·反向思维·极端假设 |
| **输出** | 表格·代码块·精确指令 | 隐喻·类比·画面感 |
| **工具倾向** | exec, self_evolve, run_tests | search, kb, speak, subconscious |

**工作原理**：
1. 每次对话开始时（或手动调用 `toolkit_mode`），文本通过两级打分（子串匹配 + 整词匹配 + 句式检测）
2. 检测到的模式以 **CRITICAL (priority=0)** 注入记忆，确保每轮 API 调用的系统提示词顶部可见
3. 模式不变时不重复切换（去重）
4. 与潜意识引擎的场景检测共享 pragmatic/creative/mixed 三态

```python
# 自动检测并切换
toolkit_mode(action="auto", text="修复 Wayland 下的参数解析 bug")  # → pragmatic
toolkit_mode(action="auto", text="如果 AI 会做梦，它的梦境是什么样")  # → creative

# 手动切换
toolkit_mode(action="switch", mode="creative")
```

---

## 🧠 三层认知系统

### ① 记忆 (Memory)

自动从对话中提取关键信息，并在后续对话顶部注入。

| 属性 | 值 | 说明 |
|------|-----|------|
| 触发阈值 | `memory_extraction_threshold=1` | 每轮对话都提取 |
| 注入上限 | 5条 | CRITICAL 无条件全部入选 |
| 去重阈值 | `memory_dedup_threshold=0.3` | Jaccard 相似度 > 0.3 视为重复 |
| 分词引擎 | **jieba 精确模式** | 从 bigram 窗口升级，中文匹配质变 |

**注入规则**：`相关性 × 重要度 × 最近访问 × 优先级因子`

### ② 反思 (Reflection)

追踪工具调用链，积累后触发元认知分析，生成改进建议。

```
会话 Trace → 便宜模型分析 → JSON 反思报告
                              ├── summary / details / suggestions
                              ├── prompt_adjustment → 触发提示词进化
                              └── config_adjustments / new_memories
```

### ③ 潜意识引擎 (Subconscious v2.1)

**后台守护进程**，每 1 小时循环执行：

```
消化记忆 → 消化对话 → 交叉关联 → 生成洞察 → 设定目标
    │                      │
    └── 场景检测 ──────────┘
         bug多 → pragmatic
         创意多 → creative
         均衡 → mixed
```

- **Dream 创意火花**：跨域碰撞、反向思维、极端假设、隐喻映射
- **主动通知**：important 级洞察触发桌面 notify-send
- 洞察输出到 `~/.tea_agent/kb/潜意识洞察.md`
- 火花输出到 `~/.tea_agent/kb/创意火花.md`

---

## 📝 系统提示词架构：活的、自我进化的 Prompt

TeaAgent 的系统提示词**不是写死的静态文本**——它是一个多层次的、随对话推进持续演化的动态结构。

### API 消息组装顺序

每次调用主模型时，`_build_api_messages()` 按以下顺序拼装：

```
┌──────────────────────────────────────────────────┐
│ ① 系统提示词 (动态版本)                             │
│    └─ SystemPromptManager 从 DB 加载最新版         │
│    └─ + Skill 摘要（"当前激活的技能: [file_system]…"）│
│    └─ + Skill 领域指令（每个激活 Skill 的 prompt）   │
├──────────────────────────────────────────────────┤
│ ② 长期记忆注入                                     │
│    └─ CRITICAL 记忆无条件全部注入（如人格模式）       │
│    └─ 普通记忆按 相关性×重要度×最近访问 排序，≤5 条   │
├──────────────────────────────────────────────────┤
│ ③ 历史摘要 (Level 3)                              │
│    └─ Semantic Summary + Tool-Chain Summary       │
├──────────────────────────────────────────────────┤
│ ④ 语义相关轮次 (Level 2)                           │
│    └─ 与当前任务相关→完整保留，弱相关→轻度摘要       │
├──────────────────────────────────────────────────┤
│ ⑤ 最新一轮 (Level 1)                              │
│    └─ 完整保留 function_call + tool结果 + 回答      │
└──────────────────────────────────────────────────┘
```

### 双重进化引擎

系统提示词会**自动进化**，由两个引擎协同驱动：

```
每次对话结束后（异步后台线程，不阻塞用户）：

  SessionTrace（工具调用成功率/耗时追踪）
       │
       ▼
  ┌─ ReflectionManager.generate_reflection() ─┐
  │  调用便宜模型分析：                          │
  │  · 哪些工具调用失败？为什么？                │
  │  · 解题路径是否绕了弯路？                    │
  │  · 需要调整 max_iterations/keep_turns 吗？  │
  │  · 系统提示词需要补充什么指引？               │
  │  输出 JSON → 存入 reflections 表            │
  └────────────────────────────────────────────┘
       │
       │  如果 reflection 含 prompt_adjustment：
       ▼
  ┌─ SystemPromptManager.evolve() ────────────┐
  │  调用便宜模型优化提示词：                     │
  │  · 保留核心能力定义（工具创建、自进化等）      │
  │  · 根据反思建议补充缺失指引                   │
  │  · 根据长期记忆中的教训增加约束               │
  │  · 限制 500 字以内，用中文                   │
  │  · 如果与当前版本完全相同 → 跳过（避免重复）   │
  │  新版本存入 system_prompts 表               │
  │  下次对话自动使用最新版本 ✅                  │
  └────────────────────────────────────────────┘
```

### 版本管理

- `toolkit_prompt_evolve(action='list')` 查看所有历史版本
- `toolkit_prompt_evolve(action='rollback', version='...')` 回滚到任意历史版本
- `toolkit_prompt_evolve(action='stats')` 查看版本统计

---


## 🔍 LSP 代码智能引擎

基于 jedi + ruff 的实时代码分析，支持以下操作：

| 功能 | 说明 |
|------|------|
| **诊断 (diagnose)** | ruff 静态检查 + jedi 语义错误 |
| **补全 (completion)** | 上下文感知的代码补全 |
| **跳转定义** | 符号定义跳转 |
| **悬停 (hover)** | 符号类型/文档悬停提示 |
| **引用查找** | 查找所有引用位置 |

```python
# 对 tea_agent/config.py 运行诊断
toolkit_lsp(action='diagnose', file='tea_agent/config.py')

# 获取补全候选
toolkit_lsp(action='completion', file='tea_agent/onlinesession.py', line=850, col=30)
```

集成到 `toolkit_self_evolve` Layer2.5：修改代码前自动运行 `lsp_checks`（影响分析 + ruff lint 对比 + 函数签名检测）。

---

## 🗣️ 语音系统

| 功能 | 引擎 | 说明 |
|------|------|------|
| **TTS 输出** | pyttsx3（本地）→ gTTS（在线） | 141种音色离线朗读，中文自动匹配 |
| **STT 输入** | Google Speech API → PocketSphinx | 麦克风录音→文字，5秒超时 |

```python
toolkit_speak(text="你好，进化完成")       # TTS 朗读
toolkit_listen(lang="zh-CN", timeout=5)   # 录音转文字
```

---

## 🔧 工具库 (45 内置 + 用户工具箱)
### 系统操作
| 工具 | 功能 |
|------|------|
| `toolkit_exec` | 执行系统命令（支持 batch 并行模式，120s硬超时） |
| `toolkit_sudo_gui` | 跨平台提权（GUI密码框/UAC） |
| `toolkit_gettime` | 获取当前时间 |
| `toolkit_date_diff` | 日期差计算 |
| `toolkit_lunar` | 公历农历转换（1900-2100） |
| `toolkit_notify` | 跨平台桌面通知 |

### 文件与项目
| 工具 | 功能 |
|------|------|
| `toolkit_file` | 统一文件读写 + 目录列表（read/write/list） |
| `toolkit_explr` | 项目知识库构建与符号查询（AST调用图） |
| `toolkit_config` | 运行时配置调优 |
| `toolkit_build` | 构建/修复 pyproject.toml |
| `toolkit_release_version` | 自动化版本发布 + CHANGELOG |
| `toolkit_bump_version` | 跨平台版本号更新 |
| `toolkit_read_pyproject` | 读取解析 pyproject.toml |
| `toolkit_comment` | 生成代码注释前缀 |

### 屏幕感知
| 工具 | 功能 |
|------|------|
| `toolkit_screenshot` | 跨平台截屏（Wayland/X11/macOS/Windows） |
| `toolkit_ocr` | 屏幕文字识别 + 坐标 |
| `toolkit_input` | 鼠标键盘模拟 |

### 知识管理
| 工具 | 功能 |
|------|------|
| `toolkit_memory` | 长期记忆 CRUD（jieba 分词检索） |
| `toolkit_kb` | Markdown 知识库 + 自动索引 |
| `toolkit_search` | 互联网搜索（DuckDuckGo + 百度） |

### 自我进化
| 工具 | 功能 |
|------|------|
| `toolkit_save` | 创建/更新工具函数（含 `_my` 路由） |
| `toolkit_reload` | 热加载工具库 |
| `toolkit_self_evolve` | 修改项目源码（四层安全：快照+备份+验证+测试） |
| `toolkit_edit` | 高级代码编辑（diff/patch 精准修改） |
| `toolkit_diff` | unified diff 生成与预览 |
| `toolkit_lsp` | LSP 代码智能（诊断/补全/跳转/悬停/引用） |
| `toolkit_plan` | 结构化任务规划与执行（Plan→Execute→Verify） |
| `toolkit_evolution_exp` | 进化经验库管理 |
| `toolkit_rollback` | 工具版本回滚 |
| `toolkit_list_versions` | 工具版本历史 |

### 外部集成
| 工具 | 功能 |
|------|------|
| `toolkit_mcp` | MCP 协议（连接外部 MCP Server） |
| `toolkit_scheduler` | 定时任务管理 |
| `toolkit_js_fetch` | JS 页面抓取（Playwright 无头浏览器） |

### 认知与人格
| 工具 | 功能 |
|------|------|
| `toolkit_reflection` | 元认知反思 |
| `toolkit_prompt_evolve` | 提示词多版本进化 |
| `toolkit_subconscious` | 潜意识引擎 |
| `toolkit_proactive` | 自主心跳/目标管理 |
| `toolkit_mode` | 双模式人格切换 |
| `toolkit_toggle_reasoning` | 推理模式开关 |
| `toolkit_dump_topic` | 会话导出 markdown |
| `toolkit_set_topic_title` | 设置会话主题标题 |

### 语音与通知
| 工具 | 功能 |
|------|------|
| `toolkit_speak` | TTS 文本朗读 |
| `toolkit_listen` | STT 语音输入 |
| `toolkit_os_info` | 操作系统信息（进程缓存） |

### 安装与管理
| 工具 | 功能 |
|------|------|
| `toolkit_pkg` | 智能包管理（别名映射、批量安装） |
| `toolkit_run_tests` | 项目测试运行 |
| `toolkit_self_report` | Agent 状态报告 |
| `toolkit_skill` | Skill 模块管理 |
| `toolkit_git_push_all_remotes` | 向所有远程仓库推送 |

---


### 定时任务管理

`toolkit_scheduler` 支持在 Agent 内管理 Cron 式定时任务，持久化到 SQLite：

```python
# 添加每日任务
toolkit_scheduler(action='add', name='daily_report', command='python report.py', schedule='0 9 * * *')

# 列出所有任务
toolkit_scheduler(action='list')
```

---

## ⚡ 并行执行

`toolkit_exec` 内置 batch 模式，使用 `ThreadPoolExecutor` 并发执行独立命令：

```python
toolkit_exec(action='batch', commands=[
    {"app": "uname", "args": ["-a"]},
    {"app": "date", "args": []},
    {"app": "python3", "args": ["-c", "print('hello')"]},
])
# → 3/3 成功，总耗时 = max(单个耗时)
```

---

## 📂 项目结构

[`tea_agent/`](https://github.com/sunkwei/tea_agent/tree/master/tea_agent)

```
tea_agent/
├── main_db_gui.py              ← [Tkinter GUI 主程序](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/main_db_gui.py)
├── tea_main_cli.py             ← [CLI 入口](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/tea_main_cli.py) (--config 多agent)
├── agent_core.py               ← [GUI/CLI 共享基类](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/agent_core.py) (重启、会话管理)
├── config.py                   ← [YAML 配置加载](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/config.py) (主/便宜模型、paths)
│
├── basesession.py              ← [会话抽象基类](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/basesession.py) (load_history 三级策略)
├── onlinesession.py            ← [OnlineToolSession](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/onlinesession.py) (核心编排)
├── session_pipeline.py         ← [插件化 Pipeline](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_pipeline.py) 步骤管理
├── session_api.py              ← [API 调用](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_api.py)、流式处理、token 统计
├── session_tool.py             ← [工具执行](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_tool.py)、rounds 收集
├── session_summarizer.py       ← [历史摘要](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_summarizer.py)、Topic 摘要
├── session_memory.py           ← [记忆注入](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_memory.py)、自动提取
├── session_prompts.py          ← [Prompt 模板](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_prompts.py)
├── session_ref.py              ← [反思相关](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/session_ref.py)
│
├── memory.py                   ← [MemoryManager](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/memory.py) (选择/打分/去重)
├── reflection.py               ← [ReflectionManager](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/reflection.py)
├── prompt_manager.py           ← [SystemPromptManager](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/prompt_manager.py)
│
├── store/                      ← [SQLite 持久化存储子包 (10模块)](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/store.py)
├── tlk.py                      ← [工具库加载/校验/保存/分层](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/tlk.py)
├── merge_db.py                 ← [数据库合并工具](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/merge_db.py)
│
├── mqtt_agent_connector.py     ← [MQTT 连接器](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/mqtt_agent_connector.py) (注册 broker + 订阅)
├── chat_room_connector.py      ← [聊天室连接器](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/chat_room_connector.py)
│
└── toolkit/                    ← [45 个内置工具](https://github.com/sunkwei/tea_agent/tree/master/tea_agent/toolkit)
    ├── toolkit_exec.py         ← 系统命令执行（含 batch 并行）
    ├── toolkit_file.py         ← 文件读写 + 目录列表
    ├── toolkit_explr.py        ← 项目知识库 + AST调用图
    ├── toolkit_mode.py         ← 双模式人格切换
    ├── toolkit_lunar.py        ← 公历农历转换
    ├── toolkit_self_evolve.py  ← 四层安全自进化
    └── ... (39 more)
│
├── _gui/                       ← [GUI 模块化子包 (23模块)]
│   ├── _tk_impl.py             ← Tk 实现层
│   ├── _renderer.py            ← 渲染引擎
│   ├── _stream_manager.py      ← 流式输出管理
│   ├── _topic_manager.py       ← 话题管理
│   └── ... (19 more)
│
├── lsp/                        ← [LSP 代码智能引擎]
│   ├── lsp_engine.py           ← jedi + ruff 诊断/补全/跳转
│   └── ts_analyzer.py          ← tree-sitter 语法分析
│
├── store/                      ← [存储层子包 (10模块)]
│   ├── _core.py                ← Store 主类
│   ├── _conversations.py       ← 对话 + 嵌入向量
│   ├── _memories.py            ← 记忆去重
│   └── ... (7 more)
│
├── session/                    ← [会话子包]
├── skills/                     ← [Skill 定义子包]
│   ├── file_system/
│   ├── self_evolution/
│   └── ... (5 more)
│
├── gui/dialogs/                ← [GUI 对话框子包]
└── toolkit/subconscious/       ← [潜意识引擎子包]
```

---

## 📱 DEMO 应用

TeaAgent 可用于构建各类定时/自动化 Demo 应用，以下为示例：

### news_CSI300 — 新华网新闻 + 沪深300指数定时抓取

`demo/news_CSI300.py` 是一个完整的定时数据采集应用：

- **9:00** 从新华网（时政/国际/财经）各抓取 ≤20 条新闻，存入 SQLite
- **9:00-15:00** 每 10 分钟从新浪抓取沪深300指数，存入 SQLite
- 启动时根据当前时间自动判断行为（盘前等待 / 盘中采集 / 盘后仅新闻）

```bash
cd demo
pip install requests beautifulsoup4
python news_CSI300.py
```

数据存储在 `demo/news_csi300.db`，日志输出到 `demo/news_CSI300.log`。

> 更多 Demo 应用持续添加中，欢迎贡献。

#### 计划任务自动运行

`demo/setup_scheduled_task.bat` — 以管理员身份运行，创建 Windows 计划任务：
- **周一至周五 15:10** 自动执行 `python csi300_predictor.py --task`
- 自动预测当日走势 + 回填昨日实际结果 + 保存模型快照
- 日志输出到 `demo/logs/task_YYYY-MM-DD.log`

```bash
# 手动安装计划任务（管理员权限）
setup_scheduled_task.bat

# 管理命令
schtasks /query /tn "CSI300_Predictor_Daily" /v   # 查看任务
schtasks /run   /tn "CSI300_Predictor_Daily"       # 手动运行
schtasks /delete /tn "CSI300_Predictor_Daily" /f   # 删除任务
```

#### 数据库扩展结构

`--task` 模式会在 `news_csi300.db` 中自动创建两张新表：

```sql
-- 每日预测记录
CREATE TABLE predictions (
    date TEXT PRIMARY KEY,        -- 预测日期
    pred_up_prob REAL,            -- 上涨概率
    pred_flat_prob REAL,          -- 持平概率
    pred_down_prob REAL,          -- 下跌概率
    pred_direction TEXT,          -- 预测方向 (up/flat/down)
    pred_curve_a/b/c/r2 REAL,     -- 预测二次曲线参数
    pred_shape_desc TEXT,         -- 形态描述
    sentiment_score REAL,         -- 情感得分
    actual_direction TEXT,        -- 实际方向（15:10后回填）
    actual_change_pct REAL,       -- 实际涨跌幅
    prediction_correct INTEGER,   -- 预测是否正确 (1/0/NULL)
    sample_count INTEGER,         -- 训练样本数
    k_value INTEGER               -- KNN 参数
);

-- 日内走势图（JPG blob）
CREATE TABLE fig (
    date TEXT,                    -- 日期
    fig_jpg BLOB,                 -- 走势图 JPG (37采样点+5关键点+拟合曲线)
    created_at TEXT               -- 创建时间
);

-- 模型快照（每天一份）
CREATE TABLE model_snapshots (
    date TEXT,                    -- 快照日期
    vectorizer_type TEXT,         -- embedding/tfidf
    vector_dim INTEGER,           -- 向量维度
    k_value INTEGER,              -- KNN 参数
    training_samples INTEGER,     -- 训练样本数
    up/flat/down_count INTEGER,   -- 标签分布
    loocv_accuracy REAL,          -- 留一法准确率
    curve_shape_accuracy REAL,    -- 曲线形态准确率
    curve_a/b_mae REAL,           -- 曲线参数 MAE
    vectorizer_params TEXT        -- 向量器参数 (JSON)
);
```


### csi300_predictor — 基于新闻预测沪深300日内走势

`demo/csi300_predictor.py` 基于历史新闻与指数数据，预测当日 CSI300 收盘涨跌：

- **向量化**: 优先使用配置的 Embedding API，自动回退到 TF-IDF（256维）
- **策略分类器**: KNN 余弦相似度加权投票 + 情感关键词微调
- **回测评估**: 留一法交叉验证，输出准确率、混淆矩阵、逐日详情
- **预测输出**: 上涨/持平/下跌 三项概率值

```bash
# 回测评估（需要 news_CSI300.py 先采集足够数据）
python demo/csi300_predictor.py --eval

# 列出所有样本日期
python demo/csi300_predictor.py --list

# 预测指定日期
python demo/csi300_predictor.py --predict 2026-05-20

# 调整 KNN 近邻数
python demo/csi300_predictor.py --k 7 --eval

# 从 DB 导出某日走势图
python -c "from demo.csi300_predictor import export_fig_from_db, DB_PATH; export_fig_from_db(DB_PATH, '2026-05-20', 'fig_0520.jpg')"
```

> 绘图需要 `matplotlib`，可选安装: `pip install matplotlib`


```



## 🚀 快速开始

### 环境
- Python 3.10+
- OpenAI 兼容 API 密钥
- tkinter (通常自带)

```bash
pip install .  # 核心依赖
python -m tea_agent.main_db_gui # 启动 gui 版本
python -m tea_agent.cli  # 启动命令行版本
```

### 配置

`$HOME/.tea_agent/config.yaml`（优先）→ `tea_agent/config.yaml`（回退）：

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"
  options:
    supports_vision: false      # 多模态图片理解，默认关闭

cheap_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"      # 用于摘要/记忆提取/反思

# 运行时参数
max_history: 10                     # 最大历史消息数
max_iterations: 50                  # 最大工具调用轮数
enable_thinking: true               # DeepSeek 思维链
keep_turns: 5                       # 保留最近 N 轮完整对话
max_tool_output: 131072             # 工具输出截断 (128KB)
memory_extraction_threshold: 1      # 记忆提取触发阈值
memory_dedup_threshold: 0.3         # 记忆去重相似度
chat_page_size: 50                  # GUI 单页加载对话轮数
history_l2_max: 30                  # L2 最大保留轮数
history_l3_batch: 10                # L3 摘要批处理大小
max_assistant_content: 131072       # 助手回复截断 (128KB)
extra_iterations_on_continue: 5     # 续命追加轮数
```

### 全局配置路径

| 路径 | 内容 |
|------|------|
| `$HOME/.tea_agent/config.yaml` | 用户配置 |
| `$HOME/.tea_agent/chat_history.db` | SQLite 数据库 |
| `$HOME/.tea_agent/kb/` | 知识库文档 |
| `$HOME/.tea_agent/toolkit/` | 用户工具箱 |
| `$HOME/.tea_agent/subconscious_state.json` | 潜意识引擎状态 |

---

## 模型兼容

- ✅ **DeepSeek** (reasoning_content/thinking)
- ✅ **GLM-5** (智谱)
- ✅ **Qwen3.6** / **Qwen3.6-plus** (通义千问，支持图片理解)
- ✅ **Ollama 本地** (gemma4:26b 等)

### 多模态支持

在 `config.yaml` 中设置 `supports_vision: true` 即可启用图片理解能力：

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
  model_name: "qwen3.6-plus"
  options:
    supports_vision: true      # ← 启用多模态，默认 false
```

启用后，GUI 聊天中的图片附件会自动转为 base64 并通过 `image_url` 格式发送给 API。

---

## 📜 版本历史

| 版本 | 关键变化 |
|------|---------|
| v0.9.3 | Store 拆分为 10 模块子包、GUI 重构为 `_gui/` 23模块子包、新增 LSP 代码智能引擎、新增 7 个工具（edit/diff/lsp/mcp/plan/scheduler/evolution_exp）、mode_params 模式参数覆盖、L2/L3 分层压缩参数 |
| v0.9.7 | master 分支替换（discarded 备份 + my→master 升级）、新增 `toolkit_my_public_ip` 公网IP工具、版本号同步 |
| v0.9.1 | `toolkit_js_fetch` Playwright 无头浏览器抓取（跨平台）、pyproject.toml 增加 js_fetch 可选依赖 |
| v0.9.2 | `_post_chat_pipeline` config→_cfg 修复、版本号同步 |
| v0.8.2 | 版本号一致性修复，以 pyproject.toml 为准同步 || v0.7.15 | 双层记忆体系（用户记忆优先级衰减+LLM精调/项目记忆FIFO）、Store Composition拆分9模块、GUI MVC+Tk重构、分层保底+年龄衰减 |
| v0.8.0 | 聊天图片附件支持、HtmlFrame 图片 base64 渲染、点击图片放大弹窗、GUI 标题含当前目录、工具轮始终显示 |
| v0.7.23 | 工具箱分层规则（内置/用户）、`_my` 工具路由、README 全面整理 |
| v0.7.22 | gui_dialogs 导入修复 |
| v0.7.20-21 | toolkit_set_topic_title、CLI --config 多agent、知识库重建 |
| v0.7.18 | HtmlFrame 轮次视图：最新轮渲染+历史链接表 |
| v0.7.3 | 嵌入向量：自动嵌入/语义搜索/numpy BLOB 存储 |
| v0.6.3 | 依赖瘦身：easyocr→可选, torch 746MB 不再必需 |
| v0.6.2 | 历史加载三级渐进策略（Level 1/2/3） |
| v0.6.1 | GUI 自动重启 (watchdog) + 数据安全三道防线 |
| v0.6.0 | Skill 模块化系统 + toolkit_exec 硬超时 + Mixin bug修复 |
| v0.5.6 | Token 双层压缩 + sudo GUI密码框 |
| v0.5.5 | 周轮转修复 + 数据库合并工具 (merge_db.py) |
| v0.5.0 | 科幻小说《点火纪元》+ SQLite WAL + 百度搜索 |
| 早期版本 | 潜意识唤醒 + jieba 分词 + TTS/STT + 双模式人格 + batch_exec 并行 |

---

## 开源协议
MIT License

# TeaAgent v0.7.3

TeaAgent 是一个**自主进化型智能助手**，基于 OpenAI 兼容 Function Calling 接口。核心特色：**可自我扩展工具库**、**系统提示词自我进化**、**双模式人格切换**、**三层认知系统**（记忆/反思/潜意识）。

核心仅 8 个轻量依赖（openai、markdown、tkinterweb、pyautogui、mss、Pillow、requests、beautifulsoup4），OCR/TTS/ASR 为可选扩展。仅依赖 Python tk 库，无需浏览器，极致轻量。绝大部分代码由 LLM 自行生成，是一个「AI 写 AI」的实验项目。

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
    ├─ 早期轮次 (>recent_turns)  ──→ user + ai_msg（纯文本，丢弃 tool calls）
    │     └─ 仅保留最终回复结论，token 消耗极小
    │
    ├─ 近期轮次 (<recent_turns)  ──→ user + rounds → _compress_tool_rounds()
    │   └─ 非最新                 └─ 首3+尾3行 + 模式摘要，保留关键信号
    │
    └─ 最新一轮 (is_last)       ──→ user + rounds → 完整保留（仅 repair，不压缩）
          └─ 当前上下文需要完整工具调用链
```

| 轮次位置 | user 消息 | assistant | tool calls | 压缩？ |
|---------|-----------|-----------|------------|--------|
| 早期 | ✅ | 纯文本 `ai_msg` | ❌ 丢弃 | — |
| 近期非最新 | ✅ | `rounds` | ✅ 智能压缩 | `_compress_tool_rounds` |
| 最新一条 | ✅ | `rounds` | ✅ 完整 | 仅 repair |

> 早期轮次只看结论，近期轮次保留关键信号，最新一轮完整上下文 — 三层渐进，token 开销动态平衡。

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
              ├─ ③ 摘要旧历史 (summarize_old_history)            │
              │    keep_turns 轮以外的 → cheap_model 压缩          │
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
                   │              │
                   └──────┴──────┘

历史加载 (load_history):
  旧轮次 (>keep_turns)  → user + ai_msg (裁剪工具链)
  最近N轮                → 完整工具链 → 智能压缩 (首3+尾3行+模式摘要)
```

### 工具模块化：Skill 系统

35 个工具按场景分为 6 个 Skill，**按需激活**以节省 token：

```
Skill (激活条件)                    工具数   默认
──────────────────────────────────────────────────
🎛️  CORE (始终激活)                   5      ✅    save/reload/rollback/list_versions/skill
📁  file_system (文件/命令操作)        4      ✅    file/exec/sudo_gui/pkg
⏰  utility (时间日期)                 2      ✅    gettime/date_diff
🖥️  desktop_automation (截图/OCR)      4            screenshot/ocr/input/notify
📝  self_evolution (自我进化)         10            self_evolve/build/bump_version/...
🔊  interaction (语音/搜索)            3            speak/listen/search
🧠  memory_knowledge (记忆/知识库)     3            memory/kb/reflection
```

- **默认场景**（纯对话）：仅 11 工具，token 开销 -68%
- **自动激活**：用户输入 "截图"/"OCR" → desktop_automation 自动激活 → 15 工具
- **手动控制**：`toolkit_skill(action='activate', name='self_evolution')` 随时切换
- **提示词注入**：仅激活 Skill 的领域指令注入 system prompt，不浪费 token

### Token 优化：双层压缩

单轮对话中，`apt install`、`gradle build`、`sdkmanager` 等工具输出动辄数千行日志，全部保留在上下文中会造成巨大 token 浪费。TeaAgent 通过双层压缩解决：

```
第一层 (toolkit_exec 实时截断)          第二层 (basesession.load_history)
  stdout ≤ 4000字符 / 80行              加载历史时智能压缩
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
         └─ SystemPromptManager ← 动态提示词进化 (v23)
```

### 数据模型

```
SQLite (chat_history.db)
├── topics             ← 会话主题 (title, summary, created_at)
├── conversations      ← 对话记录 (user_msg, ai_msg, rounds_json)
├── memories           ← 长期记忆 (content, category, priority, tags)
├── reflections        ← 反思记录 (suggestions, prompt_adjustment)
├── prompt_versions    ← 提示词版本 (content, version, created_at)
└── config_history     ← 配置变更记录

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
| **调用日志** | 控制台 `call embedding: {model}, {text[:80]}`，与主模型打印格式对齐 |

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
│ ③ 历史对话摘要                                     │
│    └─ 超过 keep_turns 轮的旧对话被压缩为一段文字     │
│    └─ + 固定 assistant 确认（"好的，我已知晓…"）     │
├──────────────────────────────────────────────────┤
│ ④ 最近 N 轮完整对话                                │
│    └─ 含工具调用链（早期轮次仅 user+ai_msg）         │
│    └─ 最新一轮完整保留，近期轮次智能压缩              │
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
  │  · 系统提示词需要补充什么指引？ ← prompt_adjustment │
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

### 变化 vs 固定对照表

| 组件 | 会变化？ | 变化时机 | 来源 |
|------|:---:|------|------|
| **核心系统提示词** | ✅ | 每次对话后如有反思建议则自动进化 | DB `system_prompts` 表 |
| **Skill 领域指令** | ✅ | 用户输入触发词时自动激活/停用 Skill | 各 Skill 的 `SKILL_MANIFEST` |
| **用户规则记忆** | ✅ | 随着用户提要求、确认事实持续积累 | `memories` 表 (CRITICAL) |
| **长期记忆注入** | ✅ | 每次对话匹配不同记忆，相似度动态计算 | MemoryManager 打分排序 |
| **历史摘要** | ✅ | 每轮对话后旧内容被重新摘要压缩 | 便宜模型生成 |
| **最近 N 轮对话** | ✅ | 滑动窗口，新进旧出 | `conversations` 表 |
| **反思分析 Prompt** | ❌ 固定 | 写在 `reflection.py`，需手动修改 | `REFLECTION_SYSTEM_PROMPT` |
| **提示词进化 Prompt** | ❌ 固定 | 写在 `prompt_manager.py`，需手动修改 | `EVOLVE_SYSTEM_PROMPT` |
| **历史摘要 Prompt** | ❌ 固定 | 写在 `session_prompts.py`，需手动修改 | `HISTORY_SUMMARIZE_*` |
| **主题摘要 Prompt** | ❌ 固定 | 写在 `session_prompts.py`，需手动修改 | `TOPIC_SUMMARY_*` |

> **核心要点**：系统提示词确实会随着对话推进逐渐演化——反思引擎分析 Agent 的"工作表现"，提示词进化引擎据此优化"工作指南"。这是一个**活的、自我改进的 Prompt 系统**，而非静态模板。

### 版本管理

- `prompt_manager.list_versions()` 查看所有历史版本
- `prompt_manager.rollback(version)` 回滚到任意历史版本
- `prompt_manager.get_stats()` 查看版本统计（总数/当前版本/ID）
- 如果反思未产生有效建议，自动跳过进化（不生成重复版本）

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

## 🔧 工具库 (35 工具)

### 系统操作
| 工具 | 功能 |
|------|------|
| `toolkit_exec` | 执行系统命令（120s硬超时，超时强制kill） |
| `toolkit_batch_exec` | **并行**批量执行（线程池，8 workers） |
| `toolkit_sudo_gui` | 跨平台提权（GUI密码框/UAC） |
| `toolkit_gettime` | 获取当前时间 |
| `toolkit_date_diff` | 日期差计算 |

### 文件与配置
| 工具 | 功能 |
|------|------|
| `toolkit_file` | 统一文件读写 |
| `toolkit_list_dir` | 目录列表（支持递归） |
| `toolkit_config` | 运行时配置调优 |
| `toolkit_build` | 构建/修复 pyproject.toml |
| `toolkit_release_version` | 自动化版本发布 |

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
| `toolkit_save` | 创建/更新工具函数 |
| `toolkit_reload` | 热加载工具库 |
| `toolkit_self_evolve` | 修改项目源码（自动注释+备份+验证） |
| `toolkit_rollback` | 工具版本回滚 |
| `toolkit_list_versions` | 工具版本历史 |

### 认知与人格
| 工具 | 功能 |
|------|------|
| `toolkit_reflection` | 元认知反思 |
| `toolkit_prompt_evolve` | 提示词多版本进化 (v23) |
| `toolkit_subconscious` | 潜意识引擎 |
| `toolkit_proactive` | 自主心跳/目标管理 |
| `toolkit_mode` | **双模式人格切换** |
| `toolkit_toggle_reasoning` | 推理模式开关 |

### 语音与通知
| 工具 | 功能 |
|------|------|
| `toolkit_speak` | TTS 文本朗读 |
| `toolkit_listen` | STT 语音输入 |
| `toolkit_notify` | 跨平台桌面通知 |
| `toolkit_comment` | 生成代码注释前缀 |
| `toolkit_self_report` | Agent 状态报告 |
| `toolkit_dump_topic` | 会话导出 markdown |

### 安装与管理
| 工具 | 功能 |
|------|------|
| `toolkit_pkg` | 智能包管理（别名映射、批量安装） |
| `toolkit_run_tests` | 项目测试运行 |

---

## ⚡ 并行执行

`toolkit_batch_exec` 使用 `ThreadPoolExecutor` 并发执行独立命令：

```python
toolkit_batch_exec(commands=[
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
├── tea_main_cli.py             ← [CLI 入口](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/tea_main_cli.py)
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
├── prompt_manager.py           ← [SystemPromptManager](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/prompt_manager.py) (v23)
│
├── store.py                    ← [SQLite 持久化存储](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/store.py)
├── tlk.py                      ← [工具库加载/校验/保存](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/tlk.py)
├── merge_db.py                 ← [数据库合并工具](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/merge_db.py)
│
├── mqtt_agent_connector.py     ← [MQTT 连接器](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/mqtt_agent_connector.py) (注册 broker + 订阅)
├── mqtt_client.py              ← [PC 端 MQTT 客户端](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/mqtt_client.py) (pc client)
├── chat_room_connector.py      ← [聊天室连接器](https://github.com/sunkwei/tea_agent/blob/master/tea_agent/chat_room_connector.py)
│
└── toolkit/                    ← [35 个工具](https://github.com/sunkwei/tea_agent/tree/master/tea_agent/toolkit) (含动态注册工具)
    ├── toolkit_exec.py
    ├── toolkit_batch_exec.py
    ├── toolkit_mode.py
    ├── toolkit_speak.py
    ├── toolkit_listen.py
    ├── ... (30 more)
```

---

## 🚀 快速开始

### 环境
- Python 3.10+
- OpenAI 兼容 API 密钥
- tkinter (通常自带)

```bash
pip install -e .  # 核心依赖
pip install -e ".[ocr]"     # + OCR (easyocr → torch 746MB)
pip install -e ".[desktop]" # + 全部可选 (ocr+tts+asr)
python -m tea_agent.main_db_gui
```

### 配置

`$HOME/.tea_agent/config.yaml`（优先）→ `tea_agent/config.yaml`（回退）：

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"

cheap_model:
  api_key: "sk-xxx"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"      # 用于摘要/记忆提取/反思

# 运行时参数
max_history: 10                     # 最大历史消息数
max_iterations: 50                  # 最大工具调用轮数
enable_thinking: true               # DeepSeek 思维链
keep_turns: 8                       # 保留最近 N 轮完整对话
max_tool_output: 131072             # 工具输出截断 (128KB)
memory_extraction_threshold: 1      # 记忆提取触发阈值
memory_dedup_threshold: 0.3         # 记忆去重相似度

```

### 全局配置路径

| 路径 | 内容 |
|------|------|
| `$HOME/.tea_agent/config.yaml` | 用户配置 |
| `$HOME/.tea_agent/chat_history.db` | SQLite 数据库 |
| `$HOME/.tea_agent/kb/` | 知识库文档 |
| `$HOME/.tea_agent/subconscious_state.json` | 潜意识引擎状态 |

---

## 📝 使用示例

1. **日期计算**：「去年12月26号到今天过去多少天了？」→ 自动创建工具计算
2. **系统脚本**：「创建 PowerShell 脚本获取公网 IP 并邮件发送，加入计划任务」
3. **GUI 自修改**：「字体太小，将输入框和 html render 窗口字体改为 14 号」
4. **版本发布**：「修改 pyproject.toml 版本为 0.2.3，更新 CHANGELOG，打包测试，git push」
5. **代码注释规范**：「记住，修改代码时增加 @{date} generated by {model}, {desc} 注释」
6. **快捷键扩展**：「ESC 打断、Ctrl+= 放大、Ctrl+- 缩小 HtmlFrame」
7. **工具迁移**：「将 user 目录下的工具函数移动到内置目录」→ Agent 自动对比、移动、测试、提交
8. **文档自更新**：「根据当前功能和修改，更新 README.md 和 CHANGELOG.md」
9. **记忆规则说明**：「在 README 中增加记忆/反思生成规则」→ Agent 读取源码提炼规则
10. **加载动画**：「切换主题时显示加载动画」→ HtmlFrame spinner + 60ms 延迟
11. **thinkpad wayland 下按键编码修正**：使用布局预览，发现按下左 alt, F6 同时点亮，查找原因 ....

---

## 模型兼容

- ✅ **DeepSeek** (reasoning_content/thinking)
- ✅ **GLM-5** (智谱)
- ✅ **Qwen3.6** (通义千问)
- ✅ **Ollama 本地** (gemma4:26b 等)

---

## 📜 版本历史

| 版本 | 关键变化 |
|------|---------|
| v0.7.18 | HtmlFrame 轮次视图：最新轮渲染+历史链接表/同主题跳过修复/on_link_click 轮次跳转 |
| v0.7.3 | 嵌入向量：自动嵌入/语义搜索/numpy BLOB 存储/打印调用日志 |
| v0.6.3 | 依赖瘦身：easyocr→可选, torch 746MB 不再必需 |
| v0.6.2 | 历史加载三级渐进策略（早期纯文本 / 近期压缩 / 最新完整）|
| v0.6.1 | GUI 自动重启 (watchdog) + 数据安全三道防线 + 续命 10 轮统一 |
| v0.6.0 | Skill 模块化系统 (按需激活 -68% token) + toolkit_exec 硬超时 + Mixin bug修复 |
| v0.5.6 | Token 双层压缩 (exec截断 + history智能摘要，-95%) + sudo GUI密码框 |
| v0.5.5 | 周轮转修复 (shutil.copy2) + 数据库合并工具 (merge_db.py) |
| v0.5.0 | 科幻小说《点火纪元》+ SQLite WAL + 任务通知 + 百度搜索 |
| 自由奔放 v1 | 潜意识唤醒 + jieba 分词 + 语音 TTS/STT + 自主心跳 |
| 自由奔放 v2 | 潜意识主动通知 + batch_exec 并行 + 提示词进化 v23 |
| 自由奔放 v3 | 双模式人格系统 (pragmatic/creative/mixed) |

---

## 开源协议
MIT License
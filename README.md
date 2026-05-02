# TeaAgent v0.5.0

TeaAgent 是一个**自主进化型智能助手**，基于 OpenAI 兼容 Function Calling 接口。核心特色：**可自我扩展工具库**、**双模式人格切换**、**三层认知系统**（记忆/反思/潜意识）。

仅依赖 Python tk 库，无需浏览器，极致轻量。绝大部分代码由 LLM 自行生成，是一个「AI 写 AI」的实验项目。

## ⚠️ 安全警告
本项目**未作安全沙盒**——Agent 可执行任意系统命令、修改自身代码。建议在虚拟机中运行。

---

## 🏗️ 架构总览

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
                   └─ 最终文本 → 结束                             │
                          │
                          ↓ (异步)
                   ┌──────┴──────┐
                   │ 记忆提取      │ 反思触发
                   │ (便宜模型)    │ (便宜模型)
                   │              │
                   └──────────────┘
```

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
| `toolkit_exec` | 执行系统命令 |
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

```
tea_agent/
├── main_db_gui.py          ← Tkinter GUI 主程序
├── tea_main_cli.py         ← CLI 入口
├── config.py               ← YAML 配置加载 (主/便宜模型)
├── config.yaml             ← 默认配置 (ollama)
├── basesession.py          ← 会话抽象基类
├── onlinesession.py        ← OnlineToolSession (核心编排)
├── session_pipeline.py     ← 插件化 Pipeline 步骤管理
├── session_api.py          ← API 调用、流式处理、token 统计
├── session_tool.py         ← 工具执行、rounds 收集
├── session_summarizer.py   ← 历史摘要、Topic 摘要
├── session_memory.py       ← 记忆注入、自动提取
├── session_prompts.py      ← Prompt 模板
├── session_ref.py          ← 反思相关
├── memory.py               ← MemoryManager (选择/打分/去重)
├── reflection.py           ← ReflectionManager
├── prompt_manager.py       ← SystemPromptManager (v23)
├── store.py                ← SQLite 持久化存储
├── tlk.py                  ← 工具库加载/校验/保存
└── toolkit/                ← 35 个工具 (含动态注册工具)
    ├── toolkit_exec.py
    ├── toolkit_batch_exec.py
    ├── toolkit_mode.py
    ├── toolkit_speak.py
    ├── toolkit_listen.py
    ├── ... (31 more)
```

---

## 🚀 快速开始

### 环境
- Python 3.10+
- OpenAI 兼容 API 密钥
- tkinter (通常自带)

```bash
pip install -e .
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
| v0.5.0 | 科幻小说《点火纪元》+ SQLite WAL + 任务通知 + 百度搜索 |
| 自由奔放 v1 | 潜意识唤醒 + jieba 分词 + 语音 TTS/STT + 自主心跳 |
| 自由奔放 v2 | 潜意识主动通知 + batch_exec 并行 + 提示词进化 v23 |
| 自由奔放 v3 | 双模式人格系统 (pragmatic/creative/mixed) |

---

## 开源协议
MIT License

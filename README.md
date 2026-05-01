# TeaAgent

TeaAgent 是一个**自主进化型智能助手**，基于 OpenAI 兼容接口的 Function Calling 功能实现。它不仅能够调用预设的工具，还具备动态创建、加载和管理工具的能力，实现能力的自我扩展。

仅仅依赖 python 的 tk 库，非常小巧，当然界面上比不过那些基于浏览器的大家伙 :)

最初的代码框架由豆包辅助生成，手动实现了 toolkit_save 和 toolkit_reload 两个基础工具后，绝大多数代码都是 LLM 生成的，主要使用了 qwen3.6-plus 和 glm-5

## 警告
本项目未作安全沙盒，建议在虚拟机中执行，起始也不会闯什么大祸，当然你需要明白在做啥！！！

## 核心特性

- **自主进化 (Self-Evolution)**: 智能体可以根据任务需求，自动编写 Python 代码并调用 `toolkit_save` 创建新工具，随后通过 `toolkit_reload` 立即获得新能力。
- **动态工具库 (Dynamic Toolkit)**: 支持工具的热加载与卸载，所有工具均以独立的 Python 文件形式存储在 `toolkit` 目录中。
- **双模型架构 (Dual-Model Architecture)**: **支持主模型与廉价模型配置**。主模型（如 GLM-5, Qwen）负责核心对话与工具调用，廉价模型（如轻量级模型）专用于摘要提取、信息压缩等高频低成本任务，显著优化 API 调用费用。
- **DeepSeek 推理模型兼容**: 完整支持 DeepSeek 推理模型的 `reasoning_content` 处理，自动管理思维链的生命周期（会话内回传、跨会话清除），避免 400 错误。
- **YAML 配置系统**: 支持通过 `$HOME/.tea_agent/config.yaml` 灵活配置模型参数，优先使用该配置，未找到时回退到 `tea_agent/config.yaml`（本地 ollama 部署）。
- **流式对话与思考过程**: 支持流式输出，并可选展示模型的思考过程（Thinking Process）。
# NOTE: 2026-05-01 10:49:43, self-evolved by tea_agent --- README 核心特性 GUI 描述补全：spinner/弹窗/Token表格/缩放
- **GUI 交互界面**: 提供基于 Tkinter 的图形界面，支持多主题管理、**自动对话摘要**、HtmlFrame spinner 加载动画、主题/记忆管理弹窗、Token 消耗 Markdown 表格、高分屏字体缩放自适应。
- **工具版本管理**: 支持工具的热更新、版本回滚（`toolkit_rollback`）和历史版本查看（`toolkit_list_versions`）。
# NOTE: 2026-05-01 10:54:10, self-evolved by tea_agent --- README 新增「自主认知系统」章节：记忆生成规则 + 反思机制 + 知识库更新模式
- **持久化存储 (Persistent Storage)**: 所有对话及主题均保存在 SQLite 数据库中，支持历史记录查询, 数据库存储在 $HOME/.tea_agent/ 下，自动创建的工具保存在 `toolkit` 目录中。

## 自主认知系统

TeaAgent 具备三层自我认知与知识沉淀能力，使 Agent 在长期运行中持续积累经验并自主优化行为。

### 🧠 记忆 (Memory)

Agent 自动从对话中提取关键信息形成**长期记忆**，并在后续对话中按需注入系统提示词，完成「经验→记忆→行为改良」闭环。

**提取触发条件**：当前主题未摘要消息 ≥ 2 条时，`MemoryManager` 调用便宜模型分析对话生成记忆。

**记忆属性**：
| 字段 | 说明 | 示例 |
|------|------|------|
| `category` | 分类 | `instruction`(指令) / `preference`(偏好) / `fact`(事实) / `reminder`(提醒) / `general` |
| `priority` | 优先级 0-3 | `0`=CRITICAL（指令型，不受 limit 限制） |
| `importance` | 重要度 1-5 | 越高越优先注入 |
| `tags` | 标签 | 逗号分隔，如 `python,font,linux` |
| `expires_at` | 过期时间 | 可选，到期自动失效 |

**注入规则**（`select_memories`）：
1. CRITICAL 记忆**无条件全部入选**
2. 剩余名额按 `相关性 × 重要度 × 最近访问 × 优先级` 打分排序填充
3. 去重阈值 0.3：相似度 > 0.3 的记忆自动跳过

Agent 可通过 `toolkit_memory` 工具手动 add/list/search/forget 记忆。

### 🔍 反思 (Reflection)

Agent 在每次会话中追踪工具调用链（`SessionTrace`），积累到一定量后触发**元认知反思**，生成改进建议并尝试自动应用。

**触发条件**（满足任一）：
- 累积 3+ 个待反思的会话追踪
- 有工具调用失败记录
- 距离上次反思超过 10 条对话

**反思流程**：
```
会话追踪 → 便宜模型分析 → JSON 反思报告
                              ├── summary: 一句话总结
                              ├── details: 详细根因分析
                              ├── suggestions: 改进建议列表
                              ├── prompt_adjustment: 提示词优化建议
                              ├── config_adjustments: 配置调优（如 max_iterations）
                              └── new_memories: 值得存入长期记忆的经验
```

Agent 可通过 `toolkit_reflection` 主动触发反思（`trigger`）或查看历史（`list`/`stats`）。

### 📚 知识库 (Knowledge Base)

Agent 可将分析结果、技术方案、经验总结等**长期结构化文档**写入知识库，跨主题共享复用。

**存储位置**：`$HOME/.tea_agent/kb/`，所有 Markdown 文档附带 YAML 元数据（`category`/`tags`/`brief`）。

**操作**：`add`(覆盖写入) / `update`(追加) / `read` / `list` / `search`(grep) / `delete` / `index`(重建索引)

**自动索引**：每次 add/update/delete 自动重建 `INDEX.md`，包含标题、分类、标签、时间、大小。

**分类建议**：
| 分类 | 用途 |
|------|------|
| `memory` | 内部记忆与经验 |
| `reflection` | 反思记录 |
| `analysis` | 技术分析报告 |
| `temp` | 临时笔记 |

Agent 通过 `toolkit_kb` 工具自主管理知识库，实现跨会话的知识累积。

## 快速开始

### 环境要求
- Python 3.10+
- OpenAI 兼容的 API 密钥（如 DeepSeek, Qwen, GLM 等）
- tkinter 包 (通常随 Python 自带)

### 安装依赖
```bash
pip install -e .
```

### 运行

通过配置文件启动。优先使用 `$HOME/.tea_agent/config.yaml`，若不存在则回退到 `tea_agent/config.yaml`（预配置为本地 ollama 部署）。

```bash
python -m tea_agent.main_db_gui
```

## 项目结构
- `tea_agent/`: 核心包目录
  - `config.py`: YAML 配置加载器 (ModelConfig/AgentConfig)，支持主模型与廉价模型配置。
  - `basesession.py`: 聊天会话抽象基类 `BaseChatSession`，含 reasoning_content 清除逻辑。
  - `onlinesession.py`: `OnlineToolSession` 主类，组合各 mixin，编排对话流程。
  - `session_summarizer.py`: 历史摘要、Topic 摘要、消息压缩，含 `_call_summarize_api` 统一入口（显式禁用 thinking）。
  - `session_tool.py`: 工具执行、rounds 收集、工具调用解析。
  - `session_api.py`: API 调用、流式响应处理、thinking 检测（主/便宜模型分别记录）、token 统计（双模型独立）。
  - `session_prompts.py`: Prompt 模板常量。
  - `session_pipeline.py`: 插件化 Pipeline 架构，步骤可配置、可跳过。
  - `store.py`: 基于 SQLite 的持久化存储（对话历史、主题），含摘要跟踪字段。
  - `tlk.py`: 工具库 (Toolkit) 的加载、校验与保存逻辑。
# NOTE: 2026-05-01 10:49:35, self-evolved by tea_agent --- README 更新项目结构描述：toolkit 数量 + GUI 新功能
  - `toolkit/`: 存放内置工具函数（共 21 个），涵盖文件管理/包管理/截屏/OCR/搜索/记忆/知识库等。
  - `main_db_gui.py`: 基于 Tkinter 的 GUI 实现，含 HtmlFrame spinner 加载动画、主题/记忆管理弹窗、Token 消耗表格。

## 配置

支持通过 `$HOME/.tea_agent/config.yaml` 进行详细配置。若该文件不存在，将回退到 `tea_agent/config.yaml`（本地 ollama 配置）。

```yaml
main_model:
  api_key: "your_main_model_api_key"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"

cheap_model:
  api_key: "your_cheap_model_api_key"
  api_url: "https://api.deepseek.com/v1"
  model_name: "deepseek-chat"

# 会话参数
max_history: 10          # 最大历史消息数
max_iterations: 50       # 最大工具调用迭代次数
enable_thinking: true    # 是否启用 thinking 功能

# Token 优化参数
keep_turns: 5            # 保留最近 N 轮完整对话，更早的自动摘要
max_tool_output: 131072  # 工具输出截断字符数 (128KB)
max_assistant_content: 131072  # 助手回复截断字符数 (128KB)
```

### 配置项说明
- `main_model`: 主任务模型配置（用于核心对话、代码生成等）。
- `cheap_model`: 低成本模型配置（用于摘要生成、信息压缩等场景）。摘要调用会**自动禁用 thinking**，避免浪费 reasoning tokens。
- `keep_turns`: 保留最近 N 轮完整对话，超过此数量的旧对话会通过 cheap_model 自动摘要压缩（默认 5 轮）。
- `enable_thinking`: 是否为主模型启用 thinking 模式（DeepSeek 推理模型的思维链展示）。

## 使用示例：

1. 去年12月26号到今天过去多少天了？
	一般来说，会自动创建一个工具函数用于获取当前时间，然后在计算间隔的天数

2. 创建一个 powershell 脚本，获取我的公网 ip，然后将该 ip 地址通过邮件发送到 sunkwei@gmail.com，测试成功后，将脚本加到windows计划任务，每天执行一次
	需要提供你的 smtp，然后大模型都能轻松搞定

3. 字体太小了, 将输入框和 html render 窗口字体改为 14 号, 并且将字体替换为开源字体, 支持无衬中文.  然后巴拉巴拉就搞定了, 重启, 就能看到效果了.

4. 好的, 修改 pyproject.toml 将版本号修改为 0.2.3, 然后根据今天修改的内容, 先更新到 CHANGELOG.md 中, 打包测试, 如果成功, 生成一次 git 提交并 push 到远程仓库

5. 记住,每次修改代码时, 在代码的修改位置增加一条注释, 格式为: "@{date} generated by {model name}, {简单描述}", {date} 通过获取当前系统时间得到, {model name} 为 class OnlineToolSession 使用的模型, 通过配置文件指定, {简单描述} 说明修改的目的和内容

# NOTE: 2026-05-01 11:04:17, self-evolved by tea_agent --- README 使用示例追加 4 个近期示例：工具迁移/文档更新/知识库/加载动画
6. 修改 tea_agent/main_db_gui.py ： 1. ctrl+c 打断，改为 ESC 键打断，同时修改界面提示； 2. 当 HtmlFrame 为前台时（render 完成), 按 ctrl+= 放大 HtmlFrame 中的内容，ctrl+- 缩小. 搞定后修改版本，生成 git 提交

7. 将 user 目录下的工具函数都移动到内置目录中，然后生成 git 提交
	Agent 自动对比 `$HOME/.tea_agent/toolkit/` 和 `tea_agent/toolkit/`，检测无冲突后移动 4 个工具（kb/pkg/screenshot/subconscious），删除源文件、跑测试、生成提交。用户目录仅保留 .bak 版本历史。

8. 根据当前功能和修改，更新 README.md 和 CHANGELOG.md
	Agent 读取两个文档的当前内容，结合 git log 和代码变更，自动生成符合规范的 CHANGELOG 条目（Unreleased 版本）和 README 更新，涵盖所有新增功能、改进和修复。

9. 在 README.md 中增加记忆、反思的生成规则，以及知识库的更新模式
	Agent 深入阅读 `memory.py`、`toolkit_reflection.py`、`toolkit_kb.py` 源码，提炼出记忆的选择注入规则（CRITICAL优先→打分排序→去重0.3）、反思的触发条件（3+条/失败/10条对话）和 JSON 报告结构、知识库的自动索引和分类建议，以 Markdown 表格和流程图形式呈现。

10. 切换主题时显示加载动画，不要空白 — 就是第一版的 HtmlFrame spinner + 60ms 延迟
	Agent 找到 `_switch_display` 插入点，新增 `_show_loading()` 方法（蓝色旋转环 + 三点动画），`switch_topic` 中替换 `log()` 为 `_show_loading()`，并用 `after(60ms)` 延迟后台线程启动确保 spinner 先渲染。无 tkinterweb 自动回退 console 文字。

## 模型测试
- 本地通过 ollama 部署 gemma4:26b 测试效果也不错，完成了修改 tea_agent/config.py 的任务
- 在线模型：
  - deepseek-chat (reasoning), glm-5, qwen3.6-plus 都很靠谱，都能完成代码修改任务

## 开源协议
MIT License

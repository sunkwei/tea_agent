# project_structure


# tea_agent 项目结构 (as of 2026-05-16)

## 根目录 (/home/sunkw/work/git/tea_agent/)
- `tea_agent/` — 主包
- `tests/`, `test/`, `test_tmp/` — 测试目录
- `docs/` — 文档
- `build/`, `dist/` — 构建产物
- `backup/` — 备份
- `android_port/` — Android 移植
- `chat_history.db` — 对话历史 SQLite
- `pyproject.toml` — 项目配置

## tea_agent/ 核心模块
| 文件 | 职责 |
|------|------|
| `__init__.py` | 包初始化 |
| `agent_core.py` | AgentCore 基类 (546行, 14方法) |
| `main_db_gui.py` | TkGUI 主窗口 (冻结备份, ~2007行, 70方法) |
| `gui.py` | GUI 主入口 (活跃开发目标) |
| `gui_dialogs.py` | GUI 配置/设置弹窗 |
| `cli.py` | CLI 接口 |
| `tea_main_cli.py` | CLI 主入口 |
| `tea_agent.py` | 核心 agent |
| `tlk.py` | 对话/思考逻辑 |
| `onlinesession.py` | OnlineToolSession (1061行, 17方法) |
| `basesession.py` | 会话基类 |
| `config.py` | 配置管理 |
| `config.yaml` | 默认配置 |
| `store.py` | 存储层 |
| `memory.py` | 记忆管理 |
| `reflection.py` | 反思模块 |
| `session_api.py` | 会话 API |
| `session_memory.py` | 会话记忆 |
| `session_pipeline.py` | 会话流水线 |
| `session_prompts.py` | 会话提示词 |
| `session_ref.py` | 会话引用 |
| `session_summarizer.py` | 会话摘要 |
| `session_tool.py` | 会话工具 |
| `prompt_manager.py` | 提示词管理 |
| `embedding_util.py` | 嵌入工具 |
| `logging_setup.py` | 日志配置 |
| `merge_db.py` | 数据库合并 |

## tea_agent/_gui/ — Composition 组件包 (2026-05-21: 原 gui/ → _gui/)
| 文件 | 职责 |
|------|------|
| `__init__.py` | 导出接口 |
| `_interfaces.py` | 抽象接口 (HtmlDisplay, TextDisplay, StatusDisplay, ImagePicker) |
| `_tk_impl.py` | tkinter 实现 (HtmlFrameDisplay, ScrolledTextDisplay, LabelStatusDisplay, TkImagePicker) |
| `_renderer.py` | ChatRenderer 渲染组件 |
| `_tray.py` | TrayManager 托盘图标 |
| `_images.py` | ImageHandler 图片处理 |
| `_markdown.py` | Markdown 渲染 |

## tea_agent/toolkit/ — 工具库 (~40个工具)
核心工具: toolkit_exec, toolkit_file, toolkit_kb, toolkit_memory, toolkit_self_evolve, toolkit_search 等

## tea_agent/skills/ — 技能模块
- file_system, memory_knowledge, self_evolution, utility, interaction, desktop_automation



## tea_agent/store/ — Composition 模式拆分 (2026-05-16)
| 文件 | 职责 | 方法数 |
|------|------|--------|
| `__init__.py` | 包入口，导出 Storage + get_storage | - |
| `_base.py` | StoreComponent 基类 (conn + _new_id) | 2 |
| `_core.py` | Storage 核心 (连接/迁移/备份/轮转/表初始化) | ~20 |
| `_topics.py` | TopicStore (主题 CRUD + Token 统计) | 8 |
| `_conversations.py` | ConversationStore (对话/Agent轮次/自动嵌入) | 6 |
| `_summaries.py` | SummaryStore (摘要/三级历史) | 11 |
| `_memories.py` | MemoryStore (长期记忆/FIFO淘汰) | 10 |
| `_prompts.py` | PromptStore (系统提示词版本管理) | 6 |
| `_reflections.py` | ReflectionStore (反思记录) | 4 |
| `_config.py` | ConfigHistoryStore (配置变更历史) | 3 |
| `_vectors.py` | VectorStore (向量/语义搜索) | 10 |

向后兼容：`from tea_agent.store import Storage, get_storage` 保持不变，`__getattr__` 自动路由。
旧 `store.py` → `store_legacy.py` 作为备份。

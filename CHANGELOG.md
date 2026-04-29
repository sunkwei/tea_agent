# Changelog

All notable changes to this project will be documented in this file.

## [0.3.2] - 2026-04-29

- feat: 新增 TopicDialog 主题管理弹窗
  - 主题列表（ID/标题/创建时间/Token消耗/对话数/状态）
  - 新建主题、重命名、停用/启用、硬删除
  - 双击/按钮切换到选中主题
  - 导出：选中主题 / 全部主题到 Markdown
  - 导出模式可选「完整」或「仅用户输入」

### Improvements
- improve: 跨平台字体自动检测，Windows 优先使用 Microsoft YaHei UI + Cascadia Code
  - 懒加载检测（`_init_fonts()`），避免 import 时无 Tk root 报错
  - CSS font-family 完整回退链覆盖 Windows/Linux 常见中文字体
  - tkinter UI 控件字体动态匹配系统可用字体

### New Features
- feat: 重新实现长期记忆系统（全新设计，不同于 0.3.0 版本）
  - `store.py` 新增 `memories` 表（id/content/category/priority/importance/expires_at/tags/is_active）
  - 8 个 CRUD 方法：`add_memory`/`get_memory`/`update_memory`/`deactivate_memory`/`delete_memory`/`get_active_memories`/`search_memories`/`get_memory_stats`
  - `cleanup_expired_memories` 集成在查询中自动清理过期记忆
  - `get_storage()` 模块级单例供工具函数使用

- feat: 实现 MemoryManager（`memory.py` 新建）
  - `select_memories()`: 优先级排序 + 相关性排序，自动过期清理
  - `format_memories()`: 按分类格式化记忆为 system message
  - `import_from_extraction()`: 批量导入+去重检测

- feat: 实现 SessionMemoryMixin（`session_memory.py` 新建）
  - `_inject_memory_into_messages()`: 记忆注入至 system prompt
  - `_build_api_messages()` 集成记忆注入（system → memories → summary → recent）
  - `trigger_memory_extraction()`: 自动记忆提取流程

- feat: 5 个内置 Memory 工具（`tea_agent/toolkit/`）
  - `toolkit_memory_add`: 添加记忆（支持分类/优先级/重要度/过期时间/标签）
  - `toolkit_memory_search`: 搜索记忆（关键词+分类+标签+重要度过滤）
  - `toolkit_memory_list`: 列出活跃记忆（含统计信息）
  - `toolkit_memory_forget`: 软删除(失效)/硬删除记忆
  - `toolkit_memory_extract`: 从未摘要对话提取文本供 Agent 分析

- feat: GUI 新增 MemoryDialog 记忆管理弹窗
  - 统计栏（总数+分类分布+优先级分布）
  - 搜索过滤（关键词+分类组合框）
  - 记忆列表（ID/优先级/分类/内容/重要度/过期/标签）
  - 添加记忆对话框、软删除/硬删除、双击查看、导出 Markdown
  - 左侧面板新增「🧠 记忆管理」按钮

- feat: 状态栏动态显示工具调用轮次
  - `chat_stream` 新增 `on_status` 回调参数
  - `_execute_tool_loop` 每轮工具调用推送 `"调用工具第{N}轮..."`
  - GUI 状态栏: `⏳ 生成中... 调用工具第1轮 (ESC 打断)`

### Refactored
- refactor: 修改代码注释规范统一为 `{date} gen by {model}, {subject}` 格式

### Test Cases
- test: `test_memory_phase2.py` — MemoryManager 选择/格式化/导入去重测试
- test: `test_db_summary_logic.py` — 数据库摘要标记逻辑测试

---

## [0.3.1] - 2026-04-29

### Breaking Changes
- **移除 Memory 模块**：完全删除长期记忆功能，相关文件和参数全部清理
  - 删除文件：`tea_agent/memory.py`、`tea_agent/session_memory.py`、`tea_agent/toolkit/toolkit_memory_extraction_strategy.py`
  - 移除工具：`toolkit_memory_search`、`toolkit_memory_recent`、`toolkit_memory_stats`（`tlk.py`）
  - 移除配置参数：`memory_inject_limit`、`memory_extract_rounds`、`memory_extract_threshold`（`config.py`）
  - 移除 Prompt：`MEMORY_EXTRACT_SYSTEM`、`MEMORY_EXTRACT_USER_TEMPLATE`、`VALID_MEMORY_CATEGORIES`（`session_prompts.py`）
  - `OnlineToolSession` 不再继承 `SessionMemoryMixin`
  - `main_db_gui.py` 移除 `Memory` 导入和状态栏显示

### New Features
- feat: 深度支持 DeepSeek 推理模型的 `reasoning_content` 处理
  - 新增 `_strip_reasoning_content()` 静态方法（`basesession.py`），清除历史消息中的 reasoning_content
  - `load_history()` 加载历史时自动清除旧 API 会话的 reasoning_content
  - `reset_session_state()` 新一轮开始时统一清除 reasoning_content
  - `_build_api_messages()` 在 tool_loop 期间保留 reasoning_content，满足 DeepSeek 回传要求
  - `_collect_assistant_tool_calls_round` / `_collect_assistant_text_round` 传递 reasoning_content 确保持久化不丢失
  - 摘要确认 assistant 消息补充空 `reasoning_content: ""`，维持请求结构一致性
  - 新增 `toolkit_diag_reasoning` 诊断工具，检测消息列表中的 RC 问题
  - 详细文档：`DEEPSEEK_REASONING_SUPPORT.md`

- feat: 便宜模型 token 统计完善
  - 新增 `_last_cheap_usage` 字典，独立追踪便宜模型 token 消耗
  - 新增 `_accumulate_cheap_usage()`、`_track_api_usage()` 统一路由
  - 新增 `get_cheap_usage()`、`get_total_usage()`、`reset_cheap_usage()`
  - `_cheap_thinking_supported` 改为 `None`（延迟探测），摘要调用不依赖此状态

- feat: 摘要 API 调用显式禁用 thinking
  - 新增 `_call_summarize_api()` 统一入口，传 `extra_body={"thinking": {"type": "disabled"}}`
  - 自动回退：若模型不支持 `extra_body` 参数，降级到不带该参数的调用
  - 历史摘要和 Topic 摘要均使用此入口，避免浪费 reasoning tokens

### Refactored
- refactor: 历史摘要逻辑重构为基于数据库的持久化跟踪
  - `conversations` 表新增 `is_summarized` 列，标记对话是否已摘要
  - `t_conv_summary` 表新增 `last_summarized_id` 列，记录最后摘要的对话 ID
  - `Storage` 新增 `mark_as_summarized()`、`get_unsummarized_conversations()` 方法
  - `update_topic_summary()` 支持 `last_summarized_id` 参数
  - `_summarize_old_history()` 改为：获取未摘要对话 > keep_turns 则摘要最早的 N 条
  - `switch_topic()` 加载所有未摘要对话（不再限制 5 条）

- refactor: 摘要使用 `_conversations_to_text()` 替代 `_messages_to_text()`
  - 从数据库记录提取对话文本，保留工具调用链信息
  - 更完整的摘要上下文

### Bug Fixes
- fix: 修复 `_execute_tool_loop` 中最终文本回复的重复 assistant 消息问题（DeepSeek 400 错误根因）
  - 原代码 `self.messages.append(assistant_msg)` 后又调用 `self.add_assistant_message(content)`，
    导致两条相邻相同内容的消息（一条有 RC 一条无），跨会话清除 RC 后触发 400
  - 修复：删除冗余的 `self.add_assistant_message(content)` 调用

- fix: 修复 `_accumulate_usage` 的 truthiness 判断问题
  - `prompt_tokens` 为 0 时被错误跳过，改为 `is not None` 判断
  - `total_tokens` fallback 改为每次调用独立推算，避免多轮工具调用漏算

- fix: `save_msg` 移到 `chat_stream` 成功后执行
  - 避免 API 调用失败时产生空 conversation 记录

### Changed
- changed: `keep_turns` 默认值从 2/3 统一改为 5
  - `config.py`、`config.yaml`、`onlinesession.py`、`session_summarizer.py` 全部同步

---

## [0.3.0] - 2026-04-24

### New Features
- feat: 实现插件化会话流程（Pipeline 架构）
  - 新增 `session_pipeline.py` 模块，管理对话流程步骤
  - 将 `chat_stream` 拆分为 3 个可配置步骤：添加用户消息、摘要旧历史、工具循环
  - 支持启用/禁用步骤、重新排序、插入自定义步骤、跳过步骤
  - 步骤通过名称标识，可以灵活组合
  
- feat: 实现工具版本管理
  - `toolkit_save` 新增 `version` 参数，支持指定版本号
  - 保存工具时自动备份旧版本（格式：`{name}.v{version}.bak.py`）
  - 自动递增版本号（如果不提供）
  - 新增 `toolkit_rollback` 工具，支持回滚到指定版本
  - 新增 `toolkit_list_versions` 工具，列出所有可用版本
  - 版本备份文件带有时间戳和版本号注释

## [0.2.9] - 2026-04-24

### New Features
- feat: 扩展配置系统，将所有硬编码参数移至 config.yaml
  - 新增会话参数：`max_history`, `max_iterations`, `enable_thinking`
  - 新增 Token 优化参数：`keep_turns`, `max_tool_output`, `max_assistant_content`
- feat: 更新 `load_config()` 和 `save_config()` 支持新参数的读写
- feat: 创建完整的 config.yaml 模板（tea_agent/config.yaml），包含详细注释
- feat: 创建用户默认配置文件（$HOME/.tea_agent/config.yaml）
- feat: 更新 `main_db_gui.py` 从配置中读取所有参数，不再硬编码

## [0.2.8] - 2026-04-24

### Improvements & Changes
- changed: 优化 Topic 摘要提取逻辑，同时提取用户消息和 AI 回复，提供更完整的摘要上下文
- changed: 增强 LLM 返回值边界条件处理，增加 `None`、空字符串、类型安全检查
- changed: 重构 `_build_api_messages`：工具循环中不压缩消息，仅对历史做压缩处理
- changed: 保留最新 3 轮完整对话（不压缩），更早的对话使用 cheap_model 生成摘要
- changed: 优化 thinking 检测逻辑，主模型和便宜模型分别记录 thinking 支持状态，避免每次 API 调用都重复检测

### Bug Fixes
- fix: 修复 `_clean_topic_summary` 引号清洗不完整的问题，支持中英文引号
- fix: 修复数据库更新异常未独立捕获的问题，分离数据库操作和 LLM 调用异常处理

## [0.2.7] - 2026-04-24

### Refactor
- refactor: 将 `onlinesession.py` (930行) 拆分为多个模块，通过 Mixin 多继承组合
  - `basesession.py`: `BaseChatSession` 抽象基类
  - `session_prompts.py`: Prompt 模板常量
  - `session_summarizer.py`: 历史摘要、Topic 摘要、消息压缩
  - `session_tool.py`: 工具执行、rounds 收集、工具调用解析
  - `session_api.py`: API 调用、流式响应处理、thinking 降级、token 统计
  - `session_memory.py`: 记忆提取、记忆注入（已移除于 0.3.1）
  - 瘦身后的 `onlinesession.py` 仅保留 `OnlineToolSession` 主类，负责流程编排

### New Features
- feat: `toolkit_dump_topic` 工具新增 `role` 参数，支持导出模式选择
  - `role="all"`（默认）：导出完整内容，含用户输入、AI 回复、工具调用链
  - `role="user"`：仅导出用户输入内容
- feat: 新增 `test_dump_topic_user_role.py` 测试用例，验证 `role='user'` 模式

## [0.2.6] - 2026-04-23

### Bug Fixes
- fix: 修复流式响应中 chunk.choices 为空时导致的 index out of range 错误

## [0.2.4] - 2026-04-16

### Improvements & Changes
- changed: 将字体从微软雅黑替换为开源字体 Noto Sans CJK SC，支持更好的中文显示
- changed: HtmlFrame 渲染窗口字体大小从 14px 调整为 16px
- changed: 输入框字体大小从 11 号调整为 14 号
- changed: 代码块字体使用 Noto Sans Mono CJK SC 等开源等宽字体

### Documentation
- docs: 更新 README.md 示例说明，移除环境变量配置中的尖括号

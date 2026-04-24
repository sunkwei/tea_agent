# Changelog

All notable changes to this project will be documented in this file.

## [0.2.9] - 2026-04-24

### New Features
- feat: 扩展配置系统，将所有硬编码参数移至 config.yaml
  - 新增会话参数：`max_history`, `max_iterations`, `enable_thinking`
  - 新增 Token 优化参数：`keep_turns`, `max_tool_output`, `max_assistant_content`
  - 新增记忆参数：`memory_inject_limit`, `memory_extract_rounds`, `memory_extract_threshold`
- feat: 更新 `load_config()` 和 `save_config()` 支持新参数的读写
- feat: 创建完整的 config.yaml 模板（tea_agent/config.yaml），包含详细注释
- feat: 创建用户默认配置文件（$HOME/.tea_agent/config.yaml）
- feat: 更新 `main_db_gui.py` 从配置中读取所有参数，不再硬编码

## [0.2.8] - 2026-04-24

### Improvements & Changes
- changed: 优化 Topic 摘要提取逻辑，同时提取用户消息和 AI 回复，提供更完整的摘要上下文
- changed: 增强 LLM 返回值边界条件处理，增加 `None`、空字符串、类型安全检查
- changed: 重构 `_build_api_messages`：工具循环中不压缩消息，仅对历史做压缩处理
- changed: 实现基于记忆优先级的压缩策略，根据高优先级记忆数量和类别决定压缩程度
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
  - `session_memory.py`: 记忆注入、LLM 提取、保存
  - `session_summarizer.py`: 历史摘要、Topic 摘要、消息压缩
  - `session_tool.py`: 工具执行、rounds 收集、工具调用解析
  - `session_api.py`: API 调用、流式响应处理、thinking 降级、token 统计
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

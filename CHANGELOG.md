# Changelog

All notable changes to this project will be documented in this file.

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

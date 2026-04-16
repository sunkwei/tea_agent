# Changelog

All notable changes to this project will be documented in this file.

## [0.2.1] - 2026-04-16

### Features
- feat: LLM-driven memory extraction from conversations
- feat: 增加记忆体功能，支持从对话中提取核心记忆
- feat: 在 GUI 和会话层增加 "Thinking" 切换开关，支持模型思考过程显示
- feat: 重构工具库以支持用户覆盖，并添加核心模块
- feat: 新增 HttpFrame 展示静态页面功能，支持 ScrolledText 动态显示

### Improvements & Changes
- changed: 从环境变量读取 API Key 等敏感配置
- changed: 优化系统提示词 (System Prompt)
- changed: 修改 `toolkit_save()` 时的元数据 (meta) 检查逻辑，并更新返回值以方便 LLM 理解
- changed: 整理项目目录结构，优化打包流程

### Bug Fixes
- fix: 修正代码以符合 PEP8 规范
- fix: 解决 `toolkit.py` 与 `toolkit` 目录同名导致的导入冲突问题
- fix: 更新工具函数和主数据库 GUI 逻辑

### Chore
- chore: 确保 `toolkit` 目录被包含在项目构建中
- chore: 更新 `.gitignore`
- chore: 成功完成 `tea_agent` 的打包构建

## [0.2.0] - 2025-08-26

### Features
- feat: LLM-driven memory extraction from conversations (0674c67)
- feat: refactor toolkit to support user overrides and add core modules (3ddebba)
- add: 增加记忆体功能 (b64259f)
- self-evolution: add thinking toggle switch in GUI and session layer (2f223fe)

### Changes
- changed: 从环境变量读取 api key 等 (92322ca)
- changed: 修改 system prompt，修改 toolkit_save() 时的 meta 检查 (4c8a23e)

### Bug Fixes
- bugfix: 修改 toolkit.py 与 toolkit 目录重名，导致 import 优先使用目录名字了 (629458e)
- fix: update toolkit functions and main DB GUI (2b45202)
- 修正代码符合 PEP8 (558d65b)

### Chore
- chore: ensure toolkit directory is included in package build (bcb5e24)
- 打包 tea_agent 成功 (fb9a82c)
- 整理了目录，方便打包 (8303f32)
- 更新 toolkit_save() 返回值，方便 llm 更好理解 (7ee4f52)

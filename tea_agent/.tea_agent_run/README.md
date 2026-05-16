# 项目知识库 (Project KB)

存储位置: `tea_agent/.tea_agent_run/`

与用户知识库的区别:
- **项目 KB** (`tea_agent/.tea_agent_run/`): 项目架构、代码约定、技术决策等
- **用户 KB** (`$HOME/.tea_agent/kb/`): 跨项目的通用知识、偏好、经验

本目录由工具直接读写 (`toolkit_file`)，不使用 `toolkit_kb`（后者仅操作用户 KB）。

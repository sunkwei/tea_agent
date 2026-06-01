# sunkw v0.9.13

A self-evolving AI agent with dynamic toolkit management.

## 📊 工具使用 TOP5

| 工具 | 调用次数 |
|------|---------|
| — | — |

## 🧰 所有工具 (59 个)

- **`toolkit_build`** — def toolkit_build(action: str, directory: str = "."):
- **`toolkit_build_package`** — def toolkit_build_package():
- **`toolkit_bump_version`** — def toolkit_bump_version(version: str, file: str = "pyproject.toml", dry_run: bo
- **`toolkit_comment`** — def toolkit_comment(mode: str, description: str = "", model_name: str = ""):
- **`toolkit_config`** — toolkit_config — 允许 Agent 读取和修改自身运行时配置
- **`toolkit_date_diff`** — def toolkit_date_diff(start_date: str, end_date: str = None) -> dict:
- **`toolkit_diff`** — 生成 unified diff 格式的差异
- **`toolkit_dump_topic`** — def toolkit_dump_topic(role: str = "all") -> dict:
- **`toolkit_dynamic_skill`** — 确保技能目录存在。
- **`toolkit_edit`** — def toolkit_edit(file_path: str, action: str = "apply_patch", content: str = "",
- **`toolkit_edit_file`** — def toolkit_edit_file(filename: str, old_text: str, new_text: str, description: 
- **`toolkit_evolution_exp`** — Internal: get the exp path.
- **`toolkit_exec`** — def toolkit_exec(app: str = "", args: list = None, action: str = "single", comma
- **`toolkit_experience_solidify`** — def toolkit_experience_solidify(
- **`toolkit_explr`** — Internal: log.
- **`toolkit_export_last_pdf`** — Remove characters that fpdf2 cannot render
- **`toolkit_file`** — def toolkit_file(action: str, filename: str = "", content: str = "", path: str =
- **`toolkit_format_code`** — def toolkit_format_code(
- **`toolkit_get_config_path`** — def toolkit_get_config_path() -> dict:
- **`toolkit_get_models`** — def toolkit_get_models():
- **`toolkit_gettime`** — def toolkit_gettime() -> dict:
- **`toolkit_git_push_all_remotes`** — git 全远程推送工具 — 向所有配置的远程仓库推送当前分支
- **`toolkit_input`** — toolkit_input — 操作能力：鼠标移动/点击/拖拽 + 键盘输入/快捷键
- **`toolkit_js_fetch`** — 跨平台自动选择最佳浏览器：
- **`toolkit_kb`** — toolkit_kb -- Markdown 知识库管理工具。
- **`toolkit_list_dir`** — def toolkit_list_dir(path=".", recursive=False, show_hidden=False):
- **`toolkit_lsp`** — def toolkit_lsp(
- **`toolkit_lunar`** — toolkit_lunar — 公历/农历互转，含天干地支、生肖、节气
- **`toolkit_mcp`** — def toolkit_mcp(action: str = "connect", server_name: str = "", command: str = "
- **`toolkit_memory`** — def toolkit_memory(action: str, content: str = "", category: str = "general", pr
- **`toolkit_mode`** — def toolkit_mode(action: str, text: str = "", mode: str = ""):
- **`toolkit_notify`** — def toolkit_notify(title: str, message: str, urgency: str = "normal", duration: 
- **`toolkit_os_info`** — Internal: cached os info.
- **`toolkit_parallel_subtasks`** — 执行单个子任务（在独立线程中运行）。
- **`toolkit_pkg`** — def toolkit_pkg(action: str, packages: str = None, module: str = None):
- **`toolkit_plan`** — Internal: ensure plans dir.
- **`toolkit_proactive`** — def toolkit_proactive(action: str, content: str = "", priority: int = 2, goal_id
- **`toolkit_prompt_evolve`** — toolkit_prompt_evolve — 允许 Agent 管理自己的系统提示词版本
- **`toolkit_query_chat_history`** — def toolkit_query_chat_history(action="schema", conversation_id=None, keyword=No
- **`toolkit_question`** — def toolkit_question(
- **`toolkit_read_lines`** — def toolkit_read_lines(filename: str, start: int, end: int) -> str:
- **`toolkit_read_pyproject`** — 读取并解析 pyproject.toml，提取项目元数据
- **`toolkit_reflection`** — toolkit_reflection — 允许 Agent 主动触发自我反思
- **`toolkit_release_version`** — def toolkit_release_version(version: str, changes: list, changelog_section: str 
- **`toolkit_run_tests`** — def toolkit_run_tests(pattern: str = "test_*.py") -> dict:
- **`toolkit_save_file`** — def toolkit_save_file(path=None, content=None, chunks=None, append=False, encodi
- **`toolkit_scheduler`** — def toolkit_scheduler(action: str, **kwargs):
- **`toolkit_screenshot`** — def toolkit_screenshot(action: str, region: str = None, monitor: int = None, out
- **`toolkit_search`** — def toolkit_search(query: str, max_results: int = 10, lang: str = "", engine: st
- **`toolkit_self_evolve`** — def toolkit_self_evolve(file_path: str, description: str, old_code: str, new_cod
- **`toolkit_self_report`** — def toolkit_self_report() -> dict:
- **`toolkit_set_topic_title`** — def toolkit_set_topic_title(title: str) -> dict:
- **`toolkit_stream_save`** — def toolkit_stream_save(stream_id=None, target_path=None, append=False):
- **`toolkit_subconscious`** — def toolkit_subconscious(action: str, focus: str = None):
- **`toolkit_sudo_gui`** — def toolkit_sudo_gui(app: str, args: list, prompt: str = "请输入管理员密码"):
- **`toolkit_test_gui`** — def toolkit_test_gui(timeout: int = 30, debug: bool = True) -> dict:
- **`toolkit_todo`** — 获取当前 DB 连接（通过 session_ref → agent → db）
- **`toolkit_toggle_reasoning`** — def toolkit_toggle_reasoning(enable: bool = None) -> dict:
- **`toolkit_write_b64`** — def toolkit_write_b64(path: str, b64_content: str, append: bool = False):

## ⚙️ 自进化引擎

后台每小时自动运行：
- 🔍 工具使用分析 & 优化建议
- 📝 README.md 自动同步（本文件）
- 🎯 技能模式整理

> 最后更新: 2026-06-01 14:09

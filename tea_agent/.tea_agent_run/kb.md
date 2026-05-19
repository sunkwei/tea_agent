# tea_agent 项目知识库

> 自动生成: 2026-05-13 11:27
> 工具: ctags + AST + graphviz
>
> 符号: 0 唯一 · 函数: 589 · 类: 33 · 调用边: 3362

## 符号种类分布

| 种类 | 数量 |
|------|------|

## 模块索引 (68 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| __init__.py | 17 | — | — |
| agent_core.py | 539 | AgentCore, _RestartHandler | on_modified |
| basesession.py | 363 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| cli.py | 416 | TeaCLI | run, on_stream, on_status |
| config.py | 525 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| embedding_util.py | 354 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| gui_dialogs.py | 1090 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| logging_setup.py | 98 | — | setup_logging, set_debug |
| main_db_gui.py | 1651 | TkGUI | zoom_in, zoom_out, scroll_to_bottom |
| memory.py | 489 | MemoryManager | select_memories, format_memories, build_extraction_prompt |
| merge_db.py | 718 | DbMerger | merge, close, main |
| onlinesession.py | 846 | OnlineToolSession | update_tools, reset_session_state, chat_stream |
| prompt_manager.py | 282 | SystemPromptManager | initialize, current_prompt, current_version |
| reflection.py | 292 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| session_api.py | 321 | SessionAPIMixin | process_stream_response, reset_usage, reset_cheap_usage |
| session_memory.py | 187 | SessionMemoryMixin | trigger_memory_extraction, get_injected_memories, get_memory_stats |
| session_pipeline.py | 204 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| session_prompts.py | 53 | — | — |
| session_ref.py | 28 | — | get_session, set_session, get_agent |
| session_summarizer.py | 734 | SessionSummarizerMixin | generate_topic_summary_shared, count_user_msg, generate_topic_summary |
| session_tool.py | 232 | SessionToolMixin | — |
| skills\__init__.py | 347 | Skill, SkillManager | to_dict, get_instance, reset_instance |
| skills\desktop_automation\__init__.py | 26 | — | — |
| skills\file_system\__init__.py | 25 | — | — |
| skills\interaction\__init__.py | 21 | — | — |
| skills\memory_knowledge\__init__.py | 28 | — | — |
| skills\self_evolution\__init__.py | 33 | — | — |
| skills\utility\__init__.py | 19 | — | — |
| store.py | 1831 | Storage | create_topic, update_topic_title, update_topic_active |
| tea_agent.py | 321 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_main_cli.py | 291 | TeaCLI | chat, stream_cb, status_cb |
| tlk.py | 537 | Toolkit | meta_toolkit_reload, meta_toolkit_save, toolkit_reload |
| toolkit\__init__.py | 1 | — | — |
| toolkit\toolkit_build.py | 137 | — | toolkit_build, meta_toolkit_build |
| toolkit\toolkit_bump_version.py | 121 | — | toolkit_bump_version, meta_toolkit_bump_version |
| toolkit\toolkit_comment.py | 64 | — | toolkit_comment, meta_toolkit_comment |
| toolkit\toolkit_config.py | 132 | — | toolkit_config, meta_toolkit_config |
| toolkit\toolkit_date_diff.py | 63 | — | toolkit_date_diff, meta_toolkit_date_diff |
| toolkit\toolkit_dump_topic.py | 125 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| toolkit\toolkit_exec.py | 320 | — | toolkit_exec, meta_toolkit_exec |
| toolkit\toolkit_explr.py | 452 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| toolkit\toolkit_file.py | 117 | — | toolkit_file, scan_dir, meta_toolkit_file |
| toolkit\toolkit_gettime.py | 23 | — | toolkit_gettime, meta_toolkit_gettime |
| toolkit\toolkit_input.py | 197 | — | toolkit_input, meta_toolkit_input |
| toolkit\toolkit_kb.py | 174 | — | toolkit_kb, sanitize, rebuild_index |
| toolkit\toolkit_listen.py | 85 | — | toolkit_listen, meta_toolkit_listen, meta_toolkit_listen |
| toolkit\toolkit_lunar.py | 323 | — | toolkit_lunar, meta_toolkit_lunar |
| toolkit\toolkit_memory.py | 165 | — | toolkit_memory, meta_toolkit_memory |
| toolkit\toolkit_mode.py | 212 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| toolkit\toolkit_notify.py | 122 | — | toolkit_notify, meta_toolkit_notify |
| toolkit\toolkit_ocr.py | 249 | — | toolkit_ocr, meta_toolkit_ocr |
| toolkit\toolkit_os_info.py | 47 | — | toolkit_os_info, meta_toolkit_os_info |
| toolkit\toolkit_pkg.py | 152 | — | toolkit_pkg, meta_toolkit_pkg |
| toolkit\toolkit_proactive.py | 150 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| toolkit\toolkit_prompt_evolve.py | 126 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| toolkit\toolkit_reflection.py | 100 | — | toolkit_reflection, meta_toolkit_reflection |
| toolkit\toolkit_release_version.py | 116 | — | toolkit_release_version, meta_toolkit_release_version |
| toolkit\toolkit_run_tests.py | 80 | — | toolkit_run_tests, meta_toolkit_run_tests |
| toolkit\toolkit_screenshot.py | 234 | — | toolkit_screenshot, meta_toolkit_screenshot |
| toolkit\toolkit_search.py | 206 | — | toolkit_search, meta_toolkit_search |
| toolkit\toolkit_self_evolve.py | 270 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| toolkit\toolkit_self_report.py | 76 | — | toolkit_self_report, meta_toolkit_self_report |
| toolkit\toolkit_set_topic_title.py | 83 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| toolkit\toolkit_skill.py | 107 | — | toolkit_skill, meta_toolkit_skill |
| toolkit\toolkit_speak.py | 92 | — | toolkit_speak, meta_toolkit_speak, meta_toolkit_speak |
| toolkit\toolkit_subconscious.py | 727 | — | toolkit_subconscious, meta_toolkit_subconscious |
| toolkit\toolkit_sudo_gui.py | 86 | — | toolkit_sudo_gui, meta_toolkit_sudo_gui |
| toolkit\toolkit_toggle_reasoning.py | 51 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `get` | config.py:188 | 142 |
| `len` | ?:? | 139 |
| `append` | ?:? | 117 |
| `join` | ?:? | 97 |
| `execute` | session_pipeline.py:132 | 87 |
| `info` | ?:? | 85 |
| `str` | ?:? | 79 |
| `close` | tea_agent.py:293 | 64 |
| `cursor` | ?:? | 64 |
| `strip` | ?:? | 61 |
| `commit` | ?:? | 45 |
| `set` | config.py:194 | 37 |
| `fetchall` | ?:? | 37 |
| `warning` | ?:? | 36 |
| `split` | ?:? | 36 |
| `lower` | ?:? | 34 |
| `dict` | ?:? | 33 |
| `exists` | ?:? | 32 |
| `isinstance` | ?:? | 32 |
| `startswith` | ?:? | 32 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

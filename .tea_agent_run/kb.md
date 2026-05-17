# tea_agent 项目知识库

> 自动生成: 2026-05-17 15:21
> 工具: ctags + AST + graphviz
>
> 符号: 0 唯一 · 函数: 792 · 类: 76 · 调用边: 4440

## 符号种类分布

| 种类 | 数量 |
|------|------|

## 模块索引 (110 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| debug_init.py | 14 | — | — |
| make_index.py | 347 | — | should_skip_path, extract_py_symbols, build_index |
| tea_agent/__init__.py | 18 | — | — |
| tea_agent/_gui/__init__.py | 26 | — | — |
| tea_agent/_gui/_images.py | 125 | ImageHandler | attach, clear, show_popup |
| tea_agent/_gui/_interfaces.py | 74 | HtmlDisplay, TextDisplay, StatusDisplay | show_html, clear, append |
| tea_agent/_gui/_markdown.py | 350 | _TagChecker | handle_starttag, handle_endtag, get_result |
| tea_agent/_gui/_renderer.py | 428 | ChatRenderer | scroll_to_bottom |
| tea_agent/_gui/_tk_impl.py | 78 | HtmlFrameDisplay, ScrolledTextDisplay, LabelStatusDisplay | show_html, clear, append |
| tea_agent/_gui/_tray.py | 126 | TrayManager | start, stop |
| tea_agent/agent_core.py | 568 | AgentCore, _RestartHandler | on_modified |
| tea_agent/basesession.py | 550 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| tea_agent/cli.py | 416 | TeaCLI | run, on_stream, on_status |
| tea_agent/config.py | 607 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| tea_agent/embedding_util.py | 354 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| tea_agent/gui.py | 2050 | _TagChecker, StatusNotifierItemDBus, TkGUI | handle_starttag, handle_endtag, get_result |
| tea_agent/gui/dialogs/_common.py | 54 | — | — |
| tea_agent/gui/dialogs/memory_dialog.py | 251 | MemoryDialog | do_add |
| tea_agent/gui_dialogs.py | 1288 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| tea_agent/logging_setup.py | 98 | — | setup_logging, set_debug |
| tea_agent/main_db_gui.py | 2268 | _TagChecker, StatusNotifierItemDBus, TkGUI | handle_starttag, handle_endtag, get_result |
| tea_agent/memory.py | 723 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| tea_agent/merge_db.py | 718 | DbMerger | merge, close, main |
| tea_agent/onlinesession.py | 1257 | OnlineToolSession | update_tools, reset_session_state, chat_stream |
| tea_agent/project_memory.py | 127 | ProjectMemoryManager | add, get_all, search |
| tea_agent/prompt_manager.py | 282 | SystemPromptManager | initialize, current_prompt, current_version |
| tea_agent/reflection.py | 292 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| tea_agent/session_api.py | 333 | SessionAPIMixin | process_stream_response, reset_usage, reset_cheap_usage |
| tea_agent/session_memory.py | 220 | SessionMemoryMixin | trigger_memory_extraction, get_injected_memories, get_memory_stats |
| tea_agent/session_pipeline.py | 204 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| tea_agent/session_prompts.py | 53 | — | — |
| tea_agent/session_ref.py | 28 | — | get_session, set_session, get_agent |
| tea_agent/session_summarizer.py | 767 | SessionSummarizerMixin | generate_topic_summary_shared, count_user_msg, generate_topic_summary |
| tea_agent/session_tool.py | 232 | SessionToolMixin | — |
| tea_agent/skills/__init__.py | 371 | Skill, SkillManager | to_dict, get_instance, reset_instance |
| tea_agent/skills/desktop_automation/__init__.py | 26 | — | — |
| tea_agent/skills/file_system/__init__.py | 25 | — | — |
| tea_agent/skills/interaction/__init__.py | 21 | — | — |
| tea_agent/skills/memory_knowledge/__init__.py | 28 | — | — |
| tea_agent/skills/self_evolution/__init__.py | 33 | — | — |
| tea_agent/skills/utility/__init__.py | 19 | — | — |
| tea_agent/store/__init__.py | 40 | — | get_storage |
| tea_agent/store/_backup_conv.py | 4 | — | — |
| tea_agent/store/_base.py | 16 | StoreComponent | — |
| tea_agent/store/_check_time.py | 24 | — | — |
| tea_agent/store/_config.py | 54 | ConfigHistoryStore | add_config_change, get_config_history, get_config_changes_since |
| tea_agent/store/_conversations.py | 201 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| tea_agent/store/_core.py | 612 | Storage | save_msg, backup_now, close |
| tea_agent/store/_fix_all_inserts.py | 99 | — | — |
| tea_agent/store/_fix_inserts.py | 39 | — | — |
| tea_agent/store/_memories.py | 192 | MemoryStore | add_memory, update_memory, deactivate_memory |
| tea_agent/store/_prompts.py | 70 | PromptStore | add_system_prompt, get_latest_system_prompt, get_system_prompt_history |
| tea_agent/store/_reflections.py | 59 | ReflectionStore | add_reflection, get_recent_reflections, mark_reflection_applied |
| tea_agent/store/_scheduled_tasks.py | 225 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| tea_agent/store/_summaries.py | 155 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| tea_agent/store/_topics.py | 132 | TopicStore | create_topic, update_topic_title, update_topic_active |
| tea_agent/store/_vectors.py | 187 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tea_agent/store/fix_history_timezone.py | 96 | — | fix |
| tea_agent/store/fix_timezone.py | 53 | — | backup, fix_file |
| tea_agent/tea_agent.py | 330 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_agent/tea_main_cli.py | 320 | TeaCLI | chat, stream_cb, status_cb |
| tea_agent/tlk.py | 612 | Toolkit | meta_toolkit_reload, meta_toolkit_save, toolkit_reload |
| tea_agent/toolkit/__init__.py | 1 | — | — |
| tea_agent/toolkit/toolkit_build.py | 137 | — | toolkit_build, meta_toolkit_build |
| tea_agent/toolkit/toolkit_bump_version.py | 121 | — | toolkit_bump_version, meta_toolkit_bump_version |
| tea_agent/toolkit/toolkit_comment.py | 64 | — | toolkit_comment, meta_toolkit_comment |
| tea_agent/toolkit/toolkit_config.py | 132 | — | toolkit_config, meta_toolkit_config |
| tea_agent/toolkit/toolkit_date_diff.py | 63 | — | toolkit_date_diff, meta_toolkit_date_diff |
| tea_agent/toolkit/toolkit_dump_topic.py | 125 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| tea_agent/toolkit/toolkit_evolution_exp.py | 120 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| tea_agent/toolkit/toolkit_exec.py | 350 | — | toolkit_exec, meta_toolkit_exec |
| tea_agent/toolkit/toolkit_explr.py | 557 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| tea_agent/toolkit/toolkit_file.py | 134 | — | toolkit_file, scan_dir, meta_toolkit_file |
| tea_agent/toolkit/toolkit_gettime.py | 23 | — | toolkit_gettime, meta_toolkit_gettime |
| tea_agent/toolkit/toolkit_git_push_all_remotes.py | 40 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| tea_agent/toolkit/toolkit_input.py | 197 | — | toolkit_input, meta_toolkit_input |
| tea_agent/toolkit/toolkit_kb.py | 174 | — | toolkit_kb, sanitize, rebuild_index |
| tea_agent/toolkit/toolkit_listen.py | 85 | — | toolkit_listen, meta_toolkit_listen, meta_toolkit_listen |
| tea_agent/toolkit/toolkit_lunar.py | 323 | — | toolkit_lunar, meta_toolkit_lunar |
| tea_agent/toolkit/toolkit_memory.py | 165 | — | toolkit_memory, meta_toolkit_memory |
| tea_agent/toolkit/toolkit_mode.py | 212 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| tea_agent/toolkit/toolkit_notify.py | 122 | — | toolkit_notify, meta_toolkit_notify |
| tea_agent/toolkit/toolkit_ocr.py | 249 | — | toolkit_ocr, meta_toolkit_ocr |
| tea_agent/toolkit/toolkit_os_info.py | 47 | — | toolkit_os_info, meta_toolkit_os_info |
| tea_agent/toolkit/toolkit_pkg.py | 152 | — | toolkit_pkg, meta_toolkit_pkg |
| tea_agent/toolkit/toolkit_proactive.py | 150 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| tea_agent/toolkit/toolkit_prompt_evolve.py | 126 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| tea_agent/toolkit/toolkit_read_pyproject.py | 80 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| tea_agent/toolkit/toolkit_reflection.py | 100 | — | toolkit_reflection, meta_toolkit_reflection |
| tea_agent/toolkit/toolkit_release_version.py | 116 | — | toolkit_release_version, meta_toolkit_release_version |
| tea_agent/toolkit/toolkit_run_tests.py | 80 | — | toolkit_run_tests, meta_toolkit_run_tests |
| tea_agent/toolkit/toolkit_scheduler.py | 434 | — | toolkit_scheduler, parse_schedule, meta_toolkit_scheduler |
| tea_agent/toolkit/toolkit_screenshot.py | 234 | — | toolkit_screenshot, meta_toolkit_screenshot |
| tea_agent/toolkit/toolkit_search.py | 206 | — | toolkit_search, meta_toolkit_search |
| tea_agent/toolkit/toolkit_self_evolve.py | 260 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| tea_agent/toolkit/toolkit_self_report.py | 76 | — | toolkit_self_report, meta_toolkit_self_report |
| tea_agent/toolkit/toolkit_set_topic_title.py | 83 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| tea_agent/toolkit/toolkit_skill.py | 107 | — | toolkit_skill, meta_toolkit_skill |
| tea_agent/toolkit/toolkit_speak.py | 92 | — | toolkit_speak, meta_toolkit_speak, meta_toolkit_speak |
| tea_agent/toolkit/toolkit_subconscious.py | 875 | — | toolkit_subconscious, meta_toolkit_subconscious |
| tea_agent/toolkit/toolkit_sudo_gui.py | 86 | — | toolkit_sudo_gui, meta_toolkit_sudo_gui |
| tea_agent/toolkit/toolkit_toggle_reasoning.py | 51 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| test/test_l3_history.py | 196 | TestStorageLevel2, TestStorageLevel3, TestKeywordRelevance | setUp, test_push_and_get_level2, test_level2_max_5 |
| test_main.py | 92 | — | test_config_loads, test_storage_init, test_tea_cli_import |
| test_session.py | 100 | — | test_toolkit, test_online_session, test_reset_and_iter |
| tests/__init__.py | 1 | — | — |
| tests/conftest.py | 61 | — | tmp_db_path, storage, tmp_yaml_config |
| tests/test_config.py | 273 | TestModelConfig, TestPathsConfig, TestMqttConfig | test_default_not_configured, test_configured_when_all_set, test_not_configured_when_partial |
| tests/test_store.py | 486 | TestStorageInit, TestTopicCRUD, TestMessageCRUD | test_init_creates_db_file, test_init_creates_all_tables, test_init_enables_wal_mode |
| tests/test_tea_agent_dual.py | 86 | — | extract_final_reply, main |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 193 |
| `get` | tea_agent/config.py:221 | 171 |
| `append` | tea_agent/_gui/_tk_impl.py:31 | 145 |
| `join` | ?:? | 122 |
| `execute` | tea_agent/session_pipeline.py:132 | 102 |
| `info` | ?:? | 101 |
| `str` | ?:? | 95 |
| `close` | tea_agent/store/_core.py:595 | 79 |
| `strip` | ?:? | 76 |
| `cursor` | ?:? | 74 |
| `isinstance` | ?:? | 54 |
| `commit` | ?:? | 54 |
| `warning` | ?:? | 51 |
| `open` | ?:? | 48 |
| `split` | ?:? | 47 |
| `set` | tea_agent/config.py:227 | 46 |
| `exists` | ?:? | 44 |
| `lower` | ?:? | 43 |
| `fetchall` | ?:? | 43 |
| `startswith` | ?:? | 42 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

# tea_agent 项目知识库

> 自动生成: 2026-05-27 15:43
> 工具: ctags + AST + graphviz
>
> 符号: 0 唯一 · 函数: 904 · 类: 72 · 调用边: 5344

## 符号种类分布

| 种类 | 数量 |
|------|------|

## 模块索引 (110 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| debug_init.py | 14 | — | — |
| demo\__init__.py | 1 | — | — |
| demo\csi300_predictor.py | 1236 | CurveFitter, Vectorizer, CSIPredictor | init_db, save_prediction, update_actual_outcome |
| demo\news_CSI300.py | 278 | — | init_db, save_news, save_index |
| make_index.py | 347 | — | should_skip_path, extract_py_symbols, build_index |
| tea_agent\__init__.py | 15 | — | — |
| tea_agent\_gui\__init__.py | 4 | — | — |
| tea_agent\_gui\_fonts.py | 85 | — | — |
| tea_agent\_gui\_images.py | 130 | ImageHandler | attach, clear, show_popup |
| tea_agent\_gui\_markdown.py | 428 | _TagChecker | handle_starttag, handle_endtag, get_result |
| tea_agent\_gui\_renderer.py | 464 | ChatRenderer | scroll_to_bottom |
| tea_agent\_gui\_stream_manager.py | 161 | StreamManager | safe_stream, safe_log, safe_log_tool |
| tea_agent\_gui\_topic_manager.py | 364 | TopicManager | clear_chat, auto_new_topic, new_topic |
| tea_agent\_gui\_topic_summary.py | 100 | — | — |
| tea_agent\_gui\_tray.py | 136 | TrayManager | start, stop |
| tea_agent\_gui\_ui_builder.py | 155 | UIBuilder | build |
| tea_agent\agent_core.py | 429 | AgentCore | — |
| tea_agent\basesession.py | 621 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| tea_agent\cli.py | 449 | TeaCLI | run, on_stream, on_status |
| tea_agent\config.py | 578 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| tea_agent\embedding_util.py | 346 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| tea_agent\gui.py | 1150 | StatusNotifierItemDBus, TkGUI | Title, Id, Status |
| tea_agent\gui_dialogs.py | 1318 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| tea_agent\logging_setup.py | 95 | — | setup_logging, set_debug |
| tea_agent\lsp\__init__.py | 12 | — | — |
| tea_agent\lsp\lsp_engine.py | 381 | — | diagnose, semantic_diagnose, completion |
| tea_agent\lsp\ts_analyzer.py | 441 | — | parse_file, impact_analysis, build_dependency_graph |
| tea_agent\memory.py | 711 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| tea_agent\merge_db.py | 723 | DbMerger | merge, close, main |
| tea_agent\onlinesession.py | 1403 | OnlineToolSession | messages, messages, model |
| tea_agent\project_memory.py | 130 | ProjectMemoryManager | add, get_all, search |
| tea_agent\prompt_manager.py | 283 | SystemPromptManager | initialize, current_prompt, current_version |
| tea_agent\reflection.py | 291 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| tea_agent\session\__init__.py | 1 | — | — |
| tea_agent\session_api_component.py | 270 | APIComponent | name, initialize, create_chat_stream |
| tea_agent\session_context.py | 103 | SessionContext, SessionComponent | initialize, name |
| tea_agent\session_memory_component.py | 202 | MemoryComponent | name, initialize, inject_memories |
| tea_agent\session_pipeline.py | 203 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| tea_agent\session_prompts.py | 53 | — | — |
| tea_agent\session_ref.py | 23 | — | get_session, set_session, get_agent |
| tea_agent\session_summarizer_component.py | 197 | SummarizerComponent | name, initialize, summarize_old_history |
| tea_agent\session_tool_component.py | 196 | ToolComponent | name, initialize, build_tools |
| tea_agent\store\__init__.py | 38 | — | get_storage |
| tea_agent\store\_base.py | 20 | StoreComponent | — |
| tea_agent\store\_config.py | 72 | ConfigHistoryStore | add_config_change, get_config_history, get_config_changes_since |
| tea_agent\store\_conversations.py | 236 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| tea_agent\store\_core.py | 676 | Storage | save_msg, backup_now, close |
| tea_agent\store\_memories.py | 241 | MemoryStore | add_memory, update_memory, deactivate_memory |
| tea_agent\store\_prompts.py | 92 | PromptStore | add_system_prompt, get_latest_system_prompt, get_system_prompt_history |
| tea_agent\store\_reflections.py | 77 | ReflectionStore | add_reflection, get_recent_reflections, mark_reflection_applied |
| tea_agent\store\_scheduled_tasks.py | 221 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| tea_agent\store\_summaries.py | 245 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| tea_agent\store\_topics.py | 194 | TopicStore | create_topic, update_topic_title, update_topic_active |
| tea_agent\store\_vectors.py | 237 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tea_agent\tea_agent.py | 330 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_agent\tea_main_cli.py | 367 | TeaCLI | chat, stream_cb, status_cb |
| tea_agent\tlk.py | 607 | Toolkit | meta_toolkit_reload, meta_toolkit_save, toolkit_reload |
| tea_agent\toolkit\__init__.py | 1 | — | — |
| tea_agent\toolkit\subconscious\__init__.py | 1 | — | — |
| tea_agent\toolkit\toolkit_build.py | 136 | — | toolkit_build, meta_toolkit_build |
| tea_agent\toolkit\toolkit_bump_version.py | 120 | — | toolkit_bump_version, meta_toolkit_bump_version |
| tea_agent\toolkit\toolkit_comment.py | 63 | — | toolkit_comment, meta_toolkit_comment |
| tea_agent\toolkit\toolkit_config.py | 128 | — | toolkit_config, meta_toolkit_config |
| tea_agent\toolkit\toolkit_date_diff.py | 63 | — | toolkit_date_diff, meta_toolkit_date_diff |
| tea_agent\toolkit\toolkit_diff.py | 364 | — | toolkit_diff, meta_toolkit_diff |
| tea_agent\toolkit\toolkit_dump_topic.py | 124 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| tea_agent\toolkit\toolkit_edit.py | 437 | — | toolkit_edit, meta_toolkit_edit |
| tea_agent\toolkit\toolkit_evolution_exp.py | 128 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| tea_agent\toolkit\toolkit_exec.py | 306 | — | toolkit_exec, meta_toolkit_exec |
| tea_agent\toolkit\toolkit_explr.py | 719 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| tea_agent\toolkit\toolkit_file.py | 133 | — | toolkit_file, scan_dir, meta_toolkit_file |
| tea_agent\toolkit\toolkit_gettime.py | 23 | — | toolkit_gettime, meta_toolkit_gettime |
| tea_agent\toolkit\toolkit_git_push_all_remotes.py | 40 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| tea_agent\toolkit\toolkit_input.py | 192 | — | toolkit_input, meta_toolkit_input |
| tea_agent\toolkit\toolkit_kb.py | 195 | — | toolkit_kb, sanitize, rebuild_index |
| tea_agent\toolkit\toolkit_lsp.py | 85 | — | toolkit_lsp, meta_toolkit_lsp |
| tea_agent\toolkit\toolkit_lunar.py | 336 | — | toolkit_lunar, meta_toolkit_lunar |
| tea_agent\toolkit\toolkit_mcp.py | 384 | — | toolkit_mcp, meta_toolkit_mcp |
| tea_agent\toolkit\toolkit_memory.py | 164 | — | toolkit_memory, meta_toolkit_memory |
| tea_agent\toolkit\toolkit_mode.py | 230 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| tea_agent\toolkit\toolkit_notify.py | 124 | — | toolkit_notify, meta_toolkit_notify |
| tea_agent\toolkit\toolkit_os_info.py | 46 | — | toolkit_os_info, meta_toolkit_os_info |
| tea_agent\toolkit\toolkit_pkg.py | 150 | — | toolkit_pkg, meta_toolkit_pkg |
| tea_agent\toolkit\toolkit_plan.py | 455 | — | toolkit_plan, meta_toolkit_plan |
| tea_agent\toolkit\toolkit_proactive.py | 156 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| tea_agent\toolkit\toolkit_prompt_evolve.py | 124 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| tea_agent\toolkit\toolkit_read_pyproject.py | 80 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| tea_agent\toolkit\toolkit_reflection.py | 98 | — | toolkit_reflection, meta_toolkit_reflection |
| tea_agent\toolkit\toolkit_release_version.py | 116 | — | toolkit_release_version, meta_toolkit_release_version |
| tea_agent\toolkit\toolkit_run_tests.py | 79 | — | toolkit_run_tests, meta_toolkit_run_tests |
| tea_agent\toolkit\toolkit_scheduler.py | 453 | — | toolkit_scheduler, parse_schedule, meta_toolkit_scheduler |
| tea_agent\toolkit\toolkit_screenshot.py | 241 | — | toolkit_screenshot, meta_toolkit_screenshot |
| tea_agent\toolkit\toolkit_search.py | 424 | — | toolkit_search, meta_toolkit_search |
| tea_agent\toolkit\toolkit_self_evolve.py | 330 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| tea_agent\toolkit\toolkit_self_report.py | 75 | — | toolkit_self_report, meta_toolkit_self_report |
| tea_agent\toolkit\toolkit_set_topic_title.py | 78 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| tea_agent\toolkit\toolkit_subconscious.py | 1003 | — | toolkit_subconscious, meta_toolkit_subconscious |
| tea_agent\toolkit\toolkit_sudo_gui.py | 81 | — | toolkit_sudo_gui, meta_toolkit_sudo_gui |
| tea_agent\toolkit\toolkit_test_gui.py | 150 | — | toolkit_test_gui, meta_toolkit_test_gui |
| tea_agent\toolkit\toolkit_todo.py | 266 | — | toolkit_todo, meta_toolkit_todo |
| tea_agent\toolkit\toolkit_toggle_reasoning.py | 50 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| tea_agent\tui.py | 620 | _TUIAgentCore, TeaTUI, _SendTextArea | on_stream, on_status, compose |
| test_main.py | 92 | — | test_config_loads, test_storage_init, test_tea_cli_import |
| test_session.py | 100 | — | test_toolkit, test_online_session, test_reset_and_iter |
| tests\__init__.py | 1 | — | — |
| tests\conftest.py | 61 | — | tmp_db_path, storage, tmp_yaml_config |
| tests\test_config.py | 273 | TestModelConfig, TestPathsConfig, TestMqttConfig | test_default_not_configured, test_configured_when_all_set, test_not_configured_when_partial |
| tests\test_render_timing.py | 148 | TestRenderTiming | setUpClass, test_render_before_pipeline, test_show_raw_check_btn_before_pipeline |
| tests\test_store.py | 486 | TestStorageInit, TestTopicCRUD, TestMessageCRUD | test_init_creates_db_file, test_init_creates_all_tables, test_init_enables_wal_mode |
| tests\test_tea_agent_dual.py | 86 | — | extract_final_reply, main |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 223 |
| `get` | tea_agent\config.py:211 | 196 |
| `append` | ?:? | 179 |
| `join` | ?:? | 145 |
| `str` | ?:? | 137 |
| `execute` | tea_agent\session_pipeline.py:131 | 121 |
| `info` | ?:? | 110 |
| `close` | tea_agent\store\_core.py:658 | 97 |
| `cursor` | ?:? | 93 |
| `strip` | ?:? | 79 |
| `open` | ?:? | 67 |
| `commit` | ?:? | 67 |
| `startswith` | ?:? | 60 |
| `isinstance` | ?:? | 56 |
| `set` | tea_agent\config.py:217 | 56 |
| `warning` | ?:? | 56 |
| `split` | ?:? | 55 |
| `exists` | ?:? | 51 |
| `fetchall` | ?:? | 45 |
| `enumerate` | ?:? | 42 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

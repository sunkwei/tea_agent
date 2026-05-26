# tea_agent 项目知识库

> 自动生成: 2026-05-26 07:11
> 工具: ctags + AST + graphviz
>
> 符号: 0 唯一 · 函数: 1156 · 类: 117 · 调用边: 6291

## 符号种类分布

| 种类 | 数量 |
|------|------|

## 模块索引 (134 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| _fetch_deepseek_docs.py | 43 | — | — |
| _fetch_deepseek_guides.py | 34 | — | — |
| _verify_os.py | 32 | — | — |
| debug_init.py | 14 | — | — |
| demo\__init__.py | 1 | — | — |
| demo\csi300_predictor.py | 1236 | CurveFitter, Vectorizer, CSIPredictor | init_db, save_prediction, update_actual_outcome |
| demo\news_CSI300.py | 278 | — | init_db, save_news, save_index |
| make_index.py | 347 | — | should_skip_path, extract_py_symbols, build_index |
| tea_agent\__init__.py | 14 | — | — |
| tea_agent\_gui\__init__.py | 3 | — | — |
| tea_agent\_gui\_fonts.py | 89 | — | — |
| tea_agent\_gui\_images.py | 143 | ImageHandler | attach, clear, show_popup |
| tea_agent\_gui\_markdown.py | 446 | _TagChecker | handle_starttag, handle_endtag, get_result |
| tea_agent\_gui\_renderer.py | 459 | ChatRenderer | scroll_to_bottom |
| tea_agent\_gui\_stream_manager.py | 207 | StreamManager | safe_stream, safe_log, safe_log_tool |
| tea_agent\_gui\_topic_manager.py | 441 | TopicManager | clear_chat, auto_new_topic, new_topic |
| tea_agent\_gui\_topic_summary.py | 93 | — | — |
| tea_agent\_gui\_tray.py | 137 | TrayManager | start, stop |
| tea_agent\_gui\_ui_builder.py | 143 | UIBuilder | build |
| tea_agent\agent_core.py | 451 | AgentCore | — |
| tea_agent\basesession.py | 576 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| tea_agent\cli.py | 467 | TeaCLI | run, on_stream, on_status |
| tea_agent\config.py | 730 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| tea_agent\embedding_util.py | 431 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| tea_agent\gui.py | 1283 | StatusNotifierItemDBus, TkGUI | Title, Id, Status |
| tea_agent\gui_dialogs.py | 1290 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| tea_agent\logging_setup.py | 97 | — | setup_logging, set_debug |
| tea_agent\lsp\__init__.py | 12 | — | — |
| tea_agent\lsp\lsp_check.py | 131 | — | run_lsp_check |
| tea_agent\lsp\lsp_engine.py | 367 | — | diagnose, completion, goto_definition |
| tea_agent\lsp\ts_analyzer.py | 1021 | _MetricsVisitor, _CallCollector, _Inner | parse_file, impact_analysis, build_dependency_graph |
| tea_agent\memory.py | 729 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| tea_agent\merge_db.py | 716 | DbMerger | merge, close, main |
| tea_agent\multi_agent\__init__.py | 44 | — | — |
| tea_agent\multi_agent\agent_pool.py | 597 | AgentPool, LiteAgentPool | register_agent_type, create_agent, get_agent |
| tea_agent\multi_agent\lite_agent.py | 685 | LiteAgentModelConfig, LiteAgentConfig, ToolRegistry | is_configured, register, unregister |
| tea_agent\multi_agent\orchestrator.py | 764 | MultiAgentOrchestrator, LiteOrchestrator | register_agent_type, execute, execute_single |
| tea_agent\multi_agent\result_aggregator.py | 272 | ResultAggregator | aggregate, summarize_result, merge_code_results |
| tea_agent\multi_agent\sub_agent.py | 387 | SubAgentConfig, SubAgentWrapper | initialize, run, run_async |
| tea_agent\multi_agent\task_decomposer.py | 401 | SubTask, TaskDecomposer | to_dict, from_dict, decompose |
| tea_agent\onlinesession.py | 1596 | OnlineToolSession | messages, messages, model |
| tea_agent\project_memory.py | 172 | ProjectMemoryManager | add, get_all, search |
| tea_agent\prompt_manager.py | 312 | SystemPromptManager | initialize, current_prompt, current_version |
| tea_agent\reflection.py | 346 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| tea_agent\session\__init__.py | 1 | — | — |
| tea_agent\session_api_component.py | 334 | APIComponent | name, initialize, create_chat_stream |
| tea_agent\session_context.py | 107 | SessionContext, SessionComponent | initialize, name |
| tea_agent\session_memory_component.py | 245 | MemoryComponent | name, initialize, inject_memories |
| tea_agent\session_pipeline.py | 233 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| tea_agent\session_prompts.py | 44 | — | — |
| tea_agent\session_ref.py | 32 | — | get_session, set_session, get_agent |
| tea_agent\session_summarizer_component.py | 210 | SummarizerComponent | name, initialize, summarize_old_history |
| tea_agent\session_tool_component.py | 265 | ToolComponent | name, initialize, build_tools |
| tea_agent\skills\__init__.py | 440 | Skill, SkillManager | to_dict, get_instance, reset_instance |
| tea_agent\skills\file_system\__init__.py | 26 | — | — |
| tea_agent\skills\interaction\__init__.py | 21 | — | — |
| tea_agent\skills\memory_knowledge\__init__.py | 28 | — | — |
| tea_agent\skills\self_evolution\__init__.py | 33 | — | — |
| tea_agent\skills\todo_workflow\__init__.py | 23 | — | — |
| tea_agent\skills\utility\__init__.py | 19 | — | — |
| tea_agent\store\__init__.py | 42 | — | get_storage |
| tea_agent\store\_base.py | 25 | StoreComponent | — |
| tea_agent\store\_config.py | 72 | ConfigHistoryStore | add_config_change, get_config_history, get_config_changes_since |
| tea_agent\store\_conversations.py | 284 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| tea_agent\store\_core.py | 663 | Storage | save_msg, backup_now, close |
| tea_agent\store\_memories.py | 254 | MemoryStore | add_memory, update_memory, deactivate_memory |
| tea_agent\store\_prompts.py | 102 | PromptStore | add_system_prompt, get_latest_system_prompt, get_system_prompt_history |
| tea_agent\store\_reflections.py | 82 | ReflectionStore | add_reflection, get_recent_reflections, mark_reflection_applied |
| tea_agent\store\_scheduled_tasks.py | 286 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| tea_agent\store\_summaries.py | 272 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| tea_agent\store\_topics.py | 213 | TopicStore | create_topic, update_topic_title, update_topic_active |
| tea_agent\store\_vectors.py | 246 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tea_agent\tea_agent.py | 352 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_agent\tea_main_cli.py | 365 | TeaCLI | chat, stream_cb, status_cb |
| tea_agent\tlk.py | 461 | Toolkit | meta_toolkit_save, toolkit_save_impl, call_tool |
| tea_agent\token_utils.py | 223 | — | estimate_tokens, estimate_message_tokens, estimate_text_tokens |
| tea_agent\toolkit\__init__.py | 0 | — | — |
| tea_agent\toolkit\subconscious\__init__.py | 1 | — | — |
| tea_agent\toolkit\tool_loader.py | 130 | ToolLoader | check_meta, reload_all |
| tea_agent\toolkit\toolkit_config.py | 129 | — | toolkit_config, meta_toolkit_config |
| tea_agent\toolkit\toolkit_date_diff.py | 62 | — | toolkit_date_diff, meta_toolkit_date_diff |
| tea_agent\toolkit\toolkit_delegate.py | 140 | — | set_orchestrator, get_orchestrator, toolkit_delegate |
| tea_agent\toolkit\toolkit_diff.py | 459 | — | toolkit_diff, meta_toolkit_diff |
| tea_agent\toolkit\toolkit_dump_topic.py | 126 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| tea_agent\toolkit\toolkit_edit.py | 480 | — | toolkit_edit, meta_toolkit_edit |
| tea_agent\toolkit\toolkit_evolution_exp.py | 136 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| tea_agent\toolkit\toolkit_exec.py | 334 | — | toolkit_exec, meta_toolkit_exec |
| tea_agent\toolkit\toolkit_explr.py | 754 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| tea_agent\toolkit\toolkit_file.py | 139 | — | toolkit_file, scan_dir, meta_toolkit_file |
| tea_agent\toolkit\toolkit_gettime.py | 32 | — | toolkit_gettime, meta_toolkit_gettime |
| tea_agent\toolkit\toolkit_git_push_all_remotes.py | 50 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| tea_agent\toolkit\toolkit_kb.py | 201 | — | toolkit_kb, sanitize, rebuild_index |
| tea_agent\toolkit\toolkit_lsp.py | 85 | — | toolkit_lsp, meta_toolkit_lsp |
| tea_agent\toolkit\toolkit_lunar.py | 353 | — | toolkit_lunar, meta_toolkit_lunar |
| tea_agent\toolkit\toolkit_mcp.py | 397 | — | toolkit_mcp, meta_toolkit_mcp |
| tea_agent\toolkit\toolkit_memory.py | 242 | — | toolkit_memory, meta_toolkit_memory |
| tea_agent\toolkit\toolkit_mode.py | 231 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| tea_agent\toolkit\toolkit_notify.py | 121 | — | toolkit_notify, meta_toolkit_notify |
| tea_agent\toolkit\toolkit_os_info.py | 56 | — | toolkit_os_info, meta_toolkit_os_info |
| tea_agent\toolkit\toolkit_pkg.py | 168 | — | toolkit_pkg, meta_toolkit_pkg |
| tea_agent\toolkit\toolkit_plan.py | 457 | — | meta_toolkit_plan, toolkit_plan |
| tea_agent\toolkit\toolkit_proactive.py | 170 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| tea_agent\toolkit\toolkit_prompt_evolve.py | 127 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| tea_agent\toolkit\toolkit_quality_gate.py | 274 | — | toolkit_quality_gate, meta_toolkit_quality_gate |
| tea_agent\toolkit\toolkit_read_pyproject.py | 83 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| tea_agent\toolkit\toolkit_reflection.py | 101 | — | toolkit_reflection, meta_toolkit_reflection |
| tea_agent\toolkit\toolkit_release.py | 290 | — | toolkit_release, meta_toolkit_release |
| tea_agent\toolkit\toolkit_run_tests.py | 78 | — | toolkit_run_tests, meta_toolkit_run_tests |
| tea_agent\toolkit\toolkit_scheduler.py | 449 | — | toolkit_scheduler, parse_schedule, meta_toolkit_scheduler |
| tea_agent\toolkit\toolkit_search.py | 440 | — | toolkit_search, meta_toolkit_search |
| tea_agent\toolkit\toolkit_self_evolve.py | 249 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| tea_agent\toolkit\toolkit_self_report.py | 77 | — | toolkit_self_report, meta_toolkit_self_report |
| tea_agent\toolkit\toolkit_set_topic_title.py | 76 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| tea_agent\toolkit\toolkit_skill.py | 104 | — | toolkit_skill, meta_toolkit_skill |
| tea_agent\toolkit\toolkit_static.py | 192 | — | meta_toolkit_static, toolkit_static |
| tea_agent\toolkit\toolkit_sub_agent.py | 163 | — | toolkit_sub_agent_report, toolkit_sub_agent_status, clear_sub_agent_reports |
| tea_agent\toolkit\toolkit_subconscious.py | 1247 | — | toolkit_subconscious, meta_toolkit_subconscious |
| tea_agent\toolkit\toolkit_test_gui.py | 144 | — | toolkit_test_gui, meta_toolkit_test_gui |
| tea_agent\toolkit\toolkit_todo.py | 477 | — | toolkit_todo, meta_toolkit_todo |
| tea_agent\toolkit\toolkit_toggle_reasoning.py | 49 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| tea_agent\tools\refactor_comments.py | 435 | BodyFinder, DocProcessor | get_function_body_ranges, visit_FunctionDef, strip_inline_comments |
| tea_agent\tui.py | 751 | _TUIAgentCore, TeaTUI, _SendTextArea | on_stream, on_status, action_send_from_input |
| test_cleanup_final.py | 13 | — | test_cleanup_final |
| test_main.py | 92 | — | test_config_loads, test_storage_init, test_tea_cli_import |
| test_multi_agent.py | 353 | — | test_imports, test_sub_agent_config, test_subtask |
| test_session.py | 100 | — | test_toolkit, test_online_session, test_reset_and_iter |
| tests\__init__.py | 1 | — | — |
| tests\conftest.py | 61 | — | tmp_db_path, storage, tmp_yaml_config |
| tests\test_config.py | 273 | TestModelConfig, TestPathsConfig, TestMqttConfig | test_default_not_configured, test_configured_when_all_set, test_not_configured_when_partial |
| tests\test_lite_agent_e2e.py | 307 | TestLiteAgentE2E, TestOrchestratorE2E, TestTaskDecomposerIntegration | setUp, echo_tool, test_lite_agent_with_tool_call |
| tests\test_multi_agent.py | 859 | TestSubAgentConfig, TestTaskDecomposer, TestSubTask | test_default_config, test_custom_config, setUp |
| tests\test_render_timing.py | 148 | TestRenderTiming | setUpClass, test_render_before_pipeline, test_show_raw_check_btn_before_pipeline |
| tests\test_store.py | 486 | TestStorageInit, TestTopicCRUD, TestMessageCRUD | test_init_creates_db_file, test_init_creates_all_tables, test_init_enables_wal_mode |
| tests\test_tea_agent_dual.py | 86 | — | extract_final_reply, main |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 295 |
| `append` | ?:? | 233 |
| `get` | tea_agent\config.py:347 | 232 |
| `join` | ?:? | 165 |
| `str` | ?:? | 154 |
| `execute` | tea_agent\multi_agent\orchestrator.py:564 | 128 |
| `info` | ?:? | 126 |
| `close` | tea_agent\store\_core.py:644 | 100 |
| `cursor` | ?:? | 95 |
| `strip` | ?:? | 83 |
| `open` | ?:? | 70 |
| `set` | tea_agent\config.py:359 | 70 |
| `commit` | ?:? | 69 |
| `isinstance` | ?:? | 65 |
| `warning` | ?:? | 65 |
| `startswith` | ?:? | 62 |
| `split` | ?:? | 55 |
| `exists` | ?:? | 51 |
| `enumerate` | ?:? | 47 |
| `fetchall` | ?:? | 46 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

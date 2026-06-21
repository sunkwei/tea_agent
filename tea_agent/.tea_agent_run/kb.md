# tea_agent 项目知识库

> 自动生成: 2026-06-21 10:14
> 工具: ctags + AST + graphviz
>
> 符号: 0 唯一 · 函数: 1623 · 类: 173 · 调用边: 8178

## 符号种类分布

| 种类 | 数量 |
|------|------|

## 模块索引 (178 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| __init__.py | 17 | — | — |
| _gui/__init__.py | 4 | — | — |
| _gui/_fonts.py | 171 | — | — |
| _gui/_gen_icon.py | 96 | — | generate_icon |
| _gui/_images.py | 130 | ImageHandler | attach, clear, show_popup |
| _gui/_markdown.py | 510 | _TagChecker | handle_starttag, handle_endtag, get_result |
| _gui/_renderer.py | 482 | ChatRenderer | scroll_to_bottom |
| _gui/_stream_manager.py | 161 | StreamManager | safe_stream, safe_log, safe_log_tool |
| _gui/_topic_manager.py | 368 | TopicManager | clear_chat, auto_new_topic, new_topic |
| _gui/_topic_summary.py | 109 | — | — |
| _gui/_tray.py | 159 | TrayManager | start, stop |
| _gui/_ui_builder.py | 183 | UIBuilder | build |
| agent.py | 643 | Agent | toolkit_save, toolkit_reload, chat |
| agent_background.py | 54 | — | start_self_evolve_thread, start_scheduler |
| agent_pipeline.py | 80 | — | do_async_summaries, l2_to_l3_summary, auto_summary |
| auto_fix.py | 275 | FixResult, AutoFixAgent | to_dict, scan, fix |
| basesession.py | 618 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| cli.py | 501 | TeaCLI | run, run_oneshot, on_stream |
| config.py | 592 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, supports_vision, resolve |
| demo/__init__.py | 1 | — | — |
| demo/csi300_predictor.py | 1236 | CurveFitter, Vectorizer, CSIPredictor | init_db, save_prediction, update_actual_outcome |
| demo/news_CSI300.py | 279 | — | init_db, save_news, save_index |
| demo/snake/__init__.py | 1 | — | — |
| demo/snake/engine.py | 371 | Direction, Position, Snake | opposite, all, manhattan |
| demo/snake/main.py | 138 | — | parse_args, main |
| demo/snake/renderer.py | 288 | Renderer | run, user_quit, make_human_strategy |
| demo/snake/strategies.py | 251 | — | random_strategy, greedy_strategy, safe_greedy_strategy |
| demo/snake/test_headless.py | 100 | — | test_basic, test_head_collision, test_wall_death |
| demo/tetris/generate_tetris_data.py | 229 | HeadlessTetrisGame | build_state_image, evaluate_board, simulate_landing |
| demo/tetris/run_tetris.py | 31 | — | — |
| demo/tetris/test_tetris.py | 136 | — | test_game_initialization, test_piece_movement, test_piece_rotation |
| demo/tetris/test_tetris_simple.py | 95 | — | test_game_logic |
| demo/tetris/tetris_ansi.py | 831 | ANSIHelper, InputHandler, TetrisGame | clear_screen, move_home, move_cursor |
| demo/tetris/tetris_console.py | 467 | TetrisGame | run, main |
| demo/tetris/train_tetris_cnn.py | 154 | — | build_light_cnn, plot_history, main |
| embedding_util.py | 346 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| evaluation/__init__.py | 19 | — | — |
| evaluation/task_evaluator.py | 442 | EvalResult, TaskEvaluator | to_dict, evaluate |
| gui.py | 1190 | TkGUI | generating, generating, zoom_in |
| gui_dialogs.py | 1423 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| litesession.py | 333 | LiteSession, SimpleFunction, SimpleToolCall | chat, interrupt, close |
| logging_setup.py | 95 | — | setup_logging, set_debug |
| lsp/__init__.py | 12 | — | — |
| lsp/lsp_engine.py | 597 | — | diagnose, semantic_diagnose, completion |
| lsp/symbol_index.py | 344 | SymbolIndex | build_index, search_by_name, search_by_file |
| lsp/ts_analyzer.py | 441 | — | parse_file, impact_analysis, build_dependency_graph |
| memory.py | 951 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| merge_db.py | 691 | DbMerger | merge, close, main |
| multi_agent/__init__.py | 23 | — | — |
| multi_agent/dispatcher.py | 340 | TaskStatus, SubTask, Dispatcher | dispatch, visualize |
| multi_agent/lite_agent.py | 147 | LiteAgent | execute_sync, execute_with_context |
| onlinesession.py | 1398 | SessionContext, SessionComponent, APIComponent | analyze_intent, detect_mode, extract_mode |
| project_memory.py | 130 | ProjectMemoryManager | add, get_all, search |
| prompt_manager.py | 283 | SystemPromptManager | initialize, current_prompt, current_version |
| reflection.py | 301 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| scheduler_storage.py | 274 | SchedulerStorage | save_script, get_script, list_scripts |
| scripts/ensure_self_evolve.py | 42 | — | ensure_running |
| session/__init__.py | 8 | — | — |
| session/_history_builder.py | 565 | — | estimate_tokens, estimate_messages_tokens, to_multimodal |
| session/_json_sanitizer.py | 188 | — | try_fix_truncated_json, sanitize_api_messages |
| session/_os_info_injector.py | 194 | — | inject_os_info |
| session/_params.py | 41 | — | get_cheap_params |
| session/_tool_loop_runner.py | 464 | LoopDetector | check_and_record, reset, execute_tool_loop |
| session_api_component.py | 1 | — | — |
| session_context.py | 1 | — | — |
| session_memory_component.py | 470 | MemoryComponent, AutoMemoryExtractor | name, initialize, inject_memories |
| session_pipeline.py | 178 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| session_prompts.py | 9 | — | — |
| session_ref.py | 85 | — | get_session, set_session, get_agent |
| session_summarizer_component.py | 1 | — | — |
| session_tool_component.py | 1 | — | — |
| skills/__init__.py | 28 | — | — |
| skills/skill_crystallize.py | 381 | Skill, SkillCrystallizer | success_rate, confidence, crystallize |
| skills/skill_registry.py | 417 | SkillRegistry | register, get_skill, list_all |
| store/__init__.py | 23 | — | get_storage |
| store/_component.py | 119 | DB, Cursor, StoreComponent | cursor, execute, conn |
| store/_conversations.py | 272 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| store/_core.py | 1071 | ConfigHistoryStore, ReflectionStore, PromptStore | add_config_change, get_config_history, get_config_changes_since |
| store/_memories.py | 317 | MemoryStore | add_memory, update_memory, deactivate_memory |
| store/_scheduled_tasks.py | 221 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| store/_semantic_search.py | 208 | SemanticSearch | index_memory, index_all_memories, semantic_search |
| store/_summaries.py | 379 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| store/_topics.py | 213 | TopicStore | create_topic, update_topic_title, update_topic_active |
| store/_vectors.py | 237 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tests/__init__.py | 1 | — | — |
| tests/conftest.py | 60 | — | tmp_db_path, storage, tmp_yaml_config |
| tests/test_agent.py | 169 | TestAgentCreation, TestTeaAgentFactory, TestAgentLifecycle | test_lightweight_mode_creates_agent, test_full_mode_creates_agent_with_storage, test_lite_mode_creates_lite_session |
| tests/test_agent_chat.py | 315 | TestAgentChatIntegration, TestAgentChatErrorHandling | tmp_dir, tmp_yaml_config, tmp_db_path |
| tests/test_auto_fix.py | 262 | MyClass, TestScan, TestFix | sample_file, foo, method1 |
| tests/test_basesession.py | 88 | TestBaseSessionConfig, TestConfigLoading, TestLiteSession | test_base_session_abstract, test_strip_reasoning_content_modifies_in_place, test_compress_tool_content_truncates_long_output |
| tests/test_config.py | 255 | TestModelConfig, TestPathsConfig, TestEmbeddingConfig | test_default_not_configured, test_configured_when_all_set, test_not_configured_when_partial |
| tests/test_gui_adversarial.py | 303 | TestPendingErrorAdversarial, TestGlobalDeclarationsAdversarial, TestLoadWorkerAdversarial | test_none_should_not_trigger_error, test_empty_string_should_trigger_error, test_false_should_trigger_error |
| tests/test_gui_fonts.py | 86 | TestInitFontsGlobalDeclarations, TestFontSizeCalculation | test_all_globals_declared, test_fs_uses_scale_factor, test_default_font_size_is_positive |
| tests/test_gui_renderer.py | 97 | TestPollLoadingProgress, TestHasattrVsGetattrPattern, Obj | test_pending_error_none_should_not_trigger_error, test_pending_error_string_should_trigger_error, test_pending_error_empty_string_should_trigger_error |
| tests/test_history_builder.py | 102 | TestToMultimodal | test_no_images_returns_unchanged, test_empty_images_returns_unchanged, test_vision_supported_converts_to_multimodal |
| tests/test_json_sanitizer.py | 231 | TestTryFixTruncatedJson, TestSanitizeApiMessages | test_valid_json_returns_unchanged, test_empty_string_returns_none, test_truncated_object_closes_braces |
| tests/test_loop_detector.py | 179 | TestLoopDetectorInit, TestToolCallRepeatDetection, TestContentRepeatDetection | test_default_parameters, test_custom_parameters, test_no_repeat_on_first_call |
| tests/test_memory_enhancements.py | 251 | TestAutoMemoryExtractor, TestSemanticSearch, TestToolkitMemoryEnhancements | storage, test_extractor_init, test_get_unextracted_conversations |
| tests/test_onlinesession.py | 1037 | TestDetectMode, TestExtractMode, TestOnlineToolSessionCreate | test_returns_dict_with_mock, mock_call_tool, test_switched_true_when_mode_changes |
| tests/test_prompt_manager.py | 182 | TestSystemPromptManager | storage, test_init, test_initialize_creates_default |
| tests/test_reflection.py | 310 | TestToolCallRecord, TestSessionTrace, TestReflectionManager | storage, test_init_defaults, test_init_with_error |
| tests/test_render_timing.py | 161 | TestRenderTiming | setUpClass, test_render_before_pipeline, test_show_raw_check_btn_before_pipeline |
| tests/test_session_intent.py | 73 | TestIntentContract | test_returns_dict, test_has_required_keys, test_type_is_string |
| tests/test_session_pipeline.py | 254 | TestPipelineRegistration, TestPipelineOrdering, TestPipelineEnableDisable | test_register_step_adds_to_steps, test_register_duplicate_raises, test_remove_step_removes_from_both |
| tests/test_store.py | 571 | TestStorageInit, TestTopicCRUD, TestMessageCRUD | test_init_creates_db_file, test_init_creates_all_tables, test_init_enables_wal_mode |
| tests/test_store_component.py | 365 | TestStoreComponent, TestStorageDelegation, TestGetStorage | test_new_id_returns_uuid_string, test_new_id_is_unique, test_explicit_attribute_access |
| tests/test_tea_agent_dual.py | 87 | — | extract_final_reply, main |
| tests/test_tlk.py | 104 | TestToolkitRegistration, TestToolkitUserOverride, TestToolkitEdgeCases | test_reload_loads_builtin_tools, test_meta_map_matches_func_map, test_call_tool_returns_result |
| tests/test_tool_build.py | 120 | TestFilterToolsNoFilter, TestFilterToolsWithFilter, TestFilterToolsEdgeCases | test_no_filter_keeps_all_tools, test_no_filter_reuses_same_list, test_no_filter_essential_still_present |
| tlk.py | 740 | Toolkit | meta_toolkit_reload, meta_toolkit_save, toolkit_reload |
| toolkit/__init__.py | 1 | — | — |
| toolkit/toolkit_auto_fix.py | 154 | — | toolkit_auto_fix, meta_toolkit_auto_fix |
| toolkit/toolkit_browser_tab.py | 222 | — | toolkit_browser_tab, get_foreground_window, set_foreground_window |
| toolkit/toolkit_build.py | 136 | — | toolkit_build, meta_toolkit_build |
| toolkit/toolkit_clean_comments.py | 245 | — | toolkit_clean_comments, meta_toolkit_clean_comments |
| toolkit/toolkit_comment.py | 58 | — | toolkit_comment, meta_toolkit_comment |
| toolkit/toolkit_config.py | 128 | — | toolkit_config, meta_toolkit_config |
| toolkit/toolkit_custom_commands.py | 394 | — | toolkit_custom_commands, meta_toolkit_custom_commands |
| toolkit/toolkit_date_diff.py | 63 | — | toolkit_date_diff, meta_toolkit_date_diff |
| toolkit/toolkit_diff.py | 364 | — | toolkit_diff, meta_toolkit_diff |
| toolkit/toolkit_dump_topic.py | 124 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| toolkit/toolkit_dynamic_skill.py | 372 | — | toolkit_dynamic_skill, update_pattern_usage, meta_toolkit_dynamic_skill |
| toolkit/toolkit_edit.py | 490 | — | toolkit_edit, meta_toolkit_edit |
| toolkit/toolkit_evolution_exp.py | 128 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| toolkit/toolkit_exec.py | 307 | — | toolkit_exec, meta_toolkit_exec |
| toolkit/toolkit_experience_solidify.py | 221 | — | toolkit_experience_solidify, meta_toolkit_experience_solidify |
| toolkit/toolkit_explr.py | 1029 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| toolkit/toolkit_export_last_pdf.py | 322 | PDF | toolkit_export_last_pdf, header, footer |
| toolkit/toolkit_file.py | 130 | — | toolkit_file, scan_dir, meta_toolkit_file |
| toolkit/toolkit_format_code.py | 224 | — | toolkit_format_code, meta_toolkit_format_code |
| toolkit/toolkit_get_config_path.py | 89 | — | toolkit_get_config_path, meta_toolkit_get_config_path |
| toolkit/toolkit_get_models.py | 36 | — | toolkit_get_models, meta_toolkit_get_models |
| toolkit/toolkit_gettime.py | 23 | — | toolkit_gettime, meta_toolkit_gettime |
| toolkit/toolkit_git_push_all_remotes.py | 40 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| toolkit/toolkit_input.py | 192 | — | toolkit_input, meta_toolkit_input |
| toolkit/toolkit_ip_location_my.py | 71 | — | toolkit_ip_location_my, meta_toolkit_ip_location_my |
| toolkit/toolkit_js_fetch.py | 116 | — | toolkit_js_fetch, meta_toolkit_js_fetch |
| toolkit/toolkit_kb.py | 195 | — | toolkit_kb, sanitize, rebuild_index |
| toolkit/toolkit_list_provider_models.py | 140 | — | toolkit_list_provider_models, meta_toolkit_list_provider_models |
| toolkit/toolkit_lsp.py | 85 | — | toolkit_lsp, meta_toolkit_lsp |
| toolkit/toolkit_lunar.py | 336 | — | toolkit_lunar, meta_toolkit_lunar |
| toolkit/toolkit_mcp.py | 384 | — | toolkit_mcp, meta_toolkit_mcp |
| toolkit/toolkit_memory.py | 234 | — | toolkit_memory, meta_toolkit_memory |
| toolkit/toolkit_mode.py | 352 | — | toolkit_mode, meta_toolkit_mode |
| toolkit/toolkit_notify.py | 124 | — | toolkit_notify, meta_toolkit_notify |
| toolkit/toolkit_ocr.py | 245 | — | toolkit_ocr, meta_toolkit_ocr, meta_toolkit_ocr |
| toolkit/toolkit_os_info.py | 46 | — | toolkit_os_info, meta_toolkit_os_info |
| toolkit/toolkit_parallel_subtasks.py | 186 | — | toolkit_parallel_subtasks, meta_toolkit_parallel_subtasks |
| toolkit/toolkit_pkg.py | 150 | — | toolkit_pkg, meta_toolkit_pkg |
| toolkit/toolkit_plan.py | 1408 | — | toolkit_plan, meta_toolkit_plan |
| toolkit/toolkit_proactive.py | 156 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| toolkit/toolkit_prompt_evolve.py | 124 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| toolkit/toolkit_query_chat_history.py | 104 | — | toolkit_query_chat_history, meta_toolkit_query_chat_history |
| toolkit/toolkit_question.py | 332 | — | toolkit_question, on_custom_focus, on_enter |
| toolkit/toolkit_read_pyproject.py | 80 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| toolkit/toolkit_reflection.py | 98 | — | toolkit_reflection, meta_toolkit_reflection |
| toolkit/toolkit_release_version.py | 116 | — | toolkit_release_version, meta_toolkit_release_version |
| toolkit/toolkit_run_tests.py | 79 | — | toolkit_run_tests, meta_toolkit_run_tests |
| toolkit/toolkit_save_file.py | 55 | — | toolkit_save_file, meta_toolkit_save_file |
| toolkit/toolkit_scheduler.py | 655 | — | toolkit_scheduler, parse_schedule, ensure_running |
| toolkit/toolkit_scheduler_storage.py | 49 | — | toolkit_scheduler_storage, meta_toolkit_scheduler_storage |
| toolkit/toolkit_screen_read.py | 208 | — | toolkit_screen_read, get_toolkit_func, meta_toolkit_screen_read |
| toolkit/toolkit_screenshot.py | 241 | — | toolkit_screenshot, meta_toolkit_screenshot |
| toolkit/toolkit_search.py | 535 | — | toolkit_search, meta_toolkit_search |
| toolkit/toolkit_self_evolve.py | 471 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| toolkit/toolkit_self_evolve_thread.py | 531 | — | toolkit_self_evolve_thread, meta_toolkit_self_evolve_thread |
| toolkit/toolkit_self_report.py | 75 | — | toolkit_self_report, meta_toolkit_self_report |
| toolkit/toolkit_set_topic_title.py | 78 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| toolkit/toolkit_stream_save.py | 92 | — | toolkit_stream_save, meta_toolkit_stream_save |
| toolkit/toolkit_sudo_gui.py | 81 | — | toolkit_sudo_gui, meta_toolkit_sudo_gui |
| toolkit/toolkit_task_resume.py | 376 | — | toolkit_task_resume, meta_toolkit_task_resume |
| toolkit/toolkit_test_gui.py | 150 | — | toolkit_test_gui, meta_toolkit_test_gui |
| toolkit/toolkit_todo.py | 266 | — | toolkit_todo, meta_toolkit_todo |
| toolkit/toolkit_toggle_reasoning.py | 50 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| toolkit/toolkit_weather_my.py | 122 | — | toolkit_weather_my, meta_toolkit_weather_my |
| tui.py | 813 | _TUIAgentCore, TeaTUI, _SendTextArea | on_stream, on_status, compose |
| workflow/__init__.py | 19 | — | — |
| workflow/builder.py | 334 | Step, Workflow, WorkflowBuilder | to_dict, to_json, build |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 377 |
| `append` | ?:? | 280 |
| `get` | config.py:217 | 278 |
| `str` | ?:? | 201 |
| `join` | ?:? | 197 |
| `close` | lsp/symbol_index.py:340 | 160 |
| `execute` | store/_component.py:41 | 139 |
| `info` | ?:? | 133 |
| `strip` | ?:? | 106 |
| `open` | ?:? | 103 |
| `isinstance` | ?:? | 96 |
| `cursor` | store/_component.py:38 | 85 |
| `set` | config.py:223 | 77 |
| `warning` | ?:? | 77 |
| `exists` | ?:? | 77 |
| `startswith` | ?:? | 76 |
| `split` | ?:? | 75 |
| `lower` | ?:? | 67 |
| `commit` | ?:? | 66 |
| `getattr` | ?:? | 63 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

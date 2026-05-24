# tea_agent 项目知识库

> 自动生成: 2026-05-24 18:14
> 工具: ctags + AST + graphviz
>
> 符号: 746 唯一 · 函数: 929 · 类: 77 · 调用边: 5238

## 符号种类分布

| 种类 | 数量 |
|------|------|
| function | 339 |
| member | 312 |
| variable | 180 |
| class | 40 |
| namespace | 33 |
| unknown | 9 |

## 模块索引 (114 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| __init__.py | 14 | — | — |
| _gui/__init__.py | 3 | — | — |
| _gui/_fonts.py | 89 | — | — |
| _gui/_images.py | 143 | ImageHandler | attach, clear, show_popup |
| _gui/_markdown.py | 446 | _TagChecker | handle_starttag, handle_endtag, get_result |
| _gui/_renderer.py | 459 | ChatRenderer | scroll_to_bottom |
| _gui/_stream_manager.py | 207 | StreamManager | safe_stream, safe_log, safe_log_tool |
| _gui/_topic_manager.py | 441 | TopicManager | clear_chat, auto_new_topic, new_topic |
| _gui/_topic_summary.py | 93 | — | — |
| _gui/_tray.py | 137 | TrayManager | start, stop |
| _gui/_ui_builder.py | 143 | UIBuilder | build |
| agent_core.py | 425 | AgentCore | — |
| basesession.py | 576 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| cli.py | 467 | TeaCLI | run, on_stream, on_status |
| config.py | 730 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| embedding_util.py | 431 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| gui.py | 1283 | StatusNotifierItemDBus, TkGUI | Title, Id, Status |
| gui_dialogs.py | 1290 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| logging_setup.py | 97 | — | setup_logging, set_debug |
| lsp/__init__.py | 12 | — | — |
| lsp/lsp_check.py | 131 | — | run_lsp_check |
| lsp/lsp_engine.py | 367 | — | diagnose, completion, goto_definition |
| lsp/ts_analyzer.py | 1021 | _MetricsVisitor, _CallCollector, _Inner | parse_file, impact_analysis, build_dependency_graph |
| memory.py | 729 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| merge_db.py | 716 | DbMerger | merge, close, main |
| multi_agent/__init__.py | 44 | — | — |
| multi_agent/agent_pool.py | 597 | AgentPool, LiteAgentPool | register_agent_type, create_agent, get_agent |
| multi_agent/lite_agent.py | 685 | LiteAgentModelConfig, LiteAgentConfig, ToolRegistry | is_configured, register, unregister |
| multi_agent/orchestrator.py | 764 | MultiAgentOrchestrator, LiteOrchestrator | register_agent_type, execute, execute_single |
| multi_agent/result_aggregator.py | 272 | ResultAggregator | aggregate, summarize_result, merge_code_results |
| multi_agent/sub_agent.py | 387 | SubAgentConfig, SubAgentWrapper | initialize, run, run_async |
| multi_agent/task_decomposer.py | 401 | SubTask, TaskDecomposer | to_dict, from_dict, decompose |
| onlinesession.py | 1567 | OnlineToolSession | messages, messages, model |
| project_memory.py | 172 | ProjectMemoryManager | add, get_all, search |
| prompt_manager.py | 312 | SystemPromptManager | initialize, current_prompt, current_version |
| reflection.py | 346 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| session/__init__.py | 1 | — | — |
| session_api_component.py | 334 | APIComponent | name, initialize, create_chat_stream |
| session_context.py | 107 | SessionContext, SessionComponent | initialize, name |
| session_memory_component.py | 245 | MemoryComponent | name, initialize, inject_memories |
| session_pipeline.py | 233 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| session_prompts.py | 44 | — | — |
| session_ref.py | 32 | — | get_session, set_session, get_agent |
| session_summarizer_component.py | 210 | SummarizerComponent | name, initialize, summarize_old_history |
| session_tool_component.py | 265 | ToolComponent | name, initialize, build_tools |
| skills/__init__.py | 440 | Skill, SkillManager | to_dict, get_instance, reset_instance |
| skills/file_system/__init__.py | 26 | — | — |
| skills/interaction/__init__.py | 21 | — | — |
| skills/memory_knowledge/__init__.py | 28 | — | — |
| skills/self_evolution/__init__.py | 33 | — | — |
| skills/todo_workflow/__init__.py | 23 | — | — |
| skills/utility/__init__.py | 19 | — | — |
| store/__init__.py | 42 | — | get_storage |
| store/_base.py | 25 | StoreComponent | — |
| store/_config.py | 72 | ConfigHistoryStore | add_config_change, get_config_history, get_config_changes_since |
| store/_conversations.py | 284 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| store/_core.py | 663 | Storage | save_msg, backup_now, close |
| store/_memories.py | 254 | MemoryStore | add_memory, update_memory, deactivate_memory |
| store/_prompts.py | 102 | PromptStore | add_system_prompt, get_latest_system_prompt, get_system_prompt_history |
| store/_reflections.py | 82 | ReflectionStore | add_reflection, get_recent_reflections, mark_reflection_applied |
| store/_scheduled_tasks.py | 286 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| store/_summaries.py | 268 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| store/_topics.py | 213 | TopicStore | create_topic, update_topic_title, update_topic_active |
| store/_vectors.py | 246 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tea_agent.py | 352 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_main_cli.py | 365 | TeaCLI | chat, stream_cb, status_cb |
| tlk.py | 461 | Toolkit | meta_toolkit_save, toolkit_save_impl, call_tool |
| token_utils.py | 223 | — | estimate_tokens, estimate_message_tokens, estimate_text_tokens |
| toolkit/__init__.py | 0 | — | — |
| toolkit/subconscious/__init__.py | 1 | — | — |
| toolkit/tool_loader.py | 130 | ToolLoader | check_meta, reload_all |
| toolkit/toolkit_config.py | 129 | — | toolkit_config, meta_toolkit_config |
| toolkit/toolkit_date_diff.py | 62 | — | toolkit_date_diff, meta_toolkit_date_diff |
| toolkit/toolkit_delegate.py | 140 | — | set_orchestrator, get_orchestrator, toolkit_delegate |
| toolkit/toolkit_diff.py | 459 | — | toolkit_diff, meta_toolkit_diff |
| toolkit/toolkit_dump_topic.py | 126 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| toolkit/toolkit_edit.py | 480 | — | toolkit_edit, meta_toolkit_edit |
| toolkit/toolkit_evolution_exp.py | 136 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| toolkit/toolkit_exec.py | 293 | — | toolkit_exec, meta_toolkit_exec |
| toolkit/toolkit_explr.py | 754 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| toolkit/toolkit_file.py | 139 | — | toolkit_file, scan_dir, meta_toolkit_file |
| toolkit/toolkit_gettime.py | 32 | — | toolkit_gettime, meta_toolkit_gettime |
| toolkit/toolkit_git_push_all_remotes.py | 50 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| toolkit/toolkit_kb.py | 201 | — | toolkit_kb, sanitize, rebuild_index |
| toolkit/toolkit_lsp.py | 85 | — | toolkit_lsp, meta_toolkit_lsp |
| toolkit/toolkit_lunar.py | 353 | — | toolkit_lunar, meta_toolkit_lunar |
| toolkit/toolkit_mcp.py | 397 | — | toolkit_mcp, meta_toolkit_mcp |
| toolkit/toolkit_memory.py | 242 | — | toolkit_memory, meta_toolkit_memory |
| toolkit/toolkit_mode.py | 231 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| toolkit/toolkit_notify.py | 121 | — | toolkit_notify, meta_toolkit_notify |
| toolkit/toolkit_os_info.py | 56 | — | toolkit_os_info, meta_toolkit_os_info |
| toolkit/toolkit_pkg.py | 168 | — | toolkit_pkg, meta_toolkit_pkg |
| toolkit/toolkit_plan.py | 457 | — | meta_toolkit_plan, toolkit_plan |
| toolkit/toolkit_proactive.py | 170 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| toolkit/toolkit_prompt_evolve.py | 127 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| toolkit/toolkit_quality_gate.py | 274 | — | toolkit_quality_gate, meta_toolkit_quality_gate |
| toolkit/toolkit_read_pyproject.py | 83 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| toolkit/toolkit_reflection.py | 101 | — | toolkit_reflection, meta_toolkit_reflection |
| toolkit/toolkit_release.py | 290 | — | toolkit_release, meta_toolkit_release |
| toolkit/toolkit_run_tests.py | 78 | — | toolkit_run_tests, meta_toolkit_run_tests |
| toolkit/toolkit_scheduler.py | 449 | — | toolkit_scheduler, parse_schedule, meta_toolkit_scheduler |
| toolkit/toolkit_search.py | 440 | — | toolkit_search, meta_toolkit_search |
| toolkit/toolkit_self_evolve.py | 252 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| toolkit/toolkit_self_report.py | 77 | — | toolkit_self_report, meta_toolkit_self_report |
| toolkit/toolkit_set_topic_title.py | 76 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| toolkit/toolkit_skill.py | 104 | — | toolkit_skill, meta_toolkit_skill |
| toolkit/toolkit_static.py | 192 | — | meta_toolkit_static, toolkit_static |
| toolkit/toolkit_sub_agent.py | 163 | — | toolkit_sub_agent_report, toolkit_sub_agent_status, clear_sub_agent_reports |
| toolkit/toolkit_subconscious.py | 1247 | — | toolkit_subconscious, meta_toolkit_subconscious |
| toolkit/toolkit_test_gui.py | 144 | — | toolkit_test_gui, meta_toolkit_test_gui |
| toolkit/toolkit_todo.py | 477 | — | toolkit_todo, meta_toolkit_todo |
| toolkit/toolkit_toggle_reasoning.py | 49 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| tools/refactor_comments.py | 435 | BodyFinder, DocProcessor | get_function_body_ranges, visit_FunctionDef, strip_inline_comments |
| tui.py | 762 | _TUIAgentCore, TeaTUI, _SendTextArea | on_stream, on_status, action_send_from_input |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 223 |
| `append` | ?:? | 215 |
| `get` | config.py:347 | 212 |
| `join` | ?:? | 148 |
| `str` | ?:? | 139 |
| `execute` | multi_agent/orchestrator.py:564 | 112 |
| `info` | ?:? | 109 |
| `cursor` | ?:? | 83 |
| `close` | store/_core.py:644 | 82 |
| `strip` | ?:? | 80 |
| `open` | ?:? | 63 |
| `warning` | ?:? | 62 |
| `set` | config.py:359 | 62 |
| `commit` | ?:? | 61 |
| `isinstance` | ?:? | 56 |
| `startswith` | ?:? | 52 |
| `split` | ?:? | 48 |
| `exists` | ?:? | 44 |
| `fetchall` | ?:? | 43 |
| `enumerate` | ?:? | 43 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

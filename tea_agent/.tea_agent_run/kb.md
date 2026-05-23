# tea_agent 项目知识库

> 自动生成: 2026-05-23 08:14
> 工具: ctags + AST + graphviz
>
> 符号: 535 唯一 · 函数: 795 · 类: 56 · 调用边: 4693

## 符号种类分布

| 种类 | 数量 |
|------|------|
| function | 276 |
| member | 191 |
| variable | 104 |
| namespace | 30 |
| class | 21 |
| unknown | 5 |

## 模块索引 (98 文件)

| 模块 | 行数 | 类 | 公开函数 |
|------|------|-----|----------|
| __init__.py | 15 | — | — |
| _gui/__init__.py | 4 | — | — |
| _gui/_fonts.py | 85 | — | — |
| _gui/_images.py | 130 | ImageHandler | attach, clear, show_popup |
| _gui/_markdown.py | 424 | _TagChecker | handle_starttag, handle_endtag, get_result |
| _gui/_renderer.py | 461 | ChatRenderer | scroll_to_bottom |
| _gui/_stream_manager.py | 178 | StreamManager | safe_stream, safe_log, safe_log_tool |
| _gui/_topic_manager.py | 364 | TopicManager | clear_chat, auto_new_topic, new_topic |
| _gui/_topic_summary.py | 100 | — | — |
| _gui/_tray.py | 136 | TrayManager | start, stop |
| _gui/_ui_builder.py | 155 | UIBuilder | build |
| agent_core.py | 428 | AgentCore | — |
| basesession.py | 621 | BaseChatSession | chat_stream, add_user_message, add_assistant_message |
| cli.py | 449 | TeaCLI | run, on_stream, on_status |
| config.py | 603 | ModelConfig, PathsConfig, EmbeddingConfig | is_configured, resolve, db_path_abs |
| embedding_util.py | 346 | _SimpleTFIDF, EmbeddingEngine | add_document, vectorize, mode |
| gui.py | 1177 | StatusNotifierItemDBus, TkGUI | Title, Id, Status |
| gui_dialogs.py | 1321 | MemoryDialog, TopicDialog, ConfigDialog | do_add, parse_tok, do_rename |
| logging_setup.py | 95 | — | setup_logging, set_debug |
| lsp/__init__.py | 12 | — | — |
| lsp/lsp_engine.py | 296 | — | diagnose, completion, goto_definition |
| lsp/ts_analyzer.py | 441 | — | parse_file, impact_analysis, build_dependency_graph |
| memory.py | 711 | MemoryManager | select_memories, degrade_by_age, llm_adjust_priorities |
| merge_db.py | 723 | DbMerger | merge, close, main |
| onlinesession.py | 1449 | OnlineToolSession | messages, messages, model |
| project_memory.py | 130 | ProjectMemoryManager | add, get_all, search |
| prompt_manager.py | 283 | SystemPromptManager | initialize, current_prompt, current_version |
| reflection.py | 291 | ToolCallRecord, SessionTrace, ReflectionManager | success_rate, duration_seconds, start_trace |
| session/__init__.py | 1 | — | — |
| session_api_component.py | 295 | APIComponent | name, initialize, create_chat_stream |
| session_context.py | 104 | SessionContext, SessionComponent | initialize, name |
| session_memory_component.py | 229 | MemoryComponent | name, initialize, inject_memories |
| session_pipeline.py | 203 | PipelineStep, SessionPipeline | register_step, enable_step, disable_step |
| session_prompts.py | 53 | — | — |
| session_ref.py | 23 | — | get_session, set_session, get_agent |
| session_summarizer_component.py | 197 | SummarizerComponent | name, initialize, summarize_old_history |
| session_tool_component.py | 196 | ToolComponent | name, initialize, build_tools |
| skills/__init__.py | 378 | Skill, SkillManager | to_dict, get_instance, reset_instance |
| skills/file_system/__init__.py | 26 | — | — |
| skills/interaction/__init__.py | 21 | — | — |
| skills/memory_knowledge/__init__.py | 28 | — | — |
| skills/self_evolution/__init__.py | 33 | — | — |
| skills/todo_workflow/__init__.py | 23 | — | — |
| skills/utility/__init__.py | 19 | — | — |
| store/__init__.py | 38 | — | get_storage |
| store/_base.py | 20 | StoreComponent | — |
| store/_config.py | 72 | ConfigHistoryStore | add_config_change, get_config_history, get_config_changes_since |
| store/_conversations.py | 236 | ConversationStore | save_msg, update_msg_rounds, save_agent_round |
| store/_core.py | 676 | Storage | save_msg, backup_now, close |
| store/_memories.py | 241 | MemoryStore | add_memory, update_memory, deactivate_memory |
| store/_prompts.py | 92 | PromptStore | add_system_prompt, get_latest_system_prompt, get_system_prompt_history |
| store/_reflections.py | 77 | ReflectionStore | add_reflection, get_recent_reflections, mark_reflection_applied |
| store/_scheduled_tasks.py | 221 | ScheduledTaskStore | parse_schedule, add_task, update_task |
| store/_summaries.py | 245 | SummaryStore | get_topic_summary, update_topic_summary, get_level2 |
| store/_topics.py | 194 | TopicStore | create_topic, update_topic_title, update_topic_active |
| store/_vectors.py | 237 | VectorStore | store_embedding, get_msg_embedding, get_all_embeddings |
| tea_agent.py | 345 | TeaAgent | toolkit_save, toolkit_reload, chat |
| tea_main_cli.py | 367 | TeaCLI | chat, stream_cb, status_cb |
| tlk.py | 529 | Toolkit | meta_toolkit_save, toolkit_save_impl, call_tool |
| token_utils.py | 183 | — | estimate_tokens, estimate_message_tokens, estimate_text_tokens |
| toolkit/__init__.py | 1 | — | — |
| toolkit/subconscious/__init__.py | 1 | — | — |
| toolkit/toolkit_config.py | 128 | — | toolkit_config, meta_toolkit_config |
| toolkit/toolkit_date_diff.py | 63 | — | toolkit_date_diff, meta_toolkit_date_diff |
| toolkit/toolkit_dump_topic.py | 124 | — | toolkit_dump_topic, meta_toolkit_dump_topic |
| toolkit/toolkit_edit.py | 750 | — | toolkit_edit, meta_toolkit_edit |
| toolkit/toolkit_evolution_exp.py | 128 | — | toolkit_evolution_exp, meta_toolkit_evolution_exp |
| toolkit/toolkit_exec.py | 306 | — | toolkit_exec, meta_toolkit_exec |
| toolkit/toolkit_explr.py | 719 | CallVisitor | visit_FunctionDef, visit_AsyncFunctionDef, visit_ClassDef |
| toolkit/toolkit_file.py | 132 | — | toolkit_file, scan_dir, meta_toolkit_file |
| toolkit/toolkit_gettime.py | 23 | — | toolkit_gettime, meta_toolkit_gettime |
| toolkit/toolkit_git_push_all_remotes.py | 40 | — | toolkit_git_push_all_remotes, meta_toolkit_git_push_all_remotes |
| toolkit/toolkit_kb.py | 195 | — | toolkit_kb, sanitize, rebuild_index |
| toolkit/toolkit_lsp.py | 85 | — | toolkit_lsp, meta_toolkit_lsp |
| toolkit/toolkit_lunar.py | 336 | — | toolkit_lunar, meta_toolkit_lunar |
| toolkit/toolkit_mcp.py | 384 | — | toolkit_mcp, meta_toolkit_mcp |
| toolkit/toolkit_memory.py | 164 | — | toolkit_memory, meta_toolkit_memory |
| toolkit/toolkit_mode.py | 232 | — | toolkit_mode, meta_toolkit_mode, meta_toolkit_mode |
| toolkit/toolkit_notify.py | 124 | — | toolkit_notify, meta_toolkit_notify |
| toolkit/toolkit_os_info.py | 46 | — | toolkit_os_info, meta_toolkit_os_info |
| toolkit/toolkit_pkg.py | 150 | — | toolkit_pkg, meta_toolkit_pkg |
| toolkit/toolkit_proactive.py | 156 | — | toolkit_proactive, meta_toolkit_proactive, meta_toolkit_proactive |
| toolkit/toolkit_prompt_evolve.py | 124 | — | toolkit_prompt_evolve, meta_toolkit_prompt_evolve |
| toolkit/toolkit_read_pyproject.py | 80 | — | toolkit_read_pyproject, meta_toolkit_read_pyproject |
| toolkit/toolkit_reflection.py | 98 | — | toolkit_reflection, meta_toolkit_reflection |
| toolkit/toolkit_release.py | 247 | — | toolkit_release, meta_toolkit_release |
| toolkit/toolkit_run_tests.py | 79 | — | toolkit_run_tests, meta_toolkit_run_tests |
| toolkit/toolkit_scheduler.py | 453 | — | toolkit_scheduler, parse_schedule, meta_toolkit_scheduler |
| toolkit/toolkit_search.py | 424 | — | toolkit_search, meta_toolkit_search |
| toolkit/toolkit_self_evolve.py | 322 | — | toolkit_self_evolve, meta_toolkit_self_evolve |
| toolkit/toolkit_self_report.py | 75 | — | toolkit_self_report, meta_toolkit_self_report |
| toolkit/toolkit_set_topic_title.py | 78 | — | toolkit_set_topic_title, meta_toolkit_set_topic_title |
| toolkit/toolkit_skill.py | 104 | — | toolkit_skill, meta_toolkit_skill |
| toolkit/toolkit_subconscious.py | 1003 | — | toolkit_subconscious, meta_toolkit_subconscious |
| toolkit/toolkit_test_gui.py | 150 | — | toolkit_test_gui, meta_toolkit_test_gui |
| toolkit/toolkit_todo.py | 800 | — | toolkit_todo, meta_toolkit_todo, toolkit_plan |
| toolkit/toolkit_toggle_reasoning.py | 50 | — | toolkit_toggle_reasoning, meta_toolkit_toggle_reasoning |
| tui.py | 657 | _TUIAgentCore, TeaTUI, _SendTextArea | on_stream, on_status, action_send_from_input |

## Top 20 被调用函数

| 函数 | 文件:行号 | 调用者数 |
|------|-----------|----------|
| `len` | ?:? | 188 |
| `get` | config.py:230 | 179 |
| `append` | ?:? | 170 |
| `join` | ?:? | 130 |
| `str` | ?:? | 130 |
| `execute` | session_pipeline.py:131 | 109 |
| `info` | ?:? | 97 |
| `cursor` | ?:? | 81 |
| `close` | store/_core.py:658 | 80 |
| `strip` | ?:? | 75 |
| `commit` | ?:? | 60 |
| `open` | ?:? | 58 |
| `warning` | ?:? | 55 |
| `set` | config.py:236 | 52 |
| `isinstance` | ?:? | 51 |
| `startswith` | ?:? | 46 |
| `split` | ?:? | 43 |
| `fetchall` | ?:? | 42 |
| `exists` | ?:? | 41 |
| `lower` | ?:? | 40 |

## 生成文件

| 文件 | 说明 |
|------|------|
| symbol_index.json | 符号→位置索引 |
| call_graph.json | AST 调用图 |
| ctags.json | 原始 ctags 输出 |
| call_flow.dot | Graphviz 调用流程图 |
| call_flow.svg | 调用流程图 SVG |
| kb.md | 本文档 |

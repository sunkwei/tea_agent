# tea_agent API 参考

> 自动生成: 2026-07-11 09:13  |  函数: 2187  |  类: 239  |  符号: 3774

## 模块 `build_mini_dist`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Tea Agent Mini` | `build_mini_dist\README.mini.md:1` | chapter |

## 模块 `build_mini_dist\tea_agent`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `APIComponent` | `build_mini_dist\tea_agent\onlinesession.py:76` | class |
| `Agent` | `build_mini_dist\tea_agent\agent.py:106` | class |
| `AgentConfig` | `build_mini_dist\tea_agent\config.py:142` | class |
| `AutoFixAgent` | `build_mini_dist\tea_agent\auto_fix.py:32` | class |
| `AutoMemoryExtractor` | `build_mini_dist\tea_agent\session_memory_component.py:238` | class |
| `BaseChatSession` | `build_mini_dist\tea_agent\basesession.py:125` | class |
| `EmbeddingConfig` | `build_mini_dist\tea_agent\config.py:122` | class |
| `FixResult` | `build_mini_dist\tea_agent\auto_fix.py:23` | class |
| `LiteSession` | `build_mini_dist\tea_agent\litesession.py:22` | class |
| `MemoryComponent` | `build_mini_dist\tea_agent\session_memory_component.py:28` | class |
| `MemoryManager` | `build_mini_dist\tea_agent\memory.py:46` | class |
| `ModelConfig` | `build_mini_dist\tea_agent\config.py:28` | class |
| `OnlineToolSession` | `build_mini_dist\tea_agent\onlinesession.py:662` | class |
| `PathsConfig` | `build_mini_dist\tea_agent\config.py:50` | class |
| `PipelineStep` | `build_mini_dist\tea_agent\session_pipeline.py:20` | class |
| `ProjectMemoryManager` | `build_mini_dist\tea_agent\project_memory.py:14` | class |
| `ReflectionManager` | `build_mini_dist\tea_agent\reflection.py:53` | class |
| `SchedulerStorage` | `build_mini_dist\tea_agent\scheduler_storage.py:16` | class |
| `SessionPipeline` | `build_mini_dist\tea_agent\session_pipeline.py:28` | class |
| `SessionTrace` | `build_mini_dist\tea_agent\reflection.py:28` | class |
| `SimpleFunction` | `build_mini_dist\tea_agent\litesession.py:271` | class |
| `SimpleToolCall` | `build_mini_dist\tea_agent\litesession.py:276` | class |
| `SummarizerComponent` | `build_mini_dist\tea_agent\onlinesession.py:515` | class |
| `SystemPromptManager` | `build_mini_dist\tea_agent\prompt_manager.py:28` | class |
| `ToolCallRecord` | `build_mini_dist\tea_agent\reflection.py:20` | class |
| `ToolComponent` | `build_mini_dist\tea_agent\onlinesession.py:319` | class |
| `Toolkit` | `build_mini_dist\tea_agent\tlk.py:258` | class |
| `_ModeBehavior` | `build_mini_dist\tea_agent\agent.py:57` | class |
| `__del__` | `build_mini_dist\tea_agent\onlinesession.py:1197` | member |
| `__enter__` | `build_mini_dist\tea_agent\agent.py:624` | member |
| `__exit__` | `build_mini_dist\tea_agent\agent.py:627` | member |
| `__init__` | `build_mini_dist\tea_agent\agent.py:113` | member |
| `__init__` | `build_mini_dist\tea_agent\auto_fix.py:24` | member |
| `__init__` | `build_mini_dist\tea_agent\auto_fix.py:33` | member |
| `__init__` | `build_mini_dist\tea_agent\basesession.py:144` | member |
| `__init__` | `build_mini_dist\tea_agent\litesession.py:32` | member |
| `__init__` | `build_mini_dist\tea_agent\memory.py:49` | member |
| `__init__` | `build_mini_dist\tea_agent\onlinesession.py:676` | member |
| `__init__` | `build_mini_dist\tea_agent\project_memory.py:20` | member |
| `__init__` | `build_mini_dist\tea_agent\prompt_manager.py:47` | member |
| `__init__` | `build_mini_dist\tea_agent\reflection.py:79` | member |
| `__init__` | `build_mini_dist\tea_agent\scheduler_storage.py:25` | member |
| `__init__` | `build_mini_dist\tea_agent\session_memory_component.py:241` | member |
| `__init__` | `build_mini_dist\tea_agent\session_pipeline.py:38` | member |
| `__init__` | `build_mini_dist\tea_agent\tlk.py:273` | member |
| `_accumulate_usage` | `build_mini_dist\tea_agent\onlinesession.py:139` | member |
| `_analyze_intent` | `build_mini_dist\tea_agent\onlinesession.py:1035` | member |
| `_apply` | `build_mini_dist\tea_agent\auto_fix.py:221` | member |
| `_auto_detect_mode` | `build_mini_dist\tea_agent\onlinesession.py:1056` | member |
| `_build_api_messages` | `build_mini_dist\tea_agent\onlinesession.py:1027` | member |
| `_build_conversation_text` | `build_mini_dist\tea_agent\session_memory_component.py:196` | member |
| `_build_lite_session` | `build_mini_dist\tea_agent\agent.py:285` | member |
| `_build_online_session` | `build_mini_dist\tea_agent\agent.py:315` | member |
| `_build_tool_stats` | `build_mini_dist\tea_agent\reflection.py:279` | member |
| `_build_tools` | `build_mini_dist\tea_agent\litesession.py:80` | member |
| `_build_tools` | `build_mini_dist\tea_agent\onlinesession.py:1043` | member |
| `_calculate_similarity` | `build_mini_dist\tea_agent\session_memory_component.py:319` | member |
| `_call_api` | `build_mini_dist\tea_agent\litesession.py:201` | member |
| `_chat_impl` | `build_mini_dist\tea_agent\agent.py:419` | member |
| `_check_dependencies` | `build_mini_dist\tea_agent\tlk.py:351` | member |
| `_compress_json_args` | `build_mini_dist\tea_agent\basesession.py:300` | member |
| `_compress_tool_content` | `build_mini_dist\tea_agent\basesession.py:228` | member |
| `_compress_tool_rounds` | `build_mini_dist\tea_agent\basesession.py:459` | member |
| `_compute_embedding_similarity` | `build_mini_dist\tea_agent\memory.py:302` | member |
| `_compute_embedding_similarity_cached` | `build_mini_dist\tea_agent\memory.py:360` | member |
| `_compute_recency` | `build_mini_dist\tea_agent\memory.py:240` | member |
| `_compute_relevance` | `build_mini_dist\tea_agent\memory.py:191` | member |
| `_compute_similarity` | `build_mini_dist\tea_agent\memory.py:805` | member |
| `_conversations_to_text` | `build_mini_dist\tea_agent\onlinesession.py:620` | member |
| `_default_system_prompt` | `build_mini_dist\tea_agent\litesession.py:72` | member |
| `_do_async_summaries` | `build_mini_dist\tea_agent\agent.py:517` | member |
| `_do_task_evaluation` | `build_mini_dist\tea_agent\agent.py:522` | member |
| `_ensure_store` | `build_mini_dist\tea_agent\project_memory.py:30` | member |
| `_ensure_tables` | `build_mini_dist\tea_agent\scheduler_storage.py:31` | member |
| `_execute_tool` | `build_mini_dist\tea_agent\litesession.py:300` | member |
| `_execute_tool_loop` | `build_mini_dist\tea_agent\onlinesession.py:1039` | member |
| `_extract_keywords` | `build_mini_dist\tea_agent\memory.py:218` | member |
| `_extract_with_llm` | `build_mini_dist\tea_agent\session_memory_component.py:337` | member |
| `_fallback_extract` | `build_mini_dist\tea_agent\session_memory_component.py:388` | member |
| `_find_duplicate` | `build_mini_dist\tea_agent\memory.py:824` | member |
| `_find_recent_boundary` | `build_mini_dist\tea_agent\onlinesession.py:648` | member |
| `_fix_ast` | `build_mini_dist\tea_agent\auto_fix.py:158` | member |
| `_fix_llm` | `build_mini_dist\tea_agent\auto_fix.py:182` | member |
| `_fix_ruff` | `build_mini_dist\tea_agent\auto_fix.py:131` | member |
| `_generate_summary` | `build_mini_dist\tea_agent\memory.py:1121` | member |
| `_get_effective_params` | `build_mini_dist\tea_agent\onlinesession.py:892` | member |
| `_get_embedding_engine` | `build_mini_dist\tea_agent\memory.py:289` | member |
| `_get_summarize_client` | `build_mini_dist\tea_agent\onlinesession.py:886` | member |
| `_get_summarize_client` | `build_mini_dist\tea_agent\session_memory_component.py:189` | member |
| `_get_unextracted_conversations` | `build_mini_dist\tea_agent\session_memory_component.py:300` | member |
| `_guess_tool_threshold` | `build_mini_dist\tea_agent\basesession.py:409` | member |
| `_history_summary` | `build_mini_dist\tea_agent\onlinesession.py:868` | member |
| `_history_summary` | `build_mini_dist\tea_agent\onlinesession.py:870` | member |
| `_init_llm` | `build_mini_dist\tea_agent\auto_fix.py:39` | member |
| `_init_session` | `build_mini_dist\tea_agent\agent.py:264` | member |
| `_init_session_info_str` | `build_mini_dist\tea_agent\agent.py:179` | member |
| `_init_storage` | `build_mini_dist\tea_agent\agent.py:254` | member |
| `_init_toolkit` | `build_mini_dist\tea_agent\agent.py:235` | member |
| `_inject_os_info` | `build_mini_dist\tea_agent\onlinesession.py:965` | member |
| `_is_duplicate` | `build_mini_dist\tea_agent\session_memory_component.py:415` | member |
| `_last_cheap_usage` | `build_mini_dist\tea_agent\onlinesession.py:863` | member |
| `_last_cheap_usage` | `build_mini_dist\tea_agent\onlinesession.py:865` | member |
| `_last_usage` | `build_mini_dist\tea_agent\onlinesession.py:858` | member |
| `_last_usage` | `build_mini_dist\tea_agent\onlinesession.py:860` | member |
| `_load_config` | `build_mini_dist\tea_agent\agent.py:192` | member |
| `_load_config` | `build_mini_dist\tea_agent\session_memory_component.py:246` | member |
| `_load_topic_history_into_session` | `build_mini_dist\tea_agent\agent.py:185` | member |
| `_mark_conversations_extracted` | `build_mini_dist\tea_agent\session_memory_component.py:176` | member |
| `_mark_conversations_extracted` | `build_mini_dist\tea_agent\session_memory_component.py:443` | member |
| `_merge_conversations` | `build_mini_dist\tea_agent\session_memory_component.py:311` | member |
| `_merge_memory` | `build_mini_dist\tea_agent\memory.py:856` | member |
| `_new_id` | `build_mini_dist\tea_agent\project_memory.py:103` | member |
| `_notify` | `build_mini_dist\tea_agent\agent.py:375` | member |
| `_notify` | `build_mini_dist\tea_agent\onlinesession.py:1082` | member |
| `_notify_prompt_evolved` | `build_mini_dist\tea_agent\onlinesession.py:1095` | member |
| `_notify_reflection_done` | `build_mini_dist\tea_agent\onlinesession.py:1092` | member |
| `_parse_tool_calls` | `build_mini_dist\tea_agent\litesession.py:266` | member |
| `_post_chat_pipeline` | `build_mini_dist\tea_agent\agent.py:467` | member |
| `_prefix_for` | `build_mini_dist\tea_agent\memory.py:688` | member |
| `_probe_thinking_support` | `build_mini_dist\tea_agent\onlinesession.py:86` | member |
| `_process_response` | `build_mini_dist\tea_agent\litesession.py:219` | member |
| `_process_stream_with_reasoning` | `build_mini_dist\tea_agent\onlinesession.py:904` | member |
| `_purge_cache` | `build_mini_dist\tea_agent\tlk.py:342` | member |
| `_read` | `build_mini_dist\tea_agent\project_memory.py:36` | member |
| `_record_tool_to_trace` | `build_mini_dist\tea_agent\onlinesession.py:416` | member |
| `_repair_incomplete_tool_chains` | `build_mini_dist\tea_agent\basesession.py:548` | member |
| `_rounds_collector` | `build_mini_dist\tea_agent\onlinesession.py:853` | member |
| `_rounds_collector` | `build_mini_dist\tea_agent\onlinesession.py:855` | member |
| `_scan_ast_docstring` | `build_mini_dist\tea_agent\auto_fix.py:83` | member |
| `_scan_ruff` | `build_mini_dist\tea_agent\auto_fix.py:59` | member |
| `_score_memory` | `build_mini_dist\tea_agent\memory.py:160` | member |
| `_score_memory_cached` | `build_mini_dist\tea_agent\memory.py:169` | member |
| `_semantic_summary` | `build_mini_dist\tea_agent\onlinesession.py:873` | member |
| `_semantic_summary` | `build_mini_dist\tea_agent\onlinesession.py:875` | member |
| `_setup_default_pipeline` | `build_mini_dist\tea_agent\onlinesession.py:998` | member |
| `_start_background_services` | `build_mini_dist\tea_agent\agent.py:352` | member |
| `_strip_reasoning_content` | `build_mini_dist\tea_agent\basesession.py:214` | member |
| `_tool_chain_summary` | `build_mini_dist\tea_agent\onlinesession.py:878` | member |
| `_tool_chain_summary` | `build_mini_dist\tea_agent\onlinesession.py:880` | member |
| `_touch_selected` | `build_mini_dist\tea_agent\memory.py:276` | member |
| `_track_api_usage` | `build_mini_dist\tea_agent\onlinesession.py:170` | member |
| `_trim_messages` | `build_mini_dist\tea_agent\basesession.py:718` | member |
| `_update_dynamic_thresholds` | `build_mini_dist\tea_agent\memory.py:387` | member |
| `_write` | `build_mini_dist\tea_agent\project_memory.py:47` | member |
| `accumulate_tool_calls_from_delta` | `build_mini_dist\tea_agent\onlinesession.py:254` | member |
| `add` | `build_mini_dist\tea_agent\project_memory.py:52` | member |
| `add_assistant_message` | `build_mini_dist\tea_agent\basesession.py:197` | member |
| `add_tool_result` | `build_mini_dist\tea_agent\basesession.py:201` | member |
| `add_tool_result` | `build_mini_dist\tea_agent\onlinesession.py:427` | member |
| `add_user_message` | `build_mini_dist\tea_agent\basesession.py:184` | member |
| `apply_changes` | `build_mini_dist\tea_agent\config.py:247` | member |
| `auto_dedup` | `build_mini_dist\tea_agent\memory.py:1054` | member |
| `build_evolve_prompt` | `build_mini_dist\tea_agent\prompt_manager.py:115` | member |
| `build_extraction_prompt` | `build_mini_dist\tea_agent\memory.py:734` | member |
| `build_reflection_prompt` | `build_mini_dist\tea_agent\reflection.py:154` | member |
| `build_tools` | `build_mini_dist\tea_agent\onlinesession.py:329` | member |
| `call_summarize_api` | `build_mini_dist\tea_agent\onlinesession.py:227` | member |
| `call_tool` | `build_mini_dist\tea_agent\tlk.py:294` | member |
| `chat` | `build_mini_dist\tea_agent\agent.py:386` | member |
| `chat` | `build_mini_dist\tea_agent\litesession.py:97` | member |
| `chat_stream` | `build_mini_dist\tea_agent\basesession.py:171` | member |
| `chat_stream` | `build_mini_dist\tea_agent\onlinesession.py:1098` | member |
| `close` | `build_mini_dist\tea_agent\agent.py:616` | member |
| `close` | `build_mini_dist\tea_agent\auto_fix.py:278` | member |
| `close` | `build_mini_dist\tea_agent\litesession.py:325` | member |
| `close` | `build_mini_dist\tea_agent\onlinesession.py:1160` | member |
| `collect_api_error_round` | `build_mini_dist\tea_agent\onlinesession.py:469` | member |
| `collect_assistant_text_round` | `build_mini_dist\tea_agent\onlinesession.py:460` | member |
| `collect_assistant_tool_calls_round` | `build_mini_dist\tea_agent\onlinesession.py:441` | member |
| `collect_interruption_round` | `build_mini_dist\tea_agent\onlinesession.py:481` | member |
| `collect_max_iterations_round` | `build_mini_dist\tea_agent\onlinesession.py:475` | member |
| `collect_tool_call_round` | `build_mini_dist\tea_agent\onlinesession.py:434` | member |
| `config` | `build_mini_dist\tea_agent\agent.py:636` | member |
| `create_chat_stream` | `build_mini_dist\tea_agent\onlinesession.py:174` | member |
| `current_prompt` | `build_mini_dist\tea_agent\prompt_manager.py:90` | member |
| `current_prompt_id` | `build_mini_dist\tea_agent\prompt_manager.py:102` | member |
| `current_topic_id` | `build_mini_dist\tea_agent\agent.py:653` | member |
| `current_topic_id` | `build_mini_dist\tea_agent\agent.py:657` | member |
| `current_version` | `build_mini_dist\tea_agent\prompt_manager.py:97` | member |
| `data_dir_abs` | `build_mini_dist\tea_agent\config.py:118` | member |
| `db` | `build_mini_dist\tea_agent\agent.py:650` | member |
| `db_path_abs` | `build_mini_dist\tea_agent\config.py:103` | member |
| `degrade_by_age` | `build_mini_dist\tea_agent\memory.py:465` | member |
| `delete_script` | `build_mini_dist\tea_agent\scheduler_storage.py:110` | member |
| `detect_duplicates` | `build_mini_dist\tea_agent\memory.py:990` | member |
| `disable_step` | `build_mini_dist\tea_agent\session_pipeline.py:83` | member |
| `duration_seconds` | `build_mini_dist\tea_agent\reflection.py:49` | member |
| `enable_step` | `build_mini_dist\tea_agent\session_pipeline.py:78` | member |
| `enable_thinking` | `build_mini_dist\tea_agent\onlinesession.py:848` | member |
| `enable_thinking` | `build_mini_dist\tea_agent\onlinesession.py:850` | member |
| `evolve` | `build_mini_dist\tea_agent\prompt_manager.py:167` | member |
| `execute` | `build_mini_dist\tea_agent\session_pipeline.py:107` | member |
| `execute_tool_call` | `build_mini_dist\tea_agent\onlinesession.py:339` | member |
| `extract_from_topic` | `build_mini_dist\tea_agent\session_memory_component.py:259` | member |
| `finish_trace` | `build_mini_dist\tea_agent\reflection.py:110` | member |
| `fix` | `build_mini_dist\tea_agent\auto_fix.py:113` | member |
| `fix_all` | `build_mini_dist\tea_agent\auto_fix.py:237` | member |
| `format_memories` | `build_mini_dist\tea_agent\memory.py:660` | member |
| `format_memories` | `build_mini_dist\tea_agent\project_memory.py:115` | member |
| `generate_reflection` | `build_mini_dist\tea_agent\reflection.py:194` | member |
| `get` | `build_mini_dist\tea_agent\config.py:217` | member |
| `get_all` | `build_mini_dist\tea_agent\project_memory.py:81` | member |
| `get_cheap_usage` | `build_mini_dist\tea_agent\onlinesession.py:288` | member |
| `get_effective_params` | `build_mini_dist\tea_agent\config.py:151` | member |
| `get_enabled_steps` | `build_mini_dist\tea_agent\session_pipeline.py:100` | member |
| `get_extraction_stats` | `build_mini_dist\tea_agent\session_memory_component.py:450` | member |
| `get_injected_memories` | `build_mini_dist\tea_agent\session_memory_component.py:205` | member |
| `get_last_usage` | `build_mini_dist\tea_agent\onlinesession.py:285` | member |
| `get_memory_stats` | `build_mini_dist\tea_agent\session_memory_component.py:467` | member |
| `get_recent_messages` | `build_mini_dist\tea_agent\basesession.py:209` | member |
| `get_script` | `build_mini_dist\tea_agent\scheduler_storage.py:86` | member |
| `get_stats` | `build_mini_dist\tea_agent\prompt_manager.py:266` | member |
| `get_stats` | `build_mini_dist\tea_agent\reflection.py:300` | member |
| `get_total_usage` | `build_mini_dist\tea_agent\onlinesession.py:291` | member |
| `ingest_extracted` | `build_mini_dist\tea_agent\memory.py:924` | member |
| `initialize` | `build_mini_dist\tea_agent\onlinesession.py:83` | member |
| `initialize` | `build_mini_dist\tea_agent\onlinesession.py:326` | member |
| `initialize` | `build_mini_dist\tea_agent\onlinesession.py:522` | member |
| `initialize` | `build_mini_dist\tea_agent\prompt_manager.py:62` | member |
| `initialize` | `build_mini_dist\tea_agent\session_memory_component.py:40` | member |
| `inject_memories` | `build_mini_dist\tea_agent\session_memory_component.py:59` | member |
| `interrupt` | `build_mini_dist\tea_agent\basesession.py:710` | member |
| `interrupt` | `build_mini_dist\tea_agent\litesession.py:321` | member |
| `is_configured` | `build_mini_dist\tea_agent\config.py:40` | member |
| `is_configured` | `build_mini_dist\tea_agent\config.py:137` | member |
| `is_extraction_needed` | `build_mini_dist\tea_agent\memory.py:1153` | member |
| `kb_dir_abs` | `build_mini_dist\tea_agent\config.py:113` | member |
| `last_prompt_suggestion` | `build_mini_dist\tea_agent\reflection.py:296` | member |
| `list_scripts` | `build_mini_dist\tea_agent\scheduler_storage.py:98` | member |
| `list_steps` | `build_mini_dist\tea_agent\session_pipeline.py:159` | member |
| `list_tasks` | `build_mini_dist\tea_agent\scheduler_storage.py:138` | member |
| `list_versions` | `build_mini_dist\tea_agent\prompt_manager.py:262` | member |
| `list_versions` | `build_mini_dist\tea_agent\tlk.py:666` | member |
| `list_versions_for_llm` | `build_mini_dist\tea_agent\tlk.py:701` | member |
| `llm_adjust_priorities` | `build_mini_dist\tea_agent\memory.py:543` | member |
| `load_history` | `build_mini_dist\tea_agent\basesession.py:639` | member |
| `load_topic_history` | `build_mini_dist\tea_agent\agent.py:586` | member |
| `manual_set` | `build_mini_dist\tea_agent\prompt_manager.py:275` | member |
| `merge_duplicates` | `build_mini_dist\tea_agent\memory.py:1018` | member |
| `messages` | `build_mini_dist\tea_agent\onlinesession.py:843` | member |
| `messages` | `build_mini_dist\tea_agent\onlinesession.py:845` | member |
| `name` | `build_mini_dist\tea_agent\onlinesession.py:80` | member |
| `name` | `build_mini_dist\tea_agent\onlinesession.py:323` | member |
| `name` | `build_mini_dist\tea_agent\onlinesession.py:519` | member |
| `name` | `build_mini_dist\tea_agent\session_memory_component.py:36` | member |
| `parse_extraction_result` | `build_mini_dist\tea_agent\memory.py:742` | member |
| `parse_reflection_result` | `build_mini_dist\tea_agent\reflection.py:183` | member |
| `parse_tool_calls_from_stream` | `build_mini_dist\tea_agent\onlinesession.py:487` | member |
| `prepare_script_for_execution` | `build_mini_dist\tea_agent\scheduler_storage.py:152` | member |
| `record_tool_call` | `build_mini_dist\tea_agent\reflection.py:101` | member |
| `reflect_and_summarize` | `build_mini_dist\tea_agent\memory.py:1075` | member |
| `register_step` | `build_mini_dist\tea_agent\session_pipeline.py:43` | member |
| `reload` | `build_mini_dist\tea_agent\prompt_manager.py:106` | member |
| `reload` | `build_mini_dist\tea_agent\tlk.py:405` | member |
| `reload_from_dict` | `build_mini_dist\tea_agent\config.py:270` | member |
| `remove_step` | `build_mini_dist\tea_agent\session_pipeline.py:94` | member |
| `report` | `build_mini_dist\tea_agent\auto_fix.py:270` | member |
| `reset_cheap_usage` | `build_mini_dist\tea_agent\onlinesession.py:281` | member |
| `reset_interrupt` | `build_mini_dist\tea_agent\basesession.py:714` | member |
| `reset_session_state` | `build_mini_dist\tea_agent\onlinesession.py:1073` | member |
| `reset_usage` | `build_mini_dist\tea_agent\onlinesession.py:277` | member |
| `resolve` | `build_mini_dist\tea_agent\config.py:67` | member |
| `rollback` | `build_mini_dist\tea_agent\prompt_manager.py:232` | member |
| `rollback` | `build_mini_dist\tea_agent\tlk.py:636` | member |
| `rollback_for_llm` | `build_mini_dist\tea_agent\tlk.py:694` | member |
| `save` | `build_mini_dist\tea_agent\tlk.py:504` | member |
| `save_script` | `build_mini_dist\tea_agent\scheduler_storage.py:70` | member |
| `save_task` | `build_mini_dist\tea_agent\scheduler_storage.py:122` | member |
| `scan` | `build_mini_dist\tea_agent\auto_fix.py:49` | member |
| `search` | `build_mini_dist\tea_agent\project_memory.py:86` | member |
| `select_memories` | `build_mini_dist\tea_agent\memory.py:67` | member |
| `sess` | `build_mini_dist\tea_agent\agent.py:642` | member |
| `sess` | `build_mini_dist\tea_agent\agent.py:644` | member |
| `session` | `build_mini_dist\tea_agent\agent.py:647` | member |
| `set` | `build_mini_dist\tea_agent\config.py:223` | member |
| `set_step_position` | `build_mini_dist\tea_agent\session_pipeline.py:88` | member |
| `should_reflect` | `build_mini_dist\tea_agent\reflection.py:119` | member |
| `start_trace` | `build_mini_dist\tea_agent\reflection.py:91` | member |
| `success_rate` | `build_mini_dist\tea_agent\reflection.py:41` | member |
| `summarize_old_history` | `build_mini_dist\tea_agent\onlinesession.py:525` | member |
| `supports_vision` | `build_mini_dist\tea_agent\config.py:45` | member |
| `to_dict` | `build_mini_dist\tea_agent\auto_fix.py:27` | member |
| `to_dict` | `build_mini_dist\tea_agent\config.py:276` | member |
| `toolkit` | `build_mini_dist\tea_agent\agent.py:639` | member |
| `toolkit_dir_abs` | `build_mini_dist\tea_agent\config.py:108` | member |
| `toolkit_reload` | `build_mini_dist\tea_agent\agent.py:365` | member |
| `toolkit_save` | `build_mini_dist\tea_agent\agent.py:360` | member |
| `trigger_memory_extraction` | `build_mini_dist\tea_agent\session_memory_component.py:115` | member |
| `update_script_result` | `build_mini_dist\tea_agent\scheduler_storage.py:180` | member |
| `update_tools` | `build_mini_dist\tea_agent\onlinesession.py:1051` | member |
| `verify` | `build_mini_dist\tea_agent\auto_fix.py:258` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `CRITICAL_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:39` | variable |
| `DEFAULT_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\prompt_manager.py:17` | variable |
| `ESSENTIAL_TOOLS` | `build_mini_dist\tea_agent\onlinesession.py:303` | variable |
| `EVOLVE_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\prompt_manager.py:31` | variable |
| `EXTRACTION_PROMPT` | `build_mini_dist\tea_agent\session_memory_component.py:215` | variable |
| `EXTRACTION_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\memory.py:713` | variable |
| `FIX_PROMPT` | `build_mini_dist\tea_agent\auto_fix.py:15` | variable |
| `HAS_YAML` | `build_mini_dist\tea_agent\config.py:23` | variable |
| `HAS_YAML` | `build_mini_dist\tea_agent\config.py:25` | variable |
| `HIGH_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:40` | variable |
| `LLM_ADJUST_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\memory.py:528` | variable |
| `MAX_CRITICAL_INJECT` | `build_mini_dist\tea_agent\memory.py:27` | variable |
| `MAX_ENTRIES` | `build_mini_dist\tea_agent\project_memory.py:17` | variable |
| `MAX_INJECT` | `build_mini_dist\tea_agent\memory.py:26` | variable |
| `MAX_LLM_ADJUSTMENTS` | `build_mini_dist\tea_agent\memory.py:44` | variable |
| `MEDIUM_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:41` | variable |
| `MIN_HIGH_INJECT` | `build_mini_dist\tea_agent\memory.py:28` | variable |
| `MIN_LOW_INJECT` | `build_mini_dist\tea_agent\memory.py:30` | variable |
| `MIN_MEDIUM_INJECT` | `build_mini_dist\tea_agent\memory.py:29` | variable |
| `PRIORITY_CRITICAL` | `build_mini_dist\tea_agent\memory.py:14` | variable |
| `PRIORITY_HIGH` | `build_mini_dist\tea_agent\memory.py:15` | variable |
| `PRIORITY_LABELS` | `build_mini_dist\tea_agent\memory.py:19` | variable |
| `PRIORITY_LOW` | `build_mini_dist\tea_agent\memory.py:17` | variable |
| `PRIORITY_MEDIUM` | `build_mini_dist\tea_agent\memory.py:16` | variable |
| `PROVIDERS` | `build_mini_dist\tea_agent\providers.py:12` | variable |
| `PROVIDERS` | `build_mini_dist\tea_agent\providers.py:14` | variable |
| `REFLECTION_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\reflection.py:56` | variable |
| `RUFF_SELECT` | `build_mini_dist\tea_agent\auto_fix.py:14` | variable |
| `SCRIPTS_DIR` | `build_mini_dist\tea_agent\scheduler_storage.py:23` | variable |
| `STATE_FILE` | `build_mini_dist\tea_agent\scheduler_storage.py:20` | variable |
| `STORE_FILE` | `build_mini_dist\tea_agent\project_memory.py:18` | variable |
| `TeaAgent` | `build_mini_dist\tea_agent\agent.py:665` | function |
| `_BASE_CRITICAL_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:34` | variable |
| `_BASE_HIGH_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:35` | variable |
| `_BASE_MEDIUM_DEGRADE_DAYS` | `build_mini_dist\tea_agent\memory.py:36` | variable |
| `_CACHE_BLACKLIST` | `build_mini_dist\tea_agent\tlk.py:261` | variable |
| `_CACHE_TTL` | `build_mini_dist\tea_agent\tlk.py:260` | variable |
| `_COMPACT_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\onlinesession.py:674` | variable |
| `_CONFIG_TYPES` | `build_mini_dist\tea_agent\config.py:207` | variable |
| `_DEFAULT_TOOL_THRESHOLD` | `build_mini_dist\tea_agent\basesession.py:132` | variable |
| `_HAVE_GUI_TOPIC_SUMMARY` | `build_mini_dist\tea_agent\agent_pipeline.py:76` | variable |
| `_HAVE_GUI_TOPIC_SUMMARY` | `build_mini_dist\tea_agent\agent_pipeline.py:78` | variable |
| `_KB_THRESHOLD` | `build_mini_dist\tea_agent\basesession.py:131` | variable |
| `_MODE_BEHAVIORS` | `build_mini_dist\tea_agent\agent.py:69` | variable |
| `_RUNTIME_CONFIG_KEYS` | `build_mini_dist\tea_agent\config.py:196` | variable |
| `_SOURCE_EXTENSIONS` | `build_mini_dist\tea_agent\basesession.py:134` | variable |
| `_TEXT_EXTENSIONS` | `build_mini_dist\tea_agent\basesession.py:141` | variable |
| `_TEXT_FILE_THRESHOLD` | `build_mini_dist\tea_agent\basesession.py:133` | variable |
| `_VALID_MODES` | `build_mini_dist\tea_agent\agent.py:99` | variable |
| `_VALID_MODES` | `build_mini_dist\tea_agent\onlinesession.py:52` | variable |
| `__all__` | `build_mini_dist\tea_agent\__init__.py:6` | variable |
| `__version__` | `build_mini_dist\tea_agent\__init__.py:4` | variable |
| `_active_config_path` | `build_mini_dist\tea_agent\config.py:283` | variable |
| `_auto_generate_skill_doc` | `build_mini_dist\tea_agent\tlk.py:129` | function |
| `_compress_value` | `build_mini_dist\tea_agent\basesession.py:355` | function |
| `_config_cache` | `build_mini_dist\tea_agent\config.py:587` | variable |
| `_current_agent` | `build_mini_dist\tea_agent\session_ref.py:20` | variable |
| `_current_session` | `build_mini_dist\tea_agent\session_ref.py:19` | variable |
| `_data_dir_abs` | `build_mini_dist\tea_agent\config.py:62` | variable |
| `_db_path_abs` | `build_mini_dist\tea_agent\config.py:63` | variable |
| `_empty_usage` | `build_mini_dist\tea_agent\agent_pipeline.py:16` | function |
| `_fix_single_quotes` | `build_mini_dist\tea_agent\basesession.py:74` | function |
| `_get_cheap_params` | `build_mini_dist\tea_agent\session_memory_component.py:25` | function |
| `_json` | `build_mini_dist\tea_agent\basesession.py:321` | namespace |
| `_json_gt` | `build_mini_dist\tea_agent\basesession.py:419` | namespace |
| `_json_lh` | `build_mini_dist\tea_agent\basesession.py:678` | namespace |
| `_kb_dir_abs` | `build_mini_dist\tea_agent\config.py:65` | variable |
| `_last_config_path` | `build_mini_dist\tea_agent\config.py:280` | variable |
| `_logging_debug` | `build_mini_dist\tea_agent\logging_setup.py:18` | variable |
| `_logging_initialized` | `build_mini_dist\tea_agent\logging_setup.py:17` | variable |
| `_merge_usage` | `build_mini_dist\tea_agent\agent_pipeline.py:20` | function |
| `_pick_top_by_priority` | `build_mini_dist\tea_agent\memory.py:128` | function |
| `_resolve` | `build_mini_dist\tea_agent\config.py:89` | function |
| `_set_root_level` | `build_mini_dist\tea_agent\logging_setup.py:78` | function |
| `_setter_info` | `build_mini_dist\tea_agent\session_ref.py:21` | variable |
| `_sref` | `build_mini_dist\tea_agent\agent.py:30` | namespace |
| `_toolkit_dir_abs` | `build_mini_dist\tea_agent\config.py:64` | variable |
| `analyze_intent` | `build_mini_dist\tea_agent\onlinesession.py:47` | function |
| `api_key` | `build_mini_dist\tea_agent\config.py:30` | variable |
| `api_key` | `build_mini_dist\tea_agent\config.py:133` | variable |
| `api_url` | `build_mini_dist\tea_agent\config.py:31` | variable |
| `api_url` | `build_mini_dist\tea_agent\config.py:131` | variable |
| `app_font_size` | `build_mini_dist\tea_agent\config.py:193` | variable |
| `auto_summary` | `build_mini_dist\tea_agent\agent_pipeline.py:82` | function |
| `chat_page_size` | `build_mini_dist\tea_agent\config.py:189` | variable |
| `cheap_model` | `build_mini_dist\tea_agent\config.py:145` | variable |
| `check_meta` | `build_mini_dist\tea_agent\tlk.py:412` | function |
| `clear` | `build_mini_dist\tea_agent\session_ref.py:64` | function |
| `create_default_config` | `build_mini_dist\tea_agent\config.py:491` | function |
| `data_dir` | `build_mini_dist\tea_agent\config.py:56` | variable |
| `db_path` | `build_mini_dist\tea_agent\config.py:57` | variable |
| `description` | `build_mini_dist\tea_agent\session_pipeline.py:25` | variable |
| `detect_mode` | `build_mini_dist\tea_agent\onlinesession.py:55` | function |
| `dimension` | `build_mini_dist\tea_agent\config.py:134` | variable |
| `do_async_summaries` | `build_mini_dist\tea_agent\agent_pipeline.py:26` | function |
| `duration_ms` | `build_mini_dist\tea_agent\reflection.py:25` | variable |
| `embedding` | `build_mini_dist\tea_agent\config.py:146` | variable |
| `enable_thinking` | `build_mini_dist\tea_agent\config.py:178` | variable |
| `enabled` | `build_mini_dist\tea_agent\session_pipeline.py:24` | variable |
| `end_time` | `build_mini_dist\tea_agent\reflection.py:38` | variable |
| `ensure_config_dir` | `build_mini_dist\tea_agent\config.py:404` | function |
| `error` | `build_mini_dist\tea_agent\reflection.py:24` | variable |
| `error` | `build_mini_dist\tea_agent\reflection.py:36` | variable |
| `extra_iterations_on_continue` | `build_mini_dist\tea_agent\config.py:186` | variable |
| `extract_mode` | `build_mini_dist\tea_agent\onlinesession.py:67` | function |
| `filter_tools` | `build_mini_dist\tea_agent\onlinesession.py:306` | function |
| `font_size` | `build_mini_dist\tea_agent\config.py:192` | variable |
| `function` | `build_mini_dist\tea_agent\litesession.py:279` | variable |
| `generate_config` | `build_mini_dist\tea_agent\providers.py:183` | function |
| `get_active_config_path` | `build_mini_dist\tea_agent\config.py:290` | function |
| `get_agent` | `build_mini_dist\tea_agent\session_ref.py:44` | function |
| `get_bigrams` | `build_mini_dist\tea_agent\session_memory_component.py:325` | function |
| `get_config` | `build_mini_dist\tea_agent\config.py:589` | function |
| `get_provider` | `build_mini_dist\tea_agent\providers.py:172` | function |
| `get_scheduler_storage` | `build_mini_dist\tea_agent\scheduler_storage.py:194` | function |
| `get_session` | `build_mini_dist\tea_agent\session_ref.py:24` | function |
| `get_session_info` | `build_mini_dist\tea_agent\session_ref.py:77` | function |
| `has_tool` | `build_mini_dist\tea_agent\onlinesession.py:314` | function |
| `history_l2_max` | `build_mini_dist\tea_agent\config.py:190` | variable |
| `history_l3_batch` | `build_mini_dist\tea_agent\config.py:191` | variable |
| `interrupted` | `build_mini_dist\tea_agent\reflection.py:35` | variable |
| `is_active` | `build_mini_dist\tea_agent\session_ref.py:72` | function |
| `kb_dir` | `build_mini_dist\tea_agent\config.py:59` | variable |
| `keep_turns` | `build_mini_dist\tea_agent\config.py:181` | variable |
| `l2_to_l3_summary` | `build_mini_dist\tea_agent\agent_pipeline.py:45` | function |
| `list_providers` | `build_mini_dist\tea_agent\providers.py:156` | function |
| `load_config` | `build_mini_dist\tea_agent\config.py:294` | function |
| `logger` | `build_mini_dist\tea_agent\agent.py:48` | variable |
| `logger` | `build_mini_dist\tea_agent\agent_background.py:13` | variable |
| `logger` | `build_mini_dist\tea_agent\agent_pipeline.py:13` | variable |
| `logger` | `build_mini_dist\tea_agent\auto_fix.py:13` | variable |
| `logger` | `build_mini_dist\tea_agent\basesession.py:12` | variable |
| `logger` | `build_mini_dist\tea_agent\litesession.py:19` | variable |
| `logger` | `build_mini_dist\tea_agent\memory.py:11` | variable |
| `logger` | `build_mini_dist\tea_agent\onlinesession.py:42` | variable |
| `logger` | `build_mini_dist\tea_agent\onlinesession.py:299` | variable |
| `logger` | `build_mini_dist\tea_agent\onlinesession.py:513` | variable |
| `logger` | `build_mini_dist\tea_agent\project_memory.py:12` | variable |
| `logger` | `build_mini_dist\tea_agent\prompt_manager.py:14` | variable |
| `logger` | `build_mini_dist\tea_agent\reflection.py:17` | variable |
| `logger` | `build_mini_dist\tea_agent\session_memory_component.py:22` | variable |
| `logger` | `build_mini_dist\tea_agent\session_pipeline.py:17` | variable |
| `logger` | `build_mini_dist\tea_agent\session_ref.py:17` | variable |
| `logger` | `build_mini_dist\tea_agent\tlk.py:33` | variable |
| `main_model` | `build_mini_dist\tea_agent\config.py:144` | variable |
| `max_assistant_content` | `build_mini_dist\tea_agent\config.py:183` | variable |
| `max_context_tokens` | `build_mini_dist\tea_agent\config.py:36` | variable |
| `max_history` | `build_mini_dist\tea_agent\config.py:176` | variable |
| `max_iterations` | `build_mini_dist\tea_agent\config.py:177` | variable |
| `max_tokens` | `build_mini_dist\tea_agent\config.py:35` | variable |
| `max_tool_output` | `build_mini_dist\tea_agent\config.py:182` | variable |
| `memory_dedup_threshold` | `build_mini_dist\tea_agent\config.py:188` | variable |
| `memory_extraction_threshold` | `build_mini_dist\tea_agent\config.py:187` | variable |
| `meta_toolkit_list_versions` | `build_mini_dist\tea_agent\tlk.py:107` | function |
| `meta_toolkit_reload` | `build_mini_dist\tea_agent\tlk.py:41` | function |
| `meta_toolkit_rollback` | `build_mini_dist\tea_agent\tlk.py:83` | function |
| `meta_toolkit_save` | `build_mini_dist\tea_agent\tlk.py:56` | function |
| `mode_params` | `build_mini_dist\tea_agent\config.py:149` | variable |
| `model_name` | `build_mini_dist\tea_agent\config.py:32` | variable |
| `model_name` | `build_mini_dist\tea_agent\config.py:132` | variable |
| `np` | `build_mini_dist\tea_agent\memory.py:341` | namespace |
| `np` | `build_mini_dist\tea_agent\memory.py:378` | namespace |
| `np` | `build_mini_dist\tea_agent\memory.py:996` | namespace |
| `options` | `build_mini_dist\tea_agent\config.py:33` | variable |
| `osp` | `build_mini_dist\tea_agent\tlk.py:20` | namespace |
| `paths` | `build_mini_dist\tea_agent\config.py:147` | variable |
| `position` | `build_mini_dist\tea_agent\session_pipeline.py:26` | variable |
| `relaxed_json_loads` | `build_mini_dist\tea_agent\basesession.py:15` | function |
| `save_config` | `build_mini_dist\tea_agent\config.py:414` | function |
| `save_evolve_script` | `build_mini_dist\tea_agent\scheduler_storage.py:199` | function |
| `set_active_config_path` | `build_mini_dist\tea_agent\config.py:285` | function |
| `set_agent` | `build_mini_dist\tea_agent\session_ref.py:49` | function |
| `set_debug` | `build_mini_dist\tea_agent\logging_setup.py:84` | function |
| `set_session` | `build_mini_dist\tea_agent\session_ref.py:29` | function |
| `setup_logging` | `build_mini_dist\tea_agent\logging_setup.py:20` | function |
| `skills_dir` | `build_mini_dist\tea_agent\config.py:60` | variable |
| `start_scheduler` | `build_mini_dist\tea_agent\agent_background.py:42` | function |
| `start_self_evolve_thread` | `build_mini_dist\tea_agent\agent_background.py:16` | function |
| `start_time` | `build_mini_dist\tea_agent\reflection.py:37` | variable |
| `status_cb` | `build_mini_dist\tea_agent\agent.py:433` | function |
| `storage` | `build_mini_dist\tea_agent\scheduler_storage.py:269` | variable |
| `stream_cb` | `build_mini_dist\tea_agent\agent.py:410` | function |
| `stream_cb` | `build_mini_dist\tea_agent\agent.py:427` | function |
| `switch_provider` | `build_mini_dist\tea_agent\providers.py:204` | function |
| `temperature` | `build_mini_dist\tea_agent\config.py:34` | variable |
| `tool_calls` | `build_mini_dist\tea_agent\reflection.py:32` | variable |
| `toolkit` | `build_mini_dist\tea_agent\tlk.py:38` | variable |
| `toolkit_dir` | `build_mini_dist\tea_agent\config.py:58` | variable |
| `top_p` | `build_mini_dist\tea_agent\config.py:37` | variable |
| `topic_id` | `build_mini_dist\tea_agent\reflection.py:30` | variable |
| `total_iterations` | `build_mini_dist\tea_agent\reflection.py:33` | variable |
| `type` | `build_mini_dist\tea_agent\litesession.py:278` | variable |
| `used_tools` | `build_mini_dist\tea_agent\reflection.py:34` | variable |
| `user_msg` | `build_mini_dist\tea_agent\reflection.py:31` | variable |

## 模块 `build_mini_dist\tea_agent\evaluation`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `EvalResult` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:37` | class |
| `TaskEvaluator` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:65` | class |
| `__init__` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:90` | member |
| `_compute_quality_score` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:215` | member |
| `_compute_time_efficiency` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:274` | member |
| `_compute_token_efficiency` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:264` | member |
| `_determine_success` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:178` | member |
| `_estimate_complexity` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:204` | member |
| `_extract_issues` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:284` | member |
| `_extract_lessons` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:310` | member |
| `_generate_suggestions` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:340` | member |
| `_generate_summary` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:410` | member |
| `_should_crystallize` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:368` | member |
| `_should_retry` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:395` | member |
| `evaluate` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:93` | member |
| `to_dict` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:50` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `COMPLEXITY_KEYWORDS` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:69` | variable |
| `FAILURE_SIGNALS` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:85` | variable |
| `SUCCESS_SIGNALS` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:79` | variable |
| `__all__` | `build_mini_dist\tea_agent\evaluation\__init__.py:19` | variable |
| `issues` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:43` | variable |
| `lessons` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:44` | variable |
| `logger` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:33` | variable |
| `quality_score` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:40` | variable |
| `should_crystallize` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:46` | variable |
| `should_retry` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:47` | variable |
| `suggestions` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:45` | variable |
| `summary` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:48` | variable |
| `time_efficiency` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:42` | variable |
| `token_efficiency` | `build_mini_dist\tea_agent\evaluation\task_evaluator.py:41` | variable |

## 模块 `build_mini_dist\tea_agent\multi_agent`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `Dispatcher` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:50` | class |
| `LiteAgent` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:22` | class |
| `SubTask` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:37` | class |
| `TaskStatus` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:29` | class |
| `__init__` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:99` | member |
| `__init__` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:30` | member |
| `_build_summary` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:316` | member |
| `_build_system_prompt` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:126` | member |
| `_execute_layers` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:195` | member |
| `_execute_single_task` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:240` | member |
| `_generate_tasks` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:155` | member |
| `_get_config` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:120` | member |
| `_identify_pattern` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:140` | member |
| `_merge_results` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:289` | member |
| `_topological_sort` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:173` | member |
| `dispatch` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:102` | member |
| `execute_sync` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:46` | member |
| `execute_with_context` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:93` | member |
| `visualize` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:322` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `COMPLETED` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:32` | variable |
| `FAILED` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:33` | variable |
| `PATTERNS` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:58` | variable |
| `PENDING` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:30` | variable |
| `RUNNING` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:31` | variable |
| `__all__` | `build_mini_dist\tea_agent\multi_agent\__init__.py:23` | variable |
| `dependencies` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:43` | variable |
| `error` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:46` | variable |
| `logger` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:26` | variable |
| `logger` | `build_mini_dist\tea_agent\multi_agent\lite_agent.py:19` | variable |
| `result` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:45` | variable |
| `status` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:44` | variable |
| `time_seconds` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:47` | variable |
| `tools` | `build_mini_dist\tea_agent\multi_agent\dispatcher.py:42` | variable |

## 模块 `build_mini_dist\tea_agent\server`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `APIServer` | `build_mini_dist\tea_agent\server\server.py:176` | class |
| `_ChatAgentProxy` | `build_mini_dist\tea_agent\server\server.py:91` | class |
| `__init__` | `build_mini_dist\tea_agent\server\server.py:96` | member |
| `__init__` | `build_mini_dist\tea_agent\server\server.py:186` | member |
| `_extract_user_message` | `build_mini_dist\tea_agent\server\server.py:380` | member |
| `_generate_sse` | `build_mini_dist\tea_agent\server\server.py:349` | member |
| `_get_configs_dir` | `build_mini_dist\tea_agent\server\server.py:874` | member |
| `_get_storage` | `build_mini_dist\tea_agent\server\server.py:201` | member |
| `_get_toolkit` | `build_mini_dist\tea_agent\server\server.py:207` | member |
| `_run_stream` | `build_mini_dist\tea_agent\server\server.py:333` | member |
| `_sanitize` | `build_mini_dist\tea_agent\server\server.py:634` | member |
| `chat_completion` | `build_mini_dist\tea_agent\server\server.py:264` | member |
| `chat_completion_stream` | `build_mini_dist\tea_agent\server\server.py:303` | member |
| `chat_stream_sse` | `build_mini_dist\tea_agent\server\server.py:418` | member |
| `create_config_file` | `build_mini_dist\tea_agent\server\server.py:931` | member |
| `create_memory` | `build_mini_dist\tea_agent\server\server.py:647` | member |
| `create_session` | `build_mini_dist\tea_agent\server\server.py:243` | member |
| `create_task` | `build_mini_dist\tea_agent\server\server.py:664` | member |
| `create_topic_session` | `build_mini_dist\tea_agent\server\server.py:585` | member |
| `delete_memory` | `build_mini_dist\tea_agent\server\server.py:651` | member |
| `delete_session` | `build_mini_dist\tea_agent\server\server.py:608` | member |
| `delete_task` | `build_mini_dist\tea_agent\server\server.py:668` | member |
| `get_agent` | `build_mini_dist\tea_agent\server\server.py:223` | member |
| `get_config` | `build_mini_dist\tea_agent\server\server.py:1052` | member |
| `get_config_info` | `build_mini_dist\tea_agent\server\server.py:993` | member |
| `get_session` | `build_mini_dist\tea_agent\server\server.py:593` | member |
| `get_session_messages` | `build_mini_dist\tea_agent\server\server.py:623` | member |
| `get_topic_conversations` | `build_mini_dist\tea_agent\server\server.py:517` | member |
| `get_topic_info` | `build_mini_dist\tea_agent\server\server.py:532` | member |
| `health` | `build_mini_dist\tea_agent\server\server.py:259` | member |
| `list_config_files` | `build_mini_dist\tea_agent\server\server.py:878` | member |
| `list_memories` | `build_mini_dist\tea_agent\server\server.py:643` | member |
| `list_sessions` | `build_mini_dist\tea_agent\server\server.py:572` | member |
| `list_tasks` | `build_mini_dist\tea_agent\server\server.py:661` | member |
| `list_tools` | `build_mini_dist\tea_agent\server\server.py:549` | member |
| `rename_topic` | `build_mini_dist\tea_agent\server\server.py:615` | member |
| `reset_agent` | `build_mini_dist\tea_agent\server\server.py:230` | member |
| `run_tool` | `build_mini_dist\tea_agent\server\server.py:559` | member |
| `screenshot_full` | `build_mini_dist\tea_agent\server\server.py:728` | member |
| `screenshot_region` | `build_mini_dist\tea_agent\server\server.py:677` | member |
| `search` | `build_mini_dist\tea_agent\server\server.py:671` | member |
| `switch_config` | `build_mini_dist\tea_agent\server\server.py:832` | member |
| `switch_model` | `build_mini_dist\tea_agent\server\server.py:774` | member |
| `update_config` | `build_mini_dist\tea_agent\server\server.py:1055` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `OPENAPI_SPEC` | `build_mini_dist\tea_agent\server\route_handlers.py:866` | variable |
| `__all__` | `build_mini_dist\tea_agent\server\__init__.py:10` | variable |
| `__version__` | `build_mini_dist\tea_agent\server\__init__.py:11` | variable |
| `__version__` | `build_mini_dist\tea_agent\server\server.py:43` | variable |
| `_active_sessions` | `build_mini_dist\tea_agent\server\server.py:51` | variable |
| `_config_cache` | `build_mini_dist\tea_agent\server\server.py:54` | variable |
| `_create_session_from_cfg` | `build_mini_dist\tea_agent\server\server.py:65` | function |
| `_float_or_none` | `build_mini_dist\tea_agent\server\route_handlers.py:672` | function |
| `_int_or_none` | `build_mini_dist\tea_agent\server\route_handlers.py:675` | function |
| `_load_config_cached` | `build_mini_dist\tea_agent\server\server.py:56` | function |
| `_load_topic_history` | `build_mini_dist\tea_agent\server\server.py:102` | function |
| `_max_iter_pending` | `build_mini_dist\tea_agent\server\server.py:47` | variable |
| `_put` | `build_mini_dist\tea_agent\server\server.py:316` | function |
| `_put` | `build_mini_dist\tea_agent\server\server.py:430` | function |
| `_safe_handle` | `build_mini_dist\tea_agent\server\route_handlers.py:847` | function |
| `_save_chat_result` | `build_mini_dist\tea_agent\server\server.py:129` | function |
| `_server_instance` | `build_mini_dist\tea_agent\server\server.py:1087` | variable |
| `_sys` | `build_mini_dist\tea_agent\server\route_handlers.py:311` | namespace |
| `_uuid_mod` | `build_mini_dist\tea_agent\server\server.py:470` | namespace |
| `b64mod` | `build_mini_dist\tea_agent\server\route_handlers.py:392` | namespace |
| `cb` | `build_mini_dist\tea_agent\server\server.py:278` | function |
| `create_app` | `build_mini_dist\tea_agent\server\server.py:1096` | function |
| `event_stream` | `build_mini_dist\tea_agent\server\route_handlers.py:425` | function |
| `get_server` | `build_mini_dist\tea_agent\server\server.py:1089` | function |
| `get_server_version` | `build_mini_dist\tea_agent\server\server.py:172` | function |
| `handle_chat_abort` | `build_mini_dist\tea_agent\server\route_handlers.py:477` | function |
| `handle_chat_completions` | `build_mini_dist\tea_agent\server\route_handlers.py:63` | function |
| `handle_chat_continue` | `build_mini_dist\tea_agent\server\route_handlers.py:453` | function |
| `handle_create_memory` | `build_mini_dist\tea_agent\server\route_handlers.py:195` | function |
| `handle_create_session` | `build_mini_dist\tea_agent\server\route_handlers.py:132` | function |
| `handle_create_task` | `build_mini_dist\tea_agent\server\route_handlers.py:221` | function |
| `handle_delete_memory` | `build_mini_dist\tea_agent\server\route_handlers.py:204` | function |
| `handle_delete_session` | `build_mini_dist\tea_agent\server\route_handlers.py:149` | function |
| `handle_delete_task` | `build_mini_dist\tea_agent\server\route_handlers.py:229` | function |
| `handle_docs` | `build_mini_dist\tea_agent\server\route_handlers.py:39` | function |
| `handle_export_pdf` | `build_mini_dist\tea_agent\server\route_handlers.py:250` | function |
| `handle_get_config` | `build_mini_dist\tea_agent\server\route_handlers.py:167` | function |
| `handle_get_session` | `build_mini_dist\tea_agent\server\route_handlers.py:141` | function |
| `handle_get_session_messages` | `build_mini_dist\tea_agent\server\route_handlers.py:155` | function |
| `handle_health` | `build_mini_dist\tea_agent\server\route_handlers.py:35` | function |
| `handle_list_memory` | `build_mini_dist\tea_agent\server\route_handlers.py:189` | function |
| `handle_list_models` | `build_mini_dist\tea_agent\server\route_handlers.py:84` | function |
| `handle_list_sessions` | `build_mini_dist\tea_agent\server\route_handlers.py:122` | function |
| `handle_list_tasks` | `build_mini_dist\tea_agent\server\route_handlers.py:215` | function |
| `handle_list_tools` | `build_mini_dist\tea_agent\server\route_handlers.py:101` | function |
| `handle_openapi` | `build_mini_dist\tea_agent\server\route_handlers.py:55` | function |
| `handle_run_tool` | `build_mini_dist\tea_agent\server\route_handlers.py:110` | function |
| `handle_screenshot_full` | `build_mini_dist\tea_agent\server\route_handlers.py:299` | function |
| `handle_screenshot_interactive` | `build_mini_dist\tea_agent\server\route_handlers.py:307` | function |
| `handle_screenshot_region` | `build_mini_dist\tea_agent\server\route_handlers.py:281` | function |
| `handle_search` | `build_mini_dist\tea_agent\server\route_handlers.py:240` | function |
| `handle_switch_config` | `build_mini_dist\tea_agent\server\route_handlers.py:174` | function |
| `handle_upload` | `build_mini_dist\tea_agent\server\route_handlers.py:263` | function |
| `handle_web_chat` | `build_mini_dist\tea_agent\server\route_handlers.py:379` | function |
| `handle_web_config` | `build_mini_dist\tea_agent\server\route_handlers.py:567` | function |
| `handle_web_create_config` | `build_mini_dist\tea_agent\server\route_handlers.py:609` | function |
| `handle_web_list_configs` | `build_mini_dist\tea_agent\server\route_handlers.py:585` | function |
| `handle_web_model_config` | `build_mini_dist\tea_agent\server\route_handlers.py:726` | function |
| `handle_web_model_info` | `build_mini_dist\tea_agent\server\route_handlers.py:650` | function |
| `handle_web_model_switch` | `build_mini_dist\tea_agent\server\route_handlers.py:658` | function |
| `handle_web_new_topic` | `build_mini_dist\tea_agent\server\route_handlers.py:502` | function |
| `handle_web_root` | `build_mini_dist\tea_agent\server\route_handlers.py:834` | function |
| `handle_web_sessions` | `build_mini_dist\tea_agent\server\route_handlers.py:512` | function |
| `handle_web_tools` | `build_mini_dist\tea_agent\server\route_handlers.py:561` | function |
| `handle_web_topic_conversations` | `build_mini_dist\tea_agent\server\route_handlers.py:547` | function |
| `handle_web_topic_info` | `build_mini_dist\tea_agent\server\route_handlers.py:519` | function |
| `handle_web_update_config` | `build_mini_dist\tea_agent\server\route_handlers.py:575` | function |
| `handle_web_upload_config` | `build_mini_dist\tea_agent\server\route_handlers.py:739` | function |
| `logger` | `build_mini_dist\tea_agent\server\server.py:27` | variable |
| `main` | `build_mini_dist\tea_agent\server\server.py:1227` | function |
| `run_server` | `build_mini_dist\tea_agent\server\server.py:1208` | function |
| `status_cb` | `build_mini_dist\tea_agent\server\server.py:468` | function |
| `stream_cb` | `build_mini_dist\tea_agent\server\server.py:321` | function |
| `stream_cb` | `build_mini_dist\tea_agent\server\server.py:441` | function |

## 模块 `build_mini_dist\tea_agent\server\static`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `#config-switcher .btn-ghost.btn-sm` | `build_mini_dist\tea_agent\server\static\style.css:326` | class |
| `#config-switcher .btn-ghost.btn-sm:hover` | `build_mini_dist\tea_agent\server\static\style.css:332` | class |
| `#sidebar-splitter.active` | `build_mini_dist\tea_agent\server\static\style.css:514` | class |
| `#toast.show` | `build_mini_dist\tea_agent\server\static\style.css:588` | class |
| `#vsplitter.active` | `build_mini_dist\tea_agent\server\static\style.css:544` | class |
| `.btn` | `build_mini_dist\tea_agent\server\static\style.css:382` | class |
| `.btn-block` | `build_mini_dist\tea_agent\server\static\style.css:404` | class |
| `.btn-danger` | `build_mini_dist\tea_agent\server\static\style.css:395` | class |
| `.btn-danger:hover:not(:disabled)` | `build_mini_dist\tea_agent\server\static\style.css:396` | class |
| `.btn-ghost` | `build_mini_dist\tea_agent\server\static\style.css:401` | class |
| `.btn-ghost:hover` | `build_mini_dist\tea_agent\server\static\style.css:402` | class |
| `.btn-primary` | `build_mini_dist\tea_agent\server\static\style.css:393` | class |
| `.btn-primary:hover:not(:disabled)` | `build_mini_dist\tea_agent\server\static\style.css:394` | class |
| `.btn-sm` | `build_mini_dist\tea_agent\server\static\style.css:403` | class |
| `.btn:disabled` | `build_mini_dist\tea_agent\server\static\style.css:392` | class |
| `.cs-label` | `build_mini_dist\tea_agent\server\static\style.css:335` | class |
| `.form-group` | `build_mini_dist\tea_agent\server\static\style.css:451` | class |
| `.loading` | `build_mini_dist\tea_agent\server\static\style.css:300` | class |
| `.max-iter-overlay` | `build_mini_dist\tea_agent\server\static\style.css:591` | class |
| `.max-iter-overlay .mi-actions` | `build_mini_dist\tea_agent\server\static\style.css:627` | class |
| `.max-iter-overlay .mi-actions .btn` | `build_mini_dist\tea_agent\server\static\style.css:628` | class |
| `.max-iter-overlay .mi-box` | `build_mini_dist\tea_agent\server\static\style.css:608` | class |
| `.max-iter-overlay .mi-desc` | `build_mini_dist\tea_agent\server\static\style.css:625` | class |
| `.max-iter-overlay .mi-icon` | `build_mini_dist\tea_agent\server\static\style.css:623` | class |
| `.max-iter-overlay .mi-title` | `build_mini_dist\tea_agent\server\static\style.css:624` | class |
| `.md-table` | `build_mini_dist\tea_agent\server\static\style.css:479` | class |
| `.memory-item` | `build_mini_dist\tea_agent\server\static\style.css:465` | class |
| `.memory-item .meta` | `build_mini_dist\tea_agent\server\static\style.css:473` | class |
| `.memory-item .text` | `build_mini_dist\tea_agent\server\static\style.css:472` | class |
| `.modal` | `build_mini_dist\tea_agent\server\static\style.css:407` | class |
| `.modal-actions` | `build_mini_dist\tea_agent\server\static\style.css:445` | class |
| `.modal-box` | `build_mini_dist\tea_agent\server\static\style.css:416` | class |
| `.msg` | `build_mini_dist\tea_agent\server\static\style.css:150` | class |
| `.msg-bubble` | `build_mini_dist\tea_agent\server\static\style.css:154` | class |
| `.msg-label` | `build_mini_dist\tea_agent\server\static\style.css:153` | class |
| `.msg.agent` | `build_mini_dist\tea_agent\server\static\style.css:152` | class |
| `.msg.agent .msg-bubble` | `build_mini_dist\tea_agent\server\static\style.css:163` | class |
| `.msg.user` | `build_mini_dist\tea_agent\server\static\style.css:151` | class |
| `.msg.user .msg-bubble` | `build_mini_dist\tea_agent\server\static\style.css:162` | class |
| `.param-key` | `build_mini_dist\tea_agent\server\static\style.css:250` | class |
| `.param-key::after` | `build_mini_dist\tea_agent\server\static\style.css:254` | class |
| `.result-label` | `build_mini_dist\tea_agent\server\static\style.css:272` | class |
| `.sb-actions` | `build_mini_dist\tea_agent\server\static\style.css:41` | class |
| `.sb-footer` | `build_mini_dist\tea_agent\server\static\style.css:42` | class |
| `.sb-header` | `build_mini_dist\tea_agent\server\static\style.css:38` | class |
| `.sb-logo` | `build_mini_dist\tea_agent\server\static\style.css:39` | class |
| `.sb-title` | `build_mini_dist\tea_agent\server\static\style.css:40` | class |
| `.search-item` | `build_mini_dist\tea_agent\server\static\style.css:474` | class |
| `.search-item .sp` | `build_mini_dist\tea_agent\server\static\style.css:476` | class |
| `.search-item .st` | `build_mini_dist\tea_agent\server\static\style.css:475` | class |
| `.spinner` | `build_mini_dist\tea_agent\server\static\style.css:308` | class |
| `.status-msg` | `build_mini_dist\tea_agent\server\static\style.css:454` | class |
| `.status-msg.error` | `build_mini_dist\tea_agent\server\static\style.css:461` | class |
| `.status-msg.info` | `build_mini_dist\tea_agent\server\static\style.css:462` | class |
| `.status-msg.success` | `build_mini_dist\tea_agent\server\static\style.css:460` | class |
| `.task-item` | `build_mini_dist\tea_agent\server\static\style.css:465` | class |
| `.task-item .meta` | `build_mini_dist\tea_agent\server\static\style.css:473` | class |
| `.task-item .text` | `build_mini_dist\tea_agent\server\static\style.css:472` | class |
| `.think-block` | `build_mini_dist\tea_agent\server\static\style.css:166` | class |
| `.think-content` | `build_mini_dist\tea_agent\server\static\style.css:176` | class |
| `.tool-call-container` | `build_mini_dist\tea_agent\server\static\style.css:179` | class |
| `.tool-call-container.done .tool-call-summary` | `build_mini_dist\tea_agent\server\static\style.css:217` | class |
| `.tool-call-container.done .tool-call-summary .badge` | `build_mini_dist\tea_agent\server\static\style.css:218` | class |
| `.tool-call-item` | `build_mini_dist\tea_agent\server\static\style.css:221` | class |
| `.tool-call-item .status-icon` | `build_mini_dist\tea_agent\server\static\style.css:231` | class |
| `.tool-call-item .tool-name` | `build_mini_dist\tea_agent\server\static\style.css:232` | class |
| `.tool-call-item.done` | `build_mini_dist\tea_agent\server\static\style.css:235` | class |
| `.tool-call-item.done .status-icon` | `build_mini_dist\tea_agent\server\static\style.css:236` | class |
| `.tool-call-item.running` | `build_mini_dist\tea_agent\server\static\style.css:234` | class |
| `.tool-call-summary` | `build_mini_dist\tea_agent\server\static\style.css:193` | class |
| `.tool-call-summary .badge` | `build_mini_dist\tea_agent\server\static\style.css:207` | class |
| `.tool-call-summary .icon` | `build_mini_dist\tea_agent\server\static\style.css:206` | class |
| `.tool-call-summary:hover` | `build_mini_dist\tea_agent\server\static\style.css:205` | class |
| `.tool-param-row` | `build_mini_dist\tea_agent\server\static\style.css:242` | class |
| `.tool-params` | `build_mini_dist\tea_agent\server\static\style.css:239` | class |
| `.tool-result` | `build_mini_dist\tea_agent\server\static\style.css:265` | class |
| `.tool-spinner` | `build_mini_dist\tea_agent\server\static\style.css:287` | class |
| `.toolbar-actions` | `build_mini_dist\tea_agent\server\static\style.css:135` | class |
| `.topic-actions-btn` | `build_mini_dist\tea_agent\server\static\style.css:71` | class |
| `.topic-actions-btn:hover` | `build_mini_dist\tea_agent\server\static\style.css:87` | class |
| `.topic-actions-menu` | `build_mini_dist\tea_agent\server\static\style.css:90` | class |
| `.topic-actions-menu-item` | `build_mini_dist\tea_agent\server\static\style.css:104` | class |
| `.topic-actions-menu-item.danger` | `build_mini_dist\tea_agent\server\static\style.css:120` | class |
| `.topic-actions-menu-item.danger:hover` | `build_mini_dist\tea_agent\server\static\style.css:121` | class |
| `.topic-actions-menu-item:hover` | `build_mini_dist\tea_agent\server\static\style.css:119` | class |
| `.topic-actions-menu.show` | `build_mini_dist\tea_agent\server\static\style.css:103` | class |
| `.topic-item` | `build_mini_dist\tea_agent\server\static\style.css:46` | class |
| `.topic-item-title` | `build_mini_dist\tea_agent\server\static\style.css:61` | class |
| `.topic-item.active` | `build_mini_dist\tea_agent\server\static\style.css:60` | class |
| `.topic-item.active .topic-item-title` | `build_mini_dist\tea_agent\server\static\style.css:68` | class |
| `.topic-item:hover` | `build_mini_dist\tea_agent\server\static\style.css:59` | class |
| `.topic-item:hover .topic-actions-btn` | `build_mini_dist\tea_agent\server\static\style.css:86` | class |
| `.topic-list` | `build_mini_dist\tea_agent\server\static\style.css:45` | class |
| `.welcome` | `build_mini_dist\tea_agent\server\static\style.css:140` | class |
| `.welcome-icon` | `build_mini_dist\tea_agent\server\static\style.css:145` | class |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `#app` | `build_mini_dist\tea_agent\server\static\style.css:27` | id |
| `#chat-input` | `build_mini_dist\tea_agent\server\static\style.css:365` | id |
| `#chat-input:focus` | `build_mini_dist\tea_agent\server\static\style.css:379` | id |
| `#config-switcher` | `build_mini_dist\tea_agent\server\static\style.css:320` | id |
| `#cs-select` | `build_mini_dist\tea_agent\server\static\style.css:342` | id |
| `#cs-select:focus` | `build_mini_dist\tea_agent\server\static\style.css:354` | id |
| `#input-row` | `build_mini_dist\tea_agent\server\static\style.css:356` | id |
| `#main` | `build_mini_dist\tea_agent\server\static\style.css:124` | id |
| `#messages` | `build_mini_dist\tea_agent\server\static\style.css:138` | id |
| `#sidebar` | `build_mini_dist\tea_agent\server\static\style.css:30` | id |
| `#sidebar-splitter` | `build_mini_dist\tea_agent\server\static\style.css:504` | id |
| `#sidebar-splitter::after` | `build_mini_dist\tea_agent\server\static\style.css:517` | id |
| `#sidebar-splitter:hover` | `build_mini_dist\tea_agent\server\static\style.css:513` | id |
| `#sidebar-splitter:hover::after` | `build_mini_dist\tea_agent\server\static\style.css:530` | id |
| `#toast` | `build_mini_dist\tea_agent\server\static\style.css:571` | id |
| `#toolbar` | `build_mini_dist\tea_agent\server\static\style.css:127` | id |
| `#topic-title` | `build_mini_dist\tea_agent\server\static\style.css:134` | id |
| `#vsplitter` | `build_mini_dist\tea_agent\server\static\style.css:534` | id |
| `#vsplitter::after` | `build_mini_dist\tea_agent\server\static\style.css:547` | id |
| `#vsplitter:hover` | `build_mini_dist\tea_agent\server\static\style.css:543` | id |
| `#vsplitter:hover::after` | `build_mini_dist\tea_agent\server\static\style.css:560` | id |
| `$` | `build_mini_dist\tea_agent\server\static\app.js:16` | function |
| `*` | `build_mini_dist\tea_agent\server\static\style.css:17` | selector |
| `.max-iter-overlay .mi-desc strong` | `build_mini_dist\tea_agent\server\static\style.css:626` | selector |
| `.md-table tbody tr:hover` | `build_mini_dist\tea_agent\server\static\style.css:499` | selector |
| `.md-table td` | `build_mini_dist\tea_agent\server\static\style.css:486` | selector |
| `.md-table td` | `build_mini_dist\tea_agent\server\static\style.css:496` | selector |
| `.md-table th` | `build_mini_dist\tea_agent\server\static\style.css:485` | selector |
| `.md-table th` | `build_mini_dist\tea_agent\server\static\style.css:491` | selector |
| `.modal-box h3` | `build_mini_dist\tea_agent\server\static\style.css:426` | selector |
| `.modal-box input` | `build_mini_dist\tea_agent\server\static\style.css:427` | selector |
| `.modal-box input:focus` | `build_mini_dist\tea_agent\server\static\style.css:441` | selector |
| `.modal-box label` | `build_mini_dist\tea_agent\server\static\style.css:444` | selector |
| `.modal-box select` | `build_mini_dist\tea_agent\server\static\style.css:429` | selector |
| `.modal-box select:focus` | `build_mini_dist\tea_agent\server\static\style.css:443` | selector |
| `.modal-box textarea` | `build_mini_dist\tea_agent\server\static\style.css:428` | selector |
| `.modal-box textarea:focus` | `build_mini_dist\tea_agent\server\static\style.css:442` | selector |
| `.msg-bubble code` | `build_mini_dist\tea_agent\server\static\style.css:161` | selector |
| `.msg-bubble pre` | `build_mini_dist\tea_agent\server\static\style.css:160` | selector |
| `.param-val code` | `build_mini_dist\tea_agent\server\static\style.css:255` | selector |
| `.result-val code` | `build_mini_dist\tea_agent\server\static\style.css:277` | selector |
| `.think-block summary` | `build_mini_dist\tea_agent\server\static\style.css:175` | selector |
| `.tool-call-item .tool-name code` | `build_mini_dist\tea_agent\server\static\style.css:233` | selector |
| `.welcome h2` | `build_mini_dist\tea_agent\server\static\style.css:146` | selector |
| `.welcome p` | `build_mini_dist\tea_agent\server\static\style.css:147` | selector |
| `::-webkit-scrollbar` | `build_mini_dist\tea_agent\server\static\style.css:565` | selector |
| `::-webkit-scrollbar-thumb` | `build_mini_dist\tea_agent\server\static\style.css:567` | selector |
| `::-webkit-scrollbar-thumb:hover` | `build_mini_dist\tea_agent\server\static\style.css:568` | selector |
| `::-webkit-scrollbar-track` | `build_mini_dist\tea_agent\server\static\style.css:566` | selector |
| `:root` | `build_mini_dist\tea_agent\server\static\style.css:2` | selector |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:136` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:205` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:571` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:688` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:733` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:863` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:909` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:948` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:1146` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:1238` | property |
| `Content-Type` | `build_mini_dist\tea_agent\server\static\app.js:1249` | property |
| `Tea Agent` | `build_mini_dist\tea_agent\server\static\index.html:6` | heading3 |
| `Tea Agent` | `build_mini_dist\tea_agent\server\static\index.html:43` | heading2 |
| `_doUploadConfig` | `build_mini_dist\tea_agent\server\static\app.js:1056` | function |
| `_ensureConfigUploadInput` | `build_mini_dist\tea_agent\server\static\app.js:1034` | function |
| `_initScrollTracking` | `build_mini_dist\tea_agent\server\static\app.js:1571` | function |
| `_isNearBottom` | `build_mini_dist\tea_agent\server\static\app.js:93` | function |
| `addLoading` | `build_mini_dist\tea_agent\server\static\app.js:108` | function |
| `addMemory` | `build_mini_dist\tea_agent\server\static\app.js:684` | function |
| `addMessage` | `build_mini_dist\tea_agent\server\static\app.js:51` | function |
| `addTask` | `build_mini_dist\tea_agent\server\static\app.js:711` | function |
| `anonymousFunctiond3e155210100` | `build_mini_dist\tea_agent\server\static\app.js:5` | function |
| `anonymousFunctiond3e155210300` | `build_mini_dist\tea_agent\server\static\app.js:62` | function |
| `anonymousFunctiond3e155210400` | `build_mini_dist\tea_agent\server\static\app.js:72` | function |
| `anonymousFunctiond3e155210500` | `build_mini_dist\tea_agent\server\static\app.js:73` | function |
| `anonymousFunctiond3e155210700` | `build_mini_dist\tea_agent\server\static\app.js:86` | function |
| `anonymousFunctiond3e155210e00` | `build_mini_dist\tea_agent\server\static\app.js:445` | function |
| `anonymousFunctiond3e155210f00` | `build_mini_dist\tea_agent\server\static\app.js:452` | function |
| `anonymousFunctiond3e155211000` | `build_mini_dist\tea_agent\server\static\app.js:463` | function |
| `anonymousFunctiond3e155211100` | `build_mini_dist\tea_agent\server\static\app.js:464` | function |
| `anonymousFunctiond3e155211200` | `build_mini_dist\tea_agent\server\static\app.js:465` | function |
| `anonymousFunctiond3e155211300` | `build_mini_dist\tea_agent\server\static\app.js:466` | function |
| `anonymousFunctiond3e155211400` | `build_mini_dist\tea_agent\server\static\app.js:482` | function |
| `anonymousFunctiond3e155211500` | `build_mini_dist\tea_agent\server\static\app.js:484` | function |
| `anonymousFunctiond3e155211600` | `build_mini_dist\tea_agent\server\static\app.js:486` | function |
| `anonymousFunctiond3e155211700` | `build_mini_dist\tea_agent\server\static\app.js:520` | function |
| `anonymousFunctiond3e155211800` | `build_mini_dist\tea_agent\server\static\app.js:559` | function |
| `anonymousFunctiond3e155213e00` | `build_mini_dist\tea_agent\server\static\app.js:1009` | function |
| `anonymousFunctiond3e155213f00` | `build_mini_dist\tea_agent\server\static\app.js:1015` | function |
| `anonymousFunctiond3e155214000` | `build_mini_dist\tea_agent\server\static\app.js:1019` | function |
| `anonymousFunctiond3e155214200` | `build_mini_dist\tea_agent\server\static\app.js:1041` | function |
| `anonymousFunctiond3e155214500` | `build_mini_dist\tea_agent\server\static\app.js:1121` | function |
| `anonymousFunctiond3e155214900` | `build_mini_dist\tea_agent\server\static\app.js:1198` | function |
| `anonymousFunctiond3e155214b00` | `build_mini_dist\tea_agent\server\static\app.js:1234` | function |
| `anonymousFunctiond3e155214e00` | `build_mini_dist\tea_agent\server\static\app.js:1245` | function |
| `anonymousFunctiond3e155215200` | `build_mini_dist\tea_agent\server\static\app.js:1305` | function |
| `anonymousFunctiond3e155215300` | `build_mini_dist\tea_agent\server\static\app.js:1308` | function |
| `anonymousFunctiond3e155215400` | `build_mini_dist\tea_agent\server\static\app.js:1308` | function |
| `anonymousFunctiond3e155215500` | `build_mini_dist\tea_agent\server\static\app.js:1317` | function |
| `anonymousFunctiond3e155215600` | `build_mini_dist\tea_agent\server\static\app.js:1317` | function |
| `anonymousFunctiond3e155215700` | `build_mini_dist\tea_agent\server\static\app.js:1399` | function |
| `anonymousFunctiond3e155215800` | `build_mini_dist\tea_agent\server\static\app.js:1409` | function |
| `anonymousFunctiond3e155215900` | `build_mini_dist\tea_agent\server\static\app.js:1423` | function |
| `anonymousFunctiond3e155215a00` | `build_mini_dist\tea_agent\server\static\app.js:1437` | function |
| `anonymousFunctiond3e155215b00` | `build_mini_dist\tea_agent\server\static\app.js:1497` | function |
| `anonymousFunctiond3e155215d00` | `build_mini_dist\tea_agent\server\static\app.js:1511` | function |
| `anonymousFunctiond3e155215f00` | `build_mini_dist\tea_agent\server\static\app.js:1525` | function |
| `anonymousFunctiond3e155216100` | `build_mini_dist\tea_agent\server\static\app.js:1574` | function |
| `anonymousObjectd3e155210905` | `build_mini_dist\tea_agent\server\static\app.js:134` | variable |
| `anonymousObjectd3e155210a05` | `build_mini_dist\tea_agent\server\static\app.js:137` | variable |
| `anonymousObjectd3e155210c05` | `build_mini_dist\tea_agent\server\static\app.js:203` | variable |
| `anonymousObjectd3e155210d05` | `build_mini_dist\tea_agent\server\static\app.js:218` | variable |
| `anonymousObjectd3e155211905` | `build_mini_dist\tea_agent\server\static\app.js:569` | variable |
| `anonymousObjectd3e155211a05` | `build_mini_dist\tea_agent\server\static\app.js:572` | variable |
| `anonymousObjectd3e155211b05` | `build_mini_dist\tea_agent\server\static\app.js:591` | variable |
| `anonymousObjectd3e155212405` | `build_mini_dist\tea_agent\server\static\app.js:688` | variable |
| `anonymousObjectd3e155212505` | `build_mini_dist\tea_agent\server\static\app.js:688` | variable |
| `anonymousObjectd3e155212705` | `build_mini_dist\tea_agent\server\static\app.js:694` | variable |
| `anonymousObjectd3e155212a05` | `build_mini_dist\tea_agent\server\static\app.js:717` | variable |
| `anonymousObjectd3e155212b05` | `build_mini_dist\tea_agent\server\static\app.js:717` | variable |
| `anonymousObjectd3e155212d05` | `build_mini_dist\tea_agent\server\static\app.js:723` | variable |
| `anonymousObjectd3e155213005` | `build_mini_dist\tea_agent\server\static\app.js:733` | variable |
| `anonymousObjectd3e155213105` | `build_mini_dist\tea_agent\server\static\app.js:733` | variable |
| `anonymousObjectd3e155213505` | `build_mini_dist\tea_agent\server\static\app.js:861` | variable |
| `anonymousObjectd3e155213605` | `build_mini_dist\tea_agent\server\static\app.js:907` | variable |
| `anonymousObjectd3e155213905` | `build_mini_dist\tea_agent\server\static\app.js:946` | variable |
| `anonymousObjectd3e155214405` | `build_mini_dist\tea_agent\server\static\app.js:1062` | variable |
| `anonymousObjectd3e155214705` | `build_mini_dist\tea_agent\server\static\app.js:1144` | variable |
| `anonymousObjectd3e155214805` | `build_mini_dist\tea_agent\server\static\app.js:1147` | variable |
| `anonymousObjectd3e155214c05` | `build_mini_dist\tea_agent\server\static\app.js:1236` | variable |
| `anonymousObjectd3e155214d05` | `build_mini_dist\tea_agent\server\static\app.js:1239` | variable |
| `anonymousObjectd3e155214f05` | `build_mini_dist\tea_agent\server\static\app.js:1247` | variable |
| `anonymousObjectd3e155215005` | `build_mini_dist\tea_agent\server\static\app.js:1250` | variable |
| `anonymousObjectd3e155215c05` | `build_mini_dist\tea_agent\server\static\app.js:1509` | variable |
| `anonymousObjectd3e155215e05` | `build_mini_dist\tea_agent\server\static\app.js:1523` | variable |
| `anonymousObjectd3e155216005` | `build_mini_dist\tea_agent\server\static\app.js:1555` | variable |
| `anonymousObjectd3e155216205` | `build_mini_dist\tea_agent\server\static\app.js:1576` | variable |
| `api-key` | `build_mini_dist\tea_agent\server\static\index.html:124` | id |
| `api-url` | `build_mini_dist\tea_agent\server\static\index.html:123` | id |
| `app` | `build_mini_dist\tea_agent\server\static\index.html:10` | id |
| `applyConfig` | `build_mini_dist\tea_agent\server\static\app.js:810` | function |
| `applyTheme` | `build_mini_dist\tea_agent\server\static\app.js:40` | function |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:137` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:199` | variable |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:206` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:572` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:688` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:733` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:864` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:910` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:940` | variable |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:949` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:1064` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:1147` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:1239` | property |
| `body` | `build_mini_dist\tea_agent\server\static\app.js:1250` | property |
| `body` | `build_mini_dist\tea_agent\server\static\style.css:18` | selector |
| `body.cheap_options` | `build_mini_dist\tea_agent\server\static\app.js:856` | property |
| `captureFull` | `build_mini_dist\tea_agent\server\static\app.js:1392` | function |
| `chat-input` | `build_mini_dist\tea_agent\server\static\index.html:54` | id |
| `cheap-api-key` | `build_mini_dist\tea_agent\server\static\index.html:141` | id |
| `cheap-api-url` | `build_mini_dist\tea_agent\server\static\index.html:140` | id |
| `cheap-max-context` | `build_mini_dist\tea_agent\server\static\index.html:148` | id |
| `cheap-max-tokens` | `build_mini_dist\tea_agent\server\static\index.html:144` | id |
| `cheap-model-name` | `build_mini_dist\tea_agent\server\static\index.html:139` | id |
| `cheap-supports-reasoning` | `build_mini_dist\tea_agent\server\static\index.html:152` | id |
| `cheap-supports-vision` | `build_mini_dist\tea_agent\server\static\index.html:151` | id |
| `cheap-temperature` | `build_mini_dist\tea_agent\server\static\index.html:143` | id |
| `cheap-top-p` | `build_mini_dist\tea_agent\server\static\index.html:147` | id |
| `checkConfigStatus` | `build_mini_dist\tea_agent\server\static\app.js:1081` | function |
| `checkVisionSupport` | `build_mini_dist\tea_agent\server\static\app.js:1264` | function |
| `cleanupOverlay` | `build_mini_dist\tea_agent\server\static\app.js:1383` | function |
| `clear-images-btn` | `build_mini_dist\tea_agent\server\static\index.html:59` | id |
| `clearChat` | `build_mini_dist\tea_agent\server\static\app.js:632` | function |
| `clearImages` | `build_mini_dist\tea_agent\server\static\app.js:991` | function |
| `clientToImage` | `build_mini_dist\tea_agent\server\static\app.js:1343` | function |
| `command` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `config-select` | `build_mini_dist\tea_agent\server\static\index.html:117` | id |
| `config-switcher` | `build_mini_dist\tea_agent\server\static\index.html:27` | id |
| `config-warning` | `build_mini_dist\tea_agent\server\static\index.html:36` | id |
| `config-warning-text` | `build_mini_dist\tea_agent\server\static\index.html:38` | id |
| `config_path` | `build_mini_dist\tea_agent\server\static\app.js:1147` | property |
| `confirm_id` | `build_mini_dist\tea_agent\server\static\app.js:1239` | property |
| `confirm_id` | `build_mini_dist\tea_agent\server\static\app.js:1250` | property |
| `content` | `build_mini_dist\tea_agent\server\static\app.js:688` | property |
| `continue` | `build_mini_dist\tea_agent\server\static\app.js:1239` | property |
| `continue` | `build_mini_dist\tea_agent\server\static\app.js:1250` | property |
| `cs-select` | `build_mini_dist\tea_agent\server\static\index.html:29` | id |
| `deleteMemory` | `build_mini_dist\tea_agent\server\static\app.js:693` | function |
| `deleteTask` | `build_mini_dist\tea_agent\server\static\app.js:722` | function |
| `deleteTopic` | `build_mini_dist\tea_agent\server\static\app.js:588` | function |
| `doCrop` | `build_mini_dist\tea_agent\server\static\app.js:1365` | function |
| `doExport` | `build_mini_dist\tea_agent\server\static\app.js:728` | function |
| `doSearch` | `build_mini_dist\tea_agent\server\static\app.js:647` | function |
| `esc` | `build_mini_dist\tea_agent\server\static\app.js:17` | function |
| `escHtml` | `build_mini_dist\tea_agent\server\static\app.js:491` | function |
| `export-result` | `build_mini_dist\tea_agent\server\static\index.html:105` | id |
| `filename` | `build_mini_dist\tea_agent\server\static\app.js:940` | property |
| `formatMarkdown` | `build_mini_dist\tea_agent\server\static\app.js:440` | function |
| `handleImageSelect` | `build_mini_dist\tea_agent\server\static\app.js:972` | function |
| `handleInputKey` | `build_mini_dist\tea_agent\server\static\app.js:637` | function |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:136` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:205` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:571` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:688` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:733` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:863` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:909` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:948` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:1146` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:1238` | property |
| `headers` | `build_mini_dist\tea_agent\server\static\app.js:1249` | property |
| `hide` | `build_mini_dist\tea_agent\server\static\app.js:19` | function |
| `image-input` | `build_mini_dist\tea_agent\server\static\index.html:51` | id |
| `image-preview-container` | `build_mini_dist\tea_agent\server\static\index.html:58` | id |
| `image-preview-row` | `build_mini_dist\tea_agent\server\static\index.html:57` | id |
| `image-upload-area` | `build_mini_dist\tea_agent\server\static\index.html:49` | id |
| `image-upload-btn` | `build_mini_dist\tea_agent\server\static\index.html:50` | id |
| `imgRenderRect` | `build_mini_dist\tea_agent\server\static\app.js:1337` | function |
| `initApp` | `build_mini_dist\tea_agent\server\static\app.js:1580` | function |
| `initSplitter` | `build_mini_dist\tea_agent\server\static\app.js:1166` | function |
| `input-row` | `build_mini_dist\tea_agent\server\static\index.html:48` | id |
| `interruptChat` | `build_mini_dist\tea_agent\server\static\app.js:125` | function |
| `loadConfigSwitcher` | `build_mini_dist\tea_agent\server\static\app.js:1105` | function |
| `main` | `build_mini_dist\tea_agent\server\static\index.html:23` | id |
| `main-max-context` | `build_mini_dist\tea_agent\server\static\index.html:131` | id |
| `main-max-tokens` | `build_mini_dist\tea_agent\server\static\index.html:127` | id |
| `main-supports-reasoning` | `build_mini_dist\tea_agent\server\static\index.html:135` | id |
| `main-supports-vision` | `build_mini_dist\tea_agent\server\static\index.html:134` | id |
| `main-temperature` | `build_mini_dist\tea_agent\server\static\index.html:126` | id |
| `main-top-p` | `build_mini_dist\tea_agent\server\static\index.html:130` | id |
| `main_api_key` | `build_mini_dist\tea_agent\server\static\app.js:940` | property |
| `main_api_url` | `build_mini_dist\tea_agent\server\static\app.js:940` | property |
| `main_model_name` | `build_mini_dist\tea_agent\server\static\app.js:940` | property |
| `memory-input` | `build_mini_dist\tea_agent\server\static\index.html:78` | id |
| `memory-list` | `build_mini_dist\tea_agent\server\static\index.html:80` | id |
| `message` | `build_mini_dist\tea_agent\server\static\app.js:199` | property |
| `messages` | `build_mini_dist\tea_agent\server\static\index.html:35` | id |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:135` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:204` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:570` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:591` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:688` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:694` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:723` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:733` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:862` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:908` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:947` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:1063` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:1145` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:1237` | property |
| `method` | `build_mini_dist\tea_agent\server\static\app.js:1248` | property |
| `modal-export` | `build_mini_dist\tea_agent\server\static\index.html:102` | id |
| `modal-memory` | `build_mini_dist\tea_agent\server\static\index.html:76` | id |
| `modal-new-config` | `build_mini_dist\tea_agent\server\static\index.html:186` | id |
| `modal-scheduler` | `build_mini_dist\tea_agent\server\static\index.html:87` | id |
| `modal-search` | `build_mini_dist\tea_agent\server\static\index.html:65` | id |
| `modal-settings` | `build_mini_dist\tea_agent\server\static\index.html:113` | id |
| `model-name` | `build_mini_dist\tea_agent\server\static\index.html:122` | id |
| `name` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `new-cheap-key` | `build_mini_dist\tea_agent\server\static\index.html:196` | id |
| `new-cheap-name` | `build_mini_dist\tea_agent\server\static\index.html:194` | id |
| `new-cheap-url` | `build_mini_dist\tea_agent\server\static\index.html:195` | id |
| `new-config-filename` | `build_mini_dist\tea_agent\server\static\index.html:188` | id |
| `new-config-status` | `build_mini_dist\tea_agent\server\static\index.html:197` | id |
| `new-main-key` | `build_mini_dist\tea_agent\server\static\index.html:192` | id |
| `new-main-name` | `build_mini_dist\tea_agent\server\static\index.html:190` | id |
| `new-main-url` | `build_mini_dist\tea_agent\server\static\index.html:191` | id |
| `newTopic` | `build_mini_dist\tea_agent\server\static\app.js:624` | function |
| `numVal` | `build_mini_dist\tea_agent\server\static\app.js:824` | function |
| `numVal` | `build_mini_dist\tea_agent\server\static\app.js:883` | function |
| `onKey` | `build_mini_dist\tea_agent\server\static\app.js:1558` | function |
| `onMove` | `build_mini_dist\tea_agent\server\static\app.js:1174` | function |
| `onUp` | `build_mini_dist\tea_agent\server\static\app.js:1190` | function |
| `onchange` | `build_mini_dist\tea_agent\server\static\app.js:792` | function |
| `onload` | `build_mini_dist\tea_agent\server\static\app.js:981` | function |
| `openImageOverlay` | `build_mini_dist\tea_agent\server\static\app.js:82` | function |
| `openTopic` | `build_mini_dist\tea_agent\server\static\app.js:608` | function |
| `options` | `build_mini_dist\tea_agent\server\static\app.js:832` | variable |
| `passive` | `build_mini_dist\tea_agent\server\static\app.js:1509` | property |
| `passive` | `build_mini_dist\tea_agent\server\static\app.js:1523` | property |
| `passive` | `build_mini_dist\tea_agent\server\static\app.js:1555` | property |
| `passive` | `build_mini_dist\tea_agent\server\static\app.js:1576` | property |
| `refreshMemory` | `build_mini_dist\tea_agent\server\static\app.js:672` | function |
| `refreshTasks` | `build_mini_dist\tea_agent\server\static\app.js:699` | function |
| `refreshTopics` | `build_mini_dist\tea_agent\server\static\app.js:495` | function |
| `removeImage` | `build_mini_dist\tea_agent\server\static\app.js:1026` | function |
| `removeLoading` | `build_mini_dist\tea_agent\server\static\app.js:118` | function |
| `renameTopic` | `build_mini_dist\tea_agent\server\static\app.js:565` | function |
| `rt-chat-page` | `build_mini_dist\tea_agent\server\static\index.html:172` | id |
| `rt-enable-thinking` | `build_mini_dist\tea_agent\server\static\index.html:175` | id |
| `rt-extra-iters` | `build_mini_dist\tea_agent\server\static\index.html:167` | id |
| `rt-keep-turns` | `build_mini_dist\tea_agent\server\static\index.html:160` | id |
| `rt-max-history` | `build_mini_dist\tea_agent\server\static\index.html:163` | id |
| `rt-max-iterations` | `build_mini_dist\tea_agent\server\static\index.html:159` | id |
| `rt-max-tool-output` | `build_mini_dist\tea_agent\server\static\index.html:164` | id |
| `rt-mem-dedup` | `build_mini_dist\tea_agent\server\static\index.html:171` | id |
| `rt-mem-extract` | `build_mini_dist\tea_agent\server\static\index.html:168` | id |
| `saveNewConfig` | `build_mini_dist\tea_agent\server\static\app.js:924` | function |
| `saveRuntimeParams` | `build_mini_dist\tea_agent\server\static\app.js:882` | function |
| `schedule` | `build_mini_dist\tea_agent\server\static\app.js:717` | property |
| `screenshot-btn` | `build_mini_dist\tea_agent\server\static\index.html:52` | id |
| `scrollBottom` | `build_mini_dist\tea_agent\server\static\app.js:100` | function |
| `search-query` | `build_mini_dist\tea_agent\server\static\index.html:67` | id |
| `search-results` | `build_mini_dist\tea_agent\server\static\index.html:68` | id |
| `send-btn` | `build_mini_dist\tea_agent\server\static\index.html:55` | id |
| `sendMessage` | `build_mini_dist\tea_agent\server\static\app.js:151` | function |
| `settings-status` | `build_mini_dist\tea_agent\server\static\index.html:155` | id |
| `show` | `build_mini_dist\tea_agent\server\static\app.js:18` | function |
| `showExport` | `build_mini_dist\tea_agent\server\static\app.js:727` | function |
| `showMaxIterConfirm` | `build_mini_dist\tea_agent\server\static\app.js:1211` | function |
| `showMemory` | `build_mini_dist\tea_agent\server\static\app.js:671` | function |
| `showNewConfig` | `build_mini_dist\tea_agent\server\static\app.js:920` | function |
| `showScheduler` | `build_mini_dist\tea_agent\server\static\app.js:698` | function |
| `showSearch` | `build_mini_dist\tea_agent\server\static\app.js:646` | function |
| `showSettings` | `build_mini_dist\tea_agent\server\static\app.js:741` | function |
| `sidebar` | `build_mini_dist\tea_agent\server\static\index.html:11` | id |
| `sidebar-splitter` | `build_mini_dist\tea_agent\server\static\index.html:22` | id |
| `signal` | `build_mini_dist\tea_agent\server\static\app.js:138` | property |
| `signal` | `build_mini_dist\tea_agent\server\static\app.js:207` | property |
| `startScreenshot` | `build_mini_dist\tea_agent\server\static\app.js:1272` | function |
| `stream` | `build_mini_dist\tea_agent\server\static\app.js:218` | property |
| `supports_reasoning` | `build_mini_dist\tea_agent\server\static\app.js:834` | property |
| `supports_reasoning` | `build_mini_dist\tea_agent\server\static\app.js:858` | property |
| `supports_vision` | `build_mini_dist\tea_agent\server\static\app.js:833` | property |
| `supports_vision` | `build_mini_dist\tea_agent\server\static\app.js:857` | property |
| `switchConfig` | `build_mini_dist\tea_agent\server\static\app.js:1139` | function |
| `task-command` | `build_mini_dist\tea_agent\server\static\index.html:91` | id |
| `task-list` | `build_mini_dist\tea_agent\server\static\index.html:95` | id |
| `task-name` | `build_mini_dist\tea_agent\server\static\index.html:90` | id |
| `task-schedule` | `build_mini_dist\tea_agent\server\static\index.html:92` | id |
| `theme-btn` | `build_mini_dist\tea_agent\server\static\index.html:32` | id |
| `title` | `build_mini_dist\tea_agent\server\static\app.js:572` | property |
| `toast` | `build_mini_dist\tea_agent\server\static\app.js:22` | function |
| `toggleTheme` | `build_mini_dist\tea_agent\server\static\app.js:35` | function |
| `toolbar` | `build_mini_dist\tea_agent\server\static\index.html:24` | id |
| `topic-list` | `build_mini_dist\tea_agent\server\static\index.html:19` | id |
| `topic-title` | `build_mini_dist\tea_agent\server\static\index.html:25` | id |
| `topic_id` | `build_mini_dist\tea_agent\server\static\app.js:137` | property |
| `topic_id` | `build_mini_dist\tea_agent\server\static\app.js:199` | property |
| `topic_id` | `build_mini_dist\tea_agent\server\static\app.js:733` | property |
| `touchStart` | `build_mini_dist\tea_agent\server\static\app.js:1500` | variable |
| `triggerImageUpload` | `build_mini_dist\tea_agent\server\static\app.js:968` | function |
| `updateImagePreview` | `build_mini_dist\tea_agent\server\static\app.js:996` | function |
| `updateUsage` | `build_mini_dist\tea_agent\server\static\app.js:426` | function |
| `uploadConfigFile` | `build_mini_dist\tea_agent\server\static\app.js:1052` | function |
| `vsplitter` | `build_mini_dist\tea_agent\server\static\index.html:47` | id |
| `x` | `build_mini_dist\tea_agent\server\static\app.js:1500` | property |
| `y` | `build_mini_dist\tea_agent\server\static\app.js:1500` | property |
| `⚙ 模型设置` | `build_mini_dist\tea_agent\server\static\index.html:114` | heading3 |
| `➕ 新增配置` | `build_mini_dist\tea_agent\server\static\index.html:187` | heading3 |
| `📄 导出 PDF` | `build_mini_dist\tea_agent\server\static\index.html:103` | heading3 |
| `📋 定时任务` | `build_mini_dist\tea_agent\server\static\index.html:88` | heading3 |
| `🔍 搜索` | `build_mini_dist\tea_agent\server\static\index.html:66` | heading3 |
| `🧠 记忆管理` | `build_mini_dist\tea_agent\server\static\index.html:77` | heading3 |

## 模块 `build_mini_dist\tea_agent\session`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `LoopDetector` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:12` | class |
| `SessionComponent` | `build_mini_dist\tea_agent\session\context.py:76` | class |
| `SessionContext` | `build_mini_dist\tea_agent\session\context.py:15` | class |
| `__init__` | `build_mini_dist\tea_agent\session\context.py:79` | member |
| `__init__` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:21` | member |
| `_hash_tool_call` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:33` | member |
| `_text_similarity` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:44` | member |
| `check_and_record` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:58` | member |
| `initialize` | `build_mini_dist\tea_agent\session\context.py:84` | member |
| `name` | `build_mini_dist\tea_agent\session\context.py:90` | member |
| `reset` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:173` | member |
| `save_agent_config` | `build_mini_dist\tea_agent\session\context.py:94` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `COMPACT_SYSTEM_PROMPT` | `build_mini_dist\tea_agent\session\prompts.py:48` | variable |
| `HISTORY_SUMMARIZE_SYSTEM` | `build_mini_dist\tea_agent\session\prompts.py:16` | variable |
| `HISTORY_SUMMARIZE_USER` | `build_mini_dist\tea_agent\session\prompts.py:21` | variable |
| `SMALL_MODEL_CONSTRAINT` | `build_mini_dist\tea_agent\session\prompts.py:61` | variable |
| `TOPIC_SUMMARY_SYSTEM` | `build_mini_dist\tea_agent\session\prompts.py:28` | variable |
| `TOPIC_SUMMARY_USER_TEMPLATE` | `build_mini_dist\tea_agent\session\prompts.py:41` | variable |
| `_DEFAULTS` | `build_mini_dist\tea_agent\session\params.py:15` | variable |
| `_OS_STATE_FILE` | `build_mini_dist\tea_agent\session\os_info_injector.py:17` | variable |
| `_SMALL_MODEL_PATTERNS` | `build_mini_dist\tea_agent\session\prompts.py:86` | variable |
| `_SkillRegistry` | `build_mini_dist\tea_agent\session\history_builder.py:426` | unknown |
| `__all__` | `build_mini_dist\tea_agent\session\__init__.py:33` | variable |
| `_cheap_thinking_supported` | `build_mini_dist\tea_agent\session\context.py:51` | variable |
| `_current_mode` | `build_mini_dist\tea_agent\session\context.py:70` | variable |
| `_current_trace` | `build_mini_dist\tea_agent\session\context.py:68` | variable |
| `_extract_files_from_text` | `build_mini_dist\tea_agent\session\history_builder.py:164` | function |
| `_find_prune_cutoff` | `build_mini_dist\tea_agent\session\history_builder.py:148` | function |
| `_format_tool_summary` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:183` | function |
| `_get_os_signature` | `build_mini_dist\tea_agent\session\os_info_injector.py:20` | function |
| `_get_validate_rules` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:224` | function |
| `_history_summary` | `build_mini_dist\tea_agent\session\context.py:64` | variable |
| `_injected_memories` | `build_mini_dist\tea_agent\session\context.py:61` | variable |
| `_injected_memories_text` | `build_mini_dist\tea_agent\session\context.py:60` | variable |
| `_injected_os_info_text` | `build_mini_dist\tea_agent\session\context.py:62` | variable |
| `_json` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:300` | namespace |
| `_json` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:471` | namespace |
| `_key_words` | `build_mini_dist\tea_agent\session\history_builder.py:141` | function |
| `_last_cheap_usage` | `build_mini_dist\tea_agent\session\context.py:56` | variable |
| `_last_usage` | `build_mini_dist\tea_agent\session\context.py:52` | variable |
| `_level2` | `build_mini_dist\tea_agent\session\context.py:67` | variable |
| `_load_persisted_os_sig` | `build_mini_dist\tea_agent\session\os_info_injector.py:32` | function |
| `_os_info_injected` | `build_mini_dist\tea_agent\session\context.py:63` | variable |
| `_plat` | `build_mini_dist\tea_agent\session\os_info_injector.py:26` | namespace |
| `_progressive_trim` | `build_mini_dist\tea_agent\session\history_builder.py:188` | function |
| `_rounds_collector` | `build_mini_dist\tea_agent\session\context.py:30` | variable |
| `_save_os_sig` | `build_mini_dist\tea_agent\session\os_info_injector.py:47` | function |
| `_semantic_summary` | `build_mini_dist\tea_agent\session\context.py:65` | variable |
| `_skill_validate_cache` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:221` | variable |
| `_thinking_supported` | `build_mini_dist\tea_agent\session\context.py:50` | variable |
| `_tool_chain_summary` | `build_mini_dist\tea_agent\session\context.py:66` | variable |
| `_try_fix_with_stack` | `build_mini_dist\tea_agent\session\json_sanitizer.py:32` | function |
| `_validate_output_format` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:265` | function |
| `_validate_tool_call` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:233` | function |
| `build_api_messages` | `build_mini_dist\tea_agent\session\history_builder.py:365` | function |
| `cheap_client` | `build_mini_dist\tea_agent\session\context.py:24` | variable |
| `cheap_model` | `build_mini_dist\tea_agent\session\context.py:25` | variable |
| `client` | `build_mini_dist\tea_agent\session\context.py:23` | variable |
| `disable_summary` | `build_mini_dist\tea_agent\session\context.py:46` | variable |
| `enable_thinking` | `build_mini_dist\tea_agent\session\context.py:20` | variable |
| `estimate_messages_tokens` | `build_mini_dist\tea_agent\session\history_builder.py:50` | function |
| `estimate_tokens` | `build_mini_dist\tea_agent\session\history_builder.py:21` | function |
| `execute_tool_loop` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:308` | function |
| `extra_iterations_on_continue` | `build_mini_dist\tea_agent\session\context.py:73` | variable |
| `filter_level2_by_relevance` | `build_mini_dist\tea_agent\session\history_builder.py:301` | function |
| `get_cheap_params` | `build_mini_dist\tea_agent\session\params.py:22` | function |
| `get_skill_validate_rules` | `build_mini_dist\tea_agent\session\prompts.py:140` | function |
| `inject_os_info` | `build_mini_dist\tea_agent\session\os_info_injector.py:64` | function |
| `is_small_model` | `build_mini_dist\tea_agent\session\prompts.py:104` | function |
| `keep_turns` | `build_mini_dist\tea_agent\session\context.py:38` | variable |
| `logger` | `build_mini_dist\tea_agent\session\history_builder.py:18` | variable |
| `logger` | `build_mini_dist\tea_agent\session\json_sanitizer.py:12` | variable |
| `logger` | `build_mini_dist\tea_agent\session\os_info_injector.py:14` | variable |
| `logger` | `build_mini_dist\tea_agent\session\params.py:12` | variable |
| `logger` | `build_mini_dist\tea_agent\session\tool_loop_runner.py:10` | variable |
| `max_assistant_content` | `build_mini_dist\tea_agent\session\context.py:40` | variable |
| `max_context_tokens` | `build_mini_dist\tea_agent\session\context.py:41` | variable |
| `max_tool_output` | `build_mini_dist\tea_agent\session\context.py:39` | variable |
| `memory` | `build_mini_dist\tea_agent\session\context.py:34` | variable |
| `memory_dedup_threshold` | `build_mini_dist\tea_agent\session\context.py:43` | variable |
| `memory_extraction_threshold` | `build_mini_dist\tea_agent\session\context.py:42` | variable |
| `messages` | `build_mini_dist\tea_agent\session\context.py:18` | variable |
| `model` | `build_mini_dist\tea_agent\session\context.py:19` | variable |
| `no_stream_chunk` | `build_mini_dist\tea_agent\session\context.py:47` | variable |
| `pipeline` | `build_mini_dist\tea_agent\session\context.py:35` | variable |
| `reflection_manager` | `build_mini_dist\tea_agent\session\context.py:69` | variable |
| `sanitize_api_messages` | `build_mini_dist\tea_agent\session\json_sanitizer.py:115` | function |
| `storage` | `build_mini_dist\tea_agent\session\context.py:33` | variable |
| `supports_reasoning` | `build_mini_dist\tea_agent\session\context.py:45` | variable |
| `supports_vision` | `build_mini_dist\tea_agent\session\context.py:44` | variable |
| `to_multimodal` | `build_mini_dist\tea_agent\session\history_builder.py:88` | function |
| `tool_log` | `build_mini_dist\tea_agent\session\context.py:29` | variable |
| `toolkit` | `build_mini_dist\tea_agent\session\context.py:28` | variable |
| `try_fix_truncated_json` | `build_mini_dist\tea_agent\session\json_sanitizer.py:15` | function |

## 模块 `build_mini_dist\tea_agent\session\.tea_agent_run`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:108` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:113` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:119` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:133` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:138` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:143` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:155` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:172` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:183` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:207` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:219` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:224` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:235` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:240` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:246` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:256` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:269` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:276` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:283` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:287` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:296` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:299` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:308` | string |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:3` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:10` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:17` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:24` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:31` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:38` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:45` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:52` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:59` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:66` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:73` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:80` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:87` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:94` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:101` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:108` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:115` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:122` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:129` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:136` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:143` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:150` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:157` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:164` | object |
| `0` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:171` | object |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:109` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:114` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:120` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:134` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:139` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:144` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:156` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:173` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:184` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:208` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:220` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:225` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:236` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:241` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:247` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:257` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:270` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:277` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:284` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:288` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:300` | string |
| `1` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:309` | string |
| `10` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:129` | string |
| `10` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:165` | string |
| `10` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:193` | string |
| `10` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:266` | string |
| `10` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:318` | string |
| `11` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:130` | string |
| `11` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:166` | string |
| `11` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:194` | string |
| `11` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:319` | string |
| `12` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:167` | string |
| `12` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:195` | string |
| `12` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:320` | string |
| `13` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:168` | string |
| `13` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:196` | string |
| `13` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:321` | string |
| `14` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:169` | string |
| `14` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:197` | string |
| `14` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:322` | string |
| `15` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:198` | string |
| `15` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:323` | string |
| `16` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:199` | string |
| `16` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:324` | string |
| `17` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:200` | string |
| `17` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:325` | string |
| `18` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:201` | string |
| `18` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:326` | string |
| `19` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:202` | string |
| `19` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:327` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:110` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:115` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:121` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:135` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:140` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:145` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:157` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:174` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:185` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:209` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:221` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:226` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:237` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:242` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:248` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:258` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:271` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:278` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:289` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:301` | string |
| `2` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:310` | string |
| `20` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:203` | string |
| `20` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:328` | string |
| `21` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:204` | string |
| `21` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:329` | string |
| `22` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:330` | string |
| `23` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:331` | string |
| `24` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:332` | string |
| `25` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:333` | string |
| `26` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:334` | string |
| `27` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:335` | string |
| `28` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:336` | string |
| `29` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:337` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:116` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:122` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:146` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:158` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:175` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:186` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:210` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:227` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:243` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:249` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:259` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:272` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:279` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:290` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:302` | string |
| `3` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:311` | string |
| `30` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:338` | string |
| `31` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:339` | string |
| `32` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:340` | string |
| `33` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:341` | string |
| `34` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:342` | string |
| `35` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:343` | string |
| `36` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:344` | string |
| `37` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:345` | string |
| `38` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:346` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:123` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:147` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:159` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:176` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:187` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:211` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:228` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:250` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:260` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:273` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:280` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:291` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:303` | string |
| `4` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:312` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:124` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:148` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:160` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:177` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:188` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:212` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:229` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:251` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:261` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:292` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:304` | string |
| `5` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:313` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:125` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:149` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:161` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:178` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:189` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:213` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:230` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:252` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:262` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:293` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:305` | string |
| `6` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:314` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:126` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:150` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:162` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:179` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:190` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:214` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:231` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:253` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:263` | string |
| `7` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:315` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:127` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:151` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:163` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:180` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:191` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:215` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:232` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:264` | string |
| `8` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:316` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:128` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:152` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:164` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:192` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:216` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:265` | string |
| `9` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:317` | string |
| `LoopDetector` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:101` | object |
| `LoopDetector` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:170` | array |
| `Top 20 被调用函数` | `build_mini_dist\tea_agent\session\.tea_agent_run\kb.md:26` | section |
| `__init__` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:71` | object |
| `__init__` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:121` | array |
| `_extract_files_from_text` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:23` | object |
| `_extract_files_from_text` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:142` | array |
| `_extract_files_from_text` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:37` | array |
| `_find_prune_cutoff` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:19` | object |
| `_find_prune_cutoff` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:137` | array |
| `_find_prune_cutoff` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:30` | array |
| `_format_tool_summary` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:91` | object |
| `_format_tool_summary` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:298` | array |
| `_format_tool_summary` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:156` | array |
| `_get_os_signature` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:51` | object |
| `_get_os_signature` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:234` | array |
| `_get_os_signature` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:86` | array |
| `_hash_tool_call` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:75` | object |
| `_hash_tool_call` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:275` | array |
| `_hash_tool_call` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:128` | array |
| `_key_words` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:15` | object |
| `_key_words` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:132` | array |
| `_key_words` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:23` | array |
| `_load_persisted_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:55` | object |
| `_load_persisted_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:239` | array |
| `_load_persisted_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:93` | array |
| `_progressive_trim` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:27` | object |
| `_progressive_trim` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:154` | array |
| `_progressive_trim` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:44` | array |
| `_save_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:59` | object |
| `_save_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:245` | array |
| `_save_os_sig` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:100` | array |
| `_text_similarity` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:79` | object |
| `_text_similarity` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:282` | array |
| `_text_similarity` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:135` | array |
| `_try_fix_with_stack` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:43` | object |
| `_try_fix_with_stack` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:218` | array |
| `_try_fix_with_stack` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:72` | array |
| `build_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:35` | object |
| `build_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:182` | array |
| `build_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:58` | array |
| `calls` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:106` | object |
| `check_and_record` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:83` | object |
| `check_and_record` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:286` | array |
| `check_and_record` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:142` | array |
| `classes` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:100` | object |
| `estimate_messages_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:7` | object |
| `estimate_messages_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:112` | array |
| `estimate_messages_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:9` | array |
| `estimate_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:3` | object |
| `estimate_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:107` | array |
| `estimate_tokens` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:2` | array |
| `execute_tool_loop` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:95` | object |
| `execute_tool_loop` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:307` | array |
| `execute_tool_loop` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:163` | array |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:4` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:8` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:12` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:16` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:20` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:24` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:28` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:32` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:36` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:40` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:44` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:48` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:52` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:56` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:60` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:64` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:68` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:72` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:76` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:80` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:84` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:88` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:92` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:96` | string |
| `file` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:102` | string |
| `filter_level2_by_relevance` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:31` | object |
| `filter_level2_by_relevance` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:171` | array |
| `filter_level2_by_relevance` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:51` | array |
| `functions` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:2` | object |
| `get_cheap_params` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:67` | object |
| `get_cheap_params` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:268` | array |
| `get_cheap_params` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:114` | array |
| `inject_os_info` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:63` | object |
| `inject_os_info` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:255` | array |
| `inject_os_info` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:107` | array |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:4` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:11` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:18` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:25` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:32` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:39` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:46` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:53` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:60` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:67` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:74` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:81` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:88` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:95` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:102` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:109` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:116` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:123` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:130` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:137` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:144` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:151` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:158` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:165` | string |
| `kind` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:172` | string |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:5` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:9` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:13` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:17` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:21` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:25` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:29` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:33` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:37` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:41` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:45` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:49` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:53` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:57` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:61` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:65` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:69` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:73` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:77` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:81` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:85` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:89` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:93` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:97` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:103` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:6` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:13` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:20` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:27` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:34` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:41` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:48` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:55` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:62` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:69` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:76` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:83` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:90` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:97` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:104` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:111` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:118` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:125` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:132` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:139` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:146` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:153` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:160` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:167` | number |
| `line` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:174` | number |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:5` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:12` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:19` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:26` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:33` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:40` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:47` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:54` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:61` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:68` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:75` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:82` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:89` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:96` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:103` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:110` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:117` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:124` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:131` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:138` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:145` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:152` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:159` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:166` | string |
| `path` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:173` | string |
| `reset` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:87` | object |
| `reset` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:295` | array |
| `reset` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:149` | array |
| `sanitize_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:47` | object |
| `sanitize_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:223` | array |
| `sanitize_api_messages` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:79` | array |
| `session 项目知识库` | `build_mini_dist\tea_agent\session\.tea_agent_run\kb.md:1` | chapter |
| `to_multimodal` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:11` | object |
| `to_multimodal` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:118` | array |
| `to_multimodal` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:16` | array |
| `try_fix_truncated_json` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:39` | object |
| `try_fix_truncated_json` | `build_mini_dist\tea_agent\session\.tea_agent_run\call_graph.json:206` | array |
| `try_fix_truncated_json` | `build_mini_dist\tea_agent\session\.tea_agent_run\symbol_index.json:65` | array |
| `模块索引 (6 文件)` | `build_mini_dist\tea_agent\session\.tea_agent_run\kb.md:15` | section |
| `生成文件` | `build_mini_dist\tea_agent\session\.tea_agent_run\kb.md:51` | section |
| `符号种类分布` | `build_mini_dist\tea_agent\session\.tea_agent_run\kb.md:8` | section |

## 模块 `build_mini_dist\tea_agent\skills`

### 类

| 类名 | 文件:行号 | 类型 |
|------|----------|------|
| `Skill` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:39` | class |
| `SkillCrystallizer` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:79` | class |
| `SkillRegistry` | `build_mini_dist\tea_agent\skills\skill_registry.py:35` | class |
| `__init__` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:106` | member |
| `__init__` | `build_mini_dist\tea_agent\skills\skill_registry.py:38` | member |
| `__post_init__` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:57` | member |
| `_extract_intent` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:237` | member |
| `_extract_steps` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:209` | member |
| `_extract_success_conditions` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:288` | member |
| `_extract_tags` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:315` | member |
| `_extract_task_features` | `build_mini_dist\tea_agent\skills\skill_registry.py:271` | member |
| `_generate_description` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:275` | member |
| `_generate_id` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:179` | member |
| `_generate_name` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:252` | member |
| `_infer_category` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:194` | member |
| `_load_index` | `build_mini_dist\tea_agent\skills\skill_registry.py:52` | member |
| `_match_query` | `build_mini_dist\tea_agent\skills\skill_registry.py:319` | member |
| `_save_index` | `build_mini_dist\tea_agent\skills\skill_registry.py:70` | member |
| `_score_relevance` | `build_mini_dist\tea_agent\skills\skill_registry.py:338` | member |
| `confidence` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:70` | member |
| `crystallize` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:116` | member |
| `get_skill` | `build_mini_dist\tea_agent\skills\skill_registry.py:145` | member |
| `list_all` | `build_mini_dist\tea_agent\skills\skill_registry.py:157` | member |
| `list_skills` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:367` | member |
| `load_skill` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:356` | member |
| `recommend` | `build_mini_dist\tea_agent\skills\skill_registry.py:234` | member |
| `register` | `build_mini_dist\tea_agent\skills\skill_registry.py:77` | member |
| `remove_skill` | `build_mini_dist\tea_agent\skills\skill_registry.py:363` | member |
| `save_skill` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:347` | member |
| `search` | `build_mini_dist\tea_agent\skills\skill_registry.py:164` | member |
| `stats` | `build_mini_dist\tea_agent\skills\skill_registry.py:401` | member |
| `success_rate` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:64` | member |

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `TOOL_CATEGORIES` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:83` | variable |
| `__all__` | `build_mini_dist\tea_agent\skills\__init__.py:28` | variable |
| `created_at` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:53` | variable |
| `fail_count` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:52` | variable |
| `last_used` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:54` | variable |
| `logger` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:35` | variable |
| `logger` | `build_mini_dist\tea_agent\skills\skill_registry.py:32` | variable |
| `success_count` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:51` | variable |
| `tags` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:55` | variable |
| `time_seconds` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:50` | variable |
| `token_cost` | `build_mini_dist\tea_agent\skills\skill_crystallize.py:49` | variable |

## 模块 `build_mini_dist\tea_agent\skills\agent-browser`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Observability Dashboard` | `build_mini_dist\tea_agent\skills\agent-browser\SKILL.md:53` | section |
| `Specialized skills` | `build_mini_dist\tea_agent\skills\agent-browser\SKILL.md:29` | section |
| `Start here` | `build_mini_dist\tea_agent\skills\agent-browser\SKILL.md:15` | section |
| `Why agent-browser` | `build_mini_dist\tea_agent\skills\agent-browser\SKILL.md:44` | section |
| `agent-browser` | `build_mini_dist\tea_agent\skills\agent-browser\SKILL.md:8` | chapter |

## 模块 `build_mini_dist\tea_agent\skills\ai-elements`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `AI Elements` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:6` | chapter |
| `Available Components` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:158` | section |
| `Customization` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:83` | section |
| `Example` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:35` | section |
| `Extensibility` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:79` | section |
| `I ran the AI Elements CLI but nothing was added to my project` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:114` | subsection |
| `Installing Components` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:23` | section |
| `My AI coding assistant can't access AI Elements components` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:147` | subsection |
| `Prerequisites` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:14` | section |
| `Still stuck?` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:154` | subsection |
| `The component imports fail with “module not found”` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:132` | subsection |
| `Theme switching doesn’t work — my app stays in light mode` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:128` | subsection |
| `Troubleshooting` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:108` | section |
| `Usage` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:31` | section |
| `Why are my components not styled?` | `build_mini_dist\tea_agent\skills\ai-elements\SKILL.md:110` | subsection |

## 模块 `build_mini_dist\tea_agent\skills\analyze-pdf`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Real-World Example` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:130` | section |
| `Step 1: Bulk Document Analysis` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:26` | subsection |
| `Step 2: Intelligent Table Extraction` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:49` | subsection |
| `Step 3: Data Quality Validation` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:63` | subsection |
| `Step 4: Automated Analysis and Insights` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:85` | subsection |
| `Step 5: Dashboard Creation` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:110` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:24` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:20` | section |
| `Transform PDF Reports Into Actionable Data and Cut Analysis Time` | `build_mini_dist\tea_agent\skills\analyze-pdf\SKILL.md:10` | chapter |

## 模块 `build_mini_dist\tea_agent\skills\autoresearch`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Autoresearch — Autonomous Goal-directed Iteration` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:8` | chapter |
| `Dispatch (bare `$autoresearch`)` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:16` | section |
| `Orchestration Loop Steps` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:72` | subsection |
| `Orchestrator` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:64` | section |
| `Orchestrator Safety Invariants` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:97` | subsection |
| `Orchestrator State` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:93` | subsection |
| `Safety Invariants (all subcommands)` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:10` | section |
| `Subcommands` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:30` | section |
| `Universal Flags` | `build_mini_dist\tea_agent\skills\autoresearch\SKILL.md:49` | section |

## 模块 `build_mini_dist\tea_agent\skills\browser-trace`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Best practices` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:229` | section |
| `Browser Trace` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:9` | chapter |
| `Browserbase remote` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:71` | subsection |
| `Drilling in with `query.mjs`` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:184` | subsection |
| `Filesystem layout` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:123` | section |
| `How it works` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:38` | section |
| `Local Chrome` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:50` | subsection |
| `Quickstart` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:48` | section |
| `Setup check` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:24` | section |
| `Summary shape` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:155` | subsection |
| `Top traversal recipes` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:201` | section |
| `Troubleshooting` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:240` | section |
| `What you get from the Browserbase platform` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:111` | subsubsection |
| `When to use` | `build_mini_dist\tea_agent\skills\browser-trace\SKILL.md:15` | section |

## 模块 `build_mini_dist\tea_agent\skills\caveman`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Auto-Clarity` | `build_mini_dist\tea_agent\skills\caveman\SKILL.md:58` | section |
| `Boundaries` | `build_mini_dist\tea_agent\skills\caveman\SKILL.md:76` | section |
| `Intensity` | `build_mini_dist\tea_agent\skills\caveman\SKILL.md:32` | section |
| `Persistence` | `build_mini_dist\tea_agent\skills\caveman\SKILL.md:13` | section |
| `Rules` | `build_mini_dist\tea_agent\skills\caveman\SKILL.md:19` | section |

## 模块 `build_mini_dist\tea_agent\skills\codebase-design`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Codebase Design` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:6` | chapter |
| `Deep vs shallow` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:30` | section |
| `Designing for testability` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:67` | section |
| `Glossary` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:10` | section |
| `Going deeper` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:111` | section |
| `Principles` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:60` | section |
| `Rejected framings` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:105` | section |
| `Relationships` | `build_mini_dist\tea_agent\skills\codebase-design\SKILL.md:97` | section |

## 模块 `build_mini_dist\tea_agent\skills\debug-incident`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Debug Production Incidents with AI Log Analysis` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:10` | chapter |
| `Real-World Example` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:130` | section |
| `Step 1: Feed in the Logs` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:26` | subsection |
| `Step 2: Identify the Error Pattern` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:38` | subsection |
| `Step 3: Correlate Across Services` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:56` | subsection |
| `Step 4: Build the Incident Timeline` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:80` | subsection |
| `Step 5: Analyze Error Rate Trends` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:118` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:22` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\debug-incident\SKILL.md:18` | section |

## 模块 `build_mini_dist\tea_agent\skills\manage-docker`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Optimize Docker Workflows and Cut Build Times by 70%` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:10` | chapter |
| `Real-World Example` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:201` | section |
| `Step 1: Audit the Current Docker Setup` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:26` | subsection |
| `Step 2: Multi-Stage Build Optimization` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:40` | subsection |
| `Step 3: Fix Orchestration with Proper Health Checks` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:98` | subsection |
| `Step 4: Optimize the CI/CD Pipeline` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:148` | subsection |
| `Step 5: Standardize the Developer Workflow` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:182` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:24` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\manage-docker\SKILL.md:20` | section |

## 模块 `build_mini_dist\tea_agent\skills\manage-monorepo`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Manage Monorepo Dependencies with AI` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:10` | chapter |
| `Real-World Example` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:128` | section |
| `Step 1: Map the Monorepo Structure` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:26` | subsection |
| `Step 2: Audit Dependency Versions` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:49` | subsection |
| `Step 3: Fix Mismatches with a Plan` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:69` | subsection |
| `Step 4: Check for Security Issues` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:92` | subsection |
| `Step 5: Set Up Ongoing Enforcement` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:108` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:24` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\manage-monorepo\SKILL.md:20` | section |

## 模块 `build_mini_dist\tea_agent\skills\optimize-sql`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Optimize SQL Queries and Database Performance` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:10` | chapter |
| `Real-World Example` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:150` | section |
| `Step 1: Identify and Profile the Slowest Queries` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:26` | subsection |
| `Step 2: Analyze Execution Plans to Find Bottlenecks` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:48` | subsection |
| `Step 3: Rewrite Queries and Add Indexes` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:78` | subsection |
| `Step 4: Set Up Performance Monitoring` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:126` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:24` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\optimize-sql\SKILL.md:20` | section |

## 模块 `build_mini_dist\tea_agent\skills\output-format-constraint`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `1. 输出结构` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:37` | subsection |
| `2. 工具使用规范` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:56` | subsection |
| `3. 输出示例` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:68` | subsection |
| `4. 禁止行为` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:84` | subsection |
| `规则（严格遵守）` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:35` | section |
| `输出规范约束（小模型版）` | `build_mini_dist\tea_agent\skills\output-format-constraint\SKILL.md:33` | chapter |

## 模块 `build_mini_dist\tea_agent\skills\process-excel`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `Real-World Example` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:140` | section |
| `Step 1: Multi-File Ingestion and Standardization` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:26` | subsection |
| `Step 2: Duplicate Detection and Cleaning` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:53` | subsection |
| `Step 3: Data Quality Analysis` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:75` | subsection |
| `Step 4: Business Insight Generation` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:97` | subsection |
| `Step 5: Automated Dashboard and Reporting` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:123` | subsection |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:24` | section |
| `The Problem` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:20` | section |
| `Transform Messy Spreadsheets Into Business Intelligence and Save 20 Hours Weekly` | `build_mini_dist\tea_agent\skills\process-excel\SKILL.md:10` | chapter |

## 模块 `build_mini_dist\tea_agent\skills\test-api-endpoints`

### 函数

| 函数名 | 文件:行号 | 类型 |
|--------|----------|------|
| `1. Define what to test` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:24` | subsection |
| `2. Build and send requests` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:28` | subsection |
| `3. Responses are validated` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:32` | subsection |
| `4. Results are reported clearly` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:40` | subsection |
| `5. Failures are diagnosed` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:71` | subsection |
| `Real-World Example` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:75` | section |
| `Step-by-Step Walkthrough` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:22` | section |
| `Test API Endpoints with AI` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:10` | chapter |
| `The Problem` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:12` | section |
| `The Solution` | `build_mini_dist\tea_agent\skills\test-api-endpoints\SKILL.md:16` | section |

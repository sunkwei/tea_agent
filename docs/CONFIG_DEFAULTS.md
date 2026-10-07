# 配置事实源与默认参数全清单

> 2026-10-05 · config.yaml 已彻底删除

## 一、事实源

| 文件 | 状态 | 内容 |
|---|---|---|
| `~/.tea_agent/provider.yaml` | **唯一事实源** | `providers` / `models` / `api_keys` + `roles` + `settings` |
| `~/.tea_agent/config.yaml` | **已删除** | 信息全部并入 provider.yaml |
| `model_config.json` | 已废弃 | 代码不再读写 |
| `config_*.yaml` | 已废弃 | 不再派生 provider，不再迁移 |

覆盖变量：`TEA_PROVIDER_FILE`（provider.yaml 路径）、`TEA_CONFIG`（仅作来源标记）、`TEA_DB_PATH`（db 路径覆盖）。

## 二、provider.yaml 段结构

```yaml
version: 1
providers:            # 供应商 + 逐模型能力（原 models 段）
  <p_name>:
    api_url: ...
    api_key: ...      # = api_keys[0]
    api_keys: [...]
    default_model: ...
    source: builtin|custom
    models:
      <m_name>: {max_context_tokens, max_output_tokens, supports_vision,
                 supports_reasoning, supports_tools, reasoning_effort,
                 temperature, top_p, note}
roles:                # 主/便宜模型绑定（原 config.yaml 的 main/cheap_model）
  main:  {provider, model, api_url, updated_at}
  cheap: {provider, model, api_url, updated_at}
settings:             # 运行时参数（原 config.yaml 顶层标量 + paths）
  keep_turns: 10
  ...
```

## 三、默认参数（代码内置，config.py）

### 模型与会话
| 键 | 默认 | 说明 |
|---|---|---|
| `max_history` | 10 | 最大历史消息数 |
| `max_iterations` | 200 | 最大工具调用迭代 |
| `keep_turns` | 10 | 保留完整对话轮数；也是 L2 压缩后的压回水位 |
| `max_tool_output` | 131072 | 工具输出截断字符 |
| `max_assistant_content` | 131072 | 助手回复截断字符 |

### 思考与推理
| 键 | 默认 | 说明 |
|---|---|---|
| `enable_thinking` | true | thinking 总开关 |
| `thinking_strength` | 0.7 | 思考强度 0.0–1.0 |
| `reasoning_effort` | `auto` | auto/none/minimal/low/medium/high/xhigh/max |

### 记忆与上下文分层
| 键 | 默认 | 说明 |
|---|---|---|
| `memory_extraction_threshold` | 2 | 触发记忆提取的最低未摘要消息数 |
| `memory_dedup_threshold` | 0.3 | 记忆去重相似度阈值 |
| `chat_page_size` | 50 | 单页对话轮数 |
| `history_l2_max` | 0 | L2 条数上限约束（0=自动，= keep_turns+batch） |
| `history_l3_batch` | 0 | L3 摘要批大小（0=自动 = keep_turns//2） |
| `l2_thinking_max_chars` | 6000 | 单条 L2 thinking 上限 |
| `l2_max_chars` | 120000 | L2 总量触发摘要阈值 |
| `rc_keep_steps` | 8 | L1 reasoning_content 分块回传步数 |

### API 弹性
| 键 | 默认 |
|---|---|
| `api_request_timeout` | 120.0 s |
| `api_connect_timeout` | 30.0 s |
| `api_max_retries` | 3 |
| `api_retry_backoff` | 2.0 s |
| `api_sleep_recovery_wait` | 5.0 s |
| `opencode_session_header` | true |
| `api_headers` | `{}` |

### 打断知识闭环 `interruption`
`enabled=true` · `similarity_threshold=0.25` · `partial_reply_max=2000` · `persist_events=true` · `analyze_interval_h=1.0` · `keep_days=30` · `skill_min_count=3`

### 任务阶段推荐温度 `PHASE_DEFAULT_TEMP`
develop 0.2 · test 0.2 · review 0.15 · devops 0.3 · design 0.45 · docs 0.5 · creative 0.8 · mixed 0.6 · pragmatic 0.2

### 路径 `paths`（默认全空 → 按兜底解析）
`data_dir` / `db_path` / `storage_scope` / `toolkit_dir` / `kb_dir` / `skills_dir` 均为 `""`。

## 四、DB 解析优先级

| # | 条件 | 结果 |
|---|---|---|
| 1 | `TEA_DB_PATH` / `paths.db_path` 绝对路径 | 尊重该路径 |
| 2 | `storage_scope=user` | 用户级 `~/.tea_agent/chat_history.db` |
| 3 | auto/project 且启动目录可写 | **项目级** `<cwd>/.tea_agent_run/chat_history.db` |
| 4 | 启动目录 == `$HOME` | 用户级（不建 `.tea_agent_run`） |
| 5 | 项目目录不可用 | 系统临时 `$TMPDIR/tea_agent_<name>_<digest>.db`（提示备份） |
| 6 | 临时也不可用 | 回退用户级 |

A CP 入口用 `TEA_DB_PATH` 隔离为 `chat_acp.db`（原 `config_acp.yaml` 机制已移除）。

## 五、落盘位置

**用户级 `~/.tea_agent/`**：`provider.yaml`、`os_state.json`、`evolution_exp.json`、`self_evolve_state.json`、`cross_topic_counter.json`、`scheduler.db`、`memory.db`、`kb/`、`commands/`、`exports/`

**项目级 `.tea_agent_run/`**：`chat_history.db`、`audit/`、`bench_history.jsonl`

## 六、兼容保留（签名在，语义已变）

| 符号 | 现语义 |
|---|---|
| `load_config(config_path)` | 忽略参数，由 provider.yaml 构建 |
| `save_config(cfg, config_path)` | 写 provider.yaml（roles + settings），返回其路径 |
| `resolve_config_path()` | 恒返回 `None` |
| `Agent._load_config(path)` | 显式路径不再抛 `FileNotFoundError` |
| `run_setup_wizard()` | 委托 `run_provider_setup_wizard()` |
| `--config` CLI | 废弃，仅告警 |
| `create_default_config` / `_build_config` / `scan_config_profiles` | 已删除 |

## 七、环境变量（22 个）

- **存储/配置**：`TEA_PROVIDER_FILE` `TEA_CONFIG` `TEA_DB_PATH` `TEA_STORAGE_SCOPE`
- **工具治理**：`TEA_TOOL_SHIELD` `TEA_TOOL_SHIELD_IDLE_DAYS` `TEA_FILE_ALLOW_OUTSIDE`
- **进化闸门**：`TEA_EVOLVE_GATE` `TEA_EVOLVE_GATE_THRESHOLD` `TEA_SNAPSHOT_REF` `TEA_GIT_SNAPSHOT_MODE` `TEA_EVO_PYC_ISOLATION`
- **审计/日志**：`TEA_AUDIT_DIR` `TEA_AUDIT_DISABLED` `TEA_BENCH_HISTORY` `TEA_EVOLUTION_LOG`
- **其它**：`TEA_API_KEY` `TEA_AGENT_API_URL` `TEA_SERVER_STATE_DB` `TEA_OS_STATE_FILE` `TEA_SPILL_THRESHOLD` `TEA_SUBAGENT_WORKERS`

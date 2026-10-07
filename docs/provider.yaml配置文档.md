# provider.yaml 配置文档

> `~/.tea_agent/provider.yaml` —— Tea Agent 的**唯一事实源**。
> 供应商端点、API Key、逐模型能力、角色绑定（main/cheap）、运行时参数全部在此声明。
> `config.yaml` 已删除，不再存在第二份配置。

- 默认路径：`~/.tea_agent/provider.yaml`
- 路径覆盖：环境变量 `TEA_PROVIDER_FILE`
- 生成方式：首次启动 `tea-agent-api` 自动引导，或 Web 界面 🏭「供应商与模型配置」页写回
- 代码入口：`tea_agent/provider_store.py`（`ProviderStore`）

---

## 1. 文件总览

```yaml
version: 1                    # schema 版本，当前恒为 1
providers:                    # 供应商目录（见 §2）
  <provider_name>: {...}
roles:                        # 角色绑定（见 §4）
  main: {...}
  cheap: {...}
settings:                     # 运行时参数（见 §5）
  ...
updated_at: '2026-10-07T10:15:13'   # 自动写入，勿手工维护
```

| 键 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `version` | int | 否 | schema 版本，缺省补 `1` |
| `providers` | map | **是** | 供应商名 → 供应商块；缺失或非 map 会触发 bootstrap 重建 |
| `roles` | map | 否 | `main` / `cheap` 角色绑定 |
| `settings` | map | 否 | 运行时参数（会话/Token/路径/打断） |
| `updated_at` | str | 自动 | 每次落盘刷新，`%Y-%m-%dT%H:%M:%S` |

---

## 2. 供应商块 `providers.<name>`

```yaml
providers:
  DeepSeek:
    api_url: https://api.deepseek.com
    api_key: sk-xxxxxxxx
    api_keys:
      - sk-xxxxxxxx
      - sk-yyyyyyyy
    default_model: deepseek-flash
    description: DeepSeek 官方 API
    supports_vision: true
    supports_thinking: true
    source: builtin
    models:
      deepseek-flash: {...}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `api_url` | str | OpenAI 兼容端点。多数服务商需带 `/v1` 后缀，以各家文档为准 |
| `api_key` | str | **主密钥**。`api_keys` 存在时恒等于 `api_keys[0]`（自动归一化） |
| `api_keys` | list[str] | 多密钥（轮换/备份用）。**加载只用首个**；去空、去重、保序 |
| `default_model` | str | 默认模型 id，须存在于 `models`；缺省取 `models` 第一个键 |
| `description` | str | 一句话说明，仅展示 |
| `supports_vision` | bool | 供应商级能力**兜底**（模型级未声明时继承） |
| `supports_thinking` | bool | 同上，映射到模型的 `supports_reasoning` |
| `source` | str | 来源标记：`builtin` / `custom` / `config`，仅迁移与展示用 |
| `models` | map | 模型目录（见 §3） |

**供应商名约束**：`^[A-Za-z0-9_.:/-]{1,64}$`，即字母、数字、`_ . : / -`，长度 1–64。
非法名会被拒绝：`invalid provider name 'xxx'`。

**密钥掩码**：对外接口（`list_providers`）返回掩码形式。
`sk-abc123456789xyz` → `sk-abc****xyz`；长度 ≤ 12 时 → `前2位****`。

**自动字段**：`live_synced_at` 由「同步线上模型」写入，记录最近一次拉取 `/v1/models` 的时间，勿手工编辑。

---

## 3. 模型块 `providers.<name>.models.<model_id>`

模型属性**唯一来源就是这里**。自 2026-09-06 起，代码不再按模型名猜测任何属性 ——
未收录的模型一律取全 0（=未知），需显式补配。

```yaml
models:
  deepseek-flash:
    max_context_tokens: 1000000
    max_output_tokens: 384000
    supports_vision: true
    supports_reasoning: true
    supports_tools: true
    reasoning_effort: auto
    temperature: 0.7
    top_p: 0.9
    note: ''
```

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `max_context_tokens` | int | `0` | 最大上下文窗口。**0 = 未知**，会退化为默认 1M，建议显式填写 |
| `max_output_tokens` | int | `0` | 最大单次输出（模型能力上限） |
| `supports_vision` | bool | `false` | 能否接收图片 |
| `supports_reasoning` | bool | `false` | 是否有思维链（`reasoning_content`） |
| `supports_tools` | bool | `true` | 是否支持 function calling |
| `reasoning_effort` | str \| list | `auto` | 思考强度，见下方值域 |
| `temperature` | float | `0.7` | 采样温度，**钳制到 0.0–2.0** |
| `top_p` | float | `0.9` | 核采样，**钳制到 0.0–1.0** |
| `note` | str | `''` | 备注，截断到 200 字符 |

**`reasoning_effort` 值域**（`REASONING_EFFORT_VALUES`）：
`auto` / `none` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max`

- `auto` = 自动推导且**不下发**该参数
- 也可写成**列表**（如 `[low, medium, high]`），表示该模型接受的值域；
  请求时按 `REASONING_EFFORT_RANKS` 取最接近档位（同距取更强档）
- 非法值回退 `auto`

**类型收敛行为**：非 dict 条目 → 全默认；int 字段转换失败 → 保留默认（记 debug 日志）；
float 字段超界 → 钳制；未知字段 → **丢弃**。

**有效能力解析**（`get_model` / `resolve`）：模型级优先，缺失时回落到供应商级
（`supports_vision` ← 供应商 `supports_vision`；`supports_reasoning` ← 供应商 `supports_thinking`）。

---

## 4. 角色绑定 `roles`

main / cheap 两个角色指向「供应商 + 模型」组合。

```yaml
roles:
  main:
    provider: opencode
    model: deepseek-v4.1-flash
    api_url: https://opencode.ai/zen/go/v1
    updated_at: '2026-10-07T09:13:44'
  cheap:
    provider: opencode
    model: mimo-v2.6-flash
    api_url: https://opencode.ai/zen/go/v1
    updated_at: '2026-10-07T09:13:44'
```

| 字段 | 说明 |
|---|---|
| `provider` | 供应商名，须存在于 `providers` |
| `model` | 模型 id，须存在于该供应商的 `models` |
| `api_url` | 冗余记录，便于面板展示；缺失时按 provider 反查补齐 |
| `updated_at` | 自动写入 |

角色绑定为**引用式**：密钥与端点不在此内嵌，运行时从 `providers` 解析。
`main_model` 缺失时兜底取 `providers` 中**文档序第一个**供应商的默认模型。

---

## 5. 运行时参数 `settings`

原 `config.yaml` 顶层标量迁移至此。全部可缺省，缺省取代码内默认值。

```yaml
settings:
  paths:
    db_path: ds_flash.db
  max_history: 10
  max_iterations: 200
  enable_thinking: true
  thinking_strength: 0.7
  reasoning_effort: auto
  keep_turns: 10
  max_tool_output: 131072
  max_assistant_content: 131072
  rc_keep_steps: 8
  memory_extraction_threshold: 2
  memory_dedup_threshold: 0.3
  chat_page_size: 50
  history_l2_max: 8
  history_l3_batch: 5
  l2_thinking_max_chars: 6000
  l2_max_chars: 120000
  interruption:
    enabled: true
    similarity_threshold: 0.25
    partial_reply_max: 2000
    persist_events: true
    analyze_interval_h: 1.0
    keep_days: 30
    skill_min_count: 3
```

### 5.1 会话参数

| 键 | 说明 |
|---|---|
| `max_history` | 保留历史轮数 |
| `max_iterations` | 单回合最大工具迭代次数 |
| `enable_thinking` | 是否启用思考模式 |
| `thinking_strength` | 思考强度（0–1） |
| `reasoning_effort` | 全局思考档位，值域同 §3 |

### 5.2 Token 优化

| 键 | 说明 |
|---|---|
| `keep_turns` | 完整保留的最近轮数，更早的走摘要 |
| `max_tool_output` | 单条工具输出字符上限 |
| `max_assistant_content` | 单条 assistant 内容字符上限 |
| `rc_keep_steps` | 保留 `reasoning_content` 的步数 |

### 5.3 记忆与历史

| 键 | 说明 |
|---|---|
| `memory_extraction_threshold` | 触发记忆提取的阈值 |
| `memory_dedup_threshold` | 记忆去重相似度阈值 |
| `chat_page_size` | 会话列表分页大小 |
| `history_l2_max` | L2 滚动窗口上限 |
| `history_l3_batch` | L2→L3 批量压缩条数 |
| `l2_thinking_max_chars` | L2 中思考内容字符上限 |
| `l2_max_chars` | L2 总字符上限 |

### 5.4 打断知识闭环 `interruption`

| 键 | 说明 |
|---|---|
| `enabled` | 是否启用打断分析 |
| `similarity_threshold` | 打断相似度阈值 |
| `partial_reply_max` | 部分回复保留字符上限 |
| `persist_events` | 是否持久化打断事件 |
| `analyze_interval_h` | 后台分析间隔（小时） |
| `keep_days` | 事件保留天数 |
| `skill_min_count` | 固化为技能的最小出现次数 |

### 5.5 路径 `paths`

| 键 | 默认 | 说明 |
|---|---|---|
| `data_dir` | `~/.tea_agent` | 数据根目录 |
| `db_path` | `chat_history.db` | 会话库路径 |
| `storage_scope` | `auto` | 存储作用域：`auto` / `project` / `user` |
| `toolkit_dir` | `~/.tea_agent/toolkit` | 动态工具目录 |
| `kb_dir` | `~/.tea_agent/kb` | 知识库目录 |
| `skills_dir` | `~/.tea_agent/skills` | 技能目录 |

> 相对路径**相对于 provider.yaml 所在目录**解析。
> `storage_scope` 语义见 AGENTS.md「存储作用域」：`auto` 优先项目级
> `$pwd/.tea_agent_run/`，不可写时回退系统临时目录。

---

## 6. 读写与持久化行为

| 行为 | 说明 |
|---|---|
| 原子落盘 | 临时文件 + `os.replace`，避免半写坏文件 |
| 自动备份 | 每次写前复制 `provider.yaml.bak.YYYYmmdd_HHMMSS` |
| 热重载 | 按文件 `mtime` 自动重载，无需重启 |
| 容错 | 解析失败/结构异常 → 告警并重建 bootstrap（不崩） |
| 密钥归一化 | 每次加载后执行：`api_keys` 去空去重保序，`api_key` 恒等于首位 |
| 首启 bootstrap | 仅从 `custom_providers.yaml` 一次性迁移；内置目录**不**整体写入 |

**bootstrap 数据源**：仅 `~/.tea_agent/custom_providers.yaml`（含 key 时一并并入）。
内置静态目录（`providers.py` 的 `PROVIDERS`）只用于命名匹配与能力速查，**绝不预置无 key 的供应商**。

---

## 7. 常见问题

**Q：模型显示 `max_context_tokens: 0` 会怎样？**
退化为默认 1M 窗口。建议在 `models.<id>` 显式填写，否则上下文预算计算会偏大。

**Q：想换 API Key？**
改 `api_key` 即可；若同时存在 `api_keys`，加载后 `api_key` 会被归一化为 `api_keys[0]`，
故应同步调整列表首位（或直接改列表）。

**Q：多个 Key 如何生效？**
仅 `api_keys[0]` 用于请求，其余为轮换/备份保留。

**Q：`config.yaml` 还在用吗？**
已删除。历史调用点（`resolve_config_path` 等）恒返回 `None`，仅为签名兼容保留。

**Q：手工编辑后需要重启吗？**
不需要。按 `mtime` 自动重载。

**Q：环境变量 `TEA_PROVIDER_FILE` 有什么用？**
指向其它路径，用于测试隔离或多实例并行。

---

## 8. 最小可用示例

```yaml
version: 1

providers:
  deepseek:
    api_url: https://api.deepseek.com
    api_key: sk-xxxxxxxxxxxxxxxx
    default_model: deepseek-chat
    description: DeepSeek 官方 API
    supports_vision: false
    supports_thinking: true
    models:
      deepseek-chat:
        max_context_tokens: 128000
        max_output_tokens: 8192
        supports_tools: true
        reasoning_effort: auto

roles:
  main:
    provider: deepseek
    model: deepseek-chat
```

本地 Ollama（无需真实 Key）：

```yaml
providers:
  ollama:
    api_url: http://localhost:11434/v1
    api_key: ollama
    default_model: qwen3.6
    models:
      qwen3.6:
        max_context_tokens: 32768
        max_output_tokens: 8192
        supports_tools: true
        note: 本地模型窗口较小，显式填写避免误判为大窗口
```

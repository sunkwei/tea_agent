# Tea Agent 代码评审报告 — AI 面向、工具正交化、DeepSeek V4 缓存、Storage 平衡

> 评审时间：2026-08-22　评审范围：`tea_agent/`（279 个 py 文件）、`tea_agent/toolkit/`（68 个内置工具）、`tea_agent/store/`（17 张表）
> 评审人视角：代码是给 **AI** 读的，不是给人读的；主模型 deepseek-v4；目标是最大化前缀缓存命中率、最小化每请求 token 成本、最小化模型路由歧义。

---

## 0. 总评

代码库已经完成了一轮非常成熟的 **DeepSeek 前缀缓存专项优化**（0.8% 命中率的教训 → L0 静态化 / 入库定型 / 水位线单调 / L2 定型 / 动态上下文尾部注入，`docs/CACHE_PREFIX_STABILITY.md` 规范完整且执行到位），并已落地 **DSH 式 append-only 事件日志 + 派生视图**。方向正确，值得肯定。

剩余的主要问题集中在三个未被触达的角落：

1. **工具集过大且全量常驻**（68 工具 ≈ 14K token/请求，主会话与子 Agent 都一样）——这是当前最大的单项未命中成本，也是模型路由歧义的来源；
2. **工具加载顺序不稳定**（`os.listdir` 非排序）——工具 JSON 顺序变化直接破坏缓存前缀；
3. **Storage 三份冗余**（conversations + agent_rounds + session_events 写同一份数据 3~5 次）+ 工具结果缓存采用"黑名单"而非"白名单"导致的正确性风险。

---

## 1. 代码是给 AI 看的（AI-facing 质量评估）

### 1.1 每请求成本结构（AI 每次都要"读"的东西）

| 输入 | 规模 | 是否命中缓存 |
|------|------|------------|
| L0 系统提示词（静态富化） | ~2-4K tokens | ✅ 稳定命中 |
| L3 摘要 + L2 相关历史 + L1 对话 | 随对话增长 | ✅ 前缀命中（已定型） |
| **68+ 工具 JSON Schema** | **~14K tokens（代码注释实测值）** | ❌ **尾部，每请求全量未命中** |
| 尾部动态上下文 | ~0.5-2K | ❌ 每轮变化 |

**结论：工具 schema 是每请求最大的固定成本，且全部落在缓存未命中区。** 正交化（删/并工具）直接 = 省钱 + 提速 + 减少路由歧义。这正是用户第 2 点的价值所在。

### 1.2 Meta schema 质量问题（AI 直接读的界面）

已发现的 AI-facing 缺陷（按严重度排序）：

1. **参数描述为空**：
   - `toolkit_lsp`：**所有必填参数（action/filepath/line/col/...）description 全为空**——模型完全不知道这些参数干什么；
   - `toolkit_diff`：`action`/`files`/`description` 描述为空；
   - `toolkit_plan`：`action` 描述为空（1294 行的大工具，却给不出参数说明）；
   - `toolkit_eval_loop`：`rules` 参数类型是 `['array','object','string']` 联合类型，违反 OpenAI 严格 schema，且规则格式说明被截断。
2. **营销文案式描述**：`toolkit_auto_pipeline` 描述为"【突破性创新】…前所未有的元能力…工具共生网络"——AI 会当真并优先选它，而它只是个关键词模板匹配器。
3. **互相引用的描述**：`toolkit_diff_edit` 描述"相比 toolkit_edit 多了 diff 输出和冲突检测"——迫使模型同时理解两个工具再抉择，路由成本翻倍。
4. **过时/失真的系统提示词**：`prompt_manager.DEFAULT_SYSTEM_PROMPT` 与 `litesession._default_system_prompt` 是**两份漂移的副本**，都写着"内置工具：toolkit_exec、toolkit_file、toolkit_save_file"，与实际 68 工具集不符（save_file 若删除则提示词失真）。应改为单一来源 + 动态注入工具名。
5. **宣传了但已废弃的参数**：`toolkit_subagent` 的 meta 仍列 `allowed_tools`/`denied_tools`，但 `LiteSession` 与 subagent 实现已明确标注"已废弃，自由奔放模式"，**参数被静默忽略**——模型以为能限制子 Agent 工具集，实际不能。

### 1.3 做得好的（值得保持）

- `history_builder.py` / `CACHE_PREFIX_STABILITY.md` 中的不变式注释（"派生只依赖事件流"、"Model-visible means logged"）是给 AI 维护者的高质量指引；
- 工具返回结构统一 `{"ok": bool, "error": str, ...}`，AI 易于解析；
- 命名规范（`toolkit_<动词>`）一致，描述大多为简体中文、含参数含义。

---

## 2. 工具正交化评估（是否删除）

### 2.1 正交化判据

每个工具应满足：**实现一个不可由其他工具组合出的原语**。三个删除判据：
- **可组合**：`exec + file + search` 等原语能拼出来 → 删；
- **零相关性**：与编码 Agent 任务无关 → 删；
- **实验残留**：自进化生成的重复品/一次性实验 → 删或并入。

### 2.2 删除候选（10 个，预计每请求省 ~2.5-3.5K token）

| 工具 | 理由 | 建议 |
|------|------|------|
| `toolkit_lunar` | 农历转换，编码任务零相关，`js_fetch`/web 可替代 | **DELETE** |
| `toolkit_weather_my` | 天气，编码任务零相关 | **DELETE**（个人场景可留 user_dir） |
| `toolkit_get_config_path` | 95 行读一个模块变量；`toolkit_config` 可覆盖 | **DELETE**（并入 config） |
| `toolkit_get_models` | 35 行读 3 个模型名；`toolkit_config(action=list)` 覆盖 | **DELETE**（并入 config） |
| `toolkit_self_report` | 状态报告是给人看的；`harness_schema` 已含工具清单 | **DELETE**（并入 harness_schema） |
| `toolkit_harness_schema` | 机器可读能力清单，消费方是 MCP/CI **不是 Agent 自身** | **移出工具集** → 做成 `/v1/harness.json` API |
| `toolkit_git_push_all_remotes` | 41 行 = `git remote \| xargs git push` | **DELETE**（exec 可组合） |
| `toolkit_auto_pipeline` | 关键词 regex 编排器，让 LLM 绕道一个哑规划器；模板引用 code_review/diff_edit/run_tests，牵一发动全身 | **DELETE**（主模型本身就是编排器） |
| `toolkit_toggle_reasoning` | `config.set(key=enable_thinking)` 已覆盖（白名单含该键） | **DELETE**（并入 config） |
| `toolkit_dump_topic` | 与 `query_chat_history(action=topic)` 重叠的导出 | **DELETE**（保留 query_chat_history） |

### 2.3 合并候选（5 组，预计再省 ~1.5-2K token）

| 合并组 | 分析 | 建议 |
|--------|------|------|
| `toolkit_diff_edit` → `toolkit_edit` | diff_edit ≈ edit.replace_text + diff 输出 + 冲突检测（自进化生成的重复品，描述互相引用） | `toolkit_edit` 增加 `return_diff` 参数，**DELETE diff_edit**，更新 auto_pipeline/diff 中的引用 |
| `toolkit_screen_read` → `screenshot + ocr + browser_tab` | screen_read = screenshot(region) + ocr + 浏览器标签，纯组合封装 | **DELETE screen_read**（保留 screenshot 原语 + ocr 的 screenshot_ocr） |
| `toolkit_save_file` → `toolkit_file(action=write)` | save_file 仅多 chunking/base64/append | 把 chunking 并入 `file.write`，**DELETE save_file**（注意 DEFAULT_SYSTEM_PROMPT 引用） |
| `toolkit_evolution_exp` → `toolkit_experience_solidify` | solidify 内部已委托 evolution_exp（两库同一数据） | 保留 solidify（结构化 skill/lesson），**DELETE evolution_exp** |
| `toolkit_export_last_pdf` | 1246 行重型 PDF 导出，消费方是人 | **移出工具集** → server endpoint（同 harness_schema） |

### 2.4 保留（原语，建议常驻核心集）

`exec`、`file`、`edit`（合并后）、`search`、`memory`、`kb`、`lsp`、`subagent`、`subagent_msg`、`question`、`todo`、`plan`、`scheduler`、`mcp`、`js_fetch`、`notify`、`clipboard`、`input`、`screenshot`、`ocr`、`vision_analyze`、`git_commit`、`self_evolve`、`prompt_evolve`、`reflection`、`experience_solidify`、`mode`、`config`、`save/reload/rollback/list_versions`、`set_topic_title`、`topic_prompt`、`fork_session`、`publish_doc`、`build`、`pkg`、`release_version`、`batch_process`、`code_review`、`eval_loop`（`agent_evolution.py` 在调用）、`custom_commands`、`browser_tab`、`sudo_gui`、`task_resume`、`query_chat_history`、`send_email`（borderline）、`remote_agent`（borderline）、`proactive`（borderline）、`parallel_subtasks`（borderline，与 subagent 重叠可后议）、`format_code`、`run_tests`、`screenshot_picker`（低优先级）。

**执行后预计：68 → ~50 个工具，每请求省 3-5K token 未命中，同时路由歧义显著下降。**

### 2.5 机制层面的正交化（比删工具更重要）

- `build_tools()` 全量发送 + `filter_tools()` 是 **no-op**（"自由奔放"）+ `LiteSession` 同样全量 + subagent `allowed_tools` 已废弃。**建议实现"核心常驻 + 按需注入"**：常驻 15-20 个核心原语，其余工具仅在意图分析命中时注入（`_analyze_intent` 已有雏形，`required_tools` 字段已存在但 `filter_tools` 被禁用）。
- 这与缓存直接相关：工具子集越小且越稳定，尾部未命中越小。

---

## 3. DeepSeek V4 缓存命中率（专项）

### 3.1 已落地且正确的（不要动）

- L0 系统提示词静态化；动态片段全部 exclude / 尾部注入（修复了 0.8% 的根因）；
- 入库定型链：`_cap_message_text` / `_compress_tool_content` / `_solidify_history` / `_solidify_level2` / `_writeback_content`；
- 水位线单调 clamp（`_loop_max_ratio`）+ `_loop_trim_done` + 尾部动态上下文锚定 `_l1_start` + `_dynamic_ctx_cache` + `_b64_cache`；
- 真实 usage 校准估算 + `cache_report.format_cache_hit_rate` 输出。

### 3.2 剩余缓存杀手（按影响排序）

1. **工具集过大 + 全量发送**（~14K token/请求未命中；见 §1.1、§2）。DeepSeek 缓存是**逐字节前缀匹配**，工具定义参与输入（Qwen-code 为此专门做了 [Global Tool Schema Stable Sort](https://qwenlm.github.io/qwen-code-docs/en/design/prompt-cache/global-tool-schema-stable-sort/) 与 [stabilize DeepSeek tool cache prefix](https://github.com/QwenLM/qwen-code/pull/4518)）：工具越多，未命中越大；工具内容/顺序一变，其后前缀全断。
2. **工具加载顺序不稳定（确定性 bug）**：`tlk.py reload()` 用 `os.listdir(d)` 遍历（文件系统顺序，**非排序**）构建 `temp_funcs`/`meta_map`。跨进程、增删工具后，工具 JSON 顺序可能变化 → 工具块字节变化 → 缓存断裂。**修复：`for filename in sorted(os.listdir(d))`**，并建议固定全局工具顺序（白名单排序）。
3. **`toolkit_save`/`reload` 中途改变工具集**：自进化线程或 Agent 保存新工具后，当回合后续请求的工具块变化 → 全断。权衡：可接受（低频），但建议在 reload 后记日志并接受一次 miss；或工具子集在请求内快照。
4. **Web 模式每请求新建 session**（`onlinesession.py` 注释：`create_session` 每次 /api/chat 新建）：`context.messages` 从 DB 重建后，`_level2_selected` / `_loop_max_ratio` / `_loop_trim_done` 等**定型状态丢失** → L2 重算 + 水位线重新决策，周期性断缓存（M2-fix 只恢复了 interruption 锚点，未恢复定型状态）。建议 Web 场景持久化/重建这些定型字段，或复用 session 对象。
5. **归因缺口**（文档已承认）：只有聚合命中率，无法定位断点。建议按 `(round, hit_rate, 变更事件类型)` 记录序列（DSH telemetry 思路）。
6. ~~`max_context_tokens` 未配置时默认 128K~~ **（勘误：实际默认是 1M）**。核实链路：`SessionContext.max_context_tokens=0` → `_resolve_max_ctx` 调 `get_max_context_tokens()`（auto_compact.py:66）——未显式配置时统一返回 **1048576（1M）**，不做模型名推断；128000 仅作为极端兜底（`get_max_context_tokens` 抛异常 / `config is None` 时）。因此 `input_budget = 0.8 × 1M = 800K`，不存在"128K 过早裁剪"。注意 `config.py` 模板注释仍写"按模型名自动推断：deepseek/gemini→1048576, claude→200000, 未知→128000"，与实现不符，建议更新模板注释（见 §5b 补充）。

### 3.3 与"只追加"原则的一致性（好消息）

`context.messages` 已被当作 append-only 日志对待（入库定型 = 永不回改），这正是 DSH "Model-visible means logged" 的落地，与 §4 的事件日志互为表里。**这一设计是缓存命中的基石，务必保持。**

---

## 4. Append-only Log 与当前 Storage 的平衡

### 4.1 现状盘点（17 张表）

同一份对话数据当前被写 **3 份**：
1. `conversations`（user_msg / ai_msg / **rounds_json**）——权威存储，GUI/搜索直读；
2. `agent_rounds`（每轮一行）——rounds_json 的**明细冗余**；
3. `session_events`（append-only：turn/start、user/message、assistant/message、tool/call、tool/result、turn/end、session/fork）——审计事实源，供 trajectory API / GUI 轨迹 / fork 血统 / 打断恢复。

另有 `msg_vectors`（异步 embedding）、`t_conv_summary`、`memories`、`system_prompts`、`reflections`、`interruption_events`、`scheduled_tasks`、`forks` 等派生/功能表。

写入路径实测：每轮对话 = conversations 1 INSERT + 1 UPDATE（ai_msg/rounds_json）+ agent_rounds N INSERT + session_events **~6+ 条** INSERT（含逐 tool 2 条同步写）+ embedding 异步写。

### 4.2 评估结论

**方向正确，当前平衡点略"重"，建议向 DSH 靠拢三步：**

1. **立即**：消除 `rounds_json` 与 `agent_rounds` 双写（同一数据两份冗余）。保留 `agent_rounds`（SQL 可查、benchmark 依赖），废弃 `rounds_json` 列（迁移脚本清理历史值）。
2. **短期**：`tool/call` + `tool/result` 事件目前**每工具 2 次同步 DB 写**（`_log_tool_event` 在 `execute_tool_call` 内）。改为**工具循环结束后批量 flush**（内存队列 + 单事务），审计语义不变，主路径少 N 次写。`_log_event` 已有异常隔离（try/except），保持。
3. **中期**：让 `conversations` 也变成**派生视图**（DSH 式：事件为唯一事实源，`derive_messages` 已存在雏形），GUI/搜索读派生结果；`conversations` 降级为只读缓存或由 FTS5 索引替代。同时给 `session_events` 加**保留策略**（如 keep_days=90 + 定期压缩 assistant/chunk 合并为 assistant/message），否则 append-only 无界增长（`interruption_events` 已有 keep_days=30 的先例）。

### 4.3 风险提示（正确性，独立于 §2/§3）

`Toolkit.call_tool` 的工具结果缓存采用**黑名单**（默认全缓存 30s，黑名单 23 个）。但有副作用/时间敏感的工具有 ~45 个未被列入，例如：
- `toolkit_question`（阻塞等用户输入——**缓存后第二次调用返回第一次的答案，错误**）；
- `toolkit_todo` / `toolkit_scheduler` / `toolkit_fork_session` / `toolkit_publish_doc` / `toolkit_notify` / `toolkit_send_email`（状态/副作用）；
- `toolkit_ocr` / `toolkit_screenshot` / `toolkit_screen_read` / `toolkit_clipboard`（**屏幕/剪贴板内容在 30s 内会变**）；
- `toolkit_lunar`（date_str 默认今天——缓存 30s 会返回"昨天"）；
- `toolkit_subagent`（spawn 子 Agent——缓存会吞掉第二次 spawn）。

**修复：改为显式白名单**（只缓存纯函数：file 读、search、lsp、memory 查询、kb 查询、get_models、query_chat_history 等），其余一律真实执行。这比继续扩黑名单更安全（默认不缓存，逐个放行）。

---

## 5. 行动清单（按 ROI 排序）

| # | 动作 | 影响 | 工作量 |
|---|------|------|--------|
| 1 | `tlk.py` 改为 `sorted(os.listdir(d))` + 固定工具顺序 | 消除工具块顺序漂移导致的缓存断裂 | S |
| 2 | `call_tool` 缓存改**白名单**（纯函数才缓存） | 修复 question/todo/screenshot 等 45 个工具的正确性 bug | S |
| 3 | 删除 10 个低价值工具（§2.2）+ 合并 5 组（§2.3） | 68→~50 工具，每请求省 3-5K token 未命中，路由更准 | M |
| 4 | 实现"核心常驻 + 按需注入"工具集（启用 `filter_tools`） | 工具尾部从 14K → 3-4K token | M |
| 5 | subagent meta 删除/实现 `allowed_tools`；LiteSession 全量问题 | 消除误导 + 子 Agent 场景降本 | S |
| 6 | Web 场景恢复定型状态（`_level2_selected` 等持久化） | Web 模式缓存稳定性 | M |
| 7 | 事件日志批量 flush + 保留策略；废弃 rounds_json 双写 | Storage 收敛到"事件为事实源" | M |
| 8 | 修复空参数描述（lsp/diff/plan/eval_loop）；统一 DEFAULT_SYSTEM_PROMPT 单一来源；清理 TOOLS.md 过期条目 | AI-facing 质量 | S |
| 9 | `harness_schema` / `export_last_pdf` 移出工具集改为 API | 每请求再省 ~0.8-1.5K token | S |
| 10 | 缓存归因序列日志（round, hit_rate, 变更事件） | 命中率可观测性 | M |

---

## 5b. 落实状态（2026-08-22 实施）

| # | 状态 | 落实内容 |
|---|------|---------|
| 1 | ✅ 已落地 | `tlk.py reload()` 遍历改为 `sorted(os.listdir(d))`；新增 `tlk.llm_tool_names()` 全局排序（工具 Schema 顺序稳定） |
| 2 | ✅ 已落地 | `_CACHE_BLACKLIST` → `_CACHE_WHITELIST`（仅 file/lsp/search/query_chat_history/list_provider_models/eval_loop/task_resume 纯函数缓存，其余真实执行） |
| 3 | ✅ 已落地 | 删除 13 个工具文件：lunar / weather_my / get_config_path / get_models / self_report / git_push_all_remotes / auto_pipeline / toggle_reasoning / dump_topic / **diff_edit→edit** / **save_file→file** / **screen_read→删** / **evolution_exp→solidify**（59 注册 / 57 暴露给 LLM） |
| 4 | ⚠️ 机制就位 | `filter_tools` 由 no-op 改为"核心集常驻 + 意图集追加"；`analyze_intent` 仍为 stub（恒 None），故**默认行为不变**（全量工具），后续接入真实意图分析即生效 |
| 5 | ✅ 已落地 | subagent meta 移除 allowed_tools/denied_tools（实现已废弃，避免误导）；LiteSession 改为 llm_tool_names 暴露 |
| 6 | ⏸ 未做（需 server 层改动，风险高） | 列入后续 |
| 7 | ◑ 部分落地 | `session_events` 新增 `cleanup_old_events(keep_days=90)` 并在后台小时循环执行（防无界增长）；**rounds_json 双写未删**（被 benchmark/server/export_last_pdf/tests 8+ 处依赖，属大迁移，列入后续）；工具事件批量 flush 未做（同步写有异常隔离，正确性优先） |
| 8 | ✅ 已落地 | lsp/diff/plan/eval_loop 参数描述补全；eval_loop rules/baseline/candidate 非法联合类型修复；DEFAULT_SYSTEM_PROMPT 单一来源（litesession 改为 import）；TOOLS.md 待后台线程自动重生成 |
| 9 | ✅ 已落地（改 API 前的第一步） | `LLM_TOOL_EXCLUDES` 机制：harness_schema / export_last_pdf 仍注册（server 依赖）但不再暴露给 LLM；后续可再加 `/v1/harness.json` 端点 |
| 10 | ⏸ 未做 | 列入后续（需在 cache_report 侧记录序列日志） |

**验证**：合并行为单测通过（edit return_diff/strict、file chunks/append、solidify list/record/search，新增 `test_experience_solidify.py` 5 例）；全量 pytest（USERPROFILE 隔离沙箱日志）**12 failed / 1074 passed，4 个失败文件全部在基准预存名单内（context_fragments / git_snapshot / onlinesession / stream_retry，均为环境类：AGENTS.md 根标记、git 沙箱、流式网络），无新增回归**；ruff 仅剩预存问题（onlinesession/tool_loop_runner/_events 等 24 处非本次改动）。

**勘误补充（2026-08-22）**：§3.2 第 6 点原称"未配置时默认 128K"有误——实际默认 1M（1048576，`auto_compact.get_max_context_tokens`），128K 仅为极端兜底。已修正正文，并顺带更新 `config.py` 模板注释（原"按模型名自动推断"与实际实现不符）。

---

## 6. 参考资料

- [DeepSeek Context Caching 官方文档](https://api-docs.deepseek.com/guides/kv_cache/)
- [Qwen-code: stabilize DeepSeek tool cache prefix (PR #4518)](https://github.com/QwenLM/qwen-code/pull/4518)
- [Qwen-code: Global Tool Schema Stable Sort Design](https://qwenlm.github.io/qwen-code-docs/en/design/prompt-cache/global-tool-schema-stable-sort/)
- [permafrost: What makes Claude Code miss DeepSeek's cache](https://github.com/jianzhichun/permafrost/blob/main/docs/cache-busters.md)
- 本仓库 `docs/CACHE_PREFIX_STABILITY.md`、`docs/cache_hit_rate_analysis.md`、`docs/TOOLS.md`

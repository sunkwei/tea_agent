# 前缀缓存稳定性规范（CACHE_PREFIX_STABILITY）

> **目标读者**：所有改动 `history_builder` / `basesession` / `context_fragments` /
> `tool_loop_runner` / `onlinesession` 的开发者（含 Agent 自进化线程）。
>
> **核心原则（对齐 DeepSeek Harness）**：**派生只依赖事件流，绝不依赖"当前请求"**。
> 同一事件流 → 同一消息序列；任何"查询相关"的动态计算都被限制在**消息入库边界**，
> 禁止在每轮请求构建时重算。

---

## 1. 背景：DeepSeek 前缀缓存机制

DeepSeek API 的 **Context Caching（上下文缓存）** 默认对所有用户启用（官方文档
`api-docs.deepseek.com/guides/kv_cache/`），计费与延迟都依赖它：

| 字段 | 含义 |
|------|------|
| `prompt_cache_hit_tokens` | 本次请求**命中缓存**的前缀 token 数 |
| `prompt_cache_miss_tokens` | 本次请求**未命中**的 token 数 |

**命中规则**：缓存以**前缀**为单位。请求前缀中任意**一个字节变化**，其后的全部内容
都无法命中（缓存键是逐 token 的前缀匹配）。

> ⚠️ **实测教训**：早期版本把动态内容注入 system prompt（消息前缀首元素），
> 导致整条前缀缓存 100% 失效——**实测命中率仅 0.8%**（569K 未命中 vs 4.6K 命中）。

---

## 2. 消息布局与缓存分层

`build_api_messages` 构建的消息序列（前缀→后缀）：

```
[L0 system] → [L3 摘要] → [L2 相关历史] → [L1 最新对话] → [尾部动态上下文]
   ↑稳定          ↑低频变化      ↑入库定型       ↑最新轮          ↑临时注入
```

**缓存友好性从前往后递减**，前缀越靠前越必须稳定：

| 层 | 内容 | 变化频率 | 缓存策略 |
|----|------|---------|---------|
| L0 system | 系统提示 + OS信息 + 静态片段 | 极低 | **必须稳定**；动态片段全部排除 |
| L3 摘要 | 语义摘要 + 工具链摘要 | 低频（增量） | 摘要**追加**在末尾，禁止整体重写 |
| L2 相关历史 | 相关性过滤的旧对话 | **入库定型** | 只在消息边界重算（S1-A） |
| L1 最新对话 | 最近轮次 + 工具输出 | 每轮新增 | 已发送部分**入库定型**，禁止二次改写 |
| 尾部动态 | 技能/TODO/记忆 | 每轮变化 | **临时 user 消息**，不持久化、不进 system |

---

## 3. 铁律（必须遵守）

### R1. 动态内容永远不进入 system prompt
技能加载、未完成任务提醒、长期记忆、当前时间、token 预算等**随请求变化**的内容，
禁止注入 L0 system prompt。

- ✅ 正确：注入消息**尾部**（`_build_dynamic_context` 返回的临时 user 消息）
- ✅ 正确：时间/token 预算在 `add_user_message` 入库时**定格**（`_append_runtime_status`）
- ❌ 错误：每轮请求动态拼进 system prompt → 前缀全断（0.8% 教训）

### R2. 消息入库即定型（Solidify）
任何可能被后续请求**二次改写**的内容，必须在**入库时**完成改写并持久化：

| 场景 | 定型点 | 幂等守卫 |
|------|--------|---------|
| tool 输出过长 | `add_tool_result`（入库压缩） | `[工具结果已省略` / `[工具输出截断` |
| user/assistant 超长文本 | `add_user_message` / `add_assistant_message`（`_cap_message_text`） | `[已截断` |
| 已发送前缀中的旧消息 | `_solidify_history`（滑出窗口时） | 同左 |

**禁止**：`build_api_messages` 每轮对**已发送过**的消息做动态裁剪/改写
（水位线 Tier1/2/3 裁剪只允许作用于**本轮新消息**，见 R4）。

### R3. L2 相关性过滤必须入库定型（S1-A）
`filter_level2_by_relevance` 依赖"当前用户消息"做查询相关检索——这是缓存杀手。
**修复（已落地）**：

- `SessionContext._level2_dirty`：`add_user_message` 时置 `True`
- `_solidify_level2(context)`：dirty 时用最新用户消息**一次性**计算并存入
  `_level2_selected`，随后置 `False`
- `build_api_messages` **直接读 `_level2_selected`**，不重算

```
add_user_message ──→ dirty=True
build_api_messages → _solidify_level2() 重算一次并定型
工具循环内 N 次请求 → 读定型结果，L2 零变化 ✅
下一条新消息 ──────→ dirty=True → 边界重算 → 重新定型
```

> 效果：L2（前缀第 3 段）在工具循环内完全稳定，其后 L1 历史可命中缓存。

> ✅ **设计确认（2026-08-28）**：L2 重筛在**每个用户消息边界**用新消息重算
> （`filter_level2_by_relevance`）。**话题切换时命中率下降是有意为之**——功能
> 正确性优先：话题变了，模型本就需要新的相关历史（L2 存在的意义），旧话题的
> L1 前缀失效是预期成本，**不做**会话级定型（那会牺牲话题自适应）。
> 缓存优化的目标边界：**同一话题内**前缀逐字节稳定（接近 99%），
> 话题切换时接受一次性失效。

### R4. 水位线裁剪只作用于新消息
`build_api_messages` 的 Tier1/2/3 裁剪（`_snip_tier1` / `_progressive_trim`）
只允许裁剪**本轮新增**的消息。已发送过（已进入前缀）的消息必须在入库时定型
（R2），确保裁剪不会翻转"上一轮完整版 → 本轮占位符"。

**落地实现（2026-08 修复，命中率根因）**：
- **首建即定型**：水位线裁剪只在**本轮首次** `build_api_messages` 执行，并把每个
  裁剪决定（工具占位符 / 文本截断 / L2 剔除）**写回 `context.messages` 定性**
  （`_src_idx` 写回 + L2 `_level2_selected` 收敛）。随后同一工具循环内的请求
  **跳过裁剪**（`context._loop_trim_done` 守卫），仅追加新工具结果 →
  **已发送前缀逐字节不变，全命中缓存**。
- **单调 clamp**：`context._loop_max_ratio` 取当前轮已到达的最大 ratio，防止
  `_calibrated_estimate` 的 scale 在相邻请求间振荡导致 tier 0↔1↔2 反复翻转、
  同一工具消息 full↔snipped 交替（曾实测每大工具结果破坏一次前缀缓存）。
- **重定位禁令（2026-08 修订）**：尾部动态上下文消息**追加在请求消息末尾**
  （`result.append`），不再锚定 `_l1_start`。原因：技能/TODO/记忆随**用户消息边界**
  重算（`add_user_message` 清 `_dynamic_ctx_cache`），若插在 L1 历史之前，任何内容
  变化都会使其后**全部 L1 历史**前缀缓存失效（实测命中率 99% → ~62%，见
  `scripts/diag_cache_prefix.py`）。追加到末尾后：L0+L3+L2+L1 前缀跨回合逐字节
  稳定，仅末尾动态消息/工具结果作为新 token 未命中 —— 与 DSH 的
  `dsh-time-context`（时间消息追加到消息列表末尾）同构。user 后跟 user 是合法
  消息结构（DSH 同款形态），API 接受。
- **压缩真阈值**：`_compress_tool_content` 为标记行预留 96 字节，保证压缩结果
  **≤ 阈值**（65536），杜绝"入库压缩后仍超阈值 → 滑出窗口又被替换为占位符"
  的两阶段翻转。

- ✅ `add_tool_result` 入库即压缩 → 永不二次改写
- ✅ `_loop_trim_done` / `_loop_max_ratio` 由 `add_user_message` 在每回合边界清零
- ⚠️ `tool_loop_runner` 直接 `context.messages.append` 的 assistant 消息
     应走 `_cap_message_text` 定型；策略3 清空 reasoning 时回写 context 定型（S2 已落地）

### R5. 图片编码必须快照缓存
`to_multimodal` 的 `_b64_cache`：同一图片文件在**覆盖前**各请求复用同一 base64 编码。
禁止每轮重新编码（内容相同但编码字节可能不同 → 破坏前缀）。

### R6. 会话级动态上下文缓存
`_get_dynamic_context` 缓存到 `context._dynamic_ctx_cache`，工具循环内复用同一版本；
仅在新用户消息入库时失效（`add_user_message` 置 `None`）。

---

## 4. `assemble_fragments` 的 exclude 清单

`_build_l0_enriched_system` 调用 `assemble_fragments` 时必须排除动态片段：

```python
frag_text = assemble_fragments(
    context,
    exclude=["session_budget", "token_budget", "current_time", "environment"],
)
```

**⚠️ 新增片段时必须同步加入 exclude**，否则新动态片段会静默进入 system prompt
破坏前缀。建议未来改造：在 `assemble_fragments` 内部做**缓存安全白名单**
（仅允许静态片段进 system），而非调用方黑名单。

---

## 5. 缓存命中率观测

- **工具**：`cache_report.py`（`format_cache_hit_rate` / `cache_hit_rate_number`）
- **入口**：`agent.py` / `agent_module.py` / `gui.py` 任务结束输出
  `缓存命中率: xx.x% (hit X / miss Y)`
- **依据**：`usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`

**归因缺口**：当前是聚合值，无法定位"哪一轮/哪个构建步骤导致缓存断裂"。
建议记录 `(round, hit_rate, 变更事件类型)` 序列（DSH telemetry 思路，待落地）。

---

## 6. 变更检查清单（改代码前过一遍）

- [ ] 新注入内容是否放在了**消息尾部**而非 system prompt？
- [ ] 新消息（user/assistant/tool）是否在**入库时**定型？
- [ ] 是否调用了 `filter_level2_by_relevance`？→ 必须经 `_solidify_level2`
- [ ] 是否新增了 context fragment？→ 检查是否需加入 `exclude` 清单
- [ ] 是否在 `build_api_messages` 内对**已发送前缀**做动态改写？→ 禁止
- [ ] 图片路径改动是否影响 `_b64_cache` 复用？

---

## 7. 相关文件索引

| 文件 | 角色 |
|------|------|
| `tea_agent/session/history_builder.py` | L0-L3 拼接、`_solidify_history`、`_solidify_level2`、水位线裁剪 |
| `tea_agent/basesession.py` | `add_user_message` / `add_assistant_message` / `add_tool_result`（入库定型点） |
| `tea_agent/session/context.py` | `_level2_selected` / `_level2_dirty` / `_dynamic_ctx_cache` 字段 |
| `tea_agent/context_fragments.py` | 上下文片段组装（动态/静态分类） |
| `tea_agent/session/tool_loop_runner.py` | 工具循环（additionalContexts 消费、assistant 消息 append） |
| `tea_agent/session/cache_report.py` | 缓存命中率报告 |
| `docs/deepseek-harness-调研报告.md` | DSH 事件溯源/fork 调研背景 |

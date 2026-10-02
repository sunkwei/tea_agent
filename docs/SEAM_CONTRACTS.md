# Tea Agent — Seam 契约表（借鉴 dsh「每个 seam 有显式契约」）

> 对应 P0/P1 落地项（invariants / spill / token_meter / compaction）。
> 规则：类型契约 + 错误分类 + 生命周期事件，三者缺一即「隐式 seam」。

## 1. 会话事实层

| Seam | 契约 | 错误分类 | 事件 |
|---|---|---|---|
| chat_history.db → L1/L2/L3 投影 | append-only 事件，投影纯函数可重放 | 读失败→空投影（fail-open）；写失败→仅告警 | turn_start / turn_end |
| turn_snapshot | 内容寻址，turn_start 后不可变 | 缺行→显式 dangling 标记（不静默） | snapshot/record |
| session_events（append-only） | seq topic 内递增，无 UPDATE/DELETE | 断裂/坏行→replay 跳过（不中断） | step/request 等（EVENT_TYPES） |
| turn_meta | `same_series`：prev 必须是 current 逐条前缀 | 违例→仅日志（旁路观测） | startsRequestSeries |

## 2. 工具执行层

| Seam | 契约 | 错误分类 | 事件 |
|---|---|---|---|
| `Toolkit.call_tool`（唯一汇聚点） | 入参绑定预检 TypeError→结构化自纠错误 | 参数错 / 拒绝 / 执行错 三分 | tool/call · tool/result |
| `toolkit_exec` 归一化 | 等价形态收敛，位置不漂移 | 参数错→`_exec_arg_error`（含正确用法） | 同上 |
| spill | 超阈值文本→`SpillRef(locator, chars, preview)` | 落盘失败→回退截断（fail-open） | 无（纯旁路） |
| token_meter | `cache_hit_ratio→[0,1] \| None` | 垃圾输入→None（绝不抛） | 无（纯旁路） |

## 3. 压缩层

| Seam | 契约 | 错误分类 | 事件 |
|---|---|---|---|
| `compact_messages` 策略入口 | `(messages, keep_recent, summary, max_len)→(msgs, summary)` | 空/短消息→原样返回 | pre_compact / post_compact hooks |
| 策略注册表 | `register_compaction_strategy(None)` 恢复默认 | 未注册→truncate 默认 | 无 |

## 4. 安全层

| Seam | 契约 | 错误分类 | 事件 |
|---|---|---|---|
| tool_approval | 风险分级 → enforce/advisory/off | 高风险未授权→结构化 deny（含授权路径） | approval/deny |
| audit_log | hash 链防篡改，pre/post 双记录 | 写失败→debug 跳过（不阻断） | tool/call · tool/result |
| invariants | `install/run/enforce`，检查器异常按违例 | 违例→`evaluate` 回退「不屏蔽」 | invariant/violation |
| tool_shield | 无数据不屏蔽 / 观测期不满不屏蔽 / 自愈通路永不屏蔽 | 闸门失效→测试红 | shield/verdict |

## 5. 生命周期

| 事件 | 触发点 | 消费方 |
|---|---|---|
| turn_start | 会话入口 | snapshot / audit / L0 |
| step（一次请求+工具调用） | tool_loop_runner | token_meter / decode_speed |
| turn_end | `_finalize_turn_reply` | 摘要 / 记忆提取 / storage_notice |
| 前缀缓存重置点 | startsRequestSeries（turn_meta） | token_meter 命中率归零观测 |

## 待落（P2 后续）

- [x] `startsRequestSeries`：turn_meta 接线 litesession/onlinesession
- [x] SessionEvent append-only → L1/L2/L3 投影化（project_l1/l2/l3 + 兜底接线）
- [ ] 审计覆盖低风险调用（可选，评估开销）

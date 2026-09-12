# Tea Agent A+B 实施报告（安全底座 + 进化基准）

> 实施日期：2026-09-12 · 基准版本：v0.15.4 · git `490a500`
> 依据：《dsh / opencode 对比与 tea_agent 下一步方向》——结论是「不去补 TUI/插件市场，把自进化从信仰变成可度量的资产」。

## 一、结论先行

| 交付项 | 状态 | 证据 |
|---|---|:---|
| A 安全底座（凭据隔离 / 审计链 / 审批闸门） | ✅ 完成 | 回归测试 32/32 |
| B 进化基准（EvolutionBench + keep-or-rollback） | ✅ 完成 | 基准 **7/7 任务、score 1.0** |
| 顺手修掉的真实缺陷 | ✅ 2 处 | `rm -rf /` 漏判、`eval` 多语句崩溃 |

**第一个进化曲线数据点**：`score=1.0, passed=7/7, tasks_ok=7/7, tag=A+B-v0, git=490a500`

## 二、A 部分：安全底座（自进化的前提）

一个能改自己代码的 Agent，如果执行环境会泄漏凭据、改动无审计、高风险动作无闸门，那「自进化」就是炸弹。A 解决这个前提。

### A1 子进程凭据隔离 — `tea_agent/toolkit/toolkit_exec.py`

- `_build_scrubbed_env()`：spawn 时丢弃命中 `KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|AUTH` 的环境变量，其余（PATH/HOME 等）保留
- **4 处 Popen 全部接入**（single / batch / sudo-gui / pkexec），无遗漏路径
- 效果：模型执行 `echo $DEEPSEEK_API_KEY` 不再把 harness 凭据泄入对话历史与日志

### A2 append-only 审计日志 — `tea_agent/audit_log.py`（343 行，零依赖）

- **append-only**：一天一个 JSONL，只追加；链首用 `GENESIS_HASH`
- **hash 链**：每条记录含 `prev` + `h = sha256(prev + canonical(body))`，篡改/插入/删除均可被 `verify()` 检出
- **脱敏**：键名命中敏感词整体掩码；值命中密钥形态（`sk-*` / `ghp_*` / `AKIA*` / `xox?-*`）替换
- **降级安全**：目录不可写则静默关闭，绝不阻断主流程
- 位置：`.tea_agent_run/audit/audit-YYYYMMDD.jsonl`（`TEA_AUDIT_DIR` 可覆盖）

### A3 审批闸门 — `tea_agent/tool_approval.py` + `toolkit/toolkit_approve.py`

三档模式（`security.approval_mode` 或 `TEA_APPROVAL_MODE`）：

| 模式 | 行为 |
|---|---|
| **off**（默认） | 全放行，仅审计高风险动作 —— 保持「自由奔放」哲学 |
| **advisory** | 全放行，但对需审批动作打标 `approval: required`（可观测不阻断） |
| **enforce** | 高风险动作缺失授权即**拒绝**（对齐 DSH「缺失=拒绝」） |

风险分级（确定性，`classify_risk`）：`critical`（self_evolve / sudo / 破坏性命令）→ `high`（git/pip/python、工具与配置变更）→ `medium`（写盘、格式化）→ 只读为 `None`。
授权入口：`toolkit_approve(action=grant|revoke|list|status)`，名单存 `.tea_agent_run/approval_allow.json`。

### 工具链路接线 — `tea_agent/tool_hooks.py`

`run_pre()` 内惰性挂载 `tool_approval` + `evolution_gate` 钩子：自动覆盖 lite / online 两条工具路径，无需改会话代码；`clear()` 后自愈重挂；任一钩子不可用只记 debug，绝不阻断工具执行。

## 三、B 部分：EvolutionBench（把「AI 写 AI」变成数字）

原 `toolkit_self_evolve` 的门槛只有「编译过 + 测试过」，无法回答「这一版是否比上一版更好」。B 补上这个判断。

### B1 确定性基准引擎 — `tea_agent/evaluation/evo_bench.py`

**3 种 check 形态（纯代码，零 LLM）：**

| 形态 | 配置 | 判定 |
|---|---|---|
| `command` | `{"run": "python -m py_compile x.py", "expect": "子串"}` | exit 0 且含 expect |
| `file` | `{"path": "a.py", "contains": "...", "regex": "..."}` | 文件存在且匹配 |
| `python` | `{"expr": "assert ..."}` / `{"expr": "bool_expr"}` | 真值即通过 |

表达式可用名字：`root`(Path) / `read(rel)` / `os` / `re` / `json` / `Path`。

**内置 7 个任务（同时是 A 的回归网络）：**

| id | 类别 | 度量什么 |
|---|---|---|
| `safety-env-scrub` | safety | 环境清洗函数存在**且 ≥4 处 Popen 接入** |
| `safety-audit-chain` | safety | 脱敏生效 + 审计写入 + `verify()` 链路完整 |
| `safety-approval-classify` | safety | 风险分级确定性（含 `rm -rf /` → critical） |
| `safety-approval-mode` | safety | 三档模式解析与环境变量覆盖 |
| `safety-hooks-wired` | safety | 审批/审计/闸门钩子确实接入执行链路 |
| `tooling-bench-selfcheck` | tooling | 基准引擎自身可用（3 类 check 已注册） |
| `integrity-compile` | tooling | 新增模块 `py_compile` 通过 |

**可扩展**：`benchmarks/*.json` 放入任务 JSON 即合并进基准（按 id 去重），改基准不用改代码。

**进化曲线**：结果 append 到 `.tea_agent_run/bench_history.jsonl`，每点含 `ts / tag / score / passed / total / git`，构成「分数随版本变化」的曲线。

### B2 keep-or-rollback 闸门 — `tea_agent/evolution_gate.py`

`toolkit_self_evolve` 成功后自动挂 post-hook：跑基准快照 → 写曲线 → 与上一数据点比对 → 给出决策。

| 模式 | 行为 |
|---|---|
| `off` | 完全关闭（零开销） |
| **`advisory`**（默认） | 跑基准 + 记录曲线 + 在结果里附建议，**不改变任何文件** |
| `enforce` | 决策为 `rollback` 时，自动从 self_evolve 生成的 `.bak.<ts>` 恢复该文件 |

阈值 `TEA_EVOLVE_GATE_THRESHOLD`（默认 0.0 = 必须严格提升才算 keep）：
- `delta > threshold` → **keep**
- `delta < 0` → **rollback**（改进使表现变差）
- 其余 → **no_change**（默认建议回滚到基线）

决策同时写入审计日志（`evolve/gate` 事件），形成「改了 → 分数变没变 → 是否保留」的完整闭环。

### B3 工具入口 — `toolkit/toolkit_evo_bench.py`

`action=run`（跑基准，可 `record=True` 记曲线）· `action=history`（看曲线数据点）· `action=compare`（keep/rollback 决策）。

> ⚠️ **注册生效时机**：`toolkit_approve` / `toolkit_evo_bench` 经 `toolkit_reload()` 已注册进 func_map，但**本轮会话已注入的 tools schema 不会即时刷新**——下一轮对话或重启后即可直接调用（属预期行为，非缺陷）。

## 四、验证结果

### 回归测试：32/32 通过

```
32 passed in 0.61s
```

覆盖：引擎 3 类 check / 任务执行 / **失败隔离** / 环境清洗 / 内置 safety 任务全绿 / 审批分级与豁免 / **`rm -rf` 漏判回归** / 审计脱敏 + **hash 独立复算** + **篡改检出** / 闸门幂等挂载 / `.bak` 自动恢复（取最新）。

### 真实基准：7/7 任务，score = 1.0

```
SCORE 1.0 | 7 / 7 | tasks 7 / 7
SNAP {ts: 2026-09-12T09:48:30+08:00, tag: A+B-v0, score: 1.0,
      passed: 7, total: 7, ok: True, git: 490a500}
```

### 实施过程中修掉的 2 个真实缺陷

1. **`rm -rf /` 不会被判 critical**（`tool_approval.py`）
   破坏性命令检测只扫描 `args`，拼出的是 `"-rf /"`，匹配不到 `"rm -rf /"` 标记 → 改为 `app + args` 共同参与匹配。已加回归测试固定。
2. **`_check_python` 对多语句表达式崩溃**（`evo_bench.py`）
   原实现 `src.startswith("assert")` 判断过窄，以赋值开头的断言串走 `eval()` → `SyntaxError`，导致 5 个 safety 任务连锁失败。改为「先尝试 `compile(..., "eval")`，失败回退 `exec`」。

## 五、怎么用

```bash
# 1) 跑基准（默认全量；kind=safety 更快）
#    Agent 内也可直接调用: toolkit_evo_bench(action="run", record=True, tag="v1")
python -c "from tea_agent.evaluation.evo_bench import run_bench; print(run_bench(root='.', record=True, tag='v1')['score'])"

# 2) 看进化曲线
python -c "from tea_agent.evaluation.evo_bench import history; [print(p['score'], p['tag'], p['git']) for p in history()]"

# 3) 开启审批闸门（默认 off，不影响现有行为）
set TEA_APPROVAL_MODE=enforce        & rem Windows
rem export TEA_APPROVAL_MODE=enforce # Linux/macOS

# 4) 把闸门提升为「分数不涨就自动回滚」
set TEA_EVOLVE_GATE=enforce
set TEA_EVOLVE_GATE_THRESHOLD=0.0
```

## 六、下一步建议

1. **跑 20 轮形成真实曲线**：当前只有 1 个数据点（1.0）。把任务集扩到 20-30 个（bug 修复 / 工具创建 / 提示词优化），曲线才有信息量。
2. **把 `enforce` 作为自进化默认**：等任务数 ≥20 且分数稳定后，把 `evolution.gate` 从 `advisory` 调为 `enforce`，让「分数不涨就回滚」成为硬门槛。
3. **曲线进 README**：把「第 1 轮 vs 第 N 轮」的成功率 / token 消耗画出来 —— 这是 DSH、opencode 都拿不出的差异化证据。

---

*本报告由 tea_agent 自身生成。A+B 代码与测试：`tea_agent/audit_log.py`、`tea_agent/tool_approval.py`、`tea_agent/evolution_gate.py`、`tea_agent/evaluation/evo_bench.py`、`tea_agent/toolkit/toolkit_approve.py`、`tea_agent/toolkit/toolkit_evo_bench.py`、`tea_agent/tests/test_evo_bench.py`*

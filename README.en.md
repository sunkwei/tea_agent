# Tea Agent v0.16.6

> ⚠️ **Experimental project — AI writing AI. Use at your own risk.**

> 🌐 **[中文版](README.md)**

> **A self-evolving AI coding assistant** — not just completing coding tasks, but modifying its own code, creating new tools, and optimizing its own prompts. It gets stronger with every task.

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.16.6-blue)](https://pypi.org/project/tea-agent)

---

## 🎯 Tea Agent in One Glance

| | |
|---|---|
| 🧠 **Self-Evolving** | AI writing AI — modifies its own code, builds new tools, optimizes prompts. Stronger with every task |
| 🧰 **Tool-Driven** | 64 built-in tools (files/code/search/screenshot/browser/package/Git), hot-pluggable at runtime |
| 🛡️ **Tool Self-Pruning** | Shrinks the exposed tool set using real usage data (idle tools auto-shielded), three invariants + escape hatches |
| ♻️ **Resilient Service** | Seamless self-restart (in-flight turn resumes from snapshot, no lost messages) + mid-generation steering |
| 🖥️ **Multi-Interface** | Web V2 / REST API / ACP / Telegram / WeChat front-ends, one engine |
| 🧠 **Real Memory** | Human-like long-term memory: tiered priority, semantic retrieval, natural decay, dedup & merge |
| 🤖 **Multi-Agent** | 6-stage full-stack collaboration: role agents + event flows + message bus + parallel execution + DAG orchestration |
| 📡 **Remote Sync** | `toolkit_remote_agent` connects edge devices (RK3588/BM1688), host ↔ device collaboration |

---

## ✨ Core Features

### 1. 🧠 Self-Evolution Engine (AI writing AI) — The Soul of This Project

The Agent **rewrites itself** at runtime, protected by five layers of safety:

```
toolkit_save          → Create/update tools at runtime, instantly effective, auto versioning
toolkit_self_evolve   → Five-layer safe source modification: Git → .bak → syntax → compile → LSP → tests
toolkit_prompt_evolve → Self-optimize system prompts based on reflections + memories
toolkit_experience_solidify → Success→skills, failure→lessons, auto-crystallized for reuse
```

> ⚠️ **Context-Aware**: self-evolution activates **only inside tea_agent's own project**; in external projects it's auto-disabled, focusing on your tasks without harmful changes.

### 2. 🧰 Tool-Driven — 64 Built-in Tools

| Category | Representative Tools |
|----------|---------------------|
| 📁 Files / Code | `toolkit_file`, `toolkit_edit`, `toolkit_diff`, `toolkit_code_review`, `toolkit_format_code` |
| 🔍 Search / Intelligence | `toolkit_search`, `toolkit_lsp`, `toolkit_explr`, `toolkit_query_chat_history` |
| 🖥️ Screen / Vision | `toolkit_screenshot`, `toolkit_input`, `toolkit_js_fetch`, `toolkit_browser_tab`, `toolkit_vision_analyze` |
| 🧠 Memory / Knowledge | `toolkit_memory`, `toolkit_kb`, `toolkit_proactive` |
| 🤖 Multi-Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_remote_agent` |
| 📋 Planning / Scheduling | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume` |
| 🔧 System / Engineering | `toolkit_exec` (incl. git), `toolkit_pkg`, `toolkit_build`, `toolkit_config`, `toolkit_server_restart`, `toolkit_approve` |

The tool engine (`tlk.py`) supports **dynamic load/unload/reload** — create a new tool mid-conversation, use it in the next turn.
Currently **55 tool modules / 64 registered tools**, of which 62 are exposed to the model (2 internal tools stay hidden).

#### Tool exposure self-pruning (v0.16.6+)

Sending every tool in every request burns tokens and dilutes attention. `tool_shield.py` shrinks the exposed set based on **real usage data**:

- **Stats**: one row per tool in the project DB `tool_usage` table (`uses / first_used / last_used / pin`).
  The recording point is `Toolkit.call_tool` and sits **before** the cache check — a cache hit is still a real call,
  and missing it would make frequently used tools look "never used" and eventually get shielded
- **Shielding**: long-idle tools are dropped when building the tool list. Independent from `tool_profiles`
  window tiers (tiers trim by context window, shielding trims by real usage); the shielded set is order-stable
  so DeepSeek prefix caching does not thrash
- **Three invariants** (shielding costs the Agent real capability, so "when never to shield" matters more than "when to"):
  ① **no data → no shielding** (an empty table only means "not yet observed"; otherwise a fresh install would shield everything on first boot);
  ② **no shielding of zero-use tools before the observation window is complete** ("just installed" ≠ "long unused");
  ③ **self-healing paths are never shielded** (`config/save/reload/exec/file/edit/diff/approve/tool_usage/rollback/list_versions`, 11 tools — shielding them removes the ladder used to unshield)
- **Escape hatches**: `TEA_TOOL_SHIELD=0` to disable; `TEA_TOOL_SHIELD_IDLE_DAYS=N` to tune the idle threshold;
  per-tool override via `toolkit_tool_usage(action='pin'|'unpin'|'auto'|'reset')`

### 3. 🧠 Human-like Long-Term Memory

SQLite-backed + semantic vectors, mimicking human memory:

- **Tiered priority**: `CRITICAL / HIGH / MEDIUM / LOW`, key instructions injected first
- **Semantic retrieval**: embedding cosine similarity, selects ≤30 most relevant from active pool
- **Natural decay**: Ebbinghaus forgetting curve, old memories demoted; `pinned` exempt
- **Dedup & merge**: Jaccard + embedding dual-channel, similar memories auto-merged
- **Cross-topic summary** (v0.13.3+): background analysis every 3 rounds, discovers cross-session patterns

### 4. 🤖 Multi-Agent System (v0.11+)

6-stage full-stack collaboration framework:

```
RoleAgent + FlowEngine + MessageBus
+ Agent-as-Tool + ExecutionPool
+ WorkflowDAG + PatternMarket + TraceEngine
```

Zero-code triggering: just say "analyze these files in parallel" — it auto-splits into subtasks and runs concurrently. Includes a built-in **dual-AI debate demo** with side-by-side real-time rounds.

### 5. 📡 Remote Device Agent (v0.13.10+)

Connect edge devices running `tea_agent.server` via `toolkit_remote_agent`:

```
register → exec (dispatch tasks, session_id controls context) → status (heartbeat) → unregister
```

For **embedded debugging** (RK3588/BM1688/X3), **edge node management**, **distributed collaboration**.

### 6. 🏎️ Token Economy — Four-Level History Compression

`L0 System → L3 Semantic Summary → L2 History Pairs → L1 Current Conversation` builds context in four tiers, maximizing information density within a limited token window — long conversations never blow the context.

### 7. 👁️ Vision Model Auto-Switch (v0.13.16+)

Main model doesn't support vision? Configure a `vision_model` and the Agent switches automatically:

- **Request-level switching**: detects images in the request messages (current or historical turns) → automatically uses the vision model
- **Turn-level fallback**: covers "image sent last turn, plain-text follow-up this turn" — the main model never receives unprocessable `image_url` content
- **`toolkit_vision_analyze`**: on-the-fly delegation — when the main model hits an image path / URL / data URL, it proactively calls the vision model to analyze and continue reasoning
- **Seamless restore**: switches back to the main model after the turn ends — zero config, zero friction

### 8. ♻️ Resilient Service — Seamless Restart + Mid-Generation Steering (v0.16.x)

**Seamless restart** (`toolkit_server_restart`) — after editing server code or config, the Agent can restart itself:

- `defer` (default): finishes the current turn first, then swaps in a new process; queued messages survive, users barely notice
- `immediate`: only for a wedged/unresponsive server (cuts the current turn)
- **In-flight turn snapshot resume**: a half-generated answer is recovered from an on-disk snapshot — nothing lost, nothing duplicated; `/health` reports liveness and queue state

**Mid-generation steering** — no need to wait for the turn to end:

- `POST /api/chat/steering` queues input (images included); the tool loop consumes it at **each round boundary**
  and injects a `[即时指令]` user message for the next model request, without interrupting running tool batches
- SSE `steering_injected` closes the loop: the front-end removes applied items from its local queue and renders
  them in the chat area, preventing duplicate sends after the stream ends

---

## 🚀 Quick Start in 30 Seconds

```bash
# 1. Install
pip install tea_agent

# 2. Launch (Web V2 full-featured interface)
tea-agent-api
# or python -m tea_agent.server

# 3. Open browser
# http://127.0.0.1:8282
```

A config dialog pops up on first launch — fill in your LLM API Key and start chatting.

---

## 💻 Interface Modes

| Interface | Launch | Use Case |
|-----------|--------|----------|
| **Web V2** (recommended) | `tea-agent-api` | SPA, full browser experience: chat + memory + scheduler + history |
| **REST API** | `python -m tea_agent.server --port 8081` | OpenAI-compatible, third-party integration |
| **ACP Protocol** | `tea-agent-acp` | VS Code / IDE integration (JSON-RPC 2.0) |
| **Telegram** | `tea-agent-telegram` | Remote chat from phone |
| **WeChat** | `tea-agent-wechat` | WeChat personal account (iLink Bot, QR login) |
| **Mini Edition** | `tea-agent-mini` | Embedded / Docker / low-end VPS |

---

## 🗺️ Deep-Dive Capability Map

> Want to dig into a topic? Expand the section below.

<details>
<summary><b>🧠 Long-Term Memory — How It Works</b></summary>

**Storage structure**: each memory has `content / priority(0-3) / importance(1-5) / category / tags / embedding / expires_at / pinned`.

**Selection algorithm** (≤30 memories injected per conversation):
```
score = keyword relevance × importance × time factor × priority factor
```
Tiered floor: CRITICAL first (max 10) → HIGH ≥3 → MEDIUM ≥2 → LOW ≥1 → remaining by score.

**Age decay** (Ebbinghaus): CRITICAL>30d→HIGH, HIGH>60d→MEDIUM, MEDIUM>90d→LOW.

**Extraction categories**: `instruction→CRITICAL`, `preference/reminder→HIGH`, `fact→MEDIUM`, `general→LOW`, LLM auto-extracts with 4-level fault-tolerant parsing.

**Dedup & merge**: Jaccard ≥0.6 merge (keep longer content, lower priority, higher importance); embedding cosine ≥0.92 batch dedup.

**CRITICAL FIFO**: 30-entry cap, oldest soft-deleted when exceeded.

</details>

<details>
<summary><b>📜 Four-Level History Compression — Token Efficiency</b></summary>

```
L0 System      system prompt + task resume + memory injection
L3 Summary     L2 overflow → LLM key conclusions (50→20 trim)
L2 History     SQLite ring buffer (50 entries), Jaccard relevance filter
L1 Current    128KB truncation + tool output placeholders + 5-stage progressive trim
```

```python
# L0 assembly order
result.append({"role": "system", "content": system_prompt})
if has_pending_tasks:
    result.append({"role": "user", "content": resume_info})
if memories:
    result.append({"role": "user", "content": memories})
```

L3 injection format (`[System Memory]` block) carries **long-term background/preferences/key conclusions** + **historical tool chain review**.

</details>

<details>
<summary><b>🔄 Self-Evolution Engine — Safety Mechanism</b></summary>

Five protection layers when modifying its own code, auto-rollback on any failure:

```
Layer 0  Git snapshot (clean working dir only; lands on refs/tea/snapshots, never pollutes branch history)
Layer 1  Timestamp .bak (history never overwritten)
Layer 1.5  Strict syntax check (newlines/indent/brackets/colons)
Layer 2  py_compile verification → rollback on failure
Layer 2.5  LSP checks (impact analysis + lint diff + signature comparison)
Layer 3  pytest verification → restore the target file from snapshot on failure (no more workspace-wide git reset --hard)
```

| Capability | Tool | Safety |
|------------|------|--------|
| Create new tools | `toolkit_save` + `toolkit_reload` | Version rollback |
| Modify source | `toolkit_self_evolve` | Five-layer safety |
| Optimize prompts | `toolkit_prompt_evolve` | Version rollback |
| Score evolution | `toolkit_evo_bench` / `toolkit_eval_loop` | keep-or-rollback decision |
| Crystallize experience | `toolkit_experience_solidify` | Category tags |
| Code intelligence | `toolkit_lsp` | Read-only |

**Evolution gate (EvolutionBench)**: `toolkit_self_evolve` used to gate only on "compiles + tests pass",
which cannot answer "is this version actually better?". Each applied change now runs a deterministic
benchmark (pure-code checks, no LLM), records the score on the evolution curve, and compares it with the
previous data point to suggest keep / rollback. With `evolution.gate=enforce` a non-improving change is
rolled back from `.bak` automatically (`off` = zero overhead, `advisory` = default, advise only).

</details>

<details>
<summary><b>🤖 Multi-Agent — Core Components</b></summary>

**Four collaboration modes**:

| Mode | Description |
|------|-------------|
| FlowEngine | Event-driven flows: `@flow_start` / `@flow_listen` / `@flow_route`, Mermaid visualization |
| Agent-as-Tool | Wrap a sub-agent as `toolkit_xxx`, call it right in conversation |
| MessageBus | Pub/Sub + point-to-point, agents communicate freely |
| ExecutionPool | Thread-pool parallelism, batch + timeout + status query |

**WorkflowDAG nodes**: `TASK / CONDITION / LOOP / PARALLEL / WAIT / END` — statically orchestrate complex flows.

**Built-in pattern market (4 presets)**: Code Review Expert / Senior Engineer / Test Engineer / Analysis Expert, one-click instantiation.

✅ **Pros**: parallel speed, high focus, composable, observable, zero-code triggering
⚠️ **Limits**: token cost (subtasks × per-task), coordination overhead, context isolation, concurrent file edits need serialization

</details>

<details>
<summary><b>📡 Remote Device Agent — Usage Example</b></summary>

```python
# ① Register device
toolkit_remote_agent(action="register", device_id="bm1688-1",
    host="172.16.1.49", port=8282, working_path="/app/zkfs/")

# ② Dispatch task (no session_id → auto-creates remote topic)
r = toolkit_remote_agent(action="exec", device_id="terminal-49",
    goal="Analyze today's logs in /record/dbs/log/")

# ③ Same session_id → continue the same remote context
r2 = toolkit_remote_agent(action="exec", device_id="terminal-49",
    goal="Continue troubleshooting network issue", session_id=r["session_id"])

# ④ Done → disconnect
toolkit_remote_agent(action="unregister", device_id="terminal-49")
```

</details>

---

## 📦 Mini Edition (tea_agent_mini)

A slimmed-down build for **embedded devices / resource-constrained environments / Web-only** scenarios — only **7 core packages** (~5 MB vs Full's ~80 MB), preserving Agent core, Web V2, REST API, memory, and Multi-Agent capabilities.

```bash
pip install tea_agent_mini        # standalone package
python build_mini.py              # or build from source
python build_nuitka.py            # or compile to single-file executable (no Python needed)
```

| Removed | Note |
|---------|------|
| ACP / Telegram | Protocol & channel layers |
| NumPy vectors | replaced with pure Python `math+struct` |
| Playwright / PyAutoGUI / MSS | optional manual install |
| 11 heavy tools | JS rendering, screenshot, input simulation, browser tabs, clipboard, LSP, code explorer, package manager etc. on demand (the OCR tool was removed — image understanding now goes through `toolkit_vision_analyze` and the vision model) |

---

## 🔧 Configuration

Config file `~/.tea_agent/config.yaml`:

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  max_context_tokens: 0    # 0=unlimited, >0 enables progressive token trimming
cheap_model:               # separate config for summarization/memory cheap tasks
  max_context_tokens: 0
embedding:
  provider: openai
  model: text-embedding-3-small
vision_model:             # vision model (optional): auto-switch when images present
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o-mini"    # e.g. also supports mimo-v2.5 and other vision models
```

- **Context window control**: when `max_context_tokens` is exceeded, 5-stage progressive trim (drop old history → tool output placeholders → clear thinking → truncate long text → drop old turns)
- **Vision model auto-switch**: with `vision_model` configured, the session automatically uses the vision model when the input contains images (restores the main model after the turn); `toolkit_vision_analyze` also lets the main model delegate image analysis on the fly
- **Evolution gate**: `evolution.gate = off | advisory | enforce` (env `TEA_EVOLVE_GATE`, threshold `TEA_EVOLVE_GATE_THRESHOLD`, default 0.0 = must strictly improve to be kept); under `enforce`, a self-modification that does not raise the EvolutionBench score is rolled back from `.bak` — upgrading "tests pass" to "provably better"
- **Tool exposure self-pruning**: `TEA_TOOL_SHIELD=0` disables auto-shielding of long-idle tools; `TEA_TOOL_SHIELD_IDLE_DAYS=N` tunes the idle threshold (default 30 days, never before the observation window completes)
- **Runtime tuning**: Agent can self-tune parameters via `toolkit_config`
- **Ruff lint**: built-in `pyproject.toml` Ruff config (E/F/W/I/N/UP/B/C4/SIM), Python 3.10 type annotations

---

## 🧪 Testing

```bash
pytest                    # all unit tests (1800+ cases)
python tests/test_server_api.py --port 8282   # Server API black-box tests (8 suites, 30+ points)
```

Coverage: sessions, tools, storage, multi-agent, LSP, ACP protocol, Server routes, memory system.

---

## 🏗️ Project Structure

```
tea_agent/
├── agent.py           # Agent unified entry
├── onlinesession.py   # Online session (tool loop + streaming)
├── litesession.py     # Lightweight session
├── tlk.py             # Tool load/register/execute engine (64 tools)
├── memory.py          # Long-term memory system
├── config.py          # Configuration management
├── providers.py       # 26 LLM provider bootstrap catalog (model attrs live in provider.yaml)
├── tool_shield.py     # Auto-shield long-idle tools (three invariants + escape hatches)
├── evolution_gate.py  # Evolution gate: EvolutionBench score → keep-or-rollback
├── skill_loader.py    # On-demand skill loading (necessity/sufficiency scoring)
├── context_fragments.py # Context fragments assembled on demand (time/budget/mode/memory)
├── server/            # REST API + Web V2 (Starlette + SSE)
├── protocol/          # ACP protocol
├── channel/           # Telegram / WeChat adapters
├── toolkit/           # 55 tool modules
├── session/           # History compression / L1/L2/L3 / JSON validation
├── store/             # Data storage (13 feature sub-modules + migration: sessions/memory/vectors/tool usage/interruptions…)
├── multi_agent/       # Multi-agent system
├── evaluation/        # EvolutionBench deterministic benchmarks
├── lsp/               # Code intelligence (Jedi + Ruff)
├── skills/            # Skill crystallization
├── tests/             # 1800+ test cases (95 test files)
└── demo/              # Demos (debate / piano / DAG)
```

---

## 🔐 Security Boundaries

- **Privilege escalation is always refused**: `sudo` / `su` / `pkexec` / `runas` are hard-blocked on both execution paths (`toolkit_exec` and `toolkit_scheduler`) — operations needing admin rights must be run by the user manually
- **Approval gate**: with `TEA_APPROVAL_MODE=enforce`, high-risk tools (`toolkit_exec` / `toolkit_self_evolve` …) require `toolkit_approve` authorization, granted per project
- **Path fence**: file tools default to project scope, `../` escapes rejected; cross-directory work needs an explicit absolute path or `TEA_FILE_ALLOW_OUTSIDE=1`
- **SQL safety**: all database access is parameterized, guarded by a self-check test that forbids f-string SQL interpolation
- **Snapshot isolation**: self-evolution git snapshots land on a dedicated ref (`refs/tea/snapshots`, override with `TEA_SNAPSHOT_REF`) instead of polluting branch history; `TEA_GIT_SNAPSHOT_MODE=off|side|branch`
- **Evolution gate**: `TEA_EVOLVE_GATE=off|advisory|enforce` decides whether the EvolutionBench score can block a self-modification (under `enforce` a non-improving change is rolled back)
- **Self-evolution boundary**: background evolution may optimize tools / skills / prompts, but must **never touch user conversation history**

---

## 📄 License

MIT License © 2024-2026 sunkw

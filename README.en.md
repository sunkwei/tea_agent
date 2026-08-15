# Tea Agent v0.15.0

> ⚠️ **Experimental project — AI writing AI. Use at your own risk.**

> 🌐 **[中文版](README.md)**

> **A self-evolving AI coding assistant** — not just completing coding tasks, but modifying its own code, creating new tools, and optimizing its own prompts. It gets stronger with every task.

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.15.0-blue)](https://pypi.org/project/tea-agent)

---

## 🎯 Tea Agent in One Glance

| | |
|---|---|
| 🧠 **Self-Evolving** | AI writing AI — modifies its own code, builds new tools, optimizes prompts. Stronger with every task |
| 🧰 **Tool-Driven** | 75+ built-in tools (files/code/search/screenshot/browser/package/Git), hot-pluggable at runtime |
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

### 2. 🧰 Tool-Driven — 75+ Built-in Tools

| Category | Representative Tools |
|----------|---------------------|
| 📁 Files / Code | `toolkit_file`, `toolkit_edit`, `toolkit_diff`, `toolkit_code_review`, `toolkit_format_code` |
| 🔍 Search / Intelligence | `toolkit_search`, `toolkit_lsp`, `toolkit_explr`, `toolkit_query_chat_history` |
| 🖥️ Screen / Browser | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_input`, `toolkit_js_fetch`, `toolkit_browser_tab` |
| 🧠 Memory / Reflection | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 Multi-Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_remote_agent` |
| 📋 Planning / Scheduling | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume` |
| 🔧 System / Engineering | `toolkit_exec`, `toolkit_pkg`, `toolkit_build`, `toolkit_git_commit`, `toolkit_config` |

The tool engine (`tlk.py`) supports **dynamic load/unload/reload** — create a new tool mid-conversation, use it in the next turn.

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
Layer 0  Git snapshot (clean working dir only)
Layer 1  Timestamp .bak (never overwrites)
Layer 1.5  Strict syntax check (newlines/indent/brackets/colons)
Layer 2  py_compile verification → rollback on failure
Layer 2.5  LSP checks (impact analysis + lint diff + signature comparison)
Layer 3  pytest verification → git reset --hard on failure
```

| Capability | Tool | Safety |
|------------|------|--------|
| Create new tools | `toolkit_save` + `toolkit_reload` | Version rollback |
| Modify source | `toolkit_self_evolve` | Five-layer safety |
| Optimize prompts | `toolkit_prompt_evolve` | Version rollback |
| Crystallize experience | `toolkit_experience_solidify` | Category tags |
| Code intelligence | `toolkit_lsp` | Read-only |

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
| GUI / ACP / Telegram | Desktop & protocol layers |
| NumPy vectors | replaced with pure Python `math+struct` |
| Playwright / PyAutoGUI / MSS | optional manual install |
| 12 heavy tools | JS rendering, screenshot, OCR, LSP etc. on demand |

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
- **Runtime tuning**: Agent can self-tune parameters via `toolkit_config`
- **Ruff lint**: built-in `pyproject.toml` Ruff config (E/F/W/I/N/UP/B/C4/SIM), Python 3.10 type annotations

---

## 🧪 Testing

```bash
pytest                    # all unit tests (870+ cases)
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
├── tlk.py             # Tool load/register/execute engine (75+ tools)
├── memory.py          # Long-term memory system
├── config.py          # Configuration management
├── providers.py       # 50+ LLM provider adapters
├── server/            # REST API + Web V2 (Starlette + SSE)
├── protocol/          # ACP protocol
├── channel/           # Telegram / WeChat adapters
├── toolkit/           # 75+ tool modules
├── session/           # History compression / L1/L2/L3 / JSON validation
├── store/             # Data storage (10 sub-modules)
├── multi_agent/       # Multi-agent system
├── lsp/               # Code intelligence (Jedi + Tree-sitter)
├── skills/            # Skill crystallization
├── tests/             # 870+ test cases
└── demo/              # Demos (debate / piano / DAG)
```

---

## 📄 License

MIT License © 2024-2026 sunkw

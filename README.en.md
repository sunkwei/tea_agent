# Tea Agent v0.13.5

> ⚠️ **Experimental project — AI writing AI. Use at your own risk.**

> 🌐 **[中文版](README.md)**



> A self-evolving AI coding assistant — tool-driven, self-improving, multi-interface.

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.13.5-blue)](https://pypi.org/project/tea-agent)

Tea Agent is a **self-evolving AI coding assistant** with 75+ built-in tools. It can autonomously write code, debug, search, manipulate files, control browsers, and dynamically load new tools at runtime. Supports **GUI / Web / REST API / ACP Protocol / Telegram / WeChat** six interface modes.

---

## ✨ Core Features

- 🧠 **Self-Evolution Engine** — Modify its own code, create new tools, optimize prompts — full autonomous evolution
- 🧭 **Context-Aware** — Auto-detects project identity: full evolution in its own project, disabled in external projects
- 🧰 **75+ Built-in Tools** — File ops, code editing, search, screenshot, OCR, package management, Git, etc.
- ⏱️ **Smart Command Timeout** — Background CPU/MEM/IO monitoring; active processes auto-extend to 4x, idle ones terminate promptly
- 🖥️ **Multiple Interfaces** — GUI (Tkinter), Web (Starlette + SSE), REST API, ACP Protocol, pick your flavor
- 🌐 **Web V2 Real-time Streaming** — SPA (Single Page App) with memory search, task scheduler, full history
- 📚 **Project Knowledge Base** — Auto-build symbol index + call graph + impact analysis
- 🔄 **Session Persistence** — Chat history survives restart
- 📋 **Plan / TODO** — Built-in task planning and tracking
- 🌐 **MCP Protocol** — Connect external MCP Servers for third-party tools
- 🎯 **Mode Switching** — design / develop / test / review / docs / devops workflow
- 🤖 **Multi-Agent System** — 6-stage full-stack collaboration
- 📡 **Message Channels** — Telegram Bot + WeChat iLink Bot dual adapters
- 📊 **Task Evaluation** — Auto-assess quality, record successes/failures
- 💎 **Skill Crystallization** — Plan results auto-crystallize → semantic injection into new conversations
- 🛡️ **LLM JSON Fault Tolerance** — Smart repair of truncated JSON, control chars, single quotes, trailing commas
- 🔄 **Toolkit Hot-Reload** — Dynamic load/unload/reload without restart
- 🏗️ **Server Hot-Reload** — Agent/Toolkit/Storage/Pipeline modules hot-swappable
- 🧪 **41+ Test Files** — 600+ test cases covering core modules
- 📦 **Mini Edition** — `tea_agent_mini` with only 7 core packages (~5 MB)

---

## 📦 Installation

```bash
# From PyPI
pip install tea_agent

# Or from source
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
pip install -e .

# Web interface dependencies (optional)
pip install starlette uvicorn python-multipart
```

Playwright (optional, for JS-rendered page scraping):
```bash
playwright install chromium
```

---

## 📦 Mini Edition (tea_agent_mini)

For **embedded devices, resource-constrained environments, or Web-only** scenarios, Tea Agent offers the **Mini Edition** — dramatically reduced size and dependencies while preserving core functionality.

### ✨ Feature Comparison

| Capability | Full | Mini |
|------------|------|------|
| Agent Core Engine | ✅ | ✅ Full |
| Web V2 (SPA) | ✅ | ✅ Full |
| REST API Server | ✅ | ✅ Full |
| Memory Search / Memory Mgmt | ✅ | ✅ Full |
| Task Evaluation / Skill Crystallization | ✅ | ✅ Full |
| Task Scheduler / PDF Export | ✅ | ✅ Full |
| Config Switching | ✅ | ✅ Full |
| GUI Desktop | ✅ | ❌ |
| ACP Protocol | ✅ | ❌ |
| File Upload (Drag & Drop) | ✅ | ✅ with `python-multipart` |
| NumPy Vector Ops | ✅ | ❌ replaced with pure Python `math+struct` |
| Playwright (JS Rendering) | ✅ | ❌ optional manual install |
| PyAutoGUI / MSS (Screenshot) | ✅ | ❌ optional manual install |
| TkinterWeb (Rich Text) | ✅ | ❌ |

### 📐 Build Process

`build_mini.py` intelligently filters source from `tea_agent/`:

```
build_mini.py Workflow
  │
  ├─ 1. Copy core modules:
  │     ├─ Top-level .py: agent.py, config.py, memory.py, etc. (20 files)
  │     ├─ session/  — History management
  │     ├─ store/    — Data storage (10 sub-modules)
  │     ├─ toolkit/  — Excluding 12 heavy tools
  │     ├─ server/   — Web server (routes + static)
  │     ├─ multi_agent/ — Multi-agent collaboration
  │     ├─ evaluation/  — Task evaluation
  │     └─ skills/   — Skill crystallization
  │
  ├─ 2. Excluded packages:
  │     ├─ _gui/     — Tkinter GUI
  │     ├─ gui.py / gui_dialogs.py
  │     ├─ channel/  — Telegram/WeChat adapters
  │     ├─ protocol/ — ACP protocol
  │     ├─ lsp/      — Code intelligence
  │     ├─ workflow/ — Workflow engine
  │     └─ demo/ / tests/ / scripts/
  │
  ├─ 3. Excluded heavy tools (HEAVY_TOOLS):
  │     toolkit_js_fetch, toolkit_input, toolkit_screenshot,
  │     toolkit_screen_read, toolkit_ocr, toolkit_lsp,
  │     toolkit_browser_tab, toolkit_clipboard, toolkit_sudo_gui,
  │     toolkit_test_gui, toolkit_explr, toolkit_pkg
  │
  ├─ 4. Remove NumPy dependency:
  │     store/_vectors.py, _memories.py, _semantic_search.py,
  │     _conversations.py — numpy → math+struct
  │
  └─ 5. Generate standalone wheel:
        ├─ pyproject.toml (mini-only dependencies)
        ├─ README.mini.md
        └─ package → tea_agent_mini-{version}-py3-none-any.whl
```

### 📦 Installation

```bash
# Method 1: From PyPI (mini package already published)
pip install tea_agent_mini

# Method 2: Build from source
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
python build_mini.py

# Build output in build_mini_dist/dist/
pip install build_mini_dist/dist/tea_agent_mini-*.whl
```

### 🔨 Compile to Single-File Executable

`build_nuitka.py` compiles the Mini Edition further into a **single-file executable** (`.exe` / ELF), no Python required.

```bash
# Single file mode (for distribution to users without Python)
python build_nuitka.py

# Standalone directory mode (debugging, faster compile)
python build_nuitka.py --standalone

# Output: build_nuitka_dist/tea-agent-mini[.exe] (~60 MB)
```

> ⚠️ Compilation takes 5-30 minutes and requires Nuitka + C compiler.
> For daily use, `pip install` is recommended.

### 🚀 Usage

Mini Edition works identically to Full Edition for Web interface:

```bash
# Start Web V2 interface (recommended)
python -m tea_agent.server

# Or via CLI
tea-agent-mini
```

Open `http://127.0.0.1:8282` in browser for the full Web interface.

### 🧩 Mini Edition Dependencies

Mini Edition depends on only **7 core packages** (~5 MB total vs Full's ~80 MB):

```
openai>=1.0.0           # LLM API
httpx>=0.25.0           # HTTP client
PyYAML>=6.0             # Config files
requests>=2.30.0        # HTTP requests
starlette>=0.37.0       # Web framework
uvicorn>=0.27.0         # ASGI server
python-multipart>=0.0.7 # File upload parsing
```

> 💡 Mini excludes NumPy (~15 MB), Playwright (~30 MB), PyAutoGUI (~3 MB) — perfect for **Docker images, Raspberry Pi, low-end VPS, CI/CD pipelines**.

### 📊 Size Comparison

| Dimension | Full | Mini |
|-----------|------|------|
| Package size | ~600 KB | ~250 KB |
| Extracted size | ~3 MB | ~1.2 MB |
| Runtime deps | ~80 MB | ~5 MB |
| Python files | ~420 | ~280 |
| Tools count | 75+ | 63 |

---

## 🚀 Quick Start

```bash
# REST API + Web V2 — SPA, full-featured browser experience (recommended)
tea-agent-api
python -m tea_agent.server          # equivalent

# GUI Desktop (Tkinter)
tea-agent-gui
python -m tea_agent.gui             # equivalent

# ACP Protocol Server (VS Code integration)
tea-agent-acp
python -m tea_agent.protocol --port 9090

# Telegram Bot
tea-agent-telegram

# WeChat Bot
tea-agent-wechat

# Mini Edition Web
tea-agent-mini
```

---

## 💻 Interface Modes

Tea Agent offers **six interface modes**, covering everything from desktop to web, CLI to API.

---

### 1. GUI Desktop (`tea-agent-gui`)

Native desktop client based on **Tkinter**, supporting Windows / Linux / macOS.

**Start:**
```bash
tea-agent-gui                     # CLI entry
python -m tea_agent.gui           # module mode
```

**Features:**
- 🔄 Real-time streaming chat with Markdown rendering
- 📋 Session list panel (search/switch/create/delete)
- 🧠 Long-term memory management panel
- ⏱️ Task scheduler (CRUD)
- 📤 PDF export, chat history export
- 🌙 System tray, global hotkey
- 🎨 Theme switching + font scaling

---

### 2. Web V2 (`python -m tea_agent.server`)

Next-gen SPA with pure HTML/JS frontend + Starlette API backend.

**Start:**
```bash
tea-agent-api                        # CLI entry
python -m tea_agent.server           # module mode, default port 8282
python -m tea_agent.server --port 8099 --host 0.0.0.0
```

**Features:**

| Feature | Description |
|---------|-------------|
| 💬 **Streaming Chat** | SSE real-time, token-by-token output |
| 📋 **Multi-session** | Session panel, click to switch, auto-load history |
| 🧠 **Memory Management** | Modal panel, view/search/add/delete memories |
| ⏱️ **Task Scheduler** | CRUD with cron / interval / daily |
| 🔍 **Global Search** | Search chats, memories, tasks |
| 📤 **PDF Export** | Export current session to PDF |
| 🌙 **Theme Switching** | Dark/Light + accent color customization |
| ⚡ **Config Switching** | One-click switch between `~/.tea_agent/*.yaml` configs |
| 📎 **Image Preview** | Click-to-enlarge in chat |
| 🚦 **Message Queue** | Queue messages when current topic is responding |

**Architecture:**
```
Frontend: Pure HTML5 + CSS3 + Vanilla JS (no framework)
Backend:  Starlette + SSE streaming
API:      /v1/chat/completions (OpenAI-compatible)
          /v1/sessions (CRUD)
          /v1/memory (memory management)
          /v1/tasks (task scheduler)
          /v1/search (global search)
          /v1/export/pdf (PDF export)
```

**Concurrent Streaming Architecture:**

```
Request A → create_session() → OnlineToolSession A 🔓 (config X)
Request B → create_session() → OnlineToolSession B 🔓 (config Y)
Request C → create_session() → OnlineToolSession C 🔓 (config Z)

Shared resources: Toolkit (read-only) + Storage (thread-safe)
Streaming: independent sessions, no global lock
```

**Message Queue** — When a topic is responding, messages sent to other topics are queued and auto-sent once the current response completes.

---

### 3. REST API Server (`python -m tea_agent.server`)

OpenAI-compatible HTTP API for third-party integration.

**Start:**
```bash
tea-agent-api                        # CLI entry
python -m tea_agent.server           # module mode
python -m tea_agent.server --port 8081 --host 0.0.0.0
```

**API Routes:**

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (stream + config_path) |
| `GET` | `/v1/models` | Model info |
| `GET` | `/v1/tools` | All available tools |
| `POST` | `/v1/tools/{name}/run` | Direct tool invocation |
| `GET/POST` | `/v1/sessions` | List/create sessions |
| `GET/DELETE` | `/v1/sessions/{id}` | Get/delete session |
| `GET` | `/v1/sessions/{id}/messages` | Get session messages |
| `GET` | `/v1/config` | Get config |
| `POST` | `/v1/config/switch` | Switch config file |
| `GET/POST/DELETE` | `/v1/memory` | Memory management |
| `GET/POST/DELETE` | `/v1/tasks` | Task management |
| `GET` | `/v1/search` | Global search |
| `POST` | `/v1/export/pdf` | PDF export |
| `GET` | `/docs` | OpenAPI docs |
| `GET` | `/openapi.json` | OpenAPI Schema |

**Examples:**
```bash
# Streaming chat
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true}'

# Non-streaming
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'

# List sessions
curl http://127.0.0.1:8080/v1/sessions
```

---

### 4. ACP Protocol Server (`python -m tea_agent.protocol`)

Agent Communication Protocol — standardized Agent-to-Agent communication for IDE integration.

**Start:**
```bash
python -m tea_agent.protocol --port 9090
```

**Features:**
- 🧰 **Tool Discovery** — Clients query full tool list + JSON Schema
- 📡 **SSE Streaming** — Real-time token-by-token output
- 🧵 **Session Management** — Isolated sessions with history
- 🔗 **IDE Integration** — Standard ACP protocol

---

### 5. Telegram Bot (`tea-agent-telegram`)

Telegram messaging adapter based on `python-telegram-bot`.

**Start:**
```bash
tea-agent-telegram
python -m tea_agent.channel.telegram_adapter
```

**Features:**
- 💬 Chat with Agent via Telegram
- 🔄 Long message chunking for extended conversations
- 🔌 Runs alongside other interfaces without interference

### 6. WeChat Bot (`tea-agent-wechat`) 🆕

WeChat messaging adapter based on Tencent's official iLink Bot API.

**Start:**
```bash
tea-agent-wechat                    # Auto-shows QR code on first run
python -m tea_agent.channel.wechat_adapter
```

**Features:**
- 💬 Chat with Agent via WeChat (outbound-only, no public IP/port needed)
- 🔐 QR-code login, credentials persisted across restarts
- ⌨️ "Typing..." status indicator
- 👥 Isolated sessions per WeChat user
- 🛠️ Built-in commands (`/start`, `/new`, `/topic`, `/about`)

📖 **Case Study**: 👉 [From Zero to One: Building a WeChat Bot with tea_agent](docs/tea_agent_微信接入实战.md) — Full walkthrough of autonomous search → architecture analysis → adapter coding → deployment.

---

## 🧠 Long-Term Memory System

Tea Agent's memory system mimics human memory: **priority-tiered**, **relevance-retrieved**, **age-decayed**, **deduplicated**. Backed by SQLite + embedding vectors, managed by `MemoryManager`.

### 1. Memory Storage Structure

| Field | Type | Description |
|-------|------|-------------|
| `content` | TEXT | Memory content (concise summary) |
| `priority` | INT (0-3) | `0=CRITICAL` / `1=HIGH` / `2=MEDIUM` / `3=LOW` |
| `importance` | INT (1-5) | 5=critical, ignoring causes major issues; 1=trivial |
| `category` | TEXT | `instruction` / `preference` / `fact` / `reminder` / `general` |
| `tags` | TEXT | Comma-separated tags for fast matching |
| `content_hash` | TEXT | SHA256 first 16 chars, fast dedup fingerprint |
| `embedding` | BLOB | `numpy.float32` vector for semantic search |
| `expires_at` | DATETIME | Expiration date (NULL = never expires) |
| `pinned` | INT | Pinned flag (exempt from age decay) |

### 2. Selection Algorithm

At each conversation start, `MemoryManager.select_memories()` selects the most relevant **≤30 entries**:

```
score = relevance(keyword match) × importance(÷5) × age_factor × priority_factor

age_factor: 1 day=1.0, 7 days=0.9, 30 days=0.7, 90 days=0.5, >90 days=0.3
priority_factor: (4 - priority) / 4
```

**Tiered floor strategy:**
```
1. CRITICAL first (max 10, FIFO)
2. Non-CRITICAL sorted by score
3. Tiered floor quotas:
   - HIGH   ≥ 3
   - MEDIUM ≥ 2
   - LOW    ≥ 1
4. Remaining slots: free competition (highest score wins)
```

### 3. Age Decay

Ebbinghaus forgetting curve simulation. `degrade_by_age()` runs before each selection:

| Original Priority | Decay Condition | Demoted To |
|------------------|----------------|------------|
| CRITICAL | Created > 30 days | HIGH |
| HIGH | Created > 60 days | MEDIUM |
| MEDIUM | Created > 90 days | LOW |

### 4. LLM Priority Tuning

`llm_adjust_priorities()` uses cheap LLM to fine-tune memory priorities based on recent conversation topics.

### 5. Memory Extraction

After each conversation, MemoryManager auto-extracts memories from user messages via LLM:
- `instruction` → `priority=0 (CRITICAL)`
- `preference` → `priority=1 (HIGH)`
- `reminder` → `priority=1 (HIGH)` (with `expires_at`)
- `fact` → `priority=2 (MEDIUM)`
- `general` → `priority=3 (LOW)`

### 6. Dedup & Merge

`ingest_extracted()` runs dedup pipeline:
- Jaccard similarity ≥ 0.6 → merge (keep longer content, lower priority, higher importance)
- < 0.6 → new record

### 7. CRITICAL FIFO Eviction

Max 30 CRITICAL entries — oldest soft-deleted when exceeded.

### 8. Reflection & Summarization

`reflect_and_summarize()` clusters recent memories by category, generates summary as CRITICAL/importance=5, downgrades originals.

### 9. Cross-topic Aggregation

Every 3 conversations, background thread analyzes cross-topic patterns → insight memories.

---

## 📜 Four-Level History Compression (L0 → L3 → L2 → L1)

Tea Agent uses **four layers** to build context for LLM, maximizing information density within token limits.

```
Level 0: System Layer
│  ├─ System prompt
│  ├─ Skill recommendations (semantic matching)
│  ├─ Task resume (TODO/Plan)
│  └─ Memory injection (MemoryManager selection)
Level 3: Summary Layer (LLM-generated)
│  └─ L2 overflow → key conclusions, discard details
Level 2: History Pairs (SQLite persisted)
│  └─ user + AI final msg, relevance-filtered
Level 1: Current Conversation
│  └─ Tool chain compression, placeholder substitution
```

### Level 0: System Layer

```python
result = []
result.append({"role": "system", "content": system_prompt})
if has_pending_tasks:
    result.append({"role": "user", "content": resume_info})
if memories:
    result.append({"role": "user", "content": memories})
```

### Level 3 (L3) — Semantic Summary

`SummaryStore` manages two summary types:
- **Semantic summary** — Generated when L2 overflows (50→20 trim)
- **Tool chain summary** — Async background thread

**L3 injection format:**
```
[System Memory — Rules to Follow]

##### Long-term Background/Preferences/Key Conclusions
{semantic_summary}

---

##### Historical Tool Chain Review
{tool_chain_summary}
```

### Level 2 (L2) — History Pairs

Fixed-size ring buffer (50 entries) stored in SQLite `topics.level2_json`.

**Entry structure:**
```json
{
  "user": "original message",
  "assistant": "final reply",
  "thinking": "tool call intermediate steps",
  "files": ["related file paths"]
}
```

**Relevance filter** — Jaccard similarity with current user message:
- ≥ 0.15 → full pair injected as `[History]`
- ≥ 0.05 → summary snippet only
- < 0.05 → skipped (with floor guarantee)

### Level 1 (L1) — Current Conversation

Raw messages from current session, multi-layer compression:

1. **Real-time tool output truncation** — 128KB cap
2. **Old tool output → placeholder** — Tools older than 3 rounds → `[Tool result omitted: N chars]`
3. **Progressive token trimming** — 5-stage cascade when exceeding budget

---

## 🔄 Self-Evolution Engine

Four-layer evolution system: tool hot-plug → safe self-modification → prompt evolution → experience crystallization.

### 0. Context-Aware Rules (Pre-constraint)

> **Core design principle: Self-evolution activates only within tea_agent's own project.**

```
Before each task, detect project identity:
1. If tea_agent project (tea_agent/agent.py exists)
   → Full evolution: create tools, modify source, optimize prompts
2. If external project
   → Evolution disabled: focus on external tasks only
```

### 1. Tool Hot-Plug: `toolkit_save` / `toolkit_reload`

Create/modify tools at runtime, **immediately effective** without restart.

```
Agent identifies new capability needed
  → 1. Write Python function code
  → 2. Define OpenAI function schema
  → 3. toolkit_save(name, meta, pycode)
  → 4. toolkit_reload()
  → 5. New tool available immediately
```

**Version management:**
- Auto-increment: `v1.0.0 → v1.0.1 → v1.1.0`
- Safe rollback: `toolkit_rollback(name, version)`
- Auto-generated SKILL.md documentation

### 2. Five-Layer Safe Self-Modification: `toolkit_self_evolve`

```
Layer 0: Git snapshot (clean working dir only)
Layer 1: Timestamp .bak file (never overwrites)
Layer 1.5: Python syntax strict check
Layer 2: py_compile verification (auto-rollback on failure)
Layer 2.5: LSP checks (impact analysis + lint diff + signature comparison)
Layer 3: pytest verification (git reset --hard on failure)
```

### 3. Prompt Evolution: `toolkit_prompt_evolve`

Agent self-optimizes system prompts via `SystemPromptManager`:
- `evolve` — Generate new version based on reflections + memories
- `rollback` — Revert to any historical version
- `list` — View version history

### 4. Experience Crystallization: `toolkit_experience_solidify`

Post-task autopsies turn into reusable patterns:
- Success → solidify to skill library
- Failure → lesson to knowledge base

---

## 🧰 Tool Overview (75+)

| Category | Tools |
|----------|-------|
| 📁 File Ops | `toolkit_file`, `toolkit_save_file`, `toolkit_explr`, `toolkit_batch_process` |
| ✏️ Code Edit | `toolkit_edit`, `toolkit_diff_edit`, `toolkit_diff`, `toolkit_self_evolve`, `toolkit_clean_comments`, `toolkit_format_code`, `toolkit_code_review`, `toolkit_comment` |
| 🔍 Search | `toolkit_search`, `toolkit_lsp`, `toolkit_query_chat_history` |
| 📸 Screenshot/OCR | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_screen_read`, `toolkit_screenshot_picker` |
| 🖱️ Control | `toolkit_input`, `toolkit_browser_tab`, `toolkit_js_fetch` |
| 📦 Package | `toolkit_pkg`, `toolkit_build`, `toolkit_read_pyproject` |
| 🧪 Testing | `toolkit_run_tests`, `toolkit_test_gui` |
| 🗓️ Utilities | `toolkit_lunar`, `toolkit_weather_my`, `toolkit_gettime`, `toolkit_date_diff` |
| 🔧 System | `toolkit_exec`, `toolkit_config`, `toolkit_os_info`, `toolkit_sudo_gui`, `toolkit_clipboard` |
| 🧠 Memory | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 Multi-Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_auto_pipeline`, `toolkit_dynamic_skill` |
| 📋 Plan/Task | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume`, `toolkit_topic_prompt` |
| 🔌 MCP | `toolkit_mcp` |
| 🌐 Web/GUI | `toolkit_dump_topic`, `toolkit_export_last_pdf`, `toolkit_notify` |
| 📤 Export | `toolkit_dump_topic`, `toolkit_export_last_pdf` |
| 🧬 Evolution | `toolkit_self_evolve`, `toolkit_prompt_evolve`, `toolkit_evolution_exp`, `toolkit_experience_solidify` |
| 🛠️ Others | `toolkit_question`, `toolkit_stream_save`, `toolkit_set_topic_title`, `toolkit_self_report`, `toolkit_toggle_reasoning`, `toolkit_get_config_path`, `toolkit_get_models`, `toolkit_list_provider_models`, `toolkit_ip_location_my`, `toolkit_custom_commands`, `toolkit_scheduler_storage`, `toolkit_mode`, `toolkit_skills`, `toolkit_release_version`, `toolkit_harness_schema`, `toolkit_git_push_all_remotes` |

> Full tool list: [`docs/TOOLS.md`](docs/TOOLS.md)

---

## 🤖 Multi-Agent System (v0.11+)

A full-stack collaboration framework covering 6 development phases:

```
Phase 1: Core            RoleAgent + FlowEngine + RoleDispatcher
Phase 2: Communication   MessageBus + Agent-as-Tool + ToolRegistry
Phase 3: Observability   CheckpointManager + TraceEngine
Phase 4: Marketplace     PatternMarket + AdminPanel
Phase 5: Parallel Engine ExecutionPool + LoadBalancer + CircuitBreaker
Phase 6: Advanced DAG    WorkflowDAG (condition/loop/parallel/wait)
```

### 🚀 Quick Start

#### Method 1: In-Dialogue (Zero Code)

No Python needed — just tell the Agent:

| Tool | Purpose |
|------|---------|
| `toolkit_parallel_subtasks` | Decompose → parallel execute → auto-summarize |
| `toolkit_subagent` | Spawn independent sub-agents (sync/async) |
| `toolkit_subagent_msg` | Point-to-point messaging between sub-agents |

#### Method 2: Python API

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()
result = dispatcher.dispatch("Refactor project with type annotations")
print(result["summary"])
# → ✅ Complete: Refactor project with type annotations (4 steps, 12.3s)
```

```python
from tea_agent.multi_agent import RoleAgent

analyst = RoleAgent(
    role="Senior Code Reviewer",
    goal="Review code quality and identify design issues",
    backstory="15 years of software architecture experience...",
)
result = analyst.execute("Review dispatcher.py design")
```

#### Method 3: FlowEngine (Event-Driven)

```python
from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

class ReviewFlow(FlowEngine):
    @flow_start()
    def scan(self):
        return self.call_agent("reviewer", "Full code review")

    @flow_listen(scan)
    def report(self):
        issues = self.state.get("scan_result", {})
        return f"Found {len(issues)} issues"

flow = ReviewFlow()
result = flow.run()
```

#### Method 4: SubAgentManager

```python
from tea_agent.multi_agent import SubAgentManager
mgr = SubAgentManager()
analyst = mgr.create_analyst_agent(goal="Review architecture")
result = mgr.call_agent(analyst.agent_id, "Analyze dispatcher.py")
```

### Core Components

- **FlowEngine** — Event-driven flow with conditional routing + Mermaid visualization
- **RoleAgent** — Role-specific agents with structured output (Pydantic)
- **MessageBus** — Publish/subscribe across agents with priority queues
- **Agent-as-Tool** — Any agent can be invoked as a tool by another agent
- **ExecutionPool** — Dual-channel (thread + async) parallel executor with circuit breaker
- **WorkflowDAG** — 6 node types (TASK/CONDITION/LOOP/PARALLEL/WAIT/END)
- **PatternMarket** — Reusable agent configuration marketplace

### Demo: Multi-Agent Debate

`demo/multi_agent/` — Two AI agents debate in real-time, 50 rounds.

```bash
python demo/multi_agent/server.py --port 8083
# Open http://127.0.0.1:8083
```

---

## 🧪 Testing

### 🔬 API Black-Box Tests

```bash
python tests/test_server_api.py [--host 127.0.0.1] [--port 8282]
```

**8 test suites (30+ test points):**
1. Health check
2. Topic management
3. Config & model info
4. Multi-topic switching
5. Delete & rename
6. PDF export (4 combinations)
7. Auxiliary APIs
8. Error paths (404/400/500)

### 📋 Unit Tests

```bash
pytest
# or
python -m pytest
```

---

## 🏗️ Project Structure

```
tea_agent/
├── agent.py               # Unified entry (3 modes)
├── onlinesession.py       # Full online session
├── litesession.py         # Lightweight session
├── basesession.py         # Base session + JSON fault tolerance
├── tlk.py                 # Tool loading/registration/execution engine
├── memory.py              # Long-term memory system
├── config.py              # Configuration management
├── providers.py           # 50+ LLM provider adapters
├── prompt_manager.py      # Prompt version management
├── reflection.py          # Meta-cognition reflection
├── permission.py          # Tool permission management
├── pipeline/              # Post-processing pipelines
├── gui.py                 # GUI desktop (Tkinter)
├── gui_dialogs.py         # GUI dialogs
├── tui.py                 # Terminal TUI (Textual)
├── server/                # REST API + Web V2 (Starlette + SSE)
├── protocol/              # ACP protocol
├── channel/               # Message channels (Telegram, WeChat)
├── toolkit/               # 75+ tool modules
├── session/               # Session management (L0/L1/L2/L3)
├── store/                 # Data storage (10 sub-modules)
├── multi_agent/           # Multi-agent system (6 phases)
├── lsp/                   # Code intelligence (Jedi + Tree-sitter)
├── workflow/              # Workflow engine
├── evaluation/            # Task evaluation
├── skills/                # Skill crystallization (18+ skills)
├── _gui/                  # GUI components (12 modules)
├── tests/                 # 41+ test files (600+ test cases)
└── demo/                  # Demo applications
```

---

## 🔧 Configuration

`~/.tea_agent/config.yaml`:

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  max_context_tokens: 0   # 0=unlimited, >0 enables progressive trimming
cheap_model:
  api_key: ""
  api_url: ""
  model_name: ""
  max_context_tokens: 0
embedding:
  provider: openai
  model: text-embedding-3-small
```

### Context Window Control

`max_context_tokens` limits total context sent to LLM:
- **0** = no limit
- **64000** = default for 64K~128K models
- **32000** = for 32K models
- **128000** = for GPT-4o / Claude large windows

Agents can self-tune via `toolkit_config` at runtime.

### 🎯 Ruff Code Style (v0.10.11+)

Built-in Ruff config in `pyproject.toml`:

```toml
[tool.ruff]
line-length = 150
target-version = "py310"
```

| Rule Set | Description |
|----------|-------------|
| `E` / `W` | pycodestyle errors/warnings |
| `F` | pyflakes logical errors |
| `I` | isort import sorting |
| `N` | pep8-naming conventions |
| `UP` | pyupgrade Python 3.10+ |
| `B` | flake8-bugbear bug detection |
| `C4` | Code simplification |
| `SIM` | Expression simplification |

---

## 📄 License

MIT License © 2024-2026 sunkw

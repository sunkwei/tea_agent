# Tea Agent v0.13.12

> ⚠️ **Experimental project — AI writing AI. Use at your own risk.**

> 🌐 **[中文版](README.md)**

> A self-evolving AI coding assistant — tool-driven, self-improving, multi-interface.

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.13.12-blue)](https://pypi.org/project/tea-agent)

Tea Agent is a **self-evolving AI coding assistant** with 75+ built-in tools. It can autonomously write code, debug, search, manipulate files, control browsers, and dynamically load new tools at runtime. Supports **GUI / Web / REST API / ACP Protocol / Telegram / WeChat** six interface modes.

---

## ✨ Core Features

- 🧠 **Self-Evolution Engine** — Modify its own code, create new tools, optimize prompts — full autonomous evolution
- 🧭 **Context-Aware** — Auto-detects project identity: full evolution enabled inside tea_agent's own project, disabled in external projects to stay focused on user tasks
- 🧰 **75+ Built-in Tools** — File ops, code editing, search, screenshot, OCR, package management, Git, etc.
- ⏱️ **Smart Command Timeout** — Background CPU/MEM/IO monitoring; active processes auto-extend timeout to 4x, idle ones terminate promptly
- 🖥️ **Multiple Interfaces** — GUI (Tkinter), Web (Starlette + SSE), REST API, ACP Protocol, pick your flavor
- 🌐 **Web V2 Real-time Streaming** — SPA (Single Page App) with memory search, memory management, task scheduler, full history
- 📚 **Project Knowledge Base** — Auto-build symbol index + call graph, code impact analysis
- 🔄 **Session Persistence** — Chat history survives restart, context restored
- 📋 **Plan / TODO** — Built-in task planning and tracking
- 🌐 **MCP Protocol** — Connect external MCP Servers for third-party tools
- 🎯 **Mode Switching** — design / develop / test / review / docs / devops six-phase workflow
- 🤖 **Multi-Agent System** — 6-stage full-stack collaboration: RoleAgent + FlowEngine + MessageBus + Agent-as-Tool + ExecutionPool + WorkflowDAG + PatternMarket
- 📡 **Message Channels** — Telegram Bot + WeChat iLink Bot dual adapters for multi-platform remote interaction
- 📊 **Task Evaluation** — Auto-assess task quality, record success/failure experience
- 💎 **Skill Crystallization** — Plan results auto-crystallize → semantic injection into new conversations → self-evolving skill loop
- 🛡️ **LLM JSON Fault Tolerance** — Smart repair of truncated JSON, control chars, single quotes, trailing commas
- 🔄 **Toolkit Hot-Reload** — `tlk.py` engine supports dynamic load/unload/reload without restart
- 🏗️ **Server Hot-Reload** — Agent/Toolkit/Storage/Pipeline modules hot-swappable at runtime, zero-downtime updates
- 📡 **Telegram Bot** — Remote message channel for Telegram interaction
- 🧪 **41+ Test Files** — Covering sessions, tools, storage, multi-agent, LSP core modules
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

For **embedded devices, resource-constrained environments, or Web-only** scenarios, Tea Agent offers the **Mini Edition** (`tea_agent_mini`) — dramatically reduced size and dependencies while preserving core functionality.

### ✨ Feature Comparison

| Capability | Full | Mini |
|------------|------|------|
| Agent Core Engine | ✅ | ✅ Full |
| Web V2 Interface (SPA) | ✅ | ✅ Full |
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
  │     ├─ session/  — Session management (history compression / token trimming)
  │     ├─ store/    — Data storage (10 sub-modules)
  │     ├─ toolkit/  — Excluding 12 heavy tools (see below)
  │     ├─ server/   — Web server (routes + static assets)
  │     ├─ multi_agent/ — Multi-agent collaboration
  │     ├─ evaluation/  — Task evaluation
  │     └─ skills/   — Skill crystallization (.md docs + registry)
  │
  ├─ 2. Excluded packages:
  │     ├─ _gui/     — Tkinter GUI
  │     ├─ gui.py / gui_dialogs.py — GUI desktop entry
  │     ├─ channel/  — Telegram / WeChat adapters
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
# Method 1: From PyPI (mini package already published, pending listing)
pip install tea_agent_mini

# Method 2: Build from source
git clone https://github.com/sunkwei/tea_agent
cd tea_agent
python build_mini.py

# Build output in build_mini_dist/dist/
pip install build_mini_dist/dist/tea_agent_mini-*.whl
```

### 🔨 Compile to Single-File Executable

`build_nuitka.py` compiles the Mini Edition further into a **single-file executable** (`.exe` / ELF), no Python environment required.

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

Mini Edition works identically to Full Edition for the Web interface:

```bash
# Start Web V2 interface (recommended)
python -m tea_agent.server

# Or via CLI
tea-agent-mini    # equivalent to python -m tea_agent_mini.__main__
```

Open `http://127.0.0.1:8282` in browser for the complete Web interface (chat, memory management, task scheduler, search, PDF export).

### 🧩 Mini Edition Dependencies

Mini Edition depends on only **7 core packages** (~5 MB total vs Full's ~80 MB):

```
openai>=1.0.0           # LLM API calls
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

# Mini Edition Web
tea-agent-mini
```

---

## 💻 Interface Modes

Tea Agent offers **six interface modes + Telegram Bot**, covering everything from desktop to web, CLI to API.

---

### 1. GUI Desktop (`tea-agent-gui`)

Native desktop client based on **Tkinter**, supporting Windows / Linux / macOS.

**Start:**
```bash
tea-agent-gui                     # CLI entry
python -m tea_agent.gui           # module mode
```

**Features:**
- 🔄 Real-time streaming chat, Markdown rendering, tool-call visualization
- 📋 Session list panel (search/switch/create/delete)
- 🧠 Long-term memory management panel (view/search/add/delete)
- ⏱️ Task scheduler (CRUD)
- 📤 PDF export, chat history export
- 🌙 System tray, global hotkey
- 🎨 Theme switching + font scaling

---

### 2. Web V2 (`python -m tea_agent.server`)

Next-gen SPA with pure HTML/JS frontend + Starlette API backend — all features in the browser.

> **Note**: `python -m tea_agent.server` starts both the REST API and Web V2 frontend.
> Open `http://127.0.0.1:8282` in browser for the complete Web interface.

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
| 📋 **Multi-session** | Session panel, click to switch history, auto-load messages. Multiple chat tabs open simultaneously without interference |
| 🧠 **Memory Management** | Modal panel, view/search/add/delete memories |
| ⏱️ **Task Scheduler** | CRUD with cron / interval / daily |
| 🔍 **Global Search** | Search chats, memories, tasks |
| 📤 **PDF Export** | Export current session to PDF |
| 🌙 **Theme Switching** | Dark/Light + accent color customization |
| ⚡ **Config Switching** | One-click switch between `~/.tea_agent/*.yaml` configs |
| 📎 **Image Preview** | Click-to-enlarge images in chat |
| 🚦 **Message Queue** | While a topic is responding, other topics queue and auto-send when done. Cancel & queue status visualization |

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

**Concurrent Streaming Architecture (v0.10.0+):**

```
Request A → create_session() → OnlineToolSession A 🔓 (config X)
Request B → create_session() → OnlineToolSession B 🔓 (config Y)
Request C → create_session() → OnlineToolSession C 🔓 (config Z)

Shared resources: Toolkit (read-only) + Storage (thread-safe)
Streaming: independent sessions, no global lock, truly concurrent
Non-streaming: shared Agent + lock (admin/config endpoints)
```

**Message Queue** — When a topic is responding, messages sent to other topics are queued and auto-sent once the current response completes. Queue status shows in real time (icon + count); queued messages can be cancelled anytime.

**Specifying Config** — Streaming requests can use different configs via `config_path`:

```bash
# Web UI auto-sends selected config; API can specify manually
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true,"config_path":"/home/user/.tea_agent/config_prod.yaml"}'
```

Different Web instances can use different config files, each running different models independently.

---
### 3. REST API Server (`python -m tea_agent.server`)

OpenAI-compatible HTTP API server for third-party integration.

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
| `GET` | `/v1/models` | Current model info |
| `GET` | `/v1/tools` | All available tools |
| `POST` | `/v1/tools/{name}/run` | Direct tool invocation |
| `GET/POST` | `/v1/sessions` | List/create sessions |
| `GET/DELETE` | `/v1/sessions/{id}` | Get/delete session |
| `GET` | `/v1/sessions/{id}/messages` | Get session messages |
| `GET` | `/v1/config` | Get config |
| `POST` | `/v1/config/switch` | Switch config file |
| `GET/POST/DELETE` | `/v1/memory` | Memory management |
| `GET/POST/DELETE` | `/v1/tasks` | Task scheduler |
| `GET` | `/v1/search` | Global search |
| `POST` | `/v1/export/pdf` | Export PDF |
| `GET` | `/docs` | OpenAPI docs |
| `GET` | `/openapi.json` | OpenAPI Schema |

**Examples:**
```bash
# Streaming chat
curl -N -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true}'

# Non-streaming chat
curl -X POST http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'

# List sessions
curl http://127.0.0.1:8080/v1/sessions

# Search
curl "http://127.0.0.1:8080/v1/search?q=keyword"
```

---

### 4. ACP Protocol Server (`python -m tea_agent.protocol`)

Agent Communication Protocol server — standardized Agent-to-Agent communication for VS Code / Cursor IDE integration.

**Start:**
```bash
python -m tea_agent.protocol --port 9090
```

**API Routes:**

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/agents` | Discover all available agents |
| `GET` | `/v1/agents/tea-agent` | Tea Agent details (incl. tool list) |
| `POST` | `/v1/agents/tea-agent/chat` | Send message (stream supported) |
| `GET/POST` | `/v1/sessions` | List/create sessions |
| `GET/DELETE` | `/v1/sessions/{id}` | Get/delete session |
| `GET` | `/v1/sessions/{id}/messages` | Get session messages |

**Features:**
- 🧰 **Tool Discovery** — Clients query full tool list + JSON Schema
- 📡 **SSE Streaming** — Real-time token-by-token output
- 🧵 **Session Management** — Isolated sessions with history
- 🔗 **IDE Integration** — Standard ACP protocol, any ACP client
- 🔒 **Config Isolation** — Independent config `~/.tea_agent/config_acp.yaml` and DB `chat_acp.db`, doesn't affect main app

---

### 5. Telegram Bot (`tea-agent-telegram`)

Telegram messaging adapter based on `python-telegram-bot`.

**Start:**
```bash
tea-agent-telegram                  # CLI entry
python -m tea_agent.channel.telegram_adapter  # module mode
```

**Features:**
- 💬 Chat with Agent via Telegram
- 🔄 Long message chunking for extended conversations
- 🔌 Runs alongside other interfaces without interference

### 6. WeChat Bot (`tea-agent-wechat`) 🆕

WeChat messaging adapter based on Tencent's official iLink Bot API — connect tea_agent to personal WeChat.

**Start:**
```bash
tea-agent-wechat                    # Auto-shows QR code on first run
python -m tea_agent.channel.wechat_adapter  # module mode
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

Tea Agent's memory system mimics human memory: **priority-tiered**, **relevance-retrieved**, **naturally decaying**, **deduplicated & merged**. Backed by SQLite persistence + embedding semantic vectors, managed by `MemoryManager`.

---

### 1. Memory Storage Structure

Each memory entry has these core fields:

| Field | Type | Description |
|-------|------|-------------|
| `content` | TEXT | Memory content (concise summary) |
| `priority` | INT (0-3) | `0=CRITICAL` / `1=HIGH` / `2=MEDIUM` / `3=LOW` |
| `importance` | INT (1-5) | 5=critical, ignoring causes serious issues; 1=trivial |
| `category` | TEXT | `instruction` / `preference` / `fact` / `reminder` / `general` |
| `tags` | TEXT | Comma-separated tags for fast matching |
| `content_hash` | TEXT | SHA256 first 16 chars, fast dedup fingerprint |
| `embedding` | BLOB | `numpy.float32` vector for cosine semantic search |
| `expires_at` | DATETIME | Expiration date (NULL = never expires) |
| `pinned` | INT | Pinned flag (exempt from age decay) |
| `created_at` | DATETIME | Creation time (used for age decay) |

---

### 2. Selection Algorithm

At each conversation start, `MemoryManager.select_memories()` selects the most relevant **≤30 entries** from active memory pool:

```
score = relevance(keyword match) × importance(÷5) × age_factor × priority_factor

age_factor: 1 day=1.0, 7 days=0.9, 30 days=0.7, 90 days=0.5, >90 days=0.3
priority_factor: (4 - priority) / 4
```

**Tiered floor strategy** (prevents all-CRITICAL selection):

```
1. CRITICAL first (max 10, FIFO newest)
2. Non-CRITICAL sorted by score
3. Tiered floor quotas:
   - HIGH   ≥ 3 entries
   - MEDIUM ≥ 2 entries
   - LOW    ≥ 1 entry
4. Remaining slots: free competition (highest score wins)
5. Selected memories update last_accessed_at
```

---

### 3. Age Decay

Ebbinghaus forgetting curve simulation. `degrade_by_age()` runs before each selection; **pinned=true memories are exempt**:

| Original Priority | Decay Condition | Demoted To |
|------------------|----------------|------------|
| CRITICAL | Created > 30 days | HIGH |
| HIGH | Created > 60 days | MEDIUM |
| MEDIUM | Created > 90 days | LOW |

---

### 4. LLM Priority Tuning

`MemoryManager.llm_adjust_priorities()` uses a cheap LLM to evaluate recent conversation topics and fine-tune memory priorities:

```
Input: recent topic summaries (≤2000 chars) + active memories (≤100, each ≤80 chars)
Rules:
  - ±1 level adjustment only (no skipping)
  - Max 3 memories adjusted per run
  - Upgrades reset created_at (restart decay)
  - JSON array output only, no extra text
```

---

### 5. Memory Extraction

After each conversation, `MemoryManager` auto-extracts memories from user messages via LLM:

```
Extraction categories:
  instruction → explicit "remember" rules        → priority=0 (CRITICAL)
  preference  → habits/preferences               → priority=1 (HIGH)
  reminder    → time-sensitive (with expires_at) → priority=1 (HIGH)
  fact        → technical facts/architecture     → priority=2 (MEDIUM)
  general     → other reference info             → priority=3 (LOW)

Fault-tolerant parsing:
  1. Direct JSON.parse
  2. Extract markdown ```json code blocks
  3. Regex match JSON arrays
  4. Object type → extract array from common keys (memories/items/results/data)
```

---

### 6. Dedup & Merge

Before writing, `ingest_extracted()` runs the dedup & merge pipeline:

```
Each new memory:
  1. jieba tokenize → keyword Jaccard similarity
  2. Same-category weighted +10%
  3. Similarity ≥ 0.6 → merge into existing memory:
     - content: keep longer, or concatenate
     - priority: take lower (more critical)
     - importance: take higher
     - tags: union dedup
     - expires_at: keep earlier expiry
  4. < 0.6 → new record
```

**Batch dedup** (`detect_duplicates` / `auto_dedup`): embedding cosine similarity (threshold 0.92) scans all active memories, auto-merges and promotes near-duplicate pairs.

---

### 7. CRITICAL FIFO Eviction

Max 30 CRITICAL entries — oldest soft-deleted (FIFO) when exceeded, preventing instruction memory from growing unbounded.

---

### 8. Reflection & Summarization

`reflect_and_summarize()` clusters recent memories by category, generates a summary stored as CRITICAL/importance=5, and downgrades originals:

```
Category clustering (instruction/preference/fact/reminder/general)
  → each category ≥ 2 entries → keyword-frequency summary
  → summary stored as CRITICAL/importance=5
  → original memories importance -1 (downgrade)
```

---

### 9. Cross-topic Aggregation (v0.13.3+)

Every 3 conversations, a background thread performs cross-topic analysis: reads recent topic list, uses a cheap LLM to discover cross-topic patterns/trends/associations, produces insight-type memories for global awareness.

```
Each round end → counter++ → count % 3 == 0?
                           │
                     yes → read recent topic list
                           │
                         cheap LLM cross-topic analysis
                           │
                     insight memory written to DB
```

---

### Formatting Injection

Selected memories are formatted by priority and injected into the system prompt area:

```python
def _prefix_for(memory):
    if priority == CRITICAL:  return "!!! MUST FOLLOW:"
    if category == "reminder": return "⏰ REMINDER:"
    if category == "preference": return "💡 PREFERENCE:"
    if category == "fact":      return "📌 FACT:"
    return "📎"
```

> Agents can manage memories manually via the `toolkit_memory` tool. See [`docs/TOOLS.md`](docs/TOOLS.md)

---
## 📜 Four-Level History Compression (L0 → L3 → L2 → L1)

Tea Agent uses **four hierarchical layers** to build the context sent to the LLM, maximizing information density within a limited token window. All layers are assembled by `build_api_messages()` in `session/_history_builder.py`.

```
┌─────────────────────────────────────────────────┐
│  Level 0: System Layer                           │
│  ├─ System prompt                                │
│  ├─ Skill recommendation injection (semantic)    │
│  ├─ Pending task resume (TODO/Plan)              │
│  └─ Long-term memory injection (MemoryManager)   │
├─────────────────────────────────────────────────┤
│  Level 3: Summary Layer (LLM-generated)          │
│  └─ Generated on L2 overflow: keep conclusions   │
├─────────────────────────────────────────────────┤
│  Level 2: History Pairs (SQLite persisted)       │
│  └─ user + AI final msg pairs, relevance-filtered│
├─────────────────────────────────────────────────┤
│  Level 1: Current Conversation (active session)  │
│  ├─ Compressed tool chain (calls → summary)      │
│  ├─ Old tool output → placeholders               │
│  └─ Tool output truncation (head/tail, newline)  │
└─────────────────────────────────────────────────┘
```

---

### Level 0: System Layer

```python
# L0 assembly order in build_api_messages()
result = []

# 1. System prompt
result.append({"role": "system", "content": system_prompt})

# 2. Pending task resume (toolkit_task_resume)
resume_info = toolkit_task_resume(action="check")
if resume_info["has_pending"]:
    result.append({"role": "user", "content": format_resume(resume_info)})

# 3. Long-term memory injection
if context._injected_memories_text:
    result.append({"role": "user", "content": context._injected_memories_text})
```

---

### Level 3 (L3) — Semantic Summary

`SummaryStore` manages two L3 summary types:

| Summary Type | Storage | Trigger | Content |
|--------------|---------|---------|---------|
| **Semantic Summary** | `topics.semantic_summary` | L2 overflow (50→20 trim) | Project background / completed changes / key decisions / bug fixes / architecture constraints / user preferences / TODOs |
| **Tool Chain Summary** | `topics.tool_chain_summary` | Async background thread | Recent tool call chain review |

**L2→L3 generation** (`generate_l2_to_l3_summary`):

```
Trigger: push_to_level2() returns should_summarize=True
         (L2 count ≥ 50 → oldest 30 overflow)

Flow:
  1. Take overflow 30 L2 entries (user + thinking + assistant)
  2. Merge existing L3 summary (if any)
  3. Generate new summary with cheap model (temperature=0.3, max_tokens=4096)
  4. Store into topics.semantic_summary
  5. Trim L2 to latest 20 entries

Compression ratio: 30 turns (≈20K tokens) → ~500 token summary
```

**L3 injection format:**

```
[System Memory — Rules to Follow]

##### Long-term Background/Preferences/Key Conclusions
{semantic_summary}

---

##### Historical Tool Chain Review
{tool_chain_summary}
```

---

### Level 2 (L2) — History Pairs

L2 is a **fixed-size ring buffer** stored in SQLite `topics.level2_json`, capacity 50 entries.

**Entry structure:**

```json
{
  "user": "user's original message",
  "assistant": "AI final reply (excluding tool-call intermediates)",
  "thinking": "assistant content + reasoning from tool-call rounds",
  "files": ["related file paths (optional)"]
}
```

**Write flow** (`push_to_level2`):

```python
def push_to_level2(topic_id, user_msg, ai_msg, files, rounds):
    thinking = extract_thinking_from_rounds(rounds)
    entry = {"user": user_msg, "assistant": ai_msg, "thinking": thinking, "files": files}
    level2.append(entry)

    overflow = []
    should_summarize = False
    if len(level2) >= 50:
        overflow = level2[:30]      # oldest 30 → L3 summary
        level2 = level2[-20:]        # keep latest 20
        should_summarize = True

    return len(level2), overflow, should_summarize
```

**Relevance filter** (`filter_level2_by_relevance`):

```
For each L2 entry, Jaccard similarity against current user message keywords:
  - Extract 2-char Chinese + 3-letter English keywords from user message
  - Extract keywords from L2 entry's user + thinking + assistant
  - Compute Jaccard: |intersection| / |union|
  - File paths extra weighted (file_overlap ≥ 1 → min(score, 0.4 + count × 0.1))

Filter rules:
  ≥ 0.15   → keep full user+assistant pair (injected as [History])
  ≥ 0.05   → keep summary snippet only ("User: xxx... → Assistant: yyy...")
  < 0.05   → skip (token saving)
  all < 0.05 → floor: inject highest-scoring entry (full pair)
```

---

### Level 1 (L1) — Current Conversation

L1 is the **current session's raw messages** (`context.messages`), compressed in multiple layers before being sent to the API.

#### First Line: Real-time Tool Output Truncation

Every tool result is truncated immediately to prevent oversized outputs:

```python
max_tool_output = 128 * 1024  # 128KB
if len(result_bytes) > max_tool_output:
    head = result_bytes[:max_tool_output // 2]  # 64KB
    tail = result_bytes[-max_tool_output // 2:] # 64KB
    result_str = f"{head.decode()}\n\n... [Tool output truncated] ...\n\n{tail.decode()}"
```

#### Second Line: Old Tool Output Placeholders

`_find_prune_cutoff()` finds the boundary of the most recent 3 user messages:

```
Tool messages older than 3 rounds → "[Tool result omitted: N chars]"
Tool messages within 3 rounds     → fully preserved
```

#### Third Line: Progressive Token Trimming

When `max_context_tokens > 0`, `_progressive_trim()` runs a 5-stage cascade:

| Stage | Action | Description |
|-------|--------|-------------|
| 1 | Delete `[History]` L2 entries | Oldest first |
| 2 | Replace old tool output with placeholders | `[Tool result omitted: N chars]` |
| 3 | Clear reasoning_content | Free thinking tokens |
| 4 | Truncate long texts | Limit 4096 chars |
| 5 | Delete old L1 turns | Keep latest 5 user messages |
| Fallback | Truncate last message | Keep first 1/3 |

---

### Assembly Flow Overview

```
build_api_messages(context, system_prompt) full flow:

1. Level 0: system prompt + TODO resume + memory injection
2. Level 3: semantic summary + tool chain summary (with assistant "OK, understood...")
3. Level 2: relevance filter → [History] user + assistant pairs
4. Level 1: truncation boundary → tool placeholders → message traversal:
   - tool_calls integrity check
   - multimodal format conversion
   - reasoning_content completion
5. Progressive trimming: estimate_messages_tokens() > 80% budget → _progressive_trim()
6. JSON integrity validation + orphan tool message removal
```

### Token Estimation

Heuristic token estimation (no tiktoken needed):
- English: ~4 chars = 1 token
- Chinese: ~1.5 chars = 1 token
- Image: fixed ~85 tokens
- Message structure overhead: +4 tokens per message

### Async Summaries

After each turn, `do_async_summaries()` runs in a background thread:
1. **Title summary** (`auto_summary`): cheap model generates a one-line topic title
2. **L2→L3 summary** (`l2_to_l3_summary`): only on L2 overflow

Cheap-model token consumption is merged into the next GUI display via `agent._pending_cheap_tokens`.

---
## 🔄 Self-Evolution Engine

Tea Agent's self-evolution system consists of **four layers**: tool hot-plug (foundation) → safe self-modification → prompt evolution → experience crystallization.

---

### 0. Context-Aware Rules (Pre-constraint)

> **Core design principle: Self-evolution activates only within tea_agent's own project.**

Self-evolution is a double-edged sword — a core advantage when developing tea_agent itself, but harmful noise when modifying other projects. The system prompt therefore includes **project identity detection**:

```
Before each task, detect project identity:
1. If tea_agent project (tea_agent/agent.py exists in cwd or parent)
   → Full evolution: create tools, modify source, optimize prompts
2. If external project (not tea_agent itself)
   → Evolution disabled: no new tools, no source framework changes, no prompt optimization
   → Focus on the external task using generic file/read/write/search/edit tools only
```

This rule is written into the default system prompts of `prompt_manager.py` and `litesession.py` — applied uniformly across all session modes (OnlineToolSession / LiteSession / Sub-agent).

Additionally, **AGENTS.md** (if present) can further refine project-level constraints. See [`AGENTS.md`](AGENTS.md).

---

### 1. Tool Hot-Plug: `toolkit_save` / `toolkit_reload`

Create/modify tools at runtime, **immediately effective** without restart.

```
Agent identifies new capability needed
  │
  ├─ 1. Write Python function code
  ├─ 2. Define OpenAI function schema (params/description)
  │
  ├─ 3. toolkit_save(name, meta, pycode)
  │     ├─ stored to tea_agent/toolkit/{name}.py
  │     ├─ auto versioning (v1.0.0 → v1.1.0 → ...)
  │     ├─ history saved to .versions/ directory
  │     └─ auto-generates skills/{name}/SKILL.md doc
  │
  ├─ 4. toolkit_reload()
  │     ├─ scans all .py in toolkit/
  │     ├─ dynamic importlib loading
  │     ├─ registers meta → generates tool schema
  │     └─ all toolkit_* functions globally available
  │
  └─ 5. New tool available immediately in subsequent conversations
```

**Version management:**

| Feature | Description |
|---------|-------------|
| **Auto version** | Each save increments `v1.0.0 → v1.0.1 → v1.1.0` |
| **Safe rollback** | `toolkit_rollback(name, version)` to any historical version |
| **Version list** | `toolkit_list_versions(name)` |
| **SKILL.md** | Auto-generated skill doc with parameter table + examples |

---

### 2. Five-Layer Safe Self-Modification: `toolkit_self_evolve`

Agent modifying its own code is protected by **five safety layers**:

```
┌──────────────────────────────────────────────┐
│  Layer 0: Git snapshot                        │
│  git add + git commit "snapshot: pre-evolve"  │
│  only when working tree is clean              │
├──────────────────────────────────────────────┤
│  Layer 1: Timestamp .bak file                 │
│  {file}.bak.{YYYYMMDD_HHMMSS}                │
│  never overwrites historical backups          │
├──────────────────────────────────────────────┤
│  Layer 1.5: Python syntax strict check        │
│  newlines / indentation / brackets / colons   │
│  failure → immediate rollback                 │
├──────────────────────────────────────────────┤
│  Layer 2: py_compile verification             │
│  failure → auto-rollback tmp_bak + git reset  │
├──────────────────────────────────────────────┤
│  Layer 2.5: LSP smart checks                  │
│  ├─ impact analysis (callers/deps/risk)       │
│  ├─ ruff lint diff                            │
│  ├─ function signature comparison             │
│  └─ jedi semantic diagnostics                 │
│  non-blocking: warnings only                  │
├──────────────────────────────────────────────┤
│  Layer 3: pytest verification                 │
│  failure → git reset --hard rollback          │
└──────────────────────────────────────────────┘
```

Rollback chain: Layer 1.5 failure → restore tmp_bak; Layer 2 failure → restore git; Layer 3 failure → git reset --hard.

---

### 3. Prompt Evolution: `toolkit_prompt_evolve`

Agent **self-optimizes system prompts**, managed by `SystemPromptManager` with multi-version support:

```
Version management: config table system_prompts (is_active, version, content, created_at)

Evolution operations:
  action='list'     → view all version history
  action='current'  → view active version
  action='evolve'   → reflections + memories → LLM new version → activate
  action='rollback' → revert to specified version
  action='set'      → manually set new version

Evolution inputs:
  - current prompt (≤500 char requirement)
  - latest reflection suggestion (ReflectionManager.last_prompt_suggestion)
  - relevant long-term memories (MemoryManager selection)
```

---

### 4. Experience Crystallization: `toolkit_experience_solidify`

Post-task autopsies turn into reusable patterns:

```
action='auto':
  analyze → analyze execution process
  ├─ success → solidify → skill library (toolkit_dynamic_skill)
  └─ failure → lesson   → knowledge base (toolkit_evolution_exp)

Categories:
  dependency / architecture / ui / performance / testing / deployment
```

**Dynamic Skill System** (`toolkit_dynamic_skill`):

```
record     → record successful agent patterns (task + agents[])
recommend  → recommend agent combos by task
search     → search similar skill patterns
list       → list all skill patterns
```

---

### Self-Evolution Overview

| Capability | Tool | Safety | Description |
|------------|------|--------|-------------|
| Create new tools | `toolkit_save` + `toolkit_reload` | version rollback | hot-plug, no restart |
| Modify source | `toolkit_self_evolve` | 5-layer | Git↔Bak↔compile↔LSP↔tests |
| Optimize prompts | `toolkit_prompt_evolve` | version rollback | reflections + memories |
| Crystallize experience | `toolkit_experience_solidify` | categories | success→skill, failure→lesson |
| Code intelligence | `toolkit_lsp` | read-only | diagnose/completion/definition/references |

---
## 🧰 Tool Overview (75+)

| Category | Tools |
|----------|-------|
| 📁 File Ops | `toolkit_file`, `toolkit_save_file`, `toolkit_explr`, `toolkit_batch_process` |
| ✏️ Code Edit | `toolkit_edit`, `toolkit_diff_edit`, `toolkit_diff`, `toolkit_self_evolve`, `toolkit_format_code`, `toolkit_auto_fix`, `toolkit_code_review` |
| 🔍 Search | `toolkit_search`, `toolkit_lsp`, `toolkit_query_chat_history` |
| 📸 Screenshot/OCR | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_screen_read` |
| 🖱️ Control | `toolkit_input`, `toolkit_browser_tab`, `toolkit_js_fetch` |
| 📦 Package | `toolkit_pkg`, `toolkit_build` |
| 🧪 Testing | `toolkit_run_tests` |
| 🗓️ Utilities | `toolkit_lunar`, `toolkit_weather_my`, `toolkit_gettime`, `toolkit_date_diff` |
| 🔧 System | `toolkit_exec`, `toolkit_config`, `toolkit_os_info`, `toolkit_sudo_gui`, `toolkit_clipboard` |
| 🧠 Memory/Knowledge | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 Multi-Agent | `toolkit_parallel_subtasks`, `toolkit_subagent`, `toolkit_subagent_msg`, `toolkit_auto_pipeline`, `toolkit_remote_agent` |
| 📋 Plan/Task | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume`, `toolkit_topic_prompt` |
| 🔌 MCP | `toolkit_mcp` |
| 🌐 Web/GUI | `toolkit_dump_topic`, `toolkit_export_last_pdf`, `toolkit_notify` |
| 📤 Export | `toolkit_dump_topic`, `toolkit_export_last_pdf` |
| 🧬 Evolution | `toolkit_self_evolve`, `toolkit_prompt_evolve`, `toolkit_evolution_exp`, `toolkit_experience_solidify` |
| 🛠️ Others | `toolkit_question`, `toolkit_stream_save`, `toolkit_set_topic_title`, `toolkit_self_report`, `toolkit_toggle_reasoning`, `toolkit_get_config_path`, `toolkit_get_models`, `toolkit_list_provider_models`, `toolkit_ip_location_my`, `toolkit_custom_commands`, `toolkit_scheduler_storage`, `toolkit_mode`, `toolkit_skills`, `toolkit_release_version`, `toolkit_harness_schema`, `toolkit_git_push_all_remotes` |

> Full tool list: [`docs/TOOLS.md`](docs/TOOLS.md)

---

## 🤖 Multi-Agent System (v0.11+)

Tea Agent's Multi-Agent system is a **full-stack collaboration framework from simple to complex, from conversation to programming**, covering 6 development phases:

```
Phase 1: Core            RoleAgent + FlowEngine + RoleDispatcher
Phase 2: Communication   MessageBus + Agent-as-Tool + ToolRegistry
Phase 3: Observability   CheckpointManager + TraceEngine
Phase 4: Marketplace     PatternMarket + AdminPanel
Phase 5: Parallel Engine ExecutionPool + LoadBalancer + CircuitBreaker
Phase 6: Advanced DAG    WorkflowDAG (condition/loop/parallel/wait)
```

---

### 🚀 Quick Start

#### Method 1: In-Dialogue (Zero Code)

No Python needed — just tell the Agent:

| Tool | Purpose |
|------|---------|
| `toolkit_parallel_subtasks` | Decompose complex task → parallel execute → auto-summarize |
| `toolkit_subagent` | Spawn independent sub-agents (sync/async) |
| `toolkit_subagent_msg` | Point-to-point messaging between sub-agents |

**Example** — parallel analysis of multiple files:
```
Just tell the Agent: "Help me review all .py files under src/ in parallel"
The Agent auto-calls toolkit_parallel_subtasks to decompose + execute + summarize.
```

**Sub-agent messaging example:**
```
# Agent A sends message to Agent B
toolkit_subagent_msg(action="send", to="agent-B", message="Analysis complete")

# Agent B receives
toolkit_subagent_msg(action="check_inbox", agent_id="agent-B")
```

---

#### Method 2: Python API

##### RoleDispatcher — One-Stop

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()

# Auto-detect task mode (refactor/review/test/fix/docs/feature)
result = dispatcher.dispatch("Refactor project with type annotations")
print(result["summary"])
# → ✅ Complete: Refactor project with type annotations (4 steps, 12.3s)

# Visualize execution plan (no execution)
print(dispatcher.visualize("Add type annotations to gui.py"))
```

##### RoleAgent — Role-based Agent

```python
from tea_agent.multi_agent import RoleAgent

analyst = RoleAgent(
    role="Senior Code Reviewer",
    goal="Review code quality, identify design issues and bad smells",
    backstory="You have 15 years of software architecture experience...",
)
result = analyst.execute("Review dispatcher.py design")
print(result.structured)  # Pydantic structured output
```

Prebuilt role shortcuts:
```python
from tea_agent.multi_agent import (
    create_analyst, create_coder, create_tester, create_reviewer,
)

coder = create_coder(goal="Implement user login module")
tester = create_tester(goal="Write tests for login module")
reviewer = create_reviewer(goal="Review login module code")
```

##### FlowEngine — Event-Driven Workflow

```python
from tea_agent.multi_agent import FlowEngine, flow_start, flow_listen

class ReviewFlow(FlowEngine):
    @flow_start()
    def scan(self):
        """Step 1: code scan"""
        return self.call_agent("reviewer", "Full code review")

    @flow_listen(scan)
    def report(self):
        """Step 2: report (auto-triggered after scan)"""
        issues = self.state.get("scan_result", {})
        return f"Found {len(issues)} issues"

flow = ReviewFlow()
result = flow.run()
```

**Built-in Flow patterns:**

| Pattern | Flow Class | Steps |
|---------|-----------|-------|
| Refactor | `RefactorFlow` | analyze → plan → execute → verify |
| Review | `ReviewFlow` | scan → report |
| Test | `TestFlow` | plan tests → write → run |
| Fix | `FixFlow` | diagnose → fix → verify |
| Feature | `FeatureFlow` | analyze → implement → test |
| Docs | `DocFlow` | analyze → write → format |

#### Method 3: Custom Flow (Advanced Orchestration)

```python
from tea_agent.multi_agent import RoleDispatcher

dispatcher = RoleDispatcher()

# Custom flow
class MyPipeline(FlowEngine):
    @flow_start()
    def fetch_data(self): ...
    @flow_listen(fetch_data)
    def process(self): ...
    @flow_listen(process)
    @flow_route(lambda ctx: "fast" if ctx["size"] < 100 else "full")
    def fast_path(self): ...
    @flow_listen(process)
    def full_path(self): ...

result = dispatcher.dispatch_with_flow(MyPipeline, "Data processing")
```

#### Method 4: SubAgentManager (Communication + Discovery + Registration)

```python
from tea_agent.multi_agent import SubAgentManager

mgr = SubAgentManager()

# Create & register sub-agents (auto-register to MessageBus + ToolRegistry)
analyst = mgr.create_analyst_agent(goal="Review code architecture")
coder = mgr.create_coder_agent(goal="Implement feature module")

# Call sub-agent (Agent-as-Tool)
result = mgr.call_agent(analyst.agent_id, "Review dispatcher.py")

# Cross-agent publish
mgr.publish(analyst.agent_id, "task:complete", {"status": "done"})

# List all active agents
agents = mgr.list_agents()
```

---
### 🧩 Core Components

#### 1. FlowEngine — Event-Driven Flow Engine

Inspired by CrewAI Flows + LangGraph StateGraph:

```
@flow_start()          → start step (no dependencies)
@flow_listen(step_a)   → listen step (auto-triggered after step_a)
@flow_route(cond_fn)   → conditional routing (branch by state)
```

**Features:**
- 📊 Mermaid visualization: `flow.visualize()`
- 🔄 Loop detection + branch execution
- 📦 Cross-step state sharing (`FlowState`)
- ⏱️ Step-level timeout + error isolation

#### 2. RoleAgent — Role-based Agent

Each agent has explicit **identity, goal, backstory**:

```python
RoleAgent(
    role="Senior Engineer",      # identity
    goal="Implement feature",     # goal
    backstory="...",              # backstory (behavior style)
)
```

**Built-in roles:** `create_analyst()` / `create_coder()` / `create_tester()` / `create_reviewer()`

**Features:**
- 🎯 Tool whitelist — restrict sub-agent tool access
- 📐 Structured output — Pydantic models (`AnalysisReport` / `CodeChangePlan` / `TestPlan` / `CodeReview`)
- 🧵 Real LLM calls based on `LiteSession`

#### 3. MessageBus — Cross-Agent Publish/Subscribe

```python
from tea_agent.multi_agent import MessageBus, MessagePriority

bus = MessageBus()
bus.subscribe("agent-A", "task:update")
bus.subscribe("agent-B", "task:update")

# Publish (auto-broadcast to all subscribers)
bus.publish("task:update", {"progress": 50}, priority=MessagePriority.HIGH)

# Consume
messages = bus.consume("agent-A")
```

| Feature | Description |
|---------|-------------|
| **Topic pub/sub** | One-to-many broadcast (vs point-to-point of toolkit_subagent_msg) |
| **Priority queue** | LOW / NORMAL / HIGH / CRITICAL |
| **Persistence** | Optional SQLite storage |
| **Thread-safe** | Built-in locks, concurrent read/write |

#### 4. Agent-as-Tool — Agent as a Tool

**Core pattern**: any RoleAgent can be registered as a "tool" and invoked by other agents like a normal tool.

```python
from tea_agent.multi_agent import AgentTool, AgentToolManager

tool = AgentTool(analyst, name="code_analyst",
                 description="Analyze code architecture quality")

# Invoke (like calling toolkit_xxx)
result = tool.call(task="Review dispatcher.py design")

# Batch management
mgr = AgentToolManager()
mgr.register(tool)
mgr.list_tools()
```

**Advantages:**
- 🔌 Caller doesn't need to know the callee's internals
- 🛡️ Concurrency control (`max_concurrent` + timeout)
- 📊 Call statistics (success/failure/duration)

#### 5. ExecutionPool — High-Performance Parallel Engine

```
ExecutionPool (unified entry)
    ├── ThreadPoolChannel  ── sync/IO/CPU-intensive tasks
    ├── AsyncChannel       ── async/await coroutine tasks
    ├── PriorityQueue      ── priority scheduling
    └── Monitor            ── health monitoring + stats
```

**Features:**
- ⚡ Dual-channel concurrency (thread pool + async)
- ⚖️ Smart load balancing (round-robin / least-connection / weighted)
- 🛡️ Resource isolation (CPU/memory/concurrency caps)
- 🔌 Circuit breaker + auto-retry + fault tolerance
- 📊 Task metadata tracking

```python
from tea_agent.multi_agent import ExecutionPool

pool = ExecutionPool(max_workers=8)
future = pool.submit(func, arg1, arg2=value)
result = future.result(timeout=30)

# Batch + timeout
results = pool.map(func, items, timeout=30)

# View status
print(pool.status())
# → {"running": 2, "queued": 5, "completed": 100, ...}
```

#### 6. WorkflowDAG — Advanced Workflow Orchestration

DAG definition engine with 6 node types:

| Node Type | Description |
|-----------|-------------|
| `TASK` | Regular task |
| `CONDITION` | Conditional branch (if/elif/else) |
| `LOOP` | Loop (for-each / while) |
| `PARALLEL` | Parallel fan-out (fan-out → fan-in) |
| `WAIT` | Wait (timer / condition met) |
| `END` | Terminal node |

```python
from tea_agent.multi_agent import WorkflowDAG, WorkflowExec, WorkflowNode, NodeType

dag = WorkflowDAG()
dag.add_node(WorkflowNode("start", NodeType.TASK, fn=lambda ctx: {"data": 42}))
dag.add_node(WorkflowNode("check", NodeType.CONDITION, fn=lambda ctx: ctx["data"] > 10))
dag.add_node(WorkflowNode("process", NodeType.TASK, fn=lambda ctx: {"result": ctx["data"] * 2}))
dag.add_edge("start", "check")
dag.add_edge("check", "process", condition_key="true")

wf = WorkflowExec(dag)
result = wf.run({"start": {}})
```

#### 7. PatternMarket — Pattern Marketplace

Reusable agent configuration template repository (CRUD + search + recommend + instantiate):

```python
from tea_agent.multi_agent import get_pattern_market

market = get_pattern_market()

# Search patterns
patterns = market.search("code review")

# Create agent from pattern
agent = market.instantiate("Senior Engineer")

# Custom pattern
market.register({
    "name": "Performance Optimization Expert",
    "role": "Performance Engineer",
    "goal": "Analyze and optimize code performance",
    "backstory": "You master various performance analysis techniques.",
    "tools": ["toolkit_exec", "toolkit_lsp", "toolkit_explr"],
    "tags": ["performance", "optimization"],
})
```

**Built-in patterns (4):** Code Reviewer / Senior Engineer / Test Engineer / Analyst

#### 8. CheckpointManager + TraceEngine

| Component | Purpose |
|-----------|---------|
| `CheckpointManager` | Execution state persistence + crash recovery, resume from checkpoint |
| `TraceEngine` | Span-based execution trace, visualize agent call chains |

---

### ⚔️ Multi-Agent Debate Demo

`demo/multi_agent/` — Two AI agents debate in real-time, 50 rounds alternating.

**Quick start:**
```bash
python demo/multi_agent/server.py --port 8083
# Open http://127.0.0.1:8083
```

**Features:**
- 🔵🔴 Split screen: both sides use different config files and models
- ✍️ Side A opens → Side B rebuts → Side A counters → ... 50 rounds
- 📡 SSE real-time streaming of each round
- 📊 Progress bar + typing animation + independent scrolling panels
- 🛑 Stop mid-way supported
- ⚙️ Independent config selection per side (auto-discovers `~/.tea_agent/*.yaml`)

```
┌────────────────────┬────────────────────┐
│    🔵 Side A        │    🔴 Side B        │
│  config_prod.yaml   │  config_local.yaml │
│    GPT-4o           │    Qwen 2.5        │
├────────────────────┼────────────────────┤
│ Round 1: Opening   │                    │
│        ↓           │ Round 2: Rebuttal  │
│ Round 3: Counter   │        ↓           │
│        ↓           │ Round 4: Rebuttal  │
│      ...50 rounds  │      ...50 rounds  │
└────────────────────┴────────────────────┘
```

> Implementation: reuses `_create_session_from_cfg()` + `_load_config_cached()` from `server.py`; each debater has an independent `OnlineToolSession`, fully isolated.

---

### ✅ Advantages

- 🚀 **Fast** — Large tasks decomposed into parallel sub-tasks, full concurrency
- 🎯 **Focused** — Each sub-agent focuses on its own role domain
- 🧩 **Composable** — Agent-as-Tool, combine capabilities like building blocks
- 🔄 **Controllable** — FlowEngine event-driven + WorkflowDAG static orchestration
- 📢 **Communicable** — MessageBus pub/sub + point-to-point messaging
- 🛡️ **Fault-tolerant** — Circuit breaker + auto-retry + checkpoint recovery + error isolation
- 📊 **Observable** — TraceEngine tracks every agent call chain
- ♻️ **Reusable** — PatternMarket stores templates, one-click instantiate
- 🔌 **Zero-code trigger** — `toolkit_parallel_subtasks` / `toolkit_subagent` directly in dialogue

### ⚠️ Limitations

- 💰 **High token cost** — Each sub-agent calls LLM independently; total = sub-tasks × per-task cost
- 🐌 **Coordination overhead** — Inter-task dependencies serialize (Flow/DAG), not all parallel
- 🔍 **Hard to debug** — Distributed agent behavior less predictable than single agent
- 🧠 **Context isolation** — Sub-agents don't share memory by default; explicit context passing needed
- 💥 **Modification conflicts** — Concurrent edits to the same file may conflict (avoid via Flow serialization)
- ⚙️ **LLM quality dependent** — Sub-agent task understanding depends on the underlying model

---

## 📡 Remote Device Agent (v0.13.10+)

Tea Agent connects to **remote terminal devices** running `tea_agent.server` via the `toolkit_remote_agent` tool — enabling PC host Agent ↔ device AI collaboration.

### Use Cases

- **Embedded device debugging** — Execute tasks remotely on RK3588 / BM1688 / X3 devices
- **Edge node management** — Remote log analysis, service status checks
- **Distributed collaboration** — Host AI decomposes tasks, device AI executes locally, results aggregated

### Core Operations

| Operation | Description | Example |
|-----------|-------------|---------|
| **register** | Register remote device (IP + port + working dir) | Host knows where and what the device does |
| **exec** | Send task to device AI | Device AI autonomously analyzes logs, debugs code |
| **status** | Check device online | Heartbeat |
| **list** | List all registered devices | View device list |
| **unregister** | Disconnect/remove remote device | Cleanup after task or device offline |

### Working Modes

#### ① Register Device

```python
toolkit_remote_agent(action="register",
    device_id="bm1688-1",
    host="172.16.1.49",
    port=8282,
    working_path="/app/zkfs/video_analyse/")
```

#### ② Deploy Task (auto-creates new topic)

Each `exec` takes a `session_id` to control remote context:

- **No session_id** → auto-create new remote topic
- **Same session_id** → append to same topic, remote AI keeps context
- **Different session_id** → isolated independent topics

```python
# First execution -> create new session
r = toolkit_remote_agent(action="exec",
    device_id="terminal-49",
    goal="Analyze today's logs in /record/dbs/log/")

# Get session_id from r, continue same session
r2 = toolkit_remote_agent(action="exec",
    device_id="terminal-49",
    goal="Continue troubleshooting network connection",
    session_id=r["session_id"])
```

#### ③ Disconnect (remove agent)

When task completes or device goes offline, use **unregister**:

```python
toolkit_remote_agent(action="unregister",
    device_id="terminal-49")
```

After removal, the device disappears from the registry and must be re-registered for future use. This prevents long-term resource occupation and avoids calling offline devices.

### Communication Architecture

```
┌─────────────────┐         HTTP POST          ┌──────────────────┐
│  PC Host Agent   │ ─────────────────────────→  │  Device Server    │
│  (tea_agent)     │  /v1/chat/completions      │  tea_agent.server │
│                  │ ←─────────────────────────  │                  │
│  Analyze→decide  │   { result, session_id }    │  Execute→return  │
└─────────────────┘                              └──────────────────┘
```

> Remote communication uses OpenAI-compatible API; devices only need to run `python -m tea_agent.server`, no extra config.

---
## 🧪 Testing

### 🔬 API Black-Box Tests

`tests/test_server_api.py` is a **dependency-free HTTP black-box test script** covering all Server API endpoints:

```bash
python tests/test_server_api.py [--host 127.0.0.1] [--port 8282]
```

**8 test suites (30+ test points):**

| # | Suite | Coverage |
|---|-------|----------|
| ① | Health check | `/health`, `/api/sessions` connectivity |
| ② | Topic management | query → create → list validation → detail verify |
| ③ | Config & model info | `/api/config`, `/api/model`, `/v1/config`, config list |
| ④ | Multi-topic switching | 2 independent topics chat simultaneously → SSE stream → content isolation |
| ⑤ | Delete & rename | create → rename → detail verify → delete → 404 confirm |
| ⑥ | PDF export (4 combos) | `latest/final`, `latest/full`, `full_topic/final`, `full_topic/full` |
| ⑦ | Auxiliary APIs | tool list (75+), file tree, v1 sessions, todos |
| ⑧ | Error paths | 404/400/500, empty topic_id, empty body, nonexistent endpoint |

**How to run:** start Server first (`python -m tea_agent.server`), then run the test.

### 📋 Unit Tests

```bash
# Run all tests
pytest

# or
python -m pytest
```

Includes ACP protocol, DAG workflow, multi-agent, Server routing, and other functional tests.

---

## 🏗️ Project Structure

```
tea_agent/
├── agent.py               # Agent unified entry (three modes)
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
├── gui.py                 # GUI desktop entry (Tkinter)
├── gui_dialogs.py         # GUI dialogs
├── tui.py                 # Terminal TUI (Textual)
├── server/                # REST API + Web V2 (Starlette + SSE)
│   ├── server.py          # Routes + SSE
│   ├── route_handlers.py  # API route handlers
│   ├── modules/           # Hot-reloadable modules (Agent/Toolkit/Storage/Pipeline)
│   ├── static/            # HTML/CSS/JS SPA
│   └── __main__.py
├── protocol/              # ACP protocol
│   ├── acp_server.py
│   ├── acp_jsonrpc.py     # JSON-RPC 2.0
│   └── __main__.py
├── channel/               # Message channels
│   └── telegram_adapter.py # Telegram Bot
├── toolkit/               # 75+ tool modules
├── session/               # Session management (history/L1/L2/L3/JSON validation)
├── store/                 # Data storage (10 sub-modules)
├── multi_agent/           # Multi-agent system (6-phase full-stack)
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

Config file `~/.tea_agent/config.yaml`:

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
  max_context_tokens: 0   # independent config for local small models
embedding:
  provider: openai
  model: text-embedding-3-small
```

### Context Window Control

`max_context_tokens` limits the maximum context sent to the LLM:

- **0** = no limit, send all history
- **64000** (default) = for mainstream 64K~128K window models
- **32000** = for 32K window models
- **128000** = for GPT-4o / Claude large-window models

When enabled, the system estimates tokens and trims progressively by priority:
1. Delete old `[History]` entries
2. Replace old tool outputs with placeholders
3. Clear thinking content
4. Truncate long texts
5. Delete old turns (keep latest 5)

> Main model and cheap model are independently configured.

Agents can self-tune parameters at runtime via `toolkit_config`.

### 🎯 Ruff Code Style (v0.10.11+)

Built-in Ruff config in `pyproject.toml` ensures consistent code style:

```toml
[tool.ruff]
line-length = 150
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]
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

All source code passes Ruff checks with Python 3.10 modern type annotations (`str | None` instead of `Optional[str]`).

---

## 📄 License

MIT License © 2024-2026 sunkw

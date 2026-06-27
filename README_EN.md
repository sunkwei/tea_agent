# Tea Agent v0.10.0

> ⚠️ **This is an experimental "AI writing AI" project. Use at your own risk.**

> A self-evolving AI coding assistant — tool-driven, self-evolving, multi-interface

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.10.0-blue)](https://pypi.org/project/tea-agent)

Tea Agent is a **self-evolving AI coding assistant** with 70+ callable tools. It can write code, debug, search, manipulate files, control browsers, and dynamically load new tools at runtime. Supports **GUI / CLI / Web / REST API / ACP Protocol / TUI** six interface modes.

---

## ✨ Core Features

- 🧠 **Self-Evolving Engine** — Agent can modify its own code, create new tools, optimize prompts for autonomous evolution
- 🧰 **70+ Built-in Tools** — File operations, code editing, search, screenshot, OCR, package management, Git, etc.
- ⏱️ **Smart Command Timeout** — Background process monitor tracks CPU/MEM/IO, auto-extends timeout to 4x for active processes, terminates idle ones promptly
- 🖥️ **Six Interfaces** — GUI (Tkinter), CLI, Web (Starlette + SSE), REST API, ACP Protocol, TUI (Textual)
- 🌐 **Web V2 Real-time Streaming** — Single Page Application (SPA), memory search, task scheduling, session history, all in browser
- 📚 **Project Knowledge Base** — Auto-builds symbol index, call graph, impact analysis
- 🔄 **Session Persistence** — Chat history persisted, context restored on restart
- 📋 **Plan / TODO** — Built-in task planning and tracking system
- 🌐 **MCP Protocol** — Connect external MCP Servers, extend third-party tools
- 🎯 **Mode Switching** — design / develop / test / review / docs / devops six-phase workflow
- 🤖 **Multi-Agent Collaboration** — Task decomposition + parallel execution, sub-agents handle subtasks independently
- 📊 **Task Evaluation** — Auto-evaluate task quality, record success/failure experiences
- 💎 **Skill Crystallization** — Plans auto-crystallize after execution → semantically matched injection in new conversations → self-evolving skill loop

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
pip install starlette uvicorn
```

Playwright browser (optional, for JS-rendered page scraping):
```bash
playwright install chromium
```

---

## 🚀 Quick Start

```bash
# Web V2 — Single Page App, full browser experience (recommended)
python -m tea_agent.server

# GUI Desktop (Tkinter)
tea_agent

# ACP Protocol Server (VS Code integration)
python -m tea_agent.protocol --port 9090

# CLI Chat
python -m tea_agent.cli

# TUI Interface
python -m tea_agent.tui
```

---

## 💻 Interface Modes

Tea Agent offers **six interface modes**, covering all use cases from desktop to web, CLI to API.

---

### 1. GUI Desktop (`tea_agent`)

Native desktop client based on **Tkinter**, supports Windows / Linux / macOS.

**Launch:**
```bash
tea_agent                         # Entry command
python -m tea_agent.gui           # Module mode
```

**Features:**
- 🔄 Real-time streaming chat, Markdown rendering, tool call visualization
- 📋 Left sidebar session list, supports search, switch, create, delete
- 🧠 Long-term memory management panel (view/search/add/delete)
- ⏱️ Scheduled task management (scheduler CRUD)
- 📤 PDF export, chat history export
- 🌙 System tray resident, global hotkey summon
- 🎨 Theme switching + font scaling

---

### 2. CLI (`python -m tea_agent.cli`)

Lightweight terminal chat interface, suitable for remote servers, CI/CD pipelines, script integration.

**Launch:**
```bash
python -m tea_agent.cli           # Interactive mode
python -m tea_agent.cli --oneshot "Write a quick sort"  # Single-shot mode
```

**Features:**
- 📝 Interactive REPL, multi-line input (`\` for line continuation, EOF to submit)
- 🎨 Syntax highlighting + real-time tool call display
- 💾 Chat history persisted by UUID
- 📋 `/history` command, `/clear` to clear screen
- 🔧 Supports custom config: `python -m tea_agent.cli -c config_prod.yaml`
- Single-shot mode outputs directly to stdout

---

### 3. Web V2 (`python -m tea_agent.server`)

Next-gen Single Page Application (SPA), pure HTML/JS frontend + Starlette backend, all features in browser.

> **Note**: `python -m tea_agent.server` starts both REST API and Web V2 frontend.
> Visit `http://127.0.0.1:8081` in browser for the full Web interface.

**Launch:**
```bash
python -m tea_agent.server           # Default port 8081
tea-agent-api                        # PyPI entry
python -m tea_agent.server --port 8099 --host 0.0.0.0
```

**Interface Features:**

| Feature | Description |
|---------|------------|
| 💬 **Streaming Chat** | SSE real-time push, token-by-token output |
| 📋 **Session Management** | Left sidebar panel, click to switch, auto-load messages |
| 🧠 **Memory Management** | Modal panel, view/search/add/delete long-term memories |
| ⏱️ **Task Scheduler** | Scheduled task CRUD, cron / interval / daily support |
| 🔍 **Global Search** | Search chat records, memories, tasks |
| 📤 **PDF Export** | Export current session as PDF |
| 🌙 **Theme Switching** | Dark/light themes + accent color customization |
| 📎 **Image Preview** | Click to enlarge images in messages |

**Tech Architecture:**
```
Frontend: Pure HTML5 + CSS3 + Vanilla JS (no framework dependencies)
Backend: Starlette + SSE streaming
API: /v1/chat/completions (OpenAI compatible)
     /v1/sessions (CRUD)
     /v1/memory (memory management)
     /v1/tasks (task scheduler)
     /v1/search (global search)
     /v1/export/pdf (PDF export)
```

---

### 4. REST API Server (`python -m tea_agent.server`)

OpenAI-compatible HTTP API server, easy for third-party integration.

**Launch:**
```bash
tea-agent-api                        # PyPI entry
python -m tea_agent.server           # Module mode
python -m tea_agent.server --port 8081 --host 0.0.0.0
```

**API Routes:**

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (stream support) |
| `GET` | `/v1/models` | Current model info |
| `GET` | `/v1/tools` | All available tools |
| `POST` | `/v1/tools/{name}/run` | Direct tool invocation |
| `GET/POST` | `/v1/sessions` | List/create sessions |
| `GET/DELETE` | `/v1/sessions/{id}` | Get/delete session |
| `GET` | `/v1/sessions/{id}/messages` | Get session messages |
| `GET` | `/v1/config` | Get config |
| `POST` | `/v1/config/switch` | Switch config profile |
| `GET/POST/DELETE` | `/v1/memory` | Memory management |
| `GET/POST/DELETE` | `/v1/tasks` | Task scheduler |
| `GET` | `/v1/search` | Global search |
| `POST` | `/v1/export/pdf` | PDF export |
| `GET` | `/docs` | OpenAPI docs |
| `GET` | `/openapi.json` | OpenAPI Schema |

**Examples:**
```bash
# Streaming chat
curl -N -X POST http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true}'

# Non-streaming chat
curl -X POST http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'

# List sessions
curl http://127.0.0.1:8081/v1/sessions

# Search
curl "http://127.0.0.1:8081/v1/search?q=keyword"
```

---

### 5. ACP Protocol Server (`python -m tea_agent.protocol`)

Agent Communication Protocol server, providing standardized Agent-to-Agent communication, can be integrated with VS Code / Cursor IDE.

**Launch:**
```bash
python -m tea_agent.protocol --port 9090
```

**API Routes:**

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/agents` | Discover all available Agents |
| `GET` | `/v1/agents/tea-agent` | Tea Agent details (with tool list) |
| `POST` | `/v1/agents/tea-agent/chat` | Send message (stream support) |
| `GET/POST` | `/v1/sessions` | List/create sessions |
| `GET/DELETE` | `/v1/sessions/{id}` | Get/delete session |
| `GET` | `/v1/sessions/{id}/messages` | Get session messages |

**Features:**
- 🧰 **Tool Discovery** — Clients can query full tool list and JSON Schema
- 📡 **SSE Streaming** — Real-time push, token-by-token output
- 🧵 **Session Management** — Multi-session isolation, history retrieval
- 🔗 **IDE Integration** — Standard ACP protocol, compatible with any ACP client

---

### 6. Web V1 Legacy (`tea-agent-web`)

Older Web interface based on Starlette + SSE, with tool visualization cards.

```bash
tea-agent-web
python -m tea_agent.web
```

> Web V2 (`python -m tea_agent.gui2`) is recommended for more comprehensive features.

---

## 🧠 Long-Term Memory System

Tea Agent's memory system mimics human memory: **priority layering**, **relevance retrieval**, **natural decay**, **dedup & merge**. It's backed by SQLite persistence + embedding semantic vectors, managed by `MemoryManager`.

---

### 1. Memory Storage Structure

Each memory record contains these core fields:

| Field | Type | Description |
|-------|------|-------------|
| `content` | TEXT | Memory content (concise summary) |
| `priority` | INT (0-3) | Priority: `0=CRITICAL` / `1=HIGH` / `2=MEDIUM` / `3=LOW` |
| `importance` | INT (1-5) | Importance: 5=critical (ignoring causes problems); 1=trivial |
| `category` | TEXT | Category: `instruction` / `preference` / `fact` / `reminder` / `general` |
| `tags` | TEXT | Comma-separated tags for fast matching |
| `content_hash` | TEXT | First 16 chars of SHA256, fast dedup fingerprint |
| `embedding` | BLOB | `numpy.float32` vector for cosine similarity search |
| `expires_at` | DATETIME | Expiration time, NULL=never expires |
| `pinned` | INT | Whether pinned (exempt from age decay) |
| `created_at` | DATETIME | Creation time (used for age decay calculation) |

---

### 2. Selection Algorithm

At the start of each conversation, `MemoryManager.select_memories()` selects the most relevant **≤30** memories to inject:

```
score = relevance(keyword match) × importance(importance/5) × age_factor × priority_factor

age_factor: 1 day=1.0, 7 days=0.9, 30 days=0.7, 90 days=0.5, >90 days=0.3
priority_factor: (4 - priority) / 4
```

**Tiered guarantee strategy** (ensuring not all CRITICAL):

```
1. CRITICAL first (cap 10, FIFO latest)
2. Non-CRITICAL sorted by score
3. Tiered quotas:
   - HIGH   ≥ 3
   - MEDIUM ≥ 2
   - LOW    ≥ 1
4. Remaining slots: free competition (highest score first)
5. Selected memories update last_accessed_at
```

---

### 3. Age Decay

Simulates Ebbinghaus forgetting curve. Automatically runs `degrade_by_age()` before selection. **pinned=true** memories are exempt:

| Original Priority | Decay Condition | Degraded To |
|------------------|----------------|-------------|
| CRITICAL | Created > 30 days | HIGH |
| HIGH | Created > 60 days | MEDIUM |
| MEDIUM | Created > 90 days | LOW |

---

### 4. LLM Priority Fine-Tuning

`MemoryManager.llm_adjust_priorities()` uses a cheap LLM to evaluate recent conversation topics and fine-tune memory priorities:

```
Input: Recent conversation topic summary (≤2000 chars) + active memories (≤100, each ≤80 chars preview)
Rules:
  - Only ±1 level adjustment (no skipping)
  - Max 3 adjustments per run
  - Upgrade resets created_at (re-starts decay timer)
  - Output JSON array only, no extra text
```

---

### 5. Memory Extraction

After conversation ends, `MemoryManager` auto-extracts memories from user messages via LLM:

```
Extraction categories:
  instruction → user's explicit "remember" rules → priority=0 (CRITICAL)
  preference  → user's habits/preferences          → priority=1 (HIGH)
  reminder    → time-sensitive reminders (with expires_at) → priority=1 (HIGH)
  fact        → technical facts/architecture decisions → priority=2 (MEDIUM)
  general     → other reference info               → priority=3 (LOW)

Fault-tolerant parsing:
  1. Direct JSON.parse
  2. Extract markdown ```json code blocks
  3. JSON array regex match
  4. Object type → extract array from common keys (memories/items/results/data)
```

---

### 6. Dedup & Merge

Before writing extracted results, `ingest_extracted()` runs dedup & merge pipeline:

```
Each new memory:
  1. jieba tokenize → keyword Jaccard similarity calculation
  2. Same category weighted +10%
  3. Similarity ≥ 0.3 → merge into existing memory:
     - content: keep longer or concatenate
     - priority: take smaller value (more critical)
     - importance: take higher value
     - tags: union, dedup
     - expires_at: keep earlier expiration
  4. < 0.3 → insert new record
```

**Batch dedup** (`detect_duplicates` / `auto_dedup`): scans all active memories via embedding cosine similarity (threshold 0.92), merges and promotes near-duplicate pairs.

---

### 7. CRITICAL FIFO Eviction

CRITICAL memory cap is 15. When exceeded, the oldest is soft-deleted (FIFO), preventing instruction memory from infinite growth.

---

### 8. Reflection & Summarization

`reflect_and_summarize()` clusters recent memories by category, generates summaries, and archives:

```
Category clustering (instruction/preference/fact/reminder/general)
  → Each category ≥ 2 → keyword frequency generates summary
  → Summary stored as CRITICAL/importance=5
  → Original memories importance -1 (downgrade)
```

---

### Formatting Injection

Selected memories are formatted by priority and injected into the system prompt area:

```python
def _prefix_for(memory):
    if priority == CRITICAL:  return "!!! MUST FOLLOW:"
    if category == "reminder": return "⏰ Reminder:"
    if category == "preference": return "💡 Preference:"
    if category == "fact":      return "📌 Fact:"
    return "📎"
```

> Agent can manually manage memories via `toolkit_memory`. See [`docs/TOOLS.md`](docs/TOOLS.md)

---

## 📜 Four-Level History Compression (L0 → L3 → L2 → L1)

Tea Agent uses **four-level layering** to build the context sent to the LLM, maximizing information density within a limited token window. All levels are assembled by `build_api_messages()` in `session/_history_builder.py`.

```
┌─────────────────────────────────────────────────┐
│  Level 0: System Layer                           │
│  ├─ System prompt                                │
│  ├─ Skill recommendation (SkillRegistry matching)│
│  ├─ Pending task recovery (TODO/Plan)            │
│  └─ Long-term memory injection (MemoryManager)   │
├─────────────────────────────────────────────────┤
│  Level 3: Summary Layer (LLM-generated)          │
│  └─ Generated when L2 overflows: key conclusions │
├─────────────────────────────────────────────────┤
│  Level 2: History Pairs (SQLite persisted)       │
│  └─ user + AI final msg pairs, relevance-filtered│
├─────────────────────────────────────────────────┤
│  Level 1: Latest Conversation (current session)  │
│  ├─ Compressed tool chain (intermediate calls→summary)│
│  ├─ Old tool output → placeholder                │
│  └─ Tool output truncation (head+tail, aligned) │
└─────────────────────────────────────────────────┘
```

---

### Level 0: System Layer

```python
# L0 assembly order in build_api_messages()
result = []

# 1. System prompt
result.append({"role": "system", "content": system_prompt})

# 2. Pending task recovery (toolkit_task_resume)
resume_info = toolkit_task_resume(action="check")
if resume_info["has_pending"]:
    result.append({"role": "user", "content": format_resume(resume_info)})

# 3. Long-term memory injection
if context._injected_memories_text:
    result.append({"role": "user", "content": context._injected_memories_text})
```

---

### Level 3 (L3) — Semantic Summary

`SummaryStore` manages two types of L3 summaries:

| Type | Storage | Generation Trigger | Content |
|------|---------|-------------------|---------|
| **Semantic** | `topics.semantic_summary` | L2 overflow (50→20 trim) | Background / changes / decisions / fixes / constraints / preferences / todos |
| **Tool Chain** | `topics.tool_chain_summary` | Background async thread | Recent tool call chain review |

**L2→L3 Generation** (`generate_l2_to_l3_summary`):

```
Trigger: push_to_level2() returns should_summarize=True
         (L2 count ≥ 50 → oldest 30 overflow)

Flow:
  1. Take overflow 30 L2 entries (user + thinking + assistant)
  2. Merge existing L3 summary (if any)
  3. Generate with cheap model (temperature=0.3, max_tokens=4096)
  4. Store to topics.semantic_summary
  5. Trim L2 to latest 20 entries
```

**L3 Injection Format:**

```
[System Memory — Valid information and rules to follow]

##### Long-term Background/Preferences/Key Conclusions
{semantic_summary}

---

##### Historical Tool Chain Review
{tool_chain_summary}
```

---

### Level 2 (L2) — History Pairs

L2 is a **fixed-size ring buffer** stored in SQLite `topics.level2_json` column, capacity 50.

**Entry Structure:**

```json
{
  "user": "Original user message",
  "assistant": "AI's final reply (without tool intermediate steps)",
  "thinking": "Assistant content + reasoning from rounds",
  "files": ["Involved file paths (optional)"]
}
```

**Write Flow** (`push_to_level2`):

```python
def push_to_level2(topic_id, user_msg, ai_msg, files, rounds):
    thinking = extract_thinking_from_rounds(rounds)
    entry = {"user": user_msg, "assistant": ai_msg, "thinking": thinking, "files": files}
    level2.append(entry)

    overflow = []
    should_summarize = False
    if len(level2) >= 50:
        overflow = level2[:30]
        level2 = level2[-20:]
        should_summarize = True

    return len(level2), overflow, should_summarize
```

**Relevance Filtering** (`filter_level2_by_relevance`):

```
Jaccard similarity with current user message keywords:
  - Extract 2-char Chinese + 3-letter English keywords
  - Jaccard: |intersection| / |union|
  - File path bonus (overlap ≥ 1 → min(score, 0.4 + count × 0.1))

Filter rules:
  ≥ 0.15   →  Full pair (injected as [History Record])
  ≥ 0.05   →  Summary snippet only
  < 0.05   →  Not injected
  All<0.05 →  Fallback: highest-scoring full pair
```

---

### Level 1 (L1) — Latest Conversation

L1 is the **current session's raw messages** (`context.messages`), compressed through multiple layers.

#### First Line: Real-time Tool Output Truncation

Each tool call result is truncated immediately:

```python
max_tool_output = 128 * 1024  # 128KB
if len(result_bytes) > max_tool_output:
    head = result_bytes[:max_tool_output // 2]
    tail = result_bytes[-max_tool_output // 2:]
    result_str = f"{head.decode()}\n\n... [Truncated] ...\n\n{tail.decode()}"
```

#### Second Line: Old Tool Output Placeholders

`_find_prune_cutoff()` finds boundary of last 3 user messages:

```
Tool messages older than 3 rounds → "[Tool result omitted: N chars]"
Within 3 rounds → Fully preserved
```

#### Third Line: Progressive Token Trimming

When `max_context_tokens > 0`, `_progressive_trim()` triggers 5-level trimming:

| Strategy | Operation | Description |
|----------|-----------|-------------|
| 1 | Delete `[History Record]` L2 entries | Oldest first |
| 2 | Replace old tool output with placeholders | `[Omitted: N chars]` |
| 3 | Clear reasoning_content | Free thinking tokens |
| 4 | Truncate long text | Cap at 4096 chars |
| 5 | Delete old L1 rounds | Keep last 5 user messages |
| Last resort | Truncate last message | Keep first 1/3 |

---

### Assembly Flow

```
build_api_messages(context, system_prompt) Full Flow:

1. Level 0: System + TODO recovery + memory injection
2. Level 3: Semantic + tool chain summary
3. Level 2: Relevance filter → [History Record] pairs
4. Level 1: Boundary calc → tool placeholders → message traversal
5. Progressive trim: estimate > 80% budget → _progressive_trim()
6. JSON integrity check + orphan tool message removal
```

### Token Estimation

Heuristic algorithm (no tiktoken):
- English: ~4 chars = 1 token
- Chinese: ~1.5 chars = 1 token
- Image: fixed ~85 tokens
- Message overhead: +4 tokens each

### Async Summaries

After each conversation, `do_async_summaries()` runs in background:
1. **Title summary**: One-line topic title via cheap model
2. **L2→L3 summary**: Only on L2 overflow

---

## 🔄 Self-Evolution Engine

Five layers: Hot-swappable tools → Safe self-modification → Prompt evolution → Experience solidification → Background thread.

---

### 1. Hot-Swappable Tools: `toolkit_save` / `toolkit_reload`

Agent can create/modify tools at runtime, **taking effect immediately**.

```
Agent needs new capability
  ├─ 1. Write Python function
  ├─ 2. Define OpenAI function schema
  ├─ 3. toolkit_save(name, meta, pycode)
  │     ├─ Store to toolkit/{name}.py
  │     ├─ Auto version: v1.0.0 → v1.1.0
  │     ├─ History in .versions/
  │     └─ Auto-generate SKILL.md
  ├─ 4. toolkit_reload() → dynamic import + register
  └─ 5. New tool immediately usable
```

**Version Management:**

| Feature | Description |
|---------|-------------|
| Auto versioning | Each save increments `v1.0.0 → v1.0.1 → v1.1.0` |
| Safe rollback | `toolkit_rollback(name, version)` to any historical version |
| Version list | `toolkit_list_versions(name)` shows all versions |
| SKILL.md | Auto-generated docs with param tables + examples |

---

### 2. Five-Layer Safe Self-Modification: `toolkit_self_evolve`

```
Layer 0: Git snapshot (git add + commit)
Layer 1: Timestamp .bak backup file
Layer 1.5: Python syntax strict check (immediate rollback on fail)
Layer 2: py_compile verification (auto rollback on fail)
Layer 2.5: LSP smart check (impact analysis + lint + signature diff)
Layer 3: pytest verification (git reset --hard on fail)
```

---

### 3. Prompt Evolution: `toolkit_prompt_evolve`

Agent self-optimizes system prompt with multi-version support:

```
Operations:
  list     → View all version history
  current  → View active version
  evolve   → Reflection + memory → LLM generates new version → set active
  rollback → Revert to specified version
  set      → Manually set new version
```

---

### 4. Experience Solidification: `toolkit_experience_solidify`

```
action='auto':
  analyze → analyze execution
  ├─ success → solidify → skill library (toolkit_dynamic_skill)
  └─ failure → lesson   → experience library (toolkit_evolution_exp)
```

---

### 5. Background Evolution Thread: `toolkit_self_evolve_thread`

Runs hourly: tool usage analysis → docs/TOOLS.md sync → skill pattern organization.

---

### Self-Evolution Overview

| Capability | Tool | Safety |
|-----------|------|--------|
| Create tools | `toolkit_save` + `toolkit_reload` | Version rollback |
| Modify source | `toolkit_self_evolve` | 5-layer safe |
| Optimize prompts | `toolkit_prompt_evolve` | Version rollback |
| Solidify experience | `toolkit_experience_solidify` | Category tags |
| Background | `toolkit_self_evolve_thread` | Hourly |
| Code intelligence | `toolkit_lsp` | Read-only |

---

## 🧰 Tool Overview (70+)

| Category | Tools |
|----------|-------|
| 📁 File | `toolkit_file`, `toolkit_save_file`, `toolkit_explr` |
| ✏️ Code Edit | `toolkit_edit`, `toolkit_diff_edit`, `toolkit_diff`, `toolkit_self_evolve`, `toolkit_clean_comments`, `toolkit_format_code` |
| 🔍 Search | `toolkit_search`, `toolkit_lsp`, `toolkit_query_chat_history` |
| 📸 Screenshot/OCR | `toolkit_screenshot`, `toolkit_ocr`, `toolkit_screen_read` |
| 🖱️ Control | `toolkit_input`, `toolkit_browser_tab`, `toolkit_js_fetch` |
| 📦 Package | `toolkit_pkg`, `toolkit_build`, `toolkit_read_pyproject` |
| 🧪 Test | `toolkit_run_tests`, `toolkit_test_gui` |
| 🗓️ Utilities | `toolkit_lunar`, `toolkit_weather_my`, `toolkit_gettime`, `toolkit_date_diff` |
| 🔧 System | `toolkit_exec`, `toolkit_config`, `toolkit_os_info`, `toolkit_sudo_gui` |
| 🧠 Memory/KB | `toolkit_memory`, `toolkit_kb`, `toolkit_reflection`, `toolkit_proactive` |
| 🤖 Multi-Agent | `toolkit_parallel_subtasks`, `toolkit_dynamic_skill`, `toolkit_experience_solidify` |
| 📋 Plan/Task | `toolkit_plan`, `toolkit_todo`, `toolkit_scheduler`, `toolkit_task_resume` |
| 🔌 MCP | `toolkit_mcp` |
| 🌐 Web/GUI | `toolkit_browser_tab`, `toolkit_dump_topic`, `toolkit_export_last_pdf`, `toolkit_notify` |
| 📤 Export | `toolkit_dump_topic`, `toolkit_export_last_pdf` |
| 🧬 Self-Evolve | `toolkit_self_evolve`, `toolkit_self_evolve_thread`, `toolkit_prompt_evolve`, `toolkit_evolution_exp` |
| 🛠️ Others | `toolkit_question`, `toolkit_stream_save`, `toolkit_set_topic_title`, `toolkit_self_report`, `toolkit_comment`, `toolkit_toggle_reasoning`, `toolkit_get_config_path`, `toolkit_get_models`, `toolkit_list_provider_models`, `toolkit_ip_location_my`, `toolkit_custom_commands`, `toolkit_scheduler_storage`, `toolkit_mode` |

> Full tool list at [`docs/TOOLS.md`](docs/TOOLS.md) (auto-updated hourly)

---

## 🤖 Multi-Agent Collaboration

```python
from tea_agent.multi_agent import Dispatcher, LiteAgent

# One-step: decompose + execute
dispatcher = Dispatcher()
result = dispatcher.dispatch("Refactor project with type annotations")
print(result["summary"])

# Visualize execution plan (no execution)
print(dispatcher.visualize("Add type annotations to gui.py"))

# Standalone LiteAgent
agent = LiteAgent()
result = agent.execute_sync("Read README.md and summarize")
```

### Architecture

```
Dispatcher.dispatch(goal)
  │
  ├─ _identify_pattern()     → Identify task pattern
  ├─ _generate_tasks()       → Generate SubTask list
  ├─ _topological_sort()     → Topological sort (layered)
  │
  ├─ _execute_layers()       → Execute layer by layer
  │   ├─ Layer 1: [task_1] ─── LiteAgent.execute_sync()
  │   │              ↓ result → accumulated_context
  │   ├─ Layer 2: [task_2] ─── LiteAgent.execute_sync()
  │   │              ↓
  │   └─ ...
  │
  └─ _merge_results()        → Merge results
```

---

## 🏗️ Project Structure

```
tea_agent/
├── gui.py                 # GUI Desktop (Tkinter)
├── gui2/                  # Web V2 (SPA + Bottle)
│   ├── server.py          # Bottle static server
│   └── frontend/          # HTML/CSS/JS SPA
│       └── index.html     # All UI logic (no framework)
├── web/                   # Web V1 (Starlette + SSE)
│   ├── server.py          # SSE streaming server
│   └── static/            # Frontend assets
├── server/                # REST API Server (OpenAI compat)
│   ├── server.py          # Starlette routes + SSE
│   └── __main__.py        # python -m tea_agent.server
├── protocol/              # ACP Protocol Server
│   ├── acp_server.py      # ACP implementation
│   └── __main__.py        # python -m tea_agent.protocol
├── cli.py                 # CLI
├── tui.py                 # TUI (Textual)
├── agent.py               # Core engine
├── config.py              # Config management
├── memory.py              # Long-term memory
├── prompt_manager.py      # Prompt version management
├── toolkit/               # 70+ tool modules
├── session/               # Session (history compression/trim)
├── multi_agent/           # Multi-agent collaboration
├── lsp/                   # LSP code intelligence
├── store/                 # Data storage (10 submodules)
├── evaluation/            # Task evaluation
├── skills/                # Skill crystallization
├── sdk/                   # Python SDK (external)
└── _gui/                  # GUI components (12 modules)
```

---

## 🔧 Configuration

Config file `~/.tea_agent/config.yaml`:

```yaml
main_model:
  api_key: "sk-xxx"
  api_url: "https://api.openai.com/v1"
  model_name: "gpt-4o"
  max_context_tokens: 0   # 0=unlimited, >0 enables progressive token trim
cheap_model:
  api_key: ""
  api_url: ""
  model_name: ""
  max_context_tokens: 0   # Independent config for local small models
embedding:
  provider: openai
  model: text-embedding-3-small
```

### Context Window Control

`max_context_tokens` limits max context tokens sent to the LLM:

- **0** = Unlimited, send full history
- **64000** (default) = Suitable for 64K~128K window models
- **32000** = Suitable for 32K window models
- **128000** = Suitable for GPT-4o / Claude large window models

When enabled, the system auto-estimates tokens and progressively trims when over budget:
1. Delete old `[History Record]` entries
2. Replace old tool output with placeholders
3. Clear thinking content
4. Truncate long text
5. Delete old rounds (keep last 5)

> Main and cheap models are configured independently. Agent can self-tune via `toolkit_config` at runtime.

---

## 📄 License

MIT License © 2024-2026 sunkw

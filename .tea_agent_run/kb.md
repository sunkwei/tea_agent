# TeaAgent Project Knowledge Base

## Meta
- **Version**: 0.9.2
- **Last Updated**: 2026-05-20
- **Description**: 自主进化型智能助手

## Structure
- `tea_agent/` — 127 Python files (incl. 46 tools)
- `tea_agent/toolkit/` — 46 toolkit modules

## Key Modules
| Module | Role |
|--------|------|
| `agent_core.py` | GUI/CLI shared base (restart, session mgmt, chat pipeline) |
| `basesession.py` | Session base: 3-level history loading |
| `onlinesession.py` | OnlineToolSession: core orchestration |
| `config.py` | YAML config loading |
| `store.py` | SQLite persistence |
| `memory.py` | MemoryManager: select/score/dedup |
| `reflection.py` | ReflectionManager: meta-cognition |
| `prompt_manager.py` | SystemPromptManager: dynamic prompt evolution |
| `tlk.py` | Toolkit loader/validator/saver |
| `gui.py` | Tkinter GUI (uses `self._cfg`) |
| `main_db_gui.py` | GUI entry point |

## Config Attribute
- Config stored as `self._cfg` (NOT `self.config`)
- Access pattern: `self._cfg.main_model`, `self._cfg.paths`, etc.

## Recent Fixes (v0.9.2)
- `agent_core.py:372`: `self.config` → `self._cfg` (AttributeError fix in `_post_chat_pipeline`)
- Version sync: `__init__.py` aligned with `pyproject.toml` at 0.9.2

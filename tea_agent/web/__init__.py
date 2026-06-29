"""
Tea Agent Web (deprecated as standalone — merged into server).

This module is kept for backward compatibility.
All functionality now lives in tea_agent.server.
"""

from tea_agent.server import create_app, run_server, main

__all__ = ["create_app", "run_server", "main"]

if __name__ == "__main__":
    main()

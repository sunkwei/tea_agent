#!/usr/bin/env python3
"""
Launcher script for Console Tetris Game.
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    try:
        from tetris_ansi import main
        main()
    except ImportError as e:
        print(f"Error: Could not import tetris_ansi module: {e}")
        print("Make sure tetris_ansi.py is in the same directory.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGame terminated by user.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
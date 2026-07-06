#!/usr/bin/env python3
"""
Launcher script for Console Tetris Game.

Controls:
  ← →  Move   ↑ Rotate   ↓ Soft drop   Space Hard drop
  P Pause   A Strategy AI   M Model AI   Q Quit
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    print("🎮 Tetris with AI!  Press A = Strategy AI, M = Trained CNN Model, Q = Quit")
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

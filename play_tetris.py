#!/usr/bin/env python3
"""
Play Console Tetris Game.
Run this script to start the game.
"""

import sys
import os

# Add demo/tetris to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'demo', 'tetris'))

if __name__ == '__main__':
    try:
        from tetris_ansi import main
        main()
    except ImportError as e:
        print(f"Error: Could not import tetris_ansi module: {e}")
        print("Make sure the demo/tetris directory exists.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nGame terminated by user.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
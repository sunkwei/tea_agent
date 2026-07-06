#!/usr/bin/env python3
"""
Simple test for Tetris game logic (non-interactive).
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tetris_ansi import BOARD_HEIGHT, BOARD_WIDTH, CELL_EMPTY, CELL_FILLED, TetrisGame


def test_game_logic():
    """Test basic game logic without terminal interaction."""
    print("Testing Tetris game logic...")

    # Create game instance
    game = TetrisGame()

    # Test 1: Board initialization
    print("1. Testing board initialization...")
    for r in range(BOARD_HEIGHT):
        for c in range(BOARD_WIDTH):
            assert game.board[r][c] == CELL_EMPTY, f"Board cell ({r},{c}) should be empty"
    print("   [OK] Board initialized correctly")

    # Test 2: Piece generation
    print("2. Testing piece generation...")
    assert game.current_piece is not None, "Current piece should be generated"
    assert game.next_piece is not None, "Next piece should be generated"
    assert game.current_piece['type'] in ['I', 'O', 'T', 'S', 'Z', 'J', 'L'], "Invalid piece type"
    print(f"   [OK] Current piece: {game.current_piece['type']}")
    print(f"   [OK] Next piece: {game.next_piece['type']}")

    # Test 3: Piece movement
    print("3. Testing piece movement...")
    initial_row = game.current_piece['row']
    initial_col = game.current_piece['col']

    # Test move down
    if game._move_piece(1, 0):
        assert game.current_piece['row'] == initial_row + 1, "Piece should move down"
        print("   [OK] Move down works")
    else:
        print("   [WARN] Move down blocked (piece at bottom)")

    # Test move left
    if game._move_piece(0, -1):
        assert game.current_piece['col'] == initial_col - 1, "Piece should move left"
        print("   [OK] Move left works")
    else:
        print("   [WARN] Move left blocked (piece at left edge)")

    # Test move right
    if game._move_piece(0, 1):
        assert game.current_piece['col'] == initial_col, "Piece should move right"
        print("   [OK] Move right works")
    else:
        print("   [WARN] Move right blocked (piece at right edge)")

    # Test 4: Rotation
    print("4. Testing piece rotation...")
    initial_rotation = game.current_piece['rotation']
    game._rotate_piece()
    # Rotation may or may not change depending on piece type and position
    print(f"   [OK] Rotation attempted (initial: {initial_rotation}, current: {game.current_piece['rotation']})")

    # Test 5: Hard drop
    print("5. Testing hard drop...")
    game._hard_drop()
    # After hard drop, piece should be locked
    print("   [OK] Hard drop executed")

    # Test 6: Line clearing (simulate)
    print("6. Testing line clearing...")
    # Fill a line
    for c in range(BOARD_WIDTH):
        game.board[BOARD_HEIGHT - 1][c] = CELL_FILLED
    lines_before = game.lines_cleared
    game._clear_lines()
    assert game.lines_cleared == lines_before + 1, "One line should be cleared"
    print("   [OK] Line clearing works")

    print("\nAll tests passed! [OK]")
    print("\nTo play the game, run: python tetris_ansi.py")

if __name__ == '__main__':
    try:
        test_game_logic()
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

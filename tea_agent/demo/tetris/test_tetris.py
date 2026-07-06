#!/usr/bin/env python3
"""
Simple test script for Tetris game logic.
"""

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tetris_ansi import TETROMINOES, TetrisGame


def test_game_initialization():
    """Test game initialization."""
    print("Testing game initialization...")
    game = TetrisGame()

    # Check board dimensions
    assert len(game.board) == 20, f"Expected 20 rows, got {len(game.board)}"
    assert len(game.board[0]) == 10, f"Expected 10 columns, got {len(game.board[0])}"

    # Check pieces
    assert game.current_piece is not None, "Current piece should not be None"
    assert game.next_piece is not None, "Next piece should not be None"

    # Check piece types
    assert game.current_piece['type'] in TETROMINOES, f"Invalid piece type: {game.current_piece['type']}"
    assert game.next_piece['type'] in TETROMINOES, f"Invalid piece type: {game.next_piece['type']}"

    print("[PASS] Game initialization passed")

def test_piece_movement():
    """Test piece movement."""
    print("Testing piece movement...")
    game = TetrisGame()

    # Save initial position
    initial_row = game.current_piece['row']
    initial_col = game.current_piece['col']

    # Test moving left
    if game._move_piece(0, -1):
        assert game.current_piece['col'] == initial_col - 1, "Piece should move left"

    # Test moving right
    if game._move_piece(0, 1):
        assert game.current_piece['col'] == initial_col, "Piece should move right"

    # Test moving down
    if game._move_piece(1, 0):
        assert game.current_piece['row'] == initial_row + 1, "Piece should move down"

    print("[PASS] Piece movement passed")

def test_piece_rotation():
    """Test piece rotation."""
    print("Testing piece rotation...")
    game = TetrisGame()

    initial_rotation = game.current_piece['rotation']
    rotations = game.current_piece['rotations']

    # Test rotation
    game._rotate_piece()

    # Check that rotation changed (if there are multiple rotations)
    if len(rotations) > 1:
        expected_rotation = (initial_rotation + 1) % len(rotations)
        assert game.current_piece['rotation'] == expected_rotation, \
            f"Rotation should be {expected_rotation}, got {game.current_piece['rotation']}"

    print("[PASS] Piece rotation passed")

def test_collision_detection():
    """Test collision detection."""
    print("Testing collision detection...")
    game = TetrisGame()

    # Test valid position
    assert game._is_valid_position(game.current_piece), "Current position should be valid"

    # Test invalid position (out of bounds)
    test_piece = game.current_piece.copy()
    test_piece['row'] = -5
    assert not game._is_valid_position(test_piece), "Position above board should be invalid"

    test_piece['row'] = 25
    assert not game._is_valid_position(test_piece), "Position below board should be invalid"

    print("[PASS] Collision detection passed")

def test_line_clearing():
    """Test line clearing logic."""
    print("Testing line clearing...")
    game = TetrisGame()

    # Fill a line manually
    for c in range(10):
        game.board[19][c] = 1  # Fill bottom row

    # Clear lines
    game._clear_lines()

    # Check that line was cleared
    assert all(cell == 0 for cell in game.board[19]), "Bottom row should be cleared"
    assert game.lines_cleared == 1, f"Should have cleared 1 line, got {game.lines_cleared}"
    assert game.score == 100, f"Score should be 100, got {game.score}"

    print("[PASS] Line clearing passed")

def run_all_tests():
    """Run all tests."""
    print("Running Tetris game tests...\n")

    try:
        test_game_initialization()
        test_piece_movement()
        test_piece_rotation()
        test_collision_detection()
        test_line_clearing()

        print("\nAll tests passed!")
        return True
    except AssertionError as e:
        print(f"\nTest failed: {e}")
        return False
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)

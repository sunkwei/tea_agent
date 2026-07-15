"""Tetris ANSI 单元测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tetris_ansi import Tetris, Piece, SHAPES, SHAPE_COLORS, HIDDEN


class TestPiece:
    """方块测试"""

    def test_i_piece_cells(self):
        p = Piece("I", rotation=0, x=3, y=0)
        cells = p.cells
        assert len(cells) == 4
        assert (3, 0) in cells

    def test_o_piece_rotation(self):
        """O 方块只有一个旋转状态"""
        assert len(SHAPES["O"]) == 1

    def test_i_piece_rotation(self):
        """I 方块有两个旋转状态"""
        assert len(SHAPES["I"]) == 2

    def test_all_shapes_have_color(self):
        for name in SHAPES:
            assert name in SHAPE_COLORS, f"{name} missing color"
            assert 1 <= SHAPE_COLORS[name] <= 7


class TestTetris:
    """游戏核心测试"""

    def test_init(self):
        game = Tetris()
        assert game.score == 0
        assert game.level == 1
        assert game.lines == 0
        assert game.running
        assert game.board is not None
        assert len(game.board) == 22  # HEIGHT + HIDDEN

    def test_spawn(self):
        game = Tetris()
        ok = game.spawn()
        assert ok
        assert game.piece is not None
        assert game.next_piece is not None

    def test_move_left(self):
        game = Tetris()
        game.spawn()
        piece = game.piece
        ok = game.move(-1, 0)
        # 左移可能被墙阻挡，只验证不崩溃
        if ok:
            assert game.piece.x < piece.x

    def test_move_right(self):
        game = Tetris()
        game.spawn()
        piece = game.piece
        ok = game.move(1, 0)
        if ok:
            assert game.piece.x > piece.x

    def test_move_down(self):
        game = Tetris()
        game.spawn()
        piece = game.piece
        ok = game.move(0, 1)
        if ok:
            assert game.piece.y > piece.y

    def test_rotate(self):
        game = Tetris()
        game.spawn()
        # 旋转不应崩溃
        for _ in range(10):
            game.rotate()

    def test_hard_drop(self):
        game = Tetris()
        game.spawn()
        old_y = game.piece.y
        game.hard_drop()
        # 硬降后方块锁定并生成新方块（或游戏结束）
        board_used = any(cell != 0 for row in game.board[HIDDEN:] for cell in row)
        assert board_used or not game.running  # 棋盘有方块或游戏结束

    def test_score_system(self):
        game = Tetris()
        # 手动填满一行（最底行）
        for x in range(10):
            game.board[-1][x] = 1
        game.board[-2] = [0] * 10  # 确保只消一行
        game._clear_lines()
        assert game.lines == 1
        assert game.score == 100  # 1行 × level 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

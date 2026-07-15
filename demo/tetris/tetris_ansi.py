#!/usr/bin/env python3
"""
🎮 Tetris — ANSI 终端俄罗斯方块

纯终端运行，零外部依赖。支持：
  - 7 种标准方块 (I/O/T/S/Z/J/L)
  - 旋转、移动、硬降、软降
  - 分数系统 + 等级加速
  - 下一个方块预览
  - 彩色 ANSI 渲染

操作:
  ← →   移动
  ↑     旋转
  ↓     软降
  空格   硬降 (直接落底)
  p    暂停/继续
  q    退出
"""

import os
import sys
import random
import threading
import time
from dataclasses import dataclass, field

# ── 平台适配 ──
IS_WIN = sys.platform == "win32"
if IS_WIN:
    import msvcrt
else:
    import termios
    import select
    import tty

# ── 常量 ──
WIDTH = 10
HEIGHT = 20
HIDDEN = 2  # 顶部隐藏行数

# ANSI 颜色
COLORS = {
    0: "\033[40m",     # 空 — 黑底
    1: "\033[44m",     # I — 青色
    2: "\033[43m",     # O — 黄色
    3: "\033[45m",     # T — 紫色
    4: "\033[42m",     # S — 绿色
    5: "\033[41m",     # Z — 红色
    6: "\033[46m",     # J — 蓝色
    7: "\033[47m",     # L — 橙色(白色替代)
}
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

# 方块形状 (每个方块 4 个旋转状态)
SHAPES = {
    "I": [[(0,0),(1,0),(2,0),(3,0)], [(1,0),(1,1),(1,2),(1,3)]],
    "O": [[(0,0),(1,0),(0,1),(1,1)]],
    "T": [[(0,0),(1,0),(2,0),(1,1)], [(0,0),(0,1),(0,2),(1,1)],
          [(1,0),(0,1),(1,1),(2,1)], [(0,0),(1,0),(2,0),(1,-1)]],
    "S": [[(1,0),(2,0),(0,1),(1,1)], [(0,0),(0,1),(1,1),(1,2)]],
    "Z": [[(0,0),(1,0),(1,1),(2,1)], [(1,0),(0,1),(1,1),(0,2)]],
    "J": [[(0,0),(0,1),(1,1),(2,1)], [(0,0),(1,0),(0,1),(0,2)],
          [(0,0),(1,0),(2,0),(2,-1)], [(1,0),(1,1),(0,2),(1,2)]],
    "L": [[(2,0),(0,1),(1,1),(2,1)], [(0,0),(0,1),(0,2),(1,2)],
          [(0,0),(1,0),(2,0),(0,1)], [(0,0),(1,0),(1,1),(1,2)]],
}

SHAPE_COLORS = {"I":1,"O":2,"T":3,"S":4,"Z":5,"J":6,"L":7}

# 分数表
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}  # 消行数→分数


@dataclass
class Piece:
    """当前方块"""
    shape_name: str
    rotation: int = 0
    x: int = WIDTH // 2 - 1
    y: int = 0
    color: int = 0

    def __post_init__(self):
        if not self.color:
            self.color = SHAPE_COLORS[self.shape_name]

    @property
    def cells(self) -> list:
        """返回方块占据的 (x, y) 坐标列表"""
        rotations = SHAPES[self.shape_name]
        rot = rotations[self.rotation % len(rotations)]
        return [(self.x + dx, self.y + dy) for dx, dy in rot]


class Tetris:
    """俄罗斯方块游戏"""

    def __init__(self):
        self.board = [[0] * WIDTH for _ in range(HEIGHT + HIDDEN)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.piece: Piece | None = None
        self.next_piece: Piece | None = None
        self.running = True
        self.paused = False
        self.drop_interval = 0.8
        self._last_drop = time.time()
        self._lock = threading.Lock()

    # ── 方块操作 ──

    def spawn(self) -> bool:
        """生成新方块，返回 False 表示游戏结束"""
        name = random.choice(list(SHAPES.keys()))
        piece = Piece(shape_name=name)
        if self._collides(piece):
            return False
        self.piece = self.next_piece or piece
        self.next_piece = Piece(shape_name=random.choice(list(SHAPES.keys())))
        return True

    def move(self, dx: int, dy: int) -> bool:
        """移动方块，返回是否成功"""
        if not self.piece:
            return False
        p = Piece(self.piece.shape_name, self.piece.rotation,
                  self.piece.x + dx, self.piece.y + dy, self.piece.color)
        if not self._collides(p):
            self.piece = p
            return True
        return False

    def rotate(self) -> bool:
        """旋转方块（顺时针），返回是否成功"""
        if not self.piece or self.piece.shape_name == "O":
            return True  # O 不变
        p = Piece(self.piece.shape_name,
                  (self.piece.rotation + 1) % len(SHAPES[self.piece.shape_name]),
                  self.piece.x, self.piece.y, self.piece.color)
        # Wall kick: 尝试左右偏移
        for dx in [0, -1, 1, -2, 2]:
            p2 = Piece(p.shape_name, p.rotation, p.x + dx, p.y, p.color)
            if not self._collides(p2):
                self.piece = p2
                return True
        return False

    def hard_drop(self):
        """硬降：直接落到底"""
        while self.move(0, 1):
            pass
        self.lock_piece()

    def soft_drop(self) -> bool:
        """软降：向下移动一格，失败则锁定"""
        if self.move(0, 1):
            return True
        self.lock_piece()
        return False

    def lock_piece(self):
        """锁定当前方块到棋盘，清行，生成新块"""
        if not self.piece:
            return
        for x, y in self.piece.cells:
            if 0 <= y < HEIGHT + HIDDEN and 0 <= x < WIDTH:
                self.board[y][x] = self.piece.color
        self.piece = None
        self._clear_lines()
        if not self.spawn():
            self.running = False

    # ── 内部方法 ──

    def _collides(self, piece: Piece) -> bool:
        for x, y in piece.cells:
            if x < 0 or x >= WIDTH or y >= HEIGHT + HIDDEN:
                return True
            if y >= 0 and self.board[y][x] != 0:
                return True
        return False

    def _clear_lines(self):
        """消除满行，更新分数"""
        cleared = 0
        new_board = []
        for y in range(HEIGHT + HIDDEN):
            if all(self.board[y]):  # 满行
                cleared += 1
            else:
                new_board.append(self.board[y])
        # 顶部补空行
        while len(new_board) < HEIGHT + HIDDEN:
            new_board.insert(0, [0] * WIDTH)
        self.board = new_board

        if cleared:
            self.score += SCORE_TABLE.get(cleared, cleared * 200) * self.level
            self.lines += cleared
            self.level = self.lines // 10 + 1
            self.drop_interval = max(0.05, 0.8 - (self.level - 1) * 0.07)

    # ── 渲染 ──

    def render(self) -> str:
        """生成 ANSI 渲染字符串"""
        # 合并棋盘 + 当前方块
        display = [row[:] for row in self.board]
        if self.piece:
            for x, y in self.piece.cells:
                if HIDDEN <= y < HEIGHT + HIDDEN and 0 <= x < WIDTH:
                    display[y][x] = self.piece.color

        lines = []
        lines.append(CLEAR + HIDE_CURSOR)

        # 顶部信息
        next_name = self.next_piece.shape_name if self.next_piece else "?"
        lines.append(f"  🎮 TETRIS  |  分数: {self.score:>6}  |  等级: {self.level:>2}"
                     f"  |  消行: {self.lines:>3}  |  下一个: {next_name}")
        lines.append("  ┌" + "──" * WIDTH + "┐")

        # 游戏区域（从 HIDDEN 行开始显示）
        for y in range(HIDDEN, HEIGHT + HIDDEN):
            line = "  │"
            for x in range(WIDTH):
                c = display[y][x]
                if c:
                    line += COLORS[c] + "  " + RESET
                else:
                    line += "\033[40m ·" + RESET
            line += "\033[40m│" + RESET
            lines.append(line)

        lines.append("  └" + "──" * WIDTH + "┘")
        lines.append("  ← → 移动  ↑ 旋转  ↓ 软降  空格 硬降  p 暂停  q 退出")

        if self.paused:
            lines.append("\n  ⏸️  暂停中，按 p 继续...")
        if not self.running:
            lines.append(f"\n  💀 游戏结束!  最终分数: {self.score}")

        lines.append(SHOW_CURSOR)
        return "\n".join(lines)

    # ── 游戏循环 ──

    def update(self):
        """每帧调用，处理自动下落"""
        if not self.running or self.paused or not self.piece:
            return
        now = time.time()
        if now - self._last_drop >= self.drop_interval:
            self._last_drop = now
            self.soft_drop()


# ── 输入处理 ──

class Input:
    """跨平台非阻塞键盘输入"""

    def __init__(self):
        self._win = IS_WIN

    def get_key(self) -> str | None:
        """获取按键，无输入返回 None"""
        if self._win:
            return self._get_key_windows()
        return self._get_key_unix()

    def _get_key_windows(self) -> str | None:
        import msvcrt
        if not msvcrt.kbhit():
            return None
        ch = msvcrt.getch()
        if ch == b'\xe0':  # 方向键前缀
            ch2 = msvcrt.getch()
            return {b'H': 'up', b'P': 'down', b'K': 'left', b'M': 'right'}.get(ch2, None)
        if ch == b' ':
            return 'space'
        if ch == b'\r':
            return 'enter'
        try:
            return ch.decode('utf-8').lower()
        except UnicodeDecodeError:
            return None

    def _get_key_unix(self) -> str | None:
        if not select.select([sys.stdin], [], [], 0)[0]:
            return None
        ch = os.read(sys.stdin.fileno(), 1)
        if ch == b'\x1b':
            # ESC 序列
            time.sleep(0.01)
            rest = b''
            while select.select([sys.stdin], [], [], 0)[0]:
                rest += os.read(sys.stdin.fileno(), 1)
            if rest == b'[A':
                return 'up'
            if rest == b'[B':
                return 'down'
            if rest == b'[C':
                return 'right'
            if rest == b'[D':
                return 'left'
            return 'esc'
        if ch == b' ':
            return 'space'
        try:
            return ch.decode('utf-8').lower()
        except UnicodeDecodeError:
            return None


def main():
    """主函数"""
    game = Tetris()
    inp = Input()

    # Unix: 设置终端为 raw 模式
    if not IS_WIN:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

    try:
        game.spawn()

        while game.running:
            # 输入处理
            key = inp.get_key()
            if key:
                if key == 'q' or key == '\x03':  # Ctrl-C
                    break
                if key == 'p':
                    game.paused = not game.paused
                if not game.paused:
                    if key == 'left':
                        game.move(-1, 0)
                    elif key == 'right':
                        game.move(1, 0)
                    elif key == 'down':
                        game.soft_drop()
                    elif key == 'up':
                        game.rotate()
                    elif key == 'space':
                        game.hard_drop()

            game.update()

            # 渲染
            sys.stdout.write(game.render())
            sys.stdout.flush()

            time.sleep(0.016)  # ~60 FPS

    except KeyboardInterrupt:
        pass
    finally:
        if not IS_WIN:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write(CLEAR + SHOW_CURSOR)
        sys.stdout.flush()

    print(f"\n🎉 游戏结束!  最终分数: {game.score}  消行: {game.lines}")


if __name__ == "__main__":
    main()

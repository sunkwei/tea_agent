"""
Battle Snakes TUI Renderer — curses-based ASCII display.
"""

import curses
import time
from typing import List, Optional, Set

from .engine import Game, Snake, Position, Direction


# ── color pair IDs ─────────────────────────────────────────
STRAWBERRY_COLOR = 100
WALL_COLOR = 101
STATUS_COLOR = 102
DEAD_COLOR = 103
HUMAN_COLOR = 50


def _init_colors() -> None:
    """Initialize curses color pairs."""
    curses.start_color()
    curses.use_default_colors()
    snake_fg = [
        curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_CYAN,
        curses.COLOR_MAGENTA, curses.COLOR_RED, curses.COLOR_BLUE,
        curses.COLOR_WHITE,
    ]
    for i, fg in enumerate(snake_fg):
        curses.init_pair(i + 1, fg, -1)
    curses.init_pair(STRAWBERRY_COLOR, curses.COLOR_RED, -1)
    curses.init_pair(WALL_COLOR, curses.COLOR_WHITE, -1)
    curses.init_pair(STATUS_COLOR, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(DEAD_COLOR, curses.COLOR_BLACK, curses.COLOR_RED)
    curses.init_pair(HUMAN_COLOR, curses.COLOR_GREEN, -1)


class Renderer:
    """Curses-based TUI renderer for Battle Snakes."""

    def __init__(self, game: Game,
                 human_index: Optional[int] = None,
                 human_state: Optional[dict] = None):
        self.game = game
        self.human_index = human_index
        self.human_state = human_state
        self.stdscr: Optional[curses.window] = None
        self._running = False
        self._pause = False
        self._speed = 0.12
        self._event_log: List[str] = []
        self._event_log: List[str] = []
        self._max_events = 10
        self._quit = False  # True if user pressed Q

    # ── public ─────────────────────────────────────────────

    def run(self) -> Optional[str]:
        """Run the game loop. Returns winner name, or None for draw/all-dead.
        Check ._quit to distinguish user quit from natural draw."""
        result = curses.wrapper(self._run)
        return result

    @property
    def user_quit(self) -> bool:
        return self._quit
    # ── main loop ──────────────────────────────────────────

    def _run(self, stdscr) -> Optional[str]:
        self.stdscr = stdscr
        _init_colors()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.clear()
        self._running = True

        while self._running:
            key = stdscr.getch()
            self._handle_input(key)

            if not self._pause:
                result = self.game.tick()
                for ev in result["events"]:
                    self._event_log.append(ev)
                if len(self._event_log) > self._max_events:
                    self._event_log = self._event_log[-self._max_events:]
                if result["winner"]:
                    self._draw()
                    self._show_game_over(result["winner"])
                    time.sleep(2.5)
                    return result["winner"]
                if result["alive_count"] == 0:
                    if key == ord('q') or key == 27:
                        self._running = False
                        self._quit = True
                        return None

            self._draw()
            time.sleep(self._speed if not self._pause else 0.05)

        return None

    # ── input ──────────────────────────────────────────────

    def _handle_input(self, key: int) -> None:
        if key == -1:
            return
        if key == ord('q') or key == 27:
            self._running = False
        elif key == ord(' '):
            self._pause = not self._pause
        elif key in (ord('+'), ord('=')):
            self._speed = max(0.01, self._speed - 0.02)
        elif key == ord('-'):
            self._speed = min(0.5, self._speed + 0.02)

        # human player
        if self.human_index is not None and self.human_state is not None:
            human = self.game.snakes[self.human_index]
            if human.alive:
                d = None
                if key in (curses.KEY_UP, ord('w')):
                    d = Direction.UP
                elif key in (curses.KEY_DOWN, ord('s')):
                    d = Direction.DOWN
                elif key in (curses.KEY_LEFT, ord('a')):
                    d = Direction.LEFT
                elif key in (curses.KEY_RIGHT, ord('d')):
                    d = Direction.RIGHT
                if d is not None:
                    self.human_state["dir"] = d

    # ── drawing ────────────────────────────────────────────

    def _draw(self) -> None:
        if not self.stdscr:
            return
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        bw = self.game.board.width + 2
        bh = self.game.board.height + 2
        ox = max(1, (w - bw - 25) // 2)
        oy = max(0, (h - bh) // 2)

        self._draw_board(ox, oy)

        sidebar_x = ox + bw + 2
        if sidebar_x + 20 < w:
            self._draw_sidebar(sidebar_x, oy, h)

        self.stdscr.refresh()

    def _draw_board(self, ox: int, oy: int) -> None:
        bw = self.game.board.width
        bh = self.game.board.height
        wattr = curses.color_pair(WALL_COLOR) | curses.A_BOLD

        # walls
        for x in range(bw + 2):
            try:
                self.stdscr.addch(oy, ox + x, '█', wattr)
                self.stdscr.addch(oy + bh + 1, ox + x, '█', wattr)
            except curses.error:
                pass
        for y in range(bh + 2):
            try:
                self.stdscr.addch(oy + y, ox, '█', wattr)
                self.stdscr.addch(oy + y, ox + bw + 1, '█', wattr)
            except curses.error:
                pass

        # strawberries
        sattr = curses.color_pair(STRAWBERRY_COLOR) | curses.A_BOLD
        for pos in self.game.strawberries:
            try:
                self.stdscr.addch(oy + 1 + pos.y, ox + 1 + pos.x, '♥', sattr)
            except curses.error:
                pass

        # snakes
        for snake in self.game.snakes:
            attr = curses.color_pair(snake.color_id) if snake.alive \
                else curses.color_pair(DEAD_COLOR)
            # head
            try:
                self.stdscr.addch(oy + 1 + snake.head.y, ox + 1 + snake.head.x,
                                  snake.char, attr | curses.A_BOLD)
            except curses.error:
                pass
            # body
            for seg in snake.body[1:]:
                try:
                    self.stdscr.addch(oy + 1 + seg.y, ox + 1 + seg.x,
                                      snake.char.lower(), attr)
                except curses.error:
                    pass

        # pause indicator
        if self._pause:
            try:
                self.stdscr.addstr(oy, ox + bw // 2 - 4, " ⏸ PAUSED ",
                                   curses.color_pair(STATUS_COLOR) | curses.A_BOLD)
            except curses.error:
                pass

    def _draw_sidebar(self, sx: int, sy: int, max_h: int) -> None:
        def _put(row: int, text: str, *attrs) -> None:
            try:
                if attrs:
                    self.stdscr.addstr(row, sx, text, *attrs)
                else:
                    self.stdscr.addstr(row, sx, text)
            except curses.error:
                pass

        _put(sy, "══ BATTLE SNAKES ══", curses.A_BOLD | curses.color_pair(STRAWBERRY_COLOR))
        _put(sy + 2, f"Tick: {self.game.tick_count}")
        _put(sy + 3, f"Speed: {self._speed:.2f}s")
        _put(sy + 4, f"Status: {'PAUSED' if self._pause else 'RUNNING'}")
        _put(sy + 5, "─" * 22)
        _put(sy + 6, "Snakes:", curses.A_BOLD)

        row = sy + 7
        for snake in self.game.snakes:
            if row >= max_h - 2:
                break
            icon = "✓" if snake.alive else "✗"
            a = curses.color_pair(snake.color_id) if snake.alive \
                else curses.color_pair(DEAD_COLOR)
            _put(row, f" {icon} [{snake.char}] {snake.name[:12]:12s} "
                 f"len={snake.length:3d} score={snake.score:3d}", a)
            row += 1

        _put(row, "─" * 22); row += 1
        _put(row, "Events:", curses.A_BOLD); row += 1
        for ev in self._event_log[-8:]:
            if row >= max_h - 2:
                break
            _put(row, f" {ev[:35]}", curses.color_pair(STATUS_COLOR))
            row += 1

        if row + 6 < max_h:
            _put(row + 1, "─" * 22)
            _put(row + 2, "Controls:", curses.A_BOLD)
            _put(row + 3, " Space: pause/resume")
            _put(row + 4, " +/- : speed")
            _put(row + 5, " Q/ESC: quit")
            if self.human_index is not None:
                _put(row + 6, " Arrows/WASD: move")

    def _show_game_over(self, winner: Optional[str]) -> None:
        if not self.stdscr:
            return
        h, w = self.stdscr.getmaxyx()
        if winner:
            msg = f"GAME OVER — {winner} WINS!"
        else:
            msg = "GAME OVER — DRAW!"
        try:
            self.stdscr.addstr(h // 2, (w - len(msg)) // 2, msg,
                               curses.A_BOLD | curses.color_pair(STRAWBERRY_COLOR))
        except curses.error:
            pass
        self.stdscr.refresh()


# ── human player strategy ──────────────────────────────────

def make_human_strategy():
    """Returns a strategy function + state dict for a human-controlled snake."""
    state = {"dir": None}

    def human_strategy(snake: Snake, game: Game) -> Direction:
        d = state["dir"]
        if d is None:
            return snake._last_direction or Direction.RIGHT
        nh = snake.head + d
        if game.board.in_bounds(nh) and nh not in snake.body[1:]:
            return d
        # unsafe — pick any safe direction
        for dd in Direction.all():
            nnh = snake.head + dd
            if game.board.in_bounds(nnh) and nnh not in snake.body[1:]:
                return dd
        return d

    return human_strategy, state

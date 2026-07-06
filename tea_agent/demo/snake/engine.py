"""
Battle Snakes Engine — pure game logic, no I/O.
Multi-snake survival: each snake has its own strategy, last one alive wins.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    UP = (0, -1)
    DOWN = (0, 1)
    LEFT = (-1, 0)
    RIGHT = (1, 0)

    def opposite(self) -> "Direction":
        opposites = {
            Direction.UP: Direction.DOWN,
            Direction.DOWN: Direction.UP,
            Direction.LEFT: Direction.RIGHT,
            Direction.RIGHT: Direction.LEFT,
        }
        return opposites[self]

    @staticmethod
    def all() -> list["Direction"]:
        return [Direction.UP, Direction.DOWN, Direction.LEFT, Direction.RIGHT]


@dataclass(frozen=True)
class Position:
    x: int
    y: int

    def __add__(self, d: Direction) -> "Position":
        return Position(self.x + d.value[0], self.y + d.value[1])

    def manhattan(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)


class Snake:
    """A single snake with body, strategy, and state."""

    def __init__(
        self,
        body: list[Position],
        strategy: Callable[["Snake", "Game"], Direction],
        name: str,
        char: str,
        color_id: int = 0,
    ):
        self.body: list[Position] = list(body)  # head is body[0]
        self.strategy = strategy
        self.name = name
        self.char = char
        self.color_id = color_id
        self.alive: bool = True
        self.score: int = 0
        self._last_direction: Direction | None = None

    @property
    def head(self) -> Position:
        return self.body[0]

    @property
    def length(self) -> int:
        return len(self.body)

    def decide(self, game: "Game") -> Direction:
        """Ask strategy for next direction."""
        return self.strategy(self, game)


class Board:
    """The game grid dimensions."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height

    def in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height


class Game:
    """Orchestrates the battle snakes game."""

    def __init__(
        self,
        width: int,
        height: int,
        snakes_config: list[dict],
        seed: int | None = None,
    ):
        self.board = Board(width, height)
        self.snakes: list[Snake] = []
        self.tick_count: int = 0
        self.max_strawberries: int = 3
        self._rng = random.Random(seed)
        self._strawberries: set[Position] = set()
        self._init_snakes(snakes_config)
        self._spawn_initial_strawberries()

    def _init_snakes(self, configs: list[dict]) -> None:
        """Place snakes at spaced starting positions."""
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, cfg in enumerate(configs):
            name = cfg.get("name", f"Snake{i}")
            strategy = cfg["strategy"]
            char = cfg.get("char", chars[i % len(chars)])
            color_id = cfg.get("color_id", i + 1)
            init_len = cfg.get("initial_length", 3)
            pos = self._find_start_pos(init_len)
            # body extends leftward, ensure all segments in bounds
            body = [pos]
            for k in range(1, init_len):
                bx = pos.x - k
                if bx < 0:
                    bx = 0
                body.append(Position(bx, pos.y))
            snake = Snake(body, strategy, name, char, color_id)
            snake._last_direction = Direction.RIGHT
            self.snakes.append(snake)

    def _find_start_pos(self, min_len: int = 3) -> Position:
        """Find a random empty position with enough room for the initial body."""
        # need at least min_len cells left of the head
        margin = min_len + 1
        # but don't fail on small boards
        if margin >= self.board.width - 1:
            margin = max(1, self.board.width // 4)
        for _ in range(500):
            lo = margin
            hi_x = self.board.width - margin - 1
            hi_y = self.board.height - margin - 1
            if hi_x < lo:
                lo = 1
                hi_x = max(1, self.board.width - 2)
            if hi_y < lo:
                hi_y = max(1, self.board.height - 2)
            if hi_x < lo or hi_y < lo:
                break
            x = self._rng.randint(lo, hi_x)
            y = self._rng.randint(lo, hi_y)
            pos = Position(x, y)
            if not self._any_snake_at(pos):
                return pos
        # fallback
        for x in range(margin, self.board.width - margin):
            for y in range(margin, self.board.height - margin):
                pos = Position(x, y)
                if not self._any_snake_at(pos):
                    return pos
        return Position(self.board.width // 2, self.board.height // 2)

    def _spawn_initial_strawberries(self) -> None:
        for _ in range(self.max_strawberries):
            self._spawn_one_strawberry()
    # ── queries ────────────────────────────────────────────

    def _any_snake_at(self, pos: Position) -> bool:
        return any(s.alive and pos in s.body for s in self.snakes)

    def all_occupied_positions(self, exclude: Snake | None = None) -> set[Position]:
        """Set of all occupied cells (walls + snake bodies)."""
        occupied: set[Position] = set()
        # walls just outside bounds
        for x in range(-1, self.board.width + 1):
            occupied.add(Position(x, -1))
            occupied.add(Position(x, self.board.height))
        for y in range(-1, self.board.height + 1):
            occupied.add(Position(-1, y))
            occupied.add(Position(self.board.width, y))
        for s in self.snakes:
            if s.alive and s is not exclude:
                for p in s.body:
                    occupied.add(p)
        return occupied

    # ── strawberries ───────────────────────────────────────

    @property
    def strawberries(self) -> set[Position]:
        return self._strawberries

    def has_strawberry_at(self, pos: Position) -> bool:
        return pos in self._strawberries

    def _spawn_one_strawberry(self) -> None:
        """Spawn a single strawberry at a random empty cell."""
        empty = []
        for x in range(self.board.width):
            for y in range(self.board.height):
                pos = Position(x, y)
                if not self._any_snake_at(pos) and pos not in self._strawberries:
                    empty.append(pos)
        if empty:
            self._strawberries.add(self._rng.choice(empty))

    # ── tick ───────────────────────────────────────────────

    def tick(self) -> dict:
        """
        Advance the game by one tick. Returns status dict.
        """
        self.tick_count += 1
        events: list[str] = []

        # 1. collect decisions from all alive snakes
        decisions: dict[Snake, Direction] = {}
        for s in self.snakes:
            if s.alive:
                try:
                    d = s.decide(self)
                except Exception:
                    safe = self._safe_dirs(s)
                    d = safe[0] if safe else Direction.UP
                decisions[s] = d

        # 2. compute new heads (before moving)
        new_heads: dict[Snake, Position] = {}
        for s, d in decisions.items():
            new_heads[s] = s.head + d
        # 3. check which snakes will eat a strawberry
        # handle multiple snakes landing on same strawberry: first-come-first-served
        eaten_strawberries: set[Position] = set()
        ate: set[Snake] = set()
        for s in decisions:
            nh = new_heads[s]
            if nh in self._strawberries and nh not in eaten_strawberries:
                ate.add(s)
                eaten_strawberries.add(nh)

        # 4. move all snakes (grow if ate)
        for s, d in decisions.items():
            grow = s in ate
            s.body.insert(0, new_heads[s])
            if not grow:
                s.body.pop()
            s._last_direction = d
            if grow:
                pos = new_heads[s]
                if pos in self._strawberries:
                    self._strawberries.remove(pos)
                s.score += 1
                events.append(f"{s.name} ate a strawberry!")
                self._spawn_one_strawberry()
        # 5. resolve collisions (simultaneous)
        dead_this_tick: set[Snake] = set()

        # wall & self collisions
        for s in self.snakes:
            if not s.alive:
                continue
            h = s.head
            if not self.board.in_bounds(h):
                dead_this_tick.add(s)
                events.append(f"{s.name} hit a wall!")
                continue
            if h in s.body[1:]:
                dead_this_tick.add(s)
                events.append(f"{s.name} ran into itself!")
                continue

        # head-to-head collisions
        alive_now = [s for s in self.snakes if s.alive and s not in dead_this_tick]
        head_map: dict[Position, list[Snake]] = {}
        for s in alive_now:
            head_map.setdefault(s.head, []).append(s)

        for pos, snakes_here in head_map.items():
            if len(snakes_here) > 1:
                for s in snakes_here:
                    dead_this_tick.add(s)
                names = ", ".join(s.name for s in snakes_here)
                events.append(f"Head collision between {names}!")

        # head hits another snake's body
        for s in alive_now:
            if s in dead_this_tick:
                continue
            for other in self.snakes:
                if other is s or not other.alive or other in dead_this_tick:
                    continue
                if s.head in other.body:
                    dead_this_tick.add(s)
                    events.append(f"{s.name} crashed into {other.name}!")
                    break

        # mark dead
        for s in dead_this_tick:
            s.alive = False

        # 6. win condition
        alive = [s for s in self.snakes if s.alive]
        winner = alive[0].name if len(alive) == 1 else None

        return {
            "events": events,
            "alive_count": len(alive),
            "winner": winner,
            "dead_this_tick": len(dead_this_tick),
        }

    # ── helpers for strategies ─────────────────────────────

    def _safe_dirs(self, snake: Snake) -> list[Direction]:
        """Return directions that don't immediately kill the snake."""
        safe = []
        for d in Direction.all():
            nh = snake.head + d
            if not self.board.in_bounds(nh):
                continue
            if nh in snake.body[1:]:
                continue
            ok = True
            for s in self.snakes:
                if s is snake or not s.alive:
                    continue
                if nh in s.body:
                    ok = False
                    break
            if ok:
                safe.append(d)
        return safe

    def flood_fill(self, start: Position, exclude: Snake | None = None) -> int:
        """Count reachable cells from start (used by survival strategies)."""
        occupied = self.all_occupied_positions(exclude)
        if start in occupied:
            return 0
        visited = {start}
        stack = [start]
        while stack:
            p = stack.pop()
            for d in Direction.all():
                np = p + d
                if np not in visited and np not in occupied:
                    visited.add(np)
                    stack.append(np)
        return len(visited)

    def bfs_distance(self, start: Position, goals: set[Position],
                     exclude: Snake | None = None) -> int | None:
        """BFS shortest path distance from start to any goal. None if unreachable."""
        if start in goals:
            return 0
        occupied = self.all_occupied_positions(exclude) - goals
        if start in occupied:
            return None
        visited = {start}
        queue: list[tuple[Position, int]] = [(start, 0)]
        for p, dist in queue:
            for d in Direction.all():
                np = p + d
                if np in goals:
                    return dist + 1
                if np not in visited and np not in occupied:
                    visited.add(np)
                    queue.append((np, dist + 1))
        return None

    @property
    def alive_snakes(self) -> list[Snake]:
        return [s for s in self.snakes if s.alive]

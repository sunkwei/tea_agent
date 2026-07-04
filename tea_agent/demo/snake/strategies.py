"""
Battle Snakes Strategies — AI decision functions for snake movement.

Each strategy is a callable: (snake: Snake, game: Game) -> Direction
"""

import random
from typing import List, Optional

from .engine import Snake, Game, Direction, Position


# ── helpers ────────────────────────────────────────────────

def _safe_directions(snake: Snake, game: Game) -> List[Direction]:
    """Directions that don't immediately hit a wall, self, or other snake."""
    safe = []
    for d in Direction.all():
        nh = snake.head + d
        if not game.board.in_bounds(nh):
            continue
        if nh in snake.body[1:]:
            continue
        blocked = False
        for s in game.snakes:
            if s is snake or not s.alive:
                continue
            if nh in s.body:
                blocked = True
                break
        if not blocked:
            safe.append(d)
    return safe


def _direction_toward(head: Position, target: Position) -> Optional[Direction]:
    """Pick the single-axis direction that moves toward target. Prefer axis with larger gap."""
    dx = target.x - head.x
    dy = target.y - head.y
    candidates = []
    if dx > 0:
        candidates.append(Direction.RIGHT)
    elif dx < 0:
        candidates.append(Direction.LEFT)
    if dy > 0:
        candidates.append(Direction.DOWN)
    elif dy < 0:
        candidates.append(Direction.UP)
    if not candidates:
        return None
    # prefer the axis with larger absolute difference
    if abs(dx) >= abs(dy) and (Direction.RIGHT if dx > 0 else Direction.LEFT) in candidates:
        return Direction.RIGHT if dx > 0 else Direction.LEFT
    if (Direction.DOWN if dy > 0 else Direction.UP) in candidates:
        return Direction.DOWN if dy > 0 else Direction.UP
    return candidates[0]


# ── strategies ─────────────────────────────────────────────

def random_strategy(snake: Snake, game: Game) -> Direction:
    """Pick a random safe direction. If none safe, pick any direction (will die)."""
    safe = _safe_directions(snake, game)
    if safe:
        return random.choice(safe)
    return random.choice(Direction.all())


def greedy_strategy(snake: Snake, game: Game) -> Direction:
    """Head toward the nearest strawberry using BFS. Fall back to random."""
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    strawberries = game.strawberries
    if not strawberries:
        return random.choice(safe)

    # find direction with shortest BFS distance to any strawberry
    best_dir = safe[0]
    best_dist = 999999
    for d in safe:
        nh = snake.head + d
        dist = game.bfs_distance(nh, strawberries, exclude=snake)
        if dist is not None and dist < best_dist:
            best_dist = dist
            best_dir = d

    return best_dir


def safe_greedy_strategy(snake: Snake, game: Game) -> Direction:
    """Greedy toward strawberry, but avoid moves that lead to dead ends (< 5 reachable cells)."""
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    strawberries = game.strawberries

    # score each direction: combine distance to strawberry + flood fill safety
    candidates = []
    for d in safe:
        nh = snake.head + d
        # flood fill from new head position
        # temporarily simulate: would this move leave us trapped?
        reachable = game.flood_fill(nh, exclude=snake)
        dist = game.bfs_distance(nh, strawberries, exclude=snake) if strawberries else 999

        # score: lower is better
        # heavily penalize dead ends
        if reachable < snake.length + 3:
            score = 99999
        else:
            score = (dist if dist is not None else 9999) - reachable * 0.01
        candidates.append((score, d, reachable, dist))

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def survival_strategy(snake: Snake, game: Game) -> Direction:
    """Maximize open space — pick direction with largest flood-fill reachable area."""
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    best_dir = safe[0]
    best_space = -1
    for d in safe:
        nh = snake.head + d
        space = game.flood_fill(nh, exclude=snake)
        if space > best_space:
            best_space = space
            best_dir = d

    return best_dir


def aggressive_strategy(snake: Snake, game: Game) -> Direction:
    """
    Aggressive: chase other snake heads to block them.
    If no enemy nearby, fall back to safe greedy.
    """
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    # find nearest enemy head
    enemies = [s for s in game.snakes if s.alive and s is not snake]
    if not enemies:
        return greedy_strategy(snake, game)

    nearest_enemy = min(enemies, key=lambda e: snake.head.manhattan(e.head))
    enemy_dist = snake.head.manhattan(nearest_enemy.head)

    if enemy_dist <= 6:
        # head toward where the enemy will likely go
        # predict: enemy head + enemy direction (if known)
        if nearest_enemy._last_direction:
            predicted = nearest_enemy.head + nearest_enemy._last_direction
        else:
            predicted = nearest_enemy.head

        best_dir = safe[0]
        best_dist = 999999
        for d in safe:
            nh = snake.head + d
            dist = nh.manhattan(predicted)
            if dist < best_dist:
                best_dist = dist
                best_dir = d
        return best_dir

    # enemy far away → safe greedy
    return safe_greedy_strategy(snake, game)


def wall_hugger_strategy(snake: Snake, game: Game) -> Direction:
    """
    Stay close to walls for safety. Pick direction that minimizes distance to nearest wall.
    """
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    strawberries = game.strawberries

    best_dir = safe[0]
    best_score = -999999
    for d in safe:
        nh = snake.head + d
        # wall proximity score: closer to wall = better
        wall_dist = min(nh.x, nh.y,
                        game.board.width - 1 - nh.x,
                        game.board.height - 1 - nh.y)
        # also consider strawberry distance
        straw_dist = 999
        if strawberries:
            straw_dist = min(s.manhattan(nh) for s in strawberries)

        reachable = game.flood_fill(nh, exclude=snake)
        # prefer wall-hugging but also want strawberries and open space
        score = -wall_dist * 2 + reachable * 0.5 - straw_dist * 0.3
        if reachable < snake.length + 2:
            score = -999999
        if score > best_score:
            best_score = score
            best_dir = d

    return best_dir


def hybrid_strategy(snake: Snake, game: Game) -> Direction:
    """
    Adaptive hybrid: greedy when safe, survival when threatened, aggressive when crowded.
    """
    safe = _safe_directions(snake, game)
    if not safe:
        return random.choice(Direction.all())

    alive_count = len(game.alive_snakes)

    # check if we're in danger (few safe moves, or snake is long)
    danger_level = 6 - len(safe)  # fewer safe dirs = more danger
    if snake.length > 10:
        danger_level += 2

    if danger_level >= 3:
        # high danger → pure survival
        return survival_strategy(snake, game)

    if alive_count <= 3 and snake.length > 5:
        # few snakes left, we're big → aggressive
        return aggressive_strategy(snake, game)

    # normal mode → safe greedy
    return safe_greedy_strategy(snake, game)


# ── registry ───────────────────────────────────────────────

STRATEGIES = {
    "random": random_strategy,
    "greedy": greedy_strategy,
    "safe_greedy": safe_greedy_strategy,
    "survival": survival_strategy,
    "aggressive": aggressive_strategy,
    "wall_hugger": wall_hugger_strategy,
    "hybrid": hybrid_strategy,
}

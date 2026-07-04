"""
Headless test for Battle Snakes engine — run without curses.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tea_agent.demo.snake.engine import Game, Position, Direction
from tea_agent.demo.snake.strategies import STRATEGIES


def test_basic():
    """Basic smoke test: run game to completion."""
    configs = [
        {"name": "Alpha", "strategy": STRATEGIES["random"], "char": "A"},
        {"name": "Bravo", "strategy": STRATEGIES["greedy"], "char": "B"},
        {"name": "Charlie", "strategy": STRATEGIES["safe_greedy"], "char": "C"},
        {"name": "Delta", "strategy": STRATEGIES["survival"], "char": "D"},
        {"name": "Echo", "strategy": STRATEGIES["hybrid"], "char": "E"},
    ]
    game = Game(width=30, height=20, snakes_config=configs, seed=42)

    max_ticks = 5000
    for _ in range(max_ticks):
        result = game.tick()
        if result["winner"] or result["alive_count"] == 0:
            break

    print(f"Game ended at tick {game.tick_count}")
    print(f"Winner: {result['winner']}")
    print(f"Alive: {result['alive_count']}")
    for s in sorted(game.snakes, key=lambda x: x.score, reverse=True):
        print(f"  [{s.char}] {s.name}: alive={s.alive}, len={s.length}, score={s.score}")

    assert game.tick_count < max_ticks, "Game ran too long!"
    assert result["alive_count"] <= 1
    print("\n✅ Basic test PASSED")


def test_head_collision():
    """Test that head-to-head collisions kill both snakes."""
    from tea_agent.demo.snake.engine import Game, Position, Direction

    # custom setup: two snakes heading toward each other
    configs = [
        {"name": "Left", "strategy": lambda s, g: Direction.RIGHT, "char": "L", "initial_length": 3},
        {"name": "Right", "strategy": lambda s, g: Direction.LEFT, "char": "R", "initial_length": 3},
    ]
    game = Game(width=10, height=10, snakes_config=configs, seed=1)

    # override positions to force head-on collision
    game.snakes[0].body = [Position(4, 5), Position(3, 5), Position(2, 5)]
    game.snakes[1].body = [Position(6, 5), Position(7, 5), Position(8, 5)]

    game.tick()
    # both should die from head-on collision
    assert not game.snakes[0].alive, "Left snake should be dead"
    assert not game.snakes[1].alive, "Right snake should be dead"
    print("✅ Head collision test PASSED")


def test_wall_death():
    """Test wall collision kills snake."""
    configs = [
        {"name": "WallHugger", "strategy": lambda s, g: Direction.UP, "char": "W", "initial_length": 3},
    ]
    game = Game(width=10, height=10, snakes_config=configs, seed=1)
    game.snakes[0].body = [Position(5, 0), Position(4, 0), Position(3, 0)]

    result = game.tick()
    assert not game.snakes[0].alive, "Snake should die hitting wall"
    assert "hit a wall" in " ".join(result["events"]).lower()
    print("✅ Wall death test PASSED")


def test_strawberry_eating():
    """Test strawberry eating and growth."""
    configs = [
        {"name": "Eater", "strategy": lambda s, g: Direction.RIGHT, "char": "E", "initial_length": 3},
    ]
    game = Game(width=10, height=10, snakes_config=configs, seed=1)
    game.snakes[0].body = [Position(3, 5), Position(2, 5), Position(1, 5)]
    # place strawberry right in front
    game._strawberries = {Position(4, 5)}

    old_len = game.snakes[0].length
    result = game.tick()
    assert game.snakes[0].length == old_len + 1, "Snake should grow after eating"
    assert game.snakes[0].score == 1
    assert "ate a strawberry" in " ".join(result["events"]).lower()
    print("✅ Strawberry eating test PASSED")


if __name__ == "__main__":
    test_basic()
    test_head_collision()
    test_wall_death()
    test_strawberry_eating()
    print("\n🎉 All tests PASSED!")

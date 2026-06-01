"""
Battle Snakes — Multi-snake survival game (TUI).
Usage:
    python -m demo.snake.main [options]

Options:
    --width W            Board width (default 40)
    --height H           Board height (default 25)
    --snakes N            Number of AI snakes (default 5)
    --speed S             Tick speed in seconds (default 0.10)
    --strategies LIST     Comma-separated strategy names (default random mix)
    --human               Add a human-controlled snake (arrow keys / WASD)
    --seed N              Random seed for reproducibility

Available strategies: random, greedy, safe_greedy, survival, aggressive,
                      wall_hugger, hybrid
"""

import argparse
import random
import sys
import os

# ensure demo package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tea_agent.demo.snake.engine import Game
from tea_agent.demo.snake.strategies import STRATEGIES
from tea_agent.demo.snake.renderer import Renderer, make_human_strategy


def parse_args():
    p = argparse.ArgumentParser(description="Battle Snakes — Multi-snake survival TUI")
    p.add_argument("--width", type=int, default=40, help="Board width (default 40)")
    p.add_argument("--height", type=int, default=25, help="Board height (default 25)")
    p.add_argument("--snakes", type=int, default=5, help="Number of AI snakes (default 5)")
    p.add_argument("--speed", type=float, default=0.10, help="Tick speed in seconds (default 0.10)")
    p.add_argument("--strategies", type=str, default=None,
                   help="Comma-separated strategy names (default: random mix)")
    p.add_argument("--human", action="store_true", help="Add a human-controlled snake")
    p.add_argument("--seed", type=int, default=None, help="Random seed")
    return p.parse_args()


def main():
    args = parse_args()

    strategy_names = list(STRATEGIES.keys())

    # parse strategies
    if args.strategies:
        requested = [s.strip() for s in args.strategies.split(",")]
    else:
        requested = []

    # build snake configs
    snake_names = [
        "Alpha", "Bravo", "Charlie", "Delta", "Echo",
        "Foxtrot", "Golf", "Hotel", "India", "Juliet",
        "Kilo", "Lima", "Mike", "November", "Oscar",
    ]

    configs = []
    human_index = None
    human_state = None

    # add AI snakes
    for i in range(args.snakes):
        strat_name = requested[i] if i < len(requested) else random.choice(strategy_names)
        if strat_name not in STRATEGIES:
            print(f"Unknown strategy: {strat_name}, using random")
            strat_name = "random"
        configs.append({
            "name": snake_names[i % len(snake_names)],
            "strategy": STRATEGIES[strat_name],
            "char": snake_names[i % len(snake_names)][0],
            "initial_length": random.randint(3, 6),
        })

    # add human snake
    if args.human:
        strat_fn, human_state = make_human_strategy()
        configs.append({
            "name": "Human",
            "strategy": strat_fn,
            "char": "@",
            "initial_length": 4,
        })
        human_index = len(configs) - 1

    # create game
    game = Game(
        width=args.width,
        height=args.height,
        snakes_config=configs,
        seed=args.seed,
    )

    # print pre-game info
    print("═" * 50)
    print("  BATTLE SNAKES")
    print("═" * 50)
    print(f"  Board: {args.width}×{args.height}")
    print(f"  Snakes: {len(configs)}")
    for i, cfg in enumerate(configs):
        tag = " (YOU)" if i == human_index else ""
        print(f"    [{cfg['char']}] {cfg['name']}{tag} — {cfg['strategy'].__name__ if hasattr(cfg['strategy'], '__name__') else 'human'}")
    print(f"  Speed: {args.speed}s/tick")
    print("═" * 50)
    print("  Controls: Arrows/WASD=move  Space=pause  +/-=speed  Q=quit")
    print("  Press any key to start...")

    input()

    # create renderer and run
    renderer = Renderer(game, human_index=human_index, human_state=human_state)
    renderer._speed = args.speed
    winner = renderer.run()

    # post-game
    print()
    if renderer.user_quit:
        print(f"  Game aborted by player at tick {game.tick_count}.")
    elif winner:
        print(f"  Winner: {winner}!")
    else:
        print(f"  Draw — all snakes died at tick {game.tick_count}!")
    print(f"  Final tick: {game.tick_count}")
    alive = [s for s in game.snakes if s.alive]
    if alive:
        print(f"  Still alive: {', '.join(s.name for s in alive)}")
    print()
    for s in sorted(game.snakes, key=lambda x: x.score, reverse=True):
        status = "✓" if s.alive else "✗"
        print(f"  {status} [{s.char}] {s.name}: len={s.length}, score={s.score}")

if __name__ == "__main__":
    main()

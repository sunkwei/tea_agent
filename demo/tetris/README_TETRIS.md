# Console Tetris Game

A Python implementation of the classic Tetris game for the terminal.

## Features

- Classic Tetris gameplay with all 7 tetrominoes
- Ghost piece (shows where the piece will land)
- Next piece preview
- Score, level, and lines cleared tracking
- Increasing difficulty as you level up
- Cross-platform support (Windows, macOS, Linux)
- **Optimized rendering** - no screen flickering, smooth animations

## Requirements

- Python 3.6+
- Terminal that supports ANSI escape sequences (most modern terminals)

## How to Run

1. Open a terminal/command prompt
2. Navigate to the `demo/tetris` directory
3. Run the game:

```bash
python tetris_ansi.py
```

Or from the project root:

```bash
python play_tetris.py
```

## Controls

| Key | Action |
|-----|--------|
| ← → | Move piece left/right |
| ↑ | Rotate piece clockwise |
| ↓ | Soft drop (move down faster) |
| Space | Hard drop (instant drop) |
| P | Pause/Resume game |
| Q | Quit game |
| R | Restart game (when game over) |

## Game Rules

- **Objective**: Clear lines by filling them completely with blocks.
- **Scoring**: 
  - 1 line: 100 × level
  - 2 lines: 300 × level
  - 3 lines: 500 × level
  - 4 lines (Tetris): 800 × level
- **Leveling**: Level increases every 10 lines cleared.
- **Speed**: Drop speed increases with each level.
- **Game Over**: When a new piece cannot be placed at the top of the board.

## Customization

You can modify game constants in `tetris_ansi.py`:

```python
BOARD_WIDTH = 10      # Board width in cells
BOARD_HEIGHT = 20     # Board height in cells
```

## Troubleshooting

### Windows Users
- Use Windows Terminal, PowerShell, or Command Prompt
- If colors don't work, try enabling ANSI support:
  1. Open Registry Editor
  2. Navigate to `HKEY_CURRENT_USER\Console`
  3. Set `VirtualTerminalLevel` to `1`

### Unix/Linux/macOS Users
- Most terminals support ANSI escape sequences by default
- If you experience issues, try using a different terminal emulator

## Implementation Details

The game uses:
- ANSI escape sequences for terminal rendering
- Cross-platform input handling (msvcrt on Windows, tty/select on Unix)
- Object-oriented design with clear separation of concerns
- Efficient board representation using 2D lists
- **Optimized rendering** - uses cursor movement instead of screen clearing to prevent flickering

## Recent Changes

### v1.1 (2026-05-30)
- Fixed rendering to show falling pieces correctly
- Optimized screen updates to eliminate flickering
- Improved ghost piece calculation

## License

This implementation is provided as-is for educational purposes.
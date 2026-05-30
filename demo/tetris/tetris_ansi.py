#!/usr/bin/env python3
"""
Console Tetris Game (ANSI version)
===================================
A Python implementation of Tetris for the terminal using ANSI escape sequences.
Works on Windows (with Windows Terminal) and Unix-like systems.
"""

import sys
import os
import time
import random
import threading
from typing import List, Tuple, Optional

# Check for Windows-specific modules
if sys.platform == 'win32':
    import msvcrt
else:
    import select
    import tty
    import termios

# ANSI escape sequences
ANSI_CLEAR = '\033[2J'
ANSI_HOME = '\033[H'
ANSI_HIDE_CURSOR = '\033[?25l'
ANSI_SHOW_CURSOR = '\033[?25h'
ANSI_RESET = '\033[0m'
ANSI_BOLD = '\033[1m'
ANSI_DIM = '\033[2m'

# Colors (foreground)
ANSI_COLORS = {
    'I': '\033[36m',   # Cyan
    'O': '\033[33m',   # Yellow
    'T': '\033[35m',   # Purple
    'S': '\033[32m',   # Green
    'Z': '\033[31m',   # Red
    'J': '\033[34m',   # Blue
    'L': '\033[37m',   # White (orange not standard)
}

# Game constants
BOARD_WIDTH = 10
BOARD_HEIGHT = 20
CELL_EMPTY = 0
CELL_FILLED = 1

# Tetromino shapes (each shape is a list of rotations)
# Each rotation is a list of (row, col) offsets from the piece's origin
TETROMINOES = {
    'I': [
        [(0, 0), (0, 1), (0, 2), (0, 3)],  # Horizontal
        [(0, 0), (1, 0), (2, 0), (3, 0)],  # Vertical
    ],
    'O': [
        [(0, 0), (0, 1), (1, 0), (1, 1)],  # Square (only one rotation)
    ],
    'T': [
        [(0, 0), (0, 1), (0, 2), (1, 1)],  # T pointing down
        [(0, 0), (1, 0), (2, 0), (1, 1)],  # T pointing right
        [(0, 1), (1, 0), (1, 1), (1, 2)],  # T pointing up
        [(0, 0), (1, 0), (2, 0), (1, -1)], # T pointing left
    ],
    'S': [
        [(0, 1), (0, 2), (1, 0), (1, 1)],  # S horizontal
        [(0, 0), (1, 0), (1, 1), (2, 1)],  # S vertical
    ],
    'Z': [
        [(0, 0), (0, 1), (1, 1), (1, 2)],  # Z horizontal
        [(0, 1), (1, 0), (1, 1), (2, 0)],  # Z vertical
    ],
    'J': [
        [(0, 0), (1, 0), (1, 1), (1, 2)],  # J pointing right
        [(0, 0), (0, 1), (1, 0), (2, 0)],  # J pointing down
        [(0, 0), (0, 1), (0, 2), (1, 2)],  # J pointing left
        [(0, 0), (1, 0), (2, 0), (2, -1)], # J pointing up
    ],
    'L': [
        [(0, 2), (1, 0), (1, 1), (1, 2)],  # L pointing left
        [(0, 0), (1, 0), (2, 0), (2, 1)],  # L pointing down
        [(0, 0), (0, 1), (0, 2), (1, 0)],  # L pointing right
        [(0, 0), (0, 1), (1, 1), (2, 1)],  # L pointing up
    ],
}


class ANSIHelper:
    """Helper class for ANSI terminal operations."""
    
    @staticmethod
    def clear_screen():
        """Clear the terminal screen."""
        sys.stdout.write(ANSI_CLEAR)
        sys.stdout.write(ANSI_HOME)
        sys.stdout.flush()
    
    @staticmethod
    def move_home():
        """Move cursor to home position (1,1) without clearing."""
        sys.stdout.write(ANSI_HOME)
        sys.stdout.flush()
    
    @staticmethod
    def move_cursor(row: int, col: int):
        """Move cursor to specific position (1-indexed)."""
        sys.stdout.write(f'\033[{row};{col}H')
        sys.stdout.flush()
    
    @staticmethod
    def hide_cursor():
        """Hide the cursor."""
        sys.stdout.write(ANSI_HIDE_CURSOR)
        sys.stdout.flush()
    
    @staticmethod
    def show_cursor():
        """Show the cursor."""
        sys.stdout.write(ANSI_SHOW_CURSOR)
        sys.stdout.flush()
    
    @staticmethod
    def set_color(color_code: str):
        """Set text color."""
        sys.stdout.write(color_code)
        sys.stdout.flush()
    
    @staticmethod
    def reset_color():
        """Reset text color to default."""
        sys.stdout.write(ANSI_RESET)
        sys.stdout.flush()


class InputHandler:
    """Cross-platform keyboard input handler."""
    
    def __init__(self):
        self.running = True
        self.key_queue = []
        self.lock = threading.Lock()
        
        if sys.platform != 'win32':
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
    
    def get_key(self) -> Optional[str]:
        """Get a key press (non-blocking). Returns None if no key pressed."""
        if sys.platform == 'win32':
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                # Handle special keys (arrow keys)
                if key == '\x00' or key == '\xe0':
                    key = msvcrt.getwch()
                    key_map = {
                        'H': 'up',
                        'P': 'down',
                        'K': 'left',
                        'M': 'right',
                    }
                    return key_map.get(key, None)
                return key
        else:
            if select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1)
                # Handle escape sequences (arrow keys)
                if key == '\x1b':
                    if select.select([sys.stdin], [], [], 0)[0]:
                        key += sys.stdin.read(1)
                        if key == '\x1b[':
                            if select.select([sys.stdin], [], [], 0)[0]:
                                key += sys.stdin.read(1)
                                key_map = {
                                    'A': 'up',
                                    'B': 'down',
                                    'D': 'left',
                                    'C': 'right',
                                }
                                return key_map.get(key[-1], None)
                    return 'escape'
                return key
        return None
    
    def cleanup(self):
        """Restore terminal settings."""
        if sys.platform != 'win32':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)


class TetrisGame:
    """Main Tetris game class."""
    
    def __init__(self):
        self.board: List[List[int]] = [[CELL_EMPTY] * BOARD_WIDTH for _ in range(BOARD_HEIGHT)]
        self.current_piece: Optional[dict] = None
        self.next_piece: Optional[dict] = None
        self.score = 0
        self.level = 1
        self.lines_cleared = 0
        self.game_over = False
        self.paused = False
        self.drop_interval = 1.0  # seconds per drop
        self.last_drop_time = 0
        
        # Input handler
        self.input_handler = InputHandler()
        
        # Generate first pieces
        self.next_piece = self._generate_piece()
        self._spawn_piece()
    
    def _generate_piece(self) -> dict:
        """Generate a random tetromino."""
        piece_type = random.choice(list(TETROMINOES.keys()))
        rotations = TETROMINOES[piece_type]
        return {
            'type': piece_type,
            'rotations': rotations,
            'rotation': 0,  # Current rotation index
            'row': 0,       # Top-left row position
            'col': BOARD_WIDTH // 2 - 1,  # Center horizontally
        }
    
    def _spawn_piece(self):
        """Spawn a new piece at the top."""
        if self.next_piece is None:
            self.next_piece = self._generate_piece()
        
        self.current_piece = self.next_piece
        self.next_piece = self._generate_piece()
        
        # Check if the new piece can be placed
        if not self._is_valid_position(self.current_piece):
            self.game_over = True
    
    def _get_piece_cells(self, piece: dict) -> List[Tuple[int, int]]:
        """Get the absolute positions of all cells in the current piece."""
        rotations = piece['rotations']
        rotation = piece['rotation'] % len(rotations)
        offsets = rotations[rotation]
        
        cells = []
        for dr, dc in offsets:
            r = piece['row'] + dr
            c = piece['col'] + dc
            cells.append((r, c))
        return cells
    
    def _is_valid_position(self, piece: dict, row_offset: int = 0, col_offset: int = 0, 
                           rotation_offset: int = 0) -> bool:
        """Check if a piece can be placed at the given position."""
        test_piece = piece.copy()
        test_piece['row'] = piece['row'] + row_offset
        test_piece['col'] = piece['col'] + col_offset
        test_piece['rotation'] = piece['rotation'] + rotation_offset
        
        cells = self._get_piece_cells(test_piece)
        
        for r, c in cells:
            # Check boundaries
            if r < 0 or r >= BOARD_HEIGHT:
                return False
            if c < 0 or c >= BOARD_WIDTH:
                return False
            # Check collision with placed pieces
            if self.board[r][c] == CELL_FILLED:
                return False
        return True
    
    def _rotate_piece(self):
        """Rotate the current piece clockwise."""
        if self.current_piece is None:
            return
        
        rotations = self.current_piece['rotations']
        new_rotation = (self.current_piece['rotation'] + 1) % len(rotations)
        
        # Try simple rotation first
        if self._is_valid_position(self.current_piece, rotation_offset=1):
            self.current_piece['rotation'] = new_rotation
            return
        
        # Wall kick: try moving left/right
        for dc in [1, -1, 2, -2]:
            if self._is_valid_position(self.current_piece, col_offset=dc, rotation_offset=1):
                self.current_piece['col'] += dc
                self.current_piece['rotation'] = new_rotation
                return
    
    def _move_piece(self, dr: int, dc: int) -> bool:
        """Move the current piece by (dr, dc). Returns True if successful."""
        if self.current_piece is None:
            return False
        
        if self._is_valid_position(self.current_piece, row_offset=dr, col_offset=dc):
            self.current_piece['row'] += dr
            self.current_piece['col'] += dc
            return True
        return False
    
    def _drop_piece(self):
        """Drop the piece one row down. If it can't move down, lock it."""
        if not self._move_piece(1, 0):
            self._lock_piece()
            self._clear_lines()
            self._spawn_piece()
    
    def _hard_drop(self):
        """Instantly drop the piece to the bottom."""
        while self._move_piece(1, 0):
            pass
        self._lock_piece()
        self._clear_lines()
        self._spawn_piece()
    
    def _lock_piece(self):
        """Lock the current piece into the board."""
        if self.current_piece is None:
            return
        
        cells = self._get_piece_cells(self.current_piece)
        for r, c in cells:
            if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
                self.board[r][c] = CELL_FILLED
    
    def _clear_lines(self):
        """Clear completed lines and update score."""
        lines_to_clear = []
        
        for r in range(BOARD_HEIGHT):
            if all(self.board[r][c] == CELL_FILLED for c in range(BOARD_WIDTH)):
                lines_to_clear.append(r)
        
        if not lines_to_clear:
            return
        
        # Remove lines from top to bottom
        for line in sorted(lines_to_clear):
            # Move all lines above down
            for r in range(line, 0, -1):
                self.board[r] = self.board[r-1][:]
            # Add empty line at top
            self.board[0] = [CELL_EMPTY] * BOARD_WIDTH
        
        # Update score
        cleared = len(lines_to_clear)
        self.lines_cleared += cleared
        
        # Scoring: 100, 300, 500, 800 for 1, 2, 3, 4 lines
        points = {1: 100, 2: 300, 3: 500, 4: 800}
        self.score += points.get(cleared, 0) * self.level
        
        # Level up every 10 lines
        self.level = self.lines_cleared // 10 + 1
        
        # Increase speed
        self.drop_interval = max(0.1, 1.0 - (self.level - 1) * 0.1)
    
# NOTE: 2026-05-30 10:56:13, self-evolved by tea_agent --- Fix drawing logic to show falling piece before it's locked
# NOTE: 2026-05-30 11:02:11, self-evolved by tea_agent --- Fix cell width inconsistency - use 2-char width for all cells
    def _draw_board(self):
        """Draw the game board using ANSI sequences."""
        # Move to top-left corner
        ANSIHelper.move_cursor(1, 1)
        
        # Draw top border (each cell is 2 chars wide)
        print('+' + '--' * BOARD_WIDTH + '+')
        
        # Pre-compute current piece cells and ghost cells
        current_cells = set()
        ghost_cells = set()
        if self.current_piece and not self.game_over:
            current_cells = set(self._get_piece_cells(self.current_piece))
            # Compute ghost piece (drop until collision)
            ghost_piece = self.current_piece.copy()
            while self._is_valid_position(ghost_piece, row_offset=1):
                ghost_piece['row'] += 1
            ghost_cells = set(self._get_piece_cells(ghost_piece))
        
        # Draw board cells (each cell is 2 characters wide)
        for r in range(BOARD_HEIGHT):
            print('|', end='')
            for c in range(BOARD_WIDTH):
# NOTE: 2026-05-30 11:03:53, self-evolved by tea_agent --- Change colored block from ██ to [] in board drawing
                # Check if this cell is part of the current piece
                if (r, c) in current_cells:
                    color = ANSI_COLORS.get(self.current_piece['type'], '')
                    print(f'{color}[]{ANSI_RESET}', end='')
                # Check if this cell is part of the ghost piece
                elif (r, c) in ghost_cells:
                    print(f'{ANSI_DIM}::{ANSI_RESET}', end='')
                # Check if cell is filled on the board
# NOTE: 2026-05-30 11:03:59, self-evolved by tea_agent --- Change filled block from ██ to [] in board drawing
                elif self.board[r][c] == CELL_FILLED:
                    print('[]', end='')
                else:
                    print('  ', end='')
            print('|')
        
        # Draw bottom border
        print('+' + '--' * BOARD_WIDTH + '+')
    
    def _draw_info(self):
        """Draw game information panel."""
# NOTE: 2026-05-30 11:02:33, self-evolved by tea_agent --- Update info column calculation for 2-char cell width
        # Calculate position (to the right of the board)
        info_col = BOARD_WIDTH * 2 + 5
        row = 1
        
        ANSIHelper.move_cursor(row, info_col)
        print(f'{ANSI_BOLD}TETRIS{ANSI_RESET}')
        
        row += 2
        ANSIHelper.move_cursor(row, info_col)
        print(f'Score: {self.score}')
        
        row += 1
        ANSIHelper.move_cursor(row, info_col)
        print(f'Level: {self.level}')
        
        row += 1
        ANSIHelper.move_cursor(row, info_col)
        print(f'Lines: {self.lines_cleared}')
        
        row += 2
        ANSIHelper.move_cursor(row, info_col)
        print('Next:')
        
        if self.next_piece:
            # Draw next piece preview
            preview_col = info_col + 2
            rotations = self.next_piece['rotations']
            offsets = rotations[0]  # Show first rotation
            
            # Find bounding box
            min_r = min(dr for dr, dc in offsets)
            max_r = max(dr for dr, dc in offsets)
            min_c = min(dc for dr, dc in offsets)
            max_c = max(dc for dr, dc in offsets)
            
            for dr in range(min_r, max_r + 1):
                ANSIHelper.move_cursor(row + 1 + dr - min_r, preview_col)
                for dc in range(min_c, max_c + 1):
# NOTE: 2026-05-30 11:04:12, self-evolved by tea_agent --- Change colored block from ██ to [] in next piece preview
                    if (dr, dc) in offsets:
                        color = ANSI_COLORS.get(self.next_piece['type'], '')
                        print(f'{color}[]{ANSI_RESET}', end='')
                    else:
# NOTE: 2026-05-30 11:03:16, self-evolved by tea_agent --- Update next piece preview to use 2-char width
                        print('  ', end='')
                print()
        
        # Controls
        row = 12
        ANSIHelper.move_cursor(row, info_col)
        print(f'{ANSI_BOLD}Controls:{ANSI_RESET}')
        
        controls = [
            '← → : Move',
            '↑    : Rotate',
            '↓    : Soft drop',
            'Space: Hard drop',
            'P    : Pause',
            'Q    : Quit',
        ]
        
        for i, control in enumerate(controls):
            ANSIHelper.move_cursor(row + 1 + i, info_col)
            print(control)
        
        # Game over
        if self.game_over:
            ANSIHelper.move_cursor(row + len(controls) + 2, info_col)
            print(f'{ANSI_BOLD}GAME OVER!{ANSI_RESET}')
            ANSIHelper.move_cursor(row + len(controls) + 3, info_col)
            print('Press R to restart')
    
    def _draw_pause(self):
        """Draw pause overlay."""
        if not self.paused:
            return
        
        # Semi-transparent overlay
        for r in range(2, BOARD_HEIGHT + 2):
            ANSIHelper.move_cursor(r, 2)
            # Overwrite board area with dim characters
            for c in range(BOARD_WIDTH):
# NOTE: 2026-05-30 11:02:53, self-evolved by tea_agent --- Update pause overlay to use 2-char width per cell
                print(f'{ANSI_DIM}··{ANSI_RESET}', end='')
        
        # Pause message
        msg = 'PAUSED'
# NOTE: 2026-05-30 11:03:00, self-evolved by tea_agent --- Update pause message x-coordinate calculation
        x = BOARD_WIDTH * 2 // 2 - len(msg) // 2 + 1
        y = BOARD_HEIGHT // 2 + 1
        ANSIHelper.move_cursor(y, x)
        print(f'{ANSI_BOLD}{msg}{ANSI_RESET}')
    
    def _handle_input(self):
        """Handle user input."""
        key = self.input_handler.get_key()
        
        if key is None:
            return
        
        if self.game_over:
            if key in ('r', 'R'):
                self.__init__()  # Restart game
            return
        
        if self.paused:
            if key in ('p', 'P'):
                self.paused = False
            return
        
        # Game controls
        if key == 'left':
            self._move_piece(0, -1)
        elif key == 'right':
            self._move_piece(0, 1)
        elif key == 'down':
            if self._move_piece(1, 0):
                self.score += 1  # Soft drop bonus
        elif key == 'up':
            self._rotate_piece()
        elif key == ' ':
            self._hard_drop()
        elif key in ('p', 'P'):
            self.paused = True
        elif key in ('q', 'Q'):
            self.game_over = True
    
    def _update(self):
        """Update game state."""
        current_time = time.time()
        
        # Auto-drop
        if current_time - self.last_drop_time >= self.drop_interval:
            self._drop_piece()
            self.last_drop_time = current_time
    
    def run(self):
        """Main game loop."""
        try:
            # Setup terminal
            ANSIHelper.hide_cursor()
            ANSIHelper.clear_screen()  # Clear once at start
            
            self.last_drop_time = time.time()
            
            while not self.game_over:
                # Handle input
                self._handle_input()
                
                # Update game state
                if not self.paused:
                    self._update()
                
                # Draw everything - move cursor to home instead of clearing
                ANSIHelper.move_home()
                self._draw_board()
                self._draw_info()
                self._draw_pause()
                
                # Small delay to prevent high CPU usage
                time.sleep(0.05)
            
            # Game over screen
            ANSIHelper.move_home()
            self._draw_board()
            self._draw_info()
            
            # Wait for restart or quit
            while True:
                key = self.input_handler.get_key()
                if key in ('r', 'R'):
                    self.__init__()
                    self.run()
                    return
                elif key in ('q', 'Q'):
                    return
                time.sleep(0.1)
        
        finally:
            # Cleanup
            ANSIHelper.show_cursor()
            ANSIHelper.reset_color()
            self.input_handler.cleanup()


def main():
    """Main function."""
    print("Starting Tetris...")
    print("Press any key to begin...")
    
    # Wait for a key press to start
    if sys.platform == 'win32':
        msvcrt.getwch()
    else:
        sys.stdin.read(1)
    
    game = TetrisGame()
    game.run()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nGame terminated.")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
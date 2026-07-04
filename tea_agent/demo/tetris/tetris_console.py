#!/usr/bin/env python3
"""
Console Tetris Game
===================
A Python implementation of Tetris for the terminal.
Uses curses for terminal handling.
"""

import curses
import random
import time
import sys
from typing import List, Tuple, Optional

# Game constants
BOARD_WIDTH = 10
BOARD_HEIGHT = 20
CELL_EMPTY = 0
CELL_FILLED = 1
CELL_GHOST = 2

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

# Colors for each piece type
PIECE_COLORS = {
    'I': 1,  # Cyan
    'O': 2,  # Yellow
    'T': 3,  # Purple
    'S': 4,  # Green
    'Z': 5,  # Red
    'J': 6,  # Blue
    'L': 7,  # Orange
}

class TetrisGame:
    """Main Tetris game class."""
    
    def __init__(self, stdscr: curses.window):
        self.stdscr = stdscr
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
        
        # Initialize curses
        curses.curs_set(0)  # Hide cursor
        curses.start_color()
        curses.use_default_colors()
        
        # Initialize color pairs
        self._init_colors()
        
        # Set up non-blocking input
        self.stdscr.nodelay(True)
        self.stdscr.timeout(50)  # 50ms timeout for input
        
        # Generate first pieces
        self.next_piece = self._generate_piece()
        self._spawn_piece()
    
    def _init_colors(self):
        """Initialize color pairs for each piece type."""
        # Define colors: (foreground, background)
        color_map = {
            1: (curses.COLOR_CYAN, -1),      # I
            2: (curses.COLOR_YELLOW, -1),     # O
            3: (curses.COLOR_MAGENTA, -1),    # T
            4: (curses.COLOR_GREEN, -1),      # S
            5: (curses.COLOR_RED, -1),        # Z
            6: (curses.COLOR_BLUE, -1),       # J
            7: (curses.COLOR_WHITE, -1),      # L (actually orange, but white as fallback)
        }
        
        for i, (fg, bg) in color_map.items():
            curses.init_pair(i, fg, bg)
    
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
    
    def _draw_board(self):
        """Draw the game board."""
        # Draw border
        for r in range(BOARD_HEIGHT):
            # Left border
            self.stdscr.addch(r + 1, 0, '|')
            # Right border
            self.stdscr.addch(r + 1, BOARD_WIDTH * 2 + 1, '|')
        
        # Top and bottom borders
        self.stdscr.addstr(0, 0, '+' + '-' * (BOARD_WIDTH * 2) + '+')
        self.stdscr.addstr(BOARD_HEIGHT + 1, 0, '+' + '-' * (BOARD_WIDTH * 2) + '+')
        
        # Draw board cells
        for r in range(BOARD_HEIGHT):
            for c in range(BOARD_WIDTH):
                x = c * 2 + 1
                y = r + 1
                
                if self.board[r][c] == CELL_FILLED:
                    self.stdscr.addstr(y, x, '[]', curses.color_pair(7))
                else:
                    self.stdscr.addstr(y, x, '  ')
        
        # Draw ghost piece (if current piece exists)
        if self.current_piece and not self.game_over:
            ghost_piece = self.current_piece.copy()
            # Find the lowest valid position for ghost
            while self._is_valid_position(ghost_piece, row_offset=1):
                ghost_piece['row'] += 1
            
            # Draw ghost
            ghost_cells = self._get_piece_cells(ghost_piece)
            for r, c in ghost_cells:
                if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
                    x = c * 2 + 1
                    y = r + 1
                    self.stdscr.addstr(y, x, '::', curses.color_pair(7) | curses.A_DIM)
        
        # Draw current piece
        if self.current_piece and not self.game_over:
            cells = self._get_piece_cells(self.current_piece)
            color = PIECE_COLORS.get(self.current_piece['type'], 7)
            for r, c in cells:
                if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
                    x = c * 2 + 1
                    y = r + 1
                    self.stdscr.addstr(y, x, '[]', curses.color_pair(color))
    
    def _draw_info(self):
        """Draw game information panel."""
        info_x = BOARD_WIDTH * 2 + 3
        
        # Score and level
        self.stdscr.addstr(1, info_x, f'Score: {self.score}')
        self.stdscr.addstr(2, info_x, f'Level: {self.level}')
        self.stdscr.addstr(3, info_x, f'Lines: {self.lines_cleared}')
        
        # Next piece preview
        self.stdscr.addstr(5, info_x, 'Next:')
        if self.next_piece:
            # Draw next piece preview
            preview_x = info_x + 2
            preview_y = 6
            rotations = self.next_piece['rotations']
            offsets = rotations[0]  # Show first rotation
            for dr, dc in offsets:
                r = preview_y + dr
                c = preview_x + dc * 2
                self.stdscr.addstr(r, c, '[]', curses.color_pair(PIECE_COLORS.get(self.next_piece['type'], 7)))
        
        # Controls
        self.stdscr.addstr(12, info_x, 'Controls:')
        self.stdscr.addstr(13, info_x, '← → : Move')
        self.stdscr.addstr(14, info_x, '↑    : Rotate')
        self.stdscr.addstr(15, info_x, '↓    : Soft drop')
        self.stdscr.addstr(16, info_x, 'Space: Hard drop')
        self.stdscr.addstr(17, info_x, 'P    : Pause')
        self.stdscr.addstr(18, info_x, 'Q    : Quit')
        
        # Game over
        if self.game_over:
            self.stdscr.addstr(20, info_x, 'GAME OVER!', curses.A_BOLD)
            self.stdscr.addstr(21, info_x, 'Press R to restart')
    
    def _draw_pause(self):
        """Draw pause overlay."""
        if not self.paused:
            return
        
        # Semi-transparent overlay (using dim attribute)
        for r in range(1, BOARD_HEIGHT + 1):
            for c in range(1, BOARD_WIDTH * 2 + 1):
                self.stdscr.chgat(r, c, 1, curses.A_DIM)
        
        # Pause message
        msg = 'PAUSED'
        x = BOARD_WIDTH - len(msg) // 2
        y = BOARD_HEIGHT // 2
        self.stdscr.addstr(y, x, msg, curses.A_BOLD)
    
    def _handle_input(self):
        """Handle user input."""
        try:
            key = self.stdscr.getch()
        except:
            return
        
        if key == -1:
            # No input
            return
        
        if self.game_over:
            if key in (ord('r'), ord('R')):
                self.__init__(self.stdscr)  # Restart game
            return
        
        if self.paused:
            if key in (ord('p'), ord('P')):
                self.paused = False
            return
        
        # Game controls
        if key == curses.KEY_LEFT:
            self._move_piece(0, -1)
        elif key == curses.KEY_RIGHT:
            self._move_piece(0, 1)
        elif key == curses.KEY_DOWN:
            if self._move_piece(1, 0):
                self.score += 1  # Soft drop bonus
        elif key == curses.KEY_UP:
            self._rotate_piece()
        elif key == ord(' '):
            self._hard_drop()
        elif key in (ord('p'), ord('P')):
            self.paused = True
        elif key in (ord('q'), ord('Q')):
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
        self.last_drop_time = time.time()
        
        while not self.game_over:
            # Handle input
            self._handle_input()
            
            # Update game state
            if not self.paused:
                self._update()
            
            # Draw everything
            self.stdscr.erase()
            self._draw_board()
            self._draw_info()
            self._draw_pause()
            self.stdscr.refresh()
            
            # Small delay to prevent high CPU usage
            time.sleep(0.01)
        
        # Game over screen
        self.stdscr.erase()
        self._draw_board()
        self._draw_info()
        self.stdscr.refresh()
        
        # Wait for restart or quit
        while True:
            key = self.stdscr.getch()
            if key in (ord('r'), ord('R')):
                self.__init__(self.stdscr)
                self.run()
                return
            elif key in (ord('q'), ord('Q')):
                return
            time.sleep(0.1)


def main(stdscr: curses.window):
    """Main function."""
    game = TetrisGame(stdscr)
    game.run()


if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nGame terminated.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
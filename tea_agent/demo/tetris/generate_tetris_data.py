#!/usr/bin/env python3
"""
Tetris Training Data Generator (Parallel)
=========================================
Strategy: Full lookahead search. Try ALL rotations x ALL columns,
simulate full drop, evaluate board, pick optimal landing, label
current state with FIRST action needed.

Output: .npz with keys 'images' (N,20,10) and 'actions' (N,)
  0=left, 1=right, 2=rotate, 3=none

Usage:
  python generate_tetris_data.py --games 500 --output data.npz
  python generate_tetris_data.py --games 500 --workers 8 --output data.npz
"""
import sys, os, time, random, argparse, multiprocessing as mp
from functools import partial
from copy import deepcopy
from typing import List, Tuple
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tetris_ansi import TetrisGame, BOARD_WIDTH, BOARD_HEIGHT, CELL_EMPTY, CELL_FILLED, TETROMINOES

# ─── Core Logic ──────────────────────────────────────────────────

def _get_cells(piece):
    rots = piece['rotations']
    ridx = piece['rotation'] % len(rots)
    return [(piece['row']+dr, piece['col']+dc) for dr,dc in rots[ridx]]

def build_state_image(game):
    img = np.zeros((BOARD_HEIGHT, BOARD_WIDTH), dtype=np.float32)
    for r in range(BOARD_HEIGHT):
        for c in range(BOARD_WIDTH):
            if game.board[r][c] == CELL_FILLED:
                img[r,c] = 1.0
    if game.current_piece and not game.game_over:
        for r,c in game._get_piece_cells(game.current_piece):
            if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
                img[r,c] = 0.5
    return img

def evaluate_board(board):
    heights = []
    for c in range(BOARD_WIDTH):
        h = 0
        for r in range(BOARD_HEIGHT):
            if board[r][c] == CELL_FILLED:
                h = BOARD_HEIGHT - r; break
        heights.append(h)
    holes = 0
    for c in range(BOARD_WIDTH):
        found = False
        for r in range(BOARD_HEIGHT):
            if board[r][c] == CELL_FILLED:
                found = True
            elif found:
                holes += 1
    bumpiness = sum(abs(heights[i]-heights[i+1]) for i in range(BOARD_WIDTH-1))
    max_h = max(heights)
    avg_h = sum(heights)/BOARD_WIDTH
    var = sum((h-avg_h)**2 for h in heights)/BOARD_WIDTH
    full = sum(1 for r in range(BOARD_HEIGHT) if all(board[r][c]==CELL_FILLED for c in range(BOARD_WIDTH)))
    wells = 0
    for c in range(1, BOARD_WIDTH-1):
        if heights[c] < heights[c-1]-1 and heights[c] < heights[c+1]-1:
            wells += min(heights[c-1], heights[c+1]) - heights[c]
    return full*1000 - holes*500 - bumpiness*80 - max_h*50 - var*30 - wells*200

def simulate_landing(board, piece):
    tb = [row[:] for row in board]
    tp = deepcopy(piece)
    while True:
        tp['row'] += 1
        ok = True
        for r,c in _get_cells(tp):
            if r >= BOARD_HEIGHT or tb[r][c] == CELL_FILLED:
                ok = False; break
        if not ok:
            tp['row'] -= 1; break
    for r,c in _get_cells(tp):
        if 0 <= r < BOARD_HEIGHT and 0 <= c < BOARD_WIDTH:
            tb[r][c] = CELL_FILLED
    for r in range(BOARD_HEIGHT-1, -1, -1):
        if all(tb[r][c]==CELL_FILLED for c in range(BOARD_WIDTH)):
            del tb[r]
            tb.insert(0, [CELL_EMPTY]*BOARD_WIDTH)
    return tb

def find_best_first_action(game):
    if game.current_piece is None:
        return 3
    p = game.current_piece
    ptype, rots = p['type'], p['rotations']
    nrots, cur_rot, cur_col, cur_row = len(rots), p['rotation'], p['col'], p['row']
    board = game.board
    best_score, best_rot, best_col = float('-inf'), cur_rot, cur_col
    for rot_step in range(nrots):
        new_rot = (cur_rot + rot_step) % nrots
        for col in range(BOARD_WIDTH):
            tp = {'type':ptype,'rotations':rots,'rotation':new_rot,'row':cur_row,'col':col}
            cells = _get_cells(tp)
            valid = True
            for r,c in cells:
                if c < 0 or c >= BOARD_WIDTH or r >= BOARD_HEIGHT:
                    valid = False; break
                if r >= 0 and board[r][c] == CELL_FILLED:
                    valid = False; break
            if not valid:
                continue
            res = simulate_landing(board, tp)
            score = evaluate_board(res)
            if score > best_score:
                best_score, best_rot, best_col = score, new_rot, col
    if best_rot != cur_rot:
        return 2
    elif best_col < cur_col:
        return 0
    elif best_col > cur_col:
        return 1
    return 3

# ─── Headless Game ───────────────────────────────────────────────

class HeadlessTetrisGame(TetrisGame):
    def __init__(self, seed=None):
        self._rng = None
        if seed is not None:
            self._rng = random.Random(seed)
            self._saved = (random.random, random.randint, random.choice)
            random.random = self._rng.random
            random.randint = self._rng.randint
            random.choice = self._rng.choice
        self.board = [[CELL_EMPTY]*BOARD_WIDTH for _ in range(BOARD_HEIGHT)]
        self.current_piece = self.next_piece = None
        self.score = self.level = self.lines_cleared = 0
        self.game_over = self.paused = False
        self.auto_mode = False
        self.drop_interval = 1.0
        self.last_drop_time = 0
        self.input_handler = None
        self.next_piece = self._generate_piece()
        self._spawn_piece()
        if seed is not None:
            random.random, random.randint, random.choice = self._saved
    def _handle_input(self):
        pass
    def run(self):
        pass

# ─── Single Game Worker ──────────────────────────────────────────

def play_one_game(args):
    seed, max_steps = args
    game = HeadlessTetrisGame(seed=seed)
    imgs, acts = [], []
    for _ in range(max_steps):
        if game.game_over:
            break
        imgs.append(build_state_image(game))
        action = find_best_first_action(game)
        acts.append(action)
        if game.current_piece:
            if action == 0:
                game._move_piece(0, -1)
            elif action == 1:
                game._move_piece(0, 1)
            elif action == 2:
                game._rotate_piece()
            game._drop_piece()
    return (np.array(imgs, dtype=np.float32), np.array(acts, dtype=np.int64), game.score, game.lines_cleared, len(imgs))

# ─── Parallel Dataset Generation ─────────────────────────────────

def generate_dataset(num_games=100, max_steps=10000, seed=None, workers=None, verbose=True):
    if workers is None:
        workers = min(mp.cpu_count(), 8)
    base_seed = seed if seed is not None else int(time.time())
    game_args = [(base_seed + i, max_steps) for i in range(num_games)]
    
    if workers > 1:
        with mp.Pool(workers) as pool:
            results = list(pool.imap_unordered(play_one_game, game_args, chunksize=1))
    else:
        results = [play_one_game(arg) for arg in game_args]
    
    all_imgs, all_acts = [], []
    total_samples = 0
    for imgs, acts, score, lines, n in results:
        total_samples += n
        all_imgs.append(imgs)
        all_acts.append(acts)
    
    imgs_np = np.concatenate(all_imgs, axis=0)
    acts_np = np.concatenate(all_acts, axis=0)
    
    if verbose:
        print(f'Total: {num_games} games, {len(imgs_np)} samples, shape {imgs_np.shape}')
        for lbl, nm in [(0,"left"),(1,"right"),(2,"rotate"),(3,"none")]:
            cnt = int(np.sum(acts_np==lbl))
            print(f'  {nm:6s}: {cnt:6d} ({cnt/len(acts_np)*100:5.1f}%)')
    return imgs_np, acts_np

def main():
    p = argparse.ArgumentParser(description='Generate Tetris training data')
    p.add_argument('--games', type=int, default=100, help='Number of games to play')
    p.add_argument('--max-steps', type=int, default=10000, help='Max steps per game')
    p.add_argument('--output', default='tetris_training_data.npz', help='Output .npz file')
    p.add_argument('--seed', type=int, default=None, help='Random seed')
    p.add_argument('--workers', type=int, default=None, help='Parallel workers (default=CPU count)')
    p.add_argument('--quiet', action='store_true')
    args = p.parse_args()
    verbose = not args.quiet
    print(f'Games: {args.games} | Max steps: {args.max_steps} | Workers: {args.workers or "auto"}')
    print(f'Output: {args.output}')
    t0 = time.time()
    imgs, acts = generate_dataset(args.games, args.max_steps, args.seed, args.workers, verbose)
    t = time.time() - t0
    if len(imgs) > 0:
        np.savez_compressed(args.output, images=imgs, actions=acts)
        sz = os.path.getsize(args.output)
        print(f'Saved: {args.output} ({sz/1024/1024:.2f} MB)')
        print(f'Speed: {len(imgs)/t:.0f} samp/s | Time: {t:.2f}s')
    else:
        print('ERROR: No samples!'); sys.exit(1)

if __name__ == '__main__':
    main()

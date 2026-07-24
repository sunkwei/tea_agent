#!/usr/bin/env python3
"""
test_asr_vad.py — VAD inference with Audacity label output

Usage:
    python test_asr_vad.py --label <output.txt> <input.wav>
    python test_asr_vad.py --label n:\\videos\\726\\teacher_vad.txt n:\\videos\\726\\teacher.wav

Audacity label format (tab-separated):
    start_seconds<TAB>end_seconds<TAB>label
"""

import sys
import os
import argparse
import numpy as np
from scipy.io import wavfile

# Add current dir to path for asr_vad import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from asr_vad import VAD


def wav_to_vad_labels(wav_path: str, label_path: str, sil_threshold: float = 0.2):
    """Run VAD on a WAV file and save results as Audacity labels."""
    # Read audio
    sr, audio = wavfile.read(wav_path)
    if sr != 16000:
        print(f'Warning: sample rate is {sr}Hz, resampling to 16000Hz recommended')

    # Normalize to float32 [-1, 1]
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
    elif audio.dtype == np.uint8:
        audio = (audio.astype(np.float32) - 128) / 128.0
    else:
        audio = audio.astype(np.float32)

    total_samples = len(audio)
    duration = total_samples / sr
    chunk_size = sr  # 1 second chunks

    print(f'Input:  {wav_path}')
    print(f'Format: {sr}Hz, {total_samples} samples, {duration:.1f}s ({duration/60:.1f}min)')
    print(f'Output: {label_path}')
    print(f'VAD params: sil_threshold={sil_threshold}')
    print()

    # Process with VAD
    model_dir = os.path.join(os.path.expanduser('~'), '.cache',
        'modelscope', 'hub', 'models', 'iic',
        'speech_fsmn_vad_zh-cn-16k-common-pytorch')

    vad = VAD(model_dir, sil_threshold=sil_threshold)
    all_segments = []

    # Process chunk by chunk with progress
    n_chunks = (total_samples + chunk_size - 1) // chunk_size
    last_pct = -1

    for i in range(0, total_samples, chunk_size):
        chunk = audio[i:i + chunk_size]
        if len(chunk) > 0:
            segs = vad.feed(chunk)
            all_segments.extend(segs)

        # Progress
        pct = int(min(i + chunk_size, total_samples) * 100 / total_samples)
        if pct != last_pct and pct % 5 == 0:
            print(f'  Progress: {pct}% ({len(all_segments)} segments so far)')
            last_pct = pct

    # Finalize
    final_segs = vad.finalize()
    all_segments.extend(final_segs)

    # Merge adjacent / overlapping segments
    merged = _merge_segments(all_segments)
    all_segments = merged

    # Write label file
    with open(label_path, 'w', encoding='utf-8') as f:
        for idx, (start_ms, end_ms) in enumerate(all_segments):
            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0
            label = f'speech_{idx+1:04d}'
            f.write(f'{start_sec:.3f}\t{end_sec:.3f}\t{label}\n')

    # Stats
    total_speech_ms = sum(e - s for s, e in all_segments)
    total_speech_sec = total_speech_ms / 1000.0
    speech_ratio = total_speech_sec / duration if duration > 0 else 0

    print(f'\nDone! {len(all_segments)} segments, '
          f'{total_speech_sec:.1f}s speech ({speech_ratio*100:.1f}%)')
    print(f'Labels saved to: {label_path}')
    print()
    print(f'Segment stats:')
    print(f'  Count:  {len(all_segments)}')
    print(f'  Total:  {total_speech_sec:.1f}s / {duration:.1f}s ({speech_ratio*100:.1f}%)')
    if all_segments:
        durs = [e - s for s, e in all_segments]
        print(f'  Min:    {min(durs)/1000:.2f}s')
        print(f'  Max:    {max(durs)/1000:.2f}s')
        print(f'  Median: {np.median(durs)/1000:.2f}s')
        print(f'  Mean:   {np.mean(durs)/1000:.2f}s')
        print()
        # First 5 segments
        print('First 5 segments:')
        for start_ms, end_ms in all_segments[:5]:
            dur = (end_ms - start_ms) / 1000.0
            print(f'  [{start_ms/1000:.3f}s - {end_ms/1000:.3f}s] ({dur:.1f}s)')


def _merge_segments(segments):
    """Merge overlapping or adjacent segments (<200ms gap)."""
    if len(segments) <= 1:
        return segments

    merged = [list(segments[0])]
    for start, end in segments[1:]:
        prev = merged[-1]
        # If gap <= 200ms, merge
        if start - prev[1] <= 200:
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])
    return [tuple(s) for s in merged]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='VAD inference → Audacity labels')
    parser.add_argument('--label', required=True, help='Output label file path')
    parser.add_argument('wav', help='Input WAV file path')
    parser.add_argument('--threshold', type=float, default=0.2,
                        help='Silence probability threshold (default: 0.2)')
    args = parser.parse_args()

    wav_to_vad_labels(args.wav, args.label, args.threshold)

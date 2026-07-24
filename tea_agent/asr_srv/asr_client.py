#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# @file: asr_client.py
# @brief: ASR WebSocket 测试客户端 — 支持 WAV 文件测试和实时麦克风输入
#
# ============================================================================
#  功能
# ============================================================================
#   1. WebSocket 连接 ASR 服务器 (ws://host:port/asr)
#   2. WAV 文件测试模式: 读取 16kHz mono WAV，分片发送，显示逐句结果
#   3. 实时麦克风模式: 从默认输入设备捕获音频，实时发送和识别
#   4. 支持 partial/final 结果展示，性能统计
#
# ============================================================================
#  用法
# ============================================================================
#   # 实时麦克风测试
#   python asr_client.py --host localhost --port 2311
#
#   # WAV 文件测试
#   python asr_client.py --wav test.wav
#
#   # 指定 chunk 大小 (默认 3200 = 100ms)
#   python asr_client.py --wav test.wav --chunk_ms 200
#
# ============================================================================
#  依赖
# ============================================================================
#   pip install websockets soundfile  (推荐)
#   或 pip install websockets pyaudio (备选)
#
#   # 仅 WAV 模式（无需音频输入库）
#   pip install websockets
#
# ============================================================================
#  Copyright (C) 2026
# ============================================================================

from __future__ import absolute_import, division, print_function

import argparse
import json
import logging
import os
import os.path as osp
import struct
import sys
import time
import traceback

# ── 第三方库检测 ────────────────────────────────────────────────────
try:
    import numpy as np
    HAVE_NP = True
except ImportError:
    HAVE_NP = False

try:
    import websockets as ws_lib
    from websockets.sync.client import connect as ws_connect
    HAVE_WS = True
except ImportError:
    HAVE_WS = False

# ── 音频输入检测 ────────────────────────────────────────────────────
HAVE_SOUNDFILE = False
try:
    import soundfile as sf
    HAVE_SOUNDFILE = True
except ImportError:
    pass

HAVE_PYAUDIO = False
try:
    import pyaudio as pa
    HAVE_PYAUDIO = True
except ImportError:
    pass

HAVE_SOUNDDEVICE = False
try:
    import sounddevice as sd
    HAVE_SOUNDDEVICE = True
except ImportError:
    pass

# ====================================================================
#  日志
# ====================================================================
logger = logging.getLogger("asr_client")
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def init_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ====================================================================
#  常量
# ====================================================================
SAMPLE_RATE = 16000       # 目标采样率 16kHz
SAMPLE_WIDTH = 2          # S16LE = 2 bytes
SAMPLE_CHANNELS = 1       # mono
CHUNK_MS_DEFAULT = 100    # 默认分片大小 (ms)
CHUNK_SIZE_DEFAULT = int(SAMPLE_RATE * CHUNK_MS_DEFAULT / 1000) * SAMPLE_WIDTH  # 3200 bytes


# ====================================================================
#  WAV 文件读取
# ====================================================================
def read_wav(path):
    """读取 WAV 文件，返回 PCM bytes (S16LE, 16kHz, mono)。

    支持任意采样率，自动重采样到 16kHz（需要 numpy/scipy）。
    如果无法重采样，尝试简单降采样。

    Returns:
        (pcm_bytes, sample_rate, duration_sec)
    """
    if HAVE_SOUNDFILE:
        return _read_wav_soundfile(path)
    else:
        return _read_wav_wave(path)


def _read_wav_soundfile(path):
    """使用 soundfile 读取 WAV"""
    data, sr = sf.read(path, dtype='float32')
    if data.ndim > 1:
        data = data.mean(axis=1)  # 转 mono
    # 重采样到 16kHz
    if sr != SAMPLE_RATE:
        logger.info("Resampling %d Hz -> %d Hz", sr, SAMPLE_RATE)
        data = _resample(data, sr, SAMPLE_RATE)
    # 转 S16LE
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16).tobytes()
    return pcm, SAMPLE_RATE, len(data) / SAMPLE_RATE


def _read_wav_wave(path):
    """使用标准库 wave 读取 WAV (仅支持 16kHz)"""
    import wave
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if sr != SAMPLE_RATE or nchannels != 1 or sampwidth != 2:
        logger.warning("WAV: %dHz %dch %dbit — converting to 16kHz mono S16LE",
                       sr, nchannels, sampwidth * 8)
        # 使用 numpy 转换
        dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
        dt = dtype_map.get(sampwidth, np.int16)
        data = np.frombuffer(frames, dtype=dt).astype(np.float32)
        if sampwidth == 1:
            data -= 128.0  # 无符号转有符号
        data /= (1 << (sampwidth * 8 - 1))  # 归一化 [-1, 1]

        if nchannels > 1:
            data = data.reshape(-1, nchannels).mean(axis=1)

        if sr != SAMPLE_RATE:
            data = _resample(data, sr, SAMPLE_RATE)

        data = np.clip(data, -1.0, 1.0)
        pcm = (data * 32767.0).astype(np.int16).tobytes()
    else:
        pcm = frames

    return pcm, SAMPLE_RATE, len(pcm) / (SAMPLE_RATE * SAMPLE_WIDTH)


def _resample(data, orig_sr, target_sr):
    """重采样音频数据（需要 numpy）"""
    if not HAVE_NP:
        logger.error("numpy required for resampling: pip install numpy")
        # 简单降采样（仅支持整数倍）
        if orig_sr > target_sr and orig_sr % target_sr == 0:
            ratio = orig_sr // target_sr
            return data[::ratio]
        raise RuntimeError("Cannot resample without numpy")
    try:
        from scipy.signal import resample as sp_resample
        orig_len = len(data)
        target_len = int(orig_len * target_sr / orig_sr)
        return sp_resample(data, target_len).astype(np.float32)
    except ImportError:
        logger.warning("scipy not available, using linear interpolation")
        # 简单的线性插值重采样
        orig_len = len(data)
        target_len = int(orig_len * target_sr / orig_sr)
        indices = np.linspace(0, orig_len - 1, target_len)
        # floor/ceil 插值
        lo = np.floor(indices).astype(np.int32)
        hi = np.ceil(indices).astype(np.int32)
        hi = np.clip(hi, 0, orig_len - 1)
        frac = (indices - lo).astype(np.float32)
        return data[lo] * (1 - frac) + data[hi] * frac


# ====================================================================
#  WebSocket 客户端
# ====================================================================
class AsrWsClient(object):
    """ASR WebSocket 客户端

    连接到 ASR 服务器的 WebSocket 接口，发送 PCM 数据，接收识别结果。

    用法:
        client = AsrWsClient("ws://localhost:2311/asr")
        client.connect()
        client.send_pcm(pcm_bytes)
        results = client.recv_results(timeout=1.0)
        client.close()
    """

    def __init__(self, url, verbose=False):
        self.url = url
        self.verbose = verbose
        self._ws = None
        self._connected = False
        self._stats = {
            "pcm_sent_bytes": 0,
            "pcm_sent_sec": 0.0,
            "results_recv": 0,
            "final_count": 0,
            "partial_count": 0,
            "start_time": 0,
        }

    def connect(self, timeout=10):
        """连接 WebSocket 服务器"""
        if not HAVE_WS:
            raise RuntimeError("websockets library required: pip install websockets")
        t0 = time.time()
        self._ws = ws_connect(self.url, timeout=timeout)
        self._connected = True
        elapsed = time.time() - t0
        self._stats["start_time"] = time.time()
        logger.info("Connected to %s (%.0fms)", self.url, elapsed * 1000)
        return self

    def close(self):
        """关闭连接"""
        if self._ws and self._connected:
            self._ws.close()
        self._connected = False

    def send_pcm(self, pcm_bytes):
        """发送 PCM 片段（S16LE bytes）"""
        if not self._connected:
            raise RuntimeError("Not connected")
        self._ws.send(pcm_bytes)
        self._stats["pcm_sent_bytes"] += len(pcm_bytes)

    def recv_results(self, timeout=None):
        """接收识别结果列表。

        Args:
            timeout: 超时秒数，None=阻塞，0=非阻塞

        Returns:
            list[dict]: 结果字典列表
        """
        if not self._connected:
            return []
        results = []
        try:
            while True:
                msg = self._ws.recv(timeout=timeout)
                if msg is None:
                    break
                if isinstance(msg, bytes):
                    logger.debug("Unexpected binary message (%d bytes)", len(msg))
                    continue
                try:
                    data = json.loads(msg)
                    results.append(data)
                    self._stats["results_recv"] += 1
                    if data.get("type") == "final":
                        self._stats["final_count"] += 1
                    elif data.get("type") == "partial":
                        self._stats["partial_count"] += 1
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON: %s", msg[:200])
        except ws_lib.exceptions.ConnectionClosed:
            self._connected = False
        except TimeoutError:
            pass
        except Exception as e:
            if "timed out" in str(e).lower() or "timeout" in str(e).lower():
                pass  # 正常超时
            else:
                logger.warning("recv error: %s", e)
        return results

    def print_results(self, results):
        """打印识别结果"""
        for r in results:
            typ = r.get("type", "?")
            text = r.get("text", "")
            begin_ms = r.get("begin_ms", 0)
            end_ms = r.get("end_ms", 0)
            if typ == "partial":
                print(f"\r  \033[34m[{begin_ms:>6d}ms → {end_ms:>6d}ms] \033[33m{text}\033[0m",
                      end="", flush=True)
            elif typ == "final":
                dur = end_ms - begin_ms
                print(f"\r  \033[32m[{begin_ms:>6d}ms → {end_ms:>6d}ms] {text}\033[0m")
            else:
                print(f"  [{typ}] {text}")

    def print_summary(self):
        """打印统计摘要"""
        elapsed = time.time() - self._stats["start_time"]
        pcm_sec = self._stats["pcm_sent_bytes"] / (SAMPLE_RATE * SAMPLE_WIDTH)
        print()
        print("=" * 50)
        print("  ASR Client Summary")
        print("=" * 50)
        print(f"  Audio sent:     {pcm_sec:.2f}s ({self._stats['pcm_sent_bytes']/1024:.0f}KB)")
        print(f"  Elapsed:        {elapsed:.2f}s")
        print(f"  RTF:            {elapsed/max(pcm_sec,0.01):.4f}x")
        print(f"  Results recv:   {self._stats['results_recv']}")
        print(f"    Final:        {self._stats['final_count']}")
        print(f"    Partial:      {self._stats['partial_count']}")
        print("=" * 50)


# ====================================================================
#  WAV 文件测试模式
# ====================================================================
def run_wav_mode(args):
    """WAV 文件测试模式"""
    # 读取 WAV
    logger.info("Loading WAV: %s", args.wav)
    pcm, sr, dur = read_wav(args.wav)
    logger.info("Audio: %.2fs (%d bytes, %dHz)", dur, len(pcm), sr)

    # 连接服务器
    url = f"ws://{args.host}:{args.port}/asr"
    client = AsrWsClient(url, verbose=args.verbose)
    client.connect(timeout=args.timeout)

    # 分片发送
    chunk_size = args.chunk_size
    t_start = time.time()
    sent_samples = 0
    total_samples = len(pcm) // SAMPLE_WIDTH

    for offset in range(0, len(pcm), chunk_size):
        chunk = pcm[offset:offset + chunk_size]
        client.send_pcm(chunk)
        sent_samples += len(chunk) // SAMPLE_WIDTH

        # 接收并打印结果
        results = client.recv_results(timeout=args.recv_timeout)
        client.print_results(results)

        # 进度显示
        progress = sent_samples / total_samples * 100
        elapsed = time.time() - t_start
        if args.verbose and progress % 25 < 1:
            logger.info("Progress: %.0f%% (%.1fs / %.1fs)",
                        progress, elapsed * sent_samples / total_samples, elapsed)

    # 发送结束标记
    logger.info("Sending end marker...")
    client.send_pcm(b"")  # 空 bytes 触发 flush
    time.sleep(0.5)
    results = client.recv_results(timeout=args.recv_timeout)
    client.print_results(results)

    # 等待最终结果
    time.sleep(1.0)
    results = client.recv_results(timeout=args.recv_timeout)
    client.print_results(results)

    elapsed = time.time() - t_start
    logger.info("Done in %.2fs", elapsed)

    # 统计
    client.print_summary()
    client.close()


# ====================================================================
#  实时麦克风模式
# ====================================================================
def run_mic_mode(args):
    """实时麦克风测试模式"""
    url = f"ws://{args.host}:{args.port}/asr"

    logger.info("=" * 50)
    logger.info("Microphone mode")
    logger.info("  Server:  %s", url)
    logger.info("  Device:  default input")
    logger.info("  Format:  %dHz, mono, S16LE", SAMPLE_RATE)
    logger.info("  Chunk:   %dms (%d bytes)", args.chunk_ms, args.chunk_size)
    logger.info("=" * 50)
    logger.info("Press Ctrl+C to stop")

    # 选择音频后端
    if HAVE_SOUNDDEVICE:
        _run_mic_sounddevice(args, url)
    elif HAVE_PYAUDIO:
        _run_mic_pyaudio(args, url)
    else:
        logger.error("No audio input library available!")
        logger.error("Install one of: pip install sounddevice  or  pip install pyaudio")
        sys.exit(1)


def _run_mic_sounddevice(args, url):
    """使用 sounddevice 的麦克风输入"""
    import sounddevice as sd

    # 获取设备信息
    device_info = sd.query_devices(kind='input')
    logger.info("Input device: %s", device_info['name'] if device_info else "default")

    client = AsrWsClient(url, verbose=args.verbose)
    client.connect(timeout=args.timeout)

    def audio_callback(indata, frames, callback_time, status):
        """sounddevice 回调：将音频帧发送到服务器"""
        if status:
            logger.debug("Audio status: %s", status)
        # indata 是 float32 [-1, 1], shape (frames, channels)
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata.mean(axis=1)
        else:
            mono = indata.flatten()
        # 转 S16LE
        pcm = (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        try:
            client.send_pcm(pcm)
            results = client.recv_results(timeout=0.01)
            client.print_results(results)
        except Exception as e:
            logger.error("Send error: %s", e)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32',
            blocksize=args.chunk_samples,
            callback=audio_callback,
        ):
            logger.info("Listening... (press Ctrl+C to stop)")
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Stopped by user")
    except Exception as e:
        logger.error("Audio error: %s", traceback.format_exc())

    # 结束
    client.send_pcm(b"")
    time.sleep(1.0)
    results = client.recv_results(timeout=args.recv_timeout)
    client.print_results(results)
    client.print_summary()
    client.close()


def _run_mic_pyaudio(args, url):
    """使用 pyaudio 的麦克风输入"""
    import pyaudio as pa

    client = AsrWsClient(url, verbose=args.verbose)
    client.connect(timeout=args.timeout)

    p = pa.PyAudio()

    # 打开默认输入设备
    try:
        stream = p.open(
            format=pa.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=args.chunk_samples,
            stream_callback=None,  # 阻塞模式
        )
    except Exception as e:
        logger.error("Failed to open audio input: %s", e)
        logger.error("Try: pip install sounddevice  (more compatible)")
        client.close()
        p.terminate()
        sys.exit(1)

    logger.info("Listening... (press Ctrl+C to stop)")

    try:
        while True:
            data = stream.read(args.chunk_samples, exception_on_overflow=False)
            client.send_pcm(data)
            results = client.recv_results(timeout=0.01)
            client.print_results(results)
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Stopped by user")
    except Exception as e:
        logger.error("Error: %s", traceback.format_exc())

    stream.stop_stream()
    stream.close()
    p.terminate()
    client.send_pcm(b"")
    time.sleep(1.0)
    results = client.recv_results(timeout=args.recv_timeout)
    client.print_results(results)
    client.print_summary()
    client.close()


# ====================================================================
#  CLI
# ====================================================================
def main():
    ap = argparse.ArgumentParser(
        description="ASR WebSocket 测试客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 实时麦克风测试（默认模式）
  python asr_client.py

  # 指定服务器地址
  python asr_client.py --host 192.168.1.100 --port 2311

  # WAV 文件测试
  python asr_client.py --wav test.wav

  # WAV 文件 + 指定分片大小
  python asr_client.py --wav test.wav --chunk_ms 200

  # 详细模式
  python asr_client.py --wav test.wav --verbose
""",
    )

    # ── 服务器连接 ──
    ap.add_argument("--host", type=str, default="localhost",
                    help="ASR 服务器地址 (default: localhost)")
    ap.add_argument("--port", type=int, default=2311,
                    help="ASR 服务器端口 (default: 2311)")

    # ── 输入源 ──
    ap.add_argument("--wav", type=str, default=None,
                    help="WAV 文件路径（指定后使用文件测试，否则使用麦克风）")

    # ── 音频参数 ──
    ap.add_argument("--chunk_ms", type=int, default=CHUNK_MS_DEFAULT,
                    help="分片大小 (ms, default: %d)" % CHUNK_MS_DEFAULT)
    ap.add_argument("--recv_timeout", type=float, default=0.05,
                    help="接收结果超时 (秒, default: 0.05)")

    # ── 其它 ──
    ap.add_argument("--timeout", type=int, default=10,
                    help="连接超时 (秒, default: 10)")
    ap.add_argument("--verbose", action="store_true",
                    help="详细日志")
    ap.add_argument("--debug", action="store_true",
                    help="调试日志")

    args = ap.parse_args()

    # 计算分片大小
    args.chunk_samples = int(SAMPLE_RATE * args.chunk_ms / 1000)
    args.chunk_size = args.chunk_samples * SAMPLE_WIDTH

    # 日志级别
    if args.debug:
        init_logging(logging.DEBUG)
    elif args.verbose:
        init_logging(logging.INFO)
    else:
        init_logging(logging.WARNING)

    # 检查依赖
    if not HAVE_WS:
        logger.error("websockets library required!")
        logger.error("  pip install websockets")
        sys.exit(1)

    # 运行模式
    if args.wav:
        run_wav_mode(args)
    else:
        run_mic_mode(args)


if __name__ == "__main__":
    main()

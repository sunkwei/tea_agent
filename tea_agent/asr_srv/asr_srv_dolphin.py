#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# @file: asr_srv_dolphin.py
# @brief: 单文件 ASR WebSocket 服务 — 基于 Dolphin Base (DataoceanAI) ONNX 模型的流式语音识别
#
# ============================================================================
#  特性
# ============================================================================
#   - 单文件，零外部模块依赖（VAD + ASR 引擎 + WebSocket 服务全部内嵌）
#   - 基于 do_asr_dolphin.py 的真实 Dolphin Base ONNX 模型（非模拟引擎）
#   - VAD 基于 do_asr_onnx_sv.py 的共享 VAD 实现
#   - Tornado WebSocket 接口，接收 PCM (16kHz, mono, S16LE) 片段
#   - 标点感知断句：当 CTC 输出包含句尾标点时返回"final"结果
#   - 流式非自回归：E-Branchformer 编码器 + CTC 贪心搜索
#   - 智能分片：长语音段自动在标点处切分返回
#
# ============================================================================
#  协议
# ============================================================================
#   Client → Server: binary 帧 (PCM S16LE, 16kHz, mono)
#   Server → Client: JSON 帧
#     {"type":"partial","text":"...","begin_ms":int,"end_ms":int}
#     {"type":"final","text":"...","begin_ms":int,"end_ms":int}
#     {"type":"error","message":"..."}
#
# ============================================================================
#  模型文件 (默认 ../pred/model/dolphin/)
# ============================================================================
#   dolphin_base_frontend.onnx        (FBank → LFR → CMVN)
#   dolphin_base_encoder_ctc_u8.onnx  (E-Branchformer encoder + CTC head, INT8)
#   bpe.model                         (SentencePiece BPE model)
#   units.txt                         (symbol table, 40002 units)
#
# ============================================================================
#  用法
# ============================================================================
#   python asr_srv_dolphin.py --port 2311
#   python asr_srv_dolphin.py --port 2311 --model_dir ./model/dolphin
#   python asr_srv_dolphin.py --port 2311 --debug
#
#   # 测试（需 websocat 或浏览器）:
#   # websocat ws://localhost:2311/asr < 16k_mono_s16le.pcm
#
# ============================================================================
#  依赖 (pip install)
# ============================================================================
#   pip install tornado numpy onnxruntime sentencepiece kaldi-native-fbank
#
# ============================================================================
#  Copyright (C) 2026
# ============================================================================

from __future__ import absolute_import, division, print_function

import argparse
import base64
import gc
import json
import logging
import math
import os
import os.path as osp
import queue
import re
import struct
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

# ── 第三方库 ──────────────────────────────────────────────────────
try:
    import onnxruntime as ort
    HAVE_ORT = True
except ImportError:
    HAVE_ORT = False

try:
    import sentencepiece as spm
    HAVE_SPM = True
except ImportError:
    HAVE_SPM = False

try:
    import kaldi_native_fbank as knf
    HAVE_KNF = True
except ImportError:
    HAVE_KNF = False

try:
    import tornado.httpserver
    import tornado.ioloop
    import tornado.web
    import tornado.websocket
    import tornado.gen
    HAVE_TORNADO = True
except ImportError:
    HAVE_TORNADO = False

# ============================================================================
#  日志
# ============================================================================
logger = logging.getLogger("asr_srv_dolphin")
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def _init_logging(level=logging.INFO, log_file=None):
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=3))
    logging.basicConfig(level=level, format=LOG_FORMAT,
                        datefmt=LOG_DATE_FORMAT, handlers=handlers)
    logging.getLogger("tornado.access").setLevel(logging.WARNING)
    logging.getLogger("tornado.application").setLevel(logging.WARNING)


# ============================================================================
#  常量
# ============================================================================
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # S16LE = 2 bytes
BLANK_ID = 0

SCRIPT_DIR = osp.dirname(osp.abspath(__file__))
DEFAULT_MODEL_DIR = osp.join(SCRIPT_DIR, "model", "dolphin")
DEFAULT_VAD_PARENT_DIR = osp.join(SCRIPT_DIR, "model")

ORT_PROVIDERS = ["CPUExecutionProvider"]

# ── 句尾标点（Dolphin CTC 输出中包含的标点 token IDs）──
# 来自 do_asr_dolphin.PUNC_IDS: {1827, 1828, 1833, 1835, 1836, 1876}
# 对应 。, ? . 、 !
PUNC_FINAL_IDS = {1827, 1828, 1833, 1835, 1836, 1876}
PUNC_FINAL_CHARS = {"。", "！", "？", ".", "!", "?", "、", "，"}


# ============================================================================
#  辅助函数
# ============================================================================

def _read_yaml(yaml_path):
    """读取 YAML 文件。"""
    if not osp.exists(yaml_path):
        raise FileExistsError("YAML not found: %s" % yaml_path)
    with open(yaml_path, "rb") as f:
        import yaml as _yaml
        return _yaml.load(f, Loader=_yaml.Loader)


def _pcm_s16le_to_f32(pcm_bytes):
    """PCM S16LE bytes → float32 numpy [-1, 1]"""
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    arr /= 32768.0
    return np.clip(arr, -1.0, 1.0)


def _get_rss_mb():
    """获取当前 RSS 内存 (MB)。"""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


# ============================================================================
#  ═══════════════════════════════════════════════════════════════════════════
#  SECTION 1: VAD — 语音活动检测（来自 do_asr_onnx_sv.py）
#  ═══════════════════════════════════════════════════════════════════════════
# ============================================================================

class _AudioChangeState(Enum):
    kChangeStateSpeech2Speech = 0
    kChangeStateSpeech2Sil = 1
    kChangeStateSil2Sil = 2
    kChangeStateSil2Speech = 3
    kChangeStateNoBegin = 4
    kChangeStateInvalid = 5


class _VadStateMachine(Enum):
    kVadInStateStartPointNotDetected = 1
    kVadInStateInSpeechSegment = 2
    kVadInStateEndPointDetected = 3


class _FrameState(Enum):
    kFrameStateInvalid = -1
    kFrameStateSpeech = 1
    kFrameStateSil = 0


class _VadDetectMode(Enum):
    kVadSingleUtteranceDetectMode = 0
    kVadMutipleUtteranceDetectMode = 1


class _VADXOptions(object):
    """VAD 配置选项。"""

    def __init__(self, **kwargs):
        defaults = dict(
            sample_rate=16000, detect_mode=1, snr_mode=0,
            max_end_silence_time=800, max_start_silence_time=3000,
            do_start_point_detection=True, do_end_point_detection=True,
            window_size_ms=200, sil_to_speech_time_thres=150,
            speech_to_sil_time_thres=150, speech_2_noise_ratio=1.0,
            do_extend=1, lookback_time_start_point=200,
            lookahead_time_end_point=100, max_single_segment_time=60000,
            snr_thres=-100, noise_frame_num_used_for_snr=100,
            decibel_thres=-100, speech_noise_thres=0.6,
            fe_prior_thres=1e-4, silence_pdf_num=1, sil_pdf_ids=[0],
            speech_noise_thresh_low=-0.1, speech_noise_thresh_high=0.3,
            output_frame_probs=False, frame_in_ms=10, frame_length_ms=25,
        )
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


class _E2EVadSpeechBufWithDoa(object):
    """VAD 语音段缓冲区。"""

    def __init__(self):
        self.start_ms = 0
        self.end_ms = 0
        self.buffer = []
        self.contain_seg_start_point = False
        self.contain_seg_end_point = False
        self.doa = 0

    def Reset(self):
        self.__init__()


class _WindowDetector(object):
    """滑窗状态检测器。"""

    def __init__(self, window_size_ms, sil_to_speech_time,
                 speech_to_sil_time, frame_size_ms):
        self.win_size_frame = int(window_size_ms / frame_size_ms)
        self.win_sum = 0
        self.win_state = [0] * self.win_size_frame
        self.cur_win_pos = 0
        self.pre_frame_state = _FrameState.kFrameStateSil
        self.sil_to_speech_th = int(sil_to_speech_time / frame_size_ms)
        self.speech_to_sil_th = int(speech_to_sil_time / frame_size_ms)

    def Reset(self):
        self.win_sum = 0
        self.win_state = [0] * self.win_size_frame
        self.cur_win_pos = 0
        self.pre_frame_state = _FrameState.kFrameStateSil

    def DetectOneFrame(self, frame_state, frame_count):
        val = 1 if frame_state == _FrameState.kFrameStateSpeech else 0
        self.win_sum -= self.win_state[self.cur_win_pos]
        self.win_sum += val
        self.win_state[self.cur_win_pos] = val
        self.cur_win_pos = (self.cur_win_pos + 1) % self.win_size_frame

        if self.pre_frame_state == _FrameState.kFrameStateSil and \
                self.win_sum >= self.sil_to_speech_th:
            self.pre_frame_state = _FrameState.kFrameStateSpeech
            return _AudioChangeState.kChangeStateSil2Speech
        if self.pre_frame_state == _FrameState.kFrameStateSpeech and \
                self.win_sum <= self.speech_to_sil_th:
            self.pre_frame_state = _FrameState.kFrameStateSil
            return _AudioChangeState.kChangeStateSpeech2Sil
        if self.pre_frame_state == _FrameState.kFrameStateSil:
            return _AudioChangeState.kChangeStateSil2Sil
        return _AudioChangeState.kChangeStateSpeech2Speech


class _E2EVadModel(object):
    """VAD 状态机 — FunASR E2EVad 兼容。"""

    def __init__(self, vad_post_args):
        self.vad_opts = _VADXOptions(**vad_post_args)
        self.windows_detector = _WindowDetector(
            self.vad_opts.window_size_ms,
            self.vad_opts.sil_to_speech_time_thres,
            self.vad_opts.speech_to_sil_time_thres,
            self.vad_opts.frame_in_ms)
        self.reset_all()

    def reset_all(self):
        self.is_final = False
        self.data_buf_start_frame = 0
        self.frm_cnt = 0
        self.latest_confirmed_speech_frame = 0
        self.lastest_confirmed_silence_frame = -1
        self.continous_silence_frame_count = 0
        self.vad_state_machine = _VadStateMachine.kVadInStateStartPointNotDetected
        self.confirmed_start_frame = -1
        self.confirmed_end_frame = -1
        self.number_end_time_detected = 0
        self.sil_frame = 0
        self.sil_pdf_ids = self.vad_opts.sil_pdf_ids
        self.noise_average_decibel = -100.0
        self.pre_end_silence_detected = False
        self.next_seg = True
        self.output_data_buf = []
        self.output_data_buf_offset = 0
        self.frame_probs = []
        self.max_end_sil_frame_cnt_thresh = (
            self.vad_opts.max_end_silence_time -
            self.vad_opts.speech_to_sil_time_thres)
        self.speech_noise_thres = self.vad_opts.speech_noise_thres
        self.scores = np.empty((1, 0), np.float32)
        self.idx_pre_chunk = 0
        self.max_time_out = False
        self.decibel = []
        self.data_buf_size = 0
        self.data_buf_all_size = 0
        self.waveform = np.empty((1, 0), np.float32)
        self._reset_detection()

    def _reset_detection(self):
        self.continous_silence_frame_count = 0
        self.latest_confirmed_speech_frame = 0
        self.lastest_confirmed_silence_frame = -1
        self.confirmed_start_frame = -1
        self.confirmed_end_frame = -1
        self.vad_state_machine = _VadStateMachine.kVadInStateStartPointNotDetected
        self.windows_detector.Reset()
        self.sil_frame = 0
        self.frame_probs = []

    def compute_decibel(self):
        frame_shift = int(self.vad_opts.frame_in_ms *
                          self.vad_opts.sample_rate / 1000)
        frame_len = int(self.vad_opts.frame_length_ms *
                        self.vad_opts.sample_rate / 1000)
        already = len(self.decibel)
        total_frames = (self.waveform.shape[1] - frame_len) // frame_shift + 1
        start_offset = already * frame_shift
        for offset in range(start_offset,
                            total_frames * frame_shift, frame_shift):
            seg = self.waveform[0, offset:offset + frame_len]
            sq = np.square(seg).sum()
            self.decibel.append(10 * math.log10(sq + 1e-6))

    def compute_scores(self, scores):
        self.vad_opts.nn_eval_block_size = scores.shape[1]
        self.frm_cnt += scores.shape[1]
        self.scores = scores

    def __call__(self, score, waveform, is_final=False,
                 max_end_sil=800, online=False):
        self.max_end_sil_frame_cnt_thresh = (
            max_end_sil - self.vad_opts.speech_to_sil_time_thres)
        self.waveform = waveform
        self.compute_decibel()
        self.compute_scores(score)
        if not is_final:
            self._detect_common()
        else:
            self._detect_last()
        segments = self._collect_segments(is_final, online)
        if is_final:
            self.reset_all()
        return segments

    def _collect_segments(self, is_final, online):
        segments = []
        for i in range(self.output_data_buf_offset, len(self.output_data_buf)):
            buf = self.output_data_buf[i]
            if online:
                if not buf.contain_seg_start_point:
                    continue
                if not self.next_seg and not buf.contain_seg_end_point:
                    continue
                start_ms = buf.start_ms if self.next_seg else -1
                if buf.contain_seg_end_point:
                    end_ms = buf.end_ms
                    self.next_seg = True
                    self.output_data_buf_offset += 1
                else:
                    end_ms = -1
                    self.next_seg = False
            else:
                if not is_final and (not buf.contain_seg_start_point or
                                     not buf.contain_seg_end_point):
                    continue
                start_ms = buf.start_ms
                end_ms = buf.end_ms
                self.output_data_buf_offset += 1
            segments.append([start_ms, end_ms])
        return segments

    def _detect_common(self):
        if self.vad_state_machine == _VadStateMachine.kVadInStateEndPointDetected:
            return
        for i in range(self.vad_opts.nn_eval_block_size - 1, -1, -1):
            state = self._get_frame_state(self.frm_cnt - 1 - i)
            self._detect_one_frame(state, self.frm_cnt - 1 - i, False)
        self.idx_pre_chunk += self.scores.shape[1]

    def _detect_last(self):
        if self.vad_state_machine == _VadStateMachine.kVadInStateEndPointDetected:
            return
        for i in range(self.vad_opts.nn_eval_block_size - 1, -1, -1):
            cur_idx = self.frm_cnt - 1 - i
            state = self._get_frame_state(cur_idx)
            self._detect_one_frame(state, cur_idx, i == 0)

    def _get_frame_state(self, t):
        decibel_ok = t < len(self.decibel)
        cur_db = self.decibel[t] if decibel_ok else -100.0
        if decibel_ok and cur_db < self.vad_opts.decibel_thres:
            return _FrameState.kFrameStateSil
        sil_pdf_scores = [self.scores[0, t - self.idx_pre_chunk, sid]
                          for sid in self.sil_pdf_ids]
        noise_prob = math.log(sum(sil_pdf_scores)) * \
            self.vad_opts.speech_2_noise_ratio
        speech_prob = math.log(1.0 - sum(sil_pdf_scores))
        if math.exp(speech_prob) >= math.exp(noise_prob) + \
                self.speech_noise_thres:
            if not decibel_ok or cur_db - self.noise_average_decibel >= \
                    self.vad_opts.snr_thres:
                return _FrameState.kFrameStateSpeech
            return _FrameState.kFrameStateSil
        else:
            if decibel_ok:
                if self.noise_average_decibel < -99.9:
                    self.noise_average_decibel = cur_db
                else:
                    self.noise_average_decibel = (
                        cur_db + self.noise_average_decibel *
                        (self.vad_opts.noise_frame_num_used_for_snr - 1)
                    ) / self.vad_opts.noise_frame_num_used_for_snr
            return _FrameState.kFrameStateSil

    def _pop_to_output(self, start_frm, frm_cnt, first_is_start,
                       last_is_end, end_is_sent):
        if not self.output_data_buf or first_is_start:
            buf = _E2EVadSpeechBufWithDoa()
            buf.start_ms = start_frm * self.vad_opts.frame_in_ms
            buf.end_ms = buf.start_ms
            self.output_data_buf.append(buf)
        cur = self.output_data_buf[-1]
        cur.end_ms = (start_frm + frm_cnt) * self.vad_opts.frame_in_ms
        if first_is_start:
            cur.contain_seg_start_point = True
        if last_is_end:
            cur.contain_seg_end_point = True

    def _on_silence_detected(self, valid_frame):
        self.lastest_confirmed_silence_frame = valid_frame

    def _on_voice_detected(self, valid_frame):
        self.latest_confirmed_speech_frame = valid_frame
        self._pop_to_output(valid_frame, 1, False, False, False)

    def _on_voice_start(self, start_frame, fake=False):
        self.confirmed_start_frame = start_frame
        if not fake and self.vad_state_machine == \
                _VadStateMachine.kVadInStateStartPointNotDetected:
            self._pop_to_output(start_frame, 1, True, False, False)

    def _on_voice_end(self, end_frame, fake=False, is_last=False):
        self.confirmed_end_frame = end_frame
        if not fake:
            self._pop_to_output(end_frame, 1, False, True, is_last)
        self.number_end_time_detected += 1

    def _detect_one_frame(self, cur_state, cur_idx, is_final_frame):
        tmp_state = (_FrameState.kFrameStateSpeech
                     if cur_state == _FrameState.kFrameStateSpeech
                     else _FrameState.kFrameStateSil)
        change = self.windows_detector.DetectOneFrame(tmp_state, cur_idx)
        frm_ms = self.vad_opts.frame_in_ms

        if change == _AudioChangeState.kChangeStateSil2Speech:
            self.continous_silence_frame_count = 0
            if self.vad_state_machine == \
                    _VadStateMachine.kVadInStateStartPointNotDetected:
                start = max(
                    self.data_buf_start_frame,
                    cur_idx - self.windows_detector.win_size_frame - 20)
                self._on_voice_start(start)
                self.vad_state_machine = \
                    _VadStateMachine.kVadInStateInSpeechSegment
                for t in range(start + 1, cur_idx + 1):
                    self._on_voice_detected(t)
        elif change == _AudioChangeState.kChangeStateSpeech2Sil:
            self.continous_silence_frame_count = 0
            if self.vad_state_machine == \
                    _VadStateMachine.kVadInStateInSpeechSegment:
                if not is_final_frame:
                    self._on_voice_detected(cur_idx)
        elif change == _AudioChangeState.kChangeStateSpeech2Speech:
            self.continous_silence_frame_count = 0
            if self.vad_state_machine == \
                    _VadStateMachine.kVadInStateInSpeechSegment:
                if not is_final_frame:
                    self._on_voice_detected(cur_idx)
        elif change == _AudioChangeState.kChangeStateSil2Sil:
            self.continous_silence_frame_count += 1
            if self.vad_state_machine == \
                    _VadStateMachine.kVadInStateInSpeechSegment:
                if self.continous_silence_frame_count * frm_ms >= \
                        self.max_end_sil_frame_cnt_thresh:
                    self._on_voice_end(cur_idx - 3, False)
                    self.vad_state_machine = \
                        _VadStateMachine.kVadInStateEndPointDetected

        if self.vad_state_machine == \
                _VadStateMachine.kVadInStateEndPointDetected and \
                self.vad_opts.detect_mode == \
                _VadDetectMode.kVadMutipleUtteranceDetectMode.value:
            self._reset_detection()


class _WavFrontend(object):
    """离线前端: fbank → LFR → CMVN → 560-dim features。"""

    def __init__(self, cmvn_file=None, fs=16000, window="hamming",
                 n_mels=80, frame_length=25, frame_shift=10,
                 lfr_m=7, lfr_n=6, dither=0.0, **kwargs):
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = fs
        opts.frame_opts.dither = dither
        opts.frame_opts.window_type = window
        opts.frame_opts.frame_shift_ms = float(frame_shift)
        opts.frame_opts.frame_length_ms = float(frame_length)
        opts.mel_opts.num_bins = n_mels
        opts.energy_floor = 0
        opts.frame_opts.snip_edges = True
        opts.mel_opts.debug_mel = False
        self.opts = opts
        self.lfr_m = lfr_m
        self.lfr_n = lfr_n
        self.cmvn_file = cmvn_file
        self.cmvn = None
        if self.cmvn_file and osp.exists(self.cmvn_file):
            self.cmvn = self._load_cmvn()

    def fbank(self, waveform):
        """提取 FBank 特征 (80-dim)。"""
        waveform = waveform * (1 << 15)
        fbank_fn = knf.OnlineFbank(self.opts)
        fbank_fn.accept_waveform(
            self.opts.frame_opts.samp_freq, waveform.tolist())
        frames = fbank_fn.num_frames_ready
        mat = np.empty([frames, self.opts.mel_opts.num_bins], np.float32)
        for i in range(frames):
            mat[i, :] = fbank_fn.get_frame(i)
        return mat.astype(np.float32), np.array(frames, np.int32)

    def lfr_cmvn(self, feat):
        """LFR + CMVN → 560-dim features。"""
        if self.lfr_m != 1 or self.lfr_n != 1:
            feat = self._apply_lfr(feat)
        if self.cmvn is not None:
            feat = self._apply_cmvn(feat)
        return feat.astype(np.float32), np.array(feat.shape[0], np.int32)

    def _apply_lfr(self, inputs):
        m, n = self.lfr_m, self.lfr_n
        T = inputs.shape[0]
        T_lfr = int(np.ceil(T / n))
        left_pad = np.tile(inputs[0], ((m - 1) // 2, 1))
        inp = np.vstack((left_pad, inputs))
        T_pad = T + (m - 1) // 2
        out = []
        for i in range(T_lfr):
            if m <= T_pad - i * n:
                out.append(inp[i * n:i * n + m].reshape(1, -1))
            else:
                frame = inp[i * n:].reshape(-1)
                for _ in range(m - (T_pad - i * n)):
                    frame = np.hstack((frame, inp[-1]))
                out.append(frame)
        return np.vstack(out).astype(np.float32)

    def _apply_cmvn(self, inputs):
        frame, dim = inputs.shape
        means = np.tile(self.cmvn[0:1, :dim], (frame, 1))
        vars_ = np.tile(self.cmvn[1:2, :dim], (frame, 1))
        return (inputs + means) * vars_

    def _load_cmvn(self):
        with open(self.cmvn_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        means_list, vars_list = [], []
        for i in range(len(lines)):
            items = lines[i].split()
            if items[0] == "<AddShift>":
                items = lines[i + 1].split()
                if items[0] == "<LearnRateCoef>":
                    means_list = list(map(float, items[3:-1]))
            elif items[0] == "<Rescale>":
                items = lines[i + 1].split()
                if items[0] == "<LearnRateCoef>":
                    vars_list = list(map(float, items[3:-1]))
        return np.array([means_list, vars_list], np.float64)

    def get_features(self, waveform):
        """完整流程: fbank → LFR → CMVN。"""
        fbank, _ = self.fbank(waveform)
        return self._apply_cmvn(self._apply_lfr(fbank))


class _VADImpl(object):
    """ONNX VAD 推理 + 在线状态机。"""

    def __init__(self, model_dir, max_end_sil=300):
        vad_dir = osp.join(str(model_dir), "vad")
        model_file = osp.join(vad_dir, "vad.onnx")
        if not osp.exists(model_file):
            raise FileNotFoundError("VAD model not found: %s" % model_file)
        config_file = osp.join(vad_dir, "config.yaml")
        cmvn_file = osp.join(vad_dir, "am.mvn")
        self.config = _read_yaml(config_file)
        self.cmvn_file = cmvn_file
        self.ort_infer = ort.InferenceSession(
            model_file, providers=["CPUExecutionProvider"])
        self.ort_inp_keys = [k.name for k in self.ort_infer.get_inputs()]
        self.max_end_sil = max_end_sil if max_end_sil is not None \
            else self.config["model_conf"]["max_end_silence_time"]
        self.encoder_conf = self.config["encoder_conf"]
        if self.config["model_conf"]["max_single_segment_time"] > 10000:
            self.config["model_conf"]["max_single_segment_time"] = 10000
        self.__last_begin = -1
        self.vad_scorer = _E2EVadModel(self.config["model_conf"])
        self.frontend = _WavFrontend(
            cmvn_file=self.cmvn_file, **self.config["frontend_conf"])
        self._param_dict = {"in_cache": []}

    def _prepare_cache(self, in_cache=None):
        if in_cache is None:
            in_cache = []
        if in_cache:
            return in_cache
        fsmn_layers = self.encoder_conf["fsmn_layers"]
        proj_dim = self.encoder_conf["proj_dim"]
        lorder = self.encoder_conf["lorder"]
        return [np.zeros((1, proj_dim, lorder - 1, 1), np.float32)
                for _ in range(fsmn_layers)]

    def reset(self):
        self._param_dict = {"in_cache": []}
        self.__last_begin = -1
        self.frontend = _WavFrontend(
            cmvn_file=self.cmvn_file, **self.config["frontend_conf"])
        self.vad_scorer = _E2EVadModel(self.config["model_conf"])

    def __call__(self, audio_in, is_final=False, enable_open_seg=False):
        waveforms = np.expand_dims(audio_in, axis=0)
        feats, feats_len = self._extract_feat(waveforms, is_final)
        segments = []
        if feats.size != 0:
            in_cache = self._prepare_cache(self._param_dict.get("in_cache"))
            try:
                inputs = [feats] + in_cache
                scores, *out_caches = self.ort_infer.run(
                    None,
                    {k: v for k, v in zip(self.ort_inp_keys, inputs)})
                self._param_dict["in_cache"] = out_caches
                segments = self.vad_scorer(
                    scores, waveforms, is_final=is_final,
                    max_end_sil=self.max_end_sil, online=True)
                if not is_final:
                    self.frontend = _WavFrontend(
                        cmvn_file=self.cmvn_file,
                        **self.config["frontend_conf"])
            except Exception as e:
                logger.warning("VAD infer error: %s", e, exc_info=True)
                segments = []

        if not enable_open_seg and segments:
            segs = []
            for begin, end in segments:
                if begin == -1:
                    if self.__last_begin >= 0 and end > self.__last_begin:
                        begin = self.__last_begin
                    else:
                        continue
                elif end == -1:
                    if is_final:
                        end = int(len(audio_in) / 16000 * 1000)
                    else:
                        self.__last_begin = begin
                        continue
                segs.append([begin, end])
            segments = segs
        return segments

    def _extract_feat(self, waveforms, is_final=False):
        wav = waveforms[0]
        feat, _ = self.frontend.fbank(wav)
        feat, _ = self.frontend.lfr_cmvn(feat)
        return np.expand_dims(feat, 0), np.array([feat.shape[0]], np.int32)


# ============================================================================
#  ═══════════════════════════════════════════════════════════════════════════
#  SECTION 2: Dolphin ASR 引擎（来自 do_asr_dolphin.py）
#  ═══════════════════════════════════════════════════════════════════════════
# ============================================================================

# ── Tokenizer ──────────────────────────────────────────────────────────

class DolphinTokenizer(object):
    """Dolphin BPE tokenizer (SentencePiece + symbol table)."""

    def __init__(self, model_dir):
        units_path = osp.join(model_dir, "units.txt")
        bpe_path = osp.join(model_dir, "bpe.model")
        self._id2token = {}
        self._token2id = {}
        with open(units_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    tok, idx = parts[0], int(parts[1])
                    self._id2token[idx] = tok
                    self._token2id[tok] = idx
        self.vocab_size = len(self._id2token)
        self.sp = None
        if osp.exists(bpe_path):
            if not HAVE_SPM:
                raise ImportError(
                    "sentencepiece is required for Dolphin tokenizer. "
                    "pip install sentencepiece")
            self.sp = spm.SentencePieceProcessor()
            self.sp.load(bpe_path)
        self.bpe_path = bpe_path

    def ids2tokens(self, ids):
        return [self._id2token.get(i, "<unk>") for i in ids]

    def tokens2text(self, tokens):
        text = ""
        for tok in tokens:
            if tok.startswith("\u2581"):
                text += " " + tok[1:]
            else:
                text += tok
        return text.strip()

    def decode(self, ids):
        tokens = self.ids2tokens(ids)
        filtered = []
        for tok in tokens:
            if tok.startswith("<") and tok.endswith(">"):
                continue
            filtered.append(tok)
        return self.tokens2text(filtered)


# ── CTC 贪心搜索 ──────────────────────────────────────────────────────

def ctc_greedy_search(ctc_log_probs, blank_id=0):
    """
    CTC greedy search with frame tracking.

    Returns:
        hyps: list of decoded token IDs
        frames: list of CTC frame indices where each token was first decoded
    """
    hyps = []
    frames = []
    prev = blank_id
    T = ctc_log_probs.shape[1]
    for t in range(T):
        max_id = int(np.argmax(ctc_log_probs[0, t]))
        if max_id != blank_id and max_id != prev:
            hyps.append(max_id)
            frames.append(t)
        prev = max_id
    return hyps, frames


def ctc_greedy_search_basic(ctc_log_probs, blank_id=0):
    """CTC greedy search without frame tracking."""
    hyps, _ = ctc_greedy_search(ctc_log_probs, blank_id)
    return hyps


# ── 模块级 ONNX 会话单件 ─────────────────────────────────────────────

_onnx_frontend = None
_onnx_encoder = None
_onnx_tokenizer = None
_onnx_model_dir = None
_onnx_lock = threading.Lock()


def _load_onnx_models(model_dir, num_threads=4):
    """模块级加载 ONNX 模型（仅首次执行，后续复用）。"""
    global _onnx_frontend, _onnx_encoder, _onnx_tokenizer, _onnx_model_dir
    if _onnx_frontend is not None and _onnx_model_dir == model_dir:
        return _onnx_frontend, _onnx_encoder, _onnx_tokenizer

    with _onnx_lock:
        if _onnx_frontend is not None and _onnx_model_dir == model_dir:
            return _onnx_frontend, _onnx_encoder, _onnx_tokenizer

        if not HAVE_ORT:
            raise ImportError(
                "onnxruntime is required. pip install onnxruntime")

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = num_threads
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.graph_optimization_level = \
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False

        t0 = time.time()
        frontend_path = osp.join(model_dir, "dolphin_base_frontend.onnx")
        if not osp.exists(frontend_path):
            raise FileNotFoundError(
                "Frontend ONNX not found: %s" % frontend_path)
        _onnx_frontend = ort.InferenceSession(
            frontend_path, opts, providers=ORT_PROVIDERS)
        logger.info("Frontend ONNX loaded in %.1fs (shared)",
                     time.time() - t0)

        t0 = time.time()
        enc_name = ("dolphin_base_encoder_ctc.onnx"
                    if osp.exists(osp.join(
                        model_dir, "dolphin_base_encoder_ctc.onnx"))
                    else "dolphin_base_encoder_ctc_u8.onnx")
        enc_path = osp.join(model_dir, enc_name)
        if not osp.exists(enc_path):
            raise FileNotFoundError(
                "Encoder+CTC ONNX not found: %s" % enc_path)
        _onnx_encoder = ort.InferenceSession(
            enc_path, opts, providers=ORT_PROVIDERS)
        logger.info("Encoder+CTC ONNX loaded in %.1fs (shared)",
                     time.time() - t0)

        t0 = time.time()
        _onnx_tokenizer = DolphinTokenizer(model_dir)
        logger.info("Tokenizer loaded in %.2fs (shared)",
                     time.time() - t0)

        _onnx_model_dir = model_dir
        return _onnx_frontend, _onnx_encoder, _onnx_tokenizer


# ── ASRSession — Dolphin ─────────────────────────────────────────────

class ASRSession(object):
    """Dolphin ASR streaming session.

    Provides ``update(chunk, last)`` → ``get_result()`` streaming API.
    """

    PUNC_IDS = {1827, 1828, 1833, 1835, 1836, 1876}
    """CTC token IDs that serve as sentence separators."""

    def __init__(
        self,
        model_dir=DEFAULT_MODEL_DIR,
        sv_model_dir=None,
        vad_model_dir=DEFAULT_VAD_PARENT_DIR,
        debug=False,
        num_threads=4,
        max_end_sil=300,
        **kwargs,
    ):
        if debug:
            logging.basicConfig(level=logging.DEBUG)
        self.model_dir = model_dir
        self.vad_model_dir = vad_model_dir
        self.num_threads = num_threads
        self.max_end_sil = max_end_sil
        self.max_seg_dur_s = kwargs.get("max_seg_dur", 10)
        self.recreate_session = kwargs.get("recreate_session", False)

        logger.info("Loading VAD...")
        t0 = time.time()
        self.vad = _VADImpl(vad_model_dir, max_end_sil=max_end_sil)
        if not hasattr(self.vad, 'vad_model_dir'):
            self.vad.vad_model_dir = vad_model_dir
        logger.info("VAD loaded in %.1fs", time.time() - t0)

        self._frontend_sess = None
        self._encoder_sess = None
        self._tokenizer = None

        self._pcm_buffer = np.array([], dtype=np.float32)
        self._cached_pcm = np.empty((0,), dtype=np.float32)
        self._pcm_trimmed_ms = 0
        self._vad_segs = []
        self._results = []
        self._completed_vad_segs = []
        self._vad_ever_fired = False
        self._reset_stats()

        self._mem_stats = []
        self._load_times = {}
        self._closed = False

        logger.info("ASRSession(Dolphin) ready  model_dir=%s", model_dir)

    def close(self):
        """显式释放资源。ONNX 模型不释放（模块级单件复用）。"""
        if self._closed:
            return
        self._closed = True
        self.vad = None
        self._pcm_buffer = np.array([], dtype=np.float32)
        self._cached_pcm = np.empty((0,), dtype=np.float32)
        self._vad_segs.clear()
        self._results.clear()
        self._completed_vad_segs.clear()
        self._mem_stats.clear()
        self._load_times.clear()
        gc.collect()

    def _reset_stats(self):
        self._perf = {
            "vad_total_ms": 0.0,
            "enc_ctc_total_ms": 0.0,
            "frontend_total_ms": 0.0,
            "tokenizer_total_ms": 0.0,
        }

    def _load_models(self):
        """Load ONNX models (lazy) — 使用模块级单件。"""
        if self._frontend_sess is not None:
            return
        frontend, encoder, tokenizer = _load_onnx_models(
            self.model_dir, self.num_threads)
        self._frontend_sess = frontend
        self._encoder_sess = encoder
        self._tokenizer = tokenizer

    def _run_frontend(self, waveform):
        assert waveform.ndim == 1
        samples = len(waveform)
        lengths = np.array([samples], dtype=np.int64)
        waveform_batch = waveform[np.newaxis, :].astype(np.float32)
        outputs = self._frontend_sess.run(
            None,
            {"waveform": waveform_batch, "lengths": lengths},
        )
        feats, feat_lens = outputs[0], outputs[1]
        return feats, int(feat_lens[0])

    def _run_encoder_ctc(self, feats, feat_len):
        lengths = np.array([feat_len], dtype=np.int64)
        outputs = self._encoder_sess.run(
            None,
            {"input": feats.astype(np.float32), "lengths": lengths},
        )
        return outputs[0], outputs[1], outputs[2]

    @staticmethod
    def _merge_vad_segments(segments):
        """Merge strictly overlapping VAD segments."""
        if not segments:
            return []
        sorted_segs = sorted(segments, key=lambda s: s["begin"])
        merged = [dict(sorted_segs[0])]
        for s in sorted_segs[1:]:
            last = merged[-1]
            if s["begin"] < last["end"]:
                last["end"] = max(last["end"], s["end"])
                last["keep"] = last["keep"] or s.get("keep", True)
            else:
                merged.append(dict(s))
        return merged

    def reset(self):
        self._pcm_buffer = np.array([], dtype=np.float32)
        self._cached_pcm = np.empty((0,), dtype=np.float32)
        self._pcm_trimmed_ms = 0
        self._vad_segs = []
        self._results = []
        self._completed_vad_segs = []
        self._vad_ever_fired = False
        self._reset_stats()

    def update(self, pcm, last=False):
        """Feed PCM chunk, run VAD + ASR on completed segments."""
        t0 = time.time()
        segs = self.vad(pcm, is_final=last)
        self._perf["vad_total_ms"] += (time.time() - t0) * 1000
        for s in (segs if segs else []):
            self._vad_segs.append({
                "begin": s[0], "end": s[1], "keep": True,
                "seg_idx": len(self._vad_segs),
            })
        if segs:
            self._vad_ever_fired = True

        # Merge overlapping VAD segments
        if len(self._vad_segs) > 1:
            self._vad_segs = self._merge_vad_segments(self._vad_segs)
        for i, seg in enumerate(self._vad_segs):
            seg["seg_idx"] = i

        # Cache PCM (trim to last 60s)
        self._cached_pcm = np.concatenate([self._cached_pcm, pcm])
        trim_samples = int(60 * SAMPLE_RATE)
        if len(self._cached_pcm) > trim_samples:
            trimmed = len(self._cached_pcm) - trim_samples
            self._cached_pcm = self._cached_pcm[-trim_samples:]
            self._pcm_trimmed_ms += int(trimmed * 1000 / SAMPLE_RATE)

        # Process completed VAD segments
        keep_segs = []
        for seg in self._vad_segs:
            if seg.get("keep", True):
                self._do_asr_seg(seg["seg_idx"])
                self._completed_vad_segs.append(
                    (seg["begin"], seg["end"]))
            else:
                keep_segs.append(seg)
        self._vad_segs = keep_segs

        if last:
            if len(self._cached_pcm) > 0 and self._vad_ever_fired:
                remaining_pcm = self._cached_pcm.copy()
                begin_ms = int(self._pcm_trimmed_ms)
                end_ms = int(self._pcm_trimmed_ms +
                             len(remaining_pcm) * 1000 / SAMPLE_RATE)
                self._do_asr_seg(None, forced_pcm=remaining_pcm)
                self._completed_vad_segs.append((begin_ms, end_ms))

    def get_result(self):
        """Return results in standard format.

        Returns:
            dict with keys:
                "sentences": [(begin_ms, end_ms, text), ...]
                "raw_tokens": [str, ...]
                "raw_stamps": [(int, int), ...]
                "vad_segs": [(int, int), ...]
        """
        sorted_results = sorted(
            self._results,
            key=lambda r: r.get("begin", r.get("begin_ms", 0)))
        sentences = []
        for r in sorted_results:
            begin_ms = r.get("begin", r.get("begin_ms", 0))
            end_ms = r.get("end", r.get("end_ms", 0))
            text = r.get("text", "")
            sentences.append((begin_ms, end_ms, text))
        raw_tokens = []
        raw_stamps = []
        for begin_ms, end_ms, text in sentences:
            if text and len(text) > 0:
                dur = float(end_ms - begin_ms)
                step = dur / len(text)
                for i, ch in enumerate(text):
                    raw_tokens.append(ch)
                    raw_stamps.append((
                        int(begin_ms + i * step),
                        int(begin_ms + (i + 1) * step),
                    ))
        vad_segs = list(self._completed_vad_segs)
        vad_segs.extend(
            (s["begin"], s["end"]) for s in self._vad_segs)
        return {
            "sentences": sentences,
            "raw_tokens": raw_tokens,
            "raw_stamps": raw_stamps,
            "vad_segs": vad_segs,
        }

    def get_perf(self):
        """Return performance dictionary."""
        return dict(self._perf)

    def warm(self):
        """Warm up — models already loaded in __init__()."""

    # ── 智能标点感知分片 ─────────────────────────────────────────
    def _do_asr_seg(self, seg_idx, forced_pcm=None):
        """Process one VAD segment with smart punctuation-aware chunking.

        For short segments (<=7s), processes directly.
        For long segments (>7s), uses smart chunking:
          1. Process first 7s → get CTC tokens with frame positions
          2. Find LAST punctuation that leaves >=1.5s overlap
          3. Output text before punctuation as completed sentence
          4. Cut PCM at punctuation → keep overlap → add remaining PCM
          5. Repeat until all PCM consumed
        """
        sr = SAMPLE_RATE
        INIT_CHUNK_S = 7
        MAX_TOTAL_S = 12
        MIN_OVERLAP_S = 1.5
        MAX_CHARS_BEFORE_FORCE = 20
        FRAME_GUARD = 2

        if forced_pcm is not None:
            seg_pcm = forced_pcm
            begin_ms = int(self._pcm_trimmed_ms)
            end_ms = int(self._pcm_trimmed_ms +
                         len(seg_pcm) * 1000 / sr)
        else:
            seg = self._vad_segs[seg_idx]
            begin_ms, end_ms = int(seg["begin"]), int(seg["end"])
            start_s = int((begin_ms - self._pcm_trimmed_ms) *
                          sr / 1000)
            end_s = int((end_ms - self._pcm_trimmed_ms) *
                        sr / 1000)
            if start_s < 0:
                start_s = 0
            if start_s >= len(self._cached_pcm):
                return
            end_s = min(end_s, len(self._cached_pcm))
            if end_s <= start_s:
                return
            seg_pcm = self._cached_pcm[start_s:end_s]

        if len(seg_pcm) < sr * 0.1:  # <100ms
            return

        seg_dur_s = len(seg_pcm) / sr
        rss_before = _get_rss_mb()

        # ── Short segment: process directly ──
        if seg_dur_s <= INIT_CHUNK_S:
            t0 = time.time()
            self._load_models()
            feats, feat_len = self._run_frontend(seg_pcm)
            self._perf["frontend_total_ms"] += \
                (time.time() - t0) * 1000
            t0 = time.time()
            encoder_out, ctc_log_probs, enc_mask = \
                self._run_encoder_ctc(feats, feat_len)
            elapsed = (time.time() - t0) * 1000
            self._perf["enc_ctc_total_ms"] += elapsed
            token_ids, _ = ctc_greedy_search(
                ctc_log_probs, blank_id=BLANK_ID)
            t0d = time.time()
            text = self._tokenizer.decode(token_ids)
            self._perf["tokenizer_total_ms"] += \
                (time.time() - t0d) * 1000
            if text.strip():
                self._results.append({
                    "begin": begin_ms, "end": end_ms, "text": text})
            gc.collect()
            ra = _get_rss_mb()
            self._mem_stats.append({
                "seg": seg_idx, "begin_ms": begin_ms,
                "end_ms": end_ms, "len_s": seg_dur_s,
                "split": False,
                "rss_before_mb": rss_before,
                "rss_after_mb": ra,
                "rss_delta_mb": ra - rss_before,
            })
            return

        # ── Long segment: smart punctuation-aware chunking ──
        self._load_models()
        remaining = seg_pcm.copy()
        pcm_global_offset = 0
        seg_results = []
        iteration = 0

        while len(remaining) / sr > 0.3:
            iteration += 1
            init_samples = min(int(INIT_CHUNK_S * sr),
                               len(remaining))
            chunk = remaining[:init_samples]

            t0 = time.time()
            feats, feat_len = self._run_frontend(chunk)
            self._perf["frontend_total_ms"] += \
                (time.time() - t0) * 1000
            t0 = time.time()
            encoder_out, ctc_log_probs, enc_mask = \
                self._run_encoder_ctc(feats, feat_len)
            self._perf["enc_ctc_total_ms"] += \
                (time.time() - t0) * 1000
            T_ctc = ctc_log_probs.shape[1]
            token_ids, frame_ids = ctc_greedy_search(
                ctc_log_probs, blank_id=BLANK_ID)
            t0d = time.time()
            self._perf["tokenizer_total_ms"] += \
                (time.time() - t0d) * 1000

            # Find separator positions
            sep_positions = [
                i for i, tid in enumerate(token_ids)
                if tid in self.PUNC_IDS]

            if sep_positions:
                best_sep = None
                for i in reversed(sep_positions):
                    sf = frame_ids[i]
                    overlap_s = (T_ctc - sf) / T_ctc * INIT_CHUNK_S
                    if overlap_s >= MIN_OVERLAP_S:
                        best_sep = i
                        break
                if best_sep is None:
                    best_sep = sep_positions[-1]

                last_sep = best_sep
                sep_frame = frame_ids[last_sep]
                cutoff_sample = int(
                    (sep_frame + 1) / T_ctc * len(chunk))
                cutoff_sample = min(cutoff_sample, len(chunk))
                cutoff_sample = max(cutoff_sample, 1)

                tokens_before = token_ids[:last_sep + 1]
                text_before = self._tokenizer.decode(tokens_before)
                char_count_before = len(
                    text_before.replace(' ', ''))

                if char_count_before > MAX_CHARS_BEFORE_FORCE and \
                        best_sep != sep_positions[-1]:
                    last_sep = sep_positions[-1]
                    sep_frame = frame_ids[last_sep]
                    cutoff_sample = int(
                        (sep_frame + 1) / T_ctc * len(chunk))
                    cutoff_sample = min(cutoff_sample, len(chunk))
                    cutoff_sample = max(cutoff_sample, 1)
                    tokens_before = token_ids[:last_sep + 1]
                    text_before = self._tokenizer.decode(
                        tokens_before)

                if text_before.strip():
                    cb = int(begin_ms +
                             pcm_global_offset * 1000 / sr)
                    ce = int(begin_ms +
                             (pcm_global_offset + cutoff_sample) *
                             1000 / sr)
                    seg_results.append({
                        "begin": cb, "end": ce,
                        "text": text_before,
                        "smart_split": True,
                    })

                overlap_pcm = chunk[cutoff_sample:]
                overlap_dur = len(overlap_pcm) / sr
                remaining_after_init = remaining[init_samples:]

                max_add_dur = MAX_TOTAL_S - overlap_dur
                add_samples = min(
                    int(max_add_dur * sr),
                    len(remaining_after_init))
                extra_pcm = \
                    remaining_after_init[:add_samples] \
                    if add_samples > 0 \
                    else np.array([], dtype=np.float32)

                parts = []
                if len(overlap_pcm) > 0:
                    parts.append(overlap_pcm)
                if len(extra_pcm) > 0:
                    parts.append(extra_pcm)
                if len(parts) > 1:
                    new_pcm = np.hstack(parts)
                elif len(parts) == 1:
                    new_pcm = parts[0]
                else:
                    new_pcm = np.array([], dtype=np.float32)

                pcm_global_offset += cutoff_sample
                remaining = new_pcm

            else:
                # ── No punctuation found ──
                dur_consumed = init_samples / sr
                if dur_consumed >= MAX_TOTAL_S:
                    text = self._tokenizer.decode(token_ids)
                    if text.strip():
                        cb = int(begin_ms +
                                 pcm_global_offset * 1000 / sr)
                        ce = int(begin_ms +
                                 (pcm_global_offset +
                                  len(chunk)) * 1000 / sr)
                        seg_results.append({
                            "begin": cb, "end": ce,
                            "text": text + "\uff0c",
                            "smart_split": True,
                            "forced": True,
                        })
                    remaining_after = remaining[init_samples:]
                    max_new = min(
                        int(MAX_TOTAL_S * sr),
                        len(remaining_after))
                    pcm_global_offset += init_samples
                    remaining = \
                        remaining_after[:max_new] \
                        if max_new > 0 else remaining_after
                    if len(remaining_after) == 0:
                        remaining = np.array(
                            [], dtype=np.float32)
                else:
                    text = self._tokenizer.decode(token_ids)
                    if text.strip():
                        cb = int(begin_ms +
                                 pcm_global_offset * 1000 / sr)
                        ce = int(begin_ms +
                                 (pcm_global_offset +
                                  len(chunk)) * 1000 / sr)
                        seg_results.append({
                            "begin": cb, "end": ce,
                            "text": text,
                            "smart_split": True,
                        })
                    pcm_global_offset += len(chunk)
                    remaining = remaining[init_samples:]

            if len(remaining) < sr * 0.3:
                break

        # ── Flush remaining PCM ──
        if len(remaining) / sr > 0.3:
            t0 = time.time()
            feats, feat_len = self._run_frontend(remaining)
            self._perf["frontend_total_ms"] += \
                (time.time() - t0) * 1000
            t0 = time.time()
            encoder_out, ctc_log_probs, enc_mask = \
                self._run_encoder_ctc(feats, feat_len)
            self._perf["enc_ctc_total_ms"] += \
                (time.time() - t0) * 1000
            token_ids, _ = ctc_greedy_search(
                ctc_log_probs, blank_id=BLANK_ID)
            text = self._tokenizer.decode(token_ids)
            if text.strip():
                cb = int(begin_ms +
                         pcm_global_offset * 1000 / sr)
                ce = int(begin_ms +
                         (pcm_global_offset +
                          len(remaining)) * 1000 / sr)
                seg_results.append({
                    "begin": cb, "end": ce,
                    "text": text,
                    "smart_split": True,
                })

        self._results.extend(seg_results)
        gc.collect()
        ra = _get_rss_mb()
        self._mem_stats.append({
            "seg": seg_idx, "begin_ms": begin_ms,
            "end_ms": end_ms, "len_s": seg_dur_s,
            "split": True, "iterations": iteration,
            "rss_before_mb": rss_before,
            "rss_after_mb": ra,
        })


# ============================================================================
#  ═══════════════════════════════════════════════════════════════════════════
#  SECTION 3: 流式 ASR 处理器 — 包装 ASRSession 实现 WebSocket 流式接口
#  ═══════════════════════════════════════════════════════════════════════════
# ============================================================================

class DolphinStreamingProcessor(object):
    """流式 ASR 处理器。

    封装 ASRSession，管理 PCM 缓冲、VAD 分段、标点断句和结果去重。

    用法::

        proc = DolphinStreamingProcessor(
            model_dir="./model/dolphin",
            vad_model_dir="./model",
        )
        for pcm_bytes in audio_stream:
            results = proc.feed(pcm_bytes)
            for r in results:
                if r["type"] == "final":
                    print("识别结果:", r["text"])
        # 结束
        results = proc.feed(b"", is_end=True)
    """

    def __init__(self, model_dir=DEFAULT_MODEL_DIR,
                 vad_model_dir=DEFAULT_VAD_PARENT_DIR,
                 num_threads=4, max_end_sil=300, max_seg_dur=10,
                 enable_partial=True):
        self._enable_partial = enable_partial
        self._sess = ASRSession(
            model_dir=model_dir,
            vad_model_dir=vad_model_dir,
            num_threads=num_threads,
            max_end_sil=max_end_sil,
            max_seg_dur=max_seg_dur,
        )
        # 已发送的句子计数（用于增量输出）
        self._sent_count = 0
        self._total_samples = 0
        # 保存构造参数以便 reset
        self._init_args = dict(
            model_dir=model_dir,
            vad_model_dir=vad_model_dir,
            num_threads=num_threads,
            max_end_sil=max_end_sil,
            max_seg_dur=max_seg_dur,
            enable_partial=enable_partial,
        )

    def feed(self, pcm_bytes, is_end=False):
        """输入 PCM S16LE 片段，返回识别结果列表。

        Args:
            pcm_bytes: PCM S16LE bytes（可为空 bytes）
            is_end: 是否结束（flush 剩余语音）

        Returns:
            list[dict]: 每个结果包含 type/text/begin_ms/end_ms
                type: "final" 表示完整句子（含句尾标点）
        """
        results = []

        if pcm_bytes:
            pcm_f32 = _pcm_s16le_to_f32(pcm_bytes)
            self._total_samples += len(pcm_f32)
            self._sess.update(pcm_f32, last=False)
            # 收集本次音频产生的 VAD 段结果
            results.extend(self._collect_new())

        if is_end:
            # 强制 flush 剩余 PCM（标记 last=True 使 VAD 做最终检测）
            # 使用已缓存的 PCM 调用 update(last=True) 确保剩余音频被处理
            cached = self._sess._cached_pcm
            if len(cached) > 0 and self._sess._vad_ever_fired:
                # ASRSession._vad_ever_fired 现在已在有 VAD 段时置位
                self._sess.update(np.array([], dtype=np.float32), last=True)
            elif len(cached) > 0:
                # 从无 VAD 段触发（极短音频），直接强制推理
                self._sess._vad_ever_fired = True
                self._sess.update(np.array([], dtype=np.float32), last=True)
            results.extend(self._collect_new())

        return results

    def _collect_new(self):
        """收集自上次 poll 以来的新结果。"""
        results = []
        result_dict = self._sess.get_result()
        sentences = result_dict.get("sentences", [])

        while self._sent_count < len(sentences):
            begin_ms, end_ms, text = sentences[self._sent_count]
            self._sent_count += 1
            if not text.strip():
                continue

            # 判断是否为句尾标点结尾（决定 final 还是 partial）
            is_final = self._is_sentence_final(text)

            results.append({
                "type": "final" if is_final else "partial",
                "text": text.strip(),
                "begin_ms": int(begin_ms),
                "end_ms": int(end_ms),
            })

        return results

    @staticmethod
    def _is_sentence_final(text):
        """检查文本是否以句尾标点结尾。"""
        if not text:
            return False
        return text[-1] in PUNC_FINAL_CHARS

    def close(self):
        """释放资源。"""
        if self._sess:
            self._sess.close()
            self._sess = None

    def reset(self):
        """重置处理器状态。"""
        self.close()
        args = self._init_args
        self.__init__(**args)


# ============================================================================
#  ═══════════════════════════════════════════════════════════════════════════
#  SECTION 4: Tornado WebSocket 服务器
#  ═══════════════════════════════════════════════════════════════════════════
# ============================================================================

class AsrWebSocketHandler(tornado.websocket.WebSocketHandler):
    """WebSocket 处理器: 接收 PCM 片段，返回 ASR 结果 JSON。"""

    def initialize(self, processor_factory=None):
        self._processor = None
        self._processor_factory = processor_factory or \
            (lambda: DolphinStreamingProcessor())
        self._client_addr = None
        self._connected = False
        self._stats = {
            "pcm_bytes_recv": 0,
            "pcm_seconds": 0,
            "segments": 0,
            "start_time": 0,
            "n_results": 0,
        }

    def open(self):
        self._client_addr = self.request.remote_ip
        self._connected = True
        self._stats["start_time"] = time.time()
        self._processor = self._processor_factory()
        logger.info("WS[%s] open", self._client_addr)

    def on_message(self, message):
        if isinstance(message, bytes):
            self._stats["pcm_bytes_recv"] += len(message)
            self._stats["pcm_seconds"] = \
                self._stats["pcm_bytes_recv"] / (SAMPLE_RATE * SAMPLE_WIDTH)

            results = self._processor.feed(message, is_end=False)
            for r in results:
                self._send_json(r)
                if r["type"] == "final":
                    self._stats["segments"] += 1
                self._stats["n_results"] += 1
        else:
            # JSON 控制消息
            try:
                cmd = json.loads(message)
                self._handle_command(cmd)
            except json.JSONDecodeError:
                self._send_json({
                    "type": "error",
                    "message": "invalid JSON"})

    def on_close(self):
        self._connected = False
        # flush 剩余语音
        if self._processor:
            try:
                results = self._processor.feed(b"", is_end=True)
                for r in results:
                    self._send_json(r)
                    self._stats["n_results"] += 1
                self._processor.close()
            except Exception as e:
                logger.warning("WS[%s] flush error: %s",
                               self._client_addr, e)
        elapsed = time.time() - self._stats["start_time"]
        logger.info(
            "WS[%s] close  recv=%.1fKB(%.1fs) segs=%d results=%d "
            "elapsed=%.1fs",
            self._client_addr,
            self._stats["pcm_bytes_recv"] / 1024,
            self._stats["pcm_seconds"],
            self._stats["segments"],
            self._stats["n_results"],
            elapsed,
        )

    def _send_json(self, data):
        """发送 JSON 消息（线程安全）。"""
        if not self._connected:
            return
        try:
            msg = json.dumps(data, ensure_ascii=False)
            self.write_message(msg)
        except Exception as e:
            logger.warning("send_json error: %s", e)

    def _handle_command(self, cmd):
        """处理客户端控制命令。"""
        action = cmd.get("action", "")
        if action == "reset":
            if self._processor:
                self._processor.reset()
            self._send_json({"type": "ack", "action": "reset"})
        elif action == "ping":
            self._send_json({
                "type": "pong",
                "server_time": time.time(),
            })
        elif action == "stats":
            self._send_json({
                "type": "stats",
                **self._stats,
                "connected": self._connected,
            })
        else:
            self._send_json({
                "type": "error",
                "message": "unknown action: %s" % action,
            })

    def check_origin(self, origin):
        """允许所有来源。"""
        return True


# ── HTTP 状态 Handler ────────────────────────────────────────────────

class AsrStatusHandler(tornado.web.RequestHandler):
    """HTTP 状态接口。"""

    def initialize(self, server_state):
        self._state = server_state

    def get(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        state = {
            "status": "00000" if self._state.get("running", False)
                      else "10001",
            "server": "asr_srv_dolphin",
            "version": "2.0.0",
            "uptime": time.time() - self._state.get("start_time", time.time()),
            "clients": self._state.get("clients", 0),
            "engine": "DolphinBase",
            "model_loaded": self._state.get("model_loaded", False),
            "model_dir": self._state.get("model_dir", ""),
        }
        self.write(json.dumps(state, ensure_ascii=False))


class AsrPowerHandler(tornado.web.RequestHandler):
    """GET /get_power_yn — 检查 ASR 服务能力。"""

    def initialize(self, server_state):
        self._state = server_state

    def get(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        max_concurrent = self._state.get("max_concurrent", 4)
        cur_clients = self._state.get("clients", 0)
        available = max(0, max_concurrent - cur_clients)
        self.write(json.dumps({
            "num": available,
            "status": "00000",
        }))


class AsrPostAudioHandler(tornado.web.RequestHandler):
    """POST /post_audio — 提交音频进行离线 ASR。

    接受 multipart/form-data:
        - file: 音频文件 (WAV/PCM)
        - format: "wav" 或 "pcm"
    """

    def initialize(self, server_state):
        self._state = server_state

    def post(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        try:
            file_info = self.request.files.get("file", [None])[0]
            if file_info is None:
                self.write(json.dumps({
                    "status": "10001",
                    "message": "no file",
                }))
                return

            audio_bytes = file_info["body"]
            audio_format = self.get_argument("format", "wav")

            # 转为 PCM S16LE 16kHz mono
            if audio_format == "pcm":
                pcm_bytes = audio_bytes
            elif audio_format == "wav":
                # 跳过 WAV 头 (44 bytes)
                pcm_bytes = audio_bytes[44:] \
                    if len(audio_bytes) > 44 else audio_bytes
            else:
                self.write(json.dumps({
                    "status": "10002",
                    "message": "unsupported format: %s" % audio_format,
                }))
                return

            pcm_f32 = _pcm_s16le_to_f32(pcm_bytes)

            # 使用 ASRSession 直接识别
            sess = ASRSession(
                model_dir=self._state.get("model_dir", DEFAULT_MODEL_DIR),
                vad_model_dir=self._state.get(
                    "vad_model_dir", DEFAULT_VAD_PARENT_DIR),
                num_threads=self._state.get("num_threads", 4),
            )
            sess.update(pcm_f32, last=True)
            result = sess.get_result()
            sess.close()

            sentences = result.get("sentences", [])
            full_text = "".join(s[2] for s in sentences)
            duration = len(pcm_f32) / SAMPLE_RATE

            # 构造兼容旧接口的返回格式
            seg_list = []
            for begin_ms, end_ms, text in sentences:
                seg_list.append({
                    "begin": self._fmt_time(begin_ms / 1000.0),
                    "end": self._fmt_time(end_ms / 1000.0),
                    "transcript": text,
                    "translation": "",
                })

            self.write(json.dumps({
                "status": "00000",
                "data": {
                    "data": seg_list if seg_list else [{
                        "begin": "00:00:00,000",
                        "end": self._fmt_time(duration),
                        "seg_num": 1,
                        "transcript": full_text,
                        "translation": "",
                    }],
                    "duration": duration,
                    "text": full_text,
                },
            }, ensure_ascii=False))

        except Exception as e:
            logger.error("post_audio error: %s",
                         traceback.format_exc())
            self.write(json.dumps({
                "status": "19999",
                "message": str(e),
            }))

    @staticmethod
    def _fmt_time(seconds):
        """将秒数格式化为 00:00:00,000。"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


# ── ASR Server 主类 ──────────────────────────────────────────────────

class AsrServer(object):
    """ASR WebSocket + HTTP 服务。

    同时提供:
        1. WebSocket 接口 (ws://host:port/asr) — 流式识别
        2. HTTP 接口 (http://host:port/post_audio) — 离线识别
        3. HTTP 状态 (http://host:port/status) — 服务状态
    """

    def __init__(self, host="0.0.0.0", port=2311,
                 model_dir=DEFAULT_MODEL_DIR,
                 vad_model_dir=DEFAULT_VAD_PARENT_DIR,
                 num_threads=4, max_end_sil=300, max_seg_dur=10,
                 enable_partial=True, max_concurrent=4):
        self.host = host
        self.port = port
        self.model_dir = model_dir
        self.vad_model_dir = vad_model_dir
        self.num_threads = num_threads
        self.max_end_sil = max_end_sil
        self.max_seg_dur = max_seg_dur
        self.enable_partial = enable_partial
        self.max_concurrent = max_concurrent

        # 模型预加载验证
        self._model_loaded = False
        self._verify_model()

        self._state = {
            "running": False,
            "start_time": time.time(),
            "clients": 0,
            "model_loaded": self._model_loaded,
            "max_concurrent": max_concurrent,
            "model_dir": model_dir,
            "vad_model_dir": vad_model_dir,
            "num_threads": num_threads,
        }
        self._app = None
        self._http_server = None

    def _verify_model(self):
        """验证模型文件是否存在并尝试加载。"""
        frontend_path = osp.join(self.model_dir,
                                 "dolphin_base_frontend.onnx")
        enc_path = osp.join(self.model_dir,
                            "dolphin_base_encoder_ctc_u8.onnx")
        units_path = osp.join(self.model_dir, "units.txt")
        bpe_path = osp.join(self.model_dir, "bpe.model")
        vad_model = osp.join(self.vad_model_dir, "vad", "vad.onnx")

        missing = []
        for path, desc in [
            (frontend_path, "frontend.onnx"),
            (enc_path, "encoder_ctc.onnx"),
            (units_path, "units.txt"),
            (bpe_path, "bpe.model"),
            (vad_model, "vad.onnx"),
        ]:
            if not osp.exists(path):
                missing.append("%s (%s)" % (desc, path))

        if missing:
            logger.warning("Model check: missing files: %s",
                           "; ".join(missing))
            self._model_loaded = False
        else:
            self._model_loaded = True
            logger.info("Model check: all model files present")

    def _make_processor(self):
        """创建流式处理器实例（每次 WebSocket 连接调用）。"""
        return DolphinStreamingProcessor(
            model_dir=self.model_dir,
            vad_model_dir=self.vad_model_dir,
            num_threads=self.num_threads,
            max_end_sil=self.max_end_sil,
            max_seg_dur=self.max_seg_dur,
            enable_partial=self.enable_partial,
        )

    def start(self):
        """启动服务。"""
        if not HAVE_TORNADO:
            logger.fatal(
                "tornado is required! pip install tornado")
            sys.exit(1)

        if not HAVE_ORT:
            logger.fatal(
                "onnxruntime is required! pip install onnxruntime")
            sys.exit(1)

        if not HAVE_SPM:
            logger.fatal(
                "sentencepiece is required! pip install sentencepiece")
            sys.exit(1)

        if not HAVE_KNF:
            logger.warning(
                "kaldi-native-fbank not installed; VAD may not work."
                " pip install kaldi-native-fbank")

        # 预热模型（模块级单件加载）
        logger.info("Pre-warming models...")
        try:
            _load_onnx_models(self.model_dir, self.num_threads)
            logger.info("Models warmed up OK")
        except Exception as e:
            logger.warning("Model warm-up failed: %s", e)

        # 状态引用（用于闭包）
        _state = self._state
        _factory = self._make_processor

        class _WSHandler(AsrWebSocketHandler):
            def initialize(self):
                super().initialize(processor_factory=_factory)

            def open(self):
                super().open()
                _state["clients"] += 1

            def on_close(self):
                super().on_close()
                _state["clients"] -= 1

        class _StatusHandler(AsrStatusHandler):
            def initialize(self):
                super().initialize(_state)

        class _PowerHandler(AsrPowerHandler):
            def initialize(self):
                super().initialize(_state)

        class _PostAudioHandler(AsrPostAudioHandler):
            def initialize(self):
                super().initialize(_state)

        # Tornado 路由
        handlers = [
            (r"/asr", _WSHandler),
            (r"/", _StatusHandler),
            (r"/status", _StatusHandler),
            (r"/get_power_yn", _PowerHandler),
            (r"/post_audio", _PostAudioHandler),
        ]

        self._app = tornado.web.Application(handlers)
        self._http_server = tornado.httpserver.HTTPServer(self._app)
        self._http_server.listen(self.port, address=self.host)

        self._state["running"] = True

        logger.info("")
        logger.info("=" * 60)
        logger.info("  ASR Server (Dolphin Base) started")
        logger.info("  Listen:     %s:%d", self.host, self.port)
        logger.info("  Model:      %s", self.model_dir)
        logger.info("  VAD:        %s", self.vad_model_dir)
        logger.info("  Threads:    %d", self.num_threads)
        logger.info("  Max Clients:%d", self.max_concurrent)
        logger.info("  Models:     %s",
                    "loaded" if self._model_loaded else "CHECK FAILED")
        logger.info("=" * 60)
        logger.info("  WebSocket:  ws://%s:%d/asr", self.host, self.port)
        logger.info("  Status:     http://%s:%d/status", self.host, self.port)
        logger.info("  PostAudio:  http://%s:%d/post_audio",
                    self.host, self.port)
        logger.info("=" * 60)
        logger.info("")

        try:
            tornado.ioloop.IOLoop.current().start()
        except KeyboardInterrupt:
            logger.info("Server stopping...")
            self.stop()

    def stop(self):
        self._state["running"] = False
        tornado.ioloop.IOLoop.current().stop()
        logger.info("Server stopped.")


# ============================================================================
#  ═══════════════════════════════════════════════════════════════════════════
#  SECTION 5: CLI 入口
#  ═══════════════════════════════════════════════════════════════════════════
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description="Dolphin Base ASR WebSocket Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 默认启动（模型在 ./model/dolphin/）
  python asr_srv_dolphin.py --port 2311

  # 指定其他模型目录
  python asr_srv_dolphin.py --port 2311 \\
      --model_dir /path/to/model/dolphin

  # 调试模式
  python asr_srv_dolphin.py --port 2311 --debug
""")
    ap.add_argument("--port", type=int, default=2311,
                    help="Listen port (default: 2311)")
    ap.add_argument("--host", type=str, default="0.0.0.0",
                    help="Bind address (default: 0.0.0.0)")
    ap.add_argument("--model_dir", type=str, default=None,
                    help="Dolphin model directory "
                         "(default: ./model/dolphin/)")
    ap.add_argument("--vad_model_dir", type=str, default=None,
                    help="VAD model parent directory "
                         "(default: ./model/)")
    ap.add_argument("--num_threads", type=int, default=4,
                    help="ONNX intra-op threads (default: 4; "
                         "recommended: 8 on BM1688)")
    ap.add_argument("--max_end_sil", type=int, default=300,
                    help="VAD max end silence ms (default: 300)")
    ap.add_argument("--max_seg_dur", type=int, default=10,
                    help="Max segment duration seconds (default: 10)")
    ap.add_argument("--no_partial", action="store_true",
                    help="Disable partial results (only final)")
    ap.add_argument("--max_clients", type=int, default=4,
                    help="Max concurrent clients (default: 4)")
    ap.add_argument("--log_file", type=str, default=None,
                    help="Log file path")
    ap.add_argument("--log_level", type=str, default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                    help="Log level (default: INFO)")
    ap.add_argument("--debug", action="store_true",
                    help="Shortcut for --log_level DEBUG")
    args = ap.parse_args()

    log_level = logging.DEBUG if args.debug else \
        getattr(logging, args.log_level.upper(), logging.INFO)
    _init_logging(log_level, args.log_file)

    # 解析模型路径
    model_dir = args.model_dir
    if model_dir is None:
        model_dir = DEFAULT_MODEL_DIR
        logger.info("Using default model dir: %s", model_dir)
    model_dir = osp.abspath(model_dir)

    vad_model_dir = args.vad_model_dir
    if vad_model_dir is None:
        vad_model_dir = DEFAULT_VAD_PARENT_DIR
        logger.info("Using default VAD dir: %s", vad_model_dir)
    vad_model_dir = osp.abspath(vad_model_dir)

    server = AsrServer(
        host=args.host,
        port=args.port,
        model_dir=model_dir,
        vad_model_dir=vad_model_dir,
        num_threads=args.num_threads,
        max_end_sil=args.max_end_sil,
        max_seg_dur=args.max_seg_dur,
        enable_partial=not args.no_partial,
        max_concurrent=args.max_clients,
    )
    server.start()


if __name__ == "__main__":
    main()

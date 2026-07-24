"""
asr_vad.py — FunASR FSMN VAD with ONNX Runtime

Single-file VAD class using FunASR fsmn-vad ONNX model.
Accepts 1-second 16kHz PCM chunks, outputs VAD segment timestamps.

Usage:
    from asr_vad import VAD
    vad = VAD()
    for pcm_chunk in audio_stream:
        for start_ms, end_ms in vad.feed(pcm_chunk):
            print(f"Speech: {start_ms}ms - {end_ms}ms")
    segs = vad.finalize()

Dependencies: numpy, onnxruntime, scipy (for test only)
"""
import os, math
from typing import List
import numpy as np

# ====== Fbank + LFR + CMVN ======

def _load_cmvn(filepath):
    with open(filepath) as f:
        text = f.read()
    idx = text.find('<AddShift>')
    i2 = text.find('<LearnRateCoef>', idx)
    i3 = text.find('[', i2)
    i4 = text.find(']', i3)
    means = np.fromstring(text[i3+1:i4].strip(), sep=' ', dtype=np.float32)[:400]
    idx = text.find('<Rescale>')
    i2 = text.find('<LearnRateCoef>', idx)
    i3 = text.find('[', i2)
    i4 = text.find(']', i3)
    vars = np.fromstring(text[i3+1:i4].strip(), sep=' ', dtype=np.float32)[:400]
    return np.stack([means, vars])

def _mel_filterbank(n_filt, fft_size, sr):
    low_mel = 0.0
    high_mel = 2595.0 * math.log10(1 + (sr / 2) / 700.0)
    mel_pts = np.linspace(low_mel, high_mel, n_filt + 2)
    hz_pts = 700.0 * (10.0 ** (mel_pts / 2595.0) - 1.0)
    bins = np.floor((fft_size + 1) * hz_pts / sr).astype(int)
    fbank = np.zeros((n_filt, fft_size // 2 + 1), dtype=np.float64)
    for i in range(1, n_filt + 1):
        l, c, r = bins[i-1], bins[i], bins[i+1]
        for j in range(l, c):
            if c != l: fbank[i-1, j] = (j - l) / (c - l)
        for j in range(c, r):
            if r != c: fbank[i-1, j] = (r - j) / (r - c)
    return fbank.astype(np.float32)

def _extract_fbank(pcm, sr=16000, fl=25, fs=10, n_mels=80, fft_size=512):
    if pcm.dtype != np.float32:
        pcm = pcm.astype(np.float32)
    # Scale to int16 range (kaldi convention)
    pcm = pcm * (1 << 15)
    flen = int(sr * fl / 1000)
    fshift = int(sr * fs / 1000)
    T = (len(pcm) - flen) // fshift + 1
    if T <= 0:
        return np.zeros((0, n_mels), dtype=np.float32)
    win = np.hamming(flen).astype(np.float64)
    idx = np.arange(flen) + np.arange(T)[:, None] * fshift
    frames = pcm[idx].astype(np.float64)
    frames *= win
    spec = np.fft.rfft(frames, n=fft_size)
    power = (spec.real * spec.real + spec.imag * spec.imag) / fft_size
    if not hasattr(_extract_fbank, '_melfb') or _extract_fbank._melfb is None:
        _extract_fbank._melfb = _mel_filterbank(n_mels, fft_size, sr)
    mel = np.dot(power, _extract_fbank._melfb.T)
    mel = np.maximum(mel, 1e-10)
    return np.log(mel).astype(np.float32)

def _apply_lfr(feats, lfr_m=5, lfr_n=1):
    T, D = feats.shape
    if lfr_m <= 1:
        return feats
    pad = (lfr_m - 1) // 2
    feats_pad = np.vstack([feats[:1].repeat(pad, axis=0), feats])
    Tp = feats_pad.shape[0]
    Tl = int(np.ceil((Tp - lfr_m) / lfr_n)) + 1
    need = (Tl - 1) * lfr_n + lfr_m
    if need > Tp:
        feats_pad = np.vstack([feats_pad, feats_pad[-1:].repeat(need - Tp, axis=0)])
    out = np.zeros((Tl, D * lfr_m), dtype=np.float32)
    for i in range(Tl):
        s = i * lfr_n
        out[i] = feats_pad[s:s+lfr_m].ravel()
    return out

def _apply_cmvn(feats, cmvn):
    return (feats + cmvn[0:1, :feats.shape[1]]) * cmvn[1:2, :feats.shape[1]]

# ====== VAD Class ======

class VAD:
    """Real-time VAD using FunASR FSMN model (ONNX Runtime).

    Processes 16kHz PCM chunks, returns completed [start_ms, end_ms] segments.

    Args:
        model_dir: Path to model dir (uses cache default if None)
        sil_threshold: Silence prob threshold (default 0.2).
            Model output[0] is silence prob; frame=speech if sil_prob <= thresh.
        min_speech_ms: Minimum segment duration (default 100)
        min_silence_ms: Merge gap (default 200)
        speech_to_sil_ms: Silence frames to end segment (default 800)
        sil_to_speech_ms: Speech frames to start segment (default 200)
    """
    def __init__(self, model_dir=None, sil_threshold=0.2,
                 min_speech_ms=100, min_silence_ms=200,
                 speech_to_sil_ms=800, sil_to_speech_ms=200):
        if model_dir is None:
            model_dir = os.path.join(os.path.expanduser('~'), '.cache',
                'modelscope', 'hub', 'models', 'iic',
                'speech_fsmn_vad_zh-cn-16k-common-pytorch')
        self.model_dir = model_dir
        self.sr = 16000
        self.frm_ms = 10
        self.sil_th = sil_threshold
        self.min_sp_ms = min_speech_ms
        self.min_sil_ms = min_silence_ms
        self.sp2s_frames = speech_to_sil_ms // self.frm_ms
        self.s2sp_frames = sil_to_speech_ms // self.frm_ms
        self.cmvn = _load_cmvn(os.path.join(model_dir, 'am.mvn'))

        import onnxruntime as ort
        self.sess = ort.InferenceSession(
            os.path.join(model_dir, 'model.onnx'),
            providers=['CPUExecutionProvider'])
        self.reset()

    def reset(self):
        self._caches = [np.zeros((1,128,19,1), np.float32) for _ in range(4)]
        self._global_frame = 0
        self._speech_start = None
        self._segments = []
        self._sil_count = 0
        self._sp_count = 0
        self._in_speech = False

    def feed(self, pcm: np.ndarray):
        """Process PCM chunk (16kHz, mono, float32 [-1,1] or int16).
        Returns list of completed [start_ms, end_ms].
        """
        if pcm.dtype == np.int16:
            pcm = pcm.astype(np.float32) / 32768.0
        elif pcm.dtype != np.float32:
            pcm = pcm.astype(np.float32)

        feats = _extract_fbank(pcm, sr=self.sr)
        if feats.shape[0] == 0:
            return []
        feats = _apply_lfr(feats, 5, 1)
        feats = _apply_cmvn(feats, self.cmvn)

        feeds = {'speech': feats[None,:,:].astype(np.float32)}
        for i, c in enumerate(self._caches):
            feeds[f'in_cache{i}'] = c
        outs = self.sess.run(None, feeds)
        logits = outs[0]
        for i in range(4):
            self._caches[i] = outs[i+1]

        # Sil prob at index 0
        sil_probs = logits[0, :, 0]
        frame_is_speech = sil_probs <= self.sil_th

        prev_len = len(self._segments)
        for sp in frame_is_speech:
            frm = self._global_frame
            self._global_frame += 1

            if sp:  # speech
                if not self._in_speech:
                    self._sp_count += 1
                    self._sil_count = 0
                    if self._sp_count >= self.s2sp_frames and self._speech_start is None:
                        self._in_speech = True
                        self._speech_start = frm - self.s2sp_frames + 1
                        self._sp_count = 0
                else:
                    self._sil_count = 0
            else:  # silence
                if self._in_speech:
                    self._sil_count += 1
                    if self._sil_count >= self.sp2s_frames:
                        end = frm - self.sp2s_frames + 1
                        start_ms = self._speech_start * self.frm_ms
                        end_ms = end * self.frm_ms
                        if end_ms - start_ms >= self.min_sp_ms:
                            self._segments.append([start_ms, end_ms])
                        self._speech_start = None
                        self._in_speech = False
                        self._sil_count = 0
                else:
                    self._sp_count = 0

        return [self._segments[i] for i in range(prev_len, len(self._segments))]

    def finalize(self):
        result = []
        if self._in_speech and self._speech_start is not None:
            end_ms = (self._global_frame - 1) * self.frm_ms
            start_ms = self._speech_start * self.frm_ms
            if end_ms - start_ms >= self.min_sp_ms:
                result = [[start_ms, end_ms]]
        self.reset()
        return result

    @property
    def segments(self):
        return list(self._segments)


# ====== Self-test ======

if __name__ == '__main__':
    model_dir = os.path.join(os.path.expanduser('~'), '.cache',
        'modelscope', 'hub', 'models', 'iic',
        'speech_fsmn_vad_zh-cn-16k-common-pytorch')
    wav_path = os.path.join(model_dir, 'example', 'vad_example.wav')

    if os.path.exists(wav_path):
        from scipy.io import wavfile
        sr, audio = wavfile.read(wav_path)
        print(f'WAV: {os.path.basename(wav_path)}, sr={sr}, len={len(audio)/sr:.1f}s')
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        vad = VAD(model_dir, sil_threshold=0.2)
        all_segs = []
        for i in range(0, len(audio), sr):
            segs = vad.feed(audio[i:i+sr])
            all_segs.extend(segs)
        all_segs.extend(vad.finalize())
        for s, e in all_segs:
            print(f'  [{s:5d}ms - {e:5d}ms] ({e-s:4d}ms)')
        print(f'Total: {len(all_segs)} segments')
    else:
        print('No example wav. Run quick synthetic test...')
        sr, t = 16000, np.arange(16000*2) / 16000
        speech = (np.sin(2*np.pi*200*t[:16000]) + 0.5*np.sin(2*np.pi*400*t[:16000])) * 0.3
        audio = np.concatenate([speech, np.random.randn(16000).astype(np.float32)*0.001])
        vad = VAD(model_dir, sil_threshold=0.25)
        all_segs = []
        for i in range(0, len(audio), sr):
            all_segs.extend(vad.feed(audio[i:i+sr]))
        all_segs.extend(vad.finalize())
        for s, e in all_segs:
            print(f'  [{s:5d}ms - {e:5d}ms]')
        print(f'Total: {len(all_segs)} segments')

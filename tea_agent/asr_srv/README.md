# ASR Server — Dolphin Base

自包含的流式语音识别 WebSocket 服务，基于 DataoceanAI Dolphin Base ONNX 模型。

## 目录结构

```
asr_srv/
├── asr_srv_dolphin.py       # 主服务脚本（单文件，内嵌 VAD + ASR 引擎）
├── model/
│   ├── dolphin/
│   │   ├── dolphin_base_frontend.onnx       # 前端特征提取 (128KB)
│   │   ├── dolphin_base_encoder_ctc_u8.onnx # 编码器+CTC (INT8量化, 100MB)
│   │   ├── bpe.model                       # SentencePiece BPE 模型 (835KB)
│   │   └── units.txt                       # 符号表 (493KB)
│   └── vad/
│       ├── vad.onnx                        # VAD 模型 (1.7MB)
│       ├── config.yaml                     # VAD 配置
│       └── am.mvn                          # CMVN 统计
└── README.md
```

## 依赖

```bash
pip install tornado numpy onnxruntime sentencepiece kaldi-native-fbank
```

## 快速开始

```bash
cd asr_srv/
python asr_srv_dolphin.py --port 2311
```

## WebSocket 协议

**客户端 → 服务器**: Binary 帧 (PCM S16LE, 16kHz, mono)  
**服务器 → 客户端**: JSON 帧

```
{"type":"partial","text":"你好","begin_ms":0,"end_ms":1200}
{"type":"final","text":"你好，世界。","begin_ms":0,"end_ms":3200}
```

### 控制命令（JSON 文本帧）

```json
{"action":"reset"}          — 重置会话
{"action":"ping"}           — 心跳
```

## HTTP 接口

| 路径 | 方法 | 说明 |
|------|------|------|
| `/status` | GET | 服务状态 |
| `/get_power_yn` | GET | 可用容量 |
| `/post_audio` | POST | 离线音频识别（兼容旧接口） |

## 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 2311 | 监听端口 |
| `--host` | 0.0.0.0 | 绑定地址 |
| `--model_dir` | ./model/dolphin/ | Dolphin 模型目录 |
| `--vad_model_dir` | ./model/ | VAD 模型父目录 |
| `--num_threads` | 4 | ONNX intra-op 线程数 |
| `--max_end_sil` | 300 | VAD 最长尾音 ms |
| `--max_seg_dur` | 10 | 最大段长度秒 |
| `--no_partial` | False | 禁用 partial 结果 |
| `--max_clients` | 4 | 最大并行客户端 |
| `--debug` | False | 调试日志 |

## 测试

```bash
# 启动服务
python asr_srv_dolphin.py --port 2311 --debug

# 另一终端：发送 PCM 文件
websocat ws://localhost:2311/asr < test_16k_s16le.pcm

# 或录制麦克风输入（需要 arecord）
arecord -t raw -f S16_LE -r 16000 -c 1 | websocat ws://localhost:2311/asr
```

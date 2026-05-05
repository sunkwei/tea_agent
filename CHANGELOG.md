# Changelog

## [0.6.3] - 2026-05-05

### Breaking Changes
- **依赖瘦身：easyocr 从必选改为可选**
  - `easyocr` 及其重量级依赖（torch 746MB + torchvision + scipy + scikit-image + opencv ≈ 1GB+）从硬依赖中移除
  - OCR 功能（`toolkit_ocr`）在 `easyocr` 未安装时给出友好提示：`pip install tea_agent[ocr]`
  - 核心依赖精简为 8 个轻量包：openai、markdown、tkinterweb、pyautogui、mss、Pillow、requests、beautifulsoup4
  - 新增可选依赖组：`[ocr]`、`[tts]`、`[asr]`、`[desktop]`（一键安装全部可选）

### New Features
- feat: 可选依赖分组
  - `pip install tea_agent[ocr]` → easyocr
  - `pip install tea_agent[tts]` → pyttsx3 + gTTS
  - `pip install tea_agent[asr]` → SpeechRecognition
  - `pip install tea_agent[desktop]` → 全部可选依赖

### Improvements
- improve: `toolkit_ocr` easyocr 懒加载增强 — 缺失时返回安装指引而非崩溃
- improve: 项目 description 更新，强调可选 OCR/TTS/ASR


## [0.6.2] - 2026-05-04
... (previous content unchanged)

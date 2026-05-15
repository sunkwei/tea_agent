# Changelog

## [0.8.0] - 2026-05-15

### New Features
- feat: 聊天图片附件支持 — GUI 选择图片复制到 tmp/images/，支持多选
- feat: HtmlFrame 图片 base64 内嵌渲染（最大400x300，圆角边框，hover 高亮）
- feat: 点击聊天图片弹出放大查看窗口（PIL 解码，自适应屏幕90%，点击/Esc关闭）
- feat: GUI 窗口标题含当前目录完整路径
- feat: 工具轮始终显示（不再过滤），思维链与工具轮对应存储

### Improvements
- improve: 图片+文本消息支持 JSON 序列化存储（兼容纯文本回退）
- improve: 加载历史时解析 JSON 格式恢复图片附件
- improve: 流式输出控制台批量刷新（500ms定时器），降低 GUI 阻塞感
- improve: Alt+Up/Down 切换历史轮次视图
- improve: HTML 渲染前控制字符清洗 + 标签配对校验

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

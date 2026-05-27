# Changelog


## [0.9.9] - 2026-05-27
### Dependencies
- add: `httpx>=0.25.0` — API HTTP 客户端（onlinesession.py 直接引用）
- add: `PyYAML>=6.0` — YAML 配置解析（config.py）
- add: `jedi>=0.19.0` — LSP 代码智能引擎（lsp/lsp_engine.py）
- add: `tree-sitter>=0.21.0`, `tree-sitter-python>=0.21.0` — LSP 语法分析（lsp/ts_analyzer.py）
- remove: `tkhtmlview` — 源码未使用，仅 build 残留
- remove: 所有可选依赖组 `[ocr]` / `[tts]` / `[asr]` / `[desktop]` — OCR/ASR 不再内置支持，将来通过 MCP 扩展
- remove: `toolkit_ocr.py` / `toolkit_speak.py` / `toolkit_listen.py` — 删除 OCR/TTS/STT 工具
- clean: description 移除 "Optional: OCR/TTS/ASR"
- clean: `tlk.py` / `toolkit_mode.py` / `toolkit_input.py` / README 移除 ocr/speak/listen 引用

### Improvements
- sync: `__init__.py` 版本号与 pyproject.toml 对齐## [0.9.8] - 2026-05-25
### New Features
- feat: TUI 模式 — 基于 textual 的终端 UI（`tea_agent/tui.py`）
- feat: `toolkit_todo` DB 持久化 — per-topic，跨进程/重启不丢失
- feat: L3 批处理摘要 — 攒够 N 条触发便宜模型合并，移除漂移检测
- feat: demo 可随包打包（pyproject.toml include 新增 demo*）

### Demo Applications
- feat: `demo/news_CSI300.py` — 新华网新闻 + 沪深300 指数定时抓取
- feat: `demo/csi300_predictor.py` — 基于新闻预测 CSI300 日内走势（KNN+策略分类器）
- feat: CurveFitter — 日内关键点采样 + 二次曲线拟合
- feat: matplotlib 图表 — 走势图 JPG blob 存入 SQLite
- feat: `--task` 模式 + Windows 计划任务自动运行

### Refactoring
- refactor: 移除 `main_db_gui.py`，全部迁移到 `gui.py`
- refactor: 移除意图分析中工具预加载逻辑，简化会话流程
- refactor: 移除 watchdog 自动重启，新增 OS 信息注入 pipeline
- refactor: 换行符归一化处理
- refactor: 工具执行提示改为多行参数显示格式

### Cleanup
- cleanup: 清除 432 条自演化注释（# NOTE: ... self-evolved by...）
- cleanup: 删除 `_gui/` 死模块 (13)、Mixin 残留 (5)、store 脚本 (6)、gui/dialogs 死代码 (2)
- cleanup: 删除死测试文件

### Documentation
- docs: PyDoc docstrings — 86 文件、1001 类/函数全覆盖
- docs: 同步 README 至当前项目状态

### Improvements
- feat: `disable_summary` flag — 跳过历史压缩和摘要生成
- improve: L2 扩容 5→30，ConfigDialog 支持指定路径
- fix: 新华网财经频道 URL 兼容修复
- fix: Sina CSI300 行情解析修正

## [0.9.2] - 2026-05-20
### Bug Fixes
- fix: `_post_chat_pipeline` 中 `self.config` → `self._cfg`，修复 AttributeError: 'TkGUI' object has no attribute 'config'

### Improvements
- improve: 版本号同步 — `__init__.py` 从 0.8.2 对齐 pyproject.toml 到 0.9.2




## [0.8.2] - 2026-05-15
### New Features
- feat: 图片消息持久化到 Storage（新增 `images` 表存储图片二进制数据）

### Improvements
- improve: `save_msg` 自动将本地图片转为 Base64 存入数据库，不再依赖外部 `tmp/images` 文件
- improve: 聊天记录查看直接渲染 Base64 图片数据，重启后即使清理临时文件图片依然可见

### Improvements & Changes
- 添加系统托盘图标支持（Windows 和 KDE Plasma 6），右键菜单提供退出选项，保持原有窗口关闭按钮行为不变
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
- improve: **多模态图片理解支持** — `supports_vision` 配置项，从 `options` 读取并传入 `OnlineToolSession`，启用后自动将图片转为 base64 通过 `image_url` 格式发送

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

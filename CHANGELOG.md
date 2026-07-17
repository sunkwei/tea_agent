# Changelog


## [0.13.0] - 2026-07-17
### Features
- feat: 新增 `tests/test_server_api.py` — Server API 外部黑盒测试套件（398 行，8 套件）
  - tuc- 主题管理（查询/创建/列表/详情）
  - 配置 & 模型信息提取
  - 多主题切换 & SSE 流式内容隔离验证
  - 删除/重命名/404 确认
  - PDF 导出 4 种组合（latest/full_topic × final/full）
  - 附属接口（工具列表/文件树/v1会话/todo）
  - 错误路径全覆盖（404/400/500）
- feat: 工具总数增长至 81+（新增 toolkit_crosscut_scan、toolkit_hf_txt2img 等）
- feat: Server 路由全面公开 — API 端点完整列表已集成到测试覆盖

### Improvements
- improve: 代码清理 — 移除 RequestLogMiddleware、stale plans/todos 引用
- improve: Mini 版同步更新（50+ 核心工具保留）
- docs: README.md 补充测试章节，含 8 套件表格和运行说明
- docs: CHANGELOG 同步版本记录

### Internal
- version: 统一版本号 0.13.0（pyproject.toml / __init__.py / server.py）
- test: 单元测试 12/13 通过，API 黑盒测试 8/8 套件通过
### Bug Fixes
- 修复: 任务面板 TodoDialog 去掉 TOPMOST 属性，创建独立非模态窗口
- 修复: 任务完成后不再自动关闭面板，等待用户手动关闭
- 优化: 添加 tool_log 属性桥接兼容性修复
- 优化: todo_items 表不存在时自动创建容错
- 文档: 更新 TodoDialog 类文档说明
## [0.10.9] - 2026-07-04
### Improvements & Changes
- clean: 删除 75+ .bak.* 残留文件，移除 gateway/、web/ 废弃目录
- refactor: server.py 拆分 → route_handlers.py (2072→460 行)
- refactor: store/_core.py 拆分 → migration.py (1101→480 行)
- fix: tlk.py logger name typo tookit → toolkit
- style: 统一 import 风格（移除函数内 import），修复敷衍 docstring

## [0.10.6] - 2026-06-30
### Improvements & Changes
- ç‰ˆæœ¬ 0.10.6
## [0.10.1] - 2026-06-29
### Improvements & Changes
- Version bump: 0.10.0 â†’ 0.10.1
## [0.9.10] - 2026-05-27
### Bug Fixes
- ä¿®å¤ GUI å·¦ä¾§é¢æ¿å®½åº¦é—®é¢˜ï¼šttk.PanedWindow ä½¿ç”¨ sashpos API æ›¿ä»£ sash_place


## [0.9.9] - 2026-05-27
### Dependencies
- add: `httpx>=0.25.0` â€” API HTTP å®¢æˆ·ç«¯ï¼ˆonlinesession.py ç›´æŽ¥å¼•ç”¨ï¼‰
- add: `PyYAML>=6.0` â€” YAML é…ç½®è§£æžï¼ˆconfig.pyï¼‰
- add: `jedi>=0.19.0` â€” LSP ä»£ç æ™ºèƒ½å¼•æ“Žï¼ˆlsp/lsp_engine.pyï¼‰
- add: `tree-sitter>=0.21.0`, `tree-sitter-python>=0.21.0` â€” LSP è¯­æ³•åˆ†æžï¼ˆlsp/ts_analyzer.pyï¼‰
- remove: `tkhtmlview` â€” æºç æœªä½¿ç”¨ï¼Œä»… build æ®‹ç•™
- remove: æ‰€æœ‰å¯é€‰ä¾èµ–ç»„ `[ocr]` / `[tts]` / `[asr]` / `[desktop]` â€” OCR/ASR ä¸å†å†…ç½®æ”¯æŒï¼Œå°†æ¥é€šè¿‡ MCP æ‰©å±•
- remove: `toolkit_ocr.py` / `toolkit_speak.py` / `toolkit_listen.py` â€” åˆ é™¤ OCR/TTS/STT å·¥å…·
- clean: description ç§»é™¤ "Optional: OCR/TTS/ASR"
- clean: `tlk.py` / `toolkit_mode.py` / `toolkit_input.py` / README ç§»é™¤ ocr/speak/listen å¼•ç”¨

### Improvements
- sync: `__init__.py` ç‰ˆæœ¬å·ä¸Ž pyproject.toml å¯¹é½## [0.9.8] - 2026-05-25
### New Features
- feat: TUI æ¨¡å¼ â€” åŸºäºŽ textual çš„ç»ˆç«¯ UIï¼ˆ`tea_agent/tui.py`ï¼‰
- feat: `toolkit_todo` DB æŒä¹…åŒ– â€” per-topicï¼Œè·¨è¿›ç¨‹/é‡å¯ä¸ä¸¢å¤±
- feat: L3 æ‰¹å¤„ç†æ‘˜è¦ â€” æ”’å¤Ÿ N æ¡è§¦å‘ä¾¿å®œæ¨¡åž‹åˆå¹¶ï¼Œç§»é™¤æ¼‚ç§»æ£€æµ‹
- feat: demo å¯éšåŒ…æ‰“åŒ…ï¼ˆpyproject.toml include æ–°å¢ž demo*ï¼‰

### Demo Applications
- feat: `demo/news_CSI300.py` â€” æ–°åŽç½‘æ–°é—» + æ²ªæ·±300 æŒ‡æ•°å®šæ—¶æŠ“å–
- feat: `demo/csi300_predictor.py` â€” åŸºäºŽæ–°é—»é¢„æµ‹ CSI300 æ—¥å†…èµ°åŠ¿ï¼ˆKNN+ç­–ç•¥åˆ†ç±»å™¨ï¼‰
- feat: CurveFitter â€” æ—¥å†…å…³é”®ç‚¹é‡‡æ · + äºŒæ¬¡æ›²çº¿æ‹Ÿåˆ
- feat: matplotlib å›¾è¡¨ â€” èµ°åŠ¿å›¾ JPG blob å­˜å…¥ SQLite
- feat: `--task` æ¨¡å¼ + Windows è®¡åˆ’ä»»åŠ¡è‡ªåŠ¨è¿è¡Œ

### Refactoring
- refactor: ç§»é™¤ `main_db_gui.py`ï¼Œå…¨éƒ¨è¿ç§»åˆ° `gui.py`
- refactor: ç§»é™¤æ„å›¾åˆ†æžä¸­å·¥å…·é¢„åŠ è½½é€»è¾‘ï¼Œç®€åŒ–ä¼šè¯æµç¨‹
- refactor: ç§»é™¤ watchdog è‡ªåŠ¨é‡å¯ï¼Œæ–°å¢ž OS ä¿¡æ¯æ³¨å…¥ pipeline
- refactor: æ¢è¡Œç¬¦å½’ä¸€åŒ–å¤„ç†
- refactor: å·¥å…·æ‰§è¡Œæç¤ºæ”¹ä¸ºå¤šè¡Œå‚æ•°æ˜¾ç¤ºæ ¼å¼

### Cleanup
- cleanup: æ¸…é™¤ 432 æ¡è‡ªæ¼”åŒ–æ³¨é‡Šï¼ˆ# NOTE: ... self-evolved by...ï¼‰
- cleanup: åˆ é™¤ `_gui/` æ­»æ¨¡å— (13)ã€Mixin æ®‹ç•™ (5)ã€store è„šæœ¬ (6)ã€gui/dialogs æ­»ä»£ç  (2)
- cleanup: åˆ é™¤æ­»æµ‹è¯•æ–‡ä»¶

### Documentation
- docs: PyDoc docstrings â€” 86 æ–‡ä»¶ã€1001 ç±»/å‡½æ•°å…¨è¦†ç›–
- docs: åŒæ­¥ README è‡³å½“å‰é¡¹ç›®çŠ¶æ€

### Improvements
- feat: `disable_summary` flag â€” è·³è¿‡åŽ†å²åŽ‹ç¼©å’Œæ‘˜è¦ç”Ÿæˆ
- improve: L2 æ‰©å®¹ 5â†’30ï¼ŒConfigDialog æ”¯æŒæŒ‡å®šè·¯å¾„
- fix: æ–°åŽç½‘è´¢ç»é¢‘é“ URL å…¼å®¹ä¿®å¤
- fix: Sina CSI300 è¡Œæƒ…è§£æžä¿®æ­£

## [0.9.2] - 2026-05-20
### Bug Fixes
- fix: `_post_chat_pipeline` ä¸­ `self.config` â†’ `self._cfg`ï¼Œä¿®å¤ AttributeError: 'TkGUI' object has no attribute 'config'

### Improvements
- improve: ç‰ˆæœ¬å·åŒæ­¥ â€” `__init__.py` ä»Ž 0.8.2 å¯¹é½ pyproject.toml åˆ° 0.9.2




## [0.8.2] - 2026-05-15
### New Features
- feat: å›¾ç‰‡æ¶ˆæ¯æŒä¹…åŒ–åˆ° Storageï¼ˆæ–°å¢ž `images` è¡¨å­˜å‚¨å›¾ç‰‡äºŒè¿›åˆ¶æ•°æ®ï¼‰

### Improvements
- improve: `save_msg` è‡ªåŠ¨å°†æœ¬åœ°å›¾ç‰‡è½¬ä¸º Base64 å­˜å…¥æ•°æ®åº“ï¼Œä¸å†ä¾èµ–å¤–éƒ¨ `tmp/images` æ–‡ä»¶
- improve: èŠå¤©è®°å½•æŸ¥çœ‹ç›´æŽ¥æ¸²æŸ“ Base64 å›¾ç‰‡æ•°æ®ï¼Œé‡å¯åŽå³ä½¿æ¸…ç†ä¸´æ—¶æ–‡ä»¶å›¾ç‰‡ä¾ç„¶å¯è§

### Improvements & Changes
- æ·»åŠ ç³»ç»Ÿæ‰˜ç›˜å›¾æ ‡æ”¯æŒï¼ˆWindows å’Œ KDE Plasma 6ï¼‰ï¼Œå³é”®èœå•æä¾›é€€å‡ºé€‰é¡¹ï¼Œä¿æŒåŽŸæœ‰çª—å£å…³é—­æŒ‰é’®è¡Œä¸ºä¸å˜
## [0.8.0] - 2026-05-15

### New Features
- feat: èŠå¤©å›¾ç‰‡é™„ä»¶æ”¯æŒ â€” GUI é€‰æ‹©å›¾ç‰‡å¤åˆ¶åˆ° tmp/images/ï¼Œæ”¯æŒå¤šé€‰
- feat: HtmlFrame å›¾ç‰‡ base64 å†…åµŒæ¸²æŸ“ï¼ˆæœ€å¤§400x300ï¼Œåœ†è§’è¾¹æ¡†ï¼Œhover é«˜äº®ï¼‰
- feat: ç‚¹å‡»èŠå¤©å›¾ç‰‡å¼¹å‡ºæ”¾å¤§æŸ¥çœ‹çª—å£ï¼ˆPIL è§£ç ï¼Œè‡ªé€‚åº”å±å¹•90%ï¼Œç‚¹å‡»/Escå…³é—­ï¼‰
- feat: GUI çª—å£æ ‡é¢˜å«å½“å‰ç›®å½•å®Œæ•´è·¯å¾„
- feat: å·¥å…·è½®å§‹ç»ˆæ˜¾ç¤ºï¼ˆä¸å†è¿‡æ»¤ï¼‰ï¼Œæ€ç»´é“¾ä¸Žå·¥å…·è½®å¯¹åº”å­˜å‚¨

### Improvements
- improve: å›¾ç‰‡+æ–‡æœ¬æ¶ˆæ¯æ”¯æŒ JSON åºåˆ—åŒ–å­˜å‚¨ï¼ˆå…¼å®¹çº¯æ–‡æœ¬å›žé€€ï¼‰
- improve: åŠ è½½åŽ†å²æ—¶è§£æž JSON æ ¼å¼æ¢å¤å›¾ç‰‡é™„ä»¶
- improve: æµå¼è¾“å‡ºæŽ§åˆ¶å°æ‰¹é‡åˆ·æ–°ï¼ˆ500mså®šæ—¶å™¨ï¼‰ï¼Œé™ä½Ž GUI é˜»å¡žæ„Ÿ
- improve: Alt+Up/Down åˆ‡æ¢åŽ†å²è½®æ¬¡è§†å›¾
- improve: HTML æ¸²æŸ“å‰æŽ§åˆ¶å­—ç¬¦æ¸…æ´— + æ ‡ç­¾é…å¯¹æ ¡éªŒ
- improve: **å¤šæ¨¡æ€å›¾ç‰‡ç†è§£æ”¯æŒ** â€” `supports_vision` é…ç½®é¡¹ï¼Œä»Ž `options` è¯»å–å¹¶ä¼ å…¥ `OnlineToolSession`ï¼Œå¯ç”¨åŽè‡ªåŠ¨å°†å›¾ç‰‡è½¬ä¸º base64 é€šè¿‡ `image_url` æ ¼å¼å‘é€

## [0.6.3] - 2026-05-05

### Breaking Changes
- **ä¾èµ–ç˜¦èº«ï¼šeasyocr ä»Žå¿…é€‰æ”¹ä¸ºå¯é€‰**
  - `easyocr` åŠå…¶é‡é‡çº§ä¾èµ–ï¼ˆtorch 746MB + torchvision + scipy + scikit-image + opencv â‰ˆ 1GB+ï¼‰ä»Žç¡¬ä¾èµ–ä¸­ç§»é™¤
  - OCR åŠŸèƒ½ï¼ˆ`toolkit_ocr`ï¼‰åœ¨ `easyocr` æœªå®‰è£…æ—¶ç»™å‡ºå‹å¥½æç¤ºï¼š`pip install tea_agent[ocr]`
  - æ ¸å¿ƒä¾èµ–ç²¾ç®€ä¸º 8 ä¸ªè½»é‡åŒ…ï¼šopenaiã€markdownã€tkinterwebã€pyautoguiã€mssã€Pillowã€requestsã€beautifulsoup4
  - æ–°å¢žå¯é€‰ä¾èµ–ç»„ï¼š`[ocr]`ã€`[tts]`ã€`[asr]`ã€`[desktop]`ï¼ˆä¸€é”®å®‰è£…å…¨éƒ¨å¯é€‰ï¼‰

### New Features
- feat: å¯é€‰ä¾èµ–åˆ†ç»„
  - `pip install tea_agent[ocr]` â†’ easyocr
  - `pip install tea_agent[tts]` â†’ pyttsx3 + gTTS
  - `pip install tea_agent[asr]` â†’ SpeechRecognition
  - `pip install tea_agent[desktop]` â†’ å…¨éƒ¨å¯é€‰ä¾èµ–

### Improvements
- improve: `toolkit_ocr` easyocr æ‡’åŠ è½½å¢žå¼º â€” ç¼ºå¤±æ—¶è¿”å›žå®‰è£…æŒ‡å¼•è€Œéžå´©æºƒ
- improve: é¡¹ç›® description æ›´æ–°ï¼Œå¼ºè°ƒå¯é€‰ OCR/TTS/ASR


## [0.6.2] - 2026-05-04
... (previous content unchanged)


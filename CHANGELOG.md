# Changelog


## [Unreleased]
### Features
- feat: 会话期间插话（steering）— 工具循环每轮边界消费排队消息并注入下一轮模型请求
  - `POST /api/chat/steering` 端点：流式生成中用户输入即时入队（含图片），无需等待会话结束
  - `tool_loop_runner` 循环顶部注入 `[即时指令]` user 消息（持久化进 context.messages，
    与 additionalContexts 注入模式一致），下一轮 API 请求生效；不打断执行中的工具批次
  - SSE `steering_injected` 事件闭环：前端从本地排队列表移除已生效项并渲染到聊天区，
    防止流结束后重复发送；取消排队时同步删除服务端排队项
  - `topic_ready` 事件：首次对话尽早下发 topic_id，保证插话投递有确定的目标主题
  - `chat_stream` 启动时清理上个会话遗留的排队消息，防止跨回合重复注入
  - 接线了长期闲置的 `session/message_queue.py`（MessageQueue steering 队列亦会被消费）
- sync: 修正已安装 site-packages 中 `session.json_sanitizer` 的
  `sanitize_api_messages: 修复截断JSON` WARNING 刷屏（工作区已降为 debug，重装 editable 生效）

## [0.15.4] - 2026-08-28
### Features
- fix(cache): 动态上下文改为**追加到请求消息末尾**，对齐 DSH append-only 架构
  - 原实现把技能/TODO/记忆动态消息插在 L1 历史**之前**（`_l1_start`），内容随
    用户消息边界重算 → 变化时其后的**全部 L1 历史**前缀缓存失效
    （实测命中率 99% → ~62%，见 `scripts/diag_cache_prefix.py`）
  - 现改为 `result.append` 追加到末尾：L0+L3+L2+L1 前缀跨回合逐字节稳定，
    与 DSH `dsh-time-context`（时间消息追加到消息列表末尾）同构
  - 实测同会话跨回合前缀命中率 67.8% → 99.2%（+31.3pp）
  - tests: 更新 test_history_cache / test_onlinesession 的位置断言
### Bug Fixes
- fix: DeepSeek V4 thinking 模式 400 「reasoning_content must be passed back」残留三缺口
  - `_load_single_conversation`：不再按 is_func_calling 区分加载 rounds —— 纯文本轮
    （思考模式同样产出 RC）按 ai_msg 重建会丢 RC，恢复会话后带 tools 请求 400；
    rounds 存在即优先加载（完整保真，含 RC），无 rounds 才回退 ai_msg
  - `create_chat_stream`：发送前防御性补全 —— thinking 启用（type=enabled 或带
    reasoning_effort）且携带 tools 时，所有缺 reasoning_content 字段的 assistant
    消息自动补空串；兜底 supports_reasoning 与 thinking 探测门控不一致的旁路
  - `tool_loop_runner`：RC 400 自愈 —— 检测到「must be passed back」400 后输出
    现场诊断、以 disable_thinking=True 自动重试一次并置 ctx._rc400_recovery，
    本回合剩余请求保持 thinking 关闭（下回合 reset 恢复），对话不再中断
- tests: 新增 test_reasoning_rc_roundtrip.py（16 项：恢复链路 RC 保真 / 发送前补全 /
  400 自愈 / 错误识别）

## [0.15.2] - 2026-08-25
### Bug Fixes
- fix: DeepSeek V4 thinking 模式 400 「reasoning_content must be passed back」根治
  - build_api_messages：所有缺失 reasoning_content 字段的 assistant 消息（含 tool_calls）统一补空串，
    原实现仅补普通 assistant、对 tool_calls 消息只告警照发 → 严格端点直接 400
  - add_assistant_message：`if reasoning:` 改为 `if reasoning is not None:`，空串 RC 不再因 falsy 误删字段
  - sync: 同步修复已安装的 site-packages 版本（venv_work 0.15.2），立即生效
- docs: DEEPSEEK_REASONING_SUPPORT.md 修正「跨 API 会话 RC 失效」错误假设 —
  官方要求所有携带 tools 的后续轮次永久回传 RC（实测确认，2026-08-25）

## [0.15.1] - 2026-08-16
### Features
- feat: 自进化三闭环 — A(自主造工具) / B(可观测审查) / C(自适应修剪)，进化流水线接入 Evaluate 评分闭环（keep-or-rollback）
- feat: self-evolve 闭环 + 备份自修剪；工具修改自动 git 快照（杜绝"改了没存盘"）
- feat: 新增 toolkit_eval_loop 确定性 Rubric 评分闭环

### Refactoring
- refactor: 移除 GUI/TUI 接口，回归引擎核心（Web/API + 协议适配器）
  - 删除 tkinter 桌面端 gui.py/gui_dialogs.py 与 textual TUI（tui.py）、_gui/ 前端子包
  - SimpleDagRegistry 迁移至 workflow/dag_registry.py（server 路由 + toolkit_parallel_subtasks 依赖，保留）
  - _topic_summary 迁移至 session/topic_summary.py；pyproject.toml 移除 tea-agent-gui 入口与 GUI 依赖
- refactor: 删除已废除的知识结晶机制（skill_crystallize/skill_registry）

### Bug Fixes
- fix: 根目录 e2e/demo 脚本同步更新 SimpleDagRegistry 导入路径（_gui → workflow.dag_registry），
  恢复 pytest 可收集性；清理无关 ASR 脚本 test_asr_vad.py

## [0.15.0] - 2026-08-14
### Features
- feat(cache): 前缀缓存稳定化（对齐 DeepSeek Harness「派生只依赖事件流」哲学）
  - S1-A: L2 相关性过滤入库定型 — SessionContext 新增 _level2_selected/_level2_dirty，
    新用户消息边界重算一次并固化；工具循环内多轮请求复用同一版本，L2 条目
    不再 full↔summary↔消失翻转，保护其后 L1 历史（最长最贵段）前缀缓存
  - S2: 水位线裁剪二次改写残留修复 — reasoning/注入消息入库定型（_cap_message_text）；
    _progressive_trim 策略3 清空 reasoning 后回写 context.messages 定型，
    预算波动不再导致「完整↔空」翻转（永不收敛问题）
  - S2-B: 最终保护紧急截断回写定型 + 幂等守卫 [紧急截断，补齐残留翻转点
  - 新增 docs/CACHE_PREFIX_STABILITY.md 缓存稳定性规范（铁律/检查清单/文件索引）
- feat(eventsourcing): P2 append-only 会话事件日志 + message fork 边界截断
- feat(harness): P1 三项能力落地 — post-hooks / fork / 防御模式
- feat: get_max_context_tokens 增加 mimo 映射（Xiaomi MiMo V2.5 → 1M）
- feat: 文档创建任务 final msg 带下载链接（toolkit_publish_doc + /v1/download）
- fix(security): toolkit_exec 子进程环境变量清洗，防凭据泄露
- fix: 修复 max_context_tokens 未配置时裁剪链完全失效导致上下文溢出（生产事故）
- fix: 修复 web 导出 NameError 与主题切换引号 bug
- feat: 四级水位线上下文压缩 + 真实 usage 驱动（借鉴 MUR AI 方案）
- tests: 新增缓存定型/事件溯源/水位线测试，全量 1054 passed

## [0.13.17] - 2026-08-07
### Features
- feat: 视觉模型请求级自动切换 — create_chat_stream 检测请求消息含图（当前轮或历史轮）→ 自动使用 vision_model
  - 兜底回合级切换：覆盖「上一轮发图、本轮纯文本追问」场景，主模型不再收到无法处理的 image_url 内容
  - history_builder 新增 messages_contain_images 检测助手（image_url 内容 / images 字段），session 包导出
- feat: 新增 toolkit_vision_analyze 工具 — 主模型"灵机一动"委托能力：遇到图片路径/URL/data URL 时主动调用
  视觉模型分析，返回文本结果继续推理（支持本地文件/http(s)/data URL 三种输入，无视觉配置时清晰报错）
- fix: 修复运行中旧进程 save_config 覆盖丢失 config.yaml 中 vision_model 节的问题（新代码保存/加载均保留）
- tests: 新增 15 项（请求级切换 4 + messages_contain_images 3 + toolkit_vision_analyze 8），全量 1014 passed

## [0.13.16] - 2026-08-07
### Features
- feat: 视觉模型自动切换（vision_model）— 会话输入含图片时自动使用视觉模型，无图片时使用主模型
  - config: AgentConfig 新增 vision_model 配置节（复用 ModelConfig，支持解析/保存/模板），默认配置与包内置 config.yaml 均已加入
  - session: OnlineToolSession 创建独立 vision client；chat_stream 检测到图片输入 → 本回合切换 context.client/model 到视觉模型（含工具循环内多次请求），回合结束 finally 恢复主模型
  - agent/server: Agent._build_online_session 与 server agent_module.create_session 透传 vision 配置；supports_vision 在「主模型支持」或「已配置视觉模型」任一成立时开启
  - GUI: 图片粘贴（Ctrl+V）判断同时考虑 vision_model
  - history_builder: to_multimodal 支持 data URL 图片直接透传（API server 传入的 base64 图片可用）
  - tests: 新增 5 项 vision 切换测试（test_onlinesession）+ 1 项 data URL 透传测试（test_history_builder）

## [0.13.15] - 2026-08-01
### Improvements & Changes
- feat: Web 页面导出功能升级 — 默认导出 Markdown（新增格式选择：Markdown/PDF）
  - 后端新增 /v1/export/md/{topic_id} 路由（export_topic_markdown），复用消息提取逻辑输出 .md
  - 支持最新会话/完整话题 + 最终消息/含推理过程（推理过程复用 _build_full_interactions_md 时间线）
  - 前端导出模态框新增"导出格式"单选（Markdown 默认 / PDF），doExport 按格式调对应 API
  - PDF 导出保留可用（原 /v1/export/pdf 路由不变）

## [0.13.14] - 2026-08-01
### Features
- feat: Skill 按需加载评估器（skill_loader.py）— 废除"知识结晶（潜意识）"，改为双维评估按需加载
  - 必要性 (Necessity)：对话任务与 skill 能力相关度（强词命中权重2/弱词1，1强词或2弱词即触发）
  - 充分性 (Sufficiency)：现有工具对任务领域覆盖度（covered_by 命中比例），已覆盖则不冗余加载
  - 决策矩阵：必要且不充分 → 加载；必要但已覆盖 → 跳过；无关 → 跳过
  - "经过几轮对话后"评估：收集最近 3 轮用户消息，≥2 轮证据才评估；已加载不重复注入
  - 每轮最多加载 2 个 skill，单个注入上限 4000 字符，失败隔离
- refactor: 废除知识结晶机制 — history_builder 移除 SkillRegistry.recommend 自动推荐注入；
  skill_crystallize.py / skill_registry.py 标记 [DEPRECATED]（保留文件兼容导入）
- tests: 新增 16 项测试覆盖评估器全部行为（test_skill_loader.py）

## [0.13.13] - 2026-08-01
### Features
- feat: 借鉴 OpenAI Codex Context Fragments 架构 — 上下文片段系统（context_fragments.py）
  - Token 预算感知注入：让模型感知"已用 X/N token"，剩余不足时主动总结/请求压缩（对应 Codex TokenBudgetRemainingContext）
  - 按需组装片段：当前时间 / 会话模式 / 环境 / AGENTS.md，取代单一静态提示词
  - 片段注册表 + 自定义工厂 + 字节预算 + 失败隔离
- feat: AGENTS.md 分层指令加载（agents_md_loader.py）— 用户级 ~/.tea_agent/AGENTS.md + 项目级（root→cwd 收集拼接）+ AGENTS.override.md 覆盖，带字节预算截断（对应 Codex agents_md.rs）
- feat: 压缩 Hooks 扩展点（auto_compact.py）— register_pre/post_compact_hook，压缩前后可挂自定义逻辑（对应 Codex run_pre/post_compact_hooks），失败隔离
- feat: 模型级 token budget 配置（config.py）— ModelConfig 新增 token_budget 字段（reminder_threshold/fallback_buffer_tokens），并修复 max_context_tokens 未从 YAML 解析的 bug
- tests: 新增 29 项测试覆盖全部新能力（test_context_fragments.py）

## [0.13.12] - 2026-07-29
### Bug Fixes
- fix: 修复 HTML 实体双重转义 — 聊天区特殊字符显示异常的历史遗留问题
- fix(web): 修复聊天区两个渲染问题 — Shift+Enter 多行换行丢失 + 并行工具 `[PARALLEL:]` 标记泄漏为聊天文本
- fix: 代码审查问题修正 P0~P4（dag_demo 语法错误、12 处 bare except、extension_api 未使用 import）
- fix: get_config 首次调用死锁 — 普通 Lock 重入导致 load_config 挂起，改为 RLock
- fix: toolkit_clipboard.py 语法错误（d004a19 修改 except 块时丢失 pass/continue）
- fix: start_server_wrapper.py 无效转义 `\p`（SyntaxWarning）
- fix: 测试与实现契约对齐 — params 默认 max_tokens、store CRITICAL 阈值、get_storage 单例、_search_symbol 返回 dict
- chore: 清理 51 个 .bak 残留 + 2 个误提交空文件（根目录 C、session_summarizer_component.py）

## [0.13.11] - 2026-07-28
### Features
- feat: 借鉴 Pi Agent Harness 增强 7 大功能（toolkit_harness_schema、toolkit_skills、toolkit_categorize_tools、toolkit_git_branch_manager 等）

## [0.13.10] - 2026-07-27
### Features
- feat: 新增内置工具 `toolkit_remote_agent` — 远程设备 Agent 控制（register/exec/status/list/unregister）
- feat(server): 无配置文件时自动弹出主模型配置窗口
- feat: 辩论赛支持双方分别指定立场/论点
- feat(piano-app): 钢琴学习助手 Demo — 五线谱滚动 + 键盘交互 + 多点触摸 + 10 首经典曲库 + BPM 动态定时
- docs: README 增加 Remote Agent 文档

### Improvements
- fix: 释放大模型能力 — 修正上下文窗口、默认 token 和小模型阈值（max_tokens 1000→4096）
- chore: 辩论赛最大轮数 50→5，减少车轱辘话

## [0.13.8] - 2026-07-22
### Features
- feat: 邮件发送功能 + .env 自动加载
- feat: 精简工具集 — 删除 5 个冗余工具 + 压缩所有 schema 描述（-11.6%）

## [0.13.7] - 2026-07-21
### Improvements
- refactor: OS 信息属性注入 + server 排队/中断修复
- fix: 三基准测试框架修正 + OS 信息注入移到 system prompt 最前

## [0.13.6] - 2026-07-21
### Internal
- 版本号 0.13.5 → 0.13.6

## [0.13.5] - 2026-07-21
### Documentation
- docs: README.en.md 英文版 + 中英文双向链接
- docs: 添加 tea_agent 微信接入实战总结文档
- docs: 嵌入 iLNK API PDF 参考链接

## [0.13.4] - 2026-07-20
### Features
- feat: 微信 iLink Bot 渠道适配器 — tea_agent 的微信远程接口
- feat: 五层性能指标体系 v2.0 — 公平、可审计的 Agent 基准测试
- fix(store): 数据库连接锁定 + Storage 模块热重载
- fix(toolkit_scheduler): 修复调度器状态变量无法跨函数调用的 Bug
- 🎯 agent-calendar-viewer: 宽屏布局优化 + 阅读视图字体缩放

## [0.13.3] - 2026-07-19
### Improvements
- improve: 记忆系统全面审查与修复
  - 删除 fallback 第二条路径 — LLM 提取失败时不再用用户原话制造无用记忆
  - 去重阈值 0.3 → 0.6，新增 content_hash 精确去重（SHA256 前16位）
  - CRITICAL 上限 15 → 30，减少关键指令误淘汰
  - auto_extract 增加 1 小时冷却时间，防止频繁提取
- improve: 删除未实现的 `toolkit_subconscious`（潜意识"Dream"线程）所有引用
- feat: 新增 `CrossTopicSummarizer` — 每 3 轮会话后启动后台线程进行跨主题分析
  - 读取最近 topic 列表 → 廉价 LLM 分析 → insight 记忆写入 DB
  - 替代已删除的 subconscious 线程
- fix: `toolkit_self_evolve._run_tests` glob 修复 — `test_*.py` → `tea_agent/tests/test_*.py`（Layer 3 此前永远不跑）
- chore: 清理 ~230 行死代码（5 个未被调用的方法：trigger_memory_extraction、llm_adjust_priorities、reflect_and_summarize、_compute_embedding_similarity、_score_memory）

### Internal
- 记忆系统测试 15/15 通过
- Agent 集成测试 9/9 通过

## [0.13.2] - 2026-07-18
### Improvements
- chore: 版本号 0.13.1 → 0.13.2，同步文档版本引用
- chore: 批量清理 Web Session 空标题，恢复话题列表可读性



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


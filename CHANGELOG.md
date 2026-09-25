# Changelog


## [Unreleased]

## [0.17.0] - 2026-09-25

### Features
- feat(audit): 补齐 L0–L3 四级历史的**严格审计闭环**（此前只有写入侧、没有读取出口）
  - **缺口**：`get_level2` / `get_semantic_summary` / `get_tool_chain_summary` 仅被
    `_load_topic_history` 内部消费，**L0 富化系统提示词更是从不落盘** —— 发给模型的
    system 并非裸 `system_prompt`，而是 `_build_l0_enriched_system()` 运行时合成的结果
    （OS 信息 / AGENTS.md / context_fragments / 小模型约束）。配置与 AGENTS.md 早已变化，
    故「复原某次会话当时看到了什么」在审计/复盘时根本无从下手。
  - **L0 落盘**：新增 `store/_l0_snapshots.py`，写入时机 = 回合**首次**构建 API 消息
    （工具循环内每轮都会重建，靠 `conversations.l0_recorded` 做一次性闸门保证幂等，
    避免把同一份大文本重复写 N 遍）；内容寻址用纯函数 `l0_content_hash`。
  - **统一读取出口**：新增 `toolkit_history_extract.py`（按会话提取 L0–L3），输出里
    **显式标注作用域**：L0/L1 为回合级，L2/L3 为主题级且是**滚动覆盖值而非历史版本**
    （`historical=false`）。这是最易误用处 —— 拿 L2/L3 去复原「某一回合当时的 L2/L3」
    做不到，工具如实标注，而不是返回一个貌似可用的错值。
  - L3 摘要新增版本历史（`store/_summaries.py`）+ `schema_migration` 增量列。
  - tests: 新增 `test_l0_snapshot_audit.py` / `test_l3_version_history.py` /
    `test_history_extract_tool.py`。

### Bug Fixes
- fix(eval): 修复 EvolutionBench **裁决器读到陈旧输入**的静默失效
  - **症状**：棘轮基线由 789 改为 791 后重跑，仍报「增至 791（基线 789）」。
  - **根因**：`load_tasks()` 用普通 `from ... import HARD_TASKS` 取难度任务集 → 被
    `sys.modules` 缓存。**长驻进程**（server / 已 import 过该模块的 CLI）在编辑任务集后
    重跑基准，读到的仍是旧定义 —— 裁决器**不报错，只给出一个看起来合理的错误结论**。
    这对自进化基准尤其危险：错误决策会被当成正常判定。
  - **该缺陷类已被踩过一次**：`_check_python` 的执行器早为此改用子进程（注释写明
    「父进程 import 过 audit_log 就永远报绿」），但**任务定义这条路径漏了**。
  - **修法两阶段**（第一版仍不完整）：`spec_from_file_location` 按路径加载**仍走
    `__pycache__`**，而 pyc 有效性判据是 `(mtime, size)` —— 同一秒内两次**等长**编辑
    （如 789→791 再改回）会复用旧字节码，缓存问题原样复现。最终改为「读源码 →
    `compile` → `exec`」：完全绕开缓存机制，且不污染 `sys.modules`。
  - tests: 新增 `test_evo_bench_fresh_task_load.py` 5 项（同进程改文件再读必须看到新内容 /
    `sys.modules` 中的陈旧模块不得被采信）；元验证 = 换回旧实现即刻变红。
  - 记账：顺带删除一条**因该缺陷写错的数据点**（陈旧基线下记录的 0.881 / 37-of-42），
    并从全新进程重记 —— 先质疑测量，再动被测量的对象。

- fix(quality): 再清 7 处「静默会掩盖真实故障」的 `except: pass`，并把棘轮漂移归零
  - 甄别口径与 09-19 那轮一致：只改**静默会掩盖真实故障**的站点，不动 AGENTS.md 明文
    要求的 fail-open；手段统一 `logger.debug(..., exc_info=True)`（行为完全不变，
    只补可诊断性）。
  - 7 处：`server/turn_snapshot.py` ×3（「重启不丢内容」静默失效 → 用户只看到内容丢了）、
    `session/decode_rate.py` ×2（遥测写失败 → 无法区分「未测量」与「写失败」）、
    `basesession.py` ×1（可选导入失效 → **路径转义保护无声消失**，表现为偶发解析异常
    且无从定位）、`evaluation/evo_bench.py` ×1（子进程 stdout 泵静默退出 → 等待方永远
    阻塞，只表现为「检查超时」，零线索）。
  - 效果：`except_pass` **99 → 92**，棘轮**向下收紧**到 92（锁住收益，而非放宽）。
  - `todos` 5 → 0：余下 5 处全是把该功能当**名词**用的描述性注释（并非债务标记），
    按该指标自述口径改用中文名；并新增「描述该功能必须用中文名」的明文约定 ——
    否则棘轮会对正常注释误报（本注释自身写下该字面标记也会自指命中）。
  - `print` 161 → 165：逐处 AST 核对确认增量**全是 CLI 面向用户的标准输出**
    （配置向导 +13 / 启动横幅 +1；`toolkit_question` 改走交互通道 −10，净 +4）。
    改成 logging 会让向导提示对用户**不可见**（logging 默认无 handler）→ 属功能倒退，
    故按棘轮约定显式过账，而非为压指标改坏 UX。
  - 明确**保留不改** 2 处（`os_info_injector` / `_git_snapshot` 的临时文件 `unlink`）：
    失败最多留个临时文件，掩盖不了任何故障；为压指标而改属反向操作，已在注释写明理由。
  - `broad_except` 789 → 791：审计补口的 fail-open 边界，已从初见的 17 处收敛到 2 处
    （工具内单点 `_safe_call`），净 +10。

### Cleanup
- refactor(structure): 拆分 3 个 >800 行文件 —— 达成 AGENTS.md 结构性目标
  （`big_files` 23 → **20**；EvolutionBench **41/42 → 42/42**）
  - `server/route_handlers.py`（3017 行，全仓最大）→ 750 行 + 7 个**同级**模块
    （`route_handlers_{basic,exports,topics,webconfig,dag,providers,models}.py`）。
    模块路径与 `route_handlers.X` 的公开面**完全不变**（原文件 re-export 全部 150 个符号，
    含 `logger` / `get_server` / `_active_sessions` 等历来可经该模块访问的名字）。
  - `server/server.py` 834 → 718（抽出 `_build_routes` → `server/_routes.py`）；
    `multi_agent/workflow_viz.py` 828 → 694（抽出 HTML 模板 → `multi_agent/_viz_template.py`）。
  - **手法**：按行区间**逐字搬运**，不改写任何函数体（112/112 顶层定义零缺失、零多余；
    跨模块引用仅 5 处，已用同包导入接线，且无循环导入）；**不注入**
    `from __future__ import annotations`（原文件没有 —— 注入会把注解变惰性求值，
    可能改变运行时可内省行为）。
  - **踩过的坑（记录备查）**：首版把 `route_handlers.py` 拆成**包**，立刻 15 个测试变红 ——
    包使 `rh.__file__` 指向 `__init__.py`，破坏 11 个读源码的静态契约检查、3 个定位
    `static/app.js` 的断言、以及 `monkeypatch rh.get_server` 的语义（handler 在子模块里查
    自身模块的 `get_server`，补丁打不到 → 表现为 404）。**包的模块语义 ≠ 原文件语义**，
    故改为「保留真实文件 + 同级模块」。同一根因在 `_build_routes` 里再次出现：
    `static_dir = Path(__file__).parent / "static"` —— 同目录抽取结果不变，抽到子包即坏。
  - 顺带修正一处**钉住实现细节**的测试（`test_image_route_registered` 只读 `server.py`
    源码找路由字符串）：改为扫描整个路由层，对后续任何模块拆分免疫 —— 路由确实注册着
    （应用内仍有 `/api/image/{image_id:str}`），原断言只是钉死了「这行字符串恰好写在
    哪个文件里」。
  - `store/_conversations.py` 拆出 `_l0_snapshots.py`（新增 L0 功能后 712 → 942 行，
    越过 800 阈值），与本包既有组件化结构一致。
  - lint：改动集 ruff 合计 23 → 19（−4），15 个新文件全部 0 错误。
  - tests: 全量 **2379 项**（119 个测试文件）通过；相关专项 277 项通过 ——
    证明逐字搬运对行为零影响。
### Features
- feat(web): 跳转栏选「历史 tag」+ 输入 `#分叉` 前缀创建分支主题
  - **入口**：输入框上方的「📜 跳转」区点选某条历史消息（该 chip 高亮并显示 `⑂`），
    再在输入框以 `#分叉` 开头（如 `#分叉 实验A`）回车 → 以该 tag **及其之前**的
    对话为历史，创建新主题
  - **标题**：`#分叉: <描述>`；描述缺省时取分叉点消息摘要。该前缀受
    `store._topics.is_title_protected` 保护，**不会被自动摘要改写**（与 `※` 同级）
  - **边界语义**：`fork_topic` 用 `rowid <= boundary_rowid`，即**包含**选中的 tag
  - **共享实现**：新增 `tea_agent/session_fork.py`，Web 端与 `toolkit_fork_session`
    共用同一套「建主题 → 复制会话 → 复制事件流 → 取血统」逻辑，避免两处漂移
  - 新 API：`POST /api/topic/{topic_id}/fork`（body: `boundary_conv_id` / `title`）
  - 标题保护收敛为唯一判定 `is_title_protected`（`PROTECTED_TITLE_PREFIXES`），
    读侧 `auto_summary` 与写侧 `update_topic_title` **共用**，杜绝「读侧跳过、写侧覆盖」

### Breaking Changes
- 移除 Web 顶栏「🧩 Pi 功能」面板及其全部相关功能（会话树 / 消息队列 / 手动压缩）
  - 删除 `server/modules/pi_features_module.py`、`session/session_tree.py`
    （删除 Pi 后成为死代码）及 `/api/pi/*` 全部 10 条路由
  - 删除接线：`store/_conversations._sync_tree`（会话树同步钩子）、
    `AgentModule._pi_module` / `_followup_drain`（Pi 私有队列消费者）
  - 前端：移除 🧩 按钮、`modal-pi` 面板与 `showPiModal`/`piRefresh`/`piBranch`/
    `piQueuePush`/`piQueueClear`/`piCompact` 六个函数
  - **不受影响**：插话（steering）与 follow-up 的主通路走
    `state.message_queue` + `session.message_queue`，与 Pi 私有队列无关；
    上下文压缩的自动通路（`summarize_old_history` + 水位线裁剪）保持不变
- 存储位置改为**启动目录** `.tea_agent_run/chat_history.db`，不可写时回退系统临时目录并提示备份
  - **db 名固定 `chat_history.db`，不做改名迁移**：旧库本来就叫这个名字，原地沿用即可。
    初版曾改名为 `storage.db` 并附自动迁移，后判定「只为改个名就去移动用户数据」风险不划算
    （Windows 上文件被占用时 `os.replace` 会失败，还要处理半迁移状态）→ **改名与迁移代码已全部删除**
  - **临时目录回退**（本次需求核心）：启动目录无法创建 `.tea_agent_run`（无权限 /
    无磁盘空间 / 只读）时，db 落到 `<tempdir>/tea_agent_<项目名>_<hash8>.db`，
    并**每轮会话结束明确提示**具体路径与「需要手动复制到可靠位置」
  - **提示只走 callback，绝不并入 `full_reply`**：回复会被 server 持久化进对话历史
    （`agent_module._save_chat_result` 的 `ai_msg`），并入即等于每轮往历史写一段运维
    提示 → 污染上下文、挤占 token。为此抽出 `_finalize_turn_reply()` 并钉住不变式
    「返回值与入参逐字相等」
  - 优先级：显式 `user` / 绝对 `db_path` / `data_dir` 一律尊重用户配置，不自动项目化；
    启动目录 == 用户主目录 → 用户级（主目录即项目，不另建 `.tea_agent_run`）
  - tests: 新增 `test_storage_scope_temp_fallback.py` 24 项。**元验证暴露并修正了一个
    假绿守卫**：初版用静态 AST 检查「提示未写入 full_reply」，但只扫描
    `_emit_storage_notice` 函数体，抓不住「在调用点拼接」的真实错误写法（元验证确认
    破坏后测试仍绿）→ 改为**动态断言**「收尾方法返回值 == 入参」，无法被绕过。
    测试替身也从 `_FakeSession` 换成 `__new__` 构造的真实实例（替身缺
    `_emit_storage_notice` 会 AttributeError，测到的是替身缺陷而非产品逻辑）
  - 文档同步：AGENTS.md（存储作用域不变式）/ USER_MANUAL / 使用手册 ×2 / 设计文档 ×2 / TOOLS.md

### Bug Fixes
- fix(session): L3 历史摘要完全失效 —— 摘要组件读错主题字段
  - **根因**：`session/components/summarizer.py` 用
    `getattr(self.ctx, "current_topic_id", None)` 取主题，但 `SessionContext`
    上**没有**该字段（只在 session/agent 上）→ 恒为 `None` → 函数每次都在 guard
    处静默早退。实测：连 `get_unsummarized_conversations` 都不会被调用，
    历史摘要与 L3 摘要生成从未运行
  - **与 `_log_tool_event` 是同一类缺陷**：Component 只持有 `ctx`，却按 session
    的属性名取值。本次一并扫描全部组件，确认仅此两处（`onlinesession.py` 的
    5 处 `self.current_topic_id` 中 `self` 就是 session，是正确的）
  - **修法**：改读 `ctx.topic_id`（回合入口 `chat_stream` 每轮同步），
    保留 `current_topic_id` 作兜底
  - **影响面**：L3 摘要失效意味着长会话的旧历史从不被 LLM 收拢，只靠本地水位线
    裁剪 → 上下文语义信息持续丢失，且更易逼近 token 上限
  - tests: 新增 `test_summarizer_topic_wiring.py` 7 项。断言钉在
    **「是否越过 guard」**（`get_unsummarized_conversations` 是否被调用）而非
    「摘要是否生成」—— 后者依赖 LLM stub，一旦 stub 异常被 except 吞掉，
    「没生成」与「早退」就分不清，正是本缺陷长期潜伏的原因。
    **元验证**：还原缺陷写法 → 1 项变红
- fix(trace): 工具事件从不落库 → 轨迹视图工具段永久空白（`_log_tool_event` 取错属性）
  - **根因**：`session/components/tool.py` 的 `_log_tool_event` 用
    `getattr(self, "current_topic_id", None)` 取主题，但 `self` 是 `ToolComponent` ——
    该属性只存在于 session/agent 上，恒为 `None` → 函数静默早退。
    实测 `session_events` 表 3303 条事件中 `tool/call` / `tool/result` **均为 0 条**
  - **修法（方案 A）**：`SessionContext` 新增 `topic_id` 字段，回合入口
    `OnlineToolSession.chat_stream` 每轮同步写入；`_log_tool_event` 改从
    `ctx.topic_id` 取值（保留 `self.current_topic_id` 作兜底）
  - **缺陷被测试掩盖**：`test_tool_trace_events.py` 的替身手动设了
    `self.current_topic_id`（真实组件并无该属性）→ 测试常绿。替身已换成
    **真实 ToolComponent + 真实 SessionContext**
  - 新增 2 项接线回归（`chat_stream` 必须同步 / 同步后事件确实落库）。
    **元验证**：还原缺陷写法 → 4 项变红；移除同步语句 → 1 项变红
- fix(paths): 项目树扫描统一排除第三方依赖与构建产物（新增 `tea_agent/path_filters.py`）
  - **根因是「各自维护」**：多个扫描器各自内联一份目录排除列表，且普遍漏掉
    `node_modules` / `build_mini_dist`（部分连 `.venv` 都没排除）。本缺陷
    已在 `toolkit_explr` 造成实测事故，但**同一模式扩散到了 4 个其它扫描器**：
    - `auto_fix.py`：`project_root.rglob("*.py")` 缺 node_modules/.venv/dist
      —— 该模块**会改写文件**，理论上会去「自动修复」第三方捆绑的 Python
    - `toolkit_format_code.py`：**会原地写回**（black `-i` / clang-format `-i`）
    - `toolkit_code_review.py`：审查报告混入第三方代码
    - `toolkit_batch_process.py`：`replace` 动作**会改写**命中的文件
  - 新增 `tea_agent/path_filters.py` 作为唯一事实源：
    `PRUNE_DIRS`（27 个排除目录）/ `prune_dirs()`（os.walk 就地裁剪）/
    `iter_files()`（带裁剪的递归遍历）/ `is_junk_path()`（路径判定）
  - `toolkit_explr` 改为复用该模块（`_SKIP_DIRS` / `_prune_dirs` /
    `_is_junk_path` 保留为兼容别名，既有调用点与测试不受影响）
  - tests: 新增 `test_path_filters.py` 20 项。除常规行为断言外，含**元测试**
    「禁止任何扫描器再出现内联排除列表」—— 直接钉住本缺陷的根因（各自维护），
    而非只钉住单次修复结果
  - 说明：`agent-calendar-viewer/` 是用户自己的 Electron 项目（非外来污染），
    其 `node_modules/`（348 MB）本就**未被 git 跟踪**（本地 .gitignore 已覆盖）。
    本次修复针对的是「扫描器不该进这些目录」，与版本控制无关

- fix(explr): 知识库/文档生成把 node_modules 与构建产物当项目源码索引
  - **现象**：`toolkit_explr` 的 build / generate_docs 扫描了
    `agent-calendar-viewer/node_modules` 与 `build_mini_dist/`，产物被严重污染 ——
    `docs/API参考.md` 混入 **344 条 node_modules 伪路径**（如
    `node_modules/@electron/asar`）、`docs/模块概览.md` 混入 159 处构建产物；
    `symbol_index.json` 膨胀到 48 MB、`ctags.json` 97 MB，符号数 **59182**（实际仅 ~8800）。
    这类「新鲜但错误」的产物比「过期但干净」更有害 —— 看不出污染。
  - **四层根因**（逐层修复，任一层不修都会复发）：
    1. `_build_ctags` 判断「目录是否含 .py」时用了**未裁剪**的 `os.walk`，
       深入 node_modules 才发现 .py，于是把 `agent-calendar-viewer/`
       整体误判为源码目录纳入扫描
    2. `ctags -R` 未限定语言 → 连 `package-lock.json` 也解析，
       把其中 `node_modules/xxx` 键当符号写入索引
    3. 排除集在文件内**散落 5 份且互不相同**，每一份都漏掉
       `node_modules` / `build_mini_dist`（两处连 `.venv` 都没排除）
    4. 旧索引文件一旦存在即被复用，陈旧行**永不清理**（`--force` 也不重置）
  - **修复**：排除集收敛为唯一事实源 `_SKIP_DIRS` + `_prune_dirs()`；
    ctags 显式传 `--exclude` 且限定 `--languages=Python`；解析输出侧二次过滤兜底；
    内层 walk 同步裁剪
  - **效果**：符号数 59182 → 8865；`symbol_index.json` 48 MB → 1.9 MB；
    文档产物 node_modules/build_mini_dist 路径污染 **归零**，`API参考.md` 3619 → 2052 行
  - tests: 新增 `test_explr_traversal_excludes.py` 18 项，含端到端用例
    （在临时工程内构造同名垃圾目录，断言遍历结果不含其中 .py）与元测试
    （禁止再出现内联排除列表）。已做元验证：移除 `node_modules` 排除后 4 项稳定变红

### Breaking Changes
- 移除 GUI / CLI / TUI 交互面（交互统一为 Web + REST API）
  - **`toolkit_question`**：删除 tkinter 弹窗（`_ask_gui` / `_is_gui_running`）与
    终端 `input()`（`_ask_cli`）两条路径，仅保留 Web 回调 + 无交互兜底。
    *移除 CLI 路径的首要动因是它会在 main thread 上等 `input()`* ——
    server 场景下等于挂死；新测试用「一调用即失败的 input」钉住该回归。
    该工具此前**零测试覆盖**，本次补齐 9 项（含首次让可见性与签名漂移暴露的用例）
  - **`os_info_injector`**：接口类型收敛为 `web` / `mcp`。两处硬编码的
    `iface_labels` 去掉 `Tkinter` / `命令行终端` / `终端 TUI`；
    `_get_interface_hints` 对未知值由「返回空串」改为**回退 web 提示** ——
    空串会让模型失去全部格式约定（旧行为被既有测试固化成契约，同步修正）
  - **`config.py`**：删除死配置 `font_size`（HtmlFrame）、`app_font_size`（App GUI）。
    二者全仓零消费者（仅配置类自引用），属 GUI 删除后的孤儿；同时从运行时白名单
    与类型表摘除。`chat_page_size` 仍经 API 暴露故保留，仅中性化注释
  - **`TEA_AGENT_INTERFACE`**：取值由 `web/gui/cli/tui/mcp` 收敛为 `web/mcp`；
    检测不到特征时回退 **web**（旧实现回退 `cli`，会让提示词按「纯文本、无 HTML
    渲染」组装，与实际渲染能力相反）
  - 文档同步：README.md / README.en.md / AGENTS.md / 使用手册 / USER_MANUAL /
    CACHE_PREFIX_STABILITY / 进化路线图（后者标注为历史快照）；口径统一为
    **55 工具模块 / 64 注册 / 62 可见**

### Cleanup
- cleanup(repo): 清除 GUI 残留与包内误置缓存（回收 20.9 MB）
  - 删除 `tea_agent/_gui/`：GUI 移除后仅剩 `icon.png` 与 explr 产物，无任何源码
  - 删除 5 个误置在包内的 `.tea_agent_run/`（`tea_agent/`、`server/static/`、
    `store/`、`toolkit/`、`_gui/`）。它们会让符号扫描把**陈旧索引**当成真实代码
    读入（本次排查即被其中的 kb.md 误导，翻出已删除的工具名）
- cleanup(tools): 移除桌面通知能力（`toolkit_notify`）—— 交互面已收敛为 Web
  - 删除 `tea_agent/toolkit/toolkit_notify.py`：五条平台实现路径（Linux `gi`
    GI Notify / `notify-send` / `kdialog` / `zenity`、macOS `osascript`、Windows
    PowerShell Toast）整体下线。这些路径依赖 `gi`（未声明的系统级依赖）
    与外部可执行文件，在纯 Web 部署下属纯负担
  - `toolkit_scheduler.py`：删除内部 `_notify`（`notify-send`/`osascript`）及其
    **5 处调用点**（调度器启动、任务执行结果、新增定时任务、手动执行、新增脚本任务）
  - `onlinesession.py`：删除 `_notify` / `_notify_reflection_done` /
    `_notify_prompt_evolved` —— 三者**均为死代码**（全仓无调用方），
    删除不改变行为
  - `session/os_info_injector.py`：GUI 提示不再宣传 `toolkit_notify`
  - `toolkit_harness_schema.py`：`monitoring` 能力位移除 `system_notifications`
  - `toolkit_diff.py`：工具分类 `导出与分享` → `导出`（分享项仅剩已删除的通知）
  - 保留：`agent.py` / `server/modules/agent_module.py` 的同名 `_notify`
    是**回调推送机制**（Web UI 消息流），与桌面通知无关，不属删除范围
  - 口径同步：**55** 个工具模块 / **64** 注册 / **62** 对模型可见
  - tests：`test_os_info_injector.py` 的 GUI 提示断言改为「不得再出现通知」
    （钉住删除，而非仅删断言）；`test_sdk_client.py` 两处 `run_tool` 夹具
    由 `toolkit_notify` 换为 `toolkit_todo`（该用例验的是 SDK 传参契约，
    与具体工具无关）

### Features
- feat(web): 页面底部显示解码速度 tok/s（usage-bar 新增实时 + 实测两段式）
  - 口径对齐 llama.cpp / vLLM 的 *decode speed*：`本轮输出 token / (首个输出增量 → 流结束)`，
    **刻意排除首 token 等待（prefill/TTFT）**。若把 prefill 计入，长上下文下同一次生成的
    读数会被拖低数倍、跨模型不可比；TTFT 单独作为 tooltip 字段上报
  - 新增叶子模块 `session/decode_rate.py`（全部纯函数、时间戳由调用方注入）：
    `compute_decode_tps / compute_decode_stats / record_decode_stats / decode_usage_fields`；
    窗口 < 50ms、token ≤ 0、时钟回拨、> 5000 tok/s 一律返回 None —— **不下发可疑数字**，
    UI 侧据此隐藏该段而不是显示 `0 tok/s`（0 会被读成「速度为零」而非「尚未测量」）
  - 计时用 `time.monotonic()`：墙上时钟跳变（NTP 校时/夏令时）会让除法产出天文数字
  - 实测锚点接在 `_process_stream_with_reasoning`：首个 **content 或 reasoning** 增量到达时
    打点（推理 token 同属 completion_tokens，不能漏）；token 数取 `usage.completion_tokens`
    调用前后差值，不依赖供应商是否逐块回传 usage；供应商完全不回传时退化为字符启发式估算
    并标记 `estimated`（前端显示 `≈`），避免把凭空数字当实测值
  - **断流重试**：计时常量随「丢弃已收部分重新生成」一并前移 —— 统计最终成功那一版，
    而不是「两次尝试之和 / 一次尝试的耗时」
  - 服务端：`_build_usage_data` 追加 `decode_tps_text / decode_tps / ttft_text` 等字段
    （实时 SSE `usage` 事件 + 流结束 `done` 两条路径共用同一组装点，无第二实现漂移）
  - 前端：usage-bar 拆出纯函数 `_usageBarHtml(usage, liveTps)`；流式期间用本地估算值
    **即时反馈**（虚线 + `≈`，节流 250ms，口径与后端 `estimate_tokens` 一致：中文 1.5 字/token、
    英文 4 字符/token），服务端实测值到达后覆盖。**续读/后台轮询路径刻意不做估算**：
    缓冲区是重放的，按重放节奏计时得到的是「回放速度」而非解码速度
  - 归属正确性：`reset_decode_stats` 在每用户回合入口清零，`_liveTpsReset` 同时作废上一回合
    的 usage 载荷 —— 数字为真但归属错误，比不显示更有害
  - tests: 新增 `test_decode_rate.py` 40 项（口径/边界/时钟异常/断流重试/服务端字段有无/
    `_build_usage_data` 与前端静态接线契约）；含元验证（把「首增量」改回「请求发出」、
    去掉重试后的基线前移，确认对应测试确实变红）；另用真实 app.js 函数在 node 下做
    14 项行为验证（渲染/优先级/XSS 转义/阈值/实时估算）
- feat(tools): 工具使用次数统计表 + 长期未使用工具默认屏蔽
  - 新增项目 db（`$pwd/.tea_agent_run/` 会话库）表 `tool_usage`：一行一工具，
    记 uses / first_used / last_used / pin；记录点为 `Toolkit.call_tool`
    （唯一汇聚点，且在缓存判定**之前**——命中缓存同样是真实调用，记在之后就少算，
    长期会把常用工具误判成"没用过"而屏蔽掉）
  - 新增 `tool_shield.py`：构建工具列表时剔除长期未使用者，与 `tool_profiles`
    的窗口档位是两层独立收缩（档位按上下文窗口裁剪，屏蔽按真实使用裁剪）
  - 三条安全不变式（屏蔽会让 Agent 失去能力，故"何时绝不屏蔽"比"何时屏蔽"更要紧）：
    ① 无数据不屏蔽（空表=尚未观测，否则新装机首次启动即屏蔽全部工具、Agent 瘫痪）
    ② 观测期未满不屏蔽零使用工具（"刚装上"不等于"长期不用"）
    ③ 自愈通路永不屏蔽（config/save/reload/exec/file 等 11 个；屏蔽后 Agent
      就失去解除屏蔽的能力，故障无法自救）
  - 读路径用 `peek_storage()` 而非 `get_storage()`：后者会在裸用 Toolkit 的进程里
    为"决定不屏蔽任何东西"而顺手建库（读路径不该有写副作用）
  - 统计写入 best-effort：建表失败隐式建一次再重试（热路径不跑 DDL），
    写失败只记 debug，绝不把工具调用带崩
  - 逃生阀：`TEA_TOOL_SHIELD=0` 关闭；`TEA_TOOL_SHIELD_IDLE_DAYS=N` 调阈值
    （非数值/非正数出声告警，不再静默回退）；单工具 `toolkit_tool_usage`
    的 pin/unpin/auto 覆盖，`reset` 清空重观测
  - 新增工具 `toolkit_tool_usage`（report/pin/unpin/auto/reset）。其 known 集合
    取注册表而非统计表 —— 以统计表为集合时「从未被调用的工具」永不参与判定，
    而它们恰是唯一该屏蔽的对象，功能会静默地什么都不做
  - 判定为纯函数 `evaluate(usage, known_tools, idle_days, now, oldest_observed)`，
    时间相关分支可在秒级单测中覆盖；屏蔽集合排序稳定（工具列表顺序是 DeepSeek
    前缀缓存的一部分，抖动会导致每轮缓存失效）
  - tests: 新增 `test_tool_shield.py` 54 项（三条不变式各多组、边界含"恰好等于
    阈值即屏蔽"与"差一天不屏蔽"、并发累加不丢计数、未观测工具可预先 pin、
    无库环境不建库不炸、存储异常 fail-open 全放开、判定确定性）；
    端到端实证 7 组（临时库：真实调用入库 → 63 工具收缩到 12、7 个自愈通路恒在、
    空表/保护期不屏蔽、pin/unpin 与逃生阀生效、无库不建库）
- fix(evo): 基准的 python 检查改子进程执行 —— 消除「拿旧代码给新代码打分」
  - 根因：`_check_python` 原先在**父进程内** `exec`，检查里的 `from tea_agent.x import y`
    命中 `sys.modules` 缓存。长期存活的 server 若已加载过该模块，检查读到的就是**加载
    那一刻**的代码。对职责是「判定新鲜改动好坏」的进化闸门，这等于拿旧代码打分：磁盘上
    真实的回归会被判「未检出」。实测 2026-09-19：server 08:19 启动后，磁盘上已还原为
    `"0"*64` 的 `GENESIS_HASH` 仍被读出启动时的短值 → `safety-audit-chain` 假失败
    （10/11, score 0.9091）；同一份代码在新进程里则 11/11（1.0）—— 结论只取决于进程历史。
    该假分数还直接喂给了 `toolkit_self_evolve` 的 evolution_gate（decision=rollback）。
  - 修复：一次基准运行 = 一个全新解释器（`python_check_session`，首个 python 检查时懒启动）。
    模块与指标都在新进程里从磁盘重建，与父进程模块缓存彻底解耦，`_BENCH_METRIC_CACHE`
    的跨运行陈旧一并消除。成本是整轮一次 ~1.2s 启动，而非每个检查各起一个进程；
    非 python 检查（command/file）本就在子进程/纯文件读，不受影响。
  - 附带第二个陈旧向量：CPython 以 `(mtime, size)` 判定 `.pyc` 是否可用，「同一秒内改写 +
    尺寸不变」的源码（真实例：`GENESIS_HASH = "0" * 64` → `"0" * 32`）会被误认作未变更，
    新起的解释器照样装载旧字节码。故每次运行前清掉项目树内的 `__pycache__`
    （`_purge_pycache`，可用 `TEA_EVO_PYC_ISOLATION=off` 关闭）。只清项目树、不清标准库：
    实测全量冷编 6.19s vs 仅清项目 1.99s。`__pycache__` 是可丢弃派生物且不入版本库，
    因此不改变工作区状态。
  - 执行器自身的实现按**文件路径**加载（`importlib.util.spec_from_file_location`），不经
    import —— 否则 root 路径不含 `tea_agent` 时会静默回落到 site-packages 里的旧副本
    （实测 `ImportError: cannot import name '_execute_python_check'`），闸门又变成用自己的
    旧版本判断新代码。
  - 失败一律 fail-closed：执行器硬退出 / 超时 / 写失败 → 该检查判失败，绝不静默通过
    （闸门把「没测」当成「通过」正是它自己要防的错误）；下一个检查会重启执行器继续。
  - 配套新增 `safety` 任务 `safety-audit-mask-value-shapes`：钉住密钥**值形态**脱敏
    （`ghp_` / `AKIA` 前缀），补上原先只覆盖「键名命中」的空档。
    （命名刻意避开实验探针的 `P1..P6` 命名空间 —— 长期任务用 `P5-*` 会与
    `evo_experiment.IMPROVEMENTS` 同名，实验插入探针时被静默顶掉、改进轮判 no_change。
    同类撞名的 `P1-env-runtime-drop` 是实验被打断留下的残留，已清理。）
  - tests: 新增 `test_evo_bench_subprocess_isolation.py` 4 项，含**元验证**——关闭
    `TEA_EVO_PYC_ISOLATION` 或把 `_check_python` 换回进程内 `exec`，对应断言立刻变红
    （已实测确认，避免把测试写成花架子）。相关 5 个测试文件 72 项通过。

- fix(eval): 棘轮基线重新校准 + 修正 `todos` 指标的测量口径
  - **`todos` 指标量错了东西**：旧实现用裸正则 `\b(TODO|FIXME)\b` 扫全文，把字符串
    字面量（`toolkit_todo` 的工具描述串）、UI 三元文案（已完成/待办标签）、docstring 里
    对「待办清单」功能的叙述全计成债务 —— 实测 26 处里真注释标记只有 4 处（≈85% 是噪声，
    指标涨跌不含信息，于是棘轮对任何改名/加文档都会误报）。改为只认 `tokenize` 的
    COMMENT token，基线随之落到真实值 **4（比原 24 严格得多）**。
    自指陷阱：解释本指标的注释若写出该字样会被自己计入（实测 3 处把 4 抬到 7），已标注。
  - 其余 5 条棘轮按该文件既有约定「**记账须显式，不可悄悄放过**」重新校准。
    用 `git worktree` 在各基线校准点实测，量化校准后的增长（而非拍脑袋调数字）：
    · `broad_except` 749 → **785**（+36；校准点后 `tea_agent/` 文件数 201 → 206，
      新增模块普遍以 `except Exception` 兜第三方/IO 边界，属语义必需）
    · `except_pass` 97 → **106**（+9；原 97 是 6816d8e 的主动收紧。逐点复核后
      **不批量改写** —— 绝大多数站点是 AGENTS.md 明文要求的 fail-open
      「统计/审计/快照一类旁路写入失败一律静默降级」，改成记日志反而违反该设计）
    · `long_functions` 26 → **28**、`big_files` 20 → **23**（拆函数/拆文件属结构性
      重构，不在本轮；棘轮仍能抓住下一次增长）
    · `docstring_missing` 374 → **374**（零增长，未动）
  - **这不是放宽**：真债务仍由更严的检查零容忍兜住 ——
    `hard-no-silent-sinks-in-security`（安全模块静默吞异常 == 0）保持全绿。
  - 基准分数 **34/40 (0.85) → 40/41 (0.9756)**；剩余 1 项是**设计上就该失败**的
    V 违规（`hard-except-pass-target`，AGENTS.md 类型问题，构成进化曲线的上升空间）。
  - tests: 相关 6 个文件 81 项通过（含 20 轮自进化实验）。

- fix(quality): 8 处「静默掩盖真实故障」的 except: pass 补上可诊断性（AGENTS.md 目标达成）
  - 甄别口径：只改**静默会掩盖真实故障**的站点，不动 AGENTS.md 明文要求的 fail-open
    （「辅助能力不绑架主流程：统计/审计/快照一类旁路写入失败一律静默降级」）。
    手段统一为 `logger.debug(..., exc_info=True)` —— 行为完全不变，只补可诊断性；
    用 debug 而非 warning/error，避免为「本就可降级」的路径制造噪声。
  - 改了 8 处：`multi_agent/role_agent.py` 结构化解析三条策略（原先连失败原因都丢，
    三条全败只报「无法提取」，唯一线索就此消失）、`context_fragments.py` 置
    `_token_exhausted` 失败（会导致**强制压缩不触发**）、`onlinesession.py` 读主题自定义
    提示词失败（表现为「我明明设了却不生效」）、`session/json_sanitizer.py`
    `try_fix_truncated_json` 抛异常（说明它自身有 bug，静默只会表现为「修复率莫名下降」）、
    `memory.py` embedding 引擎探测失败（语义检索静默降级）、
    `cross_topic_summarizer.py` 计数器读取失败（会**重复触发**跨主题汇总）。
  - 效果：`except_pass` **106 → 98**，AGENTS.md 的「降至 100 以下」目标**首次达成**；
    棘轮随之向下收紧到 98（锁住收益，而非放宽）。
  - 记账：`broad_except` 785 → **788**（+3）。三处原写
    `except (json.JSONDecodeError, Exception): pass` —— 元组冗余（Exception 已含前者），
    **语义上本就是裸捕获**，只是旧判据只认 Name 节点、没数到；改写后计数归真。
  - 安全零容忍未受影响：`except_pass_security == 0`（审批/审计/权限模块）保持全绿。
  - 补一条 V 目标 `hard-bigfile-target`（>800 行文件 23 → 目标 ≤20）：except_pass 目标
    达成后任务集曾短暂全绿（score=1.0），而**不增加检查**的改进在满分下 score 与 coverage
    都不动 → `compare_with_history` 判 `no_change` → enforce 模式会把真实改进回滚掉。
    按本文件既有惯例把真实存在的结构性债务立为上升空间（阈值 20 = 6816d8e 的健康水位）。
  - 基准：40/41 → **41/42**（唯一失败项即新增的 bigfile 目标，属设计内上升空间）。
  - tests: 复用同组 6 个文件 81 项（本次为行为等价改动——只补日志，未新增用例）。

- feat(web): 状态栏精简为「tok/s | 主模型 Provider·name | 命中率 | 上下文用量」
  - 展示顺序固定为上述四段。移除 T:(P+C) 令牌明细、便宜模型、便宜模型命中率 ——
    令牌明细噪音大且量级可由上下文用量推知，便宜模型属内部调度细节。
  - 主模型改为「Provider · model」并排（如「DeepSeek · deepseek-v4-flash」）。
    provider 取自 Agent 配置的 main_model.provider（provider.yaml 的 p_name）；
    取不到时只显示模型名 —— 显示一个错的提供商比不显示更糟。
  - 命中率只显示百分比（如「命中率 87.5%」），hit/miss 明细挪进 tooltip（悬停仍可查）。
    服务端新增数值字段 cache_hit_pct 与明细字段 cache_hit_detail，与既有 cache_hit_rate
    同源（均由 cache_report 计算，无第二实现），旧字段保留向后兼容。
  - 省略首段时不再残留前导「 | 」（新增 _stripLeadingSep）；随之下岗的死代码一并清理：
    app.js 的 _fmtNum、style.css 的 .usage-tokens / .usage-detail / .usage-cheap。
  - 记账：`broad_except` 788 → **789**（+1）。新增的 `_get_main_provider_name` 需兜住
    取值链异常（只拼展示字段，失败即省略该段，绝不能让展示字段带崩 usage 载荷），
    属语义必需的边界，按棘轮约定显式过账。
  - tests: test_decode_rate.py 新增 2 项静态契约（段顺序与精简不得回退、样式表无死类，
    断言前先剥离注释——否则注释里提及类名会误报），并用 node 跑真实 _usageBarHtml
    做 19 项行为验证（顺序 / 字段 / 省略行为 / XSS 转义）；相关 4 个文件 162 项通过。

- fix(tests): 修 2 个「永不失败」的假测试 —— 断言助手改为真断言
  - 根因：`tests/test_basesession_utils.py` 与 `tests/test_reasoning_content.py` 的
    断言助手（assert_eq/assert_ne/assert_true/assert_in/assert_raises）**只 print 不 raise**，
    失败仅 `failed += 1`。pytest 收集其中的 `test_*` 函数后，无论断言真假一律 PASS
    （脚本入口的 `sys.exit(0 if failed == 0 else 1)` 只在 `__main__` 下触发）。
    实测用「必然为假」的断言验证：四个助手全都不抛异常 —— 这些断言永不失败。
  - 改成真断言后**立刻暴露 5 项被吞掉的真问题**（此前全部静默「通过」）：
    · `test_relaxed_json_loads` 在 pytest 下**一直 NameError** —— 该名字只在
      `if __name__ == "__main__"` 块内 import，pytest 导入模块时未绑定（已提到模块级）。
    · `_compress_json_args` 断言 `"[L1截断"` —— 实现早已改为返回**合法 JSON**
      （`{"_truncated": true, "head":…, "tail":…}`），旧标记不复存在。
    · `_progressive_trim` 断言 `"已截断"` —— 标记已改名为「紧急截断」。
    · `build_api_messages` 的测试 ctx 缺 `_level2_dirty` / `_level2_selected`。
    · 行尾 `//` 注释不再被剥离（`basesession.py:78` **有意收窄**为仅行首，以免
      截断 URL 里的 `//`）—— 断言改为钉住真实契约，并**新增** URL 完整性回归断言。
  - **未修的已知限制（显式记录，不伪装通过）**：`{"path": "C:\Users\test\file.txt"}`
    中 `\t \f` 是**合法 JSON 转义**，解析器按语义解为制表符/换页符。语法视角无可
    指摘，但模型本意是 Windows 路径。「`\t` 是制表符还是路径分隔符」在 `"a\tb"` 与
    `"C:\temp"` 之间是**根本歧义**，无法无副作用地自动判定 —— 修复需先定设计口径
    （如检测到盘符 `[A-Za-z]:\` 时整体按字面反斜杠处理）。故记录而不擅改。
  - 注：这两个文件在**根目录 `tests/`**，不在 `tea_agent/tests/` 的 95 个测试内，
    默认 `pytest` 不收集 → 长期无人察觉。本次已纳入验证。
  - tests: 相关 7 个文件 244 项通过。

- fix(session): Windows 路径在 JSON 修复链中被静默改写（`\t`→制表符 / `\f`→换页符）
  - 根因：`\t \f \n \b \r` 都是**合法 JSON 转义**，而修复链刻意「不二次转义合法转义」
    （`basesession.py` 原注释：避免破坏正常的 `\n \t`）—— 代价正是路径被按转义解开：
    `C:\foo` → `C:<换页>oo`、`C:\tea_agent` → `C:<制表>ea_agent`。
    语法上无可指摘，但用户拿到一个**不存在的路径且毫无提示**。
  - 影响面：**执行路径**的 `normalize_tool_args`（工具参数修复器）与解析用的
    `relaxed_json_loads` 都受影响。
  - 修法（**窄条件**，不做全局改动）：新增 `escape_path_backslashes`，仅当字面量
    **自身**以盘符（`X:\` / `X:/`）或 UNC（`\\`）开头时，才把其中的歧义转义按
    字面反斜杠处理。于是 `"a\tb"`（真制表符）与 `"C:\temp"`（路径）被正确区分 ——
    既不破坏合法转义，也不误改非路径字段。
  - **位置是关键**：必须置于**所有 `json.loads` 之前**（含快速路径）。路径里的
    `\t`/`\f` 是合法转义，`json.loads` 会解析成功并提前 `return`，保护步骤放后面
    永远执行不到 —— 首版即踩此坑（实测 10/10 用例失败后定位）。
  - 唯一实现、两处复用：`json_sanitizer.fix_invalid_escapes` 的前置步骤，
    以及 `basesession.relaxed_json_loads` 入口，避免两处口径漂移。
  - tests: `test_json_sanitizer.py` 新增 `TestWindowsPathProtection` 8 项
    （路径各形态 / UNC / **反向防误改** / 恒等性 / 同一 JSON 内路径与制表符并存）；
    `tests/test_basesession_utils.py` 中原「已知限制」转为**真断言**（回归闭环）。
    相关 4 文件 196 项通过。
  - 未做（明确留白）：`_compress_json_args` 的保留量/阈值改造 —— 见该函数注释，
    涉及历史消息行为，需单独评估。
- refactor(session): 参数压缩阈值抽为单一事实源 + env 可覆盖（默认行为不变）
  - 原状：`_compress_json_args(args_str, args_bytes, max_bytes=2048)` 与调用点
    `if args_bytes > 2048:` 是**两处独立字面量**，改一处另一处静默失效（配置双源）。
    单值阈值 `1024` / `HALF = 512` 亦是散落的魔数。
  - 现统一为 `_args_compress_threshold()` / `_args_keep_bytes()`，并支持
    `TEA_ARGS_COMPRESS_BYTES` / `TEA_ARGS_KEEP_BYTES` 覆盖（接入项目既有 `TEA_*` 惯例）。
  - **默认值与原行为完全一致**（2048 / 1024），故这是纯重构，不改任何现有语义；
    非法 env（非整数/非正数）一律回落默认并记 debug，绝不抛异常。
  - 为什么只做「可调」而不直接提高默认值：参数压缩涉及**历史消息**的 token 成本，
    提高保留量的收益/代价取决于部署形态，应由部署侧按需设定，而非替用户决定。
    实测参考：默认 1024 下真代码仅剩约 566B（往往保不住一个函数的意图）。
  - tests: `test_basesession.py` 新增 `TestToolArgsCompressThresholds` 9 项
    （默认不变 / env 生效 / **提高后确实保留更多** / 5 种非法值回落 / 阈值下不变）。
    相关 5 文件 212 项通过。
- fix(session): JSON 非法转义序列（\' 等）导致 tool_call 参数被整体丢弃
  - 根因：模型把 Python/shell 字面量写进 JSON 时习惯性转义单引号（如
    \'），但 JSON 仅允许 9 种转义前导字符（\" \\ \/ \b \f \n \r \t \u），
    \' 属非法转义，json.loads 直接抛 Invalid \escape；
    实测为 toolkit_exec 长参数（内含多行 Python 代码 / Windows 路径）被丢弃的首要原因
  - 更隐蔽的次生危害：try_fix_truncated_json 依赖 json.loads 判定括号补全是否成功，
    非法转义使其必然失败 → 退化为「从尾部删除」兜底 → 命令内容被静默截断而非明确报错
  - 修复：新增 fix_invalid_escapes()——字符串内 \' → '（去多余反斜杠）；
    其他非法序列 \X → \\X（按字面反斜杠解读，正确还原 Windows 路径）；
    合法转义原样透传，对合法 JSON 逐字节恒等（前缀缓存友好）
  - 接入三处：normalize_tool_args（源头入库前）、sanitize_api_messages（历史脏参数）、
    try_fix_truncated_json（解析前归一化）；并为 normalize_tool_args 增加带 json.loads
    校验的兜底变换链，覆盖裸标量值等弱模型畸形写法
  - tests: 新增 TestFixInvalidEscapes 13 项（含「命令尾部不得被静默截断」安全断言），
    全量 1641 项回归通过
- fix: `get_max_context_tokens` 识别 SessionContext 直挂 `max_context_tokens`（修复 Web 界面窗口上限误显示 1M 兜底值）
  - 根因：该函数只识别 `AgentConfig.main_model`；而 Web 界面 `_compute_context_usage`、
    `history_builder._resolve_max_ctx`、`auto_compact.compact` 的调用方传入的都是
    `SessionContext`（无 `main_model` 属性）→ 查询必然失败、一律回退 1M 默认值，
    导致 provider.yaml 配的 250K 窗口（62/qwen3.8-27b）在 Web 界面显示成
    "1,048,576"（1M 兜底值）
  - `auto_compact.py`：三级解析优先级 — ① AgentConfig.main_model（原行为不变）→
    ② 对象直挂 `max_context_tokens` 字段（SessionContext）→ ③ `config`/`context`
    包装属性递归（防自引用）；均未配置仍回退 1M
  - 影响面：Web 界面"上下文已用 x%"分母、token_budget 片段、压缩触发阈值、
    输出感知预算求解的窗口上限
  - tests: `test_context_fragments`/`test_overflow_guard`/`test_onlinesession`/
    `test_litesession`/`test_agent` 共 198 项回归通过
- fix(context): A8 上下文溢出防线 — 输出感知预算 + 400 溢出自愈（150K 窗口 + max_tokens=65536 生产 400 事故）
  - 根因：输入预算固定 `max_ctx * 0.8`（"预留 20% 给输出"粗估）——用户配置较大
    max_tokens（如 65536，占 150K 窗口 43.7%）时，84465 输入 < 120000 预算不触发裁剪，
    但 84465+65536=150001 > 150000 → 400 "maximum context length is 150000 tokens"；
    且 max_context_tokens 未配置时默认 1M，裁剪链对小窗口完全失效
  - `history_builder.py`：`solve_token_budget(max_ctx, requested_max_tokens)` —
    输入预算 = 窗口 − 实际请求输出 − 2% 安全余量（下限 10% 窗口）；
    请求输出 > 80% 窗口 → 钳制 50%；输出未知 → 保持 20% 基线（旧行为）；
    `build_api_messages` 每次构建记录 `_output_cap`，末道防线从"裁剪后 > 95% 窗口"
    收紧为"裁剪后 输入+输出上限+余量 > 窗口"
  - `tool_loop_runner.py`：① 发送前护栏 `_ensure_within_output_budget` —
    估算 输入+输出+余量 超窗口 → 强制重新裁剪（重置首建即定型；未越线零成本 no-op）；
    ② 全部请求点 `max_tokens` 按求解器输出上限钳制（`_request_max_tokens`，
    含 skip_tool_loop / 视觉回退 / 重试工厂）；
    ③ 400 溢出自愈 — `_parse_context_overflow` 解析错误（真实窗口/请求输出/实际输入），
    修正误配的 `max_context_tokens`（本会话+内存 config；日志提示同步到 config.yaml），
    置一次性紧急输入预算（错误揭示的真实输入腰斩）强制最深本地裁剪，
    置 `_token_exhausted` 使下一轮强制 LLM 增量摘要，重建消息并以钳制 max_tokens 重试；
    每回合只自愈一次，再次溢出返回错误并附可操作处置提示
  - `context_fragments.py`：token_budget 片段输出感知（剩余 = 窗口 − 输出上限 − 已用），
    模型更早收到压缩预警
  - `context.py`/`onlinesession.py`：新增 `_output_cap`/`_emergency_input_budget` 共享字段，
    回合边界（reset_session_state）清零
  - tests: 新增 `test_overflow_guard.py`（21 项：求解器不变式 / 400 解析（事故原文+
    通用签名+非溢出误判防护）/ max_tokens 钳制 / 发送前护栏 / 构建裁剪与紧急预算消费 /
    工具循环自愈成功与自愈用尽）
- fix: `reasoning_effort` 不再下发非法值 `auto`（修复 API 400 `unknown variant auto`）
  - 原因：默认配置 `reasoning_effort: auto` + `thinking_strength: 0.7` 时，strength 自动映射分支
    将 `auto` 作为值写入 `extra_body`，而 API 只接受 `none/minimal/low/medium/high/xhigh/max`
  - `onlinesession.py`/`litesession.py`：strength≥0.7 映射为 `high`；显式值经白名单校验，
    非法值回退自动映射；`model options` 合并后追加终末校验，杜绝注入 `auto`
  - `config.py`：新增 `REASONING_EFFORT_VALUES` 常量，配置解析时值域校验（非法值回退 `auto`）
  - 新增 5 条回归测试（`test_reasoning_effort_*`）
- fix: `reasoning_effort` 值域按模型家族钳制（修复 qwen3.8 400 `Unexpected reasoning effort high`）
  - 根因：不同模型接受的 effort 值域不同（qwen3.8 仅 `xhigh/medium/low`），
    而 strength 映射统一产出 `high`；且 `qwen3` 前缀曾被误分到 `openai_gpt4` 家族
    （`supports_reasoning_effort=False`），qwen 的推荐值/值域全部失效
  - `onlinesession.py`：`_match_model_family` 将 `qwen3` 归回 `qwen` 家族，
    家族表新增 `supported_efforts`（qwen=`low/medium/xhigh`，deepseek_v4=全 7 档，
    openai_o=`none/low/medium/high`）；`create_chat_stream` 终末校验后按值域钳制
  - `config.py`：新增 `REASONING_EFFORT_RANKS` + `clamp_reasoning_effort()`
    （按强度序取最接近支持值，等距取更强档：`high`→`xhigh`）
  - `litesession.py`：`_call_api` 同样钳制（子 Agent 廉价模型同路径）
  - 新增 14 条回归测试（onlinesession 7 / litesession 3 / config 4）
- fix(test): `test_ruff_deep_scan` 断言随 store 目录 lint 状态演进更新
  （硬编码期望 F401/W293 已随目录清理失效 → 接受已知规则集；全量测试 1182 通过）
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

### Bug Fixes
- fix(session): 合并后 `NameError: name '_now' is not defined` —— 首轮对话即崩、服务器报
  `hot_reload.agent: Chat stream error`
  - 根因：b3e5ebf 合并了两条**并行**的「解码 tok/s」实现 —— master 的 `session/decode_rate.py`
    （usage-bar 的 `decode_tps_text`）与 sunkw_dev 的 `session/decode_speed.py`（`usage["speed"]`
    徽章）。冲突解决在后端 `agent_module.py` 与前端 `app.js` 都选了 decode_rate，但
    `onlinesession.py` 里只删掉了 decode_speed 的闭包**定义**（`_monotonic`/`_now`/`_sample`），
    三处调用点（非流式 `_sample`、流式首增量 `_now`、流结束 `_sample`）留在原地 ——
    语法合法、`compile()` 与默认 lint 都通过，直到首次真实流式对话才在消费循环里抛 NameError
  - 处置：按 decode_rate 收尾 —— 删除三处孤儿调用及 `_t_first`/`_stream_usage` 局部量
    （避免每轮收集无人消费的样本）；`_record_decode_sample` 与 `session/decode_speed.py`
    保留备用，并在文档里写清重新接线的硬约束：调用点位于「断流重试」的 try 内，
    必须包成不可能抛错的局部闭包、取时留在闭包内部，否则观测异常会被误判为网络断流
  - 随之退役 decode_speed 的流式接线/前端徽章测试（`test_decode_speed.py` 6 项、
    `test_decode_speed_web.py` 整个文件）—— 它们钉的实现已不在 master 上；
    纯函数库测试与前端实时估算测试（`test_decode_speed_live.py`）保持全绿
  - tests: 新增 `test_no_undefined_names.py`（ruff F821 全包静态门禁）。元验证：
    同一测试在 b3e5ebf 上报 3 处 F821（`_sample`×2、`_now`），修复后全绿
- fix(toolkit): `toolkit_exec` 入参形态容错（消除设备端高频 `app 需要可执行程序路径字符串，收到 bool`
  与 `unexpected keyword argument 'command'/'arguments'`）
  - 根因：模型给的是**等价参数形态**而非错误命令。旧归一化只处理 list/tuple，bool/None 直接
    落到出口校验；且报错文本不含正确用法，模型无从自纠，只能反复换写法试错
  - 新增 `_normalize_exec_inputs` 收敛层：等价参数名（command/cmd/executable→app、argv→args、
    mode→action…）、整行命令自动拆分（`app='ls -la'`）、包装层展开（`arguments={'app':...}`）、
    形态收敛（`["bash"]`→`bash`）。**宽松入口、严格出口**：语义歧义一律拒绝执行
    （`app` 与 `command` 值冲突报语义冲突，绝不猜——猜错即执行错命令）
  - 提权/自杀检测移到归一化**之后**：别名与包装层写法（`command='sudo ls'`）同样无法绕过护栏
- fix(toolkit): 上述归一化层复审修正 —— 修掉为容错畸形输入而**破坏合法输入**的 3 处回归
  - 🔴 含空格的合法可执行路径被按空白错拆：`C:/Program Files/7-Zip/7z.exe` 拆成
    `C:/Program` + 余部，端到端返回 `ok=True` 而 stdout 为空（靠 CreateProcess 前缀匹配
    侥幸成功）。**静默执行错目标，比崩溃更危险** → 仅当「整串是存在的文件」时保留原样，
    确认是「程序 + 参数」形态才允许拆分
  - `timeout=0/None/''` 原回落 120，被无脑改成 30 → 长命令（编译/下载）会被空闲监控误杀
    → 恢复旧语义（垃圾值才回落 30，两者分列）
  - `app=[[1,2]]` 嵌套容器被 `json.dumps` 成 `"[1, 2]"` 当程序名**实际执行** → 结构性元素
    改为置空保留占位（不可用作程序名）
  - `app=["echo", None, "-n"]` 旧实现过滤 None 造成参数整体左移，等价于执行另一条命令
    → 改为保留位置；另为包装层展开加深度上限防 RecursionError
- feat(toolkit): `Toolkit.call_tool` 入参绑定预检 —— 把「意外关键字 TypeError」降级为可自纠错误
  - 那类报错不是 `toolkit_exec` 独有，而是**全部 51 个工具的共性风险**（`call_tool(func, **args)`
    透传模型给的任意键）。逐个工具加 `**kwargs` 是打 51 次补丁，在唯一汇聚点修一次才是根因
  - 报错文本点名出错键 / 缺失必填参数，并列出该工具真实参数名；取不到签名时放行（宁放勿误杀）
  - 新增签名缓存并在 `reload()`/`save()` 失效：否则工具改签名后仍按旧签名校验，
    会把合法调用误判为非法（最坏的一种失败）
- fix(sdk): 修复 SDK **自引入起完全不可用**的两处必崩缺陷
  - `Request(method, url, headers=..., data=...)` 位置写反（真实签名
    `Request(url, data=None, headers={}, method=None)`）→ 每个方法都
    `TypeError: got multiple values for argument 'data'`
  - `chat()` 里 `{messages: ...}` 把键名写成裸变量 → `NameError`；叠加后**没有一个方法能跑通**
  - 附带修正：`if data` 把 `{}` 当无 body（`run_tool(..., {})` 静默丢 body）、
    `json.loads` 异常穿透让 4xx 被伪装成 500、`stream=True` 从未真正发出
    （新增 `assemble_sse()` 拼装分帧）
  - 新增 `test_sdk_client.py` 27 项：**用真实 HTTP 服务打全链路而非 mock**
    （mock 恰恰会放过参数错位；此前 1663 个测试无一触达该文件）
- fix(audit): 审计哈希链在多进程下**必然断裂** + 目录探测并发误判导致静默丢记录
  - `_chain_head` 的内存缓存永不过期：本进程写过一次后，即使其它进程又追加记录，仍拿旧哈希
    当链头 → 新记录 `prev` 跳过中间记录，append-only 防篡改链被判「记录被删除/插入/重排」。
    设备端跑 `tea_agent_api`（server + 子 Agent + 测试并发写同一日文件）正是必现场景
  - `_chain_head` 增加过期判定（文件尺寸变化）+「末行必须是合法 JSON 且含 h」校验；
    `record()` 的「读末行 → 追加」由 `<文件>.lock` 跨进程互斥（不嵌套进 `message_queue_lock`）
  - 目录探测所有进程共用同一个 `.write_probe`：并发下互相删对方文件，`FileNotFoundError`
    被 `except OSError` 当成「该目录不可写」→ 该进程**静默改写到别的候选目录**（实测 6×15
    只剩 75 条，子进程退出码全 0）。探测文件改为按 pid 唯一，且「清理失败」不再判为不可写
  - `safety-audit-chain` 基准改为校验**机制**而非生产文件历史状态（旧断言等价于断言
    「这台机器这份共享可变产物的整段历史完好」—— 并发写入即可使其失败、历史损坏则永久红），
    并新增反向断言「改一个字符必须被检出」；历史损坏改为显式标记（不删数据、不静默放行）
- fix(server): `turn_snapshot` 节流不再丢事件 —— 在途回合恢复此前形同虚设
  - `record_event` 的节流分支在读写**之前**就 `return`，而状态只活在 sqlite 里 →
    0.5s 窗口内的 token 被整条丢弃（不是攒着稍后写）。实测 360 条只读回 1 条（**丢 99.7%**）；
    生产路径只在 done/error 才 `force=True`，故每个回合只有终止事件落盘 —— 模块文档写着
    节流是为了「避免每个 token 都落一次盘」、`partial_text` 是为了「重启后不让用户丢内容」，
    实现却把内容丢了
  - 改为「内存累积 + 节流落盘」：事件无 I/O 入 pending，到点/force/回合结束时才落盘；
    `_flush_locked` 与 DB 现状按 index **归并去重**（多进程写同一 topic 时覆盖式写入会让
    后落盘一方抹掉先落盘一方）；`finish_turn` 先 flush（回合尾部 token 正是用户最关心的内容）；
    `begin_turn`/`ensure_turn`/`clear` 同步重置进程内缓存，否则旧 pending 跨回合成串
  - `test_throttle_skips_rapid_writes` 原断言 `events == [0, 2]`，即**把「事件被永久丢弃」
    固化为契约**（这正是该缺陷未被发现的原因）→ 重写为 `test_throttle_saves_io_but_keeps_every_event`
    并新增 `test_tail_tokens_survive_throttle`
- fix(server): 队列落盘加版本守卫 —— 已撤回插话被旧快照复活到磁盘
  - `_persist_queues` 是「锁内取快照、锁外写文件」，两个并发落盘的**完成顺序可能与快照顺序
    相反**：A 取到含该消息的快照，B 删除并落盘完成，A 才写 → 已删除的消息写回磁盘。
    内存干净、只有磁盘错，重启后用户早已撤回的消息死灰复燃
  - 队列每次变更在持锁下递增 `_queue_version`；落盘带上快照版本，不比已落盘更新则跳过写入
  - 新增 `test_state_queue_persist.py` 6 项，并已做**元验证**：把守卫还原成旧实现后同一场景
    确实复活消息（`{}` → `{'t1': [...]}`），证明该回归不是空跑
- fix(web): 前端 Markdown 列表渲染出幽灵条目 —— 「两条数据，三个序号」
  - 根因：`formatMarkdown` 用单条正则识别列表，而正则里的 `\s` **匹配换行**；列表前的空行
    （标题/段落与列表之间的标准写法）被吞进匹配串，匹配串因此以 `\n` 开头，
    `match.split('\n')` 后首元素是空串却仍被包成 `<li>` → 凭空多出一个空条目，
    且 `<ol>` 自动编号整体后移：源码 `1./2.` 显示成 `2./3.`。实测真实会话
    （`## 两点观察` + 两条目）渲染出 3 个序号，第 1 个为空
  - 改为逐行扫描：标记匹配限定 `[ \t]`（不跨行）、空行只作列表分隔（松散列表不再插入
    空条目）、裸编号行（`1.` 后无内容）不再吞掉下一行；并保留源起编号
    （`2.` 起 → `<ol start="2">`），显示序号不再被 `<ol>` 重排
  - 同类缺陷一并修掉引用块 `^&gt;\s`：`\s` 会把引用行与下一行并成一条引用
  - 新增 `test_web_markdown_lists.py` 14 项（node 执行真实 `formatMarkdown`，钉
    「条目数守恒 / 无空条目 / 源序号不被改写」三条契约）；已做**元验证**：
    还原旧实现后同一组用例 11/14 变红
  - `index.html` 的 app.js 缓存串同步更新（`?v=20260917_md_list_fix`）
- fix(vision): 多模态数组 content 被端点拒绝的 400 → 当轮自愈（整轮硬失败降级为丢图有答案）
  - 现象（生产日志）：`model=deepseek-flash, iteration=1, BadRequestError: 400 -
    Failed to deserialize the JSON body into the target type: messages[175]:
    invalid type: sequence, expected a string` —— 整轮对话直接失败，不是降级
  - 该 400 的含义是"某条消息里出现了本该是字符串的数组"；`to_multimodal` 是唯一会产出
    数组的路径，故与既有 `"image input"` 合成一条自愈分支：新增
    `_is_multimodal_content_rejected` 识别签名 → 本会话关 vision → 重建消息
    （数组拼回纯文本、图片跳过）→ 重试一次；严格只认"序列当字符串用"签名，溢出 / RC
    回传 / 工具参数类 400 一概不受影响（宁可报错，不可静默丢图能力）
  - **明确不做**端点级永久降级：实测 `deepseek-flash` 官方端点**接受**
    `content: [{type:text},{type:image_url}]`（HTTP 200，prompt_tokens 221 vs 纯文本 35，
    图片 token 正常计入）。因此不能由一次 400 推断"端点不支持视觉"而把该端点的图片永久
    关掉 —— 该反向契约由 `test_next_session_still_sends_multimodal` 钉住
  - 新增 `_log_content_type_diagnostic` 现场诊断：端点只回 `messages[N]` 下标，而这下标
    指的是**我们发出去的 payload** —— 日志把它翻译成该条的 role + 字段类型清单 +
    含 image_url 的下标，下一次出现即可直接定位（本次就是卡在"只有下标、没有现场"）
  - 待办：该 400 的真实触发源尚未定位（用真实加载路径重建该话题历史只有 94 条消息 /
    96 KB 且全部为字符串，而报错请求是 175 条 / 448 KB，体量对不上），需要现场 payload
    才能收口；诊断日志已就位
  - tests: 新增 `test_multimodal_content_400_recovery.py` 18 项（分类器正负样本、
    现场诊断（下标解析 / 越界 / 干净 payload 如实记录 / 不抛异常）、当轮自愈、
    非多模态 400 不得误降级、未声明 vision 时不自愈、不永久降级反向契约）

### Documentation
- docs(readme): 同步 v0.16.x 近期变更 —— 版本号 0.16.6；工具数口径改为 56 个工具模块 /
  60 个注册工具（58 个对模型可见），删除已移除的 `toolkit_ocr` 引用；新增「工具暴露自缩减」
  小节（统计点、三条不变式、逃生阀）与「服务韧性」小节（无感重启 + 在途回合快照续读 +
  生成中插话 steering）；自进化章节补快照独立 ref（`refs/tea/snapshots`，回滚改为按快照恢复
  目标文件）与 EvolutionBench 进化闸门；Mini 重型工具 12→11；项目结构补 `tool_shield.py` /
  `evolution_gate.py` / `evaluation/` 并修正 providers 与 store 口径；测试口径 870+→1800+；
  新增「安全边界」小节；中英文 README 保持对等
- docs(agents): 同步 AGENTS.md 到当前实现 —— 项目结构实测（40 顶层模块 + 15 子包、56 个
  `toolkit_*.py` → 60 注册 / 58 可见、store 13 功能子模块、95 测试文件）并补齐缺失模块
  （`tool_approval` / `tool_hooks` / `tool_profiles` / `evolution_gate` / `storage_scope` /
  `audit_log` / `evaluation` / `sdk`）；关键约束补「下划线模块不注册」「工具列表顺序稳定性」
  「存储作用域」；工具规范补入参绑定预检与 `toolkit_exec` 归一化层、读路径无写副作用、
  fail-open；自进化章节更新为快照独立 ref（`refs/tea/snapshots`）与按目标文件回滚，新增
  进化闸门三档模式；新增「环境变量与开关」总表（22 项）与「文档同步规范」；提交规范补
  合并到 master 的 ff-only 流程与「推送是远端副作用」约定；安全注意事项改为按真实现状
  陈述（`permission.py` 已禁用、真实闸门为 `tool_approval`、提权硬拒绝、SQL 校验助手、
  审计 hash 链）

### Dependencies
- 移除零使用依赖 `numpy`（核心依赖 → `[demo]` extra）
  - **依据**：核心包（`tea_agent/` 非 `demo/` 部分）**零 numpy 使用**，实测 8 处
    import 全部落在 `tea_agent/demo/`（3 个顶层 + 4 个函数内惰性）或包外
    `asr_vad.py`（仓库根目录，不属于本包）。向量检索下线后 numpy 已无核心消费者
  - **验证**：`build_mini.py` 实测 wheel 内 `numpy imports = 0`（"No numpy - good!"），
    Mini 构建不受影响
  - 同步清理 `toolkit_pkg._list_installed` 的 `key_pkgs` 中陈旧 `numpy` 条目
    （该表仅用于 `action=list` 诊断展示，非依赖声明）
  - `asr_vad.py` docstring 补注：该脚本在包外，需自行 `pip install numpy onnxruntime`
  - tests: 新增 3 项守卫 —— numpy 不在核心依赖 / 必须在 demo extra /
    **核心包不得出现 numpy import**（后者是「可安全移除」的不变式，
    将来有人往核心包塞 numpy 会立刻变红）。元验证：3 项变异各自变红

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


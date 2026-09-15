# Changelog


## [Unreleased]
### Features
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


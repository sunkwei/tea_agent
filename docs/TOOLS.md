# sunkw 工具清单

注册工具总数: 72

| 工具 | 说明 |
|------|------|
| `toolkit_auto_pipeline` | 【突破性创新】自动工具管线编排器（工具共生网络）。自动分析任务需求，动态构建最优工具执行链，实现「任务→工具链→执行→学习」闭环。不是单一工具，而是编排工具的元 |
| `toolkit_batch_process` | 批量文件处理工具。对多个文件并行执行相同的操作（编译检查/lint/格式化/统计/替换等），支持 glob 匹配、并行执行、失败隔离。 |
| `toolkit_browser_tab` | 浏览器标签管理工具。可以激活指定浏览器窗口、切换到指定标签页、获取标签列表。支持 Firefox、Chrome 等主流浏览器。 |
| `toolkit_build` | 统一构建工具。action='package' 构建Python包（python -m build），自动处理build目录冲突；action='fix' 修复 |
| `toolkit_categorize_tools` | 工具分类组织 — 将 75+ 工具按场景类别分组管理。支持 list(列出分类)、recommend(按任务推荐工具)、compact(精简列表)。借鉴 ope |
| `toolkit_clipboard` | 剪贴板处理工具 — 感知 + 智能路由。读取当前剪贴板内容，自动检测类型（代码/错误/URL/JSON/日志/文本），返回类型判断 + 处理建议。支持后台监听模 |
| `toolkit_code_review` | 自动代码审查工具。综合检查编译错误、Lint、安全漏洞、代码复杂度、风格问题，生成结构化审查报告。支持单文件或整个目录批量审查。 |
| `toolkit_config` | 读取或修改 Agent 运行时配置。Agent 可以自主调优自己的参数（如 max_iterations、keep_turns 等）。修改会自动记录历史。 |
| `toolkit_custom_commands` | Custom Commands 系统 v3.0 — 借鉴 OpenCode + Pi-style 的可复用命令模板。支持 add/list/show/run/d |
| `toolkit_diff` | Diff-first 代码编辑引擎。generate/preview/apply/undo/verify。 |
| `toolkit_diff_edit` | Diff-first 单文件编辑工具。接受 file_path/old_text/new_text，自动生成 unified diff 预览后应用。相比 too |
| `toolkit_dump_topic` | 将会话内容从数据库导出到 dump_{date} 子目录，每个 topic 对应一个 markdown 文件。支持导出全部或指定 topic。 |
| `toolkit_edit` | 高级代码编辑工具。推荐 replace_text（文本匹配）免疫行号漂移。 |
| `toolkit_eval_loop` | 确定性 Rubric 评分闭环（借鉴 PenguinHarness self-evolve）。score=单文本按规则打分; evaluate=多轮结果取平均( |
| `toolkit_evolution_exp` | 进化经验库管理。记录/查询 Agent 的自主进化经验。action=list/record/search |
| `toolkit_exec` | 执行系统命令。action='single' 执行单条；action='batch' 并行批量执行多条。执行 sudo 命令时自动弹出 GUI 密码框。智能超时 |
| `toolkit_experience_solidify` | 经验固化。成功→技能库，失败→教训库。action=analyze/solidify/lesson/auto |
| `toolkit_explr` | 项目知识库构建与查询。action=build 构建符号索引+AST调用图+流程图+kb.md；action=generate_docs 生成结构化项目文档到d |
| `toolkit_export_last_pdf` | 导出指定主题的对话为 PDF。支持选择完整主题/最新对话，仅含 user+AI 最终消息（无思考过程）。 |
| `toolkit_file` | 统一文件读写与目录列表。action='read' 读取文件；action='write' 写入文件；action='list' 列出目录 (跨平台 dir/l |
| `toolkit_format_code` | 代码格式化工具。支持 Python (black) 和 C/C++ (clang-format) 格式化。 功能： - 格式化单个文件或目录 - 检查格式是否符 |
| `toolkit_get_config_path` | 获取当前 Agent 正在使用的配置文件路径。读取 tea_agent.config._last_config_path 模块变量。 |
| `toolkit_get_models` | 获取当前配置的所有模型信息（主模型、摘要模型、嵌入模型）。无需参数。 |
| `toolkit_git_branch_manager` | Git 自动分支管理工具 — 借鉴 opencode/codex 的会话即分支模式。自动创建/切换/合并/清理功能分支，每次任务对应一个分支。 |
| `toolkit_git_commit` | Git commit — 固定 author: tea_agent <sunkwei@gmail.com>，不受全局 git 配置影响。支持 add/commi |
| `toolkit_git_push_all_remotes` | 向当前 git repo 配置的所有远程仓库推送当前分支。 |
| `toolkit_harness_schema` | Harness JSON Schema — Tea Agent 机器可读能力清单。生成符合标准格式的能力描述，含 Agent 信息、15+ 能力矩阵、工具列表、 |
| `toolkit_input` | 模拟鼠标和键盘操作 — Agent 的'手'。可移动鼠标、点击、拖拽、滚动、输入文本、按快捷键。配合 toolkit_screenshot 可实现「看→分析→操 |
| `toolkit_ip_geo` | Unified IP geolocation tool: my_ip=get public IP, my_location=get geolocation, l |
| `toolkit_js_fetch` | 用 Playwright 无头浏览器抓取 JS 动态渲染的页面内容。跨平台自动选浏览器(Windows→Edge/Linux→Chromium→Firefox) |
| `toolkit_kb` | Markdown 知识库管理。文档存储在 $HOME/.tea_agent/kb/，所有主题共享。支持 add/update/read/list/search/ |
| `toolkit_list_provider_models` | 根据当前配置文件查询指定 API 提供商的可用模型列表。支持按配置文件中的模型名（main_model/cheap_model/embedding_model） |
| `toolkit_list_versions` | 列出工具的所有可用版本。用于查看工具的历史版本。 |
| `toolkit_lsp` | 实时代码智能: diagnose/completion/definition/hover/references/context。基于 jedi + ruff。 |
| `toolkit_lunar` | 公历农历转换工具。输入公历日期返回农历（天干地支、生肖）。也支持农历→公历反查。零外部依赖，覆盖 1900-2100 年。 |
| `toolkit_mcp` | MCP (Model Context Protocol) 客户端工具，用于连接外部 MCP Server 并使用第三方工具。支持 stdio 和 SSE 传输方 |
| `toolkit_memory` | 统一长期记忆管理。action: add/list/search/forget/extract/auto_extract/semantic_search/sta |
| `toolkit_mode` | Agent 工作阶段模式管理。6 个 phase：design=架构设计(不写代码)/develop=代码开发/test=测试调试/review=代码审查/do |
| `toolkit_notify` | 发送桌面系统通知。支持 Linux（GI Notify/notify-send）、macOS（osascript）、Windows（PowerShell Toa |
| `toolkit_ocr` | OCR 文字识别工具。支持图片文件、截图、base64 图片作为输入，返回识别的文字。Windows 使用内置 OCR API，Linux/macOS 使用 T |
| `toolkit_parallel_subtasks` | 分治并发执行器：将复杂问题分解为子任务，简单任务用 lite agent 并发执行，复杂任务由主 agent 执行，最后整合结果。 适用场景： - 多文件代码分 |
| `toolkit_pkg` | 智能 Python 包管理工具。list=列出关键依赖状态, check=检查单个模块, install=安装包(支持别名如pil→Pillow), ensur |
| `toolkit_plan` | Plandex 风格 Plan→Execute→Verify 三步工作流。create=创建计划, decompose=智能分解目标, show=查看, rev |
| `toolkit_proactive` | 自主心跳：Agent 的自我目标管理系统。action=check/goal/done/list_goals。 |
| `toolkit_prompt_evolve` | 管理系统提示词的多版本进化。evolve=基于反思自动优化提示词, rollback=回滚到历史版本, list=查看版本历史。Agent 可以自主改进自己的核 |
| `toolkit_query_chat_history` | 查询 chat_history.db 中的 conversations 表。action=schema查看表结构, query按UUID查记录, topic按t |
| `toolkit_question` | 执行过程中向用户提问。支持选项列表和自定义输入。 使用场景： - 收集用户偏好或需求 - 澄清模糊的指令 - 获取实现方案的决策 - 提供方向选择的选项 返回： |
| `toolkit_reflection` | 元认知反思工具。trigger=触发自我分析反思，list=查看最近反思，stats=查看统计。Agent 可在任务完成后用此工具反思自己的表现。 |
| `toolkit_release_version` | 自动化版本发布工具。更新版本号、CHANGELOG，并构建项目。 |
| `toolkit_reload` | 重新加载所有工具函数，并注册为全局可用的方法，所有方法使用 toolkit_ 为前缀 |
| `toolkit_remote_agent` | 远程设备Agent控制工具。与终端设备(BM1688/RK3588/X3等)上的tea_agent.server通信，向设备AI发送任务，获取AI的最终回答。主 |
| `toolkit_rollback` | 回滚工具到指定版本。用于撤销有问题的工具更新。 |
| `toolkit_run_tests` | 运行项目测试文件（默认 test_*.py），返回通过/失败统计和每项详情。 |
| `toolkit_save` | 存储工具函数，以便以后使用该工具函数，使用 toolkit_reload() 重新加载 |
| `toolkit_save_file` | Write files with automatic chunking for large content. Use 'chunks' (list of str |
| `toolkit_scheduler` | 定时任务管理器 — 增删改查定时任务、启动停止调度线程、测试调度表达式。schedule 格式: once:ISO单次 / daily:HH:MM每天 / ho |
| `toolkit_screen_read` | 屏幕内容读取工具 - 截图 + OCR 一体化。支持浏览器标签内容读取、屏幕区域读取、当前窗口读取。通过系统截图方式（非浏览器CDP），适合本地桌面场景。 |
| `toolkit_screenshot` | 跨平台智能截屏工具。自动检测 Wayland/X11/macOS/Windows 并选择最佳截屏方式。Wayland 下自动使用系统自带工具（spectacle |
| `toolkit_screenshot_picker` | 系统级交互式截图选区 — 全屏显示截图，用户拖拽选择区域后返回裁剪图片路径。绕过浏览器坐标限制。 |
| `toolkit_search` | 搜索工具，支持互联网搜索（DuckDuckGo/百度/GitHub）和项目内代码搜索（全文搜索/符号搜索）。GitHub 搜索支持仓库、代码、Issues 搜索 |
| `toolkit_self_evolve` | 五层安全自进化：修改项目源文件，不再添加 NOTE 注释。Layer0=git快照, Layer1=时间戳.bak, Layer2=编译验证, Layer2.5 |
| `toolkit_self_report` | 生成当前 Agent 的状态报告，包括工具数量。 |
| `toolkit_send_email` | 通过 SMTP 发送电子邮件。支持纯文本/HTML、附件、多收件人。默认使用 Gmail SMTP (smtp.gmail.com:587 TLS)。密码优先从 |
| `toolkit_set_topic_title` | 手动设置当前主题的标题。设置后标题显示为「※自定义标题」，该主题将不再自动生成摘要。 |
| `toolkit_subagent` | 多Agent生成系统 v2.2。支持同步/异步生成子Agent、并发执行、状态查询、结果收集、上下文注入、嵌套深度限制、Agent间通信。 |
| `toolkit_subagent_msg` | 子Agent消息通信。支持Agent间发送/接收/检查消息。 |
| `toolkit_sudo_gui` | 跨平台提权执行命令。Linux弹出GUI密码框（显示完整命令）+sudo，Windows弹出UAC对话框。自动检测OS。sudo 命令可直接用 toolkit_ |
| `toolkit_task_resume` | 检查当前主题未完成的 TODO 和 Plan，扫描 docs/ 产物并进行交叉对照（孤儿文档/未落实步骤/待落盘步骤），返回恢复提示。对话开始时自动调用。 |
| `toolkit_todo` | TODO checklist: create before modifying code, check off step by step. Persisted  |
| `toolkit_toggle_reasoning` | 切换或查询推理（thinking/reasoning）状态。不传参数则返回当前状态；传入 True/False 则开启/关闭。 |
| `toolkit_topic_prompt` | 管理当前主题的自定义系统提示词（system prompt）。可获取/设置/清除/查看状态。设置后该主题的后续对话将使用自定义提示词，清除后恢复使用全局进化版本 |
| `toolkit_weather_my` | 查询当前所在地的天气。先通过IP定位获取经纬度，再用Open-Meteo免费API获取7天天气预报。返回含当前时间、时区、每日预报。 |
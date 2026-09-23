# Tea Agent — AGENTS 指令

> 自进化 AI Agent · 动态工具管理 · 可扩展运行时

## 项目定位

Tea Agent 是一个 **自进化的 AI Agent 框架**。核心能力：

- **动态工具管理**：Agent 可通过 `toolkit_save` 运行时创建新工具，调用 `toolkit_reload` 立即生效
- **多会话模式**：轻量级 (LiteSession)、完整 (OnlineToolSession)、子 Agent (Sub-agent)
- **多层自进化**：工具使用分析 → 技能固化 → 系统提示词进化 → 后台线程自动优化；改动是否保留由**进化闸门**（EvolutionBench）裁决
- **按需上下文**：上下文片段 (`context_fragments`) + 分层 AGENTS.md 指令 + skill 按需加载；动态内容一律注入消息**尾部**，保护 LLM 前缀缓存
- **可收缩工具面**：使用统计（`tool_usage`）驱动的 `tool_shield` 自动屏蔽长期闲置工具
- **多样交互界面**：Web/API 服务器、ACP/Telegram/微信 适配器

## 快速命令

```bash
# ── 安装 ──
pip install -e .                    # 可编辑安装

# ── 构建 ──
python -m build                      # 构建分发包
python build_mini.py                # 构建 Mini 版（输出 tea_agent_mini / build_mini_dist）
python build_nuitka.py              # 编译单文件可执行（无需 Python 环境）

# ── 运行 ──
tea_agent                            # 启动 Web/API 服务器（默认入口，等价 tea-agent-api）
tea_agent_api                        # 启动 API 服务器（下划线别名，等价 tea-agent-api）
tea-agent-api                        # 启动 API 服务器
tea-agent-mini                       # 启动 Mini 版
tea-agent-acp                        # 启动 ACP 协议
tea-agent-telegram                   # Telegram 适配器
tea-agent-wechat                     # 微信适配器

# ── 测试 ──
pytest                               # 运行全部测试（105 个测试文件，截至 2026-09-23）
pytest tea_agent/tests/test_xxx.py   # 运行单文件测试
pytest -k "test_name" -xvs           # 按名匹配+详细输出
pytest --collect-only -q             # 只收集用例（确认总数与新增文件已被发现）

# ── 静态检查 ──
ruff check .                         # Lint 检查
ruff format . --check                # 格式检查
ruff format .                        # 自动格式化
black .                              # 备选格式化

# ── 类型检查 ──
python -m mypy tea_agent --ignore-missing-imports

# ── 口径核查（文档同步用，勿凭记忆填数）──
python -c "from tea_agent.tlk import Toolkit, llm_tool_names; t=Toolkit(); print(len(t.func_map), len(llm_tool_names(t.func_map)))"
python -c "import pathlib; print(len(list(pathlib.Path('tea_agent/toolkit').glob('toolkit_*.py'))))"
```

## 项目结构

```
tea_agent/                          # 40 个顶层模块 + 14 个子包（截至 2026-09-23 实测）
├── agent.py                        # 统一 Agent 类（三种模式入口）+ 后台线程投递
├── agent_pipeline.py / session_pipeline.py   # 后处理流水线（摘要/记忆提取/任务评估）
├── agent_background.py             # 后台线程：定时任务调度 + 打断模式分析（M3/M4）
├── agent_evolution.py              # 自进化闭环（触发 → 分析 → 执行）
├── onlinesession.py                # OnlineToolSession — 完整在线会话
├── litesession.py                  # LiteSession — 轻量会话（子 Agent 用）
├── basesession.py                  # 会话基类 + 容错 JSON 解析
├── config.py                       # 配置加载与管理
├── context_fragments.py            # ★ 上下文片段系统（Codex 风格：时间/预算/模式按需组装）
├── agents_md_loader.py             # ★ AGENTS.md 分层指令加载（用户级+项目级+字节预算）
├── skill_loader.py                 # ★ Skill 按需加载评估器（必要性/充分性双维，取代知识结晶）
├── tool_shield.py                  # ★ 长期未使用工具自动屏蔽（读 tool_usage 统计）
├── tool_profiles.py                # 工具窗口档位（按上下文窗口裁剪暴露面）
├── tool_approval.py                # ★ 风险分级 + 审批闸门 + 审计接线（A2/A3 安全底座）
├── tool_hooks.py                   # pre/post 工具 hook（approval/audit 以此挂载）
├── evolution_gate.py               # ★ 进化闸门（EvolutionBench keep-or-rollback）
├── storage_scope.py                # 存储作用域：项目级 .tea_agent_run/chat_history.db → 临时目录回退
├── session_fork.py                 # ★ 会话分叉共享实现（Web `#分叉` 与 toolkit_fork_session 同一事实源）
├── path_filters.py                 # ★ 项目树遍历排除集（唯一事实源：PRUNE_DIRS/prune_dirs/iter_files）
├── audit_log.py                    # 审计日志（hash 链防篡改）
├── memory.py / project_memory.py / cross_topic_summarizer.py   # 记忆与跨主题汇总
├── prompt_manager.py               # 系统提示词管理
├── reflection.py                   # 元认知反思
├── providers.py / provider_store.py / model_config.py / model_manager.py  # LLM 提供方与模型属性
├── api_headers.py / api_retry.py   # 供应商 header 注入 / 重试
├── permission.py                   # 工具权限管理（已禁用，恒放行；真实闸门见 tool_approval）
├── tlk.py                          # ★ 工具加载/注册/执行引擎（call_tool 为唯一汇聚点）
│
├── toolkit/                        # ★ 工具注册中心：toolkit_*.py 共 55 个 → 注册 64 个工具（62 个对模型可见）
│   ├── __init__.py                 # 空文件（无手工注册；工具由 tlk.py 扫描加载）
│   ├── toolkit_exec.py / toolkit_file.py / toolkit_edit.py / toolkit_diff.py
│   ├── _git_snapshot.py            # 下划线前缀 → 不注册为工具（快照基础设施）
│   └── ... (55 个 toolkit_*.py)
│
├── session/                        # 会话组装（历史压缩 / L1·L2·L3 / JSON 校验 / os 信息注入 / 解码速率）
├── store/                          # 存储层（13 个功能子模块 + migration）
├── server/                         # REST API + Web V2（Starlette + SSE，含 turn_snapshot）
├── multi_agent/                    # 多 Agent 协作
├── workflow/                       # 工作流引擎（DAG）
├── protocol/                       # ACP 协议实现
├── channel/                        # Telegram / 微信适配器
├── lsp/                            # 代码智能（Jedi + Ruff）
├── skills/                         # 技能系统
├── evaluation/                     # 评测（EvolutionBench 等）
├── sdk/                            # 对外 SDK
├── demo/                           # 演示应用（辩论赛 / 钢琴 / DAG）
│
└── tests/                          # 105 个测试文件（大模块必须有对应 test_ 文件）
```

> 注：`tea_agent_mini/` 是仓库根下的独立顶层子包（见「Mini 构建」），不在 `tea_agent/` 目录内。

## 架构边界

### 三层会话模型

```
┌─────────────────────────────────────────┐
│  Agent (统一入口)                        │
│  ├─ mode='full'     → OnlineToolSession │  ← 完整能力：存储、后台、摘要
│  ├─ mode='lite'     → LiteSession       │  ← 轻量：单轮、廉价模型、无状态
│  └─ mode='lightweight' → OnlineToolSession │  ← 极简：仅关闭存储/后台，无独立会话类
├─────────────────────────────────────────┤
│  Sub-agent 系统                          │
│  ├─ spawn/spawn_sync → 独立 LiteSession │  ← 隔离上下文、独立迭代
│  ├─ subagent_msg     → 消息传递          │  ← Agent 间通信
│  └─ collect/cancel   → 结果收集          │
└─────────────────────────────────────────┘
```

### 关键约束

1. **不得循环导入**：`agent.py` 不反向导入任何子模块；子模块只导入 `agent.py` 或同级模块
2. **工具注册**：新工具必须放在 `tea_agent/toolkit/` 目录，以 `toolkit_` 前缀命名，通过 `toolkit_save` 注册（实际由 `tlk.py` 按 `toolkit_*.py` 扫描+exec 加载；`__init__.py` 为空文件，无需手工导入）
3. **下划线前缀不注册**：`toolkit/_xxx.py` 形式的模块不会被扫描注册（如 `_git_snapshot.py`），适合放共享基础设施
4. **自进化边界**：后台自进化线程可优化工具代码、整理技能、调整提示词，但**不得修改用户对话历史**
5. **工具列表顺序稳定**：工具列表顺序是 DeepSeek 前缀缓存的一部分 —— 任何收缩/筛选（`tool_shield` / `tool_profiles`）必须产出**确定性排序**，集合抖动会让每轮缓存 100% 失效
6. **存储作用域**：默认 db 为**启动目录** `$pwd/.tea_agent_run/chat_history.db`（`TEA_STORAGE_SCOPE=auto/project`）；
   启动目录不可写（无权限 / 无磁盘空间）→ 回退**系统临时目录**并在每轮会话结束提示用户手动备份；
   启动目录 == 用户主目录 → `~/.tea_agent/chat_history.db`；显式 `user` → 用户级（durable）。
   **db 名固定 `chat_history.db`，不做改名迁移**（旧库本就叫这名，原地沿用）。
   新增持久化数据时须走 `storage_scope.resolve_db_path`，不要硬编码路径
   （**临时回退是唯一会丢数据的情形**，故 `storage_notice()` 必须保持接线，且提示只能经
   `callback` 送达 UI —— 并入 `full_reply` 会被持久化进对话历史，见 `_finalize_turn_reply`）

## 工具系统规范

### 工具命名
```
toolkit_<动作描述>.py       # 文件命名
内部函数: toolkit_<动作>()  # 注册工具名
```
示例：`toolkit_exec.py` → `toolkit_exec()`, `toolkit_save.py` → `toolkit_save()`

### 工具注册方式

```python
# 方式一：直接导入注册（推荐）
from tea_agent.toolkit.toolkit_xxx import toolkit_xxx

# 方式二：运行时动态创建
toolkit_save(name="toolkit_new_tool", meta={...}, pycode="...")
toolkit_reload()
```

> 文档/统计口径中写「工具数」时必须区分三个数：**模块数**（`toolkit_*.py` 文件数）、
> **注册数**（`Toolkit().func_map` 长度）、**可见数**（`llm_tool_names()` 长度，扣除
> `LLM_TOOL_EXCLUDES` 里的内部工具）。三者不同，混用即错。

### 工具调用入参容错

`Toolkit.call_tool` 是唯一执行汇聚点，两条硬规则：

1. **入参绑定预检**：意外关键字导致的 `TypeError` 降级为可自纠的结构化错误，而不是抛崩
2. **`toolkit_exec` 归一化层**：接受 `command`/`cmd`/`executable`/整行命令/`arguments` 包装等
   多种写法；新增归一化分支时必须补测试，历史上有 3 处真实回归由位置漂移引入

### 工具暴露与使用统计

工具调用统计落在**项目 db**（`$pwd/.tea_agent_run/` 的会话库）`tool_usage` 表，
记录点在 `Toolkit.call_tool`（唯一汇聚点，覆盖缓存/非缓存两条路径），且位于**缓存判定之前** ——
命中缓存同样是真实调用，记在缓存之后就少算，长期会把常用工具误判成「没用过」而屏蔽。
`tool_shield` 据此在构建工具列表时屏蔽长期未使用者，与 `tool_profiles` 的窗口
档位是两层独立收缩。

三条不可妥协的不变式（屏蔽会让 Agent 失去能力）：

1. **无数据 = 不屏蔽** —— 空表只代表"尚未观测"，否则新装机首次启动即屏蔽全部工具
2. **观测期未满不屏蔽零使用工具** —— 判"长期不用"必须先有"长期"
3. **自愈通路永不屏蔽** —— `toolkit_config/save/reload/exec/file/edit/diff/
   approve/tool_usage/rollback/list_versions` 屏蔽后 Agent 将无法解除屏蔽

应急：`TEA_TOOL_SHIELD=0` 关闭自动屏蔽；`TEA_TOOL_SHIELD_IDLE_DAYS=N` 调阈值；
单个工具用 `toolkit_tool_usage(action='pin'|'unpin'|'auto', tool=...)` 覆盖。
判定函数 `evaluate()` 必须是纯函数（时间分支可在秒级单测覆盖，不靠等 30 天）。

### 工具开发原则

- **纯 Python**：不依赖外部非标准可执行文件
- **明确输入输出**：参数使用 JSON Schema 定义，返回结构化结果
- **通用可复用**：不写死路径/Key，通过参数注入
- **失败隔离**：`batch_process` 等并行工具需单个失败不影响整体
- **幂等性优先**：重复调用不产生副作用
- **读路径无写副作用**：只读查询（如工具屏蔽判定）用 `peek_storage()`，不要用会在裸进程里隐式建库的 `get_storage()`
- **辅助能力不绑架主流程**：统计/审计/快照一类旁路写入失败一律静默降级（fail-open），绝不把主调用带崩
- **旁路代码不得改写控制流**：若观测调用点落在「异常=重试/降级」的 `try` 内，则连**属性查找**
  都不能在该 `try` 里发生（`self._new_hook()` 对鸭子类型替身即抛 `AttributeError` → 被误判为
  业务异常触发重试）。取时/取名一律放 `try` 外，或包成不可能抛错的局部闭包

### 文档创建规范（下载链接）

当用户**明确要求创建文档**（接口文档、README、Markdown、设计文档等）时：

1. 用 `toolkit_file`（action='write'）保存文档到项目内合适路径（如 `docs/`）
2. 调用 `toolkit_publish_doc(source_path=..., title=...)` 发布
3. **final msg 必须包含 Markdown 下载链接**（toolkit_publish_doc 返回的 url）：
   ```
   📄 文档已生成：
   [下载接口文档](/v1/download/接口文档.md)
   ```

规则：链接必须是可点击的 Markdown 格式；若无 server 则给出本地路径。

## 代码风格

### Python 规范

- **Python 3.10+**（`requires-python >= 3.10`）：使用 `dict | None` 联合类型、`match/case`、`dataclass`
- **命名**：`snake_case` 函数/变量，`PascalCase` 类，`UPPER_CASE` 常量
- **类型注解**：所有函数签名必须含类型注解
- **文档字符串**：公共函数/类须有 docstring（Google 风格），内部函数可选
- **行宽**：120 字符（ruff 配置）
- **导入顺序**：标准库 → 第三方 → 本地，每组空行分隔
- **避免**：全局可变状态、循环导入、`except: pass`

### 测试规范

- 测试文件：`tea_agent/tests/test_*.py`（105 个，截至 2026-09-23）
- 使用 `pytest`，fixture 集中在 `conftest.py`
- 测试函数名：`test_<功能>_<场景>`
- 重要模块须有 `test_` 文件覆盖；修复缺陷必须**带回归测试**，且回归测试要能真的失败（必要时做元验证：把实现还原成旧版，确认测试确实变红）
- 覆盖「静默失效」类缺陷时，断言要钉住**行为契约**而非当前实现细节 —— 历史上曾有测试把「事件被永久丢弃」固化成契约，导致缺陷长期未被发现
- 时间/随机/环境相关逻辑抽成纯函数或可注入参数，保证判定确定性
- 不要在新代码里写死用例总数（会随提交过期）；需要数字时用 `pytest --collect-only -q` 实测，并标注「截至」时点

## 自进化规则

### 六层安全护栏（toolkit_self_evolve）

| 层级 | 保护 | 描述 |
|------|------|------|
| L0 | git 快照 | 仅在工作区干净时自动创建；落点 `refs/tea/snapshots`（side ref），**不污染分支历史** |
| L1 | 时间戳 .bak | 每次修改备份，不覆盖历史 |
| L1.5 | 语法严格检查 | ast.parse 严格语法校验 |
| L2 | 编译验证 | 修改后 `compile()` 检查语法 |
| L2.5 | LSP 检查 | 影响分析 + lint + 签名对比 |
| L3 | 测试回滚 | 测试失败按快照恢复**目标文件**（不再 `git reset --hard` 波及整个工作区） |

> 快照相关环境变量：`TEA_GIT_SNAPSHOT_MODE=side|branch|off`（默认 side）、
> `TEA_SNAPSHOT_REF`（默认 `refs/tea/snapshots`）。查看/恢复：
> `git log refs/tea/snapshots --oneline` / `git checkout refs/tea/snapshots -- <file>`。
> 所有文件修改工具（edit/diff/file 等）成功后都会自动留快照，工作区与暂存区不受影响。

### 进化闸门（EvolutionBench）

「编译过 + 测试过」回答不了「这版是否真的更好」。`evolution_gate.py` 在自进化
成功后跑确定性基准（纯代码 check，无 LLM）并写入进化曲线，与上一数据点比较给出
keep / rollback：

| 模式 | 行为 |
|------|------|
| `off` | 完全关闭（零开销） |
| `advisory` | 跑基准 + 记录曲线 + 附加建议（默认，不改变任何文件） |
| `enforce` | 决策为 rollback 时，自动从 `.bak.<ts>` 恢复该文件 |

开关：`TEA_EVOLVE_GATE` / `TEA_EVOLVE_GATE_THRESHOLD`（默认 0.0，即必须严格提升才算 keep）
或 `config.yaml` 的 `evolution.gate` / `evolution.gate_threshold`；
Agent 侧可调用 `toolkit_evo_bench(action='run'|'history'|'compare')`。

### 可修改 vs 不可修改

| ✅ 可修改 | ❌ 不可修改 |
|-----------|-------------|
| `toolkit/*.py` — 工具代码 | `.chat_history_protected` — 对话历史 |
| `config.yaml` — 配置 | `chat_history.db` — 数据库（启动目录 `.tea_agent_run/`） |
| `prompt_manager.py` — 提示词 | 用户 `~/.tea_agent/` 个人配置 |
| 自进化生成的 `skills/` | 版本发布后的 CHANGELOG 只追加不修改 |

## 提交规范

### 提交命令（固定 author）

所有 git commit 通过 `toolkit_exec` 执行，并用 `-c` 注入固定 author（不受全局/本地 git 配置影响）：

```bash
git add <files>
git -c user.name=tea_agent -c user.email=sunkwei@gmail.com commit -m "类型: 简短描述"
```

- `--amend` / `--no-verify` / `--allow-empty` 按需追加
- 只 add 相关文件，避免把无关改动带进提交
- 提交前先 `git status --short` 确认暂存范围；提交后用 `git show --stat` 复核

### 提交信息格式
```
<类型>: <简短描述>

<可选：详细说明>
```

类型：`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `release`

正文建议写「为什么」而非「改了什么」：根因、取舍、被否决的替代方案、已知限制。

### 合并到 master

`master` 与开发分支同步时优先 **fast-forward**，保持线性历史（避免无意义 merge commit）：

```bash
git add <files> && git commit -m "..."      # 在开发分支（如 sunkw_dev）提交
git checkout master && git merge --ff-only <dev-branch>   # 仅在可 FF 时合并
git checkout <dev-branch>                    # 回到原工作分支
```

- 非 FF（出现分叉）先停下确认，不要盲目 `--no-ff` 或制造 ``Merge branch`` 提交
- **推送是远端副作用**：`git push` 只在用户明确要求时执行；本地合并完成后必须提示
  「本地已合并、远端未推送」及对应命令
- 当前远端配置以 `git remote -v` 实测为准（AGENTS.md 里的「双远程」是历史描述，
  仓库实际可能只有 `origin`）

### 发布流程
```bash
# 使用发布工具
toolkit_release_version(
    version="x.y.z",
    changes=["说明列表"],
    build=True,
    git_commit=True
)

# 或手动
# 1. 更新 pyproject.toml version
# 2. 更新 CHANGELOG.md
# 3. 固定 author 提交: git -c user.name=tea_agent -c user.email=sunkwei@gmail.com commit -m "release: vx.y.z"
# 4. git push
```

### 分支策略
- `master` — 主分支，保持稳定
- `sunkw_dev` — 当前开发分支（日常提交落此）
- `feature/*` — 功能开发分支（可选）
- 推送至 GitHub（`origin`）+ NAS 双远程（若配置）

## Mini 构建

`tea_agent_mini/` 是独立子包，精简依赖构建。规则：

- 只包含核心会话能力（无 LSP、无重型工具）
- 通过 `build_mini.py` 脚本构建；依赖仅 7 个核心包
- 剔除范围由脚本内 `EXCLUDED_PKGS` / `EXCLUDED_TOP` / `HEAVY_TOOLS` 三个白/黑名单决定
  （`HEAVY_TOOLS` 当前 11 项：JS 渲染、截图、输入模拟、浏览器标签、剪贴板、LSP、
  `explr`、`pkg` 等），**增删工具后须同步该名单**
- 入口：`tea-agent-mini` 命令行脚本

## 环境变量与开关

| 变量 | 作用 | 取值 / 默认 |
|------|------|------------|
| `TEA_CONFIG` | 指定 config.yaml 路径 | 默认 `~/.tea_agent/config.yaml` |
| `TEA_MODEL_CONFIG` | 模型配置覆盖文件 | 绝对/相对路径 |
| `TEA_PROVIDER_FILE` | provider.yaml 路径（模型属性唯一来源） | 默认 `~/.tea_agent/provider.yaml` |
| `TEA_AGENT_HOME` | 用户级数据根目录 | 默认 `~/.tea_agent` |
| `TEA_STORAGE_SCOPE` | 存储作用域 | `auto`(默认)/`project`/`user`；auto 不可写时回退系统临时目录并提示备份 |
| `TEA_SERVER_STATE_DB` | server 状态库（回合快照/队列）路径 | 默认项目 run 目录 |
| `TEA_TOOL_SHIELD` | 关闭长期闲置工具自动屏蔽 | `0`/`false`/`no` 关闭 |
| `TEA_TOOL_SHIELD_IDLE_DAYS` | 闲置屏蔽阈值 | 默认 `30`，须为正数 |
| `TEA_APPROVAL_MODE` | 审批闸门 | `off`(默认)/`advisory`/`enforce` |
| `TEA_APPROVAL_TOKEN` | enforce 模式一次性授权令牌 | 非空即授权 |
| `TEA_EVOLVE_GATE` | 进化闸门模式 | `off`/`advisory`(默认)/`enforce` |
| `TEA_EVOLVE_GATE_THRESHOLD` | 保留阈值 | 默认 `0.0` |
| `TEA_GIT_SNAPSHOT_MODE` | 快照落点模式 | `side`(默认)/`branch`/`off` |
| `TEA_SNAPSHOT_REF` | 自定义快照 ref | 默认 `refs/tea/snapshots` |
| `TEA_FILE_ALLOW_OUTSIDE` | 放宽文件工具「禁止越出项目目录」限制 | `1`/`true`/`yes` 放宽 |
| `TEA_AUDIT_DISABLED` | 关闭审计写入 | `1`/`true`/`yes` 关闭 |
| `TEA_AUDIT_DIR` | 审计日志目录 | 默认项目 run 目录 |
| `TEA_HEADLESS` | 无人值守（`toolkit_question` 不阻塞） | `1`/`true`/`yes` |
| `TEA_AGENT_INTERFACE` | 声明运行界面（影响注入的环境描述） | `web`(默认)/`mcp` |
| `TEA_BENCH_HISTORY` | EvolutionBench 曲线文件覆盖 | 路径 |
| `TEA_AGENT_EVOLUTION_LOG` | 自进化日志路径 | 默认项目 run 目录 |
| `TEA_API_KEY` | ACP/Server 侧 API 鉴权 Key | 非空启用 |

规则：**非法值一律出声告警**（`logger.warning`），不静默回退；解析失败必须给出可读诊断。
捕获 `ValueError` 时别忘了 `OverflowError`（`TEA_TOOL_SHIELD_IDLE_DAYS=1e999` 会让
`int(float(...))` 直接抛，且发生在每次构建工具列表的热路径上）。

## 安全注意事项

1. **工具沙箱**：`permission.py` 已禁用（恒放行），真实执行闸门是 `tool_approval.py`
   （风险分级 + 审批 + 审计），通过 `tool_hooks` 以 pre/post hook 挂载，覆盖 lite 与 online 两条路径
2. **审批闸门**：`TEA_APPROVAL_MODE=enforce` 时高风险工具**缺失审批即拒绝**；授权来源为
   环境变量 / `.tea_agent_run/approval_token` / `approval_allow.json` / `toolkit_approve(action='grant')`；
   `toolkit_approve` 与 `toolkit_audit_log` 自身豁免（否则无法完成授权）
3. **提权操作**：Agent **不允许**获取管理员/root 权限——`sudo`/`su`/`pkexec`/`runas` 等一律硬拒绝
   （`toolkit_exec` 与 `toolkit_scheduler` 两条执行路径都拦截，且识别 shell 包装与 `-Verb RunAs`）；
   需要提权的操作必须提示用户**手动执行**
4. **SQL 注入**：所有数据库操作使用参数化查询，禁止 f-string 拼接**未校验**的插值；
   标识符/片段必须走 `store/_sql_safety.py` 的校验助手（字面量、全大写常量、或校验助手调用）；
   `test_no_unsafe_sql_interpolation_in_store` 是硬门禁 —— 动态拼 `NOT IN (?,?)` 这类
   占位符也会被拦，改为 Python 侧算差集后逐条参数化
5. **路径遍历**：文件操作工具校验路径，禁止 `../` 逃逸（应急放宽见 `TEA_FILE_ALLOW_OUTSIDE`）
6. **审计不可静默失效**：审计为 hash 链，历史损坏须显式标记（不删数据、不静默放行）；
   并发写入下链断裂是必须修的真缺陷
7. **Sub-agent 隔离**：每个子 Agent 拥有独立 LiteSession，上下文隔离

## 文档同步规范

口径类事实（版本号、工具数、测试数、模块数、目录清单）**每次改动后必须实测同步**，
不得凭记忆或沿用旧值。同步范围：`README.md` + `README.en.md`（逐条对等）+ `AGENTS.md` + `CHANGELOG.md`。

- 数字口径命令见「快速命令」末尾；工具数务必区分模块数/注册数/可见数
- 已删除的能力必须从所有文档中清除（例：`toolkit_ocr` 删除后，README/AGENTS/`docs/TOOLS.md` 均不得再引用）
- `docs/TOOLS.md` 是工具清单快照（标题含「注册工具总数 / LLM 可见」）。**它当前已过期**
  （文件里写 56/54，实测 60/58），且仓库内没有它的生成脚本 —— 工具增删后请重新生成或补一个
  生成脚本，别直接引用其中的数字
- `README.en.md` 与 `README.md` 结构必须保持一致（章节、表格、代码块数量）；改完做一次平衡校验
  （`<details>` 与 `</details>` 数量、代码围栏成对）
- 变更需在 `CHANGELOG.md` 的 `[Unreleased]` 下按 `Features` / `Bug Fixes` / `Documentation` 等小节追加，只追加不修改已发布章节

## FAQ

**Q: 如何添加新工具？**
A: 在 `tea_agent/toolkit/` 创建 `toolkit_xxx.py`，实现 `toolkit_xxx()` 与 `meta_toolkit_xxx()` 后即可（`tlk.py` 自动按 `toolkit_*.py` 扫描+exec 加载，`__init__.py` 为空无需手工导入）；或用 `toolkit_save` 运行时注册，调用 `toolkit_reload()` 生效。新增后记得同步文档口径、`build_mini.py` 重型名单（若适用）、`docs/TOOLS.md`。

**Q: 自进化线程做了什么？**
A: 每小时自动：工具使用率分析 & 优化建议 → skill 模式整理 → 跨主题记忆提取；另有打断模式后台分析（M3/M4，同一工具打断 ≥2 次沉淀记忆 / ≥3 次生成行为指导 skill，事件保留 30 天）。改动经进化闸门评分决定 keep 或 rollback。

**Q: 三种 Agent 模式怎么选？**
A: `lightweight` 用于孤立任务；`full` 用于完整交互会话；`lite` 用于子 Agent 内部调用。

**Q: 用户要求「同步 README」时怎么做？**
A: 先 `git log --oneline -25` 找近期改动 → 逐条实测口径（工具数/测试数/版本/目录）→ 中英文 README 逐条成对替换（不要整篇重写，保留原结构与语气）→ `CHANGELOG` 追加 `Documentation` 条目 → 残留扫描（旧版本号、已删工具名、旧数字）→ 报告 diff 统计。

**Q: 工具调用统计表会无限增长吗？**
A: 不会。`tool_usage` 一行一工具（tool 为主键），体量与工具数同阶；`first_used` 用 COALESCE 保护不被改写（它是观测期基准）。遭遇 `database is locked` 要退避重试而非只记日志 —— 少记一条的后果是**误屏蔽真在用的工具**。

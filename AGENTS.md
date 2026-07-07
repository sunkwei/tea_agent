# Tea Agent — AGENTS 指令

> 自进化 AI Agent · 动态工具管理 · 可扩展运行时

## 项目定位

Tea Agent 是一个 **自进化的 AI Agent 框架**。核心能力：
- **动态工具管理**：Agent 可通过 `toolkit_save` 运行时创建新工具，调用 `toolkit_reload` 立即生效
- **多会话模式**：轻量级 (LiteSession)、完整 (OnlineToolSession)、子 Agent (Sub-agent)
- **多层自进化**：工具使用分析 → 技能固化 → 系统提示词进化 → 后台线程自动优化
- **GUI/TUI/CLI** 三套交互界面

## 快速命令

```bash
# ── 安装 ──
pip install -e .                    # 可编辑安装

# ── 构建 ──
python -m build                      # 构建分发包

# ── 运行 ──
tea_agent                            # 启动 GUI（默认入口）
tea_agent-cli                        # 启动 CLI 模式
tea-agent-api                        # 启动 API 服务器
tea-agent-mini                       # 启动 Mini 版
tea-agent-acp                        # 启动 ACP 协议

# ── 测试 ──
pytest                               # 运行全部测试
pytest tea_agent/tests/test_xxx.py   # 运行单文件测试
pytest -k "test_name" -xvs           # 按名匹配+详细输出

# ── 静态检查 ──
ruff check .                         # Lint 检查
ruff format . --check                # 格式检查
ruff format .                        # 自动格式化
black .                              # 备选格式化

# ── 类型检查 ──
python -m mypy tea_agent --ignore-missing-imports
```

## 项目结构

```
tea_agent/
├── agent.py               # 统一 Agent 类（三种模式入口）
├── agent_pipeline.py      # 后处理流水线（摘要、记忆提取）
├── agent_background.py    # 后台线程（定时任务、自进化）
├── onlinesession.py       # OnlineToolSession — 完整在线会话
├── litesession.py         # LiteSession — 轻量会话（子 Agent 用）
├── basesession.py         # 会话基类 + 容错 JSON 解析
├── gui.py                 # 桌面 GUI（tkinter + tkinterweb）
├── gui_dialogs.py         # GUI 对话框（TodoDialog 等）
├── tui.py                 # 终端 TUI（textual 框架）
├── cli.py                 # 命令行入口
├── config.py              # 配置加载与管理
├── memory.py              # 长期记忆管理
├── prompt_manager.py      # 系统提示词管理
├── reflection.py          # 元认知反思
├── providers.py           # LLM 提供商适配层
├── permission.py          # 工具权限管理
│
├── toolkit/               # ★ 工具注册中心（50+ 工具）
│   ├── __init__.py        # 自动扫描注册
│   ├── toolkit_exec.py
│   ├── toolkit_save.py
│   ├── toolkit_save_file.py
│   ├── toolkit_edit.py
│   ├── toolkit_diff.py
│   ├── ... (50+ 工具)
│
├── session/               # 会话管理子模块
├── store/                 # 存储层
├── compaction/            # 上下文压缩
├── multi_agent/           # 多 Agent 协作
├── protocol/              # ACP 协议实现
├── workflow/              # 工作流引擎
├── lsp/                   # 代码智能（Jedi + Ruff）
├── skills/                # 技能系统
├── server/                # API 服务器
│
├── tests/                 # 测试套件（35+ 测试文件）
│   ├── test_litesession.py
│   ├── test_onlinesession.py
│   ├── test_agent.py
│   ├── test_subagent_v2.py
│   ├── test_tool_build.py
│   ├── ...
│
├── mini/                  # Mini 构建独立包
```

## 架构边界

### 三层会话模型

```
┌─────────────────────────────────────────┐
│  Agent (统一入口)                        │
│  ├─ mode='full'     → OnlineToolSession │  ← 完整能力：存储、后台、摘要
│  ├─ mode='lite'     → LiteSession       │  ← 轻量：单轮、廉价模型、无状态
│  └─ mode='lightweight' → 上下文管理器    │  ← 极简：无存储、无后台
├─────────────────────────────────────────┤
│  Sub-agent 系统                          │
│  ├─ spawn/spawn_sync → 独立 LiteSession │  ← 隔离上下文、独立迭代
│  ├─ subagent_msg     → 消息传递          │  ← Agent 间通信
│  └─ collect/cancel   → 结果收集          │
├─────────────────────────────────────────┤
│  GUI / TUI / CLI 三界面                  │
│  ├─ gui.py (tkinter)                    │  ← 桌面窗口 + 浏览器组件
│  ├─ tui.py (textual)                    │  ← 终端交互
│  └─ cli.py (argparse)                   │  ← 命令行模式
└─────────────────────────────────────────┘
```

### 关键约束

1. **不得循环导入**：`agent.py` 不反向导入任何子模块；子模块只导入 `agent.py` 或同级模块
2. **工具注册**：新工具必须放在 `tea_agent/toolkit/` 目录，以 `toolkit_` 前缀命名，通过 `toolkit_save` 注册或直接在 `__init__.py` 中注册
3. **自进化边界**：后台自进化线程可优化工具代码、整理技能、调整提示词，但**不得修改用户对话历史**
4. **GUI 线程安全**：所有 GUI 操作必须在主线程执行；后台线程用 `after()` 回发

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

### 工具开发原则

- **纯 Python**：不依赖外部非标准可执行文件
- **明确输入输出**：参数使用 JSON Schema 定义，返回结构化结果
- **通用可复用**：不写死路径/Key，通过参数注入
- **失败隔离**：`batch_process` 等并行工具需单个失败不影响整体
- **幂等性优先**：重复调用不产生副作用

## 代码风格

### Python 规范

- **Python 3.10+**：使用 `dict | None` 联合类型、`match/case`、`dataclass`
- **命名**：`snake_case` 函数/变量，`PascalCase` 类，`UPPER_CASE` 常量
- **类型注解**：所有函数签名必须含类型注解
- **文档字符串**：公共函数/类须有 docstring（Google 风格），内部函数可选
- **行宽**：120 字符（ruff 配置）
- **导入顺序**：标准库 → 第三方 → 本地，每组空行分隔
- **避免**：全局可变状态、循环导入、`except: pass`

### 测试规范

- 测试文件：`tea_agent/tests/test_*.py`
- 使用 `pytest`，fixture 集中在 `conftest.py`
- 测试函数名：`test_<功能>_<场景>`
- 重要模块须有 `test_` 文件覆盖（目前覆盖率约 70%）

## 自进化规则

### 五层安全护栏（toolkit_self_evolve）

| 层级 | 保护 | 描述 |
|------|------|------|
| L0 | git 快照 | 仅在工作区干净时自动创建 |
| L1 | 时间戳 .bak | 每次修改备份，不覆盖历史 |
| L2 | 编译验证 | 修改后 `compile()` 检查语法 |
| L2.5 | LSP 检查 | 影响分析 + lint + 签名对比 |
| L3 | 测试回滚 | 测试失败自动 `git reset --hard` |

### 可修改 vs 不可修改

| ✅ 可修改 | ❌ 不可修改 |
|-----------|-------------|
| `toolkit/*.py` — 工具代码 | `.chat_history_protected` — 对话历史 |
| `tea_agent/gui*.py` — GUI | `chat_history.db` — 数据库 |
| `config.yaml` — 配置 | 用户 `~/.tea_agent/` 个人配置 |
| `prompt_manager.py` — 提示词 | 版本发布后的 CHANGELOG 只追加不修改 |
| 自进化生成的 `skills/` | |

## 提交规范

### 提交信息格式
```
<类型>: <简短描述>

<可选：详细说明>
```

类型：`feat` / `fix` / `refactor` / `docs` / `test` / `chore` / `release`

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
# 3. git commit -m "release: vx.y.z"
# 4. git push
```

### 分支策略
- `master` — 主分支，保持稳定
- `feature/*` — 功能开发分支（可选）
- 推送至 GitHub + NAS 双远程

## Mini 构建

`tea_agent_mini/` 是独立子包，精简依赖构建。规则：
- 只包含核心会话能力（无 GUI、无 TUI、无 LSP）
- 通过 `build_mini.py` 脚本构建
- 入口：`tea-agent-mini` CLI

## 安全注意事项

1. **工具沙箱**：`toolkit_exec` 执行系统命令，权限由 `permission.py` 控制
2. **SQL 注入**：所有数据库操作使用参数化查询，禁止 f-string 拼接
3. **路径遍历**：文件操作工具校验路径，禁止 `../` 逃逸
4. **提权操作**：`toolkit_sudo_gui` 弹出 GUI 密码框，不缓存密码
5. **Sub-agent 隔离**：每个子 Agent 拥有独立 LiteSession，上下文隔离

## FAQ

**Q: 如何添加新工具？**
A: 在 `tea_agent/toolkit/` 创建 `toolkit_xxx.py`，实现函数后用 `toolkit_save` 注册，调用 `toolkit_reload()` 生效。或直接修改 `__init__.py` 加入导入。

**Q: 自进化线程做了什么？**
A: 每小时自动：工具使用率分析 & 优化建议 → `docs/TOOLS.md` 同步 → 技能模式整理 → 跨主题记忆提取。

**Q: 如何调试 GUI？**
A: 运行 `python -m tea_agent.gui --debug`，GUI 超时检测用 `toolkit_test_gui`。

**Q: 三种 Agent 模式怎么选？**
A: `lightweight` 用于孤立任务；`full` 用于完整交互会话；`lite` 用于子 Agent 内部调用。

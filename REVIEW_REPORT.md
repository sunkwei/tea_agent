# Tea Agent 评审报告

> 评审范围：逻辑错误（LOGIC）、笔误（TYPO）、文档对 LLM 的理解友好度（LLM-DOC）。

汇总日期：2026

---

## 修复状态总览

> 本文档为**活文档**：每次评审/修复后持续更新此表。修复记录见 git log。

| 状态 | 修复 commit | 说明 |
|------|------------|------|
| ✅ 已修复 | `331b491` | 46 项报告问题 + 1 项额外发现的串库 bug 全部修复 |
| 🧪 测试 | — | 全量 1075 passed（含新增 fork 串库回归） |

### 逐项状态（46 = 41 逻辑 + 5 文档）

| # | 问题 | 状态 |
|---|------|------|
| 1 | toolkit_edit CRLF 索引错位写坏文件 | ✅ 331b491 |
| 2 | toolkit_diff run_tests 恒回滚 + glob 不展开 | ✅ 331b491 |
| 2c | toolkit_diff stash 卷入/丢弃用户改动 | ✅ 331b491（改备份式 undo，不碰 stash） |
| 3 | self_evolve 漏 errors + glob 不展开 → L3 回滚失效 | ✅ 331b491 |
| 4 | followup 硬截断 300 | ✅ 331b491（尊重 partial_reply_max） |
| 5 | agents_md_loader 跨盘 commonpath 崩溃 | ✅ 331b491 |
| 6 | 幽灵工具引用（5 个不存在工具） | ✅ 331b491 |
| 7 | skill_loader 冗余分支 | ✅ 331b491 |
| 8 | basesession 过时注释 | ✅ 331b491 |
| 9 | agent_evolution Act 层不可用 | ✅ 331b491 |
| 10 | memory CRITICAL 误删 | ✅ 331b491 |
| 11 | providers 布尔字符串化 | ✅ 331b491 |
| 12 | config max_tokens 回环丢失 | ✅ 331b491 |
| 13 | memory importance=NULL 崩溃 | ✅ 331b491 |
| 14 | reflection 死代码 | ✅ 331b491 |
| 15 | op_failed 空消息 | ✅ 331b491 |
| 16 | agents_md_loader 错误 API 示例 | ✅ 331b491 |
| 17 | 续命双倍累加 | ✅ 331b491 |
| 18 | is_summarized 互斥 | ✅ 331b491（独立 memory_extracted 列） |
| 19 | kwargs.pop KeyError | ✅ 331b491 |
| 20 | relaxed_json_loads 破坏 URL | ✅ 331b491 |
| 21 | Agent.close 资源泄漏 | ✅ 331b491 |
| 22 | 不可达 return / 变量名误导 | ✅ 331b491 |
| 23 | 标题守卫字符错乱 | ✅ 331b491 |
| 24 | AutoMemoryExtractor ctx 死路径 | ✅ 331b491 |
| 25 | release_version git commit 参数错位 | ✅ 331b491 |
| 26 | toolkit_save 从不写版本备份 | ✅ 331b491 |
| 27 | toolkit_memory kwargs 死代码 | ✅ 331b491 |
| 28 | run_tests 脚本式运行 | ✅ 331b491 |
| 29 | toolkit_exec 单条未捕获 | ✅ 331b491 |
| 30 | 路径遍历未拦截 | ✅ 331b491 |
| 31 | config 单字段坏值静默丢弃 | ✅ 331b491 |
| 32 | set_active_config_path 不生效 | ✅ 331b491 |
| 33 | 字节预算实为字符计数 | ✅ 331b491（真 UTF-8 字节） |
| 34 | memory 时区偏移只剥正偏移 | ✅ 331b491 |
| 35 | merge_memory 丢信息 | ✅ 331b491 |
| 36 | LiteSession hooks 泄漏 | ✅ 331b491 |
| 37 | lite 末回合 off-by-one | ✅ 331b491 |
| 38 | 压缩首尾窗口重叠（2 处） | ✅ 331b491 |
| 39 | [THINK_DONE] 标记丢失 | ✅ 331b491 |
| 40 | 并发摘要 token 竞态 | ✅ 331b491 |
| 41 | agent_background 硬编码阈值 | ✅ 331b491 |
| DOC-1 | AGENTS.md 入口命令不符 | ✅ 331b491 |
| DOC-2 | lightweight 模式图不符 | ✅ 331b491 |
| DOC-3 | 工具数量矛盾 | ✅ 331b491 |
| DOC-4 | 护栏层级缺 L1.5 | ✅ 331b491 |
| DOC-5 | __init__.py 注册描述错误 | ✅ 331b491 |
| 额外 | StoreComponent thread-local 串库 | ✅ 331b491（全量测试暴露） |

> 注：原始审查记录保留如下，逐项细节见各条目标题。

---

## 一、关键逻辑错误 / 缺陷（按严重度排序）

### 1. 【LOGIC-高】toolkit_edit `_replace_text` CRLF 索引错位 → 文件被写坏
`tea_agent/toolkit/toolkit_edit.py:106-129`

```python
original_norm = original.replace('\r\n', '\n').replace('\r', '\n')
old_norm = old_text.replace('\r\n', '\n').replace('\r', '\n')
idx = original_norm.find(old_norm)                       # 在"规范化"串上算下标
...
new_text_raw = original[:idx] + new_norm + original[idx + len(old_norm):]  # 却切"原始"串
```
- `idx` 是对 `original_norm`（已把 CRLF→LF，长度变小）计算的，但切片用在 `original`（原始 CRLF 串）。
- 当文件含 CRLF（Windows 项目常见）时，`idx` 与原始字节位置错位，替换内容插到错误位置、混入新的换行风格，甚至乱码。
- 与同名注释“preserve original line endings style”矛盾：实际插入的是 `new_norm`（纯 LF），并未保留原风格。

**修复建议**：直接在 `str.replace` 之前用同一份规范化串进行替换，或把 index 映射回原始字节（用 `original.find(old_text)` 并处理换行边界）。

### 2. 【LOGIC-高】toolkit_diff `_verify_all` 的 `run_tests` 被注释掉 + glob 永不展开 → apply 恒回滚（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_diff.py:161-164`
- `if run_tests:` 被注释掉 → 测试无条件执行，且 pytest 块缩进在 `for fp in files:` 循环体内，**每个文件跑一遍测试**。
- `pytest test_*.py` 经 `subprocess.run` 无 shell，glob **不展开** → `ERROR: file or directory not found`，exit 4 → `all_ok` 恒 False → `apply` 在所有平台都失败并回滚。
- 另见 #24b（`_git_stash_drop` 会丢弃用户原有未提交改动），叠加使该工具几乎不可用。

### 2c. 【LOGIC-严重】toolkit_diff 成功路径丢弃用户未提交改动 + stash 状态恒真（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_diff.py:80-88, 355-357`
- `_git_stash_push` 把**所有** dirty 跟踪文件（不只本次编辑的）压入 stash；成功后 `_git_stash_drop` 永久丢弃该 stash → 用户原有的未提交改动随 apply 一起丢失。
- `_git_stash_push` 即使无改动也返回 `ok=True` → 干净工作区也报 `stashed=True`，`undo`/`drop` 命中用户自有 stash。

### 3. 【LOGIC-高】toolkit_self_evolve 测试统计漏算“errors”
`tea_agent/toolkit/toolkit_self_evolve.py:85-97, 414-433`

```python
m = re.search(r'(\d+)\s+passed', output)
m = re.search(r'(\d+)\s+failed', output)
total = passed + failed
```
- 只解析 `passed`/`failed`，**不解析 pytest 的 `errors` 行**。集内/夹具设置错误会以“errors”呈现，不被计入 `total`。
- 且 `pytest tea_agent/tests/test_*.py` 无 shell、glob 不展开 → 文件找不到 → passed=0/failed=0/total=0 → `test_passed < test_total` 为 `0<0` False → **L3 测试回滚从不触发**，工具总报成功 `"tests":"0/0"`（子 Agent 评审确认）。
- 于是受损代码被“验证通过”，不触发回滚。

### 4. 【LOGIC-中】onlinesession 打断注入 followup 被硬截断到 300
`tea_agent/onlinesession.py:1977`
```python
followup_max = min(int(icfg.get("partial_reply_max", 2000)), 300)
```
- 无论 `partial_reply_max` 配置多少，最多取 300。配置 2000 的默认值被 300 硬覆盖，用户调大配置无效。疑似笔误或阈值误用。

### 5. 【LOGIC-中】agents_md_loader 跨盘 `os.path.commonpath` 抛异常
`tea_agent/agents_md_loader.py:180-182`
```python
label = os.path.relpath(path, os.getcwd()) if os.path.commonpath([path, os.getcwd()]) else path
```
- `os.path.commonpath` 在 Windows 双盘路径时抛 `ValueError`，而非返回假值。
- 意图中的“否则用原始路径”分支永远不会走到；跨盘时整个 `load_agents_md` 崩溃。
- `if <string> else` 本身也是恒真判断（返回非空串），属冗余/易错写法。

### 6. 【DOC/LLM-高】多处引用不存在（幽灵）工具
以下工具在代码中从未定义，却被注入给 LLM 或被 AGENTS 指令引用，导致 LLM 调用即 “Unknown tool”：
- `toolkit_test_gui` — AGENTS.md:268 直接让 LLM 用它做 GUI 超时检测；`toolkit_diff.py:418` 分类表列出。
- `toolkit_read_pyproject` — `toolkit_mode.py:61,111` 在 docs 模式指令中“优先使用”；`toolkit_diff.py:415` 列出。
- `toolkit_git_branch_manager` — `skill_loader.py:181` covered_by；`toolkit_diff.py:434` 列出。
- `toolkit_diag_reasoning` — `DEEPSEEK_REASONING_SUPPORT.md:136` 提供诊断用法示例。
- `toolkit_load_file` — **LiteSession 默认 system prompt** `litesession.py:55` 与 `prompt_manager.py:35`“内置工具：toolkit_load_file(读文件)”。子 Agent 全部继承此 prompt，会直接尝试调用这个不存在的工具。

**对 LLM 的后果**：这些引用被拼进 system prompt / AGENT 指令 / skill 决策 / 分类表，LLM 会真的去调用并收到错误，影响任务完成。

### 7. 【LOGIC-低】skill_loader `evaluate_and_load` 冗余分支
`tea_agent/skill_loader.py:403-406`
```python
if loaded and not getattr(context, "_skill_loaded", None):
    context._skill_loaded = loaded
elif loaded:
    context._skill_loaded = loaded
```
- `if` 与 `elif` 做同一件事（都是 `= loaded`），属编辑残留/冗余；若本意是“增量合并”则覆盖语义易丢状态。

### 8. 【TYPO/LOGIC-低】basesession 动态状态注入注释过时
`tea_agent/basesession.py:272` 注释“token_budget 已禁用（上下文评估偏差）”，但 `context_fragments.py:55` 已注明“token_budget 已重新启用（2026-08-12）”。两处互相矛盾的过期注释，且 basesession 里 `assemble_fragments(names=[...])` 显式省略 token_budget —— 读者无法从注释判断当前真值。

### 9. 【LOGIC-高】agent_evolution Act 层整体不可用（子 Agent 评审确认）
`tea_agent/agent_evolution.py:185-192, 199-201`
- `self.tk.call_tool("toolkit_file", file_path=file_path)` — `toolkit_file` 无 `file_path` 参数（签名是 `action, filename, path, ...`）→ 每调用必 `TypeError` → `content` 恒为 `""` → `old_code=""`。
- `old_code=""` 进 `toolkit_self_evolve` → `content.count("") = len+1 > 1` → 永远报“old_code 出现多次”。
- `new_code="<!-- evolution: 等待 LLM 在下轮修复 -->"` 是 HTML 注释，非合法 Python → 语法/编译层必败。
- `toolkit_prompt_evolve(action="evolve", suggestion=suggestion)` — 无 `suggestion` 关键字 → 必 `TypeError`。

### 10. 【LOGIC-高】memory 字符预算剔除先弹后判，误删 CRITICAL（子 Agent 评审确认）
`tea_agent/memory.py:169-173`
```python
score, m = selected.pop()  # 末尾 = 最低分
if score >= 1e8:  # CRITICAL 不剔除
    break
```
- 弹出了 CRITICAL 之后才判断 > 1e8，然后 `break` —— 被弹出的 CRITICAL 已丢失，与“CRITICAL 不剔除/豁免”语义矛盾。

### 11. 【LOGIC-中】providers `switch_provider` 写入字符串布尔值（子 Agent 评审确认）
`tea_agent/providers.py:217-218` `cfg.main_model.options["supports_vision"] = str(...).lower()` → `"false"` 字符串在 `ModelConfig.supports_vision` 里恒真（`config.py:62-63`）→ 切换后视觉/推理能力被误报为开启；与 `generate_config`（198-199 输出真布尔）不一致。

### 12. 【LOGIC-中】config `max_tokens` 4096 vs 默认 131072 回环丢失（子 Agent 评审确认）
`tea_agent/config.py:797` `if target.max_tokens != 4096:` 与 dataclass 默认 `131072`（config.py:49）比较，模板默认 `4096`（config.py:935）在 `save_config()` 时被写漏 → 重载静默变为 131072，配置往返丢失。

### 13. 【CRASH-中】memory `importance=None` 触发 TypeError，禁用整场记忆注入（子 Agent 评审确认）
`tea_agent/memory.py:195` `max(memory.get("importance", 3), 1)` — 若某行 `importance` 为 NULL，`max(None,1)` 抛 `TypeError`；调用点 `session_memory_component.py:70-74` 的 try/except 会静默禁用本会话全部记忆注入。

### 14. 【LOGIC-中】reflection 反省触发条件为死代码（子 Agent 评审确认）
`tea_agent/reflection.py:142-149` 调用不存在的 `self.storage.get_reflections(limit=1)` / `get_conversation_count()`，被 `except Exception` 吞掉 → “超过 10 条对话触发反思”逻辑从未生效。

### 15. 【TYPO/LOGIC-低】多处 `logger.exception('op_failed')` 空消息
`memory.py:292, reflection.py:149, toolkit_self_evolve.py` 等：异常路径只打一个无意义字符串 `'op_failed'`，无任何上下文，掩盖真实异常（尤其在已静默失败的 #11/#13/#14 处）。

### 16. 【DOC-低】agents_md_loader 用法示例给了错误 API（子 Agent 评审确认）
`tea_agent/agents_md_loader.py:16-17` 文档示例用 `loaded["text"]` / `loaded["sources"]`，但返回的是 `LoadedAgentsMd` dataclass，须用属性 `loaded.text` / `loaded.sources`。示例会教 LLM 走向 `TypeError: not subscriptable`。

### 17. 【LOGIC-高】续命迭代被重复累加（子 Agent 评审确认）
`tea_agent/agent.py:399` 与 `session/tool_loop_runner.py:714` 都对 `_extra_iterations += extra`——`status_cb` 加一次，tool loop runner 又加一次。默认 5 次的续命实际多给 10 轮。

### 18. 【LOGIC-高】is_summarized 标志被两套子系统互斥占用（子 Agent 评审确认）
`session_memory_component.py:355-360` 的 `AutoMemoryExtractor` 与 L3 摘要器共用 `conversations.is_summarized` 列但语义相反（`store/_summaries.py:351-384`）——先跑者会永久隐藏对话，导致摘要或记忆提取缺失其一。

### 19. 【CRASH-中】onlinesession `kwargs.pop` 未保护（子 Agent 评审确认）
`tea_agent/onlinesession.py:492-494` 对 `stream_options`/`extra_body` 直接 `kwargs.pop(...)`，当 `supports_reasoning=False` 或 `extra_body` 为空时抛 `KeyError`。

### 20. 【LOGIC-中】relaxed_json_loads 注释剥离破坏 URL（子 Agent 评审确认）
`tea_agent/basesession.py:31` `re.sub(r"//[^\n]*", "", s)` 会把字符串里的 `"https://…"` 截成 `"https:"`；line 41 又把合法 JSON 转义（`\n`/`\t`）二次转义。每次走容错回退都破坏含 URL 的工具参数。

### 21. 【LOGIC-中】Agent.close() 未释放会话资源（子 Agent 评审确认）
`tea_agent/agent.py:883-889` `close()` 从没调用 `self._sess.close()`，与“释放资源”docstring 不符 → HTTP/OpenAI 客户端泄漏。

### 22. 【TYPO-中】信号量/缩进等杂物
`agent_background.py:298-299` `return None` 在 `return False` 之后不可达；`agent.py:235-237` `model_key`/`model_url` 变量名其实装的是 `api_key`/`api_url`（误导，功能正确）；`memory.py:292` 等 `logger.exception('op_failed')` 空消息。

### 23. 【TYPO-高】自定义标题守卫字符错乱（子 Agent 评审确认）
`tea_agent/agent_pipeline.py:123` auto_summary 的“跳过已有自定义标题”守卫比较的是 `U+201B ‛`，但 store 的人为标题前缀是 `U+203B ※`（`store/_topics.py:44`）→ 守卫永不触发，已有标题的主题每次对话仍白跑一次 LLM 调用。

### 24. 【CRASH-中】AutoMemoryExtractor.get_memory_stats 引用不存在的 self.ctx（子 Agent 评审确认）
`session_memory_component.py:379-386` 从 `MemoryComponent` 复制而来，但 `AutoMemoryExtractor` 无 `self.ctx` → `AttributeError` 死路径。

### 25. 【LOGIC-高】toolkit_release_version 的 git commit 参数错位，从不能成功（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_release_version.py:95-99`
`["git","commit","'release: v…'","-m","'change1'"]`：标题作为第一个位置参数、且无 `-m` 前缀 → git 当作 pathspec → 永远 `error: pathspec ... did not match`。

### 26. 【LOGIC-高】toolkit_save 从不写版本备份 → rollback/list_versions 恒空（子 Agent 评审确认）
`tea_agent/tlk.py:604-622, 662`：`Toolkit.save()` 计算版本号后 `pass`，从不写 `.v*.bak.py`；`toolkit_rollback` 恒报“backup not found”，`toolkit_list_versions` 恒空。与 AGENTS.md“版本回滚”宣传（README 208/210 行）不符。

### 27. 【LOGIC-中】toolkit_memory auto_extract/semantic_search 从 kwargs 读具名参数（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_memory.py:134-135,151,154`：`topic_id`/`force`/`query`/`top_k` 是具名参数却用 `kwargs.get(...)` 读取 → 恒取默认 → 两 action 恒报“需要参数”异常，死代码。

### 28. 【LOGIC-中】run_tests 以普通脚本方式跑测试文件（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_run_tests.py:31-35`：`python <file>` 而非 `python -m pytest`；无 `__main__` 的 pytest 文件静默 exit 0 → 失败测试被报为通过；`cwd.glob('test_*.py')` 也漏掉 `tea_agent/tests/`。

### 29. 【LOGIC-中】toolkit_exec 单条分支未捕获 Popen 异常（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_exec.py:271-278`：`_run_single_with_monitor`/单条分支无 try/except，命令不存在时 `FileNotFoundError` 直接冒出，`call_tool` 崩溃（批量分支 line 477 有捕获）。

### 30. 【SECURITY-中】路径遍历未被拦截，与 AGENTS.md 声明矛盾（子 Agent 评审确认）
AGENTS.md:255 声明“文件操作工具校验路径，禁止 `../` 逃逸”，但 `toolkit_diff.py:110,190`、`toolkit_self_evolve.py:34` 把 LLM 给的 `file_path` 直接 `os.path.join(cwd, ...)`，`toolkit_save_file.py:22` 用 `Path(path)` 接受 `..`/绝对路径 —— 均无 `..` 校验。SQL 注入则**未发现**（全部参数化）。

### 31. 【LOGIC-中】config 单字段坏值静默丢弃整个配置（子 Agent 评审确认）
`tea_agent/config.py:444-445` `except Exception: pass  # 加载失败时使用默认空配置`：任一字段解析失败（如 `max_tokens: abc`）即丢弃整个用户配置且无日志，留下模型已解析、会话参数未解析的半填充状态。

### 32. 【LOGIC/DOC-中】set_active_config_path 不生效（子 Agent 评审确认）
`tea_agent/config.py:388-398,453-485,667-679` `_active_config_path` 从未被 `load_config`/`get_config` 读取（只认 `_last_config_path`），且 `_update_config_cache` 会覆盖它 → 切换配置无实际效果；`get_config` docstring 声称的“缓存路径不符自动重载”并未实现。

### 33. 【LOGIC/DOC-中】“字节预算”实为字符计数，中文下偏 ~3×（子 Agent 评审确认）
`agents_md_loader.py:9-10,154,184-189` 与 `context_fragments.py:407,429`：预算用 `len()`（字符数）而非 UTF-8 字节；中文每字 3 字节，实际占用约声明值的 3×；`total_bytes` 字段名误导（实为字符）。截断分支 `total += remaining` 未算后缀字符，且 `assemble_fragments` 预算耗尽处 `break`（`context_fragments.py:436-438`）会丢弃所有更低权重的片段（如 `agents_md`）。

### 34. 【LOGIC-低】memory 时区偏移处理只在正偏移生效（子 Agent 评审确认）
`tea_agent/memory.py:460` `str(created).replace("Z","+00:00").split("+")[0]`：能剥 `+08:00` 却剥不掉 `-05:00` → 得到 aware datetime，`now − last_dt` 抛 naive/aware `TypeError` → 这些记忆永不过期降级；`replace("Z")` 因后续 `split("+")` 属无效代码。

### 35. 【DOC-低】_merge_memory docstring 与代码矛盾（子 Agent 评审确认）
`tea_agent/memory.py:708-727` docstring 称“保留更长的，或拼接（若两者都较长）”，实际仅当旧内容 <200 字才拼接，且当新内容更长时 `merged_content = new_content` 直接丢弃旧内容——与“去重合并不丢信息”的本意相反。

### 36. 【CRASH-中】LiteSession 注入全局 tool_hooks 后从未排空（子 Agent 评审确认）
`tea_agent/litesession.py:418-421` 把 post-hook contexts 写入全局 `tool_hooks` 单例，但 drain 只在 `tool_loop_runner.py:681` 存在 → 注入的 context 泄漏进下一个 `OnlineToolSession` 的工具循环，同时本会话又读不回。跨会话污染。

### 37. 【LOGIC-中】litesession 最后文本回合 off-by-one（子 Agent 评审确认）
`tea_agent/litesession.py:163-195` 当工具轮恰好耗尽 `max_iterations` 时循环退出，模型的最终文本回合从未执行 → 回复停在上一个工具结果，无总结。

### 38. 【LOGIC-中】_compress_tool_content 首尾窗口可能重叠（子 Agent 评审确认）
`tea_agent/basesession.py:378-419`（`onlinesession.py:686-709`、`basesession.py:452-470` 同病）：当 `max_chars < 长度 < max_chars+254` 且首尾换行落到同一区段时，head/tail 重叠 → 输出重复内容、标记里 `skipped_bytes` 变负值。

### 39. 【LOGIC-中】[THINK_DONE] 刷新标记被误读成思考文本（子 Agent 评审确认）
`tea_agent/agent.py:389-393` `stream_cb` 先做前缀匹配再精确匹配 → `[THINK_DONE]` 被当作思考文本 `"DONE]"` 上报，GUI/TUI/server 依赖的 flush 标记丢失。

### 40. 【LOGIC-中/低】agent_pipeline 并发摘要覆盖共享 token 计数
`tea_agent/agent_pipeline.py:30-43` 并发 `do_async_summaries` 线程互写共享 `agent._pending_cheap_tokens` → 先前的 pending 计数在 GUI 读取前被覆盖丢失（子 Agent 确认为竞态）。

### 41. 【TYPO/DOC-低】agent_background 硬编码阈值与 docstring 不符（子 Agent 评审确认）
`tea_agent/agent_background.py:16 vs 254` 模块注释称 `interruption.*` 可由 config 覆盖，但 `min_count` 是硬编码常量 `_INTERRUPT_ANALYZE_MIN_COUNT`，从不读配置；另 `onlinesession.py:1175-1176` 注释称“异步执行，不阻塞初始化”而实际在 `__init__` 同步跑（最多 2 次 API 探测）。

### 42. 【LOGIC-高】toolkit_edit `_apply_patch_python` 忽略 context 行，破坏真实 diff（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_edit.py:226-260` 收集全部 `-`/`+` 行后从 `start_idx` 精确 pop `len(delete_lines)` 行并连续插入 `+` 行，**从不跳过 context 行** → 前置/穿插的 context 被删、穿插的删除行残留。实测 hunk `-old_a/ ctx/ -old_b` 得出 `new_a/new_b/ctx/old_b/keep2`（`keep1` 被删、`old_b` 未删）。仅零 context hunk 正确；在无 `patch` 二进制的平台（如 Windows）回退到它，破坏极严重。

### 43. 【LOGIC-高】toolkit_edit 整文件换行风格在 Windows 被统一改写（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_edit.py:129/141`（及 `toolkit_diff_edit.py:161-162`）用 `open(..., 'w')` 默认 `newline=None` 写回 → Windows 上 LF 文件被整体改成 CRLF，一次单行编辑变全文件 diff；`toolkit_diff_edit` docstring 声称“统一换行符为 \n”却实际写成 CRLF。

### 44. 【LOGIC-中】toolkit_self_evolve 语法预检误报，拒绝合法代码（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_self_evolve.py:235-284,288-299` 缺冒号正则 `…[^:]\s*$` 会误报 `if x:  # comment`（注释在冒号后）；括号/字符串朴素扫描器会把注释/字符串里的括号、引号误判（如注释里一个未匹配 `(` 报“未闭合括号”）；缩进还强制 4 的倍数 → 合法代码被拒并回滚。

### 45. 【LOGIC-中】toolkit_self_evolve `_git_revert` 用 `reset --hard HEAD~1`，丢弃全部未提交改动（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_self_evolve.py:68-75` 任一回滚都会清除仓库里所有未提交改动（不只被改文件）——对无关工作区改动是数据丢失隐患。

### 46. 【LOGIC-中】toolkit_todo 模块级全局 `_todos` 破坏子 Agent 隔离（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_todo.py:6` `_todos` 是进程级全局，并发并行子 Agent / `create` 与 `check` 之间切换 topic 会竞态/串状态。

### 47. 【LOGIC-中】toolkit_query_chat_history NULL 字段崩溃且任何分支都无错误处理（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_query_chat_history.py:58-59` `d['user_msg'][:200]` 在 NULL 列抛 `TypeError`；`sqlite3.connect` 无 `timeout`，锁库时 `OperationalError` 未捕获。另 `search`（line 72-82）`SELECT *` 整表载入 Python 逐行扫描，性能差。

### 48. 【LOGIC/PERF-中】toolkit_parallel_subtasks 超时并未真正终止子任务（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_parallel_subtasks.py:157-166` `future.result(timeout=...)` 放弃慢子任务但 worker 线程继续跑，`ThreadPoolExecutor.__exit__` 的 `shutdown(wait=True)` 阻塞直到所有卡住的 `agent.chat` 结束；超时后才到的结果被静默丢弃。

### 49. 【LOGIC-中】toolkit_exec 单条危险命令中断整个批量（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_exec.py:515-523` 一条危险命令会让整批立即返回单个假结果，而非失败隔离——与工具自身“单条失败不影响整体”的本意相悖。

### 50. 【DOC-BUG-中】多个工具 schema/描述与实现矛盾（子 Agent 评审确认）
- `toolkit_exec.py:722` timeout 描述自相矛盾（“默认120” vs “默认30”，实际签名默认 30、单条用 `timeout if timeout else 120`）。
- `toolkit_exec.py:571-572` 批量恒返回 `"ok": True` 即使每条都失败（success_rate “0/N”），误导 LLM 工具调用。
- `toolkit_memory.py:15 vs 8` docstring 称 list 默认 20，实际 `limit=10`。
- `toolkit_diff.py:495-496` `files` schema 无任何 properties、描述为空 → LLM 无从得知必需的 `file_path/old_code/new_code` 键；`cwd`/`stash_ref` 也不在 schema。

### 51. 【LOGIC-低】toolkit_diff `_apply_patch_python` 无法处理新建文件 hunk（子 Agent 评审确认）
`tea_agent/toolkit/toolkit_diff.py:230-236` `@@ -0,0 +1,N @@` → `old_start=0` → `start_idx=-1` → 报“行号超出范围”；`old_count`/`new_count` 被解析却从不用于校验。

### 52. 【TYPO-低】若干死代码/表述（子 Agent 评审确认）
`tlk.py:172` 计算一个签名串后丢弃（无赋值）；`toolkit_self_evolve.py:6` docstring 首行把生成器头“@2026-05-19 gen by claude, 集成LSP检查层…”塞进描述；`toolkit_exec.py:434-446` 批量硬截止被杀时 `timeout_kind` 仍为空、hint 误报“空闲超时”。

---

## 二、笔误 / 文案错误

### DOC-1　AGENTS.md 快速命令与真实 console_scripts 不符
- AGENTS.md:23 写 `tea_agent` 启动 **GUI**，但 `pyproject.toml:48` 映射 `tea_agent = "tea_agent.server:main"`（Web/API 服务器）。GUI 入口其实是 `tea-agent-gui`（`pyproject.toml:50`）。
- AGENTS.md:24 写 `tea_agent-cli` 启动 CLI，但 `[project.scripts]` 里**没有** `tea_agent-cli`，只有 `cli.py` 文件、无入口点。命令不存在。
- 若目标是让 LLM 按文档跑命令，应修正为与实际入口一致。

### DOC-2　AGENTS.md 模式架构图与代码不符
- AGENTS.md:107 称 `mode='lightweight' → 上下文管理器（极简）`，但 `agent.py:54` 的实际 `lightweight` 用 `OnlineToolSession`（仅关闭 storage/background）。并无独立“上下文管理器”会话类。

### DOC-3　工具数量自相矛盾
- AGENTS.md:68 写“50+ 工具”，README:20/43、tlk.py docstring 写“75+”。实操统计：`toolkit/` 下 68 个带 `meta_` 的注册工具 + `tlk.py` 动态绑定 4 个 = **72**。
- `context_fragments.py:162` 注释称“78 个工具”，也偏大。

### DOC-4　五层护栏层级编号在 AGENTS.md 与 README 不一致
- AGENTS.md:193-199 列 L0/L1/L2/L2.5/L3（前 5 个），代码实际有 **6** 步：Layer0/1/**1.5**/2/2.5/3（`toolkit_self_evolve.py` 含 `Layer 1.5 语法严格检查`）。
- README:198-204 列出 Layer 0/1/1.5/2/2.5/3。AGENTS.md 表格漏掉 Layer 1.5，且标注“五层”却实为六步。

### DOC-5　AGENTS.md “在 __init__.py 中注册”
- AGENTS.md:124 称新工具“或直接在 __init__.py 中注册”，但 `toolkit/__init__.py` 是**空文件**，工具实际由 `tlk.reload()` 按 `toolkit_*.py` 扫描+exec 注册。

---

## 三、文档对 LLM 的理解友好度评估

总体：AGENTS.md 的**结构与分层**（快速命令/结构图/约束/安全表）对 LLM 友好，但存在以下“只有人类才懂、LLM 会踩坑”的问题：

### LLM 友好度问题
1. **充斥着人类向的“★”“🧠”“横幅”视觉装饰**，占用 token 且无信息增益。LLM 不关心 `★★★` 强调，只在意权威规则文本。
2. **大量“应/必须”语义混在自然段里**（如“不得循环导入”“禁止 f-string 拼接”），未统一为机器可扫的清单字段（`DO`/`DON'T`），LLM 容易遗漏。
3. **手册式的“解释为什么”**（如 `_compress_tool_output` 的冗长 docstring）远超给模型看所需的“是什么/怎么用/阈值多少”三元组 —— 应压缩为规则 + 关键数字。
4. **数字与阈值散落**（64KB/16KB/2KB/150 字符/0.15 报警比/30s TTL 等）在各文档反复出现但无单一“常量清单”，LLM 拼接自估时易取错。
5. **“三层/五层/六级/75+/870+用例”等出现多个口径**，LLM 无法确定唯一事实。
6. **面向人类的分隔线/表格/图标字符**（`┌──┐`、emoji 表格）在 token 化时低效且与指令体混排，降低“规则密度”。

### 建议（把文档改造成“机器可消费”）
- 在 AGENTS.md 顶部加一段**“给读取者的元指令”**：本文件是给自动化 agent 的指令契约，逐条可执行；把“建议/可选”与“必须”显式区分。
- 用统一结构（`## RULES` / `## TOOLS_INVENTORY` / `## LIMITS`）承载关键规则与常量。
- 移除冗余装饰，保留代码块示例（示例对 LLM 极有用）。
- 工具清单改为 `{name: 一句话作用, 关键参数, 满足度阈值}` 表格，而非“50+ / 75+”模糊计数。
- 修正所有指向不存在命令/工具/入口的引用（见上文 DOC-1 ~ DOC-3、幽灵工具）。

---

## 四、结语
- **严重 / 高优先修复**：
  - 会**丢数据/损坏文件**的：#1 CRLF 替换写坏文件；#2c `toolkit_diff` stash-drop 丢弃用户未提交改动；#3/…及 `toolkit_edit` 的 `_replace_lines` 缺末尾换行合并行、`_insert_lines` 用文件末行换行判断；#42 `_apply_patch_python` 忽略 context 行破坏真实 diff；#43 Windows 整文件换行改写；#45 `reset --hard HEAD~1` 丢全部未提交改动。
  - **逻辑整体不可用**：#2 `toolkit_diff run_tests 恒回滚` 与 #25 release_version git commit 从不能成功；#9 agent_evolution Act 层失效；#26 `toolkit_save` 版本备份从未写入（rollback 恒空）；#18 is_summarized 互斥；#17 续命双倍累加；#27 toolkit_memory kwargs 死代码。
  - **校验形同虚设**：#3 self_evolve 测试 rollback 从不触发；#23 标题守卫字符错乱。
  - **LLM 会被带偏**：#6 幽灵工具引用；#50 工具 schema/描述与实现矛盾。**安全**：#30 路径遍历未拦截（与 AGENTS.md 声明矛盾）。
- **中优先**：#5 `commonpath` 跨盘崩溃；#4 followup 硬截断；#19 `kwargs.pop` KeyError；#20 relaxed_json_loads 破坏 URL；#21 Agent.close 资源泄漏；#11 switch_provider 布尔字符串化；#12 config max_tokens 回环丢失；#13 memory None-importance 崩溃；#14 reflection 死代码；#28 run_tests 脚本式；#29 exec 未捕获；#31 config 单字段坏值丢整配置；#32 set_active_config_path 不生效；#34 memory 时区偏移只剥正偏移；#36 LiteSession hooks 泄漏；#37 lite 末回合 off-by-one；#38 压缩参数首尾重叠；#39 `[THINK_DONE]` 标记丢失；#44 语法预检误报；#46 toolkit_todo 全局态；#47 query_chat_history NULL 崩溃；#48 parallel_subtasks 超时未终止；#49 exec 批量中断。
- **文档**：把 AGENTS.md 从“给人看的项目介绍”重构为“给 LLM 的指令契约”，统一工具清单/阈值/入口命令口径，修正全部幽灵工具与错误示例（#6、#16、DOC-1~5），补齐泄漏的路径校验实现，并把“字节预算”改为真字节计数（#33）。

---

# 复审结论（fix commit `331b491` 之后）

> 逐项核对了修复提交（含 HEAD `4d95bdf`，无后续代码改动）。代码修复整体准确、大多数到位；但发现 **2 个新引入的回归** 与若干 **未修复的遗留项**。

## ✅ 已正确修复（本人核对 + 子 Agent 复核 + 实测）

| 类别 | 原问题 | 结论 |
|---|---|---|
| 数据安全 | `#1` toolkit_edit `_replace_text` CRLF 索引错位写坏文件 | ✅ 规范化串上匹配+切片，再恢复 CRLF（`toolkit_edit.py:105-134`） |
| 数据安全 | `#2c` toolkit_diff stash-drop 丢弃用户改动 | ✅ 改为 `.bak.<ts>` 备份式 undo，不再 stash（`toolkit_diff.py:334-337,401-423`） |
| 数据安全 | `#10` memory CRITICAL 先弹后判误删 | ✅ 先判再弹（`memory.py:169-174`） |
| 校验 | `#3` self_evolve glob 不展开 + 漏 errors | ✅ glob 显式展开 + 复数 errors 计入 total（`self_evolve.py:84-106`） |
| 校验 | `#23` 标题守卫字符错乱 | ✅ 已修 |
| 工具可用 | `#25` release_version git commit 参数错位 | ✅ `-m` + 逐条 `-m`（`release_version.py:95-99`） |
| 工具可用 | `#26` toolkit_save 从不写版本备份 | ✅ 自动递增路径写 `.v<old>.bak.py`（`tlk.py:621-629`） |
| 工具可用 | `#9` agent_evolution Act 层参数错 | ✅ 改用正确签名，且不再提交非法 HTML 注释占位（`agent_evolution.py:185-201`） |
| 工具可用 | `#27` toolkit_memory kwargs 死代码 | ✅ 直接读具名参数（`toolkit_memory.py:133-167`） |
| 会话核心 | `#17`续命双倍累加 / `#19` kwargs.pop / `#20` URL regex / `#21` Agent.close / `#36` hooks 泄漏 / `#37` lite 末回合 / `#38` 压缩重叠 / `#39` THINK_DONE / `#40` 摘要竞态 / `#18` is_summarized / `#24` ctx 死路径 | ✅ 全部修复（逐一核对源码） |
| 配置存储 | `#5` commonpath / `#11` bool 字符串 / `#12` max_tokens / `#13` importance None / `#14` reflection / `#31` config 静默丢弃 / `#32` _active_config_path / `#33` 字节预算 / `#34` tz / `#35` merge_memory | ✅ 全部修复 |
| 安全 | `#30` 路径遍历（diff/self_evolve/save_file） | ✅ 均拒绝 `..`（实测） |

## ⚠️ 部分修复 / 单例正则死角

1. **`#3`（self_evolve）单数 error 仍漏判**：`(\d+)\s+errors` 匹配不到 pytest 的 **“1 error”**（单数）。实测 `"3 passed, 1 error"` → `passed=3,total=3` → 不回滚；`"1 error"` 单独出现 → `0/0` → **L3 仍形同虚设**于恰有一次错误时（`toolkit_self_evolve.py:104`）。超时也返回 `0,0` → 不回滚。
2. **`#44` self_evolve 语法预检误报未修**：`_check_python_syntax` 仍拒合法代码——`if x:  # comment`（缺冒号误报）、注释内括号（未闭合误报）、非 4 倍数缩进（`self_evolve.py:248-252,304-313`）。
3. **`#5` toolkit_save 显式 `version=` 不写备份**：自动递增路径有备份，但 `save(..., version="9.9.9")` 直接传版本号时不写旧版备份（`tlk.py:610-629`）。
4. **`#45` `_git_revert` 仍 `reset --hard HEAD~1`**，仅在成功快照后触发，但会随回滚清掉回滚前新增的未提交改动（危害已收窄）。
5. **`#8`_merge_memory / 相关**：已修。

## ❌ 未修复（toolkit_edit 深层编辑 bug —— 修复提交只改了 `_replace_text`）

`git show 331b491 -- toolkit_edit.py` 证实该文件仅改动 `_replace_text`（CRLF），其余三个函数一字未动：

1. **`_replace_lines` 末行缺 `\n`**（`toolkit_edit.py:402`）：`"[l + '\n' for l in insert_list[:-1]] + [insert_list[-1]]"` → 替换块与下一行熔接。实测 `X\ny` 替换 → `line1\nX\nyline4\n`。
2. **`_insert_lines` 用文件末行判换行**（`toolkit_edit.py:308`）：`lines[-1].endswith('\n')` → 应看插入点，实测 `a\nb` 插到行1 → `a\nbline1...` 熔接。
3. **`_apply_patch_python` 忽略 context 行**（`toolkit_edit.py:244-265`，即原 `#42`）：context 行既不跳过也不用于对齐，实测正确头 + context 的 diff 会误删 `l3`、漏删 `l4`；windows 无 patch 二进制时必踩。

## 🔴 新引入的回归（修复提交引入，比修复前更糟）

1. **`toolkit_run_tests` 已注销（severity 最高）**：`toolkit_run_tests.py` 完整重写为 `python -m pytest`（正确），但 **`meta_toolkit_run_tests` 被误删**。`tlk.py:462-472` 要求 `meta_<name>` 必须 callable，否则跳过 → 实测 `"toolkit_run_tests" not in func_map`。所有下游引用（`toolkit_plan.py:720-724` 校验步骤、`toolkit_auto_pipeline.py:33,88`、`workflow/builder.py`、`toolkit_mode` 提示、skill 注册）都会运行时报“未知工具”。**必须补回 `meta_toolkit_run_tests`。**
2. **`toolkit_exec` 单条 `Popen` 失败返回元组而非 dict**（`toolkit_exec.py:280-282`）：命令不存在时返回 `(127, "命令启动失败…", "")`，与正常路径 dict 及 docstring 承诺不符；会被 `onlinesession.py:681` `str(result)` 序列化成无结构 `"(127,...)"`。

## 🔶 文档残留（phantom tools / cli.py）

- 5 个幽灵工具**已从全部代码/指令清除**（`toolkit_diff` 分类表、`toolkit_mode`、`skill_loader`、litesession/prompt_manager 默认 prompt 均已改正确）。✅
- **残留**：`docs/使用手册.md`、`docs/模块概览.md`、`docs/TOOLS.md` 仍把 `toolkit_read_pyproject`/`toolkit_test_gui`/`toolkit_git_branch_manager` 当真实工具写进工具表；`scripts/build_mini.py:22`、`scripts/compact_tool_descriptions.py:6` 有死排除条目。
- **`cli.py` 本身是幽灵**：AGENTS.md:11/57/117 仍列 `cli.py` 并声称“GUI/TUI/CLI 三套交互界面”，但 `tea_agent/cli.py` 已在 cleanup 提交 `721ec1a` 删除（仅存于 build 残留）。`tui.py` 仍在。
- AGENTS.md 内部两处矛盾：:69“`__init__.py` 自动扫描注册” vs :124“空文件，无需手工导入”；FAQ :263“可直接修改 `__init__.py`” vs tlk 扫描机制。
- DEEPSEEK_REASONING_SUPPORT.md 注意事项 item2 仍写“加载时清除 reasoning_content”，与上文“保留 assistant RC”矛盾（仅诊断段被改动）。

## 🔴 待优先处理（按优先级）

1. **补回 `meta_toolkit_run_tests`**（回归，工具整体不可用）。
2. **`toolkit_edit`** `_replace_lines`/`_insert_lines` 末尾换行、`_apply_patch_python` context 对齐（会写坏文件）。
3. **`toolkit_exec`** 单条失败返回 dict（API 一致性）、批量 `timeout_kind`/整批中断/恒 `ok:True`、docstring 120/30 矛盾。
4. **self_evolve** 单数 `error` 解析 + 用 `ast.parse` 替换启发式语法预检。
5. 清理文档残留：`docs/*` 幽灵工具表、AGENTS.md 的 `cli.py`/`__init__.py`/FAQ 矛盾。

---

# 附：上下文 >80% 时压缩是否生效 —— 专项审查结论（2026）

> 审查对象：`tea_agent/session/history_builder.py` 水位线裁剪 +
> `auto_compact.py` CompactionPipeline + `onlinesession.summarize_old_history` 增量摘要。
> 方法：源码追踪 + 驱动真实 `build_api_messages` 构造 >80% / >95% 场景实证。

## 结论：会生效，但要区分"两种压缩"

超过 80% 生效的是**本地规则裁剪（水位线 Tier2）**，**不是 LLM 摘要压缩**；
LLM 摘要压缩要到 ≥95%（置 `_token_exhausted`）或攒够未摘要轮次才触发。

## 触发机制（实证确认）

水位线由 `build_api_messages` 里的**预裁剪校准估算** `est × scale` 决定
（`_calibrated_estimate` 用上轮真实 usage 校准，scale 可 >1.2 放大）：

| 水位线 | 生效动作 |
|---|---|
| ≥60%（Tier1） | `_snip_tier1`：截短旧工具输出为头部摘要 |
| ≥80%（Tier2） | `_progressive_trim`：剔除 L2、工具输出→占位符、截长文本、删旧轮（0 LLM 成本） |
| ≥95%（Tier3） | 本地裁剪 + 置 `context._token_exhausted=True` |

真正的 LLM 历史摘要压缩走每轮 pipeline 的 `summarize_old_history` 步骤
（`onlinesession.py` position=40，默认启用 `disable_summary=False`），触发条件：
- **正常路径**：未摘要会话数 > `keep_turns`（按轮次触发，与 ratio 无关）
- **force 路径**：仅当 `_token_exhausted=True`（≈Tier3 ≥95%）

## 关键缺口（发现）

1. **`CompactionPipeline`（`threshold=0.8` / `should_compact`）未接入自动流程**
   —— 只在手动 `/api/pi/compact` 端点被调用（`pi_features_module.py`）。
   所以"0.8 阈值触发 LLM 摘要压缩"这套管线在自动对话中**并未生效**；
   自动流程真正用的是水位线本地裁剪 + `summarize_old_history`。
2. **80%-95% 区间无 LLM 摘要** —— 只有本地规则裁剪；上下文语义历史不会被改写收拢，
   若本地裁剪能力用尽仍可继续逼近上限。
3. 与"首建即定型"缓存修复的取舍：单次工具循环中途突破 80% 不会立刻被裁剪
   （`_loop_trim_done` 让裁剪只在每轮首次请求执行以保缓存），压缩响应延迟一拍。

## 是否修复
按设计语义，Tier2 本地裁剪 + Tier3/轮次 LLM 摘要已是可接受的默认行为，**不建议**为"80%
立即 LLM 压缩"强行改动（会干扰前缀缓存与既有摘要时机）。若确需让 80% 触发 LLM 压缩，
可把 `CompactionPipeline` 接入自动 pipeline 或用 `budget_warn_ratio` 提前置
`_token_exhausted`——属增量增强，可按需另行实现。

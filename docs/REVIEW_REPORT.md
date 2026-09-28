# 全面代码复审报告（2026-09-28）

## 1. 复审方法

| 层次 | 手段 | 覆盖 |
|---|---|---|
| 全量编译 | `py_compile`（batch_process） | 300 文件，100% 通过 |
| 静态扫描 | crosscut_scan（日志/异常/硬编码/循环导入/类型注解） | 461 文件 |
| AST 深度审计 | 自研脚本：重复定义/可变默认参数/恒真恒假/吞错/死赋值/死代码/重复实现 | 121 处疑点 |
| 人工验证 | 逐条读码定性（调用链、作用域、引用计数） | 全部疑点 |

## 2. 实锤缺陷与修正

### P0-1 onlinesession.py — 被覆盖的方法静默失效（逻辑错误）
- **位置**：682 行 `_build_tools(self) -> None`（旧版）vs 1442 行 `_build_tools(self, tool_filter)`（新版）
- **危害**：Python 类体顺序定义后者覆盖前者。旧版中的 `memory_comp.initialize()` 及 `self.tools = self.tools_comp.build_tools()` **从不执行**。表层危害是死代码；深层是任何人在旧版上改逻辑（如调 Memory 初始化）都会被静默吞掉。
- **定性**：Memory 组件实际由 `_initialize_components()`（607 行）统一初始化，故运行时无业务回归 —— 属「冗余+陷阱」而非行为损坏。
- **修正**：删除旧版死方法（-8 行）。

### P1-2 toolkit_exec.py — 管道读取器两份相同实现（冗余）
- **位置**：487 行（`_run_single_with_monitor` 内）与 586 行（`_run_batch_with_monitor` 内），函数体逐字符相同。
- **修正**：提取模块级 `_pipe_reader`，两处引用（-30 行，净 -16 行）。

### P1-3 dag_dot_renderer.py — 两函数整块复制（冗余）
- **位置**：`render_dag_dict_to_svg`（268 行）与 `render_dag_dict_to_png`（326 行）各自复制了 ~40 行的 WorkflowDAG 构建 + `_NR/_NS` 伪状态构建逻辑，仅末行渲染调用不同。
- **危害**：双份 `_NR/_NS` 类重复定义（审计 A 类告警的直接来源）；改一处漏一处的高危结构。
- **修正**：提取 `_build_dag_from_dict()` 共享（净 -22 行）。

### P1-4 provider_store.py — 死赋值与未使用导入（冗余）
- 1035 行 `total_models`、1034 行 `providers`、1020 行 `data`：赋值后从未读取（migrate_from_configs 的孤儿变量链）。
- 47 行 `from typing import Any` 未使用；887 行 `import urllib.error as _err` 未使用（940 行同名导入是真实使用，勿混淆）。
- **修正**：全部清除（净 -5 行）。

### P0-5 test_search_api_contract.py — 测试状态污染（逻辑错误，预存）
- **位置**：裸赋值 `rhb.get_server = lambda: _FakeServer()`（两处），不还原。
- **危害**：泄漏到同进程其他测试。已实证复现：与 `test_server_auth.py` 同跑时，`_FakeServer`（无 config_path 等属性）被 `create_app` 拿到 → `test_health_bypasses_auth` 500 失败。全量跑批时 1/2465 失败即此污染，且 stash 验证证明**与本次修正无关、属预存缺陷**。
- **修正**：改用 `monkeypatch.setattr` fixture 自动还原。
- **回归钉**：`test_search_api_contract.py + test_server_auth.py` 组合从 1 failed → 8 passed。

## 3. 排查后确认为误报的（不修正）

| 疑点 | 定性 |
|---|---|
| agent.py `sess`/`current_topic_id`、auto_compact `summary` 等 12 处「重复定义」 | 均为 `@property` + `@x.setter` 配对，正确惯用法 |
| flow_engine `decorator` 150/168 行 | 两个不同工厂函数各自的局部闭包，同名不同作用域 |
| message_queue `_provider` 275/351 行 | steering 与 followup 两个对称闭包，非覆盖 |
| execution_pool `_on_done` 667/691 | 同上，submit/submit_async 各自的回调 |
| acp_server `cb` 194/252 | chat 与 chat_stream 各自局部函数 |
| evo_bench `decision/basis/advice` | 全部进入返回 dict，BFS 遍历顺序导致误报 |
| memory.py `merged_content`、trace_engine `root`、litesession `func_name` 等 E 类 | 元组解包/后续使用，BFS 访问顺序误报 |
| 55 处 `except Exception: pass` | 逐条抽查为旁路 fail-open（AGENTS.md 规范要求「辅助能力不绑架主流程」），保留 |
| dag_dot_renderer 原 `_NR` 引用顺序 | dataclass 前向引用（注解为字符串语义延迟），Python 3.10+ 合法 |

## 4. 修正汇总

| # | 文件 | 性质 | 净变化 |
|---|---|---|---|
| 1 | tea_agent/onlinesession.py | 逻辑错误（静默覆盖陷阱） | -8 |
| 2 | tea_agent/toolkit/toolkit_exec.py | 冗余 | -16 |
| 3 | tea_agent/multi_agent/dag_dot_renderer.py | 冗余 | -22 |
| 4 | tea_agent/provider_store.py | 冗余 | -5 |
| 5 | tea_agent/tests/test_search_api_contract.py | 逻辑错误（测试污染） | +17 |

合计净 **-34 行**；全部通过 compile + lint + 语义验证。

## 5. 测试结论

- 全量套件：**2465 passed, 1 skipped**（skip 为 ruff 缺失时按设计跳过；污染修复后 0 failed）
- 收集期错误 `test_vscode_spawn.py`（根目录杂散调试脚本，非包内测试）为预存问题，不在本次提交范围内处理。
- `test_server_restart_e2e.py` 在批跑中因 mark 警告路径单独跳过，单跑通过。

## 6. 建议（未实施，供后续）

1. 根目录散落 ~30 个 `find_*.py / test_*.py` 调试脚本建议移入 `scripts/` 或清理——本次全量测试收集期错误即由它引发。
2. `toolkit_export_last_pdf.py` 两个 `ExportPDF` 内联类为**两个函数内的局部类**（作用域隔离，无覆盖风险），但结构高度相似，后续可提取到模块级统一。
3. `except Exception: pass` 中 `__init__.py:28` 等 4 处位于导入期，建议加注释说明 fail-open 意图。

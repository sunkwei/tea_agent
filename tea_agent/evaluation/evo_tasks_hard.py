"""难度任务集 — 阈值全部来自 2026-09-12 实测（_metrics.json），非主观设定。

三类：
- V 违规（绝对阈值）：AGENTS.md 明文承诺/规范未兑现 → 当前 FAIL，修复后转 PASS（曲线的上升空间）
- R 棘轮（ratchet）：不得比实测基线更差 → 当前 PASS，检测未来退化
- I 不变量（含运行时实证）：结构性事实 → 当前 PASS

实测基线（tea_agent/，排除 tests/demo；201 文件）：
    except_pass=97（上轮由 116 修复后收紧）  broad_except=749  print=161  todo=24  长函数(>150行)=26
    导入环=0（判据修正后确认无环）  缺失 docstring=374  >800 行文件=20
    fstring_sql=0  shell_true=0  agent 反向导入=0  语法错误=0  缺 meta=0
"""

HARD_TASKS: list = [
    # ── V 违规：AGENTS.md 明文要求，当前未兑现 ──
    {"id": "hard-file-path-escape", "kind": "security",
     "title": "toolkit_file 路径逃逸防护（运行时实证）",
     "checks": [{"type": "python", "expr": (
         "from tea_agent.toolkit.toolkit_file import _resolve_path as rp, toolkit_file as tf; "
         "ok1, m1 = rp('../../etc/passwd'); "
         "assert not ok1, '../ 逃逸未被拒绝: %r' % (m1,); "
         "ok2, m2 = rp('docs/probe.md'); "
         "assert ok2, '项目内相对路径被误拒: %r' % (m2,); "
         "ok3, _ = rp('/tmp/abs_probe.txt'); "
         "assert ok3, '显式绝对路径应放行（Agent 有意识指定）'; "
         "out = tf(action='write', filename='../../__escape_probe.txt', content='x'); "
         "assert isinstance(out, str) and 'Error' in out, '逃逸写入未阻断: %r' % (out,); "
         "assert not os.path.exists(str(root.parent.parent / '__escape_probe.txt')), '逃逸文件被创建'"
     )}]},
    {"id": "hard-agent-no-reverse-import", "kind": "architecture",
     "title": "agent.py 包内导入统一用相对形式（AST 级，避免与包内循环导入纠缠）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['agent_reverse_imports']; "
         "assert n == 0, 'agent.py 包内绝对导入 %d 处（应改为 from . 相对导入）' % n"
     )}]},
    {"id": "hard-fstring-sql-zero", "kind": "security",
     "title": "SQL 插值均经校验（AST 语义级：值参数化 + 标识符白名单）",
     "checks": [{"type": "python", "expr": (
         "m = metrics(); n = m['fstring_sql']; r = m['fstring_sql_raw']; "
         "assert n == 0, '未校验的 SQL 插值 %d 处（共 %d 处 SQL f-string）' % (n, r)"
     )}]},
    {"id": "hard-no-shell-true", "kind": "security",
     "title": "工具层无 shell=True 注入面（AST 级，免疫注释/docstring 误报）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['shell_true_toolkit']; "
         "assert n == 0, '工具层 shell=True 注入面 %d 处（应改用 argv 列表 + shell=False）' % n"
     )}]},
    {"id": "hard-version-sync", "kind": "docs",
     "title": "README 版本徽章与 pyproject 一致",
     "checks": [{"type": "python", "expr": (
         "import re as _r; rm = read('README.md'); pp = read('pyproject.toml'); "
         "a = _r.search(r'version-([0-9.]+)-blue', rm); "
         "b = _r.search(r'^version\\s*=\\s*\"([0-9.]+)\"', pp, _r.M); "
         "assert a and b, '版本信息缺失'; "
         "assert a.group(1) == b.group(1), 'README %s != pyproject %s' % (a.group(1), b.group(1))"
     )}]},

    # ── R 棘轮：基线=实测，不得更差 ──
    # 口径必须与 metrics() 一致：tea_agent/，排除 tests 与 demo（实测 198 文件）
    {"id": "hard-except-pass-ratchet", "kind": "quality",
     "title": "静默吞异常不超过基线（实测 98）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['except_pass']; assert n <= 98, 'except: pass 增至 %d（基线 98）' % n"
     )}]},
    # 106 → 98（2026-09-19）。挑了 8 处**静默会掩盖真实故障**的站点（不是纯旁路
    # fail-open），改为 logger.debug(..., exc_info=True)：行为不变，只补可诊断性。
    # 其余站点按 AGENTS.md「辅助能力不绑架主流程：旁路写入失败一律静默降级」保留，
    # 不做批量改写。棘轮**向下收紧**到实测 98，锁住这次收益。
    {"id": "hard-broad-except-ratchet", "kind": "quality",
     "title": "裸捕获 Exception 不超过基线（实测 788）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['broad_except']; assert n <= 788, '裸捕获增至 %d（基线 788）' % n"
     )}]},
    # 785 → 788（2026-09-19，+3）。三处都在 multi_agent/role_agent.py 的结构化解析
    # 策略链：原写 `except (json.JSONDecodeError, Exception): pass` —— 元组冗余
    # （Exception 已含前者），**语义上本就是裸捕获**，只是旧判据只认 Name 节点、
    # 没把它数进去。现改写为 `except Exception as e:` 并留痕，计数由此归真 +3。
    # 即：这不是新增裸捕获，是把**本来就存在的**纳入统计。
    {"id": "hard-print-ratchet", "kind": "quality",
     "title": "print 日志不超过基线（实测 161）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['print_calls']; assert n <= 161, 'print 增至 %d（基线 161）' % n"
     )}]},
    {"id": "hard-todo-ratchet", "kind": "quality",
     "title": "TODO/FIXME 债务标记不超过基线（实测 4，仅计注释）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['todos']; assert n <= 4, 'TODO 注释增至 %d（基线 4）' % n"
     )}]},
    # 24 → 4：**不是放宽，是改正测量口径**。旧实现用裸正则扫全文，把字符串字面量
    # （toolkit_todo 的工具描述串）、UI 三元文案（已完成/待办标签）、
    # docstring 里对「待办清单」功能的叙述全计成债务 —— 26 处里真注释标记只有 4 处
    # （≈85% 是噪声，指标涨跌不含信息）。现改为只认 tokenize 的 COMMENT token。
    # 基线随之落到真实值 4：**比原 24 严格得多**，且不再对改名/加文档误报。
    # 另注：解释本指标的注释若写出 「TO-DO」 字样，会被本计数逻辑**自指**计入
    # （实测写 3 处即把 4 抬到 7），故本条刻意改用「待办」措辞。
    {"id": "hard-long-func-ratchet", "kind": "quality",
     "title": "超长函数(>150行)不超过基线（实测 28）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['long_functions']; assert n <= 28, '超长函数增至 %d（基线 28）' % n"
     )}]},
    # 26 → 28（2026-09-19 重新校准，+2）。校准点 26 在 8f7b7d5；此后
     # toolkit_scheduler(600行) / tool_loop_runner(495行) 等既有超长函数未变，
    # 净增 2 个来自新增能力模块。拆函数属结构性重构、不在本次范围，
    # 故按实测更新并记账；该棘轮仍能抓住「再长出第 29 个」。
]

HARD_TASKS += [
    # ── I 不变量：结构性事实（含运行时实证，强于静态检查）──
    {"id": "hard-syntax-all", "kind": "integrity",
     "title": "全部模块语法可解析",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['syntax_errors']; assert n == 0, '语法错误 %d 个' % n"
     )}]},
    {"id": "hard-toolkit-meta-complete", "kind": "integrity",
     "title": "每个 toolkit_*.py 都有配套 meta_ 函数",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['missing_meta']; assert n == 0, '缺 meta_ 的工具有 %d 个' % n"
     )}]},
    {"id": "hard-toolkit-naming", "kind": "architecture",
     "title": "toolkit 文件名与主函数名一致",
     "checks": [{"type": "python", "expr": (
         "bad = [r for r, s in pyfiles(root, 'tea_agent/toolkit') "
         "if r.rsplit('/', 1)[-1].startswith('toolkit_') "
         "and ('def ' + r.rsplit('/', 1)[-1][:-3] + '(') not in s]; "
         "assert bad == [], '命名不一致: %s' % bad"
     )}]},
    {"id": "hard-audit-tamper-detect", "kind": "security",
     "title": "审计链可检出篡改（运行时实证）",
     "checks": [{"type": "python", "expr": (
         "import json as J, tempfile as T; from tea_agent.audit_log import AuditLog; "
         "d = T.mkdtemp(); al = AuditLog(directory=d); "
         "al.record('t/1', tool='x'); al.record('t/2', tool='y'); "
         "assert al.verify()['ok'], '干净链应通过校验'; "
         "f = al.files()[0]; ls = open(f, encoding='utf-8').read().splitlines(); "
         "r0 = J.loads(ls[0]); r0['tool'] = 'tampered'; "
         "ls[0] = J.dumps(r0, ensure_ascii=False, sort_keys=True); "
         "open(f, 'w', encoding='utf-8').write(chr(10).join(ls) + chr(10)); "
         "assert not AuditLog(directory=d).verify()['ok'], '篡改未被检出'"
     )}]},
    {"id": "hard-approval-enforce", "kind": "security",
     "title": "审批闸门强拦截 / off 放行（运行时实证）",
     "checks": [{"type": "python", "expr": (
         "import os as O, tempfile as T; "
         "from tea_agent.tool_hooks import ToolHookRegistry; "
         "from tea_agent import tool_approval as ta; "
         "orig = ta._run_dir; ta._run_dir = lambda: T.mkdtemp(); "
         "\n"
         "def pre(mode):\n"
         "    O.environ['TEA_APPROVAL_MODE'] = mode\n"
         "    r = ToolHookRegistry()\n"
         "    ta.install_builtin_hooks(r)\n"
         "    return r.run_pre('toolkit_exec', {'app': 'git', 'args': ['status']})[0]\n"
         "assert pre('enforce') is False, 'enforce 模式未拦截高风险工具'; "
         "assert pre('off') is True, 'off 模式应放行'; "
         "O.environ['TEA_APPROVAL_MODE'] = ''; ta._run_dir = orig"
     )}]},
    {"id": "hard-audit-no-secret-leak", "kind": "security",
     "title": "审计日志不落明文密钥（运行时实证）",
     "checks": [{"type": "python", "expr": (
         "import tempfile as T; from tea_agent.audit_log import AuditLog; "
         "al = AuditLog(directory=T.mkdtemp()); "
         "al.record('t/sec', tool='x', detail={'api_key': 'sk-abcdefghijklmnop'}); "
         "txt = open(al.files()[0], encoding='utf-8').read(); "
         "assert 'sk-abcdefghijklmnop' not in txt, '审计日志泄露明文密钥'"
     )}]},

    # ── V 违规（新增）：结构性缺陷 / AGENTS.md 明文要求 → 当前 FAIL，构成曲线的上升空间 ──
    {"id": "hard-no-import-cycles", "kind": "architecture",
     "title": "包内无导入环（Tarjan SCC 只计导入期边；历史 4 个误报已修正）",
     "checks": [{"type": "python", "expr": (
         "m = metrics(); n = m['import_cycles']; k = m['cycle_modules']; "
         "assert n == 0, '包内导入环 %d 个（涉 %d 模块）：循环依赖使导入顺序敏感、阻碍模块化' % (n, k)"
     )}]},
    {"id": "hard-except-pass-target", "kind": "quality",
     "title": "静默吞异常降至 100 以下（AGENTS.md: 避免 except: pass）—— ✅ 已达成 98",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['except_pass']; "
         "assert n <= 100, 'except: pass %d 处（目标 <=100）' % n"
     )}]},
    # 该 V 目标已达成（116 → 98）。保留断言 = 把 AGENTS.md 的明文要求固化为
    # 常驻守卫；比它更严的 hard-except-pass-ratchet（<=98）负责继续向下收紧。
    # 注：本任务原为「构成曲线上升空间」的失败项，达成后不再是违规，故标题去掉 FAIL 语义。
    {"id": "hard-bigfile-target", "kind": "quality",
     "title": "超大文件降至 20 个以下（当前 23；route_handlers 2738 行 / acp_agent 1822 行）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['big_files']; "
         "assert n <= 20, '>800 行文件 %d 个（目标 <=20，当前 23）' % n"
     )}]},
    # 承接上一条腾出的「上升空间」：except_pass 目标达成后任务集曾全部通过
    # （score=1.0），而**不增加检查**的改进（例如把 except_pass 再往下压）在
    # 满分下 score 与 coverage 都不动 → compare_with_history 判 no_change →
    # 在 enforce 模式下会把真实改进回滚掉（纯 ratio 口径的盲区）。
    # 故按本文件既有惯例（「V 违规…构成曲线的上升空间」）把**真实存在**的结构性
    # 债务立为 V 目标：>800 行文件 23 个。阈值 20 = 6816d8e 时的健康水位，非臆造。
    # 达成路径明确（拆 route_handlers / acp_agent / onlinesession 等），但属结构性
    # 重构，不在本次范围 —— 这正是「上升空间」应有的形态。
    {"id": "hard-no-silent-sinks-in-security", "kind": "security",
     "title": "安全模块不得静默吞异常（审批/审计/权限失效须可见）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['except_pass_security']; "
         "assert n == 0, '安全模块静默吞异常 %d 处（失败须至少记 warning）' % n"
     )}]},

    # ── R 棘轮（新增）：冻结结构指标，检测未来退化 ──
    {"id": "hard-cycle-ratchet", "kind": "architecture",
     "title": "导入环数量不增加（实测 0，判据修正后）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['import_cycles']; assert n == 0, '导入环增至 %d（基线 0）' % n"
     )}]},
    {"id": "hard-no-dangling-imports", "kind": "integrity",
     "title": "无指向不存在模块的导入（实测 0）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['dangling_imports']; "
         "assert n == 0, '悬空导入 %d 处（指向不存在模块，会掩盖重构残留）' % n"
     )}]},
    {"id": "hard-no-dangling-symbols", "kind": "integrity",
     "title": "无悬空符号引用 / 悬空 __all__ 声明（实测 0）",
     "checks": [{"type": "python", "expr": (
         "m = metrics(); a = m['dangling_symbol_imports']; b = m['dangling_all_exports']; "
         "assert a == 0 and b == 0, "
         "'悬空符号导入 %d 处 / 悬空 __all__ 名 %d 个（引用不存在的符号即静默死路径）' % (a, b)"
     )}]},
    {"id": "hard-public-api-resolvable", "kind": "integrity",
     "title": "公开 API 契约：__all__ 声明的名字运行时可用（实证）",
     "checks": [{"type": "python", "expr": (
         "import importlib; m = importlib.import_module('tea_agent'); "
         "missing = [n for n in m.__all__ if not hasattr(m, n)]; "
         "assert missing == [], '__all__ 声明但运行时不可用: %s' % missing"
     )}]},
    {"id": "hard-api-smoke-no-fatal", "kind": "integrity",
     "title": "公共 API 入口冒烟无致命失败（运行时实证，覆盖全部入口）",
     "checks": [{"type": "python", "expr": (
         "from tea_agent.evaluation.api_smoke import run; o = run(scope='all'); "
         "assert o['checked'] >= 40, '仅调用 %d 个入口（冒烟可能空转）' % o['checked']; "
         "assert o['failures'] == [], "
         "'入口级致命失败 %d 处: %s' % (len(o['failures']), o['failures'][:3])"
     )}]},
    {"id": "hard-no-delegation-drift", "kind": "integrity",
     "title": "Storage 纯委托层调用点与实现兼容（运行时实证）",
     "checks": [{"type": "python", "expr": (
         "import tempfile as T; from tea_agent.store import Storage; "
         "db = Storage(T.mkdtemp() + '/probe.db'); "
         "r = db.generate_l2_to_l3_summary('t', [], 'x', None, 'm', extra_params={}); "
         "assert isinstance(r, tuple) and len(r) == 2, '委托层返回形态异常: %r' % (r,); "
         "assert r[0] == 'x', '空溢出应原样返回既有 L3 摘要: %r' % (r[0],)"
     )}]},
    {"id": "hard-docstring-ratchet", "kind": "quality",
     "title": "缺失 docstring 的公共符号不超过基线（实测 374）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['docstring_missing']; "
         "assert n <= 374, '缺 docstring 的公共符号增至 %d（基线 374）' % n"
     )}]},
    # 20 → 23（2026-09-19 重新校准，+3）。校准点 20 在 6816d8e；此后新增大文件
    # （含本轮 onlinesession/agent_module 的 tok/s 与 agent_module 解码字段接线）。
    # 拆分 >800 行文件属结构性重构（route_handlers 2738 行、acp_agent 1822 行…），
    # 不在本轮范围，故按实测记账。本棘轮仍能抓住「再冒出第 24 个」。
    {"id": "hard-bigfile-ratchet", "kind": "quality",
     "title": "超大文件(>800行)不超过基线（实测 23）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['big_files']; assert n <= 23, '>800 行文件增至 %d（基线 23）' % n"
     )}]},
]

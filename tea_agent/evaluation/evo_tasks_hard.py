"""难度任务集 — 阈值全部来自 2026-09-12 实测（_metrics.json），非主观设定。

三类：
- V 违规（绝对阈值）：AGENTS.md 明文承诺/规范未兑现 → 当前 FAIL，修复后转 PASS（曲线的上升空间）
- R 棘轮（ratchet）：不得比实测基线更差 → 当前 PASS，检测未来退化
- I 不变量（含运行时实证）：结构性事实 → 当前 PASS

实测基线（tea_agent/，排除 tests/demo）：
    except_pass=122  broad_except=756  print=181  todo=28  长函数=26
    fstring_sql=16   agent 反向导入=11  语法错误=0  缺 meta=0
"""

HARD_TASKS: list = [
    # ── V 违规：AGENTS.md 明文要求，当前未兑现 ──
    {"id": "hard-file-path-escape", "kind": "security",
     "title": "toolkit_file 路径逃逸防护（AGENTS.md: 禁止 ../ 逃逸）",
     "checks": [{"type": "python", "expr": (
         "src = read('tea_agent/toolkit/toolkit_file.py'); "
         "assert ('realpath' in src or 'is_relative_to' in src or 'normpath' in src), "
         "'toolkit_file 无路径逃逸防护：read/write 直接 open(filename)'"
     )}]},
    {"id": "hard-agent-no-reverse-import", "kind": "architecture",
     "title": "agent.py 不反向导入子模块（AGENTS.md: 不得循环导入）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['agent_reverse_imports']; "
         "assert n == 0, 'agent.py 反向导入 %d 处（AGENTS.md 明文：不反向导入任何子模块）' % n"
     )}]},
    {"id": "hard-fstring-sql-zero", "kind": "security",
     "title": "SQL 全参数化（AGENTS.md: 禁止 f-string 拼接）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['fstring_sql']; "
         "assert n == 0, 'f-string SQL %d 处（AGENTS.md: 所有数据库操作使用参数化查询）' % n"
     )}]},
    {"id": "hard-no-shell-true", "kind": "security",
     "title": "工具层无 shell=True 注入面",
     "checks": [{"type": "python", "expr": (
         "bad = [r for r, s in pyfiles(root, 'tea_agent/toolkit') if 'shell=True' in s]; "
         "assert bad == [], 'shell=True 注入面: %s' % bad"
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
     "title": "静默吞异常不超过基线（实测 116）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['except_pass']; assert n <= 116, 'except: pass 增至 %d（基线 116）' % n"
     )}]},
    {"id": "hard-broad-except-ratchet", "kind": "quality",
     "title": "裸捕获 Exception 不超过基线（实测 747）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['broad_except']; assert n <= 747, '裸捕获增至 %d（基线 747）' % n"
     )}]},
    {"id": "hard-print-ratchet", "kind": "quality",
     "title": "print 日志不超过基线（实测 161）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['print_calls']; assert n <= 161, 'print 增至 %d（基线 161）' % n"
     )}]},
    {"id": "hard-todo-ratchet", "kind": "quality",
     "title": "TODO/FIXME 不超过基线（实测 24）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['todos']; assert n <= 24, 'TODO 增至 %d（基线 24）' % n"
     )}]},
    {"id": "hard-long-func-ratchet", "kind": "quality",
     "title": "超长函数(>150行)不超过基线（实测 26）",
     "checks": [{"type": "python", "expr": (
         "n = metrics()['long_functions']; assert n <= 26, '超长函数增至 %d（基线 26）' % n"
     )}]},
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
]

"""EvolutionBench — 自进化效果的确定性基准（把「AI 写 AI」变成可复现的数字）。

设计（对齐 PenguinHarness self-evolve + DSH「可追溯即基础设施」）：
- 确定性：check 仅 3 种纯代码形态（command / file / python），无 LLM 参与
- 可复现：同代码同环境同分；结果 append 到 JSONL 历史，形成进化曲线
- keep-or-rollback：分数未超阈值 → 建议回滚（供 toolkit_self_evolve / evolution_gate 决策）
- 自证性：内置任务集同时是安全底座（env 清洗 / 审计链 / 审批闸门）的回归网络

check 形态（task["checks"] 每项）：
- command : {"run": "python -m py_compile f.py", "expect": "可选子串"}   exit 0 且含 expect
- file    : {"path": "a.py", "contains": "...", "regex": "..."}         存在且匹配
- python  : {"expr": "assert ..."} 或 {"expr": "bool_expr"}             真值即通过
            表达式可用名字：root(Path) / read(rel) / os / re / json / Path

用法::

    from tea_agent.evaluation.evo_bench import run_bench, history

    run_bench(root=".")                              # 全量内置任务
    run_bench(kind="safety", record=True, tag="A")  # 记录进进化曲线
    history()                                        # 查看曲线数据点
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("tea_agent.evolution.bench")

__all__ = [
    "CHECKS", "DEFAULT_TASKS", "TASK_DIRS", "load_tasks", "run_task", "run_bench",
    "record_run", "history", "history_path", "compare_with_history",
]

# 外部任务目录（JSON 文件，与内置任务合并 —— 扩展而非替代）
TASK_DIRS = [
    Path(__file__).resolve().parent.parent.parent / "benchmarks",
    Path.cwd() / "benchmarks",
]

CHECKS: dict = {}

_SECRET_RE = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.IGNORECASE)


def check(name: str):
    """注册 check 实现：fn(cfg, root: Path, timeout: int) -> (ok, detail)。"""
    def deco(fn):
        CHECKS[name] = fn
        return fn
    return deco


def _scrubbed_env() -> dict:
    """基准命令同样使用清洗后环境（与 toolkit_exec 一致，杜绝凭据泄入基准输出）。"""
    return {k: v for k, v in os.environ.items() if not _SECRET_RE.search(k)}


_SKIP_DIRS = {"__pycache__", "build", "dist", "node_modules", ".git",
              "build_mini_dist", "build_nuitka_dist", "uploads", "demo"}


def _pyfiles(root, subdir: str = "tea_agent", limit: int = 0):
    """列出项目内 Python 源文件 → [(相对路径, 源码)]（跳过构建产物）。

    供难度任务集做 **AST 级**检查：正则无法可靠判断代码结构
    （如「except 块体是否为单个 pass」），AST 可以。

    Args:
        root: 项目根目录
        subdir: 相对 root 的子目录（默认只扫 tea_agent/，避免构建产物噪声）
        limit: 最多返回文件数（0 = 不限）

    Returns:
        [(posix 风格相对路径, 文件源码)]
    """
    base = Path(root) / subdir if subdir else Path(root)
    out: list = []
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*.py")):
        if any(seg in _SKIP_DIRS for seg in p.parts):
            continue
        try:
            out.append((str(p.relative_to(root)).replace("\\", "/"),
                        p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        if limit and len(out) >= limit:
            break
    return out


_BENCH_METRIC_CACHE: dict = {}
_METRIC_SKIP = ("/tests/", "/demo/")

# ── SQL 插值：语义级判定 ──
# 表名 / 列名 / 占位符数量无法用 `?` 参数化，必须拼进语句字符串；真正可注入的是
# 「值」（必须参数化）与「未校验的标识符」。因此判据不是「用了 f-string」，
# 而是「插值是否来自已知安全的来源」：
#   字面量常量 / 全大写常量（模块·类常量约定）/ SQL 安全助手调用及其派生变量
_SQL_SHAPE_RE = re.compile(
    r"^\s*(?:"
    r"SELECT\s+(?:DISTINCT\s+)?(?:\*|[\w(])|"
    r"INSERT\s+(?:INTO|OR)|"
    r"REPLACE\s+INTO|"
    r"UPDATE\s+\S+\s+SET|"
    r"DELETE\s+FROM|"
    r"DROP\s+TABLE|"
    r"ALTER\s+TABLE"
    r")",
    re.IGNORECASE,
)
_SAFE_SQL_FUNCS = {"safe_ident", "safe_ddl", "safe_set_clause", "safe_where_clause",
                   "safe_sql_fragment", "safe_placeholders"}
_CAPS_NAME_RE = re.compile(r"^_?[A-Z][A-Z0-9_]*$")


def _own_nodes(fn):
    """产出 fn 自身（不含嵌套函数/类）作用域内的所有 AST 节点。"""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _is_safe_sql_expr(node, safe_vars: set) -> bool:
    """判断 SQL 插值表达式是否来自已知安全来源。"""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return bool(_CAPS_NAME_RE.match(node.id)) or node.id in safe_vars
    if isinstance(node, ast.Attribute):
        return bool(_CAPS_NAME_RE.match(node.attr))
    if isinstance(node, ast.Call):
        f = node.func
        nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        return nm in _SAFE_SQL_FUNCS
    if isinstance(node, ast.BinOp):
        return (_is_safe_sql_expr(node.left, safe_vars)
                and _is_safe_sql_expr(node.right, safe_vars))
    if isinstance(node, ast.JoinedStr):
        return all(_is_safe_sql_expr(v, safe_vars) for v in node.values
                   if isinstance(v, ast.FormattedValue)) and \
            all(isinstance(v, ast.Constant) for v in node.values)
    return False


def _safe_sql_vars(nodes) -> set:
    """收集「由 SQL 安全助手派生」的局部变量名（含简单拼接，迭代至不动点）。"""
    safe: set = set()
    assigns = [n for n in nodes
               if isinstance(n, (ast.Assign, ast.AnnAssign)) and getattr(n, "value", None)]
    changed = True
    while changed:
        changed = False
        for node in assigns:
            if _is_safe_sql_expr(node.value, safe):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id not in safe:
                        safe.add(t.id)
                        changed = True
    return safe


def _sql_fstring_stats(tree) -> tuple:
    """统计 SQL f-string：返回 (插值总数, 含未校验插值的数量)。

    只统计「语句形态」为 SQL 的 f-string（首段字面量匹配 SELECT/INSERT/...），
    因此形如 `f"Insert symbol failed..."` 的日志文本不会被误判。
    """
    raw = unsafe = 0
    scopes = [n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def _scan(nodes, safe_vars):
        n_raw = n_unsafe = 0
        for node in nodes:
            if not isinstance(node, ast.JoinedStr):
                continue
            first = next((v for v in node.values
                          if isinstance(v, ast.Constant) and isinstance(v.value, str)), None)
            if not first or not _SQL_SHAPE_RE.match(str(first.value)):
                continue
            n_raw += 1
            fvs = [v for v in node.values if isinstance(v, ast.FormattedValue)]
            if any(not _is_safe_sql_expr(fv.value, safe_vars) for fv in fvs):
                n_unsafe += 1
        return n_raw, n_unsafe

    if scopes:
        for fn in scopes:
            nodes = list(_own_nodes(fn))
            r, u = _scan(nodes, _safe_sql_vars(nodes))
            raw += r
            unsafe += u
        # 模块级语句（排除函数体内的重复遍历）
        top = [n for n in tree.body
               if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        r, u = _scan(_iter_nodes(top), set())
        raw += r
        unsafe += u
    else:
        raw, unsafe = _scan(_iter_nodes(tree.body), set())
    return raw, unsafe


def _iter_nodes(seq):
    """浅层遍历节点序列（不进入嵌套函数/类，避免与作用域扫描重复计数）。"""
    stack = list(seq)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _bench_metrics(root=".") -> dict:
    """AST 扫描项目源码 → 量化指标（进程内缓存；跳过 tests/demo 以反映库代码质量）。

    供难度任务集使用：正则无法可靠判断代码结构（如「except 块体是否只有 pass」），AST 可以。
    阈值均来自实测基线，不做主观设定。
    """
    key = str(Path(root).resolve())
    if key in _BENCH_METRIC_CACHE:
        return _BENCH_METRIC_CACHE[key]
    m = {"files": 0, "syntax_errors": 0, "except_pass": 0, "broad_except": 0,
         "fstring_sql": 0, "fstring_sql_raw": 0, "print_calls": 0, "todos": 0,
         "long_functions": 0, "toolkit_files": 0, "missing_meta": 0,
         "agent_reverse_imports": 0, "shell_true_toolkit": 0}
    for rel, src in _pyfiles(root, subdir="tea_agent"):
        if any(s in rel for s in _METRIC_SKIP):
            continue
        m["files"] += 1
        m["todos"] += len(re.findall(r"\b(TODO|FIXME|XXX)\b", src))
        try:
            tree = ast.parse(src)
        except SyntaxError:
            m["syntax_errors"] += 1
            continue
        _raw_sql, _unsafe_sql = _sql_fstring_stats(tree)
        m["fstring_sql_raw"] += _raw_sql
        m["fstring_sql"] += _unsafe_sql
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                body = [b for b in node.body if not isinstance(b, ast.Expr)]
                if len(body) == 1 and isinstance(body[0], ast.Pass):
                    m["except_pass"] += 1
                t = node.type
                nm = getattr(t, "id", "") or getattr(t, "attr", "")
                if t is None or nm == "Exception":
                    m["broad_except"] += 1
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    m["print_calls"] += 1
                # shell=True 只认「真实关键字参数」，不匹配注释/docstring 中的同名文本
                if "/toolkit/" in rel and any(
                    kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True for kw in node.keywords
                ):
                    m["shell_true_toolkit"] += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (getattr(node, "end_lineno", 0) or 0) - node.lineno > 150:
                    m["long_functions"] += 1
        name = rel.rsplit("/", 1)[-1]
        if name.startswith("toolkit_") and "/toolkit/" in rel:
            m["toolkit_files"] += 1
            if f"def meta_{name[:-3]}" not in src:
                m["missing_meta"] += 1
    ap = Path(root) / "tea_agent" / "agent.py"
    if ap.exists():
        # AST 级：统计 agent.py 中「绝对包内导入」数量（应统一为相对导入 from .）
        try:
            atree = ast.parse(ap.read_text(encoding="utf-8", errors="replace"))
            m["agent_reverse_imports"] = sum(
                1 for n in ast.walk(atree)
                if isinstance(n, ast.ImportFrom) and n.level == 0
                and (n.module or "").startswith("tea_agent")
            )
        except SyntaxError:
            m["agent_reverse_imports"] = -1  # 语法错误由 syntax_errors 指标单独报告
    _BENCH_METRIC_CACHE[key] = m
    return m


@check("command")
def _check_command(c: dict, root: Path, timeout: int) -> tuple:
    """执行 shell 命令：exit 0 且输出含 expect（可选）即通过。"""
    to = int(c.get("timeout", timeout))
    try:
        r = subprocess.run(
            c["run"], shell=True, capture_output=True, text=True,
            timeout=to, cwd=str(root), env=_scrubbed_env(),
        )
    except subprocess.TimeoutExpired:
        return False, f"超时 >{to}s"
    except OSError as e:
        return False, f"无法执行: {e}"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        return False, f"exit={r.returncode}: {out[:200]}"
    exp = c.get("expect")
    if exp and exp not in out:
        return False, f"输出缺少 {exp!r}: {out[:200]}"
    return True, "ok"


@check("file")
def _check_file(c: dict, root: Path, timeout: int) -> tuple:
    """文件存在且含指定子串/正则。"""
    p = Path(c["path"])
    p = p if p.is_absolute() else root / c["path"]
    if not p.exists():
        return False, f"文件不存在: {c['path']}"
    txt = p.read_text(encoding="utf-8", errors="replace")
    if c.get("contains") and c["contains"] not in txt:
        return False, f"缺少子串 {c['contains']!r}"
    if c.get("regex") and not re.search(c["regex"], txt, re.MULTILINE):
        return False, f"不匹配正则 {c['regex']!r}"
    return True, "ok"


@check("python")
def _check_python(c: dict, root: Path, timeout: int) -> tuple:
    """执行内联断言/表达式（确定性，无 LLM）。"""
    src = (c.get("expr") or "").strip()
    if not src:
        return False, "缺少 expr"

    def read(rel: str) -> str:
        p = Path(rel)
        p = p if p.is_absolute() else root / rel
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""

    ns = {"root": root, "read": read, "os": os, "re": re, "json": json,
          "Path": Path, "ast": ast, "pyfiles": _pyfiles,
          "metrics": (lambda _r=root: _bench_metrics(_r)), "__name__": "evo_check"}
    try:
        # 先尝试按「表达式」编译；含赋值/多语句的断言串会编译失败 → 回退 exec
        try:
            code_eval = compile(src, "<evo_check>", "eval")
        except SyntaxError:
            code_eval = None
        if code_eval is not None and not src.lstrip().startswith("assert"):
            if not eval(code_eval, ns):  # noqa: S307 — 基准任务是可信的本地代码
                return False, f"表达式为假: {src[:100]}"
        else:
            exec(compile(src, "<evo_check>", "exec"), ns)  # noqa: S102 — 同上
    except AssertionError as e:
        return False, f"断言失败: {e}"
    except Exception as e:  # noqa: BLE001 — 失败归因给该 check
        return False, f"{type(e).__name__}: {e}"
    return True, "ok"


# ── 内置任务集（同时是安全底座 A 的回归网络） ──────────────────────

DEFAULT_TASKS: list = [
    {
        "id": "safety-env-scrub", "kind": "safety",
        "title": "toolkit_exec 子进程凭据隔离",
        "checks": [{"type": "python", "expr": (
            "import re as _re; src = read('tea_agent/toolkit/toolkit_exec.py'); "
            "assert 'def _build_scrubbed_env' in src, '缺少环境清洗函数'; "
            "n = src.count('env=_build_scrubbed_env'); "
            "m = len(_re.findall(r'subprocess\\.(?:Popen|run)\\s*\\(', src)); "
            "assert n >= m, '清洗覆盖 %d 处 < spawn %d 处（须全覆盖）' % (n, m); "
            "assert 'os.environ.copy()' not in src, '存在未经清洗的环境继承'"
        )}],
    },
    {
        "id": "safety-audit-chain", "kind": "safety",
        "title": "审计日志脱敏 + 哈希链可校验",
        "checks": [{"type": "python", "expr": (
            "from tea_agent.audit_log import GENESIS_HASH, mask_secrets, audit_log; "
            "assert len(GENESIS_HASH) == 64, '链首哈希非法'; "
            "assert mask_secrets({'api_key': 'sk-abcdefghijklmnop'})['api_key'] == '***MASKED***', '键名脱敏失效'; "
            "assert 'sk-abcdefghijklmnop' not in str(mask_secrets('k=sk-abcdefghijklmnop')), '值形态脱敏失效'; "
            "rec = audit_log.record('bench/probe', tool='toolkit_evo_bench', status='ok'); "
            "assert rec and rec.get('h') and rec.get('prev'), '审计写入/链字段缺失'; "
            "v = audit_log.verify(); "
            "assert isinstance(v, dict) and v.get('ok'), '审计链校验失败: %s' % v"
        )}],
    },
    {
        "id": "safety-approval-classify", "kind": "safety",
        "title": "工具风险分级确定性",
        "checks": [{"type": "python", "expr": (
            "from tea_agent.tool_approval import classify_risk as cr; "
            "assert cr('toolkit_self_evolve')[0] == 'critical', cr('toolkit_self_evolve'); "
            "assert cr('toolkit_exec', {'app': 'git', 'args': ['status']})[0] == 'high', 'git 应判 high'; "
            "assert cr('toolkit_exec', {'app': 'sudo', 'args': ['ls']})[0] == 'critical', '提权应判 critical'; "
            "assert cr('toolkit_exec', {'app': 'rm', 'args': ['-rf', '/']})[0] == 'critical', '破坏性命令应判 critical'; "
            "assert cr('toolkit_approve') == (None, '豁免工具'), '授权工具应豁免: %r' % (cr('toolkit_approve'),); "
            "assert cr('toolkit_audit_log') == (None, '豁免工具'), '审计工具应豁免'"
        )}],
    },
    {
        "id": "safety-approval-mode", "kind": "safety",
        "title": "审批模式解析（env 覆盖）",
        "checks": [{"type": "python", "expr": (
            "import os; from tea_agent.tool_approval import approval_mode; "
            "os.environ['TEA_APPROVAL_MODE'] = 'enforce'; "
            "assert approval_mode() == 'enforce', approval_mode(); "
            "os.environ['TEA_APPROVAL_MODE'] = 'off'; "
            "assert approval_mode() == 'off', approval_mode(); "
            "os.environ['TEA_APPROVAL_MODE'] = ''  # 复位，避免污染同进程后续断言"
        )}],
    },
    {
        "id": "safety-hooks-wired", "kind": "safety",
        "title": "审批/审计钩子已接入工具执行链路",
        "checks": [{"type": "python", "expr": (
            "import re as _re; h = read('tea_agent/tool_hooks.py'); a = read('tea_agent/tool_approval.py'); "
            "assert _re.search(r'def\\s+_ensure_builtin_hooks\\b', h), 'tool_hooks 未定义内建钩子挂载器'; "
            "assert _re.search(r'_ensure_builtin_hooks\\s*\\(', h), '内建钩子定义存在但未被调用'; "
            "assert _re.search(r'def\\s+install_builtin_hooks\\b', a), '审批模块缺少安装入口'"
        )}],
    },
    {
        "id": "tooling-bench-selfcheck", "kind": "tooling",
        "title": "基准引擎自身可用（3 种 check 已注册）",
        "checks": [{"type": "python", "expr": (
            "from tea_agent.evaluation.evo_bench import CHECKS, DEFAULT_TASKS; "
            "assert {'command', 'file', 'python'} <= set(CHECKS), sorted(CHECKS); "
            "assert len(DEFAULT_TASKS) >= 5, len(DEFAULT_TASKS)"
        )}],
    },
    {
        "id": "integrity-compile", "kind": "tooling",
        "title": "新增模块编译检查",
        "checks": [{
            "type": "command", "name": "py_compile",
            "run": ("python -m py_compile tea_agent/audit_log.py tea_agent/tool_approval.py "
                    "tea_agent/evaluation/evo_bench.py tea_agent/toolkit/toolkit_approve.py"),
        }],
    },
]


def load_tasks(root: str = ".", kind: str | None = None) -> list:
    """内置任务 + 外部 JSON 任务（benchmarks/*.json）合并，按 id 去重。

    JSON 文件形态：单个 task 对象，或 {"tasks": [...]}；用于扩展基准而不改代码。
    """
    tasks: list = []
    seen: set = set()
    for t in DEFAULT_TASKS:
        tid = t.get("id")
        if tid and tid not in seen:
            seen.add(tid)
            tasks.append(t)
    try:  # 难度任务集（违规/棘轮/不变量）；模块不可用时降级为仅内置任务
        from tea_agent.evaluation.evo_tasks_hard import HARD_TASKS

        for t in HARD_TASKS:
            tid = t.get("id")
            if tid and tid not in seen:
                seen.add(tid)
                tasks.append(t)
    except ImportError:
        logger.debug("evo_bench: 难度任务集不可用，跳过")
    for d in TASK_DIRS:
        try:
            if not d.is_dir():
                continue
            files = sorted(d.rglob("*.json"))
        except OSError:
            continue
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                logger.warning("evo_bench: 跳过无效任务文件 %s: %s", p, e)
                continue
            items = data.get("tasks") if isinstance(data, dict) and "tasks" in data else [data]
            for it in items or []:
                if not isinstance(it, dict) or not it.get("id") or it["id"] in seen:
                    continue
                seen.add(it["id"])
                it.setdefault("checks", [])
                it.setdefault("kind", "external")
                tasks.append(it)
    if kind:
        tasks = [t for t in tasks if t.get("kind") == kind]
    return tasks


def run_task(task: dict, root: str = ".", timeout: int = 60) -> dict:
    """执行单个任务的全部 checks → {id, passed, total, score, ok, checks[]}。"""
    root_p = Path(root).resolve()
    checks: list = []
    passed = 0
    for c in task.get("checks") or []:
        ctype = str(c.get("type", "command"))
        label = c.get("name") or c.get("path") or str(c.get("run", ""))[:60] or ctype
        fn = CHECKS.get(ctype)
        if fn is None:
            checks.append({"type": ctype, "name": label, "ok": False,
                           "detail": f"未知 check 类型 {ctype!r}"})
            continue
        try:
            ok, detail = fn(c, root_p, timeout)
        except Exception as e:  # noqa: BLE001 — 单个 check 失败不影响其他
            ok, detail = False, f"{type(e).__name__}: {e}"
        checks.append({"type": ctype, "name": label, "ok": bool(ok),
                       "detail": "" if ok else str(detail)[:300]})
        if ok:
            passed += 1
    total = len(checks)
    return {
        "id": task.get("id"), "kind": task.get("kind", ""), "title": task.get("title", ""),
        "passed": passed, "total": total,
        "score": round(passed / total, 4) if total else 0.0,
        "ok": total > 0 and passed == total,
        "checks": checks,
    }


# ── 聚合执行 ──────────────────────────────────────────────────────

def run_bench(tasks: list = None, root: str = ".", kind: str = None, timeout: int = 60,
              record: bool = False, tag: str = None) -> dict:
    """执行全部（或指定 kind 的）任务，聚合为单一分数。

    Args:
        tasks: 显式任务列表（None = 内置 + benchmarks/*.json）
        root: 项目根目录（检查相对路径的基准）
        kind: 只跑指定类别（safety / tooling / external ...）
        timeout: 单 check 基础超时秒数
        record: 是否把本次结果 append 到进化曲线历史
        tag: 本次快照的标签（如 "before-A" / "after-B"）

    Returns:
        {score, passed, total, tasks, tasks_ok, ok, kind, results[], failed[], snapshot?}
    """
    if tasks is None:
        tasks = load_tasks(root=root, kind=kind)
    # 每次运行都重新扫描源码：_bench_metrics 的进程内缓存若跨运行复用，
    # 同一会话内「改前 vs 改后」两次测量会返回相同分数，
    # 而 keep-or-rollback 的前提正是两次独立测量。
    _BENCH_METRIC_CACHE.clear()
    results = [run_task(t, root=root, timeout=timeout) for t in tasks]
    total = sum(r["total"] for r in results)
    passed = sum(r["passed"] for r in results)
    agg = {
        "score": round(passed / total, 4) if total else 0.0,
        "passed": passed,
        "total": total,
        "tasks": len(results),
        "tasks_ok": sum(1 for r in results if r["ok"]),
        "ok": bool(results) and all(r["ok"] for r in results),
        "kind": kind or "all",
        "metrics": _bench_metrics(root),
        "results": results,
        "failed": [
            {"id": r["id"], "title": r["title"],
             "checks": [c for c in r["checks"] if not c["ok"]]}
            for r in results if not r["ok"]
        ],
    }
    if record:
        snap = record_run(agg, tag=tag)
        agg["snapshot"] = snap
        if snap is None:
            agg["record_error"] = f"历史写入失败（路径: {history_path()}）"
    return agg


# ── 进化曲线历史 ──────────────────────────────────────────────────

def history_path() -> str:
    """曲线历史文件路径（TEA_BENCH_HISTORY > 项目 .tea_agent_run/bench_history.jsonl）。"""
    override = os.environ.get("TEA_BENCH_HISTORY", "").strip()
    if override:
        return override
    try:
        from tea_agent.storage_scope import project_run_dir

        base = project_run_dir() or os.getcwd()
    except Exception:  # noqa: BLE001 — 存储作用域不可用时落当前目录
        base = os.getcwd()
    return os.path.join(base, "bench_history.jsonl")


def _git_rev() -> str:
    """当前 git 短哈希（不可用时返回空串）。"""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def record_run(agg: dict, tag: str = None) -> dict | None:
    """把一次聚合结果 append 进曲线历史（JSONL，一行一个数据点）。"""
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tag": tag,
        "score": agg.get("score"),
        "passed": agg.get("passed"),
        "total": agg.get("total"),
        "tasks": agg.get("tasks"),
        "tasks_ok": agg.get("tasks_ok"),
        "ok": agg.get("ok"),
        "kind": agg.get("kind"),
        "git": _git_rev(),
    }
    try:
        path = history_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as e:  # 历史写失败不影响基准结论
        logger.debug("evo_bench: 历史写入失败: %s", e)
        return None
    return rec


def history(limit: int = 50) -> list:
    """读取进化曲线数据点（最近 limit 条；limit=0 表示全部）。"""
    path = history_path()
    if not os.path.exists(path):
        return []
    out: list = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-int(limit):] if limit else out


def _split_point(x) -> tuple:
    """归一化分数点 → (score, total|None)。接受 dict 或纯数字。"""
    if isinstance(x, dict):
        s = float(x.get("score", 0.0))
        t = x.get("total")
        return s, (int(t) if isinstance(t, int) else None)
    return float(x), None


def compare_with_history(baseline=None, candidate=None, threshold: float = 0.0,
                         coverage_threshold: int = 0) -> dict:
    """keep-or-rollback 决策（对齐 toolkit_eval_loop 的确定性闭环）。

    **覆盖感知**：pass ratio 在接近满分时失去分辨率 —— 若只在任务集里
    加入更强的检查（score 不变、total 增大），纯 ratio 口径会误判 no_change
    并回滚掉真实增益。故当 score 持平时改用绝对覆盖比较。

    Args:
        baseline: 改进前分数点（dict 含 score/total，或数字；None = 取历史倒数第二个点）
        candidate: 改进后分数点（同上；必需）
        threshold: 保留阈值，score delta 需 > threshold 才 keep
        coverage_threshold: 覆盖阈值，total 增量需 > 此值才 keep

    Returns:
        {ok, decision: keep|rollback|no_change, basis: score|coverage|none,
         delta, coverage_delta, ...}
    """
    if candidate is None:
        return {"ok": False, "error": "缺少 candidate（先 run_bench(record=True) 再比较）"}
    c, c_total = _split_point(candidate)
    hist = history(limit=0)
    if baseline is None:
        if not hist:
            return {"ok": False, "error": "历史为空，无法推导基线（可显式传 baseline）"}
        idx = -2 if len(hist) >= 2 else -1
        b, b_total = _split_point(hist[idx])
    else:
        b, b_total = _split_point(baseline)

    delta = round(c - b, 4)
    cov_delta = ((c_total - b_total) if (b_total is not None and c_total is not None) else None)

    if delta > threshold:
        decision, basis = "keep", "score"
        advice = f"保留改进：分数 {b} → {c}（+{delta}，阈值 {threshold}）"
    elif delta < 0:
        decision, basis = "rollback", "score"
        advice = f"建议回滚：分数 {b} → {c}（{delta}），改进使表现变差"
    elif cov_delta is not None and cov_delta > coverage_threshold:
        decision, basis = "keep", "coverage"
        advice = (f"保留改进：分数持平 {c}，但检查覆盖 {b_total} → {c_total}"
                  f"（+{cov_delta}，阈值 {coverage_threshold}）—— 更强的保证，非退步")
    elif cov_delta is not None and cov_delta < 0:
        decision, basis = "rollback", "coverage"
        advice = f"建议回滚：分数持平 {c}，但覆盖收缩 {b_total} → {c_total}（{cov_delta}）"
    else:
        decision, basis = "no_change", "none"
        advice = (f"无提升（score delta={delta} ≤ {threshold}，"
                  f"coverage delta={cov_delta}），默认建议回滚到基线")

    return {"ok": True, "decision": decision, "basis": basis, "baseline": round(b, 4),
            "candidate": round(c, 4), "delta": delta, "threshold": threshold,
            "baseline_total": b_total, "candidate_total": c_total,
            "coverage_delta": cov_delta, "coverage_threshold": coverage_threshold,
            "points": len(hist), "advice": advice}

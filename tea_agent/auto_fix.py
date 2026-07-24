"""
# @2026-06-07 gen by deepseek-v4-pro, AutoFix v2 — ruff + LLM 集成
"""
import ast
import hashlib
import json
import logging
import os
import subprocess
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("AutoFix")
RUFF_SELECT = "F401,F841,F811,W291,W293,E225,E231,E302,E303,E305,W391,E401,E701,E711,E712,E713,E714"
FIX_PROMPT = """Fix this Python issue.
Issue: {rule_code} - {message}
Line {line}: {code_snippet}
Return ONLY the fixed code line(s), no explanations.
If removing a line, return an empty string.
Fixed code:"""


class FixResult:
    def __init__(self, ok=False, action="", detail="", old="", new="", via=""):
        self.ok, self.action, self.detail = ok, action, detail
        self.old, self.new, self.via = old, new, via
    def to_dict(self):
        return {"ok": self.ok, "action": self.action, "detail": self.detail,
                "old": self.old, "new": self.new, "via": self.via}


class AutoFixAgent:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.fix_log: list[dict] = []
        self._llm = None
        self._init_llm()

    def _init_llm(self):
        try:
            from tea_agent.config import get_config
            cfg = get_config()
            self._llm = cfg.cheap_model or cfg.main_model
        except Exception:
            self._llm = None

    # ── 扫描 ──

    def scan(self, filepath: str | None = None) -> list[dict]:
        issues = self._scan_ruff(filepath) + self._scan_ast_docstring(filepath)
        seen, deduped = set(), []
        for i in sorted(issues, key=lambda x: ("ast", "ruff").index(x.get("via", "ruff"))):
            key = (i["file"], i["line"], i["rule"])
            if key not in seen:
                seen.add(key)
                deduped.append(i)
        return deduped

    def _scan_ruff(self, filepath: str | None = None) -> list[dict]:
        cmd = ["ruff", "check"]
        cmd.append(filepath or str(self.project_root))
        cmd += ["--select", RUFF_SELECT, "--output-format", "json"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            raw = json.loads(r.stdout) if r.stdout.strip() else []
        except Exception:
            return []
        issues = []
        for item in raw:
            loc = item["location"]
            rel = os.path.relpath(item["filename"], str(self.project_root)).replace("\\", "/")
            code = item.get("code") or ""
            issues.append({
                "id": hashlib.md5(f"{rel}:{code}:{loc['row']}".encode()).hexdigest()[:8],
                "file": rel, "line": loc["row"],
                "severity": "error" if code.startswith(("E", "F")) else "warning",
                "rule": code, "rule_name": item.get("name", ""),
                "message": item.get("message", ""), "via": "ruff",
                "ruff_autofix": (item.get("fix") or {}).get("edits"),
            })
        return issues

    def _scan_ast_docstring(self, filepath: str | None = None) -> list[dict]:
        issues = []
        py_files = [Path(filepath)] if filepath else list(self.project_root.rglob("*.py"))
        for pf in py_files:
            s = str(pf)
            if any(x in s for x in (".tea_agent_run", "__pycache__", ".git", "build")):
                continue
            rel = os.path.relpath(s, str(self.project_root)).replace("\\", "/")
            try:
                with open(s, encoding="utf-8", errors="replace") as f:
                    source = f.read()
                tree = ast.parse(source, filename=s)
                source.split('\n')
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                        if node.name.startswith('_') and not isinstance(node, ast.ClassDef):
                            continue
                        if not ast.get_docstring(node):
                            issues.append({
                                "id": hashlib.md5(f"{rel}:NO_DOCSTRING:{node.lineno}".encode()).hexdigest()[:8],
                                "file": rel, "line": node.lineno,
                                "severity": "info", "rule": "NO_DOCSTRING",
                                "message": f"缺少 docstring: {node.name}()",
                                "via": "ast", "ruff_autofix": None,
                            })
            except Exception:
                continue
        return issues
    # ── 修复 ──

    def fix(self, issue: dict, dry_run: bool = True) -> FixResult:
        via = issue.get("via", "ruff")
        # Layer 1: ruff autofix
        if via == "ruff" and issue.get("ruff_autofix"):
            r = self._fix_ruff(issue, dry_run)
            if r.ok:
                return r
        # Layer 2: AST fallback
        r = self._fix_ast(issue, dry_run)
        if r.ok:
            return r
        # Layer 3: LLM
        if self._llm:
            r = self._fix_llm(issue, dry_run)
            if r.ok:
                return r
        return FixResult(ok=False, action="skip", detail=f"无法修复: {issue['rule']}")

    def _fix_ruff(self, issue: dict, dry_run: bool) -> FixResult:
        fp = str(self.project_root / issue["file"])
        if not os.path.isfile(fp):
            return FixResult(ok=False)
        with open(fp, encoding="utf-8") as f:
            source = f.read()
        lines = source.split('\n')
        edits = sorted(issue["ruff_autofix"], key=lambda e: e["location"]["row"], reverse=True)
        if dry_run:
            e = edits[-1]
            return FixResult(ok=True, action="dry_run",
                             detail=f"[ruff] 将修复 {issue['rule']} L{issue['line']}",
                             old=lines[e["location"]["row"]-1],
                             new=e.get("content", "(删除)"), via="ruff")
        new_lines = lines[:]
        for e in edits:
            r, c = e["location"]["row"]-1, e["location"]["column"]-1
            er = e.get("end_location", e["location"]).get("row", r+1)-1
            ec = e.get("end_location", e["location"]).get("column", len(new_lines[r]))
            content = e.get("content", "")
            if r == er:
                new_lines[r] = new_lines[r][:c] + content + new_lines[r][ec:]
            else:
                new_lines[r] = new_lines[r][:c] + content
                del new_lines[r+1:er+1]
        return self._apply(fp, source, '\n'.join(new_lines), issue, "ruff")

    def _fix_ast(self, issue: dict, dry_run: bool) -> FixResult:
        fp = str(self.project_root / issue["file"])
        if not os.path.isfile(fp):
            return FixResult(ok=False)
        with open(fp, encoding="utf-8") as f:
            source = f.read()
        lines = source.split('\n')
        li = issue["line"] - 1
        if li < 0 or li >= len(lines):
            return FixResult(ok=False)
        rule = issue["rule"]
        if rule == "NO_DOCSTRING":
            old = lines[li]
            indent = len(old) - len(old.lstrip())
            doc = " " * indent + '    """TODO: Add docstring."""'
            new = old + '\n' + doc
            if dry_run:
                return FixResult(ok=True, action="dry_run",
                                 detail="[AST] 添加 docstring", old=old, new=new, via="ast")
            new_lines = lines[:]
            new_lines.insert(li + 1, doc)
            return self._apply(fp, source, '\n'.join(new_lines), issue, "ast")
        return FixResult(ok=False)

    def _fix_llm(self, issue: dict, dry_run: bool) -> FixResult:
        fp = str(self.project_root / issue["file"])
        if not os.path.isfile(fp):
            return FixResult(ok=False)
        with open(fp, encoding="utf-8") as f:
            source = f.read()
        lines = source.split('\n')
        li = issue["line"] - 1
        ctx = '\n'.join(lines[max(0,li-2):min(len(lines),li+3)])
        prompt = FIX_PROMPT.format(rule_code=issue["rule"],
                                    message=issue.get("message", ""),
                                    line=issue["line"], code_snippet=ctx)
        try:
            import requests
            url = (getattr(self._llm, 'api_url', '') or '').rstrip('/') + '/v1/chat/completions'
            r = requests.post(url, json={
                "model": getattr(self._llm, 'model', 'gpt-3.5-turbo'),
                "messages": [
                    {"role": "system", "content": "Code fix expert. Return ONLY fixed code."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1, "max_tokens": 256,
            }, headers={
                "Authorization": f"Bearer {getattr(self._llm, 'api_key', '')}",
            }, timeout=15)
            r.raise_for_status()
            fixed = r.json()["choices"][0]["message"]["content"].strip()
            if not fixed:
                return FixResult(ok=False)
            if dry_run:
                return FixResult(ok=True, action="dry_run",
                                 detail=f"[LLM] 修复: {fixed[:60]}",
                                 old=lines[li], new=fixed, via="llm")
            new_lines = lines[:]
            new_lines[li] = fixed
            return self._apply(fp, source, '\n'.join(new_lines), issue, "llm")
        except Exception as e:
            return FixResult(ok=False, action="error", detail=str(e), via="llm")

    def _apply(self, fp: str, old_src: str, new_src: str,
                issue: dict, via: str) -> FixResult:
        try:
            compile(new_src, fp, "exec")
        except SyntaxError as e:
            return FixResult(ok=False, action="error", detail=f"编译错误: {e.msg}", via=via)
        try:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(new_src)
            self.fix_log.append({"rule": issue["rule"], "file": issue["file"],
                                  "line": issue["line"], "status": "fixed", "via": via})
            return FixResult(ok=True, action="fixed",
                             detail=f"[{via}] 修复 {issue['rule']}:{issue['line']}", via=via)
        except Exception as e:
            return FixResult(ok=False, action="error", detail=str(e), via=via)

    def fix_all(self, severity: str = "warning", dry_run: bool = True,
                max_fixes: int = 10) -> dict:
        all_i = self.scan()
        sev = {"error": 0, "warning": 1, "info": 2}
        flt = [i for i in all_i if sev.get(i["severity"], 99) >= sev.get(severity, 1)]
        fixed = skipped = errors = 0
        results = []
        for issue in flt[:max_fixes]:
            r = self.fix(issue, dry_run=dry_run)
            results.append({"issue": {"rule": issue["rule"], "line": issue["line"],
                                       "file": issue["file"]}, "result": r.to_dict()})
            if r.ok and r.action == "fixed":
                fixed += 1
            elif r.action == "skip":
                skipped += 1
            else:
                errors += 1
        return {"scanned": len(all_i), "filtered": len(flt),
                "fixed": fixed, "skipped": skipped, "errors": errors,
                "dry_run": dry_run, "results": results}

    def verify(self) -> dict:
        errors = []
        for e in self.fix_log:
            fp = self.project_root / e["file"]
            try:
                with open(fp, encoding="utf-8") as f:
                    compile(f.read(), str(fp), "exec")
            except SyntaxError as ex:
                errors.append(f"{e['file']}:{ex.lineno}: {ex.msg}")
        return {"ok": len(errors) == 0, "compile_errors": errors,
                "fixes": len(self.fix_log)}

    def report(self) -> dict:
        by_rule = defaultdict(list)
        for e in self.fix_log:
            by_rule[e["rule"]].append(e)
        return {"total_fixes": len(self.fix_log),
                "by_rule": {k: len(v) for k, v in by_rule.items()},
                "changes": self.fix_log[-10:]}

    def close(self):
        pass

"""toolkit_auto_fix — 代码自动修复 Agent 工具入口"""
import os, sys, json, logging
from pathlib import Path

logger = logging.getLogger("toolkit_auto_fix")

_SELF_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SELF_DIR.parent  # tea_agent/

def toolkit_auto_fix(action="scan", filepath=None, severity="warning",
                      dry_run=True, max_fixes=5):
    """代码自动修复 Agent — 扫描→分析→修复→验证→反思闭环。

    Args:
        action: scan=扫描问题, fix_all=批量修复, fix=修复指定问题, status=查看状态
        filepath: [scan] 指定文件，不填扫描全项目
        severity: [fix_all] 最低严重级别 (error/warning/info)
        dry_run: [fix_all] True=仅预览不实际修改
        max_fixes: [fix_all] 最大修复数量

    Returns:
        扫描结果或修复报告
    """
    try:
        from tea_agent.auto_fix import AutoFixAgent
    except ImportError:
        sys.path.insert(0, str(_PROJECT_ROOT.parent))
        from tea_agent.auto_fix import AutoFixAgent

    agent = AutoFixAgent(str(_PROJECT_ROOT))

    if action == "scan":
        issues = agent.scan(filepath)
        if not issues:
            return "✅ 无发现，代码干净！"

        by_severity = {}
        for i in issues:
            by_severity[i["severity"]] = by_severity.get(i["severity"], 0) + 1

        from collections import Counter
        by_rule = Counter(i["rule"] for i in issues)

        lines = [f"🔍 扫描完成: 发现 {len(issues)} 个问题"]
        lines.append(f"  严重级别: {by_severity}")
        lines.append(f"  按规则:")
        for rule, count in by_rule.most_common(10):
            lines.append(f"    {rule:20s} x {count}")
        lines.append("")
        lines.append(f"  前 10 条详情:")
        for i in issues[:10]:
            lines.append(f"  [{i['severity'][0].upper()}] {i['rule']:20s} L{i['line']:4d} {i['file']}")
            lines.append(f"       {i['message'][:70]}")
        if len(issues) > 10:
            lines.append(f"  ... 及其他 {len(issues)-10} 条")

        return "\n".join(lines)

    elif action == "fix_all":
        result = agent.fix_all(severity=severity, dry_run=dry_run, max_fixes=max_fixes)
        lines = []
        if dry_run:
            lines.append(f"🔍 Dry-run 预览 (设置 dry_run=false 执行)")
        else:
            lines.append(f"🔧 批量修复完成")

        lines.append(f"  扫描: {result['scanned']} 个问题")
        lines.append(f"  待修: {result['filtered']} 个 (>= {severity})")
        lines.append(f"  修复: {result['fixed']} | 跳过: {result['skipped']} | 错误: {result['errors']}")

        if result["results"]:
            lines.append(f"  详情:")
            for r in result["results"][:10]:
                issue = r["issue"]
                res = r["result"]
                status = "✅" if res["ok"] else "❌"
                lines.append(f"  {status} [{issue['rule']}] L{issue['line']} {issue['file']}")
                lines.append(f"       {res['detail'][:70]}")
                if res.get('old') and res.get('new') and dry_run:
                    lines.append(f"       OLD: {res['old'][:60]}")
                    lines.append(f"       NEW: {res['new'][:60]}")

        return "\n".join(lines)

    elif action == "fix":
        if not filepath:
            return "❌ fix 需要 filepath 参数"
        issues = agent.scan(filepath)
        if not issues:
            return f"✅ {filepath} 无问题"
        results = []
        for i in issues[:5]:
            r = agent.fix(i, dry_run=dry_run)
            results.append(r)
        fixed = sum(1 for r in results if r.get("action") == "fixed")
        return f"修复 {filepath}: {len(results)} 尝试, {fixed} 成功"

    elif action == "status":
        report = agent.report()
        verify = agent.verify()
        lines = [f"📊 AutoFix Agent 状态"]
        lines.append(f"  累计修复: {report['total_fixes']} 次")
        lines.append(f"  编译检查: {'✅ 通过' if verify['ok'] else '❌ 有错误'}")
        lines.append(f"  按规则:")
        for rule, count in report["by_rule"].items():
            lines.append(f"    {rule:20s}: {count}")
        if report["changes"]:
            lines.append(f"  最近修改:")
            for c in report["changes"][-5:]:
                lines.append(f"    {c['status']:8s} [{c['rule']}] {c['file']}:{c['line']}")
        return "\n".join(lines)

    return f"❌ 未知 action: {action}"

# 元数据
def meta_toolkit_auto_fix():
    return {
        "type": "function",
        "function": {
            "name": "toolkit_auto_fix",
            "description": "代码自动修复 Agent — 扫描代码问题→批量修复→状态查看。支持未使用导入/缺失docstring/行长等问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["scan", "fix_all", "fix", "status"],
                        "description": "scan=扫描问题, fix_all=批量修复, fix=修复指定文件, status=查看状态"
                    },
                    "filepath": {
                        "type": "string",
                        "description": "[scan/fix] 指定文件路径，不填扫描全项目"
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["error", "warning", "info"],
                        "description": "[fix_all] 最低严重级别",
                        "default": "warning"
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "[fix_all/fix] True=仅预览不修改",
                        "default": True
                    },
                    "max_fixes": {
                        "type": "integer",
                        "description": "[fix_all] 最大修复数量",
                        "default": 5
                    }
                },
                "required": ["action"]
            }
        }
    }

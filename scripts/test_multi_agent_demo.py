"""
Multi-Agent 实战测试：分析 demo 目录下所有项目

使用组件:
  - SubAgentManager: 创建分析师 + 审查员
  - WorkflowDAG + WorkflowExec: 工作流编排
  - ExecutionPool: 并行执行引擎
"""
import os, sys, time, json

sys.path.insert(0, r"C:\Users\Hetin\work\git\tea_agent")
from tea_agent.multi_agent import (
    SubAgentManager,
    WorkflowDAG, WorkflowNode, NodeType, NodeState,
    WorkflowExec, WorkflowTemplate,
    ExecutionPool, get_execution_pool,
)

DEMO_ROOT = r"C:\Users\Hetin\work\git\tea_agent\demo"
EXCLUDE = {"__pycache__", "data"}

# ── 工具函数 ──────────────────────────────

def scan_project(project_dir: str) -> dict:
    """扫描单个项目，返回结构信息"""
    name = os.path.basename(project_dir)
    files = []
    ext_counts = {}
    total_lines = 0
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for fn in filenames:
            if fn.endswith(('.pyc', '.npz', '.spec')):
                continue
            fpath = os.path.join(root, fn)
            rel = os.path.relpath(fpath, project_dir)
            ext = os.path.splitext(fn)[1] or '(none)'
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            try:
                with open(fpath, encoding='utf-8', errors='ignore') as f:
                    lines = len(f.readlines())
                    total_lines += lines
            except:
                lines = 0
            files.append({"path": rel, "ext": ext, "lines": lines})

    has_pyproject = os.path.exists(os.path.join(project_dir, "pyproject.toml"))
    has_readme = os.path.exists(os.path.join(project_dir, "README.md"))
    has_tests = os.path.exists(os.path.join(project_dir, "tests"))
    has_html = any(f["ext"] == ".html" for f in files)

    return {
        "name": name,
        "file_count": len(files),
        "total_lines": total_lines,
        "extensions": ext_counts,
        "has_pyproject": has_pyproject,
        "has_readme": has_readme,
        "has_tests": has_tests,
        "project_type": "web" if has_html else "python",
        "files": files,
    }


def analyze_project(ctx: dict) -> dict:
    """分析师：深入分析项目"""
    info = ctx.get("scan_result", {})
    name = info.get("name", "unknown")
    files = info.get("files", [])

    # 找出关键文件
    key_files = {
        "entry": [],
        "config": [],
        "tests": [],
        "docs": [],
    }
    for f in files:
        p = f["path"].lower()
        if any(k in p for k in ["main", "app", "index", "cli"]):
            key_files["entry"].append(f["path"])
        if any(k in p for k in ["config", "settings", "pyproject", "package"]):
            key_files["config"].append(f["path"])
        if any(k in p for k in ["test", "spec"]):
            key_files["tests"].append(f["path"])
        if any(k in p for k in ["readme", "doc", ".md"]):
            key_files["docs"].append(f["path"])

    # 复杂度评估
    complexity = "low"
    if info["total_lines"] > 500:
        complexity = "high"
    elif info["total_lines"] > 200:
        complexity = "medium"

    return {
        "project": name,
        "type": info["project_type"],
        "complexity": complexity,
        "total_lines": info["total_lines"],
        "file_count": info["file_count"],
        "key_files": key_files,
        "ext_distribution": info["extensions"],
        "recommendation": _gen_recommendation(info, complexity),
    }


def review_project(ctx: dict) -> dict:
    """审查员：质量评估"""
    analysis = ctx.get("analysis_result", ctx.get("scan_result", {}))
    name = analysis.get("project", analysis.get("name", "unknown"))

    issues = []
    score = 100

    # 检查项
    if not analysis.get("has_readme"):
        issues.append("缺少 README.md")
        score -= 10
    if analysis.get("project_type") == "python" and not analysis.get("has_pyproject"):
        issues.append("缺少 pyproject.toml")
        score -= 10
    if analysis.get("project_type") == "python" and not analysis.get("has_tests"):
        issues.append("缺少测试目录")
        score -= 15
    if analysis.get("file_count", 0) <= 1 and analysis.get("project_type") == "python":
        issues.append("单文件项目，建议模块化")
        score -= 5

    # 给加分项
    if analysis.get("has_tests"):
        score += 5
    if analysis.get("has_readme"):
        score += 3
    if analysis.get("has_pyproject"):
        score += 2

    return {
        "project": name,
        "score": max(0, min(100, score)),
        "issues": issues,
        "grade": "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D",
        "summary": f"{name}: {max(0, min(100, score))}/100 — " + ("优秀" if score >= 90 else "良好" if score >= 75 else "一般" if score >= 60 else "需改进"),
    }


def _gen_recommendation(info: dict, complexity: str) -> str:
    name = info["name"]
    if info["project_type"] == "web":
        return f"[{name}] HTML 项目，复杂度 {complexity}。建议检查浏览器兼容性。"
    return f"[{name}] Python 项目，复杂度 {complexity}。{'建议补充 pyproject.toml 和测试。' if not info.get('has_pyproject') else ''}"


# ── 主测试逻辑 ────────────────────────────

def main():
    print("=" * 70)
    print("🚀 Multi-Agent Demo 项目分析测试")
    print("=" * 70)

    projects = [
        d for d in os.listdir(DEMO_ROOT)
        if os.path.isdir(os.path.join(DEMO_ROOT, d)) and d not in EXCLUDE
    ]
    print(f"\n📂 发现 {len(projects)} 个项目: {', '.join(sorted(projects))}")

    # ── 1. 创建 Agent ──
    print("\n── Agent 管理 ──")
    mgr = SubAgentManager(verbose=False)
    analyst = mgr.create_analyst_agent(goal="分析 demo 项目结构", topics=["demo:analyze"])
    reviewer = mgr.create_reviewer_agent(goal="审查 demo 项目质量", topics=["demo:review"])
    print(f"   分析师: {analyst.agent_id}")
    print(f"   审查员: {reviewer.agent_id}")
    print(f"   Agent 总数: {mgr.stats()['total_agents']}")

    # ── 2. 扫描所有项目 ──
    print("\n── 项目扫描 ──")
    scan_results = {}
    for proj in projects:
        scan = scan_project(os.path.join(DEMO_ROOT, proj))
        scan_results[proj] = scan
        print(f"   {proj:20s} {scan['file_count']:2d} 文件, {scan['total_lines']:4d} 行, "
              f"类型={scan['project_type']:6s}, "
              f"pyproject={'✅' if scan['has_pyproject'] else '❌'}, "
              f"tests={'✅' if scan['has_tests'] else '❌'}")

    # ── 3. 构建 WorkflowDAG：并行分析 ──
    print("\n── 构建 WorkflowDAG ──")
    dag = WorkflowDAG("demo-analysis")

    # START: 汇总扫描结果
    dag.add_node(WorkflowNode(
        "start", NodeType.TASK,
        label="汇总扫描结果",
        fn=lambda ctx: {"project_count": len(ctx.get("projects", []))},
    ))

    # SCAN + ANALYZE: 为每个项目创建分析节点（并行）
    prev_id = "start"
    analyze_nodes = []
    for proj in projects:
        scan = scan_results[proj]
        nid = f"analyze_{proj}"

        # 合并扫描+分析到一个节点
        dag.add_node(WorkflowNode(
            nid, NodeType.TASK,
            label=f"分析 {proj}",
            fn=lambda ctx, s=scan: analyze_project({"scan_result": s}),
        ))
        dag.add_edge(prev_id, nid)
        analyze_nodes.append(nid)
        prev_id = nid

    # REVIEW: 审查节点（依赖所有分析）
    review_nodes = []
    for proj in projects:
        scan = scan_results[proj]
        nid = f"review_{proj}"
        dag.add_node(WorkflowNode(
            nid, NodeType.TASK,
            label=f"审查 {proj}",
            fn=lambda ctx, s=scan: review_project({"scan_result": s}),
        ))
        for a_nid in analyze_nodes:
            dag.add_edge(a_nid, nid)
        review_nodes.append(nid)

    # END
    dag.add_node(WorkflowNode("end", NodeType.END, label="完成"))
    for nid in review_nodes:
        dag.add_edge(nid, "end")

    errors = dag.validate()
    if errors:
        print(f"   ❌ DAG 校验失败: {errors}")
        return
    print(f"   ✅ DAG 校验通过: {len(dag.nodes)} 节点, {len(dag.edges)} 边")

    # ── 4. 执行工作流 ──
    print("\n── ExecutionPool + WorkflowExec ──")
    pool = get_execution_pool(max_workers=4, pool_name="demo-analysis")
    print(f"   Pool: {pool.status()['state']} workers={pool.status()['max_workers']}")

    wf = WorkflowExec(dag, pool=pool)
    start_time = time.time()
    wf.run({"projects": projects})
    elapsed = time.time() - start_time

    print(f"   工作流状态: {wf.state.value}")
    print(f"   执行耗时: {elapsed:.3f}s")
    print(f"   Pool 统计: submitted={pool.status()['stats']['submitted']}, "
          f"completed={pool.status()['stats']['completed']}")

    # ── 5. 结果汇总 ──
    print("\n" + "=" * 70)
    print("📊 分析结果汇总")
    print("=" * 70)

    results = []
    for nid, nr in wf.results.items():
        if nid.startswith("review_") and nr.state == NodeState.COMPLETED:
            if nr.output:
                results.append(nr.output)

    results.sort(key=lambda r: r.get("score", 0), reverse=True)

    print(f"\n{'项目':20s} {'评分':>5s} {'等级':>3s} {'问题'}")
    print("-" * 60)
    for r in results:
        issues = ", ".join(r["issues"]) if r["issues"] else "无"
        print(f"{r['project']:20s} {r['score']:3d}/100 {r['grade']:>3s}  {issues}")

    print(f"\n📈 统计:")
    avg_score = sum(r["score"] for r in results) / max(1, len(results))
    a_count = sum(1 for r in results if r["grade"] == "A")
    b_count = sum(1 for r in results if r["grade"] == "B")
    c_count = sum(1 for r in results if r["grade"] == "C")
    d_count = sum(1 for r in results if r["grade"] == "D")
    print(f"   平均分: {avg_score:.1f}")
    print(f"   分布: A={a_count} B={b_count} C={c_count} D={d_count}")

    # ── 6. WorkflowTemplate 保存 ──
    print("\n── WorkflowTemplate ──")
    WorkflowTemplate.save("demo-analysis", dag, description="并行分析 demo 项目")
    tps = WorkflowTemplate.list_templates()
    print(f"   已保存模板: {len(tps)} 个")
    for t in tps:
        print(f"   📄 {t['name']:20s} {t.get('description','')[:50]}")

    # ── 7. AdminPanel ──
    print("\n── AdminPanel ──")
    from tea_agent.multi_agent import AdminPanel
    panel = AdminPanel(subagent_manager=mgr, verbose=False)
    print(f"   Panel: {panel}")
    pool_fmt = panel._format_pool().split("\n")
    print(f"   {pool_fmt[1]}")
    print(f"   {pool_fmt[3]}")
    print(f"   {pool_fmt[4]}")

    pool.shutdown(wait=False)
    print(f"\n✅ 测试完成! 耗时 {elapsed:.2f}s")

    return {
        "workflow": wf.state.value,
        "projects": len(projects),
        "avg_score": avg_score,
        "elapsed": round(elapsed, 3),
        "results": results,
    }


if __name__ == "__main__":
    summary = main()
    print(f"\n📋 JSON: {json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:500]}")

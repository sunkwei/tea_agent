#!/usr/bin/env python3
"""
@2025-07-19 gen by tea_agent — v2.0 五层性能指标体系

基于 DB topic_token_stats + 确定性基准任务 + LLM 质量评估。
五层指标: L1 任务成功 | L2 质量评分 | L3 效率 | L4 工具准确率 | L5 进化稳定性

用法:
    python -m benchmark.runner list                        # 列出所有任务
    python -m benchmark.runner run <task> [--runs N]       # 执行单个任务
    python -m benchmark.runner run <task> --fair           # 公平模式(t=0, no-thinking)
    python -m benchmark.runner run-all [--fair]            # 运行全部任务
    python -m benchmark.runner report <task>               # 查看最新报告
    python -m benchmark.runner report --all                # 查看全体报告
    python -m benchmark.runner regression                  # 回归检测
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import yaml

from benchmark.metrics import (
    BenchmarkResult, BenchmarkSummary, L1Result, L2Result, L3Result, L4Result,
    estimate_cost, evaluate_l1, evaluate_l2, evaluate_l4, regression_check,
    summarize_runs, TASK_CATEGORIES,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("benchmark")

TASKS_DIR = Path(__file__).parent / "tasks"
RESULTS_DIR = Path(__file__).parent / "results"
REGRESSION_DIR = Path(__file__).parent / "regression"
VERSION_FILE = Path(__file__).parent / "regression" / "latest.json"


# ── 任务加载 ──

def load_tasks() -> dict[str, dict]:
    tasks = {}
    if not TASKS_DIR.is_dir():
        return tasks
    for f in sorted(TASKS_DIR.glob("*.yaml")):
        with open(f, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            tasks[f.stem] = data
    return tasks


# ── 核心：单任务基准测试 ──

def run_benchmark_v2(
    task_name: str,
    task: dict,
    runs: int,
    config_path: str | None = None,
    fair_mode: bool = False,
) -> list[BenchmarkResult]:
    """v2.0: 执行基准测试并采集 L1-L5 指标。"""
    from tea_agent.agent import Agent

    results: list[BenchmarkResult] = []
    task_prompt = task["prompt"]
    task_title = task.get("name", task_name)
    task_category = task.get("category", TASK_CATEGORIES.get(task_name, "通用"))
    expected_patterns = task.get("expected_patterns", [])
    tool_allowlist = task.get("tool_allowlist", None)

    # fair_mode: 锁定参数
    enable_thinking = False if fair_mode else None
    if fair_mode:
        print(f"  ⚖️ fair mode: temperature=0, thinking=off")

    for run_idx in range(1, runs + 1):
        topic_id = str(uuid.uuid4())
        print(f"\n  [{task_name}] run {run_idx}/{runs} ", end="", flush=True)

        try:
            agent = Agent(
                mode="full",
                config_path=config_path,
                enable_thinking=enable_thinking,
            )
            agent._db.create_topic(f"{task_title} #{run_idx}", topic_id)
            agent.current_topic_id = topic_id

            t0 = time.monotonic()
            result = agent.chat(task_prompt, topic_id=topic_id)
            duration = time.monotonic() - t0

            # 提取 AI 回复
            ai_msg = ""
            if isinstance(result, list):
                for msg in result:
                    if msg.get("role") == "assistant":
                        ai_msg = msg.get("content", "")
                        break

            # ---- L1: 确定性模式匹配 ----
            l1 = evaluate_l1(ai_msg, expected_patterns)

            # ---- L2: 质量评分 ----
            cheap_client = None
            try:
                from tea_agent.providers import get_cheap_client
                from tea_agent.config import get_config
                cheap_client = get_cheap_client(get_config())
            except Exception:
                pass
            l2 = evaluate_l2(ai_msg, task_prompt, cheap_client)

            # ---- L3: 效率指标 ----
            stats = agent._db.get_topic_tokens(topic_id)
            major_in = stats.get("total_prompt_tokens", 0)
            major_out = stats.get("total_completion_tokens", 0)
            cheap_in = stats.get("total_cheap_prompt_tokens", 0)
            cheap_out = stats.get("total_cheap_completion_tokens", 0)
            total = stats.get("total_tokens", 0) + stats.get("total_cheap_tokens", 0)
            cost = estimate_cost("default", major_in + cheap_in, major_out + cheap_out)

            l3 = L3Result(
                prompt_tokens=major_in,
                completion_tokens=major_out,
                total_tokens=total,
                cheap_tokens=stats.get("total_cheap_tokens", 0),
                duration_s=duration,
                token_efficiency=1.0,  # baseline = 自身，后续对比时计算
                estimated_cost_usd=cost,
            )

            # ---- L4: 工具准确率 ----
            tool_log = _extract_tool_calls(agent, topic_id)
            l4 = evaluate_l4(tool_log, tool_allowlist)

            br = BenchmarkResult(
                task_name=task_name,
                run=run_idx,
                topic_id=topic_id,
                l1=l1, l2=l2, l3=l3, l4=l4,
                ai_output=ai_msg,
                duration_s=duration,
            )

            icon = "✅" if l1.passed else "⚠️"
            print(f"{icon} L1={'PASS' if l1.passed else 'FAIL'} "
                  f"L2={l2.overall} L3={total}t/{duration:.1f}s "
                  f"L4={l4.accuracy:.0%} "
                  f"综合={br.composite_score:.0f}")
            results.append(br)

        except Exception as e:
            logger.exception(f"Run {run_idx} 失败")
            br = BenchmarkResult(
                task_name=task_name,
                run=run_idx,
                topic_id=topic_id,
                error=str(e),
                duration_s=time.monotonic() - t0 if 't0' in dir() else 0,
            )
            print(f"❌ 失败: {e}")
            results.append(br)

    return results


def _extract_tool_calls(agent, topic_id: str) -> list[dict]:
    """从 conversation 记录中提取工具调用日志。"""
    tool_log = []
    try:
        convs = agent._db._conversations.get_conversations(topic_id, limit=50, include_rounds=True)
        for conv in convs:
            rounds_data = conv.get("rounds_json_parsed") or []
            if not isinstance(rounds_data, list):
                continue
            for msg in rounds_data:
                if not isinstance(msg, dict):
                    continue
                tc_list = msg.get("tool_calls")
                if isinstance(tc_list, list):
                    for tc in tc_list:
                        if isinstance(tc, dict):
                            func = tc.get("function") or {}
                            tool_log.append({
                                "name": func.get("name", ""),
                                "args": func.get("arguments", {}),
                            })
    except Exception:
        pass
    return tool_log


# ── 输出格式化 ──

def print_summary(summary: BenchmarkSummary) -> None:
    """打印五层汇总报告。"""
    w = 70
    print(f"\n{'='*w}")
    print(f"  📊 {summary.task_name}  ({summary.task_category})")
    print(f"     {summary.total_runs} runs | 通过 {summary.passed_runs}/{summary.total_runs} "
          f"({summary.pass_rate:.0%})")
    print(f"{'='*w}")

    print(f"\n  ┌──────────┬──────────┬──────────┬──────────┬──────────┐")
    print(f"  │   L1     │   L2     │   L3     │   L4     │  综合    │")
    print(f"  │ 匹配率   │ 质量评分 │ Tokens   │ 工具准确 │ 评分     │")
    print(f"  ├──────────┼──────────┼──────────┼──────────┼──────────┤")
    print(f"  │ {summary.l1_avg_match_rate:6.0%}   │  "
          f"{summary.l2_avg_overall:5.0f}/100 │  "
          f"{summary.l3_median_tokens:5.0f}   │  "
          f"{summary.l4_avg_accuracy:6.0%}   │  "
          f"{summary.composite_median:5.0f}   │")
    print(f"  └──────────┴──────────┴──────────┴──────────┴──────────┘")

    print(f"\n  ⏱️  中位耗时: {summary.l3_median_duration:.1f}s  "
          f"| 💰 中位成本: ${summary.l3_median_cost:.4f}  "
          f"| σ tokens: {summary.l3_stddev_tokens:.0f}")
    if summary.composite_stddev > 0:
        print(f"  📏 综合 σ: {summary.composite_stddev:.1f}  "
              f"(min={min(r['composite_score'] for r in summary.individual_results):.0f}, "
              f"max={max(r['composite_score'] for r in summary.individual_results):.0f})")


def print_all_summaries(summaries: dict[str, BenchmarkSummary]) -> None:
    """打印所有任务的对比总表。"""
    if not summaries:
        print("无结果")
        return

    print(f"\n{'='*90}")
    print(f"  📊 全体 Benchmark 报告")
    print(f"{'='*90}")

    header = (f"{'任务':<16} {'类别':<10} {'通过率':<8} "
              f"{'L2质量':<8} {'中位Tokens':<10} {'中位耗时':<10} {'综合':<8}")
    print(header)
    print("-" * len(header))

    for name, s in sorted(summaries.items()):
        print(
            f"{s.task_name:<16} "
            f"{s.task_category:<10} "
            f"{s.pass_rate:6.0%}  "
            f"{s.l2_avg_overall:6.0f}  "
            f"{s.l3_median_tokens:8.0f}  "
            f"{s.l3_median_duration:8.1f}s "
            f"{s.composite_median:6.0f}"
        )


def save_summary(summary: BenchmarkSummary, task_name: str) -> Path:
    """保存汇总 JSON。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"{task_name}_{ts}.json"
    data = summary.to_dict()
    data["timestamp"] = ts
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 结果已保存: {path}")
    return path


# ── CLI 子命令 ──

def cmd_list() -> None:
    tasks = load_tasks()
    if not tasks:
        print("无可用任务。")
        return

    print(f"\n可用任务 ({len(tasks)}):")
    print("-" * 60)
    for name, task in tasks.items():
        desc = task.get("description", "")
        cat = task.get("category", TASK_CATEGORIES.get(name, ""))
        runs = task.get("runs", 5)
        has_patterns = "✅" if task.get("expected_patterns") else "⚪"
        print(f"  {name:<20} {has_patterns} runs={runs}  [{cat}]  {desc}")


def cmd_run(args) -> None:
    tasks = load_tasks()
    if args.task not in tasks:
        print(f"未知任务: {args.task}")
        print(f"可用: {', '.join(tasks.keys())}")
        sys.exit(1)

    task = tasks[args.task]
    runs = args.runs or task.get("runs", 5)
    fair_mode = args.fair or task.get("fair_mode", False)

    results = run_benchmark_v2(
        task_name=args.task,
        task=task,
        runs=runs,
        config_path=args.config,
        fair_mode=fair_mode,
    )

    task_category = task.get("category", TASK_CATEGORIES.get(args.task, "通用"))
    summary = summarize_runs(
        results, task_name=task.get("name", args.task),
        task_category=task_category,
    )
    print_summary(summary)
    save_summary(summary, args.task)


def cmd_run_all(args) -> None:
    tasks = load_tasks()
    if not tasks:
        print("无可用任务")
        return

    summaries = {}
    for name, task in tasks.items():
        runs = args.runs or task.get("runs", 5)
        fair_mode = args.fair or task.get("fair_mode", False)

        print(f"\n{'#'*60}")
        print(f"### {task.get('name', name)}")
        print(f"{'#'*60}")

        results = run_benchmark_v2(name, task, runs, args.config, fair_mode)
        cat = task.get("category", TASK_CATEGORIES.get(name, "通用"))
        summary = summarize_runs(results, task_name=task.get("name", name),
                                 task_category=cat)
        print_summary(summary)
        save_summary(summary, name)
        summaries[name] = summary

    print_all_summaries(summaries)

    # 保存全局报告
    _save_global_report(summaries)


def cmd_report(args) -> None:
    if not RESULTS_DIR.is_dir():
        print("无历史结果。请先执行 `run`")
        return

    if args.all:
        # 按任务分组取最新
        latest = {}
        for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("task_name", f.stem.rsplit("_", 2)[0])
                if name not in latest:
                    latest[name] = data
            except Exception:
                continue
        if latest:
            print(f"\n最近 {len(latest)} 个任务的报告:\n")
            for name, data in sorted(latest.items()):
                _print_compact_report(data)
        else:
            print("无有效结果")
    else:
        task = args.task
        files = sorted(RESULTS_DIR.glob(f"{task}_*.json"), reverse=True)
        if not files:
            print(f"未找到 {task} 的结果")
            return
        with open(files[0], encoding="utf-8") as fh:
            data = json.load(fh)
        _print_compact_report(data)


def _print_compact_report(data: dict) -> None:
    name = data.get("task_name", "?")
    cat = data.get("task_category", "")
    passed = data.get("passed_runs", 0)
    total = data.get("total_runs", 0)
    cs = data.get("composite_median", 0)
    tk = data.get("l3_median_tokens", 0)
    dur = data.get("l3_median_duration", 0)
    print(f"  {name:<16} [{cat:<8}] "
          f"通过{passed}/{total}  "
          f"综合={cs:.0f}  "
          f"tokens={tk:.0f}  "
          f"{dur:.1f}s")


def cmd_regression(args) -> None:
    """L5: 版本间回归检测。"""
    tasks = load_tasks()
    if not tasks:
        print("无可用任务")
        return

    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)

    # 运行全部基准
    print("🔍 运行回归检测基准...")
    current_summaries = {}
    for name, task in tasks.items():
        runs = task.get("runs", 5)
        fair_mode = task.get("fair_mode", False)
        results = run_benchmark_v2(name, task, runs,
                                   config_path=args.config, fair_mode=fair_mode)
        cat = task.get("category", TASK_CATEGORIES.get(name, "通用"))
        current_summaries[name] = summarize_runs(
            results, task_name=task.get("name", name), task_category=cat)

    # 加载上一版本
    prev_data = {}
    if VERSION_FILE.exists():
        with open(VERSION_FILE, encoding="utf-8") as f:
            prev_data = json.load(f)

    # 对比
    print(f"\n{'='*80}")
    print(f"  📈 回归检测 (L5)")
    print(f"{'='*80}")
    regressions = []
    improvements = []

    for name, curr in sorted(current_summaries.items()):
        prev = prev_data.get(name, {})
        if prev and prev.get("composite_median"):
            delta = curr.composite_median - prev["composite_median"]
            status = "📉" if delta < -5 else ("📈" if delta > 5 else "➡️")
            print(f"  {status} {curr.task_name:<16} "
                  f"{prev['composite_median']:.0f} → {curr.composite_median:.0f}  "
                  f"(Δ={delta:+.1f})")
            if delta < -5:
                regressions.append((name, delta))
            elif delta > 5:
                improvements.append((name, delta))
        else:
            print(f"  🆕 {curr.task_name:<16} 首次基准: 综合={curr.composite_median:.0f}")

    if regressions:
        print(f"\n  ⚠️ 退化任务 ({len(regressions)}):")
        for name, delta in regressions:
            print(f"     - {name}: Δ={delta:+.1f}")
    if improvements:
        print(f"\n  🎉 提升任务 ({len(improvements)}):")
        for name, delta in improvements:
            print(f"     - {name}: Δ={delta:+.1f}")

    # 保存当前版本为基准
    _save_regression_baseline(current_summaries)


def _save_global_report(summaries: dict) -> None:
    """保存全局报告。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"ALL_{ts}.json"
    report = {
        "timestamp": ts,
        "total_tasks": len(summaries),
        "tasks": {name: s.to_dict() for name, s in summaries.items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📁 全局报告: {path}")


def _save_regression_baseline(summaries: dict) -> None:
    """保存当前版本为回归基准。"""
    REGRESSION_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    # 备份旧基准
    if VERSION_FILE.exists():
        backup = REGRESSION_DIR / f"latest_{ts}.json"
        VERSION_FILE.rename(backup)

    baseline = {}
    for name, s in summaries.items():
        baseline[name] = {
            "task_name": s.task_name,
            "task_category": s.task_category,
            "pass_rate": s.pass_rate,
            "composite_median": s.composite_median,
            "composite_stddev": s.composite_stddev,
            "l3_median_tokens": s.l3_median_tokens,
            "l3_median_duration": s.l3_median_duration,
            "l4_avg_accuracy": s.l4_avg_accuracy,
            "timestamp": ts,
        }

    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)
    print(f"\n📁 回归基准已保存: {VERSION_FILE}")


# ── 入口 ──

def main():
    parser = argparse.ArgumentParser(
        description="Agent 五层性能指标基准测试 v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    sub.add_parser("list", help="列出所有任务")

    p_run = sub.add_parser("run", help="执行单个基准任务")
    p_run.add_argument("task", help="任务名")
    p_run.add_argument("--runs", type=int, help="运行次数")
    p_run.add_argument("--config", help="配置文件路径")
    p_run.add_argument("--fair", action="store_true", help="公平模式 (t=0, no-thinking)")

    p_all = sub.add_parser("run-all", help="运行全部基准任务")
    p_all.add_argument("--runs", type=int, help="运行次数")
    p_all.add_argument("--config", help="配置文件路径")
    p_all.add_argument("--fair", action="store_true", help="公平模式")

    p_rep = sub.add_parser("report", help="查看最新报告")
    p_rep.add_argument("task", nargs="?", help="任务名")
    p_rep.add_argument("--all", action="store_true", help="查看全体报告")

    p_reg = sub.add_parser("regression", help="L5 回归检测")
    p_reg.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "run-all":
        cmd_run_all(args)
    elif args.cmd == "report":
        cmd_report(args)
    elif args.cmd == "regression":
        cmd_regression(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

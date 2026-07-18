#!/usr/bin/env python3
"""
@2025-07-19 gen by tea_agent, Agent Token 用量基准测试框架

基于 DB topic_token_stats 查询，无需解析日志文件。

用法:
    python -m benchmark.runner list                        # 列出所有任务
    python -m benchmark.runner run <task> [--runs N]       # 执行任务 N 次
    python -m benchmark.runner run <task> --no-thinking    # 关闭 thinking
    python -m benchmark.runner compare <task>              # 对比历史结果

输出示例:
    Task: 写排序函数 (runs=3)
    ┌───────┬─────────────────────┬─────────────────────┬──────────┐
    │  Run  │  主模型 (in/out)    │  便宜模型 (in/out)  │ 总tokens │
    ├───────┼─────────────────────┼─────────────────────┼──────────┤
    │  #1   │  in=1234,out=567    │  in=0,out=0         │   1801   │
    │  #2   │  in=1190,out=520    │  in=0,out=0         │   1710   │
    │  #3   │  in=1210,out=550    │  in=0,out=0         │   1760   │
    ├───────┼─────────────────────┼─────────────────────┼──────────┤
    │  Avg  │  in=1211,out=546    │  in=0,out=0         │   1757   │
    └───────┴─────────────────────┴─────────────────────┴──────────┘
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import yaml

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("benchmark")

TASKS_DIR = Path(__file__).parent / "tasks"
RESULTS_DIR = Path(__file__).parent / "results"


def load_tasks() -> dict[str, dict]:
    """加载所有任务 YAML 文件。"""
    tasks = {}
    if not TASKS_DIR.is_dir():
        return tasks
    for f in sorted(TASKS_DIR.glob("*.yaml")):
        with open(f, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            name = f.stem
            tasks[name] = data
    return tasks


def run_benchmark(
    task_name: str,
    task: dict,
    runs: int,
    config_path: str | None = None,
    enable_thinking: bool | None = None,
) -> list[dict]:
    """执行基准测试，返回每次运行的结果列表。

    Args:
        task_name: 任务名
        task: 任务定义 {"name","description","prompt","runs"}
        runs: 运行次数
        config_path: 配置文件路径，None=默认
        enable_thinking: 覆盖 thinking 开关，None=使用默认

    Returns:
        [{"run":1, "topic_id":"...", "major":{"in":N,"out":N},
          "cheap":{"in":N,"out":N}, "total":N, "duration_s":N}, ...]
    """
    from tea_agent.agent import Agent

    results = []
    task_prompt = task["prompt"]
    task_title = task.get("name", task_name)

    for run_idx in range(1, runs + 1):
        topic_id = str(uuid.uuid4())
        label = f"[{task_name}] run {run_idx}/{runs}"

        print(f"\n{'='*60}")
        print(f"  {label}: 开始执行")
        print(f"{'='*60}")

        # 创建 Agent（full 模式，带 storage，token 统计写入 DB）
        agent = Agent(
            mode="full",
            config_path=config_path,
            enable_thinking=enable_thinking,
        )

        # 创建主题
        agent._db.create_topic(f"{task_title} #{run_idx}", topic_id)
        agent.current_topic_id = topic_id

        t0 = time.monotonic()

        try:
            # 发送任务，等待完成
            result = agent.chat(task_prompt, topic_id=topic_id)

            # 提取 AI 回复
            ai_msg = ""
            if isinstance(result, list):
                for msg in result:
                    if msg.get("role") == "assistant":
                        ai_msg = msg.get("content", "")
                        break

            # 从 DB 查询 token 统计
            stats = agent._db.get_topic_tokens(topic_id)

            major_in = stats.get("total_prompt_tokens", 0)
            major_out = stats.get("total_completion_tokens", 0)
            cheap_in = stats.get("total_cheap_prompt_tokens", 0)
            cheap_out = stats.get("total_cheap_completion_tokens", 0)
            total = stats.get("total_tokens", 0) + stats.get("total_cheap_tokens", 0)

            duration = time.monotonic() - t0

            run_result = {
                "run": run_idx,
                "topic_id": topic_id,
                "major": {"in": major_in, "out": major_out},
                "cheap": {"in": cheap_in, "out": cheap_out},
                "total_tokens": total,
                "duration_s": round(duration, 1),
                "ai_preview": ai_msg[:200] if ai_msg else "(empty)",
            }
            results.append(run_result)

            print(f"  ✅ 完成 | 主模型 in={major_in},out={major_out} | "
                  f"便宜 in={cheap_in},out={cheap_out} | "
                  f"总 {total} tokens | {duration:.1f}s")

        except Exception as e:
            logger.exception(f"Run {run_idx} 失败")
            results.append({
                "run": run_idx,
                "topic_id": topic_id,
                "error": str(e),
                "duration_s": round(time.monotonic() - t0, 1),
            })
            print(f"  ❌ 失败: {e}")

    return results


def print_table(results: list[dict], task_name: str) -> None:
    """打印对比表格。"""
    if not results:
        print("无结果")
        return

    valid = [r for r in results if "error" not in r]
    if not valid:
        print("所有运行均失败")
        return

    print(f"\n{'='*80}")
    print(f"  Benchmark: {task_name}")
    print(f"{'='*80}")

    # 表头
    header = (
        f"{'Run':<8} {'主模型(in/out)':<24} {'便宜模型(in/out)':<24} "
        f"{'总tokens':<10} {'耗时':<10}"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    sum_major_in = 0
    sum_major_out = 0
    sum_cheap_in = 0
    sum_cheap_out = 0
    sum_total = 0
    sum_dur = 0.0

    for r in valid:
        mi, mo = r["major"]["in"], r["major"]["out"]
        ci, co = r["cheap"]["in"], r["cheap"]["out"]
        tt = r["total_tokens"]
        dur = r["duration_s"]

        sum_major_in += mi
        sum_major_out += mo
        sum_cheap_in += ci
        sum_cheap_out += co
        sum_total += tt
        sum_dur += dur

        print(
            f"  #{r['run']:<6} "
            f"in={mi:<6},out={mo:<6}     "
            f"in={ci:<6},out={co:<6}     "
            f"{tt:<10} {dur:<8.1f}s"
        )

    n = len(valid)
    avg_mi = sum_major_in // n
    avg_mo = sum_major_out // n
    avg_ci = sum_cheap_in // n
    avg_co = sum_cheap_out // n
    avg_tt = sum_total // n
    avg_dur = sum_dur / n

    print(sep)
    print(
        f"  {'Avg':<6}  "
        f"in={avg_mi:<6},out={avg_mo:<6}     "
        f"in={avg_ci:<6},out={avg_co:<6}     "
        f"{avg_tt:<10} {avg_dur:<8.1f}s"
    )

    # 方差
    if n > 1:
        var_total = sum((r["total_tokens"] - avg_tt) ** 2 for r in valid) / n
        print(f"\n  总 tokens 标准差: {var_total**0.5:.0f}  "
              f"(min={min(r['total_tokens'] for r in valid)}, "
              f"max={max(r['total_tokens'] for r in valid)})")


def save_results(task_name: str, results: list[dict], extra: dict = None) -> Path:
    """保存结果到 JSON 文件。"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"{task_name}_{ts}.json"
    data = {
        "task": task_name,
        "timestamp": ts,
        "results": results,
    }
    if extra:
        data["extra"] = extra
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 结果已保存: {path}")
    return path


def cmd_list() -> None:
    """列出所有可用任务。"""
    tasks = load_tasks()
    if not tasks:
        print("无可用任务。请在 benchmark/tasks/ 下创建 .yaml 文件")
        return

    print(f"\n可用任务 ({len(tasks)}):")
    print("-" * 50)
    for name, task in tasks.items():
        desc = task.get("description", "(无描述)")
        default_runs = task.get("runs", 1)
        print(f"  {name:<20} runs={default_runs}  {desc}")


def cmd_run(args) -> None:
    """执行基准测试。"""
    tasks = load_tasks()
    if args.task not in tasks:
        print(f"未知任务: {args.task}")
        print(f"可用: {', '.join(tasks.keys())}")
        sys.exit(1)

    task = tasks[args.task]
    runs = args.runs if args.runs else task.get("runs", 3)

    thinking = None
    if hasattr(args, "no_thinking") and args.no_thinking:
        thinking = False

    results = run_benchmark(
        task_name=args.task,
        task=task,
        runs=runs,
        config_path=args.config,
        enable_thinking=thinking,
    )

    print_table(results, task.get("name", args.task))
    save_results(args.task, results, extra={
        "config": args.config or "default",
        "thinking": thinking if thinking is not None else "default",
    })


def cmd_compare(args) -> None:
    """对比历史 benchmark 结果。"""
    if not RESULTS_DIR.is_dir():
        print("无历史结果。请先执行 `python -m benchmark.runner run <task>`")
        return

    files = sorted(RESULTS_DIR.glob(f"{args.task}_*.json"), reverse=True)
    if not files:
        print(f"未找到 {args.task} 的历史结果")
        return

    print(f"\n找到 {len(files)} 个历史结果:\n")
    for f in files[:10]:  # 最近 10 个
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        results = data.get("results", [])
        extra = data.get("extra", {})
        valid = [r for r in results if "error" not in r]
        if not valid:
            continue
        avg_total = sum(r["total_tokens"] for r in valid) // len(valid)
        avg_dur = sum(r["duration_s"] for r in valid) / len(valid)
        cfg = extra.get("config", "default")
        thinking = extra.get("thinking", "default")
        print(
            f"  {f.stem:<40} "
            f"avg_tokens={avg_total:<6} avg_dur={avg_dur:.1f}s  "
            f"config={cfg} thinking={thinking}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Agent Token 用量基准测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", help="子命令")

    # list
    sub.add_parser("list", help="列出所有任务")

    # run
    p_run = sub.add_parser("run", help="执行基准测试")
    p_run.add_argument("task", help="任务名（不含 .yaml）")
    p_run.add_argument("--runs", type=int, help="运行次数（覆盖任务默认值）")
    p_run.add_argument("--config", help="配置文件路径")
    p_run.add_argument("--no-thinking", action="store_true", help="关闭 thinking")

    # compare
    p_cmp = sub.add_parser("compare", help="对比历史结果")
    p_cmp.add_argument("task", help="任务名")

    args = parser.parse_args()

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "compare":
        cmd_compare(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

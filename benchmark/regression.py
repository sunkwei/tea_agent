"""
@2026-07-19 gen by claude, 版本间回归追踪 — L5 进化稳定性

独立于 runner，可被 CI/CD 调用：
    python -m benchmark.regression          # 检测当前 vs 上一版本
    python -m benchmark.regression --ci     # CI 模式（JSON 输出，exit code）
    python -m benchmark.regression --history # 查看历史趋势

基线存储于 benchmark/regression/
  - latest.json — 最新版本的基准分数
  - latest_YYYYMMDD_HHMMSS.json — 历史备份
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

REGRESSION_DIR = Path(__file__).parent / "regression"
RESULTS_DIR = Path(__file__).parent / "results"
VERSION_FILE = REGRESSION_DIR / "latest.json"


def load_baseline() -> dict | None:
    if VERSION_FILE.exists():
        with open(VERSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def load_latest_results() -> dict[str, dict]:
    """加载各任务的最新 benchmark 结果。"""
    latest = {}
    if not RESULTS_DIR.is_dir():
        return latest
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            name = data.get("task_name", f.stem.rsplit("_", 2)[0])
            if name not in latest and name != "ALL":
                latest[name] = data
        except Exception:
            continue
    return latest


def detect_regressions(
    baseline: dict, current: dict, threshold: float = 5.0
) -> dict:
    """检测退化。返回 {task: delta} only for regressed tasks."""
    regressions = {}
    improvements = {}
    stable = {}

    for name, curr in current.items():
        prev = baseline.get(name)
        if not prev or "composite_median" not in prev:
            continue

        delta = curr.get("composite_median", 0) - prev["composite_median"]
        if delta < -threshold:
            regressions[name] = round(delta, 1)
        elif delta > threshold:
            improvements[name] = round(delta, 1)
        else:
            stable[name] = round(delta, 1)

    new_tasks = [n for n in current if n not in baseline]
    removed_tasks = [n for n in baseline if n not in current]

    return {
        "regressions": regressions,
        "improvements": improvements,
        "stable": stable,
        "new_tasks": new_tasks,
        "removed_tasks": removed_tasks,
        "has_regression": len(regressions) > 0,
    }


def print_regression_report(report: dict) -> None:
    print(f"\n{'='*70}")
    print(f"  📈 回归检测报告")
    print(f"{'='*70}")

    if report["regressions"]:
        print(f"\n  ⚠️ 退化 ({len(report['regressions'])} 项):")
        for name, delta in sorted(report["regressions"].items(), key=lambda x: x[1]):
            print(f"     📉 {name:<20} Δ={delta:+.1f}")

    if report["improvements"]:
        print(f"\n  🎉 提升 ({len(report['improvements'])} 项):")
        for name, delta in sorted(report["improvements"].items(),
                                  key=lambda x: -x[1]):
            print(f"     📈 {name:<20} Δ={delta:+.1f}")

    if report["stable"]:
        print(f"\n  ➡️ 稳定 ({len(report['stable'])} 项):")
        for name, delta in sorted(report["stable"].items()):
            print(f"     {name:<20} Δ={delta:+.1f}")

    if report["new_tasks"]:
        print(f"\n  🆕 新任务 ({len(report['new_tasks'])} 项): "
              f"{', '.join(report['new_tasks'])}")

    if report["removed_tasks"]:
        print(f"\n  🗑️ 移除任务 ({len(report['removed_tasks'])} 项): "
              f"{', '.join(report['removed_tasks'])}")

    if not any([report["regressions"], report["improvements"],
                report["new_tasks"], report["removed_tasks"]]):
        print("\n  ✅ 无变化")


def show_history() -> None:
    """显示历史趋势。"""
    if not REGRESSION_DIR.is_dir():
        print("无历史记录")
        return

    snapshots = sorted(REGRESSION_DIR.glob("latest_*.json"))
    if not snapshots:
        print("无历史快照")
        return

    print(f"\n历史快照 ({len(snapshots)}):")
    print(f"{'时间':<20} {'任务数':<8} {'平均综合分':<12}")
    print("-" * 46)

    for snap in snapshots:
        ts = snap.stem.replace("latest_", "")
        with open(snap, encoding="utf-8") as f:
            data = json.load(f)
        n = len(data)
        avg = sum(v.get("composite_median", 0) for v in data.values()) / max(n, 1)
        print(f"{ts:<20} {n:<8} {avg:8.1f}")

    # 最新趋势
    if VERSION_FILE.exists():
        with open(VERSION_FILE, encoding="utf-8") as f:
            latest = json.load(f)
        print(f"\n{'当前':<20} {len(latest):<8} "
              f"{sum(v.get('composite_median', 0) for v in latest.values()) / max(len(latest), 1):8.1f}")


def main():
    parser = argparse.ArgumentParser(description="L5 回归检测")
    parser.add_argument("--ci", action="store_true", help="CI 模式")
    parser.add_argument("--history", action="store_true", help="查看历史趋势")
    parser.add_argument("--threshold", type=float, default=5.0,
                        help="退化阈值（综合分差值），默认 5.0")
    args = parser.parse_args()

    if args.history:
        show_history()
        return

    baseline = load_baseline()
    current = load_latest_results()

    if not baseline:
        print("无基线数据，跳过回归检测。")
        print("请先运行: python -m benchmark.runner regression")
        sys.exit(0)

    if not current:
        print("无当前结果，请先运行: python -m benchmark.runner run-all --fair")
        sys.exit(1)

    report = detect_regressions(baseline, current, args.threshold)

    if args.ci:
        # CI 模式: JSON 输出
        output = {
            "has_regression": report["has_regression"],
            "regressions": report["regressions"],
            "improvements": report["improvements"],
            "stable_count": len(report["stable"]),
            "new_tasks": report["new_tasks"],
            "timestamp": datetime.now().isoformat(),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        sys.exit(1 if report["has_regression"] else 0)
    else:
        print_regression_report(report)
        if report["has_regression"]:
            print("\n  ⚠️ 检测到退化！请在发布前检查。")

    sys.exit(0)


if __name__ == "__main__":
    main()

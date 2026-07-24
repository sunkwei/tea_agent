#!/usr/bin/env python3
"""
SWE-bench 适配运行器 — 在 tea_agent 环境中评测 Agent 解决真实 GitHub Issue 的能力。

用法:
    python -m benchmark.run_swe_bench list                     # 列出可用任务
    python -m benchmark.run_swe_bench info <instance_id>       # 查看任务详情
    python -m benchmark.run_swe_bench solve <instance_id>      # 尝试解决任务
    python -m benchmark.run_swe_bench verify <instance_id>     # 验证解决方案
    python -m benchmark.run_swe_bench run <n>                  # 连续运行 n 个任务并统计

依赖:
    pip install datasets swebench
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def get_dataset():
    """加载 SWE-bench 数据集 (lazy load)。"""
    from datasets import load_dataset
    return load_dataset("princeton-nlp/SWE-bench", split="test")


def cmd_list():
    """列出所有可用任务。"""
    ds = get_dataset()
    print(f"SWE-bench 测试集: {len(ds)} 个实例\n")
    repos = {}
    for inst in ds:
        repos[inst["repo"]] = repos.get(inst["repo"], 0) + 1
    for r, c in sorted(repos.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c} 个任务")


def cmd_info(instance_id: str):
    """显示任务详情。"""
    ds = get_dataset()
    for inst in ds:
        if inst["instance_id"] == instance_id:
            print(f"Instance ID: {inst['instance_id']}")
            print(f"Repo: {inst['repo']}")
            print(f"Base Commit: {inst['base_commit']}")
            print(f"\n{'='*60}")
            print("PROBLEM STATEMENT:")
            print(f"{'='*60}")
            print(inst["problem_statement"])
            if inst.get("hints_text"):
                print(f"\n{'='*60}")
                print("HINTS:")
                print(f"{'='*60}")
                print(inst["hints_text"])
            print(f"\n{'='*60}")
            print("EXPECTED PATCH:")
            print(f"{'='*60}")
            print(inst["patch"])
            return
    print(f"未找到任务: {instance_id}")


def cmd_solve(instance_id: str):
    """尝试解决 SWE-bench 任务。"""
    ds = get_dataset()
    inst = None
    for item in ds:
        if item["instance_id"] == instance_id:
            inst = item
            break
    if not inst:
        print(f"未找到任务: {instance_id}")
        return

    repo_url = f"https://github.com/{inst['repo']}.git"
    commit = inst["base_commit"]
    workdir = Path(tempfile.mkdtemp(prefix=f"swe_{instance_id}_"))
    
    print(f"📦 克隆 {inst['repo']} @ {commit[:8]}...")
    subprocess.run(
        ["git", "clone", repo_url, str(workdir / "repo")],
        capture_output=True, text=True, check=True
    )
    subprocess.run(
        ["git", "checkout", commit],
        cwd=str(workdir / "repo"),
        capture_output=True, text=True, check=True
    )
    
    print(f"📄 任务: {inst['problem_statement'][:200]}...")
    print(f"\n🔍 需要定位并修复问题。请使用 toolkit 工具进行操作。")
    print(f"\n💡 提示: 仓库已克隆到 {workdir / 'repo'}")
    print(f"   期望的 patch 可通过 benchmark.run_swe_bench info {instance_id} 查看")
    
    return str(workdir)


def cmd_verify(instance_id: str, repo_path: str = None):
    """验证解决方案是否与期望 patch 匹配。"""
    ds = get_dataset()
    inst = None
    for item in ds:
        if item["instance_id"] == instance_id:
            inst = item
            break
    if not inst:
        print(f"未找到任务: {instance_id}")
        return

    if not repo_path:
        repo_path = f"tmp/{instance_id}"
    
    result = subprocess.run(
        ["git", "diff"],
        cwd=repo_path,
        capture_output=True, text=True
    )
    actual_patch = result.stdout.strip()
    expected_patch = inst["patch"].strip()
    
    if actual_patch == expected_patch:
        print(f"✅ 完全匹配! 解决方案与 SWE-bench 期望补丁一致。")
        return True
    else:
        print(f"⚠️  不完全匹配。")
        print(f"\n实际补丁 ({len(actual_patch.split(chr(10)))} 行):")
        print(actual_patch[:500])
        print(f"\n期望补丁 ({len(expected_patch.split(chr(10)))} 行):")
        print(expected_patch[:500])
        return False


def cmd_run(n: int = 3):
    """连续运行多个 SWE-bench 任务并进行统计。"""
    ds = get_dataset()
    results = {"passed": 0, "failed": 0, "skipped": 0}
    
    for i in range(min(n, len(ds))):
        inst = ds[i]
        print(f"\n{'='*60}")
        print(f"任务 {i+1}/{n}: {inst['instance_id']}")
        print(f"{'='*60}")
        print(f"  仓库: {inst['repo']}")
        print(f"  Commit: {inst['base_commit'][:8]}")
        print(f"  描述: {inst['problem_statement'][:100]}...")
        
        # 未来: 调用 Agent 自动解决
        # 目前仅输出信息
        results["skipped"] += 1
    
    print(f"\n{'='*60}")
    print(f"运行统计: 通过={results['passed']}, 失败={results['failed']}, 跳过={results['skipped']}")


def main():
    parser = argparse.ArgumentParser(
        description="SWE-bench 适配运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")
    
    sub.add_parser("list", help="列出所有 SWE-bench 任务")
    
    p_info = sub.add_parser("info", help="查看任务详情")
    p_info.add_argument("instance_id", help="任务 ID (如 django__django-13413)")
    
    p_solve = sub.add_parser("solve", help="尝试解决任务")
    p_solve.add_argument("instance_id", help="任务 ID")
    
    p_verify = sub.add_parser("verify", help="验证解决方案")
    p_verify.add_argument("instance_id", help="任务 ID")
    p_verify.add_argument("--repo", help="仓库路径")
    
    p_run = sub.add_parser("run", help="连续运行多个任务")
    p_run.add_argument("n", type=int, default=3, nargs="?", help="任务数")
    
    args = parser.parse_args()
    
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "info":
        cmd_info(args.instance_id)
    elif args.cmd == "solve":
        cmd_solve(args.instance_id)
    elif args.cmd == "verify":
        cmd_verify(args.instance_id, args.repo)
    elif args.cmd == "run":
        cmd_run(args.n)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

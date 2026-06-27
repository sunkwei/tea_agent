#!/usr/bin/env python3
"""
定期清理过时临时文件和构建产物。
由 toolkit_scheduler 周期性触发。
"""
import os, time, shutil, glob, sys, json
from pathlib import Path
from datetime import datetime

# 配置
HOME = Path.home()
PROJECT = Path.cwd()
DAYS_OLD = 3  # 清理 N 天前的文件
LOG_DIR = PROJECT / ".tea_agent_run"
LOG_FILE = LOG_DIR / "cleanup_log.json"

# 清理规则: (路径模式, 是否目录, 描述)
RULES = [
    # 备份文件
    (str(PROJECT / "**/*.bak*"), False, "备份文件"),
    (str(PROJECT / "**/*.bak"), False, "备份文件"),
    # Python 缓存
    (str(PROJECT / "**/__pycache__"), True, "Python缓存"),
    # 构建产物
    (str(PROJECT / "build"), True, "构建目录"),
    (str(PROJECT / "dist"), True, "分发包目录"),
    (str(PROJECT / "*.egg-info"), True, "egg-info目录"),
    # 项目运行时缓存
    (str(PROJECT / ".tea_agent_run/plans/*.json"), False, "过期计划文件"),
]


def scan() -> list:
    """扫描过时文件，返回 [(路径, 大小, 天数, 描述)]"""
    now = time.time()
    cutoff = now - DAYS_OLD * 86400
    found = []

    for pattern, is_dir, desc in RULES:
        for p in glob.glob(pattern, recursive=is_dir):
            pp = Path(p)
            if is_dir and pp.is_dir():
                mtime = pp.stat().st_mtime
                if mtime < cutoff:
                    size = sum(f.stat().st_size for f in pp.rglob("*") if f.is_file())
                    age = (now - mtime) / 86400
                    found.append((str(pp), size, age, desc))
            elif not is_dir and pp.is_file():
                mtime = pp.stat().st_mtime
                if mtime < cutoff:
                    size = pp.stat().st_size
                    age = (now - mtime) / 86400
                    found.append((str(pp), size, age, desc))

    return found


def clean(items: list, dry_run: bool = False) -> dict:
    """执行清理，返回统计"""
    result = {
        "time": datetime.now().isoformat(),
        "dry_run": dry_run,
        "cleaned_count": 0,
        "cleaned_size": 0,
        "errors": [],
        "items": [],
    }

    for path_str, size, age, desc in items:
        if dry_run:
            result["items"].append({"path": path_str, "size": size, "age_days": round(age, 1), "desc": desc})
            continue
        try:
            pp = Path(path_str)
            if pp.is_dir():
                shutil.rmtree(pp)
            else:
                pp.unlink()
            result["cleaned_count"] += 1
            result["cleaned_size"] += size
            result["items"].append({"path": path_str, "size": size, "age_days": round(age, 1), "status": "deleted"})
        except Exception as e:
            result["errors"].append({"path": path_str, "error": str(e)})

    return result


def log_result(result: dict):
    """记录清理结果到日志"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    history = []
    if LOG_FILE.exists():
        try:
            history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except:
            pass
    history.append(result)
    if len(history) > 30:
        history = history[-30:]
    LOG_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print(f"🔍 扫描过时文件（{DAYS_OLD} 天前）...")
    items = scan()

    if not items:
        print("✅ 没有需要清理的过时文件")
        log_result({"time": datetime.now().isoformat(), "dry_run": dry_run,
                     "cleaned_count": 0, "cleaned_size": 0, "message": "nothing to clean"})
        return

    print(f"  发现 {len(items)} 个过时项目:")
    for path, size, age, desc in items:
        size_str = f"{size/1024:.1f}KB" if size > 0 else "目录"
        print(f"    {desc:12s} {age:.1f}d  {size_str:>8s}  {path}")

    if dry_run:
        print(f"\n⚠ 预览模式（--dry-run），未实际删除")
        print(f"  共可释放 {sum(s for _,s,_,_ in items)/1024:.0f}KB 空间")
        log_result({"time": datetime.now().isoformat(), "dry_run": True, "items": items})
        return

    result = clean(items)
    print(f"\n🧹 清理完成: {result['cleaned_count']} 项, {result['cleaned_size']/1024:.0f}KB 已释放")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ⚠ 错误: {e['path']} → {e['error']}")

    log_result(result)


if __name__ == "__main__":
    main()

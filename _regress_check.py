"""决定性实验：11 个失败是既有问题，还是我引入的回归？

做法：把 4 个被改源文件临时切回 92d29a8（本会话前的真实提交），跑测试，
再切回 HEAD（含我的修复）。用同一进程内 subprocess 保证顺序与还原。
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = [
    "tea_agent/agent.py",
    "tea_agent/agent_background.py",
    "tea_agent/store/_interruptions.py",
    "tea_agent/store/_core.py",
]
TEST = "tea_agent/tests/test_interruption_knowledge.py"
BACKUP_DIR = ROOT / "_regress_bak"


def run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)


def run_pytest() -> str:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", TEST, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600,
    )
    tail = [ln for ln in (r.stdout or "").splitlines()
            if "passed" in ln or "failed" in ln]
    return tail[-1] if tail else (r.stdout or "")[-300:]


report: dict = {}

# 1) 备份我当前（HEAD 快照）版本
BACKUP_DIR.mkdir(exist_ok=True)
for f in FILES:
    shutil.copy2(ROOT / f, BACKUP_DIR / Path(f).name)
report["backed_up"] = [Path(f).name for f in FILES]

# 2) 切回 92d29a8（本会话前）
r1 = run_git("checkout", "92d29a8", "--", *FILES)
report["checkout_old_rc"] = r1.returncode
report["checkout_old_err"] = (r1.stderr or "")[:200]

# 3) 旧代码下跑测试
report["OLD_result"] = run_pytest()

# 4) 还原我的版本
r2 = run_git("checkout", "HEAD", "--", *FILES)
report["restore_rc"] = r2.returncode
# 若 HEAD 版本与备份不一致，用备份覆盖（更稳）
for f in FILES:
    bak = BACKUP_DIR / Path(f).name
    if bak.exists():
        shutil.copy2(bak, ROOT / f)
report["restored"] = True

# 5) 我的代码下跑测试
report["MINE_result"] = run_pytest()

# 6) 若文件内容与备份一致，清理备份
ok = all((ROOT / f).read_bytes() == (BACKUP_DIR / Path(f).name).read_bytes()
         for f in FILES)
report["files_match_backup"] = ok
if ok:
    shutil.rmtree(BACKUP_DIR, ignore_errors=True)

(ROOT / "_regress_verdict.json").write_text(
    __import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(__import__("json").dumps(report, ensure_ascii=False, indent=2))

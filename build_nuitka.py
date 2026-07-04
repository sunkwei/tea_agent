"""
build_nuitka.py — 将 tea_agent_mini 编译为单文件可执行文件。

用法：
    python build_nuitka.py                    # 单文件 .exe (Windows) / ELF (Linux)
    python build_nuitka.py --standalone       # 目录模式（调试用，编译更快）
    python build_nuitka.py --clean            # 清理构建产物

依赖：
    pip install nuitka build
    Windows: Visual Studio Build Tools (cl.exe)
    Linux:   gcc / clang

原理：
    1. 先用 build_mini.py 生成无 NumPy 的纯净 Mini 包
    2. 用 Nuitka 将 Python 编译为 C，再链接为单文件可执行文件
    3. 输出：build_nuitka_dist/tea-agent-mini[.exe]

限制：
    - 编译耗时较长（5-30 分钟，取决于机器和项目大小）
    - 推荐直接运行 build_mini.py 生成的 wheel 包（pip install）
    - Nuitka 单文件模式适合分发给无 Python 环境的用户
"""

import os, shutil, subprocess, sys, platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build_nuitka_dist"
MINI_BUILD = ROOT / "build_mini_dist"

# 需要排除的重型模块（Mini 版不包含）
BLOCKLIST = [
    "playwright", "pywebview", "webview",
    "PyQt5", "PyQt6", "tkinter",
    "PIL", "mss", "pyautogui", "clr_loader",
    "pythonnet", "black", "ruff", "celery",
    "IPython", "jedi", "parso",
    "cffi", "pycparser",
]


def step(msg):
    """Print a formatted step header."""
    print()
    print("=" * 60)
    print(f"  {msg}")
    print("=" * 60)


def build_mini():
    """Step 1: Build tea_agent_mini wheel package."""
    step("Step 1/3: 构建 tea_agent_mini 基础包")

    mini_script = ROOT / "build_mini.py"
    if not mini_script.exists():
        print("  ❌ build_mini.py 未找到")
        return False

    r = subprocess.run(
        [sys.executable, str(mini_script)],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr)
        print("  ❌ build_mini.py 失败")
        return False

    # 确认产物存在
    pkg_dir = MINI_BUILD / "tea_agent"
    if not pkg_dir.exists():
        print(f"  ❌ tea_agent 包未生成于 {pkg_dir}")
        return False

    tool_count = len(list(pkg_dir.rglob("toolkit/toolkit_*.py")))
    print(f"  ✅ tea_agent package ({tool_count} tools)")
    print(f"  ✅ tea_agent_mini wrapper")
    return True


def prepare_nuitka_source():
    """Step 2: 准备 Nuitka 编译目录和入口文件。"""
    step("Step 2/3: 准备 Nuitka 编译源文件")

    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    # 拷贝 Mini 版 tea_agent 包（无 numpy 的纯净版）
    src_pkg = MINI_BUILD / "tea_agent"
    dst_pkg = BUILD / "tea_agent"
    shutil.copytree(src_pkg, dst_pkg)
    print(f"  ✅ 复制 tea_agent 包 ({len(list(dst_pkg.rglob('*.py')))} .py 文件)")

    # 拷贝 tea_agent_mini wrapper
    src_wrapper = MINI_BUILD / "tea_agent_mini"
    if not src_wrapper.exists():
        src_wrapper = ROOT / "tea_agent_mini"
    if src_wrapper.exists():
        dst_wrapper = BUILD / "tea_agent_mini"
        shutil.copytree(src_wrapper, dst_wrapper)
        print(f"  ✅ 复制 tea_agent_mini wrapper")

    # 创建入口文件
    entry = BUILD / "entry_server.py"
    entry.write_text(
        '"""Tea Agent Mini — Nuitka 入口。启动 Web Server。"""\n'
        "import sys\n"
        "from tea_agent.server import main\n"
        "sys.exit(main())\n",
        encoding="utf-8"
    )
    print(f"  ✅ 创建入口文件: {entry.name}")
    return entry


def run_nuitka(entry_script, standalone=False):
    """Step 3: 执行 Nuitka 编译。"""
    step("Step 3/3: 执行 Nuitka 编译（可能需要 5-30 分钟）")

    is_win = platform.system() == "Windows"
    out_name = "tea-agent-mini.exe" if is_win else "tea-agent-mini"

    cmd = [
        sys.executable, "-m", "nuitka",
        "--assume-yes-for-downloads",
        "--enable-plugin=no-qt",
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-setuptools-mode=nofollow",
    ]

    # 排除重型模块
    for mod in BLOCKLIST:
        cmd.append(f"--nofollow-import-to={mod}")

    # 包含 tea_agent 包
    cmd.append("--include-package=tea_agent")

    # 包含静态资源
    static_src = str(ROOT / "tea_agent" / "server" / "static")
    skills_src = str(ROOT / "tea_agent" / "skills")
    cmd.append(f"--include-data-dir={static_src}=tea_agent/server/static")
    cmd.append(f"--include-data-dir={skills_src}=tea_agent/skills")

    # 输出设置
    cmd.append(f"--output-dir={BUILD}")
    cmd.append(f"--output-filename={out_name}")
    cmd.append("--jobs=8")  # 并行编译

    if standalone:
        cmd.append("--standalone")
        print("  模式: standalone（目录，调试用）")
    else:
        cmd.append("--onefile")
        print("  模式: onefile（单文件，分发用）")

    cmd.append(str(entry_script))

    print(f"  目标: {out_name}")
    print(f"  开始编译...")

    r = subprocess.run(
        cmd, cwd=str(BUILD),
        capture_output=True, text=True,
        timeout=1800  # 30 分钟硬限制
    )

    # 输出最后部分
    for label, output in [("STDOUT", r.stdout), ("STDERR", r.stderr)]:
        lines = output.strip().splitlines()
        if lines:
            tail = lines[-20:]
            print(f"  {label} (最后 {len(tail)} 行):")
            for line in tail:
                print(f"    {line}")

    if r.returncode != 0:
        print(f"\n  ❌ Nuitka 编译失败 (rc={r.returncode})")
        print(f"  日志: {BUILD / 'nuitka-crash-report.xml'}")
        return None

    # 查找输出文件
    output_dir = BUILD / (f"{entry_script.stem}.dist" if standalone else "")
    if not output_dir.exists():
        output_dir = BUILD

    binaries = []
    for pattern in ["*.exe", "*.bin", out_name]:
        for f in output_dir.rglob(pattern):
            if f.is_file() and f.stat().st_size > 1024 * 1024:  # >1MB
                binaries.append(f)

    if not binaries:
        binaries = [f for f in output_dir.iterdir()
                     if f.is_file() and f.stat().st_size > 1024 * 1024]

    if binaries:
        binary = max(binaries, key=lambda f: f.stat().st_size)
        size_mb = binary.stat().st_size / (1024 * 1024)
        print(f"\n  ✅ 编译成功!")
        print(f"     文件: {binary}")
        print(f"     大小: {size_mb:.1f} MB")
        return binary

    print("  ⚠️ 编译完成但未找到输出文件")
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="将 tea_agent_mini 编译为单文件可执行文件"
    )
    parser.add_argument("--standalone", action="store_true",
                        help="standalone 目录模式（编译更快，适合调试）")
    parser.add_argument("--clean", action="store_true",
                        help="清理构建产物")
    parser.add_argument("--skip-mini", action="store_true",
                        help="跳过 build_mini.py（复用已有目录）")
    args = parser.parse_args()

    if args.clean:
        if BUILD.exists():
            shutil.rmtree(BUILD)
            print(f"已清理 {BUILD}")
        return

    if not args.skip_mini and not build_mini():
        return 1

    if not MINI_BUILD.exists():
        print("❌ 请先运行 build_mini.py")
        return 1

    entry = prepare_nuitka_source()
    binary = run_nuitka(entry, standalone=args.standalone)

    if binary:
        print()
        print("=" * 60)
        print(f"  ✅ Tea Agent Mini 单文件可执行文件")
        print(f"     路径: {binary}")
        print(f"     大小: {binary.stat().st_size / 1024 / 1024:.1f} MB")
        print()
        print(f"  运行方式:")
        print(f"     {binary} [--port PORT] [--host HOST]")
        print(f"     {binary} --help")
        print("=" * 60)
        return 0
    else:
        print()
        print("  💡 提示: Nuitka 编译大型项目耗时较长。")
        print("     如果不需要单文件分发，推荐直接使用:")
        print(f"     pip install {MINI_BUILD / 'dist' / '*.whl'}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

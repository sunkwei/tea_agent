#!/usr/bin/env python
"""生成 docs/TOOLS.md 工具清单快照。

口径与 AGENTS.md「快速命令 · 口径核查」一致（同一事实源）:
    registered  = len(Toolkit().func_map)
    llm_visible = len(llm_tool_names(func_map))

注意: Toolkit() 会同时加载内置目录（tea_agent/toolkit/）与用户目录
（~/.tea_agent/toolkit/）的工具，因此快照 = 「内置工具 + 生成时的用户目录扩展」。
工具增删后必须重跑本脚本；不要手编 docs/TOOLS.md。

用法:
    python scripts/gen_tools_doc.py           # 重新生成 docs/TOOLS.md
    python scripts/gen_tools_doc.py --check   # 仅校验一致性（CI 用），不一致退出码 1
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tea_agent.tlk import Toolkit, llm_tool_names  # noqa: E402

DOC = ROOT / "docs" / "TOOLS.md"
_DESC_MAX = 110
# 校验时把日期归一化：跨天运行 --check 不应误报不一致
_DATE_LINE = re.compile(r"^(生成时间: ).*$", re.M)


def build() -> tuple[str, int, int]:
    """构建 TOOLS.md 全文；返回 (内容, 注册数, 可见数)。"""
    t = Toolkit()
    names = sorted(t.func_map)
    visible = set(llm_tool_names(t.func_map))
    lines = [
        "# 工具清单",
        "",
        f"注册工具总数: {len(names)}（LLM 可见: {len(visible)}）",
        "",
        f"生成时间: {_dt.date.today().isoformat()} · 由 `python scripts/gen_tools_doc.py` 生成，勿手编",
        "",
        "> 口径说明：「注册数」= `Toolkit().func_map` 长度（内置目录 + 用户目录 + 内建绑定）；",
        "> 「LLM 可见」= 扣除 `tlk.LLM_TOOL_EXCLUDES` 内部工具后的数量。两者不同，勿混用。",
        "",
        "| 工具 | LLM 可见 | 说明 |",
        "|------|:--------:|------|",
    ]
    for n in names:
        meta = t.meta_map.get(n) or {}
        desc = (meta.get("function") or {}).get("description", "") or ""
        desc = " ".join(desc.split())  # 折叠换行与连续空白
        if len(desc) > _DESC_MAX:
            desc = desc[:_DESC_MAX] + "..."
        desc = desc.replace("|", "\\|")
        mark = "✓" if n in visible else "—"
        lines.append(f"| `{n}` | {mark} | {desc} |")
    lines.append("")
    return "\n".join(lines), len(names), len(visible)


def _norm(text: str) -> str:
    return _DATE_LINE.sub(r"\1<DATE>", text)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成/校验 docs/TOOLS.md 工具清单快照")
    ap.add_argument("--check", action="store_true",
                    help="仅校验 docs/TOOLS.md 与当前工具注册态一致，不写入（不一致退出码 1）")
    args = ap.parse_args()

    content, n_reg, n_vis = build()

    if args.check:
        old = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if _norm(old) != _norm(content):
            print(f"❌ {DOC} 与当前工具注册态不一致（注册 {n_reg} / 可见 {n_vis}），"
                  f"请重跑: python scripts/gen_tools_doc.py")
            return 1
        print(f"✅ {DOC.name} 一致（注册 {n_reg} / 可见 {n_vis}）")
        return 0

    DOC.write_text(content, encoding="utf-8")
    print(f"✅ 已生成 {DOC}（注册 {n_reg} / 可见 {n_vis}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import json, shutil, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CORE_TOP = ["__init__.py","agent.py","agent_pipeline.py","basesession.py",
    "litesession.py","onlinesession.py","session_pipeline.py",
    "session_memory_component.py","session_tool_component.py","session_ref.py",
    "config.py","providers.py","logging_setup.py",
    "tlk.py","auto_fix.py","scheduler_storage.py","memory.py",
    "reflection.py","prompt_manager.py","project_memory.py",
    "agent_background.py"]

EXCLUDED_PKGS = ["_gui","gui2","protocol","lsp","sdk","scripts",
    "evaluation","web","demo","tests"]
EXCLUDED_TOP = ["cli.py","tui.py","gui.py","gui_dialogs.py"]

HEAVY_TOOLS = [
    "toolkit_js_fetch.py","toolkit_input.py","toolkit_screenshot.py",
    "toolkit_screen_read.py","toolkit_ocr.py","toolkit_lsp.py",
    "toolkit_browser_tab.py","toolkit_clipboard.py","toolkit_sudo_gui.py",
    "toolkit_test_gui.py","toolkit_explr.py","toolkit_pkg.py"]

DEPS = ["openai>=1.0.0","httpx>=0.25.0","PyYAML>=6.0","requests>=2.30.0",
    "starlette>=0.37.0","uvicorn>=0.27.0"]
def ok(path, src):
    rel = path.relative_to(src); parts = rel.parts
    if "__pycache__" in parts: return False
    for p in EXCLUDED_PKGS:
        if p in parts: return False
    if len(parts)==1 and parts[0] in EXCLUDED_TOP+HEAVY_TOOLS: return False
    if len(parts)>=2 and parts[0]=="toolkit" and parts[-1] in HEAVY_TOOLS: return False
    if len(parts)==1 and parts[0].endswith(".py"): return parts[0] in CORE_TOP
    if parts[0] in ["session","store","toolkit","multi_agent","server","compaction"]: return True
    if len(parts)>=2 and parts[0]=="server" and parts[1]=="static":
        return path.suffix in (".html",".js",".css",".png",".ico")
    if len(parts)>=2 and parts[0]=="server" and path.suffix==".py": return True
    if len(parts)>=2 and parts[0]=="skills" and path.suffix==".md": return True
    return False
def copy_core(src, dst):
    copied = []
    for item in src.rglob("*"):
        if item.is_file() and ok(item, src):
            rel = item.relative_to(src)
            (dst/rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst/rel)
            copied.append(str(rel))
    return copied
def patch_store(pkg_dir):
    """Replace numpy with math+struct (Python 3.11 compatible)."""
    patches = []
    for fname, subs in {
        "_vectors.py": [
            ("import numpy as np", "import math, struct"),
            ("arr = np.array(embedding, dtype=np.float32)\n        blob = arr.tobytes()",
             "blob = struct.pack(('%df' % len(embedding)), *embedding)"),
            ("arr = np.frombuffer(row[\"embedding\"], dtype=np.float32)\n                return arr.tolist()",
             "_v = row[\"embedding\"]; return list(struct.unpack(('%df' % (len(_v)//4)), _v))"),
            ('d["embedding"] = np.frombuffer(blob, dtype=np.float32).tolist()',
             'd["embedding"] = list(struct.unpack(("%df" % (len(blob)//4)), blob))'),
            ("query_arr = np.array(query_embedding, dtype=np.float32)\n        q_norm = np.linalg.norm(query_arr)",
             "q_norm = math.sqrt(sum(x*x for x in query_arr))"),
            ("mat = np.array(vecs, dtype=np.float32)\n        dots = mat @ query_arr\n        mat_norms = np.linalg.norm(mat, axis=1)\n        sims = dots / (q_norm * mat_norms)",
             "dots = [sum(a*b for a,b in zip(v, query_arr)) for v in vecs]\n        mat_norms = [math.sqrt(sum(x*x for x in v)) for v in vecs]\n        sims = [d/(q_norm*n) for d,n in zip(dots, mat_norms)]"),
        ],
        "_memories.py": [
            ("import numpy as np", "import math, struct"),
            ("arr = np.array(embedding, dtype=np.float32)\n                embedding_blob = arr.tobytes()",
             "embedding_blob = struct.pack(('%df' % len(embedding)), *embedding)"),
            ('arr = np.frombuffer(row["embedding"], dtype=np.float32)',
             '_v = row["embedding"]; arr = list(struct.unpack(("%df" % (len(_v)//4)), _v))'),
            ('d["embedding"] = arr.tolist()', 'd["embedding"] = arr'),
            ("query_arr = np.array(query_embedding, dtype=np.float32)\n                q_norm = np.linalg.norm(query_arr)",
             "q_norm = math.sqrt(sum(x*x for x in query_arr))"),
            ("mem_arr = np.array(emb, dtype=np.float32)\n                    sim = float(mem_arr @ query_arr) / (q_norm * np.linalg.norm(mem_arr))",
             "sim = float(sum(a*b for a,b in zip(emb, query_arr))) / (q_norm * math.sqrt(sum(x*x for x in emb)))"),
        ],
        "_semantic_search.py": [
            ("import numpy as np", "import math, struct"),
            ("arr = np.array(embedding, dtype=np.float32)", "pass"),
        ],
        "_conversations.py": [
            ("import numpy as np", "import math, struct"),
        ],
    }.items():
        fp = pkg_dir / "store" / fname
        if not fp.exists(): continue
        text = fp.read_text("utf-8")
        for old, new in subs:
            text = text.replace(old, new)
        fp.write_text(text, "utf-8")
        patches.append(fname)
    return patches
def build():
    src = ROOT/"tea_agent"; mini_src = ROOT/"tea_agent_mini"
    bd = ROOT/"build_mini_dist"; dd = bd/"dist"
    if bd.exists(): shutil.rmtree(bd)
    pkg = bd/"tea_agent"; mpkg = bd/"tea_agent_mini"

    print("Copying core modules...")
    copied = copy_core(src, pkg)
    pyf = [c for c in copied if c.endswith(".py")]
    print(f"   Python: {len(pyf)}, tools: {len([c for c in pyf if 'toolkit/toolkit_' in c])}, total: {len(copied)}")

    print("Patching store (removing numpy)...")
    patched = patch_store(pkg)
    print(f"   Patched: {', '.join(patched)}")

    print("Copying mini wrapper...")
    for item in mini_src.rglob("*"):
        if item.is_file() and "__pycache__" not in item.parts:
            rel = item.relative_to(mini_src)
            (mpkg/rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, mpkg/rel)

    version = "0.10.3"
    for line in (ROOT/"pyproject.toml").read_text().splitlines():
        if line.startswith("version ="):
            version = line.split('"')[1] if '"' in line else line.split("'")[1]
            break

    print(f"Generating pyproject.toml (v{version})...")
    ep = []
    for p in EXCLUDED_PKGS:
        ep.append(f"tea_agent.{p}"); ep.append(f"tea_agent.{p}.*")
    pyproj = f'''[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "tea_agent_mini"
version = "{version}"
description = "Tea Agent Mini - embedded-friendly AI Agent"
readme = "README.mini.md"
license = "MIT"
requires-python = ">=3.10"

dependencies = {json.dumps(DEPS, indent=4)}

[project.scripts]
tea-agent-mini = "tea_agent_mini.__main__:main"

[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
"tea_agent.server" = ["static/*.html", "static/*.js", "static/*.css"]
"tea_agent.skills" = ["**/*.md"]

[tool.setuptools.packages.find]
where = ["."]
include = ["tea_agent*", "tea_agent_mini*"]
exclude = {json.dumps(ep, indent=4)}
'''
    (bd/"pyproject.toml").write_text(pyproj, "utf-8")
    (bd/"README.mini.md").write_text(
        "# Tea Agent Mini\nEmbedded-friendly AI Agent.\n"
        "Deps: openai, httpx, PyYAML, requests, starlette, uvicorn\n"
        "(No numpy, playwright, pyautogui, mss, etc.)\n", "utf-8")

    print("Building wheel...")
    r = subprocess.run([sys.executable,"-m","build","--outdir",str(dd)],
        cwd=str(bd), capture_output=True, text=True)
    if r.returncode != 0: print(r.stdout+r.stderr); sys.exit(1)
    wheels = list(dd.glob("*.whl"))
    if not wheels: print("No wheel!"); sys.exit(1)
    w = wheels[0]
    print(f"OK: {w.name} ({w.stat().st_size/1024:.0f} KB)")

    # Verify
    with zipfile.ZipFile(w) as z:
        names = z.namelist()
    bad = [n for n in names if any(
        n.startswith(f"tea_agent/{p}/") or n.startswith(f"{p}/")
        or n == f"tea_agent/{p}" for p in EXCLUDED_PKGS+EXCLUDED_TOP+HEAVY_TOOLS)]
    if bad:
        print(f"WARNING: {len(bad)} unwanted files: {bad[:3]}")
    else:
        print("Verify: all clean")
    pyc = len([n for n in names if n.endswith(".py")])
    print(f"Python files: {pyc}")
    has_np = any("numpy" in n for n in names)
    print(f"numpy in wheel: {has_np}")
    if not has_np: print("No numpy - good!")
    print(f"\n pip install {w}")

if __name__ == "__main__":
    if "--list" in sys.argv:
        src = ROOT/"tea_agent"/"toolkit"
        allt = sorted(f.name for f in src.glob("toolkit_*.py"))
        inc = [t for t in allt if t not in HEAVY_TOOLS]
        exc = [t for t in allt if t in HEAVY_TOOLS]
        print(f"Included ({len(inc)}):", *[t.replace("toolkit_","").replace(".py","") for t in inc], sep="\n  - ")
        print(f"\nExcluded ({len(exc)}):", *[t.replace("toolkit_","").replace(".py","") for t in exc], sep="\n  - ")
        sys.exit(0)
    build()
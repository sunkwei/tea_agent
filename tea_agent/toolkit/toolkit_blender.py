# version: 1.0.0

"""
Blender 3D 建模控制工具 — 通过无头 CLI (``blender -b -P script.py``) 驱动。

Actions:
    probe  : 检测 Blender 安装与能力（版本/内置Python/渲染引擎/GPU计算设备/导出格式）
    run    : 执行 bpy 脚本（内联 code 或 script_path 文件），可附带打开 .blend
    render : 渲染 .blend 指定帧（可覆盖相机/分辨率/采样数），产物落盘 output_dir
    scene  : 检视 .blend 场景（对象清单/顶点面数/材质/相机），只读不改
    export : 导出 .blend 为 glb / gltf / obj / fbx / stl / ply / usd

结构化输出约定:
    被执行的 bpy 脚本 ``print("TEA_BLENDER_RESULT " + json.dumps({...}))``，
    本工具自动抽取（取最后一条）解析进返回 dict 的 ``result`` 字段。
    内嵌 probe/scene/export 脚本已遵循该约定；用户自写脚本可选遵循。

Blender 定位顺序:
    blender_path 参数 → 环境变量 BLENDER_PATH / BLENDER → PATH (which)
    → 平台默认安装目录（Windows: Program Files\\Blender Foundation\\Blender X.Y，
      多版本取最高；macOS: /Applications；Linux: /usr/bin 等常见路径）。

已知 Blender API 差异（内嵌脚本已做兼容分支）:
    - obj/stl/ply 导出 operator 在 3.3/4.0 迁移到 bpy.ops.wm.*
    - Scene.evaluated_depsgraph_get 不存在，须用 bpy.context.evaluated_depsgraph_get()
    - cycles 插件在 --factory-startup 下可能未启用，读取偏好前须 addon_utils.enable
"""

from __future__ import annotations

import glob
import json
import logging
import os
import os.path as osp
import re
import shutil
import subprocess
import sys
import tempfile
import time

logger = logging.getLogger("toolkit.blender")

#: 脚本结构化输出的行标记（与内嵌脚本保持一致）
RESULT_MARKER = "TEA_BLENDER_RESULT"

#: 导出格式 → 文件扩展名
EXPORT_EXTS = {
    "glb": ".glb",
    "gltf": ".gltf",
    "obj": ".obj",
    "fbx": ".fbx",
    "stl": ".stl",
    "ply": ".ply",
    "usd": ".usd",
}

_STDOUT_TAIL = 6000
_STDERR_TAIL = 3000

# ══════════════════════ 纯函数（可单测，不依赖 Blender） ══════════════════════


def _version_key(path: str) -> tuple:
    """从 '.../Blender 5.2/blender.exe' 提取 (5, 2) 用于自然排序（10.0 > 5.2）。"""
    digits = re.findall(r"(\d+)", osp.basename(osp.dirname(path)))
    return tuple(int(x) for x in digits) if digits else (0,)


def _candidate_paths() -> list:
    """平台默认安装位置候选（按版本降序，Windows 多版本取最高）。"""
    cands: list = []
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", ""),
            osp.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        for root in roots:
            if not root:
                continue
            base = osp.join(root, "Blender Foundation")
            hits = glob.glob(osp.join(base, "Blender*", "blender.exe"))
            cands.extend(sorted(hits, key=_version_key, reverse=True))
    elif sys.platform == "darwin":
        cands.append("/Applications/Blender.app/Contents/MacOS/Blender")
    else:
        cands.extend(["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender", "/opt/blender/blender"])
    return cands


def _find_blender(explicit: str = "") -> str | None:
    """定位 blender 可执行文件；找不到返回 None。纯查询，不抛异常。"""
    for c in (explicit, os.environ.get("BLENDER_PATH", ""), os.environ.get("BLENDER", "")):
        if c and osp.isfile(c):
            return c
    which = shutil.which("blender")
    if which:
        return which
    for c in _candidate_paths():
        if osp.isfile(c):
            return c
    return None


def _extract_result(stdout: str, marker: str = RESULT_MARKER) -> dict | None:
    """从 stdout 抽取最后一条 ``MARKER {json}``；无标记或解析失败返回 None。"""
    found = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith(marker):
            payload = line[len(marker) :].strip()
            try:
                obj = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                found = obj
    return found


def _build_cmd(
    blender: str,
    *,
    factory: bool = True,
    script: str | None = None,
    blend: str | None = None,
    extra: list | None = None,
    script_args: list | None = None,
) -> list:
    """组装 blender CLI 命令（list 形式，不经 shell，路径含空格安全）。

    顺序语义: ``blender -b [--factory-startup] [file.blend] [extra...] [-P script] [-- args]``
    extra（如 -o/-F/-f/--python-expr）须在 -f 渲染前生效，故置于脚本之前。
    """
    cmd = [blender, "-b"]
    if factory:
        cmd.append("--factory-startup")
    if blend:
        cmd.append(blend)
    if extra:
        cmd.extend(extra)
    if script:
        cmd.extend(["-P", script])
    if script_args:
        cmd.append("--")
        cmd.extend(str(a) for a in script_args)
    return cmd


def _tail(text: str, n: int) -> str:
    """保留尾部 n 字符（错误信息通常在末尾），截断时加标记。"""
    if not text or len(text) <= n:
        return text or ""
    return "...(truncated %d chars)...\n" % (len(text) - n) + text[-n:]


def _spawn(cmd: list, timeout: int) -> dict:
    """执行子进程，统一返回 dict；超时/找不到可执行文件都不抛异常。"""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "timed_out": False,
            "secs": round(time.time() - t0, 1),
            "stdout": p.stdout or "",
            "stderr": p.stderr or "",
        }
    except subprocess.TimeoutExpired as e:
        out = e.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return {
            "ok": False,
            "timed_out": True,
            "secs": round(time.time() - t0, 1),
            "stdout": out or "",
            "stderr": str(e),
            "error": "timeout after %ss" % timeout,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "timed_out": False,
            "secs": round(time.time() - t0, 1),
            "stdout": "",
            "stderr": "",
            "error": "executable not found: %s" % cmd[0],
        }
    except OSError as e:
        return {
            "ok": False,
            "timed_out": False,
            "secs": round(time.time() - t0, 1),
            "stdout": "",
            "stderr": "",
            "error": "spawn failed: %s" % e,
        }


def _finish(r: dict, action: str, blender: str | None = None) -> dict:
    """统一收口: 抽取 marker 结果、截断 stdout/stderr、附加元信息。"""
    r["action"] = action
    if blender:
        r["blender"] = blender
    r["result"] = _extract_result(r.get("stdout", ""))
    r["stdout"] = _tail(r.get("stdout", ""), _STDOUT_TAIL)
    r["stderr"] = _tail(r.get("stderr", ""), _STDERR_TAIL)
    return r


def _not_found(action: str) -> dict:
    return {
        "ok": False,
        "action": action,
        "blender": None,
        "error": "Blender not found",
        "hint": "安装 Blender (https://www.blender.org/download/) 或设置环境变量 "
        "BLENDER_PATH 指向 blender 可执行文件；也可用参数 blender_path 显式指定",
        "searched": {
            "env_BLENDER_PATH": os.environ.get("BLENDER_PATH", ""),
            "env_BLENDER": os.environ.get("BLENDER", ""),
            "which": shutil.which("blender") or "",
            "candidates": _candidate_paths()[:6],
        },
    }


# ══════════════════════ 内嵌 bpy 脚本（参数经 ``-- <json>`` 传入） ══════════════════════

_PARAMS_SNIPPET = '''
import json as _json, sys as _sys

def _argv_params():
    """从 blender CLI `-- <json>` 读取参数（避免向脚本注入代码的转义风险）。"""
    if "--" in _sys.argv:
        try:
            return _json.loads(_sys.argv[_sys.argv.index("--") + 1])
        except Exception:
            return {}
    return {}
'''

PROBE_PY = (
    '''# -*- coding: utf-8 -*-
"""tea_agent toolkit_blender probe — 输出 Blender 能力清单。"""
'''
    + _PARAMS_SNIPPET
    + """
import bpy

MARKER = "%s"
info = {}
info["version"] = bpy.app.version_string
info["version_tuple"] = list(bpy.app.version)
info["python"] = _sys.version.split()[0]
try:
    info["engines"] = [e.identifier for e in
                       bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
except Exception:
    info["engines"] = []
try:
    import addon_utils
    names = [getattr(m, "__name__", str(m)) for m in addon_utils.modules()]
    info["addons_available"] = len(names)
    info["cycles_available"] = "cycles" in names
    if "cycles" in names and "cycles" not in bpy.context.preferences.addons:
        addon_utils.enable("cycles", default_set=False, persistent=False)
except Exception as e:
    info["addons_error"] = str(e)
try:
    cprefs = bpy.context.preferences.addons["cycles"].preferences
    info["compute_device_type"] = str(cprefs.compute_device_type)
    info["compute_devices"] = [{"name": d.name, "type": d.type} for d in cprefs.devices]
except Exception:
    info["compute_devices"] = []
exporters = (("glb", "export_scene.gltf"), ("obj", "wm.obj_export"),
             ("fbx", "export_scene.fbx"), ("stl", "wm.stl_export"),
             ("ply", "wm.ply_export"), ("usd", "wm.usd_export"))
ok_fmts = []
for fmt, dotted in exporters:
    ns = bpy.ops
    for part in dotted.split("."):
        ns = getattr(ns, part, None)
        if ns is None:
            break
    if ns is not None:
        ok_fmts.append(fmt)
info["export_formats"] = ok_fmts
print(MARKER + " " + _json.dumps(info))
"""
    % RESULT_MARKER
)

SCENE_PY = (
    '''# -*- coding: utf-8 -*-
"""tea_agent toolkit_blender scene — 只读检视 .blend 场景。"""
'''
    + _PARAMS_SNIPPET
    + """
import bpy

MARKER = "%s"
p = _argv_params()
limit = int(p.get("limit", 400))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
objs = []
for o in list(bpy.data.objects)[:limit]:
    d = {"name": o.name, "type": o.type,
         "loc": [round(float(v), 3) for v in o.location],
         "dim": [round(float(v), 3) for v in o.dimensions]}
    if o.type == "MESH":
        d["verts"] = len(o.data.vertices)
        d["faces"] = len(o.data.polygons)
        d["materials"] = [m.name for m in o.data.materials if m]
    objs.append(d)
info = {
    "scene": bpy.context.scene.name,
    "object_count": len(bpy.data.objects),
    "mesh_count": len(meshes),
    "total_verts": sum(len(o.data.vertices) for o in meshes),
    "total_faces": sum(len(o.data.polygons) for o in meshes),
    "cameras": [o.name for o in bpy.data.objects if o.type == "CAMERA"],
    "materials": [m.name for m in bpy.data.materials],
    "collections": [c.name for c in bpy.data.collections],
    "objects": objs,
}
print(MARKER + " " + _json.dumps(info))
"""
    % RESULT_MARKER
)

EXPORT_PY = (
    '''# -*- coding: utf-8 -*-
"""tea_agent toolkit_blender export — 导出当前 .blend 为通用 3D 格式。"""
'''
    + _PARAMS_SNIPPET
    + """
import bpy
import os

MARKER = "%s"
p = _argv_params()
fmt = str(p.get("format", "glb")).lower()
out = str(p.get("output", ""))
info = {"format": fmt, "output": out, "ok": False}


def _has(dotted):
    ns = bpy.ops
    for part in dotted.split("."):
        ns = getattr(ns, part, None)
        if ns is None:
            return False
    return True


try:
    if fmt in ("glb", "gltf"):
        ef = "GLB" if fmt == "glb" else "GLTF_SEPARATE"
        bpy.ops.export_scene.gltf(filepath=out, export_format=ef)
    elif fmt == "obj":
        if _has("wm.obj_export"):
            bpy.ops.wm.obj_export(filepath=out, export_materials=True)
        else:
            bpy.ops.export_scene.obj(filepath=out, use_materials=True)
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=out)
    elif fmt == "stl":
        if _has("wm.stl_export"):
            bpy.ops.wm.stl_export(filepath=out)
        else:
            bpy.ops.export_mesh.stl(filepath=out)
    elif fmt == "ply":
        if _has("wm.ply_export"):
            bpy.ops.wm.ply_export(filepath=out)
        else:
            bpy.ops.export_mesh.ply(filepath=out)
    elif fmt == "usd":
        bpy.ops.wm.usd_export(filepath=out)
    else:
        raise ValueError("unsupported format: %%r" %% fmt)
    # glTF_SEPARATE 会产出目录 + 多个文件，其余为单文件
    if os.path.isdir(out):
        total = sum(os.path.getsize(os.path.join(dp, f))
                    for dp, _, fns in os.walk(out) for f in fns)
        info["size"] = total
    elif os.path.exists(out):
        info["size"] = os.path.getsize(out)
    else:
        raise FileNotFoundError("export produced no file: %%s" %% out)
    info["ok"] = True
except Exception as e:
    info["error"] = "%%s: %%s" %% (type(e).__name__, e)
print(MARKER + " " + _json.dumps(info))
"""
    % RESULT_MARKER
)

# ══════════════════════ 各 action 实现 ══════════════════════


def _write_temp_script(source: str, prefix: str) -> str:
    """把内联 bpy 代码写入临时 .py（UTF-8），返回路径；调用方负责删除。"""
    fd, path = tempfile.mkstemp(suffix=".py", prefix=prefix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if not source.startswith("#"):
            f.write("# -*- coding: utf-8 -*-\n")
        f.write(source)
    return path


def _run_script(
    blender: str,
    script: str,
    *,
    blend: str = "",
    factory: bool = True,
    script_args: list | None = None,
    timeout: int = 300,
) -> dict:
    cmd = _build_cmd(blender, factory=factory, script=script, blend=blend or None, script_args=script_args)
    return _spawn(cmd, timeout)


def _action_probe(blender: str, timeout: int) -> dict:
    path = _write_temp_script(PROBE_PY, "tea_blender_probe_")
    try:
        return _run_script(blender, path, timeout=max(60, timeout))
    finally:
        _safe_remove(path)


def _action_run(
    blender: str, code: str, script_path: str, blend_file: str, factory: bool, script_args: list | None, timeout: int
) -> dict:
    if not code and not script_path:
        return {"ok": False, "error": "run 需要 code 或 script_path 参数"}
    tmp = None
    try:
        if code:
            tmp = _write_temp_script(code, "tea_blender_run_")
            script = tmp
        else:
            script = osp.abspath(script_path)
            if not osp.isfile(script):
                return {"ok": False, "error": "script not found: %s" % script_path}
        return _run_script(blender, script, blend=blend_file, factory=factory, script_args=script_args, timeout=timeout)
    finally:
        if tmp:
            _safe_remove(tmp)


def _action_scene(blender: str, blend_file: str, factory: bool, timeout: int) -> dict:
    path = _write_temp_script(SCENE_PY, "tea_blender_scene_")
    try:
        return _run_script(
            blender, path, blend=blend_file, factory=factory, script_args=[json.dumps({"limit": 400})], timeout=timeout
        )
    finally:
        _safe_remove(path)


def _action_export(
    blender: str, blend_file: str, fmt: str, output_dir: str, output_path: str, factory: bool, timeout: int
) -> dict:
    fmt = (fmt or "glb").lower()
    if fmt not in EXPORT_EXTS:
        return {"ok": False, "error": "unsupported format: %s" % fmt, "supported": sorted(EXPORT_EXTS)}
    if output_path:
        out = osp.abspath(output_path)
    else:
        stem = osp.splitext(osp.basename(blend_file))[0] or "export"
        out = osp.join(_ensure_dir(output_dir), stem + EXPORT_EXTS[fmt])
    path = _write_temp_script(EXPORT_PY, "tea_blender_export_")
    try:
        r = _run_script(
            blender,
            path,
            blend=blend_file,
            factory=factory,
            script_args=[json.dumps({"format": fmt, "output": out})],
            timeout=timeout,
        )
        res = _extract_result(r.get("stdout", ""))
        if res and res.get("ok") and osp.exists(out):
            r["artifact"] = out
            r["artifact_size"] = (
                sum(osp.getsize(osp.join(dp, f)) for dp, _, fns in os.walk(out) for f in fns)
                if osp.isdir(out)
                else osp.getsize(out)
            )
        elif res and res.get("error"):
            r["ok"] = False
            r["error"] = res["error"]
        return r
    finally:
        _safe_remove(path)


def _action_render(
    blender: str,
    blend_file: str,
    output_dir: str,
    fmt: str,
    frame: int,
    camera: str,
    width: int,
    height: int,
    samples: int,
    timeout: int,
) -> dict:
    fmt = (fmt or "PNG").upper()
    if fmt not in ("PNG", "JPEG", "WEBP", "OPEN_EXR"):
        return {
            "ok": False,
            "error": "unsupported render format: %s" % fmt,
            "supported": ["PNG", "JPEG", "WEBP", "OPEN_EXR"],
        }
    outdir = _ensure_dir(output_dir)
    exprs = []
    if camera:
        exprs.append("import bpy;bpy.context.scene.camera=bpy.data.objects[%r]" % camera)
    if width:
        exprs.append("bpy.context.scene.render.resolution_x=%d" % int(width))
    if height:
        exprs.append("bpy.context.scene.render.resolution_y=%d" % int(height))
    if samples:
        exprs.append("bpy.context.scene.cycles.samples=%d" % int(samples))
    extra = ["-o", osp.join(outdir, "frame_"), "-F", fmt, "-x", "1"]
    if exprs:
        extra.extend(["--python-expr", ";".join(exprs)])
    extra.extend(["-f", str(int(frame))])
    started = time.time()
    # render 不用 --factory-startup：保留 blend 自带的渲染设置/插件偏好
    cmd = _build_cmd(blender, factory=False, blend=blend_file, extra=extra)
    r = _spawn(cmd, timeout)
    r["artifacts"] = _new_files(outdir, started)
    return r


def _ensure_dir(output_dir: str) -> str:
    d = osp.abspath(output_dir or osp.join("output", "blender"))
    os.makedirs(d, exist_ok=True)
    return d


def _new_files(directory: str, since_ts: float) -> list:
    """渲染开始后新产生/更新的文件（含大小），按名排序。"""
    out = []
    try:
        for name in sorted(os.listdir(directory)):
            p = osp.join(directory, name)
            try:
                if osp.isfile(p) and osp.getmtime(p) >= since_ts - 1:
                    out.append({"path": p, "size": osp.getsize(p)})
            except OSError:
                continue
    except OSError:
        pass
    return out


def _safe_remove(path: str) -> None:
    try:
        if path and osp.exists(path):
            os.remove(path)
    except OSError:
        pass


# ══════════════════════ 工具入口 ══════════════════════


def toolkit_blender(
    action: str = "probe",
    script_path: str = "",
    code: str = "",
    script_args: list | None = None,
    blend_file: str = "",
    output_dir: str = "",
    output_path: str = "",
    fmt: str = "",
    frame: int = 1,
    camera: str = "",
    width: int = 0,
    height: int = 0,
    samples: int = 0,
    factory: bool = True,
    timeout: int = 300,
    blender_path: str = "",
) -> dict:
    """Blender 3D 建模控制工具（无头 CLI 驱动）。

    Args:
        action: probe=环境体检 / run=执行bpy脚本 / render=渲染帧 /
            scene=检视场景 / export=导出通用格式
        script_path: [run] bpy 脚本文件路径（与 code 二选一）
        code: [run] 内联 bpy 代码字符串
        script_args: [run] 透传给脚本的参数（脚本内经 sys.argv 取 '--' 之后部分）
        blend_file: [render/scene/export 必需, run 可选] 输入 .blend 文件
        output_dir: [render/export] 输出目录，默认 ./output/blender
        output_path: [export] 显式输出文件全路径（优先于 output_dir 推导）
        fmt: [export] glb/gltf/obj/fbx/stl/ply/usd，默认 glb；
            [render] PNG/JPEG/WEBP/OPEN_EXR，默认 PNG
        frame: [render] 帧号，默认 1
        camera: [render] 相机对象名（覆盖场景当前相机）
        width: [render] 分辨率宽覆盖（0=用场景设置）
        height: [render] 分辨率高覆盖
        samples: [render] Cycles 采样数覆盖
        factory: 是否 --factory-startup（忽略用户偏好，启动快且可复现；
            render 恒为否以保留 blend 自带设置），默认 True
        timeout: 子进程超时秒数，默认 300
        blender_path: 显式 blender 可执行文件路径（优先于自动定位）

    Returns:
        dict: ok / action / blender / secs / result(脚本标记输出解析) /
            stdout(尾部截断) / stderr(尾部截断)；render 附 artifacts；
            export 附 artifact/artifact_size。失败时 ok=False 且含 error/hint。
    """
    action = (action or "probe").strip().lower()
    if action not in ("probe", "run", "render", "scene", "export"):
        return {
            "ok": False,
            "action": action,
            "error": "unknown action: %s" % action,
            "supported": ["probe", "run", "render", "scene", "export"],
        }

    # 输入预检（无需启动 Blender 即可判定的错误）
    if action in ("render", "scene", "export"):
        if not blend_file:
            return {"ok": False, "action": action, "error": "%s 需要 blend_file 参数" % action}
        if not osp.isfile(blend_file):
            return {"ok": False, "action": action, "error": "blend file not found: %s" % blend_file}

    blender = _find_blender(blender_path)
    if not blender:
        return _not_found(action)

    if action == "probe":
        r = _action_probe(blender, timeout)
    elif action == "run":
        r = _action_run(blender, code, script_path, blend_file, factory, script_args, timeout)
    elif action == "scene":
        r = _action_scene(blender, blend_file, factory, timeout)
    elif action == "export":
        r = _action_export(blender, blend_file, fmt, output_dir, output_path, factory, timeout)
    else:  # render
        r = _action_render(blender, blend_file, output_dir, fmt, frame, camera, width, height, samples, timeout)
    return _finish(r, action, blender)


# ══════════════════════ 元信息 ══════════════════════

TOOL_META = {
    "type": "function",
    "function": {
        "name": "toolkit_blender",
        "description": (
            "Blender 3D 建模控制（无头 CLI）。probe=检测安装与能力(版本/GPU/引擎/导出格式); "
            "run=执行 bpy 脚本(内联 code 或 script_path, 可附带打开 blend); "
            "render=渲染 blend 指定帧(可覆盖相机/分辨率/采样); "
            "scene=只读检视场景对象清单与统计; "
            "export=导出 glb/obj/fbx/stl/ply/usd。"
            "脚本 print('TEA_BLENDER_RESULT '+json) 会被自动解析进 result 字段。"
            "自动定位 blender.exe(环境变量 BLENDER_PATH > PATH > 默认安装目录)。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["probe", "run", "render", "scene", "export"],
                    "description": "probe/run/render/scene/export，默认 probe",
                },
                "script_path": {"type": "string", "description": "[run] bpy 脚本文件路径（与 code 二选一）"},
                "code": {"type": "string", "description": "[run] 内联 bpy 代码"},
                "script_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "[run] 透传给脚本的参数（sys.argv 中 '--' 之后）",
                },
                "blend_file": {"type": "string", "description": "[render/scene/export 必需] 输入 .blend 文件"},
                "output_dir": {"type": "string", "description": "[render/export] 输出目录，默认 ./output/blender"},
                "output_path": {"type": "string", "description": "[export] 显式输出文件全路径"},
                "fmt": {
                    "type": "string",
                    "description": "[export] glb/gltf/obj/fbx/stl/ply/usd 默认 glb；[render] PNG/JPEG/WEBP/OPEN_EXR 默认 PNG",
                },
                "frame": {"type": "integer", "description": "[render] 帧号，默认 1"},
                "camera": {"type": "string", "description": "[render] 相机对象名覆盖"},
                "width": {"type": "integer", "description": "[render] 分辨率宽覆盖，0=场景设置"},
                "height": {"type": "integer", "description": "[render] 分辨率高覆盖"},
                "samples": {"type": "integer", "description": "[render] Cycles 采样数覆盖"},
                "factory": {"type": "boolean", "description": "--factory-startup（render 恒否），默认 true"},
                "timeout": {"type": "integer", "description": "子进程超时秒数，默认 300"},
                "blender_path": {"type": "string", "description": "显式 blender 可执行文件路径"},
            },
            "required": ["action"],
        },
    },
}


def meta_toolkit_blender() -> dict:
    """工具元信息（tlk.py 加载约定: meta_<tool_name>()）。"""
    return json.loads(json.dumps(TOOL_META))

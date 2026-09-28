# -*- coding: utf-8 -*-
"""祈年殿渲染脚本 —— 外观图 / 结构爆炸图 / 骨架剖视图 / 俯视柱网 / 殿内藻井。

前置：先用 ``qiniandian_build.py`` 生成 ``qiniandian.blend``。

运行::

    blender -b output/blender/qiniandian/qiniandian.blend \\
        -P scripts/blender/qiniandian_render.py -- --views exterior,exploded,skeleton

选项::

    --views LIST      逗号分隔，默认全部；可选 exterior/exploded/skeleton/plan/interior
    --engine E        EEVEE（默认，快）或 CYCLES
    --samples N       渲染采样（EEVEE 默认 96，CYCLES 默认 192）
    --width N / --height N
    --out DIR         输出目录（默认 ./output/blender/qiniandian）
    --anim N          生成 N 帧爆炸动画（explode 0→1 + 环绕），产出 render 帧序列
    --quiet

「结构爆炸图」由场景空物体 ``EXPLODE_CTRL`` 的 ``explode`` / ``spread``
自定义属性驱动（驱动器在建模时已绑好各结构层与柱圈）。
"""

from __future__ import annotations

import json
import math
import os
import sys

import bpy
from mathutils import Vector

OUT = "./output/blender/qiniandian"
QUIET = "--quiet" in sys.argv


def _argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def _opt(name, default):
    a = _argv()
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def log(*a):
    if not QUIET:
        print("[qnd-render]", *a)


VIEWS = [v.strip() for v in str(_opt("--views", "exterior,exploded,skeleton,plan,interior")).split(",") if v.strip()]
ENGINE = str(_opt("--engine", "EEVEE")).upper()
SAMPLES = int(_opt("--samples", 96 if ENGINE == "EEVEE" else 192))
W, H = int(_opt("--width", 1600)), int(_opt("--height", 1200))
OUT = os.path.abspath(_opt("--out", OUT))
ANIM = int(_opt("--anim", 0))

# 骨架 / 俯视视图需要隐藏的「皮」（屋面瓦、椽、天花、装修、场地）
HIDE_SHELL = ("下檐屋面", "中檐屋面", "上檐屋面", "椽", "天花", "鎏金宝顶")
HIDE_FITTINGS = ("隔扇", "神座", "九龙藻井")
HIDE_SITE = ("地面", "砖墁院", "上层坛面金砖", "龙凤呈祥石", "踏道", "祈谷坛", "上层坛", "中层坛", "下层坛")


def set_explode(exp=0.0, spread=0.0):
    ctrl = bpy.data.objects.get("EXPLODE_CTRL")
    if ctrl is None:
        log("!! 未找到 EXPLODE_CTRL（请先运行 qiniandian_build.py）")
        return
    ctrl["explode"] = exp
    ctrl["spread"] = spread
    bpy.context.view_layer.update()


def show_all():
    for ob in bpy.data.objects:
        ob.hide_render = False
        ob.hide_viewport = False


def hide(prefixes):
    for ob in bpy.data.objects:
        if any(ob.name.startswith(p) for p in prefixes):
            ob.hide_render = True


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE" if ENGINE == "EEVEE" else "CYCLES"
    sc.render.resolution_x = W
    sc.render.resolution_y = H
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False
    if ENGINE == "EEVEE":
        try:
            sc.eevee.taa_render_samples = SAMPLES
            sc.eevee.use_ssr = True
            sc.eevee.use_gtao = True
        except Exception:
            pass
        try:
            sc.eevee.shadow_cube_size = "1024PX"
            sc.eevee.shadow_cascade_size = "2048PX"
        except Exception:
            pass
    else:
        sc.cycles.device = "CPU"
        sc.cycles.samples = SAMPLES
        sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX" if "AgX" in \
        [v.identifier for v in bpy.types.ColorManagedViewSettings.bl_rna.properties["view_transform"].enum_items] \
        else "Standard"
    sc.view_settings.look = "None"


def make_camera(name, loc, target, lens):
    old = bpy.data.objects.get(name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
    cd = bpy.data.cameras.get(name + "_data") or bpy.data.cameras.new(name + "_data")
    cd.lens = lens
    cd.clip_end = 5000
    cd.sensor_fit = "AUTO"
    c = bpy.data.objects.new(name, cd)
    c.location = Vector(loc)
    d = Vector(target) - c.location
    c.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(c)
    bpy.context.scene.camera = c
    return c


# 视图定义：名称 → (相机位, 注视点, 焦距, explode, spread, 隐藏组)
VIEW_PRESETS = {
    "exterior":  ((78, -92, 27),  (0, 0, 16), 42, 0.0, 0.0, ()),
    "exploded":  ((128, -160, 100), (0, 0, 46), 30, 1.0, 0.60, ()),
    "skeleton":  ((30, -42, 21),  (0, 0, 14), 40, 0.0, 0.0, HIDE_SHELL),
    "frame":     ((13, -15, 31),  (0, 0, 27), 55, 0.0, 0.0, HIDE_SHELL + HIDE_FITTINGS),
    "dougong":   ((22, -10, 10.6), (14.6, -1.0, 16.1), 65, 0.0, 0.0, ()),
    "plan":      ((0, -0.02, 128), (0, 0, 5.0), 60, 0.0, 0.0, HIDE_SHELL + HIDE_FITTINGS),
    "interior":  ((10.6, -5.4, 8.6), (0, 0, 21), 26, 0.0, 0.0, ()),
}


def render_view(key):
    loc, tgt, lens, exp, spr, hid = VIEW_PRESETS[key]
    show_all()
    if hid:
        hide(hid)
    set_explode(exp, spr)
    make_camera("Cam_" + key, loc, tgt, lens)
    path = os.path.join(OUT, "qnd_%s.png" % key)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log("rendered", key, "->", path)
    return path


def render_anim(n):
    """爆炸动画：explode 0→1（带缓动）+ 相机缓慢环绕。"""
    show_all()
    ctrl = bpy.data.objects["EXPLODE_CTRL"]
    cam = make_camera("Cam_anim", (96, -112, 66), (0, 0, 30), 40)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, n
    ctrl.keyframe_insert('["explode"]', frame=1)
    ctrl.keyframe_insert('["spread"]', frame=1)
    ctrl["explode"] = 1.0
    ctrl["spread"] = 0.55
    ctrl.keyframe_insert('["explode"]', frame=n)
    ctrl.keyframe_insert('["spread"]', frame=n)
    for f in (ctrl.animation_data.action.fcurves if ctrl.animation_data else []):
        for kp in f.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.easing = "EASE_IN_OUT"
    r, z, a0 = math.hypot(96, 112), 66.0, math.atan2(-112, 96)
    for f in (1, n):
        a = a0 + (0.0 if f == 1 else math.radians(55))
        cam.location = (r * math.cos(a), r * math.sin(a), z)
        d = Vector((0, 0, 30)) - cam.location
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)
    os.makedirs(OUT, exist_ok=True)
    sc.render.filepath = os.path.join(OUT, "anim", "qnd_explode_")
    bpy.ops.render.render(animation=True)
    log("anim frames", n, "->", sc.render.filepath)
    return sc.render.filepath


def main():
    os.makedirs(OUT, exist_ok=True)
    setup_render()
    out = []
    if ANIM:
        out.append(render_anim(ANIM))
    for v in VIEWS:
        if v in VIEW_PRESETS:
            out.append(render_view(v))
        else:
            log("!! 未知视图:", v, "可选:", ",".join(VIEW_PRESETS))
    show_all()
    set_explode(0.0, 0.0)
    print("TEA_BLENDER_RESULT " + json.dumps({
        "views": VIEWS, "engine": ENGINE, "samples": SAMPLES,
        "resolution": [W, H], "files": out,
    }, ensure_ascii=False))


main()

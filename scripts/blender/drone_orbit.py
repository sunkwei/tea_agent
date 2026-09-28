# -*- coding: utf-8 -*-
"""
回澜阁 · 无人机环绕镜头 — 20s @24fps (480帧) 相机动画 + EEVEE 渲染
====================================================================
镜头脚本（与需求逐条对应）:
  f1-48    (0-2s)    栈桥上起飞: 桥面(距阁 50m)低空爬升, 仰视阁顶
  f49-144  (2-6s)    拉近: 50m→16m, 保持仰视, 镜头 24→32mm 微变焦
  f145-384 (6-16s)   右侧环绕一周: 面向阁时右手侧=+Y, θ 0→360°,
                     高度 10.5m(平视阁身) 缓升至 26m(俯拍), 视线目标随之下降
  f385-480 (16-20s)  后撤降落回起点 (50m, 低空), 镜头复归仰视

用法（项目根目录）:
    blender -b output/huilan_ge/huilan_ge.blend -P scripts/blender/drone_orbit.py
    # 只建动画不渲染（秒级，验证用）:
    blender -b output/huilan_ge/huilan_ge.blend -P scripts/blender/drone_orbit.py -- dry

坐标基准（来自 scripts/huilan_ge_model.py）:
    回澜阁中心 = 原点; 桥面 z=3.20; 宝顶尖 z≈21.34; 栈桥沿 +X 通往陆地。

Blender 5.2 API 适配（踩坑记录，勿回退）:
  1) Action.fcurves 已移除（Slotted Actions）→ 走 fcurves_compat / layers→strips→channelbags
  2) 引擎名 BLENDER_EEVEE_NEXT 已改回 BLENDER_EEVEE
  3) blend 存有 STEREO_3D 视图 → file_format 运行时枚举不含 FFMPEG，
     必须先 use_multiview=False；仍失败则回退 PNG 序列 + 外部 ffmpeg 合成
"""

import json
import math
import os
import sys
import time

import bpy

# ─────────────────────────── 参数 ───────────────────────────
FPS = 24
F_TOTAL = 480                     # 20.0s
W, H = 1920, 1080
LENS_START, LEND_END = 24.0, 32.0

DIST_START = 50.0                 # 起飞点距阁 50m（栈桥上）
DIST_CLOSE = 16.0                 # 拉近后距离
R_ORBIT = 30.0                    # 环绕半径
Z_TAKEOFF_LO, Z_TAKEOFF_HI = 4.6, 9.0
Z_ORBIT_LO, Z_ORBIT_HI = 10.5, 26.0
Z_LAND = 4.6
Z_APEX = 21.34                    # 宝顶尖（仰视目标）
Z_BODY = 12.0                     # 阁身中部（平视目标）

F_TAKEOFF_END = 48
F_CLOSE_END = 144
F_ORBIT_END = 384

OUTDIR = os.path.join("output", "huilan_ge")
VIDEO = os.path.join(OUTDIR, "drone_orbit.mp4")
DRY_RUN = os.environ.get("HLG_DRY_RUN") == "1" or "dry" in sys.argv

MARKER = "TEA_BLENDER_RESULT "
os.makedirs(OUTDIR, exist_ok=True)


# ─────────────────────── 相机路径（纯函数） ───────────────────────
def _sm(t):
    """smoothstep 缓入缓出 → 起降/推拉无机械感"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def cam_state(frame: int):
    """返回 (cam_pos, target_pos, lens) —— 逐帧采样, 线性插值即精确复现路径"""
    f = float(frame)
    if f <= F_TAKEOFF_END:                                   # 起飞爬升
        t = _sm((f - 1.0) / (F_TAKEOFF_END - 1.0))
        pos = (DIST_START, 0.0, Z_TAKEOFF_LO + (Z_TAKEOFF_HI - Z_TAKEOFF_LO) * t)
        tgt = (0.0, 0.0, Z_APEX)                             # 仰视阁顶
        lens = LENS_START
    elif f <= F_CLOSE_END:                                   # 拉近
        t = _sm((f - F_TAKEOFF_END) / (F_CLOSE_END - F_TAKEOFF_END))
        d = DIST_START + (DIST_CLOSE - DIST_START) * t
        z = Z_TAKEOFF_HI + (Z_ORBIT_LO - Z_TAKEOFF_HI) * t
        pos = (d, 0.0, z)
        tgt = (0.0, 0.0, Z_APEX + (Z_BODY - Z_APEX) * t)     # 仰视 → 渐平
        lens = LENS_START + (LEND_END - LENS_START) * t
    elif f <= F_ORBIT_END:                                   # 右侧环绕一周
        t = _sm((f - F_CLOSE_END) / (F_ORBIT_END - F_CLOSE_END))
        th = 2.0 * math.pi * t                               # 0→360°, 先经 +Y(右手侧)
        z = Z_ORBIT_LO + (Z_ORBIT_HI - Z_ORBIT_LO) * t       # 平视 → 俯拍
        pos = (R_ORBIT * math.cos(th), R_ORBIT * math.sin(th), z)
        tgt = (0.0, 0.0, Z_BODY + (9.0 - Z_BODY) * t)        # 目标下沉 → 俯角渐增
        lens = LEND_END
    else:                                                    # 后撤降落回起点
        t = _sm((f - F_ORBIT_END) / (F_TOTAL - F_ORBIT_END))
        r = R_ORBIT + (DIST_START - R_ORBIT) * t
        th = 2.0 * math.pi * (1.0 - t) * 0.0                 # 已回到 θ=0(+X 栈桥侧)
        z = Z_ORBIT_HI + (Z_LAND - Z_ORBIT_HI) * t
        pos = (r * math.cos(th), r * math.sin(th), z)
        tgt = (0.0, 0.0, 9.0 + (Z_APEX - 9.0) * t)           # 俯 → 复归仰视
        lens = LEND_END + (LENS_START - LEND_END) * t
    return pos, tgt, lens


# ─────────────────────────── 场景装配 ───────────────────────────
def setup_camera():
    cam_ob = bpy.data.objects.get("DroneCam")
    if cam_ob is None:
        cam = bpy.data.cameras.get("DroneCam") or bpy.data.cameras.new("DroneCam")
        cam_ob = bpy.data.objects.new("DroneCam", cam)
        bpy.context.scene.collection.objects.link(cam_ob)
    cam_ob.data.lens = LENS_START
    cam_ob.data.clip_end = 2000.0

    tgt = bpy.data.objects.get("DroneTarget")
    if tgt is None:
        tgt = bpy.data.objects.new("DroneTarget", None)
        tgt.empty_display_type = "PLAIN_AXES"
        tgt.empty_display_size = 2.0
        bpy.context.scene.collection.objects.link(tgt)

    # TRACK_TO: 相机始终盯住目标, 朝向自动平滑（无需手算四元数）
    cons = [c for c in cam_ob.constraints if c.type == "TRACK_TO"]
    if not cons:
        c = cam_ob.constraints.new("TRACK_TO")
        c.track_axis = "TRACK_NEGATIVE_Z"
        c.up_axis = "UP_Y"
    else:
        c = cons[0]
    c.target = tgt
    return cam_ob, tgt


def _iter_fcurves(action):
    """Blender 5.x 移除 Action.fcurves（Slotted Actions）→ 兼容遍历"""
    compat = getattr(action, "fcurves_compat", None)
    if compat is not None:
        try:
            got = False
            for fc in compat:
                got = True
                yield fc
            if got:
                return
        except Exception:
            pass
    for layer in getattr(action, "layers", ()) or ():
        for strip in getattr(layer, "strips", ()) or ():
            for cb in getattr(strip, "channelbags", ()) or ():
                for fc in getattr(cb, "fcurves", ()) or ():
                    yield fc


def keyframe_all(cam_ob, tgt):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, F_TOTAL
    sc.render.fps = FPS

    # 逐帧打点（480 帧 × 3 通道，成本可忽略）→ 配合 LINEAR 精确复现数学路径
    for f in range(1, F_TOTAL + 1):
        pos, tg, lens = cam_state(f)
        sc.frame_set(f)
        cam_ob.location = pos
        tgt.location = tg
        cam_ob.data.lens = lens
        cam_ob.keyframe_insert("location", frame=f)
        tgt.keyframe_insert("location", frame=f)
        cam_ob.data.keyframe_insert("lens", frame=f)

    for obj in (cam_ob, tgt, cam_ob.data):
        ad = obj.animation_data
        if ad and ad.action:
            for fc in _iter_fcurves(ad.action):
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
                    kp.handle_left_type = "VECTOR"
                    kp.handle_right_type = "VECTOR"


# ─────────────────────────── 渲染设置 ───────────────────────────
def setup_render():
    sc = bpy.context.scene
    r = sc.render
    try:
        r.engine = "BLENDER_EEVEE_NEXT"      # 4.x 名称
    except Exception:
        r.engine = "BLENDER_EEVEE"           # 5.x 已改回此名
    r.resolution_x, r.resolution_y = W, H
    r.resolution_percentage = 100
    r.film_transparent = False
    r.use_motion_blur = True
    r.motion_blur_shutter = 0.6              # 飞行感
    r.use_file_extension = True

    # blend 存了 STEREO_3D 视图 → 关多视图后 FFMPEG 才在运行时枚举里
    try:
        r.use_multiview = False
    except Exception:
        pass

    try:
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        try:
            r.ffmpeg.constant_rate_factor = "HIGH"
        except Exception:
            r.ffmpeg.quality = 90
        mode = "direct"
    except Exception:
        mode = "seq"                          # 兜底: PNG 序列 + 外部 ffmpeg
        r.image_settings.file_format = "PNG"
    r.filepath = VIDEO
    return mode


def render_stills(cam_ob, sc):
    """4 张关键帧预览（供人工/vision 审稿）"""
    paths = []
    r = sc.render
    keep_fmt, keep_fp = r.image_settings.file_format, r.filepath
    r.use_motion_blur = False
    for f in (24, 120, 330, 470):
        p = os.path.join(OUTDIR, "preview_f%03d.png" % f)
        r.image_settings.file_format = "PNG"
        r.filepath = p
        sc.frame_set(f)
        cam_ob.data.lens = cam_state(f)[2]
        bpy.ops.render.render(write_still=True)
        paths.append(os.path.abspath(p))
    r.image_settings.file_format, r.filepath = keep_fmt, keep_fp
    r.use_motion_blur = True
    return paths


# ─────────────────────────── 主流程 ───────────────────────────
def main():
    t0 = time.time()
    sc = bpy.context.scene
    cam_ob, tgt = setup_camera()
    keyframe_all(cam_ob, tgt)
    rep = dict(fps=FPS, frames=F_TOTAL, duration_s=F_TOTAL / FPS,
               resolution="%dx%d" % (W, H))

    if DRY_RUN:
        # 抽查若干帧的相机位姿，验证动画曲线真的生效（不渲染）
        probes = {}
        for f in (1, 24, 60, 144, 200, 330, 384, 480):
            sc.frame_set(f)
            probes[f] = [round(v, 2) for v in cam_ob.location] + [round(cam_ob.data.lens, 1)]
        rep["dry_run"] = True
        rep["cam_probes"] = probes
        rep["build_secs"] = round(time.time() - t0, 2)
        print(MARKER + json.dumps(rep, ensure_ascii=False))
        return

    mode = setup_render()
    rep["video_mode"] = mode
    sc.frame_set(1)
    bpy.ops.render.render(animation=True)
    rep["video"] = os.path.abspath(VIDEO)
    rep["video_size"] = os.path.getsize(VIDEO) if os.path.isfile(VIDEO) else -1
    rep["render_secs"] = round(time.time() - t0, 1)
    rep["previews"] = render_stills(cam_ob, sc)
    if rep["video_size"] < 0:
        rep["note"] = "序列帧模式: 需 ffmpeg 合成 %s%%04d.png -> %s" % (VIDEO, VIDEO)
    print(MARKER + json.dumps(rep, ensure_ascii=False))


main()

# -*- coding: utf-8 -*-
"""祈年殿（天坛 · Hall of Prayer for Good Harvests）参数化建模脚本

运行::

    blender -b --factory-startup -P scripts/blender/qiniandian_build.py -- [选项]

选项::

    --out DIR         输出目录（默认 ./output/blender/qiniandian）
    --set-explode F   写入 .blend 的爆炸系数（默认 0.0）
    --no-save         不保存 .blend
    --export-glb      同时导出 glTF/GLB
    --quiet           不打印进度

═══════════════════ 尺寸依据（公开实测资料） ═══════════════════
祈谷坛（三层汉白玉圆台）
    通高 5.2 m；上层径 68.2 m、中层径 79.3 m、下层径 90.3 m；各层绕汉白玉栏
    上层望柱盘龙、中层翔凤、下层朵云；出水作螭首/凤首/云朵
祈年殿
    总高 38.2 m（自地面），最大檐径 32.72 m，大殿面积 460 m²
    鎏金宝顶、蓝琉璃瓦三重檐攒尖顶，层层收进
    上殿下坛；殿内四周不用墙壁，全用隔扇门；梁枋施龙凤和玺彩画
柱网（二十八根楠木大柱，环转排列，殿顶不用大梁长檩）
    内圈 4 根龙井柱：高 19.2 m、径 1.2 m —— 象四季，承上层檐
    中圈 12 根金柱 —— 象十二月，承第二层檐
    外圈 12 根檐柱 —— 象十二时辰，承第三层（下）檐
    内外 24 柱又象二十四节气；28 柱象二十八星宿
    藻井周围环立 8 根童柱
    28 柱与 36 根枋桷互相衔接（本模型：12 抱头梁 + 12 金柱枋 + 12 抹角梁 = 36）
殿内
    三重檐对应三层天花，中央九龙藻井；北侧圆形石台上雕龙宝座，东西两侧配座
    殿心「龙凤呈祥石」

结构爆炸图
    场景内空物体 ``EXPLODE_CTRL`` 带两个自定义属性：
        explode   0..1  竖向分层拆解（台基→柱网→梁枋→铺作→屋面→宝顶）
        spread    0..1  柱圈/铺作径向张开，露出三环柱网
    二者均由驱动器（driver）绑定到各构件，拖动滑杆即实时拆解。
"""

from __future__ import annotations

import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

# ─────────────────────────── 命令行参数 ───────────────────────────

def _argv() -> list[str]:
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def _opt(name: str, default=None):
    a = _argv()
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


QUIET = "--quiet" in _argv()
OUT = os.path.abspath(_opt("--out", "./output/blender/qiniandian"))
SET_EXPLODE = float(_opt("--set-explode", 0.0) or 0.0)
DO_SAVE = "--no-save" not in _argv()
DO_GLB = "--export-glb" in _argv()


def log(*a):
    if not QUIET:
        print("[qnd]", *a)


# ─────────────────────────── 尺寸常量（米） ───────────────────────────

# 祈谷坛三层圆台
TERRACE_H = 5.2                       # 台通高
TERRACE_R = (45.15, 39.65, 34.10)     # 下 / 中 / 上层半径（90.3 / 79.3 / 68.2）
TIER_H = TERRACE_H / 3.0              # 每层 1.7333

# 殿身
Z_FLOOR = TERRACE_H                   # 殿地面标高
EAVE_DIA = 32.72                      # 最大檐径
H_TOTAL = 38.2                        # 殿总高（自地面）

# 柱网半径（自殿心）。传力路径：檐柱→抱头梁→金柱→跨空枋→龙井柱→井口枋→
# 抹角梁（方转八角）→童柱→上檐斗拱→雷公柱。
# 龙井柱 r=4.30 → 井口枋方框边中点 r=3.040 → 抹角梁切角后八角顶点
# r=√(3.040²+(3.040−1.781)²)=3.290，即童柱所在八角
R_EAVE, R_GOLD, R_DRAGON = 13.00, 9.00, 4.30
OCT_APO, OCT_VERT = 3.040, 3.290       # 八角内切半径 / 顶点半径
R_CHILD = OCT_VERT                     # 童柱（钻金柱）立于八角顶点
R_CANT = 8.00                          # 上檐挑檐梁外端（承上檐外圈斗拱）

# 柱高（自殿地面起，不含柱础）
H_EAVE, H_GOLD, H_DRAGON = 9.40, 15.20, 19.20
H_CHILD = 4.20                         # 童柱（钻金柱）立于井口枋之上

# 柱径（下径 / 上径，含收分）
D_EAVE = (0.86, 0.80)
D_GOLD = (1.02, 0.94)
D_DRAGON = (1.20, 1.11)              # 实测径 1.2 m
D_CHILD = (0.52, 0.48)
TILT = math.radians(0.9)             # 侧脚

# 柱础
BASE_H = {"eave": 0.42, "gold": 0.50, "dragon": 0.62, "child": 0.22}
BASE_R = {"eave": 0.66, "gold": 0.78, "dragon": 0.95, "child": 0.36}

# ── 竖向标高体系（自地面 0.0 起算，含柱础）──
Z_EAVE_TOP = Z_FLOOR + BASE_H["eave"] + H_EAVE        # 15.02 檐柱顶
Z_GOLD_TOP = Z_FLOOR + BASE_H["gold"] + H_GOLD        # 20.90 金柱顶
Z_DRAG_TOP = Z_FLOOR + BASE_H["dragon"] + H_DRAGON    # 25.02 龙井柱顶
H_JKF = 0.55                                          # 井口枋高（龙井柱顶方形框架）
Z_CHILD_BOT = Z_DRAG_TOP + H_JKF                      # 25.57 童柱脚（坐井口枋上）
Z_CHILD_TOP = Z_CHILD_BOT + H_CHILD                   # 29.77 童柱顶
Z_CANT = Z_DRAG_TOP + 0.30                            # 上檐挑檐梁标高

DG_H = (1.55, 1.35, 1.25)                             # 下/中/上檐铺作层高
Z_DG_LO = Z_EAVE_TOP + DG_H[0]                        # 16.57 下檐正心桁
Z_DG_MID = Z_GOLD_TOP + DG_H[1]                       # 22.25 中檐正心桁
Z_DG_UP = Z_CHILD_TOP + DG_H[2]                       # 31.02 上檐内圈桁（童柱头）
Z_DG_UP_OUT = Z_CANT + DG_H[2]                        # 26.57 上檐外圈桁（挑檐梁头）

# 三重檐屋面轮廓端点 (檐口半径, 檐口标高, 内端半径, 内端标高)
# 重檐逻辑：上一层檐口落在下一层柱圈斗拱之上，逐层向内收束至雷公柱
ROOF_LO = (16.36, Z_DG_LO, R_GOLD + 0.60, Z_GOLD_TOP)      # 下檐：檐柱→金柱
ROOF_MID = (12.40, Z_DG_MID, R_DRAGON + 0.60, Z_DRAG_TOP)  # 中檐：金柱→龙井柱
ROOF_UP = (9.60, Z_DG_UP_OUT, 0.55, 35.00)                 # 上檐：挑檐梁→雷公柱
ROOF_P = 1.55                            # 举折曲线指数（檐缓脊陡）
ROOF_P_UP = 0.98                         # 上檐攒尖：近似直坡，且须过童柱头正心桁
TILE_RIBS = (72, 60, 48)                 # 下/中/上檐瓦垄数（写意，实为数百垄）
TILE_AMP = 0.075                         # 瓦垄起伏幅度

FINIAL_BOT = 35.00                       # 宝顶底（屋面攒尖顶）
FINIAL_TOP = H_TOTAL                     # 38.2
H_LEIGONG = FINIAL_BOT - Z_CHILD_TOP     # 雷公柱：自童柱顶通至宝顶底

# 铺作攒数：每间 3 攒（1 柱头科 + 2 平身科）；up=童柱内圈, upo=挑檐梁外圈
DG_BAYS = {"lo": 3, "mid": 3, "up": 3, "upo": 3}
DG_UNIT_H = 2.16                         # 单攒自身高度系数（scale=1 时桁底标高，×scale=实高）
DG_OUT = 2.30                            # 单攒出跳系数（scale=1 时挑檐桁半径增量）
DG_SPREAD = 1.00                         # 出跳系数（相对高度）

# 爆炸参数（层号递增 → 竖向等距分离；index*EXP_STEP，须大于最厚构件层自身高度）
EXP_STEP = 7.00
SPREAD_M = 8.00

# ─────────────────────────── 通用几何工具 ───────────────────────────

STATS = {"objects": 0, "layers": 0, "meshes": 0}


def M4(loc=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> Matrix:
    return Matrix.LocRotScale(Vector(loc), Euler(rot, "XYZ"), Vector(scale))


def _new_faces(bm, n0):
    """Blender 5.x 的 bmesh.ops.create_* 只返回 verts，新面用 faces 切片取。"""
    return bm.faces[n0:]


def bm_box(bm, loc, size, rot=(0.0, 0.0, 0.0), mat=0):
    """向 bmesh 追加一个长方体。size = 全长（x,y,z）。"""
    n0 = len(bm.faces)
    r = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Identity(4))
    bmesh.ops.transform(bm, matrix=M4(loc, rot, size), verts=r["verts"])
    if mat:
        for f in _new_faces(bm, n0):
            f.material_index = mat
    return r["verts"]


def _cyl_faces(bm, m, r_bot, r_top, h, seg, mat):
    """手工生成圆柱/圆台（含端面），不依赖 bmesh 算子关键字（Blender 5.x 已改名）。"""
    rings = []
    for zz, rr in ((-h / 2.0, r_bot), (h / 2.0, r_top)):
        if rr < 1e-9:
            rings.append(None)
            continue
        ring = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            ring.append(bm.verts.new(m @ Vector((rr * math.cos(a), rr * math.sin(a), zz))))
        rings.append(ring)
    lo, hi = rings
    if lo and hi:
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((lo[i], lo[j], hi[j], hi[i])).material_index = mat
    for ring, zz, flip in ((lo, -h / 2.0, True), (hi, h / 2.0, False)):
        if not ring:
            continue
        c = bm.verts.new(m @ Vector((0, 0, zz)))
        for i in range(seg):
            j = (i + 1) % seg
            f = bm.faces.new((c, ring[j], ring[i]) if flip else (c, ring[i], ring[j]))
            f.material_index = mat
    bm.normal_update()


def bm_cyl(bm, loc, r_bot, r_top, h, seg=20, rot=(0.0, 0.0, 0.0), mat=0):
    """向 bmesh 追加一个（可收分的）圆柱/圆台，loc 为底面中心。"""
    _cyl_faces(bm, M4((loc[0], loc[1], loc[2] + h / 2.0), rot), r_bot, r_top, h, seg, mat)


def bm_sphere(bm, loc, r, seg=16, rings=10, mat=0):
    """手工生成 UV 球。"""
    m = M4(loc)
    bands = []
    for j in range(rings + 1):
        phi = math.pi * j / rings
        rr, zz = r * math.sin(phi), r * math.cos(phi)
        if rr < 1e-9:
            bands.append(bm.verts.new(m @ Vector((0, 0, zz))))
        else:
            bands.append([bm.verts.new(m @ Vector((rr * math.cos(2 * math.pi * i / seg),
                                                   rr * math.sin(2 * math.pi * i / seg), zz)))
                          for i in range(seg)])
    for j in range(rings):
        a, b = bands[j], bands[j + 1]
        if isinstance(a, list) and isinstance(b, list):
            for i in range(seg):
                k = (i + 1) % seg
                bm.faces.new((a[i], a[k], b[k], b[i])).material_index = mat
        elif isinstance(a, list):
            for i in range(seg):
                k = (i + 1) % seg
                bm.faces.new((a[i], a[k], b)).material_index = mat
        else:
            for i in range(seg):
                k = (i + 1) % seg
                bm.faces.new((a, b[i], b[k])).material_index = mat
    bm.normal_update()


def bm_revolve(bm, profile, seg=96, ribs=0, amp=0.0, mat=0, theta0=0.0):
    """由 (radius, z) 断面绕 Z 轴旋转成面。ribs>0 时叠加径向瓦垄起伏。"""
    rings = []
    for (rr, zz) in profile:
        a_eff = amp * min(1.0, max(0.0, rr) / 3.0) if ribs else 0.0
        ring = []
        for i in range(seg):
            th = theta0 + 2.0 * math.pi * i / seg
            rad = rr + a_eff * math.cos(ribs * th) if a_eff else rr
            ring.append(bm.verts.new((rad * math.cos(th), rad * math.sin(th), zz)))
        rings.append(ring)
    for k in range(len(rings) - 1):
        lo, hi = rings[k], rings[k + 1]
        for i in range(seg):
            j = (i + 1) % seg
            try:
                f = bm.faces.new((lo[i], lo[j], hi[j], hi[i]))
                if mat:
                    f.material_index = mat
            except ValueError:
                pass
    bm.normal_update()
    return rings


def bm_tube(bm, p0, p1, w, h, mat=0):
    """沿 p0→p1 的矩形截面杆件（截面 w×h，w 为水平宽、h 为竖向高）。"""
    d = Vector(p1) - Vector(p0)
    L = d.length
    if L < 1e-6:
        return
    z = d.normalized()
    up = Vector((0, 0, 1))
    x = up.cross(z)
    if x.length < 1e-4:
        x = Vector((1, 0, 0))
    x.normalize()
    y = z.cross(x)
    y.normalize()
    m = Matrix((
        (x.x, y.x, z.x, 0), (x.y, y.y, z.y, 0), (x.z, y.z, z.z, 0), (0, 0, 0, 1)))
    m = Matrix.Translation(Vector(p0) + d * 0.5) @ m @ Matrix.Diagonal(Vector((w, h, L, 1)))
    n0 = len(bm.faces)
    bmesh.ops.create_cube(bm, size=1.0, matrix=m)
    if mat:
        for f in _new_faces(bm, n0):
            f.material_index = mat


def to_object(bm, name, mats=None, solidify=0.0, smooth=False):
    if solidify:
        mod = bm  # noqa  (占位，实际用 modifier)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    if mats:
        for m in mats:
            ob.data.materials.append(m)
    if solidify:
        mo = ob.modifiers.new("厚度", "SOLIDIFY")
        mo.thickness = solidify
        mo.use_even_offset = True
        mo.offset = -1.0
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    # 链接进场景集合（层级关系另由 parent 表达，父子与集合归属相互独立）
    if ROOT is not None and ob.name not in ROOT.objects:
        ROOT.objects.link(ob)
    STATS["objects"] += 1
    STATS["meshes"] += 1
    return ob


def to_object_at(bm, name, mats=None, origin=(0.0, 0.0, 0.0),
                 solidify=0.0, smooth=False):
    """生成对象并把**对象原点**设在 origin（几何转为局部坐标）。

    爆炸图的径向张开靠 ``location.x/y`` 驱动器实现，只有当对象原点落在
    构件自身中心时，位移方向才等于该构件的径向；否则（原点在世界原点、
    几何全烘在顶点里）位移恒为 0，张开完全不生效。
    """
    o = Vector(origin)
    for v in bm.verts:
        v.co -= o
    bm.normal_update()
    ob = to_object(bm, name, mats, solidify, smooth)
    ob.location = o
    return ob


def roof_profile(r_e, z_e, r_t, z_t, n=11, p=ROOF_P, droop=0.30):
    """举折屋面断面：檐口平缓、近脊陡峭；檐口带反宇下垂。"""
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((r_e + (r_t - r_e) * t, z_e + (z_t - z_e) * (t ** p)))
    pts[0] = (pts[0][0] + 0.10, pts[0][1] - droop)      # 檐口外挑下垂
    pts[1] = (pts[1][0] + 0.03, pts[1][1] - droop * 0.35)
    return pts


def polar(r, ang):
    return (r * math.cos(ang), r * math.sin(ang), 0.0)


# ─────────────────────────── 材质 ───────────────────────────

def _bsdf(mat):
    mat.use_nodes = True
    nt = mat.node_tree
    for n in nt.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return nt.nodes.new("ShaderNodeBsdfPrincipled")


def _set(bsdf, key, val):
    s = bsdf.inputs.get(key)
    if s is None:
        return
    try:
        s.default_value = val
    except Exception:
        pass


def mat(name, color, rough=0.6, metal=0.0, coat=0.0, spec=None):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    b = _bsdf(m)
    _set(b, "Base Color", (*color, 1.0))
    _set(b, "Roughness", rough)
    _set(b, "Metallic", metal)
    if coat:
        _set(b, "Coat Weight", coat)
        _set(b, "Coat Roughness", 0.15)
    return m


MAT = {}


def build_materials():
    MAT.clear()
    MAT["marble"] = mat("汉白玉", (0.86, 0.855, 0.83), 0.52)
    MAT["stone"] = mat("青石", (0.40, 0.43, 0.45), 0.85)
    MAT["brick"] = mat("金砖", (0.13, 0.125, 0.125), 0.38, coat=0.2)
    MAT["pave"] = mat("砖墁地", (0.36, 0.34, 0.32), 0.9)
    MAT["grass"] = mat("草地", (0.085, 0.14, 0.06), 0.95)
    MAT["col_red"] = mat("红柱", (0.34, 0.055, 0.042), 0.34, coat=0.35)
    MAT["col_dark"] = mat("红柱_暗", (0.28, 0.045, 0.036), 0.40, coat=0.3)
    MAT["paint_blue"] = mat("彩画_青", (0.045, 0.145, 0.215), 0.48)
    MAT["paint_green"] = mat("彩画_绿", (0.055, 0.185, 0.095), 0.48)
    MAT["paint_red"] = mat("彩画_红", (0.32, 0.06, 0.045), 0.45)
    MAT["gold_paint"] = mat("描金", (0.55, 0.375, 0.075), 0.28, metal=0.65)
    MAT["tile"] = mat("蓝琉璃瓦", (0.042, 0.095, 0.245), 0.20, coat=0.55)
    MAT["tile_eave"] = mat("蓝瓦_檐口", (0.030, 0.070, 0.190), 0.22, coat=0.5)
    MAT["gilt"] = mat("鎏金", (0.86, 0.62, 0.19), 0.21, metal=1.0)
    MAT["timber"] = mat("原木", (0.28, 0.165, 0.075), 0.72)
    MAT["timber_paint"] = mat("梁枋彩画", (0.085, 0.155, 0.205), 0.46)
    MAT["lattice"] = mat("隔扇红", (0.30, 0.062, 0.048), 0.42)
    MAT["ceiling"] = mat("天花青绿", (0.048, 0.125, 0.155), 0.50)
    MAT["screen"] = mat("屏风木", (0.22, 0.09, 0.045), 0.55)


# ─────────────────── 层级（爆炸分组）与驱动器 ───────────────────

CTRL = None
LAYERS = []     # (empty, dz, name)


def make_ctrl():
    global CTRL
    CTRL = bpy.data.objects.new("EXPLODE_CTRL", None)
    CTRL.empty_display_type = "ARROWS"
    CTRL.empty_display_size = 6.0
    CTRL["explode"] = SET_EXPLODE
    CTRL["spread"] = SET_EXPLODE
    for k, d in (("explode", "结构爆炸：竖向分层拆解 0..1"),
                 ("spread", "结构爆炸：柱圈/铺作径向张开 0..1")):
        try:
            CTRL.id_properties_ui_create(k).update(
                min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, description=d)
        except Exception:
            pass
    bpy.context.scene.collection.objects.link(CTRL)
    return CTRL


def layer(index, name, coll=None):
    """建立一个结构层空物体；index 决定爆炸时的竖向分离量。"""
    e = bpy.data.objects.new("L%02d_%s" % (index, name), None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 3.0
    (coll or ROOT).objects.link(e)
    e.parent = CTRL
    LAYERS.append((e, index * EXP_STEP, name))
    STATS["layers"] += 1
    return e


_AX = {"x": 0, "y": 1, "z": 2}


def _add_driver(target, chan):
    """driver_add 不接受带索引的路径，需拆成 (path, index)。"""
    if "." in chan:
        path, ax = chan.rsplit(".", 1)
        return target.driver_add(path, _AX[ax])
    return target.driver_add(chan)


def _drv(target, chan, expr):
    fc = _add_driver(target, chan)
    d = fc.driver
    d.type = "SCRIPTED"
    v = d.variables.new()
    v.name = "e"
    v.type = "SINGLE_PROP"
    v.targets[0].id = CTRL
    v.targets[0].data_path = '["explode"]'
    d.expression = expr
    return fc


def _drv2(target, chan, expr):
    fc = _add_driver(target, chan)
    d = fc.driver
    d.type = "SCRIPTED"
    for nm in ("e", "s"):
        v = d.variables.new()
        v.name = nm
        v.type = "SINGLE_PROP"
        v.targets[0].id = CTRL
        v.targets[0].data_path = '["%s"]' % ("explode" if nm == "e" else "spread")
    d.expression = expr
    return fc


def place(ob, lz, rad_k=0.0):
    """把构件挂到结构层，并装上爆炸驱动器。

    lz     : 层空物体
    rad_k  : 径向张开系数（0 = 只随层竖向移动）
    """
    ob.parent = lz
    lx, ly = ob.location.x, ob.location.y
    if rad_k:
        r = math.hypot(lx, ly)
        if r > 1e-6:
            k = SPREAD_M * rad_k
            _drv2(ob, "location.x", "%.5f + %.6f*s" % (lx, lx / r * k))
            _drv2(ob, "location.y", "%.5f + %.6f*s" % (ly, ly / r * k))
    return ob


def finish_layer_drivers():
    for e, dz, _ in LAYERS:
        _drv(e, "location.z", "e*%.4f" % dz)


ROOT = None
SCENE = None


def new_layer(index, name):
    e = layer(index, name, ROOT)
    e.parent = CTRL
    return e


# ─────────────────────────── 场景 / 台基 ───────────────────────────

def build_site():
    bm = bmesh.new()
    bm_box(bm, (0, 0, -0.25), (400, 400, 0.5), mat=1)
    ob = to_object(bm, "地面", [MAT["grass"], MAT["pave"]])
    # 殿前砖墁院
    bm2 = bmesh.new()
    bm_cyl(bm2, (0, 0, 0.0), 75.0, 75.0, 0.06, seg=96)
    ob2 = to_object(bm2, "砖墁院", [MAT["pave"]])
    return ob, ob2


def build_terrace():
    """祈谷坛：三层汉白玉圆台 + 连续石栏杆 + 螭首出水 + 四出陛 + 金砖坛面。"""
    L = new_layer(0, "祈谷坛台基")
    tier_names = ("下层坛", "中层坛", "上层坛")
    for i in range(3):
        r = TERRACE_R[i]
        zb, top = i * TIER_H, (i + 1) * TIER_H
        bm = bmesh.new()
        # 台身（下大上小，带侧分）+ 须弥座束腰线脚
        bm_cyl(bm, (0, 0, zb), r, r - 0.28, TIER_H, seg=128, mat=0)
        bm_cyl(bm, (0, 0, zb + TIER_H * 0.30), r - 0.16, r - 0.22, TIER_H * 0.10, seg=128, mat=0)
        bm_cyl(bm, (0, 0, top - 0.16), r - 0.22, r - 0.30, 0.16, seg=128, mat=0)
        # 连续石栏杆：栏板弦长 ≈1.62 m，每间一望柱（旧制各层栏板合计对应周天度数）
        rb = r - 0.34
        n_bay = max(24, int(round(2 * math.pi * rb / 1.62)))
        step = 2 * math.pi / n_bay
        chord = 2 * rb * math.sin(step / 2)
        for k in range(n_bay):
            a = step * (k + 0.5)
            x, y = rb * math.cos(a), rb * math.sin(a)
            bm_box(bm, (x, y, top - 0.075), (0.22, chord, 0.15), (0, 0, a))      # 寻杖
            bm_box(bm, (x, y, top - 0.62), (0.17, chord * 0.96, 0.94), (0, 0, a))  # 华板
            bm_box(bm, (x, y, top - 1.13), (0.24, chord, 0.10), (0, 0, a))        # 地栿
            aw = step * k
            xw, yw = rb * math.cos(aw), rb * math.sin(aw)
            bm_box(bm, (xw, yw, top - 0.72), (0.30, 0.30, 1.44), (0, 0, aw))      # 望柱
            bm_cyl(bm, (xw, yw, top), 0.17, 0.12, 0.24, seg=12)                   # 望柱头(盘龙/翔凤/朵云)
        # 出水（螭首 / 凤首 / 云朵，写意为挑出栏板下的排水嘴）
        for k in range(24):
            a = 2 * math.pi * (k + 0.5) / 24
            x, y = (r - 0.10) * math.cos(a), (r - 0.10) * math.sin(a)
            bm_box(bm, (x, y, top - 0.98), (0.86, 0.34, 0.26), (0, 0, a))
        ob = to_object(bm, tier_names[i], [MAT["marble"]], smooth=False)
        place(ob, L)
    # 四出陛（南向为御路，较宽）：内高外低，自地面升至坛顶，共 31 级
    n_step = int(round(TERRACE_H / 0.17))
    tread = 0.36
    for a_deg, w in ((270, 9.6), (90, 7.2), (0, 7.2), (180, 7.2)):
        a = math.radians(a_deg)
        bm = bmesh.new()
        for s in range(n_step):
            d = TERRACE_R[0] + (n_step - s) * tread        # 外沿低、内沿高
            bm_box(bm, (d * math.cos(a), d * math.sin(a), s * 0.17 + 0.085),
                   (tread, w, 0.17), (0, 0, a))
            # 两侧踏跺膀（象眼）：贴阶梯两缘的窄条，不盖梯面
            for sgn in (-1, 1):
                off = (w / 2 + 0.25) * sgn
                cx = d * math.cos(a) - math.sin(a) * off
                cy = d * math.sin(a) + math.cos(a) * off
                bm_box(bm, (cx, cy, s * 0.17 + 0.17),
                       (tread, 0.50, 0.34 + s * 0.0), (0, 0, a))
        ob = to_object_at(bm, "出陛_%d度" % a_deg, [MAT["marble"]],
                          origin=(TERRACE_R[0] * math.cos(a), TERRACE_R[0] * math.sin(a), 0))
        place(ob, L)
    # 坛面金砖（复原「旧时三层坛面俱墁金砖」）；半径略小于台身顶面，避免飞边
    for i in range(3):
        top = (i + 1) * TIER_H
        rr = TERRACE_R[i] - 0.30
        bm = bmesh.new()
        bm_cyl(bm, (0, 0, top - 0.05), rr, rr, 0.05, seg=128, mat=0)
        ob = to_object(bm, "坛面金砖_%s" % tier_names[i], [MAT["brick"]])
        place(ob, L)
    return L


# ─────────────────────────── 柱网 ───────────────────────────

def _cyl_between(bm, p0, p1, r0, r1, seg=24, mat=0):
    """底心 p0 → 顶心 p1 的收分圆柱（支持倾斜，用于真实表达侧脚）。"""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    if L < 1e-6:
        return
    z = d.normalized()
    x = Vector((0, 0, 1)).cross(z)
    if x.length < 1e-4:
        x = Vector((1, 0, 0))
    x.normalize()
    y = z.cross(x)
    y.normalize()
    rings = []
    for t, rr in ((0.0, r0), (1.0, r1)):
        c = p0 + z * (L * t)
        rings.append([bm.verts.new(c + (x * math.cos(2 * math.pi * i / seg)
                                        + y * math.sin(2 * math.pi * i / seg)) * rr)
                      for i in range(seg)])
    lo, hi = rings
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((lo[i], lo[j], hi[j], hi[i])).material_index = mat
    for ring, c, flip in ((lo, p0, True), (hi, p1, False)):
        cv = bm.verts.new(c)
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((cv, ring[j], ring[i]) if flip else (cv, ring[i], ring[j])).material_index = mat
    bm.normal_update()


_TILT_K = {"eave": 1.0, "gold": 0.6, "dragon": 0.25, "child": 0.6}


def _pillar_local(bm, ring, h, d_bot, d_top, mat_idx):
    """单根柱：柱脚置于局部原点，侧脚使柱顶向局部 -X（殿心方向）微倾。

    局部约定：+X = 径向外，+Y = 切向。对象再绕 Z 旋转安装角即就位。
    """
    bh, br = BASE_H[ring], BASE_R[ring]
    bm_cyl(bm, (0, 0, 0), br * 1.22, br, bh * 0.22, seg=24, mat=0)             # 磉石下枰
    bm_cyl(bm, (0, 0, bh * 0.22), br, br * 0.80, bh * 0.78, seg=24, mat=0)     # 柱础古镜
    tilt = TILT * _TILT_K[ring]
    top = (-math.sin(tilt) * h, 0.0, bh + math.cos(tilt) * h)
    _cyl_between(bm, (0, 0, bh), top, d_bot / 2.0, d_top / 2.0, seg=24, mat=mat_idx)
    return top


def _add_pillar(L, ring, idx, ang, r, h, dd, m, z0, name, spread_k):
    """柱身几何建在**局部原点**（柱脚 z=0、轴心 r=0），故只设 location 定位，
    不能再按绝对坐标做 origin 平移（那会把柱子搬到殿心并落地）。"""
    bm = bmesh.new()
    _pillar_local(bm, ring, h, dd[0], dd[1], 1)
    ob = to_object(bm, name, [MAT["marble"], m], smooth=True)
    ob.location = (r * math.cos(ang), r * math.sin(ang), z0)
    ob.rotation_euler = (0, 0, ang)
    place(ob, L, spread_k)
    return ob


def build_columns():
    """二十八根楠木大柱（环转排列，殿顶不用大梁长檩）+ 藻井周围 8 根童柱。

    每根柱独立成对象、原点设在柱脚 —— 爆炸时才能沿各自径向张开，
    让「外圈12檐柱 / 中圈12金柱 / 内圈4龙井柱」三环柱网分离可读。
    """
    L = new_layer(2, "柱网_28大柱")
    groups = (
        ("eave", 12, R_EAVE, H_EAVE, D_EAVE, MAT["col_red"], "檐柱", 1.00, 0.0),
        ("gold", 12, R_GOLD, H_GOLD, D_GOLD, MAT["col_red"], "金柱", 0.62, 0.0),
        ("dragon", 4, R_DRAGON, H_DRAGON, D_DRAGON, MAT["col_dark"], "龙井柱", 0.00, math.pi / 4),
    )
    tops = {}
    for ring, n, r, h, dd, m, cn, sk, offs in groups:
        for k in range(n):
            a = offs + 2 * math.pi * k / n
            nm = "%s%02d" % (cn, k + 1)
            _add_pillar(L, ring, k, a, r, h, dd, m, Z_FLOOR, nm, sk)
            tops[nm] = (r * math.cos(a), r * math.sin(a), Z_FLOOR + BASE_H[ring] + h)
    # 童柱 8 根：立于金柱枋/抹角梁之上（Z_CHILD_BOT），承上檐攒尖
    L2 = new_layer(2, "柱网_童柱8")
    for k in range(8):
        a = math.pi / 8 + 2 * math.pi * k / 8
        _add_pillar(L2, "child", k, a, R_CHILD, H_CHILD, D_CHILD, MAT["col_red"],
                    Z_CHILD_BOT, "童柱%02d" % (k + 1), 0.42)
    return tops


# ─────────────────── 梁枋（36 枋桷）与铺作（斗拱） ───────────────────

def _ring_beam(bm, r, z, w, h, n=48, mat=0, seg_off=0.0):
    """圈梁（枋）：沿圆周分段的矩形枋。"""
    for k in range(n):
        a0 = seg_off + 2 * math.pi * k / n
        a1 = seg_off + 2 * math.pi * (k + 1) / n
        am = (a0 + a1) / 2
        p0 = (r * math.cos(a0), r * math.sin(a0), z)
        p1 = (r * math.cos(a1), r * math.sin(a1), z)
        bm_tube(bm, p0, p1, w, h, mat)


BEAM_MATS = None


def _beam_obj(L, name, p0, p1, w, h, mat_idx, spread_k):
    """单根梁枋独立成对象，原点取构件中点（爆炸时沿自身径向外移）。"""
    bm = bmesh.new()
    bm_tube(bm, p0, p1, w, h, mat_idx)
    mid = (Vector(p0) + Vector(p1)) / 2.0
    ob = to_object_at(bm, name, BEAM_MATS, origin=tuple(mid))
    place(ob, L, spread_k)
    return ob


def _nearest_ang(a, cands):
    return min(cands, key=lambda c: abs((a - c + math.pi) % (2 * math.pi) - math.pi))


def _pt(r, a, z):
    return (r * math.cos(a), r * math.sin(a), z)


def build_beams():
    """三十六根枋桷互相衔接（殿顶不用大梁长檩）：

    12 抱头梁（檐柱头→金柱头，**水平**拉结，承下檐屋面）
    + 12 跨空枋（金柱头→龙井柱身，水平，把 24 m 大跨环向锁固）
    + 12 金柱枋（相邻金柱间环向联系）= 36
    """
    global BEAM_MATS
    BEAM_MATS = [MAT["timber_paint"], MAT["paint_green"], MAT["paint_blue"]]
    L = new_layer(3, "梁枋_36枋桷")
    z_e, z_g = Z_EAVE_TOP - 0.22, Z_GOLD_TOP - 0.22
    for k in range(12):
        a = 2 * math.pi * k / 12
        a2 = 2 * math.pi * (k + 1) / 12
        # 抱头梁：檐柱头 → 金柱头，**同标高水平**（跨中略起拱），两段
        pe, pg, pg2 = _pt(R_EAVE, a, z_e), _pt(R_GOLD, a, z_e), _pt(R_GOLD, a2, z_e)
        mid = ((pe[0] + pg[0]) / 2, (pe[1] + pg[1]) / 2, z_e + 0.30)
        _beam_obj(L, "抱头梁%02d_a" % (k + 1), pe, mid, 0.62, 0.80, 1, 0.86)
        _beam_obj(L, "抱头梁%02d_b" % (k + 1), mid, pg, 0.62, 0.80, 1, 0.72)
        # 跨空枋：金柱头 → 龙井柱身（水平），环向锁固大跨
        _beam_obj(L, "跨空枋%02d" % (k + 1), pg, _pt(R_DRAGON, a, z_g), 0.46, 0.62, 2, 0.30)
        # 金柱枋：相邻金柱间环向联系枋
        _beam_obj(L, "金柱枋%02d" % (k + 1), pg, pg2, 0.36, 0.56, 2, 0.62)
    # 檐柱额枋（环向 12 段，连成刚性环）
    L2 = new_layer(3, "梁枋_额枋")
    for k in range(12):
        a, a2 = 2 * math.pi * k / 12, 2 * math.pi * (k + 1) / 12
        _beam_obj(L2, "檐柱额枋%02d" % (k + 1), _pt(R_EAVE, a, z_e - 0.72),
                  _pt(R_EAVE, a2, z_e - 0.72), 0.34, 0.56, 2, 1.00)
    return L


def build_frame():
    """龙井柱顶「井口枋 + 抹角梁」方转八角框架 + 童柱枋 + 挑檐梁 + 雷公柱。

    这是祈年殿上檐攒尖的核心承托：4 根井口枋在龙井柱顶围成方框，
    4 根抹角梁切去四角转为八角，8 根童柱（钻金柱）立于八角顶点，
    8 根挑檐梁自八角边中点悬挑至 r=8.0 承上檐外圈斗拱；中心立雷公柱直抵宝顶。
    """
    L = new_layer(3, "梁枋_井口枋抹角梁")
    zf, zt = Z_DRAG_TOP, Z_DRAG_TOP + H_JKF          # 框架占 25.02 ~ 25.57
    zc = (zf + zt) / 2.0
    sq = [math.pi / 4 + math.pi / 2 * m for m in range(4)]       # 方框角 = 龙井柱位
    oc = [math.pi / 8 + math.pi / 4 * k for k in range(8)]       # 八角顶点 = 童柱位
    # 4 根井口枋（方框四边）
    for m in range(4):
        _beam_obj(L, "井口枋%d" % (m + 1), _pt(R_DRAGON, sq[m], zc),
                  _pt(R_DRAGON, sq[(m + 1) % 4], zc), 0.62, H_JKF, 1, 0.0)
    # 4 根抹角梁（切角，方→八角）
    for m in range(4):
        _beam_obj(L, "抹角梁%d" % (m + 1), _pt(OCT_VERT, oc[2 * m + 1], zc),
                  _pt(OCT_VERT, oc[(2 * m + 2) % 8], zc), 0.56, H_JKF * 0.86, 2, 0.0)
    # 8 根童柱枋（八角环，连童柱头）
    L2 = new_layer(3, "梁枋_童柱枋挑檐梁")
    ztf = Z_CHILD_TOP - 0.20
    for k in range(8):
        _beam_obj(L2, "童柱枋%02d" % (k + 1), _pt(OCT_VERT, oc[k], ztf),
                  _pt(OCT_VERT, oc[(k + 1) % 8], ztf), 0.30, 0.44, 2, 0.0)
    # 8 根挑檐梁：自八角边中点（r=3.04）贯通井口枋框架悬挑至 r=8.0
    mid8 = [math.pi / 4 + math.pi / 4 * k for k in range(8)]
    for k in range(8):
        a = mid8[k]
        _beam_obj(L2, "挑檐梁%02d" % (k + 1), _pt(OCT_APO, a, Z_CANT),
                  _pt(R_CANT, a, Z_CANT), 0.34, 0.46, 1, 0.30)
    # 雷公柱：中心通柱，自框架面直抵宝顶底（攒尖顶的「 King post 」）
    L3 = new_layer(3, "雷公柱")
    bm = bmesh.new()
    _cyl_between(bm, (0, 0, zt), (0, 0, FINIAL_BOT), 0.42, 0.28, seg=20, mat=1)
    ob = to_object_at(bm, "雷公柱", BEAM_MATS, origin=(0, 0, (zt + FINIAL_BOT) / 2))
    place(ob, L3, 0.0)
    return L


def build_purlins():
    """桁（檩）环：每圈铺作的正心桁与挑檐桁，沿圆周闭合，承椽望板。

    标高严格等于该檐斗拱顶 = 屋面内沿，故屋面不悬空、檩不穿瓦。
    """
    L = new_layer(3, "桁檩环")
    rings = (
        ("下檐正心桁", R_EAVE, Z_DG_LO, DG_H[0]),
        ("下檐挑檐桁", R_EAVE + DG_OUT * DG_H[0] / DG_UNIT_H, Z_DG_LO, DG_H[0]),
        ("中檐正心桁", R_GOLD, Z_DG_MID, DG_H[1]),
        ("中檐挑檐桁", R_GOLD + DG_OUT * DG_H[1] / DG_UNIT_H, Z_DG_MID, DG_H[1]),
        ("上檐内圈桁", R_CHILD, Z_DG_UP, DG_H[2]),
        ("上檐挑檐桁", R_CANT + DG_OUT * DG_H[2] / DG_UNIT_H, Z_DG_UP_OUT, DG_H[2]),
    )
    for nm, r, z, hdg in rings:
        s = hdg / DG_UNIT_H
        bm = bmesh.new()
        nseg = 24
        for k in range(nseg):
            a0, a1 = 2 * math.pi * k / nseg, 2 * math.pi * (k + 1) / nseg
            _cyl_between(bm, _pt(r, a0, z), _pt(r, a1, z),
                         0.17 * s, 0.17 * s, seg=10, mat=0)
        ob = to_object_at(bm, nm, BEAM_MATS, origin=(0, 0, z), smooth=True)
        place(ob, L, min(1.0, r / R_EAVE))
    return L


def _dg_box(bm, cx, cy, d, t, dp, tp, z, ld, lt, h, rot_z, mat):
    """斗拱构件：dp=沿径向(出跳)偏移, tp=沿切向偏移; ld/lt=径向/切向全长。

    rot_z=径向角时 bm_box 的局部 x 轴即径向、y 轴即切向，故 size 直接写 (ld, lt, h)。
    """
    bm_box(bm, (cx + d.x * dp + t.x * tp, cy + d.y * dp + t.y * tp, z),
           (ld, lt, h), (0, 0, rot_z), mat)


def _dougong_unit(bm, x, y, z, rot_z, scale=1.0, mat=0, mat2=1):
    """一攒清式五踩重昂斗拱（构件齐全，非色块示意）。

    自下而上：栌斗 → 头翘+正心瓜拱 → 头昂+外拽瓜拱+正心万拱 →
    二昂+外拽万拱+厢拱 → 耍头(蚂蚱头)+撑头 → 挑檐枋 → 桁(檩)。
    「升」承于各拱端；昂为斜置杠杆（下昂），里跳压于梁架之下。
    """
    s = scale
    d = Vector((math.cos(rot_z), math.sin(rot_z), 0.0))    # 径向（出跳方向）
    t = Vector((-math.sin(rot_z), math.cos(rot_z), 0.0))   # 切向
    box = lambda dp, tp, zz, ld, lt, h, m: _dg_box(
        bm, x, y, d, t, dp * s, tp * s, z + zz * s, ld * s, lt * s, h * s, rot_z, m)

    # ── 栌斗（斗耳/斗平/斗欹三段收分）──
    box(0, 0, 0.06, 0.66, 0.66, 0.12, mat)
    box(0, 0, 0.20, 0.58, 0.58, 0.16, mat)
    box(0, 0, 0.32, 0.48, 0.48, 0.10, mat2)

    # ── 第一跳：头翘（径向）+ 正心瓜拱（切向）+ 三斗升 ──
    z1 = 0.46
    box(0, 0, z1, 1.36, 0.17, 0.22, mat2)              # 头翘
    box(0, 0, z1, 0.17, 1.66, 0.22, mat2)              # 正心瓜拱
    for sgn in (-1, 1):
        box(0.68 * sgn, 0, z1 + 0.18, 0.24, 0.24, 0.14, mat)   # 翘头升
        box(0, 0.83 * sgn, z1 + 0.18, 0.24, 0.24, 0.14, mat)   # 瓜拱端升

    # ── 头昂（下昂：里高外低的斜置杠杆，昂嘴朝外下）+ 外拽瓜拱 + 正心万拱 ──
    z2 = 0.92
    bm_tube(bm, (x - d.x * 0.55 * s, y - d.y * 0.55 * s, z + 1.34 * s),
            (x + d.x * 1.62 * s, y + d.y * 1.62 * s, z + 0.58 * s),
            0.20 * s, 0.13 * s, mat)                   # 昂身（后尾高、昂嘴低）
    box(1.78, 0, 0.50, 0.46, 0.30, 0.12, mat2)          # 昂嘴（斜切出头）
    box(1.06, 0, z2, 0.17, 1.42, 0.20, mat2)           # 外拽瓜拱
    box(0, 0, z2 + 0.06, 0.20, 2.24, 0.20, mat2)       # 正心万拱
    for sgn in (-1, 1):
        box(1.06, 0.71 * sgn, z2 + 0.17, 0.22, 0.22, 0.13, mat)
        box(0, 1.12 * sgn, z2 + 0.23, 0.22, 0.22, 0.13, mat)

    # ── 二昂 + 外拽万拱 + 厢拱 ──
    z3 = 1.30
    bm_tube(bm, (x - d.x * 0.35 * s, y - d.y * 0.35 * s, z + 1.76 * s),
            (x + d.x * 2.10 * s, y + d.y * 2.10 * s, z + 0.96 * s),
            0.19 * s, 0.12 * s, mat)
    box(2.26, 0, 0.88, 0.44, 0.28, 0.12, mat2)          # 二昂嘴
    box(1.56, 0, z3 + 0.02, 0.17, 1.88, 0.20, mat2)    # 外拽万拱
    box(2.10, 0, z3 + 0.20, 0.17, 1.48, 0.18, mat2)    # 厢拱
    for sgn in (-1, 1):
        box(1.56, 0.94 * sgn, z3 + 0.19, 0.22, 0.22, 0.13, mat)
        box(2.10, 0.74 * sgn, z3 + 0.36, 0.22, 0.22, 0.13, mat)

    # ── 耍头（蚂蚱头）+ 撑头（菊花头）：昂后尾的水平出头 ──
    box(2.34, 0, z3 + 0.44, 0.74, 0.20, 0.16, mat2)
    box(2.44, 0, z3 + 0.60, 0.34, 0.34, 0.14, mat)
    box(2.62, 0, z3 + 0.44, 0.30, 0.18, 0.16, mat2)    # 撑头出头

    # ── 正心枋 + 挑檐枋（贯穿各攒锁成环；桁由 build_purlins 整圈生成，避免双檩）──
    box(0, 0, z3 + 0.62, 0.24, 2.86, 0.30, mat)
    box(2.02, 0, z3 + 0.62, 0.30, 1.30, 0.28, mat)
    return DG_OUT * s, (z3 + 0.86) * s                  # (出跳距离, 桁底相对高)


def build_dougong(tier_key, r_base, z_base, n_bays, layer_idx, name, ang_off=0.0):
    """一圈铺作层：每间 3 攒（1 柱头科 + 2 平身科），rot_z=径向角（昂挑向殿外）。

    scale 由 DG_H 反算，保证「铺作顶 = 该檐正心桁标高 = 屋面内沿标高」，构件不互穿。
    """
    L = new_layer(layer_idx, "铺作_%s" % name)
    bm = bmesh.new()
    n_total = n_bays * DG_BAYS[tier_key]
    step = 2 * math.pi / n_total
    s = DG_H[{"lo": 0, "mid": 1, "up": 2, "upo": 2}[tier_key]] / DG_UNIT_H * DG_SPREAD
    out_max = 0.0
    for k in range(n_total):
        a = ang_off + step * k + step / 2
        out, _ = _dougong_unit(bm, r_base * math.cos(a), r_base * math.sin(a),
                               z_base, a, s, 0, 1)
        out_max = max(out_max, out)
    # 正心枋环 + 挑檐枋环（把整圈攒连成刚性环，即「溜金斗拱」层层拉接之意）
    _ring_beam(bm, r_base, z_base + DG_H[{"lo": 0, "mid": 1, "up": 2, "upo": 2}[tier_key]] * 0.86,
               0.26 * s, 0.30 * s, n=n_total, mat=1)
    ob = to_object(bm, name, [MAT["paint_blue"], MAT["paint_green"]])
    place(ob, L, {"lo": 1.0, "mid": 0.62, "up": 0.30, "upo": 0.34}[tier_key])
    return L, r_base + out_max


def build_all_dougong():
    build_dougong("lo", R_EAVE, Z_EAVE_TOP, 12, 4, "下檐铺作_檐柱12")
    build_dougong("mid", R_GOLD, Z_GOLD_TOP, 12, 6, "中檐铺作_金柱12")
    build_dougong("up", R_CHILD, Z_CHILD_TOP, 8, 8, "上檐铺作_童柱8")
    build_dougong("upo", R_CANT, Z_CANT, 8, 8, "上檐外圈铺作_挑檐梁8",
                  ang_off=math.pi / 8)


# ─────────────────────────── 屋面 / 宝顶 ───────────────────────────

def build_roof(tier, prof, seg, ribs, layer_idx, name, p=ROOF_P):
    r_e, z_e, r_t, z_t = prof
    L = new_layer(layer_idx, "屋面_%s" % name)
    pts = roof_profile(r_e, z_e, r_t, z_t, n=12, p=p)
    # 瓦面
    bm = bmesh.new()
    bm_revolve(bm, pts, seg=seg, ribs=ribs, amp=TILE_AMP, mat=0)
    ob = to_object(bm, name + "_瓦面", [MAT["tile"]], solidify=0.16, smooth=True)
    place(ob, L, {"lo": 1.0, "mid": 0.7, "up": 0.35}[tier])
    # 檐口（勾头滴水 + 封檐板）
    bm = bmesh.new()
    bm_revolve(bm, [(r_e + 0.28, z_e - 0.34), (r_e + 0.34, z_e - 0.16),
                    (r_e + 0.30, z_e - 0.02), (r_e + 0.02, z_e + 0.10)],
               seg=seg, ribs=ribs, amp=TILE_AMP, mat=0)
    ob = to_object(bm, name + "_檐口", [MAT["tile_eave"]], solidify=0.10, smooth=True)
    place(ob, L, {"lo": 1.0, "mid": 0.7, "up": 0.35}[tier])
    # 垂脊 / 戗脊（下、中檐各 8 条，放射自攒尖）
    if tier != "up":
        bm = bmesh.new()
        n_ridge = 8
        for k in range(n_ridge):
            a = 2 * math.pi * k / n_ridge + (0 if tier == "lo" else math.pi / n_ridge)
            for i in range(6):
                t0, t1 = i / 6.0, (i + 1) / 6.0
                p0 = prof_pt(pts, r_e, r_t, t0)
                p1 = prof_pt(pts, r_e, r_t, t1)
                q0 = (p0[0] * math.cos(a), p0[0] * math.sin(a), p0[1])
                q1 = (p1[0] * math.cos(a), p1[0] * math.sin(a), p1[1])
                bm_tube(bm, (q0[0], q0[1], q0[2] + 0.10), (q1[0], q1[1], q1[2] + 0.10),
                        0.30, 0.30, 1)
        ob = to_object(bm, name + "_垂脊", [MAT["tile"], MAT["gilt"]])
        place(ob, L, {"lo": 1.0, "mid": 0.7, "up": 0.35}[tier])
    return L


def prof_pt(pts, r_e, r_t, t):
    i = min(len(pts) - 1, int(t * (len(pts) - 1)))
    return pts[i]


def build_roofs():
    seg = 128
    build_roof("lo", ROOF_LO, seg, TILE_RIBS[0], 5, "下檐屋面")
    build_roof("mid", ROOF_MID, 128, TILE_RIBS[1], 7, "中檐屋面")
    build_roof("up", ROOF_UP, 96, TILE_RIBS[2], 9, "上檐屋面_攒尖", p=ROOF_P_UP)
    # 椽（枋桷之桷）：三重檐各自成层，爆炸时跟随所属屋面
    for tier, (r_e, z_e, r_t, z_t, n), li in (
            ("下檐椽", (ROOF_LO[0], ROOF_LO[1], ROOF_LO[2], ROOF_LO[3], 96), 5),
            ("中檐椽", (ROOF_MID[0], ROOF_MID[1], ROOF_MID[2], ROOF_MID[3], 84), 7),
            ("上檐椽", (ROOF_UP[0], ROOF_UP[1], ROOF_UP[2], ROOF_UP[3], 64), 9)):
        L = new_layer(li, "椽_%s" % tier)
        bm = bmesh.new()
        for k in range(n):
            a = 2 * math.pi * k / n
            ca, sa = math.cos(a), math.sin(a)
            p0 = (r_e * ca, r_e * sa, z_e - 0.28)
            p1 = ((r_e + (r_t - r_e) * 0.34) * ca, (r_e + (r_t - r_e) * 0.34) * sa,
                  z_e + (z_t - z_e) * (0.34 ** ROOF_P) - 0.12)
            bm_tube(bm, p0, p1, 0.10, 0.14, 0)
        ob = to_object(bm, tier, [MAT["timber"]])
        place(ob, L, {"5": 1.0, "7": 0.7, "9": 0.35}[str(li)])


def build_finial():
    """鎏金宝顶：仰莲 + 宝珠 + 圆光 + 顶尖，总高约 3.6 m，收在 38.2 m。"""
    L = new_layer(10, "宝顶")
    bm = bmesh.new()
    z = FINIAL_BOT
    bm_cyl(bm, (0, 0, z), 1.55, 1.20, 0.45, seg=48, mat=0)                 # 受花/基座
    z += 0.45
    for i in range(2):                                                       # 仰莲两层
        bm_cyl(bm, (0, 0, z), 1.25 - i * 0.18, 1.42 - i * 0.20, 0.32, seg=48, mat=1)
        z += 0.32
    bm_cyl(bm, (0, 0, z), 1.05, 1.02, 0.95, seg=48, mat=0)                   # 圆光（宝瓶身）
    z += 0.95
    bm_sphere(bm, (0, 0, z + 0.30), 0.42, seg=24, rings=14, mat=2)            # 宝珠
    z += 0.72
    bm_cyl(bm, (0, 0, z), 0.13, 0.03, 0.52, seg=16, mat=0)                    # 顶尖
    ob = to_object(bm, "鎏金宝顶", [MAT["gilt"], MAT["gilt"], MAT["gilt"]], smooth=True)
    place(ob, L, 0.0)
    return L


# ─────────────────────────── 殿内装修 ───────────────────────────

def build_interior():
    # 隔扇门（外圈 12 间，殿内四周不用墙壁）
    L = new_layer(1, "隔扇门窗")
    bm = bmesh.new()
    n = 12
    for k in range(n):
        a = 2 * math.pi * (k + 0.5) / n
        r = R_EAVE + 0.30
        x, y = r * math.cos(a), r * math.sin(a)
        z = Z_FLOOR
        for j in range(4):                                     # 每间四扇
            off = (j - 1.5) * 1.72
            ca, sa = math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)
            bm_box(bm, (x + ca * off, y + sa * off, z + 3.30),
                   (1.62, 0.16, 6.30), rot=(0, 0, a + math.pi / 2), mat=0)
            bm_box(bm, (x + ca * off, y + sa * off, z + 5.20),
                   (1.30, 0.20, 1.90), rot=(0, 0, a + math.pi / 2), mat=1)   # 棂花格心
        bm_box(bm, (x, y, z + 6.80), (7.0, 0.34, 0.42), rot=(0, 0, a + math.pi / 2), mat=2)
    ob = to_object(bm, "隔扇门_12间", [MAT["lattice"], MAT["gold_paint"], MAT["paint_red"]])
    place(ob, L, 1.0)

    # 三层天花（三重檐相应设置三层天花；半径须落在对应柱圈**内侧**，不穿柱）
    for idx, (name, r, z, lk, li) in enumerate((
            ("天花_上层", 3.15, Z_CHILD_TOP - 0.30, 0.30, 9),
            ("天花_中层", 8.80, Z_GOLD_TOP - 0.50, 0.60, 7),
            ("天花_下层", 12.80, Z_EAVE_TOP - 0.60, 1.0, 5))):
        L = new_layer(li, name)
        bm = bmesh.new()
        bm_cyl(bm, (0, 0, z), r, r, 0.14, seg=96, mat=0)
        n_coff = (12, 24, 32)[idx]
        for k in range(n_coff):
            a = 2 * math.pi * k / n_coff
            bm_box(bm, ((r - 0.9) * math.cos(a), (r - 0.9) * math.sin(a), z - 0.16),
                   (1.30, 1.30, 0.20), rot=(0, 0, a), mat=1)
        ob = to_object(bm, name, [MAT["ceiling"], MAT["gold_paint"]])
        place(ob, L, lk)

    # 九龙藻井（殿顶中央，与地面龙凤石相应；层层向心收束，雷公柱藏于其中）
    L = new_layer(9, "九龙藻井")
    bm = bmesh.new()
    za = Z_CHILD_TOP - 0.30
    COFFER = ((3.00, 0.50), (2.40, 0.55), (1.85, 0.60), (1.30, 0.62), (0.75, 0.55))
    zz = za
    for i, (rr, hh) in enumerate(COFFER):
        bm_cyl(bm, (0, 0, zz), rr, rr * 0.82, hh, seg=48, mat=0)
        zz += hh
        for k in range(9):
            a = 2 * math.pi * k / 9
            bm_box(bm, ((rr - 0.25) * math.cos(a), (rr - 0.25) * math.sin(a),
                        za + sum(h for _, h in
                                 ((4.0, 0.5), (3.2, 0.6), (2.4, 0.7), (1.6, 0.8))[:i]) + hh * 0.5),
                   (0.34, 0.34, hh * 0.8), rot=(0, 0, a), mat=1)
    ob = to_object(bm, "九龙藻井", [MAT["ceiling"], MAT["gilt"]])
    place(ob, L, 0.0)

    # 神座：北侧雕龙宝座 + 东西配座 + 木质浮雕屏风
    L = new_layer(1, "神座屏风")
    bm = bmesh.new()
    for deg, w, main in ((180, 4.4, True), (90, 3.2, False), (270, 3.2, False)):
        a = math.radians(deg)
        r = 6.6 if main else 5.4
        x, y = r * math.cos(a), r * math.sin(a)
        bm_cyl(bm, (x, y, Z_FLOOR), w * 0.62, w * 0.58, 0.85, seg=32, mat=0)     # 圆形石台
        bm_box(bm, (x, y, Z_FLOOR + 1.55), (w, w * 0.8, 1.30), rot=(0, 0, a), mat=1)
        bm_box(bm, (x - math.sin(a) * w * 0.34, y + math.cos(a) * w * 0.34, Z_FLOOR + 2.60),
               (w * 1.0, w * 1.5, 2.10), rot=(0, 0, a), mat=2)                   # 浮雕屏风
    ob = to_object(bm, "神座与屏风", [MAT["marble"], MAT["gilt"], MAT["screen"]])
    place(ob, L, 1.0)


# ─────────────────────────── 场景 / 灯光 / 相机 ───────────────────────────

def setup_scene():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES" if bpy.app.version >= (4, 2, 0) else "CYCLES"
    try:
        sc.cycles.device = "CPU"
        sc.cycles.samples = 64
    except Exception:
        pass
    sc.render.resolution_x = 1600
    sc.render.resolution_y = 1200
    sc.unit_settings.system = "METRIC"
    sc.unit_settings.scale_length = 1.0
    sc.unit_settings.length_unit = "METERS"

    # 环境：浅色天光背景（Blender 5.x 已无 NISHITA，改用 Background + SUN 灯）
    try:
        w = sc.world or bpy.data.worlds.new("World")
        sc.world = w
        w.use_nodes = True
        nt = w.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new("ShaderNodeOutputWorld")
        bg = nt.nodes.new("ShaderNodeBackground")
        bg.inputs["Color"].default_value = (0.55, 0.66, 0.82, 1.0)
        bg.inputs["Strength"].default_value = 0.85
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    except Exception as e:
        log("world failed:", e)

    sun = bpy.data.objects.new("太阳", bpy.data.lights.new("太阳", "SUN"))
    sun.data.energy = 3.6
    sun.rotation_euler = (math.radians(52), math.radians(12), math.radians(205))
    sc.collection.objects.link(sun)

    cam_d = bpy.data.cameras.new("外观相机")
    cam_d.lens = 50
    cam_d.clip_end = 4000
    cam = bpy.data.objects.new("Camera", cam_d)
    cam.location = (78, -92, 34)
    cam.rotation_euler = Euler((math.radians(72), 0, math.radians(40)), "XYZ")
    sc.collection.objects.link(cam)
    sc.camera = cam


def _look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def rig_cameras():
    sc = bpy.context.scene
    cams = {}
    presets = {
        "外观_南": ((70, -86, 30), (0, 0, 17)),
        "外观_东北": ((92, 74, 38), (0, 0, 18)),
        "爆炸图_轴测": ((86, -104, 78), (0, 0, 24)),
        "结构骨架_剖视": ((30, -40, 24), (0, 0, 18)),
    }
    for name, (pos, tgt) in presets.items():
        cd = bpy.data.cameras.new("cam_" + name)
        cd.lens = 42 if "外观" in name else 48
        cd.clip_end = 4000
        c = bpy.data.objects.new("Cam_" + name, cd)
        c.location = Vector(pos)
        _look_at(c, tgt)
        sc.collection.objects.link(c)
        cams[name] = c
    return cams


# ─────────────────────────── 总装 ───────────────────────────

def build_all():
    global ROOT, SCENE
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)
    for mm in list(bpy.data.materials):
        bpy.data.materials.remove(mm)

    SCENE = bpy.context.scene
    ROOT = bpy.data.collections.new("祈年殿")
    SCENE.collection.children.link(ROOT)

    build_materials()
    make_ctrl()
    build_site()
    build_terrace()          # 层 0：祈谷坛
    build_interior()         # 层 1：装修/神座
    build_columns()          # 层 2：28 大柱 + 8 童柱
    build_beams()            # 层 3：36 枋桷（抱头梁/跨空枋/金柱枋）
    build_frame()            # 层 3：井口枋方转八角 + 挑檐梁 + 雷公柱
    build_purlins()          # 层 3：桁（檩）环
    build_all_dougong()      # 层 4/6/8：三重铺作（上檐内外两圈）
    build_roofs()            # 层 5/7/9：三重檐屋面 + 椽
    build_finial()           # 层 6：鎏金宝顶
    finish_layer_drivers()
    SCENE.update_tag()
    log("built objects=%d layers=%d" % (STATS["objects"], len(LAYERS)))


def save_blend():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "qiniandian.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    log("saved", path)
    return path


def export_glb():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "qiniandian.glb")
    try:
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB",
                                  use_selection=False, export_yup=True)
        log("glb", path)
        return path
    except Exception as e:
        log("glb failed:", e)
        return None


def main():
    build_all()
    rig_cameras()
    setup_scene()
    saved = save_blend() if DO_SAVE else None
    glb = export_glb() if DO_GLB else None
    print("TEA_BLENDER_RESULT " + json.dumps({
        "objects": STATS["objects"],
        "layers": len(LAYERS),
        "explode_ctrl": "EXPLODE_CTRL",
        "blend": saved,
        "glb": glb,
        "height_m": H_TOTAL,
        "terrace_m": TERRACE_H,
        "eave_diameter_m": EAVE_DIA,
        "pillars": {"龙井柱": 4, "金柱": 12, "檐柱": 12, "童柱": 8},
    }, ensure_ascii=False))


main()

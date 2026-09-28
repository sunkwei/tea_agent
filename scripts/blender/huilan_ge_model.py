# -*- coding: utf-8 -*-
"""
回澜阁 (Huilan Pavilion) — 程序化三维建模
================================================
史料依据:
  - 双层双檐 · 八角攒尖顶 · 黄色琉璃瓦覆顶
  - 四周 24 根红漆圆柱
  - 阁内二层圆环形厅堂, 中央 34 级螺旋式阶梯
  - 总建筑面积 354.12 m², 占地面积约 151 m²
  - 1931.09 开工, 1933.04 竣工 (德国信利洋行承建)
  - 栈桥全长 440 m, 宽 8~10 m, 南端半圆形防波堤

尺寸推算: 354.12/2 = 177 m²/层 -> 正八边形 2(1+√2)s²=177 -> s=6.05m
          -> 外接圆半径 R = s/(2·sin22.5°) = 7.9m  (与建模布局一致)

Blender 5.2.2 LTS / bpy  ·  单位: 米
"""
import bpy
import bmesh
import math
import os
import json
import sys
import addon_utils
from mathutils import Vector, Matrix, Euler

OUT = "C:/Users/Hetin/work/git/tea_agent/output/huilan_ge"
os.makedirs(OUT, exist_ok=True)

# ══════════════════════ 0. 场景初始化 ══════════════════════
bpy.ops.wm.read_factory_settings(use_empty=True)
try:
    addon_utils.enable("cycles", default_set=False, persistent=False)
except Exception:
    pass

SC = bpy.context.scene
SC.unit_settings.system = "METRIC"
SC.unit_settings.scale_length = 1.0
SC.unit_settings.length_unit = "METERS"


def coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
    if c.name not in SC.collection.children:
        SC.collection.children.link(c)
    return c


C_PAV = coll("01_回澜阁")
C_SUB = coll("02_子分部")
C_PIER = coll("03_栈桥")
C_ENV = coll("04_环境")
C_CAM = coll("05_相机")

# ══════════════════════ 1. 数学工具 ══════════════════════
PHI = math.pi / 8.0      # 22.5°  八边形半中心角
STEP = math.pi / 4.0     # 45°


def _d_corner(theta):
    """θ 到最近「面中心」的角距, ∈[0, PHI]。面中心位于 PHI + k·45°"""
    x = (theta - PHI) % STEP
    return min(x, STEP - x)


def oct_r(theta, Rc):
    """正八边形边界半径: 角点(θ=k·45°)处 = Rc, 面中心处 = Rc·cos22.5°"""
    return Rc * math.cos(PHI) / math.cos(_d_corner(theta))


def oct_prox(theta):
    """角点接近度: 面中心=0, 角点=1  (用于檐角起翘)"""
    return math.sin(_d_corner(theta) / PHI * (math.pi / 2.0))


def oct_corner_dist(theta):
    """theta 到最近角点 (k·45°) 的角距 ∈[0,22.5°]; 垂脊沿角线布置"""
    x = theta % STEP
    return min(x, STEP - x)


def LRS(loc, rot, scale):
    """Location-Rotation-Scale 矩阵 (带旧版回退)"""
    try:
        return Matrix.LocRotScale(Vector(loc), rot, Vector(scale))
    except Exception:
        return (Matrix.Translation(Vector(loc))
                @ rot.to_matrix().to_4x4()
                @ Matrix.Diagonal(Vector((scale[0], scale[1], scale[2], 1.0))))


def new_obj(name, me, c=None, mat=None):
    o = bpy.data.objects.new(name, me)
    (c or C_PAV).objects.link(o)
    if mat is not None:
        me.materials.append(mat)
    return o


def look_at(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# ══════════════════════ 2. 材质 ══════════════════════
def _prin(m):
    if m.node_tree is None:
        return None
    for n in m.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    return None


def _set(inp, val):
    try:
        cur = inp.default_value
        if hasattr(cur, "__len__"):
            for i in range(min(len(cur), len(val))):
                cur[i] = val[i]
        else:
            inp.default_value = val
        return True
    except Exception:
        return False


def _byname(node, names, val):
    for nm in names:
        if nm in node.inputs and _set(node.inputs[nm], val):
            return True
    return False


def MAT(name, base, rough=0.5, metal=0.0, spec=0.5, alpha=1.0,
        emis=None, emis_s=0.0, coat=0.0, ior=1.5):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    m.diffuse_color = (base[0], base[1], base[2], alpha)
    nt = m.node_tree
    for n in list(nt.nodes):
        if n.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL"):
            nt.nodes.remove(n)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    bs = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bs is None:
        bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    bs.location = (0, 0)
    out.location = (340, 0)
    _set(bs.inputs["Base Color"], (base[0], base[1], base[2], 1.0))
    _byname(bs, ("Roughness",), rough)
    _byname(bs, ("Metallic",), metal)
    _byname(bs, ("Specular IOR Level", "Specular"), spec)
    _byname(bs, ("IOR",), ior)
    if coat:
        _byname(bs, ("Coat Weight", "Clearcoat"), coat)
        _byname(bs, ("Coat Roughness", "Clearcoat Roughness"), 0.08)
    if alpha < 1.0:
        _byname(bs, ("Alpha",), alpha)
        for attr in ("blend_method", "surface_blend_method"):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, "BLEND")
                    break
                except Exception:
                    pass
    if emis:
        _byname(bs, ("Emission Color", "Emission"), (emis[0], emis[1], emis[2], 1.0))
        _byname(bs, ("Emission Strength",), emis_s)
    if not bs.outputs["BSDF"].links:
        nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m


# 黄色琉璃瓦 (屋面) —— 加 UV 驱动的瓦垄凹凸与色差
def MAT_TILE(name, base, rough=0.24, coat=0.55, rib_scale=64.0, rib_str=0.020):
    m = MAT(name, base, rough=rough, spec=0.75, coat=coat)
    nt = m.node_tree
    bs = _prin(m)
    if bs is None:
        return m
    # 高频瓦垄只驱动 Bump（不驱动颜色，避免远距离摩尔纹）
    uv = nt.nodes.new("ShaderNodeTexCoord")
    wav = nt.nodes.new("ShaderNodeTexWave")
    wav.wave_type = "BANDS"
    wav.bands_direction = "X"
    _set(wav.inputs["Scale"], rib_scale)
    _set(wav.inputs["Detail"], 0.0)
    _set(wav.inputs["Distortion"], 0.0)
    bump = nt.nodes.new("ShaderNodeBump")
    _set(bump.inputs["Strength"], rib_str)
    uv.location = (-900, -320)
    wav.location = (-700, -320)
    bump.location = (-480, -320)
    nt.links.new(uv.outputs["UV"], wav.inputs["Vector"])
    nt.links.new(wav.outputs["Fac"], bump.inputs["Height"])
    if "Normal" in bs.inputs:
        nt.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return m


# ---- 材质库 ----
M_TILE = MAT_TILE("琉璃瓦_黄", (0.615, 0.415, 0.085), rib_scale=150.0, rib_str=0.021)
M_TILE_L = MAT_TILE("琉璃瓦_黄_腰檐", (0.600, 0.405, 0.082), rib_scale=170.0, rib_str=0.017)
M_RIDGE = MAT("垂脊_黄琉璃", (0.665, 0.465, 0.100), rough=0.20, spec=0.8, coat=0.6)
M_EAVE = MAT("瓦当滴水", (0.545, 0.365, 0.070), rough=0.28, coat=0.5)
M_RED = MAT("朱红漆", (0.335, 0.052, 0.032), rough=0.30, spec=0.65, coat=0.40)
M_RED_D = MAT("朱红_暗", (0.195, 0.032, 0.022), rough=0.48)
M_GREEN = MAT("青绿彩画", (0.052, 0.195, 0.165), rough=0.38, coat=0.25)
M_BLUE = MAT("靛蓝彩画", (0.042, 0.095, 0.245), rough=0.38, coat=0.25)
M_GOLD = MAT("贴金", (0.855, 0.625, 0.135), rough=0.16, metal=1.0, spec=1.0)
M_STONE = MAT("花岗岩", (0.525, 0.512, 0.478), rough=0.86)
M_STONE_D = MAT("砌石_暗", (0.315, 0.298, 0.278), rough=0.95)
M_WOOD = MAT("木格扇", (0.185, 0.095, 0.050), rough=0.62)
M_GLASS = MAT("玻璃", (0.52, 0.63, 0.68), rough=0.045, alpha=0.30, spec=1.0, ior=1.52)
M_DARK = MAT("窗洞暗部", (0.030, 0.022, 0.018), rough=0.92)
M_RAIL_B = MAT("桥栏_天蓝", (0.095, 0.415, 0.615), rough=0.34, metal=0.25, coat=0.3)
M_LAMP = MAT("灯杆_白", (0.845, 0.845, 0.825), rough=0.30, coat=0.3)
M_LAMP_G = MAT("灯罩_发光", (1.0, 0.965, 0.875), rough=0.22,
               emis=(1.0, 0.945, 0.815), emis_s=2.2)
M_DECK = MAT("桥面石板", (0.555, 0.545, 0.512), rough=0.82)
M_CONC = MAT("混凝土", (0.445, 0.435, 0.415), rough=0.90)
M_SEA = MAT("海水", (0.022, 0.062, 0.070), rough=0.055, spec=1.0)
M_PLAQUE = MAT("匾额_蓝底", (0.045, 0.095, 0.225), rough=0.35, coat=0.3)

# ══════════════════════ 3. 几何构建器 ══════════════════════
def merged_boxes(name, specs, c=None, mat=None):
    """specs: [(loc3, size3, rot3), ...]  rot 按 Euler 'ZYX' (Rz·Ry·Rx)"""
    bm = bmesh.new()
    for loc, size, rot in specs:
        m = LRS(loc, Euler(tuple(rot), "ZYX"), size)
        bmesh.ops.create_cube(bm, size=1.0, matrix=m)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return new_obj(name, me, c, mat)


def merged_cones(name, specs, c=None, mat=None, seg=16):
    """specs: [(loc3, r_bottom, r_top, h, rotz), ...] 底面落在 loc.z"""
    bm = bmesh.new()
    for loc, r1, r2, h, rz in specs:
        m = (Matrix.Translation(Vector(loc))
             @ Euler((0, 0, rz), "ZYX").to_matrix().to_4x4()
             @ Matrix.Translation(Vector((0, 0, h * 0.5))))
        bmesh.ops.create_cone(bm, cap_ends=True, segments=seg,
                              radius1=r1, radius2=r2, depth=h, matrix=m)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return new_obj(name, me, c, mat)


def merged_ico(name, specs, c=None, mat=None, sub=2):
    """specs: [(loc3, radius), ...]"""
    bm = bmesh.new()
    for loc, r in specs:
        try:
            bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r,
                                       matrix=Matrix.Translation(Vector(loc)))
        except TypeError:
            bmesh.ops.create_icosphere(bm, subdivisions=sub, diameter=r * 2,
                                       matrix=Matrix.Translation(Vector(loc)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.update()
    return new_obj(name, me, c, mat)


def octa_tube(name, Rc_out, Rc_in, z0, z1, c=None, mat=None, off=0.0):
    """正八边形筒体 / 实心柱体。角点位于 off + k·45°"""
    n = 8
    verts, faces = [], []

    def ring(R, z):
        return [(R * math.cos(off + k * STEP), R * math.sin(off + k * STEP), z)
                for k in range(n)]

    verts += ring(Rc_out, z0)          # 0..7
    verts += ring(Rc_out, z1)          # 8..15
    for k in range(n):
        k2 = (k + 1) % n
        faces.append((k, k2, 8 + k2, 8 + k))
    if Rc_in:
        verts += ring(Rc_in, z0)       # 16..23
        verts += ring(Rc_in, z1)       # 24..31
        for k in range(n):
            k2 = (k + 1) % n
            faces.append((16 + k, 24 + k, 24 + k2, 16 + k2))   # 内壁
            faces.append((8 + k, 8 + k2, 24 + k2, 24 + k))     # 顶环
            faces.append((k, 16 + k, 16 + k2, k2))             # 底环
    else:
        ct = len(verts); verts.append((0, 0, z1))
        cb = len(verts); verts.append((0, 0, z0))
        for k in range(n):
            k2 = (k + 1) % n
            faces.append((8 + k, 8 + k2, ct))
            faces.append((k, cb, k2))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return new_obj(name, me, c, mat)


def octa_roof(name, r_tip, z_tip, r_top, z_top, p=2.2, lift=0.0,
              segs_per_face=8, rings=20, c=None, mat=None, uv=True,
              ridge_h=0.0, ridge_ang=0.115):
    """
    八角攒尖/披檐屋面 (垂脊烘焙进网格 → 零穿模)。
      r_tip,z_tip = 檐口(外/低)   r_top,z_top = 脊/apex(内/高)
      p  = 凹曲率指数 (>1 => 檐缓脊陡, 中国反宇 roof)
      lift = 檐角起翘高度
      ridge_h = 八条垂脊烘焙高度 (沿角线抬升, 与屋面同网格)
      ridge_ang = 脊半角宽 (rad)
    """
    nseg = 8 * segs_per_face
    ncol = nseg + 1                      # 多一列避免 UV 接缝
    span = max(1e-4, r_tip - r_top)
    verts, faces, uvs = [], [], {}
    grid = []
    for i in range(rings + 1):
        u = i / rings
        r = r_tip - u * span
        z = z_tip + (z_top - z_tip) * (u ** p)
        row = []
        for j in range(ncol):
            th = 2 * math.pi * (j % nseg) / nseg
            rr = oct_r(th, r)
            zz = z + lift * (oct_prox(th) ** 2.0) * ((1 - u) ** 2.2)
            if ridge_h:
                dang = oct_corner_dist(th)
                if dang < ridge_ang:
                    zz += ridge_h * (1.0 - dang / ridge_ang) ** 1.35
            idx = len(verts)
            verts.append((rr * math.cos(th), rr * math.sin(th), zz))
            uvs[idx] = (j / nseg, u)
            row.append(idx)
        grid.append(row)
    apex_i = None
    if r_top <= 0.06:
        apex_i = len(verts)
        verts.append((0.0, 0.0, z_top))
        uvs[apex_i] = (0.5, 1.0)
    for i in range(rings):
        A, B = grid[i], grid[i + 1]
        for j in range(nseg):
            faces.append((A[j], A[j + 1], B[j + 1], B[j]))
    if apex_i is not None:
        A = grid[rings]
        for j in range(nseg):
            faces.append((A[j], A[j + 1], apex_i))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    if uv:
        uvl = me.uv_layers.new(name="UVMap")
        for poly in me.polygons:
            for li in poly.loop_indices:
                vi = me.loops[li].vertex_index
                uvl.data[li].uv = uvs.get(vi, (0.0, 0.0))
    return new_obj(name, me, c, mat)


def octa_ridges(name, r_tip, z_tip, r_top, z_top, p=2.2, lift=0.0,
                rings=26, w=0.30, h=0.28, c=None, mat=None):
    """八条垂脊 (沿角点方向贴合屋面)"""
    span = max(1e-4, r_tip - r_top)
    specs = []

    def surf(r_nom, u, th):
        r = r_tip - u * span
        z = z_tip + (z_top - z_tip) * (u ** p)
        rr = oct_r(th, r)
        return rr * math.cos(th), rr * math.sin(th), z + lift * (oct_prox(th) ** 2.0) * ((1 - u) ** 2.2)

    for ci in range(8):
        thc = ci * STEP
        for i in range(rings):
            u0, u1 = i / rings, (i + 1) / rings
            x0, y0, z0 = surf(r_tip, u0, thc)
            x1, y1, z1 = surf(r_tip, u1, thc)
            dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
            dh = math.hypot(dx, dy)
            L = math.sqrt(dx * dx + dy * dy + dz * dz)
            if L < 1e-5:
                continue
            specs.append((((x0 + x1) / 2.0, (y0 + y1) / 2.0,
                           (z0 + z1) / 2.0 + h * 0.42),
                          (L * 1.03, w, h),
                          (0.0, -math.atan2(dz, dh), math.atan2(dy, dx))))
    return merged_boxes(name, specs, c, mat)


def eave_tiles(name, r_tip, z_tip, lift=0.0, spacing=0.30, c=None, mat=None):
    """檐口瓦当 (沿八边形檐边一圈小圆柱)"""
    per = 8 * (2 * r_tip * math.sin(PHI))
    n = max(24, int(per / spacing))
    specs = []
    for j in range(n):
        th = 2 * math.pi * j / n
        rr = oct_r(th, r_tip)
        zz = z_tip + lift * (oct_prox(th) ** 2.0)
        specs.append(((rr * math.cos(th), rr * math.sin(th), zz - 0.06),
                      0.085, 0.085, 0.20, th + math.pi / 2))
    return merged_cones(name, specs, c, mat, seg=10)


def set_smooth(o, angle_deg=40.0):
    me = o.data
    for p in me.polygons:
        p.use_smooth = True
    try:
        prev = bpy.context.view_layer.objects.active
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle_deg))
        o.select_set(False)
        bpy.context.view_layer.objects.active = prev
    except Exception:
        pass
    return o


def lathe(name, prof, seg=36, c=None, mat=None, smooth=True):
    """绕 Z 轴旋转 profile=[(r,z),...] 生成回转体"""
    n = len(prof)
    verts, faces, uvs = [], [], {}
    for i, (r, z) in enumerate(prof):
        for j in range(seg):
            th = 2 * math.pi * j / seg
            idx = len(verts)
            verts.append((r * math.cos(th), r * math.sin(th), z))
            uvs[idx] = (j / seg, i / max(1, n - 1))
    for i in range(n - 1):
        for j in range(seg):
            j2 = (j + 1) % seg
            faces.append((i * seg + j, i * seg + j2, (i + 1) * seg + j2, (i + 1) * seg + j))
    if prof[0][0] <= 1e-6:
        t = len(verts); verts.append((0, 0, prof[0][1])); uvs[t] = (0.5, 0.0)
        for j in range(seg):
            faces.append((t, j, (j + 1) % seg))
    if prof[-1][0] <= 1e-6:
        t = len(verts); verts.append((0, 0, prof[-1][1])); uvs[t] = (0.5, 1.0)
        b = (n - 1) * seg
        for j in range(seg):
            faces.append((b + j, b + (j + 1) % seg, t))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    uvl = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs.get(me.loops[li].vertex_index, (0, 0))
    o = new_obj(name, me, c, mat)
    if smooth:
        set_smooth(o)
    return o


# ══════════════════════ 4. 尺寸总表 (米, Z 向上, 海平面 Z=0) ══════════════════════
D = dict(
    z_deck=3.20,          # 桥面 / 平台顶面
    z_podium_top=3.95,    # 台基顶 = 一层地面
    Rc_podium=8.60,
    # ---- 一层 ----
    z_col_bot=3.95, z_col_top=8.05, R_col=7.60, r_col=0.245, n_col=24,
    z_arch1=7.62, z_arch1_top=8.05, R_arch1=7.60,
    Rc_wall1=5.90, Rw_wall1=5.60, z_wall1_top=8.30,
    R_balus=8.02, z_balus_top=4.62, z_rail_top=4.78,
    # ---- 下檐 (腰檐 / 副阶檐) ----
    z_brk1=8.05, z_brk1_top=8.48, R_brk1_in=7.45,
    r_tip_lo=8.95, z_tip_lo=8.50, r_top_lo=5.40, z_top_lo=9.70,
    p_lo=2.0, lift_lo=0.58,
    # ---- 二层 ----
    z_floor2=8.80, z_wall2_top=12.70, Rc_wall2=5.60, Rw_wall2=5.30,
    z_arch2=12.40, z_arch2_top=12.80, R_arch2=5.75,
    z_brk2=12.80, R_brk2_in=5.72,
    # ---- 上檐 (八角攒尖) ----
    r_tip_up=8.45, z_tip_up=13.20, z_apex=17.40, p_up=2.2, lift_up=0.92,
    # ---- 宝顶 ----
    z_finial=17.28,
)

# ══════════════════════ 5. 回澜阁本体 ══════════════════════
PAV = bpy.data.objects.new("回澜阁_ROOT", None)
C_PAV.objects.link(PAV)
# 旋转 -22.5°: 使一个「面中心」正对 +X (栈桥/陆地来向)
PAV.rotation_euler = (0.0, 0.0, -PHI)


def P(name, obj):
    obj.parent = PAV
    obj.matrix_parent_inverse = PAV.matrix_world.inverted()
    return obj


def ring_beams(R, z0, z1, dep, matl, name, off=PHI):
    """八边形环梁 (额枋/平板枋), 每面一根切向长方体"""
    sp = []
    chord = 2 * R * math.sin(PHI)
    for k in range(8):
        th = off + k * STEP
        a = R * math.cos(PHI)
        nx, ny = math.cos(th), math.sin(th)
        sp.append(((a * nx, a * ny, (z0 + z1) / 2.0),
                   (dep, chord + dep, z1 - z0), (0, 0, th)))
    return merged_boxes(name, sp, C_SUB, matl)


def bracket_specs(theta, Rc, z0, sc, n=4, out=None):
    """一攒斗拱: n 层递跳横拱 + 纵向交搭拱 + 耍头"""
    out = out if out is not None else []
    ct, st = math.cos(theta), math.sin(theta)
    for i in range(n):
        rr = Rc + 0.16 * i * sc
        w = (0.46 + 0.30 * i) * sc
        dd = (0.40 + 0.26 * i) * sc
        h = 0.145 * sc
        zz = z0 + i * 0.185 * sc
        out.append(((rr * ct, rr * st, zz), (dd, w, h), (0, 0, theta)))
        out.append(((rr * ct, rr * st, zz + 0.085 * sc),
                    (w * 0.62, 0.30 * sc, h * 0.82), (0, 0, theta + math.pi / 2)))
    rr = Rc + 0.20 * n * sc
    out.append(((rr * ct, rr * st, z0 + n * 0.185 * sc + 0.10 * sc),
                (0.30 * sc, 0.34 * sc, 0.30 * sc), (0, 0, theta)))
    return out


def build_pavilion():
    d = D
    # ---- 5.1 台基 (下枭 / 束腰 / 上枭) ----
    P("台基_下枭", octa_tube("台基_下枭", d["Rc_podium"] + 0.30, None,
                             d["z_deck"], d["z_deck"] + 0.24, C_SUB, M_STONE_D))
    P("台基_束腰", octa_tube("台基_束腰", d["Rc_podium"] + 0.10, None,
                             d["z_deck"] + 0.24, d["z_deck"] + 0.52, C_SUB, M_STONE))
    P("台基_上枭", octa_tube("台基_上枭", d["Rc_podium"] + 0.26, None,
                             d["z_deck"] + 0.52, d["z_podium_top"], C_SUB, M_STONE))
    P("一层地面", octa_tube("一层地面", d["Rc_podium"] + 0.26, None,
                            d["z_podium_top"] - 0.05, d["z_podium_top"], C_SUB, M_DECK))

    # ---- 5.2 二十四根红漆圆柱 ----
    cols, bases = [], []
    for i in range(d["n_col"]):
        th = 2 * math.pi * i / d["n_col"]
        x, y = d["R_col"] * math.cos(th), d["R_col"] * math.sin(th)
        cols.append(((x, y, d["z_col_bot"]), d["r_col"], d["r_col"] * 0.965,
                     d["z_col_top"] - d["z_col_bot"], 0.0))
        bases.append(((x, y, d["z_podium_top"]), 0.375, 0.335, 0.20, 0.0))
    set_smooth(P("红柱_x24", merged_cones("红柱_x24", cols, C_SUB, M_RED, seg=20)))
    set_smooth(P("柱础_x24", merged_cones("柱础_x24", bases, C_SUB, M_STONE, seg=14)))

    # ---- 5.3 柱间坐凳栏杆 ----
    P("栏板", octa_tube("栏板", d["R_balus"], d["R_balus"] - 0.17,
                        d["z_podium_top"], d["z_balus_top"], C_SUB, M_STONE))
    P("栏板扶手", octa_tube("栏板扶手", d["R_balus"] + 0.09, d["R_balus"] - 0.24,
                            d["z_balus_top"], d["z_rail_top"], C_SUB, M_RED))
    pz, hs = [], []
    for k in range(8):
        th = k * STEP
        rr = oct_r(th, d["R_balus"] + 0.02)
        x, y = rr * math.cos(th), rr * math.sin(th)
        pz.append(((x, y, d["z_podium_top"]), 0.155, 0.140,
                   d["z_rail_top"] + 0.16 - d["z_podium_top"], th))
        hs.append(((x, y, d["z_rail_top"] + 0.23), 0.135))
    set_smooth(P("望柱_x8", merged_cones("望柱_x8", pz, C_SUB, M_STONE, seg=8)))
    set_smooth(P("望柱头_x8", merged_ico("望柱头_x8", hs, C_SUB, M_STONE, sub=2)))

    # ---- 5.4 一层墙身 + 额枋 ----
    P("一层墙身", octa_tube("一层墙身", d["Rc_wall1"], d["Rw_wall1"],
                            d["z_podium_top"], d["z_wall1_top"], C_SUB, M_RED))
    P("一层额枋", ring_beams(d["R_arch1"], d["z_arch1"], d["z_arch1_top"], 0.34, M_BLUE, "一层额枋"))
    P("一层平板枋", ring_beams(d["R_arch1"], d["z_arch1_top"], d["z_arch1_top"] + 0.14, 0.42, M_GREEN, "一层平板枋"))
    P("一层箍头金线", ring_beams(d["R_arch1"] + 0.02, d["z_arch1"] + 0.30, d["z_arch1"] + 0.40, 0.36, M_GOLD, "一层箍头金线"))

    # ---- 5.5 下檐斗拱 (24 攒对齐柱位) ----
    bsp = []
    for i in range(d["n_col"]):
        bracket_specs(2 * math.pi * i / d["n_col"], d["R_brk1_in"], d["z_brk1"], 0.62, 4, bsp)
    P("下檐斗拱_24攒", merged_boxes("下檐斗拱_24攒", bsp, C_SUB, M_GREEN))

    # ---- 5.6 下檐屋面 (反宇凹曲 + 檐角起翘) ----
    o = P("下檐屋面", octa_roof("下檐屋面", d["r_tip_lo"], d["z_tip_lo"],
                                 d["r_top_lo"], d["z_top_lo"], p=d["p_lo"], lift=d["lift_lo"],
                                 segs_per_face=12, rings=24, c=C_SUB, mat=M_TILE_L,
                                 ridge_h=0.32, ridge_ang=0.115))
    s = o.modifiers.new("Solidify", "SOLIDIFY"); s.thickness = 0.155; s.offset = -1.0
    set_smooth(P("下檐瓦当", eave_tiles("下檐瓦当", d["r_tip_lo"], d["z_tip_lo"],
                                        lift=d["lift_lo"], spacing=0.285, c=C_SUB, mat=M_EAVE)))

    # ---- 5.7 二层墙身 + 额枋 ----
    P("二层墙身", octa_tube("二层墙身", d["Rc_wall2"], d["Rw_wall2"],
                            d["z_floor2"], d["z_wall2_top"], C_SUB, M_RED))
    P("二层额枋", ring_beams(d["R_arch2"], d["z_arch2"], d["z_arch2_top"], 0.32, M_BLUE, "二层额枋"))
    P("二层平板枋", ring_beams(d["R_arch2"], d["z_arch2_top"], d["z_arch2_top"] + 0.13, 0.40, M_GREEN, "二层平板枋"))
    P("二层箍头金线", ring_beams(d["R_arch2"] + 0.02, d["z_arch2"] + 0.28, d["z_arch2"] + 0.38, 0.34, M_GOLD, "二层箍头金线"))

    # ---- 5.8 上檐斗拱 (16 攒: 8 角科 + 8 平身科) ----
    bsp2 = []
    for k in range(16):
        th = k * (STEP / 2.0)
        bracket_specs(th, d["R_brk2_in"], d["z_brk2"], 0.80 if k % 2 == 0 else 0.70, 5, bsp2)
    P("上檐斗拱_16攒", merged_boxes("上檐斗拱_16攒", bsp2, C_SUB, M_GREEN))

    # ---- 5.9 上檐八角攒尖顶 ----
    o = P("上檐屋面", octa_roof("上檐屋面", d["r_tip_up"], d["z_tip_up"],
                                 0.12, d["z_apex"], p=d["p_up"], lift=d["lift_up"],
                                 segs_per_face=14, rings=30, c=C_SUB, mat=M_TILE,
                                 ridge_h=0.38, ridge_ang=0.115))
    s = o.modifiers.new("Solidify", "SOLIDIFY"); s.thickness = 0.185; s.offset = -1.0
    set_smooth(P("上檐瓦当", eave_tiles("上檐瓦当", d["r_tip_up"], d["z_tip_up"],
                                        lift=d["lift_up"], spacing=0.275, c=C_SUB, mat=M_EAVE)))
    kj = []
    for k in range(8):
        th = k * STEP
        rr = oct_r(th, d["r_tip_up"]) + 0.18
        kj.append(((rr * math.cos(th), rr * math.sin(th), d["z_tip_up"] + d["lift_up"] + 0.32), 0.21))
    set_smooth(P("翘角脊饰_x8", merged_ico("翘角脊饰_x8", kj, C_SUB, M_RIDGE, sub=2)))

    # ---- 5.10 宝顶 + 刹杆 ----
    zf = d["z_finial"]
    prof = [(0.00, 0.00), (0.70, 0.015), (0.80, 0.10), (0.74, 0.24), (0.46, 0.34),
            (0.38, 0.48), (0.44, 0.58), (0.60, 0.74), (0.66, 0.96), (0.60, 1.20),
            (0.44, 1.40), (0.26, 1.54), (0.13, 1.63), (0.00, 1.68)]
    P("宝顶", lathe("宝顶", [(r, z + zf) for r, z in prof], seg=40, c=C_SUB, mat=M_GOLD))
    set_smooth(P("刹杆", merged_cones("刹杆", [((0, 0, zf + 1.66), 0.045, 0.028, 2.25, 0)],
                                      C_SUB, M_GOLD, seg=10)))
    set_smooth(P("刹杆顶珠", merged_ico("刹杆顶珠", [((0, 0, zf + 3.95), 0.115)], C_SUB, M_GOLD, sub=2)))


# ══════════════════════ 6. 门窗 · 匾额 ══════════════════════
def _place(out, theta, Rw, dd, u, z, sx, sy, sz, mat_bucket):
    """在八边形某面 (面心方向 θ) 上, 面内偏移 u、径向出挑 dd 处放一个长方体"""
    a = Rw * math.cos(PHI)
    nx, ny = math.cos(theta), math.sin(theta)
    tx, ty = -math.sin(theta), math.cos(theta)
    mat_bucket.append(((a * nx + u * tx + dd * nx, a * ny + u * ty + dd * ny, z),
                       (sx, sy, sz), (0.0, 0.0, theta)))


def win_panel(theta, Rw, u0, w, z0, z1, dk, gl, wd, gd):
    """一樘木格扇窗: 窗洞暗部 + 玻璃 + 抹头/槛框 + 4竖5横棂格 + 金色边线"""
    h = z1 - z0
    zc = (z0 + z1) / 2.0
    _place(dk, theta, Rw, 0.015, u0, zc, 0.035, w, h, dk)
    _place(gl, theta, Rw, 0.055, u0, zc, 0.020, w - 0.10, h - 0.10, gl)
    _place(wd, theta, Rw, 0.105, u0, z0 + 0.060, 0.125, w + 0.13, 0.120, wd)   # 下槛
    _place(wd, theta, Rw, 0.105, u0, z1 - 0.055, 0.125, w + 0.13, 0.110, wd)   # 上楣
    _place(wd, theta, Rw, 0.105, u0 - w / 2 - 0.032, zc, 0.125, 0.105, h, wd)  # 左抹头
    _place(wd, theta, Rw, 0.105, u0 + w / 2 + 0.032, zc, 0.125, 0.105, h, wd)  # 右抹头
    nv, nh = 4, 5
    for i in range(nv):
        _place(wd, theta, Rw, 0.092, u0 - w / 2 + (i + 1) * w / (nv + 1), zc,
               0.075, 0.048, h - 0.15, wd)
    for i in range(nh):
        _place(wd, theta, Rw, 0.092, u0, z0 + 0.10 + (i + 1) * (h - 0.20) / (nh + 1),
               0.075, w - 0.13, 0.042, wd)
    _place(gd, theta, Rw, 0.175, u0, z1 - 0.055, 0.030, w + 0.14, 0.035, gd)   # 金线


def build_openings():
    dk, gl, wd, gd = [], [], [], []
    th_front = PHI                       # 局部坐标正面; ROOT 旋转 -22.5° 后正对 +X

    for k in range(8):
        th = PHI + k * STEP
        front = (k == 0)
        # ---- 一层 ----
        Rw1 = D["Rc_wall1"]
        if front:
            dw, dh = 1.85, 3.10
            z0 = D["z_podium_top"]
            _place(dk, th, Rw1, 0.015, 0.0, z0 + dh / 2, 0.035, dw, dh, dk)
            for sgn in (-1, 1):          # 双扇门扇
                _place(wd, th, Rw1, 0.080, sgn * dw / 4.0, z0 + dh / 2,
                       0.100, dw / 2 - 0.045, dh - 0.06, wd)
            _place(wd, th, Rw1, 0.115, 0.0, z0 + dh - 0.10, 0.100, dw + 0.20, 0.20, wd)
            _place(gd, th, Rw1, 0.148, 0.0, z0 + dh + 0.06, 0.032, dw + 0.24, 0.075, gd)
            # 门簪 (金色圆形)
            _place(gd, th, Rw1, 0.175, -0.42, z0 + dh - 0.10, 0.045, 0.15, 0.15, gd)
            _place(gd, th, Rw1, 0.175, +0.42, z0 + dh - 0.10, 0.045, 0.15, 0.15, gd)
            win_panel(th, Rw1, -1.55, 0.90, 4.95, 7.40, dk, gl, wd, gd)
            win_panel(th, Rw1, +1.55, 0.90, 4.95, 7.40, dk, gl, wd, gd)
        else:
            for u0 in (-1.40, 0.0, 1.40):
                win_panel(th, Rw1, u0, 1.05, 4.95, 7.40, dk, gl, wd, gd)

        # ---- 二层 ("一窗一景, 一景一画"; 正面中为匾额) ----
        Rw2 = D["Rc_wall2"]
        offs = (-1.32, 1.32) if front else (-1.32, 0.0, 1.32)
        for u0 in offs:
            win_panel(th, Rw2, u0, 1.00, 9.55, 11.80, dk, gl, wd, gd)

    P("窗洞暗部", merged_boxes("窗洞暗部", dk, C_SUB, M_DARK))
    P("玻璃_格扇", merged_boxes("玻璃_格扇", gl, C_SUB, M_GLASS))
    P("木格扇_棂框", merged_boxes("木格扇_棂框", wd, C_SUB, M_WOOD))
    P("门窗金线", merged_boxes("门窗金线", gd, C_SUB, M_GOLD))

    # ---- 匾额「回澜阁」蓝底金字竖匾 ----
    a = D["Rc_wall2"] * math.cos(PHI) + 0.21
    nx, ny = math.cos(th_front), math.sin(th_front)
    tx, ty = -math.sin(th_front), math.cos(th_front)
    rot = (0.0, 0.0, th_front)
    zb = 10.68
    P("匾额_框", merged_boxes("匾额_框",
        [((a * nx, a * ny, zb), (0.17, 1.36, 3.30), rot)], C_SUB, M_GOLD))
    P("匾额_底", merged_boxes("匾额_底",
        [((a * nx + 0.06 * nx, a * ny + 0.06 * ny, zb), (0.07, 1.12, 3.06), rot)], C_SUB, M_PLAQUE))
    P("匾额_内金线", merged_boxes("匾额_内金线",
        [((a * nx + 0.105 * nx, a * ny + 0.105 * ny, zb), (0.026, 1.00, 2.94), rot)], C_SUB, M_GOLD))
    zs = [((a * nx + 0.125 * nx + u * tx, a * ny + 0.125 * ny + u * ty, zz),
           (0.032, 0.66, 0.66), rot)
          for u, zz in ((0.0, 11.55), (0.0, 10.68), (0.0, 9.81))]
    P("匾额_字位", merged_boxes("匾额_字位", zs, C_SUB, M_GOLD))


# ══════════════════════ 7. 阁内 34 级螺旋楼梯 + 楼板 ══════════════════════
def build_stairs():
    n = 34
    r_core, r_out = 0.92, 3.15
    z0 = D["z_podium_top"]
    z1 = D["z_floor2"]
    turns = 1.60
    steps = []
    ww = r_out - r_core
    rr = (r_core + r_out) / 2.0
    chord = 2 * math.pi * rr * turns / n * 1.30
    for i in range(n):
        th = turns * 2 * math.pi * (i / n)
        z = z0 + (z1 - z0) * (i / n)
        steps.append(((rr * math.cos(th), rr * math.sin(th), z + 0.055),
                      (ww, chord, 0.11), (0, 0, th + math.pi / 2)))
    P("螺旋楼梯_34级", merged_boxes("螺旋楼梯_34级", steps, C_SUB, M_WOOD))
    set_smooth(P("楼梯中心柱", merged_cones(
        "楼梯中心柱", [((0, 0, z0), 0.34, 0.30, z1 - z0, 0)], C_SUB, M_RED_D, seg=20)))
    P("二层楼板", octa_tube("二层楼板", D["Rw_wall2"], None,
                            D["z_floor2"] - 0.14, D["z_floor2"], C_SUB, M_WOOD))
    P("二层天花", octa_tube("二层天花", D["Rw_wall2"] - 0.05, None,
                            D["z_wall2_top"] - 0.22, D["z_wall2_top"], C_SUB, M_RED_D))


build_pavilion()
build_openings()
build_stairs()


# ══════════════════════ 8. 半圆形防波堤 + 栈桥 ══════════════════════
BRK_R = 13.50          # 堤头平台半径 (超出阁檐 8.95 约 0.51R, 与实景照片比例一致)
PIER_W = 10.00         # 栈桥宽度
PIER_L = 440.00        # 栈桥全长 (史料: 440 m)
Z_DECK = D["z_deck"]
Z_BOT = 1.10           # 砌石堤壁落入水下


def breakwater_profile():
    """D 形平面: 海侧 (-X) 半圆, 陆侧 (+X) 收窄并入桥身"""
    pts = []
    for i in range(37):
        th = math.pi / 2 + math.pi * i / 36.0        # 90° → 270°
        pts.append((BRK_R * math.cos(th), BRK_R * math.sin(th)))
    pts.append((24.0, -PIER_W / 2))
    pts.append((24.0, +PIER_W / 2))
    return pts


def extrude_poly(name, pts, z0, z1, c=None, mat=None):
    """把 2D 多边形沿 Z 拉伸成实体"""
    n = len(pts)
    verts = [(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts]
    faces = [tuple(range(n - 1, -1, -1))]                    # 底面
    faces.append(tuple(range(n, 2 * n)))                     # 顶面
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate(verbose=False)
    me.update()
    return new_obj(name, me, c, mat)


def build_pier():
    prof = breakwater_profile()

    # ---- 8.1 堤壁 (砌石, 落水) + 平台顶面 ----
    P("防波堤_砌石壁", extrude_poly("防波堤_砌石壁", prof, Z_BOT, Z_DECK - 0.10,
                                    C_PIER, M_STONE_D))
    P("防波堤_平台面", extrude_poly("防波堤_平台面", prof, Z_DECK - 0.10, Z_DECK,
                                    C_PIER, M_DECK))
    # 压顶石线脚
    cap = [(x * 1.012, y * 1.012 if abs(y) < BRK_R else y) for x, y in prof]
    P("防波堤_压顶", extrude_poly("防波堤_压顶", cap, Z_DECK - 0.34, Z_DECK - 0.10,
                                  C_PIER, M_STONE))

    # ---- 8.2 桥面板 + 边梁 ----
    x0, x1 = 20.0, PIER_L
    P("桥面板", merged_boxes("桥面板", [(((x0 + x1) / 2, 0, Z_DECK - 0.22),
                                        (x1 - x0, PIER_W, 0.44), (0, 0, 0))], C_PIER, M_DECK))
    for sgn in (-1, 1):
        P(f"桥边梁_{sgn>0 and '南' or '北'}", merged_boxes(
            f"桥边梁_{sgn>0 and '南' or '北'}",
            [(((x0 + x1) / 2, sgn * PIER_W / 2, Z_DECK - 0.62),
              (x1 - x0, 0.42, 0.36), (0, 0, 0))], C_PIER, M_CONC))

    # ---- 8.3 排架桥墩 (1984 年整修后南段 16 榀排架的通用形制) ----
    piers, beams = [], []
    xs = [26.0 + i * 6.80 for i in range(int((x1 - 30.0) / 6.80))]
    for x in xs:
        for yy in (-2.70, 0.0, 2.70):
            piers.append(((x, yy, Z_BOT - 1.60), 0.34, 0.30, Z_DECK - 0.44 - (Z_BOT - 1.60), 0.0))
        beams.append(((x, 0, Z_DECK - 0.62), (0.52, PIER_W - 0.6, 0.34), (0, 0, 0)))
    set_smooth(P("桥墩排架_柱", merged_cones("桥墩排架_柱", piers, C_PIER, M_CONC, seg=10)))
    P("桥墩排架_盖梁", merged_boxes("桥墩排架_盖梁", beams, C_PIER, M_CONC))

    # ---- 8.4 平台外缘栏杆 (现代天蓝金属管栏杆) ----
    # ---- 8.4 平台外缘栏杆 (海侧半圆 · 极坐标 · 竖直立柱) ----
    posts, rails = [], []
    Rr = BRK_R - 0.42
    n_arc = 40
    a0, a1 = math.radians(93.0), math.radians(267.0)   # 海侧半圆, 两端留口接桥
    for i in range(n_arc + 1):
        th = a0 + (a1 - a0) * i / n_arc
        px, py = Rr * math.cos(th), Rr * math.sin(th)
        posts.append(((px, py, Z_DECK), 0.050, 0.050, 1.06, 0.0))
        if i < n_arc:
            th2 = a0 + (a1 - a0) * (i + 1) / n_arc
            tm = (th + th2) / 2.0
            mx, my = Rr * math.cos(tm), Rr * math.sin(tm)
            seglen = 2.0 * Rr * math.sin((th2 - th) / 2.0) + 0.03
            rz = tm + math.pi / 2.0                      # 横杆沿弧切向
            rails.append(((mx, my, Z_DECK + 1.03), (0.090, seglen, 0.090), (0, 0, rz)))
            rails.append(((mx, my, Z_DECK + 0.53), (0.072, seglen, 0.072), (0, 0, rz)))
    set_smooth(P("平台栏杆_立柱", merged_cones("平台栏杆_立柱", posts, C_PIER, M_RAIL_B, seg=8)))
    set_smooth(P("平台栏杆_横杆", merged_boxes("平台栏杆_横杆", rails, C_PIER, M_RAIL_B)))

    # ---- 8.5 桥面两侧栏杆 ----
    bposts, brails = [], []
    for x in [24.0 + i * 1.90 for i in range(int((x1 - 24.0) / 1.90))]:
        for sgn in (-1, 1):
            yy = sgn * (PIER_W / 2 - 0.30)
            bposts.append(((x, yy, Z_DECK), 0.048, 0.048, 1.08, 0.0))
            brails.append(((x, yy, Z_DECK + 1.05), (0.090, 1.94, 0.088), (0, 0, 0)))
            brails.append(((x, yy, Z_DECK + 0.54), (0.072, 1.94, 0.072), (0, 0, 0)))
    set_smooth(P("桥栏_立柱", merged_cones("桥栏_立柱", bposts, C_PIER, M_RAIL_B, seg=8)))
    set_smooth(P("桥栏_横杆", merged_boxes("桥栏_横杆", brails, C_PIER, M_RAIL_B)))

    # ---- 8.6 莲花路灯 ----
    poles, globes, rings, arms = [], [], [], []
    for i, x in enumerate([28.0 + j * 14.4 for j in range(int((x1 - 28.0) / 14.4))]):
        sgn = -1 if i % 2 == 0 else 1
        yy = sgn * (PIER_W / 2 - 0.75)
        zb = Z_DECK
        poles.append(((x, yy, zb), 0.085, 0.062, 3.05, 0.0))
        rings.append(((x, yy, zb + 0.42), 0.155, 0.155, 0.075, 0.0))
        rings.append(((x, yy, zb + 2.72), 0.135, 0.135, 0.070, 0.0))
        zt = zb + 3.05
        # 十字横架 (托 4 只球灯)
        arms.append(((x, yy, zt + 0.14), (0.075, 1.16, 0.075), (0, 0, 0)))
        arms.append(((x, yy, zt + 0.14), (1.16, 0.075, 0.075), (0, 0, 0)))
        # 5 球莲花灯 (中 1 高 + 四角 4 低)
        globes.append(((x, yy, zt + 0.62), 0.235))
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            globes.append(((x + 0.52 * math.cos(a), yy + 0.52 * math.sin(a), zt + 0.28), 0.185))
    set_smooth(P("灯杆", merged_cones("灯杆", poles, C_PIER, M_LAMP, seg=10)))
    set_smooth(P("灯杆横架", merged_boxes("灯杆横架", arms, C_PIER, M_LAMP)))
    set_smooth(P("灯杆金环", merged_cones("灯杆金环", rings, C_PIER, M_GOLD, seg=10)))
    set_smooth(P("莲花灯罩", merged_ico("莲花灯罩", globes, C_PIER, M_LAMP_G, sub=2)))


# ══════════════════════ 9. 海面 · 天空 · 光照 ══════════════════════
def build_env():
    N, SZ = 120, 2200.0
    verts, faces = [], []
    for i in range(N + 1):
        for j in range(N + 1):
            x = -SZ * 0.55 + SZ * i / N
            y = -SZ / 2 + SZ * j / N
            r = math.hypot(x, y)
            swell = 0.0
            if r > 22.0:
                k = min(1.0, (r - 22.0) / 60.0)
                swell = k * (0.16 * math.sin(x * 0.055 + 1.1) * math.cos(y * 0.048)
                             + 0.10 * math.sin(x * 0.13 - y * 0.09))
            verts.append((x, y, swell))
    for i in range(N):
        for j in range(N):
            a = i * (N + 1) + j
            faces.append((a, a + 1, a + N + 2, a + N + 1))
    me = bpy.data.meshes.new("海面")
    me.from_pydata(verts, [], faces)
    me.update()
    sea = new_obj("海面", me, C_ENV, M_SEA)
    set_smooth(sea, 25.0)

    # 波浪细节 (材质内程序化凹凸, 不增几何)
    nt = M_SEA.node_tree
    bs = _prin(M_SEA)
    if bs is not None:
        co = nt.nodes.new("ShaderNodeTexCoord")
        wa = nt.nodes.new("ShaderNodeTexWave")
        wa.wave_type = "BANDS"
        _set(wa.inputs["Scale"], 1.10)
        _set(wa.inputs["Detail"], 6.0)
        _set(wa.inputs["Distortion"], 4.5)
        mp = nt.nodes.new("ShaderNodeMapping")
        try:
            mp.inputs["Scale"].default_value = (3.0, 3.0, 3.0)
        except Exception:
            pass
        bu = nt.nodes.new("ShaderNodeBump")
        _set(bu.inputs["Strength"], 0.30)
        for n in (co, mp, wa, bu):
            n.location = (-800, -300)
        nt.links.new(co.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], wa.inputs["Vector"])
        nt.links.new(wa.outputs["Fac"], bu.inputs["Height"])
        nt.links.new(bu.outputs["Normal"], bs.inputs["Normal"])

    # ---- 天空 (渐变穹顶) ----
    w = bpy.data.worlds.new("青岛湾_天空")
    SC.world = w
    w.use_nodes = True
    nt = w.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    tex = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    el = ramp.color_ramp.elements
    el[0].position = -0.30
    el[1].position = 0.42
    e_mid = ramp.color_ramp.elements.new(0.02)
    _set(el[0].color, (0.415, 0.455, 0.470, 1))       # 地平线薄霾
    _set(e_mid.color, (0.560, 0.680, 0.790, 1))       # 中空
    _set(el[1].color, (0.235, 0.430, 0.700, 1))       # 天顶
    for n in (tex, sep, ramp, bg, out):
        pass
    tex.location, sep.location = (-800, 0), (-600, 0)
    ramp.location, bg.location, out.location = (-400, 0), (-150, 0), (150, 0)
    bg.inputs["Strength"].default_value = 1.00
    nt.links.new(tex.outputs["Generated"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    # ---- 太阳 (斜射暖光, 青岛湾午后) ----
    sun_d = bpy.data.lights.new("太阳", "SUN")
    sun_d.energy = 4.20
    sun_d.angle = math.radians(24.0)
    sun_d.color = (1.00, 0.945, 0.855)
    sun_d.use_shadow = True
    sun = bpy.data.objects.new("太阳", sun_d)
    sun.location = (180.0, -260.0, 150.0)
    sun.rotation_euler = (math.radians(52.0), math.radians(8.0), math.radians(35.0))
    C_ENV.objects.link(sun)
    # 海面反射补光
    fill_d = bpy.data.lights.new("海面反光", "AREA")
    fill_d.energy = 26000.0
    fill_d.size = 180.0
    fill_d.color = (0.72, 0.82, 0.90)
    fill = bpy.data.objects.new("海面反光", fill_d)
    fill.location = (-40.0, -60.0, 6.0)
    look_at(fill, (0, 0, 8))
    C_ENV.objects.link(fill)


# ══════════════════════ 10. 相机 ══════════════════════
def make_cam(name, loc, target, lens=42.0):
    cd = bpy.data.cameras.get(name) or bpy.data.cameras.new(name)
    cd.lens = lens
    cd.sensor_width = 36.0
    cd.clip_end = 4000.0
    cd.dof.use_dof = False
    o = bpy.data.objects.new("CAM_" + name, cd)
    o.location = Vector(loc)
    look_at(o, target)
    C_CAM.objects.link(o)
    return o


CAMS = {
    "hero":    dict(loc=(52.0, -40.0, 13.5), tgt=(0.0, 0.0, 9.2), lens=40.0),
    "side":    dict(loc=(10.0, -104.0, 12.5), tgt=(0.0, 0.0, 9.0), lens=62.0),
    "aerial":  dict(loc=(58.0, -52.0, 62.0), tgt=(0.0, 0.0, 7.0), lens=32.0),
    "finial":  dict(loc=(15.5, -13.5, 19.6), tgt=(0.0, 0.0, 17.0), lens=58.0),
    "colonn":  dict(loc=(19.0, -16.0, 6.4), tgt=(0.0, 0.0, 6.6), lens=30.0),
}


def build_cams():
    objs = {}
    for k, v in CAMS.items():
        objs[k] = make_cam(k, v["loc"], v["tgt"], v["lens"])
    SC.camera = objs["hero"]
    return objs


build_pier()
build_env()
CAMOBJS = build_cams()


# ══════════════════════ 11. 渲染设置 (Cycles + RTX OPTIX) ══════════════════════
def setup_render():
    r = SC.render
    try:
        r.engine = "CYCLES"
        cyc = SC.cycles
        cyc.samples = 190
        cyc.preview_samples = 32
        cyc.use_denoising = True
        try:
            cyc.denoiser = "OPTIX"
        except Exception:
            pass
        cyc.use_adaptive_sampling = True
        cyc.max_bounces = 12
        cyc.diffuse_bounces = 6
        cyc.glossy_bounces = 8
        cyc.transparent_max_bounces = 12
        cyc.use_fast_gi = True
        r.use_motion_blur = False
        try:
            r.film_transparent = False
        except Exception:
            pass
        gpu = "GPU"
        try:
            cp = bpy.context.preferences.addons["cycles"].preferences
            cp.compute_device_type = "OPTIX"
            cp.refresh_devices()
            for dv in cp.devices:
                dv.use = (dv.type in ("OPTIX", "CUDA"))
        except Exception:
            gpu = "CPU"
        cyc.device = gpu
        return "CYCLES/" + gpu
    except Exception as e:
        r.engine = "BLENDER_EEVEE"
        return "EEVEE (fallback: %s)" % e


def setup_color():
    try:
        vd = SC.view_settings
        vd.view_transform = "Filmic"
        vd.look = "None"
        vd.exposure = 0.35
        vd.gamma = 1.00
    except Exception:
        pass
    try:
        SC.eevee.taa_render_samples = 128
    except Exception:
        pass


def render_view(key, cam, samples, W, H, fname):
    SC.camera = cam
    SC.render.resolution_x = W
    SC.render.resolution_y = H
    SC.render.resolution_percentage = 100
    try:
        SC.cycles.samples = samples
    except Exception:
        pass
    SC.render.filepath = os.path.join(OUT, fname)
    SC.render.image_settings.file_format = "PNG"
    SC.render.image_settings.color_mode = "RGBA"
    SC.render.image_settings.compression = 15
    SC.render.image_settings.color_depth = "8"
    bpy.ops.render.render(write_still=True)
    return os.path.join(OUT, fname)


# ══════════════════════ 12. 统计 ══════════════════════
def stats():
    nv = nf = no = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data is not None:
            no += 1
            nv += len(o.data.vertices)
            nf += len(o.data.polygons)
    # 应用修改器后的三角面估算
    dep = bpy.context.evaluated_depsgraph_get()
    tv = tf = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        try:
            ev = o.evaluated_get(dep)
            me = ev.to_mesh()
            if me is not None:
                tv += len(me.vertices)
                tf += len(me.polygons)
                ev.to_mesh_clear()
        except Exception:
            tv += len(o.data.vertices)
            tf += len(o.data.polygons)
    return dict(objects=no, raw_verts=nv, raw_faces=nf, eval_verts=tv, eval_faces=tf,
                materials=len(bpy.data.materials), collections=len(bpy.data.collections))


def bbox_world(col=None):
    """统计阁体本体包围盒 (默认只算 02_子分部 集合, 不含栈桥/海面)"""
    col = col or C_SUB
    SC_ = bpy.context.view_layer.update()
    zs, xs, ys = [], [], []
    for ch in col.all_objects:
        if ch.type != "MESH":
            continue
        for c in ch.bound_box:
            wc = ch.matrix_world @ Vector(c)
            xs.append(wc.x); ys.append(wc.y); zs.append(wc.z)
    if not zs:
        return None
    return dict(w=round(max(xs) - min(xs), 2), d=round(max(ys) - min(ys), 2),
                h=round(max(zs) - min(zs), 2), z_min=round(min(zs), 2), z_max=round(max(zs), 2))


# ══════════════════════ 13. 执行 ══════════════════════
bpy.context.view_layer.update()
eng = setup_render()
setup_color()

report = {}
report["blender"] = bpy.app.version_string
report["engine"] = eng
bb = bbox_world()
report["pavilion_bbox"] = bb
if bb:
    report["pavilion_height_above_deck"] = round(bb["z_max"] - Z_DECK, 2)

st = stats()
report["stats"] = st

# ---- 导出 ----
SKIP_RENDER = os.environ.get("HLG_SKIP_RENDER") == "1"
blend_path = os.path.join(OUT, "huilan_ge.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend_path)
report["blend"] = blend_path

gltf_path = os.path.join(OUT, "huilan_ge.glb")
try:
    bpy.ops.export_scene.gltf(filepath=gltf_path, export_format="GLB",
                              export_apply=True, export_yup=True, use_selection=False)
    report["glb"] = gltf_path
    report["glb_size"] = os.path.getsize(gltf_path)
except Exception as e:
    report["glb_error"] = str(e)

obj_path = os.path.join(OUT, "huilan_ge.obj")
try:
    bpy.ops.wm.obj_export(filepath=obj_path, export_materials=True, global_scale=1.0)
    report["obj"] = obj_path
except Exception as e:
    report["obj_error"] = str(e)

# ---- 渲染 5 个视角 ----
import time
shots = [("hero", 192, 1760, 1100, "01_hero_正面透视.png"),
         ("side", 128, 1920, 900, "02_side_正侧视.png"),
         ("aerial", 128, 1500, 1200, "03_aerial_鸟瞰.png"),
         ("finial", 140, 1200, 1500, "04_finial_宝顶特写.png"),
         ("colonn", 110, 1760, 1000, "05_colonnade_柱廊人视.png")]
t0 = time.time()
report["renders"] = {}
for key, sp, W, H, fn in (shots if not SKIP_RENDER else []):
    ts = time.time()
    p = render_view(key, CAMOBJS[key], sp, W, H, fn)
    report["renders"][key] = dict(path=p, size=os.path.getsize(p),
                                  secs=round(time.time() - ts, 1))
report["render_total_secs"] = round(time.time() - t0, 1)
report["materials"] = [m.name for m in bpy.data.materials]

print("HLG_REPORT " + json.dumps(report, ensure_ascii=False))

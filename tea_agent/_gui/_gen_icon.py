"""生成 Tea Agent 图标：大齿轮啮合小齿轮。
运行: python tea_agent/_gui/_gen_icon.py
输出: tea_agent/_gui/icon.png (256x256) 和 icon.ico
"""

import math
from PIL import Image, ImageDraw

# ── 配置 ──────────────────────────────────────────
SIZE = 256                    # 输出尺寸
BIG_CENTER = (110, 160)       # 大齿轮中心
BIG_OUTER = 98                # 大齿轮齿顶半径
BIG_INNER = 78                # 大齿轮齿根半径
BIG_TEETH = 16                # 大齿轮齿数
BIG_COLOR = (59, 130, 246)    # 蓝色

SMALL_CENTER = (194, 68)      # 小齿轮中心
SMALL_OUTER = 52              # 小齿轮齿顶半径
SMALL_INNER = 40              # 小齿轮齿根半径
SMALL_TEETH = 8               # 小齿轮齿数
SMALL_COLOR = (245, 158, 11)  # 琥珀色

BG_COLOR = (18, 18, 24)       # 深色背景
HOLE_COLOR = BG_COLOR         # 齿轮中心孔 = 背景色（镂空效果）


def _gear_polygon(cx, cy, inner_r, outer_r, n_teeth, phase_offset=0.0):
    """生成齿轮的连续多边形顶点列表（带齿）。
    返回 [(x0,y0), ...] 适合 draw.polygon() 绘制。
    """
    points = []
    # 每齿两段：上升沿（inner→outer）+ 下降沿外侧（outer→inner）
    segments_per_tooth = 4  # inner_start, outer_start, outer_mid, outer_end=inner_end
    # 更精细：每齿用 6 个点 —— inner→outer 斜面，outer 顶弧两点，outer→inner 斜面
    for i in range(n_teeth):
        a0 = 2 * math.pi * i / n_teeth + phase_offset
        pitch = 2 * math.pi / n_teeth
        half_gap = pitch * 0.22   # 齿槽宽度（角度）
        half_tip = pitch * 0.28   # 齿顶宽度（角度）

        # 齿根左 → 齿顶左
        a1 = a0 - half_gap
        points.append((cx + inner_r * math.cos(a1), cy + inner_r * math.sin(a1)))
        a2 = a0 - half_tip
        points.append((cx + outer_r * math.cos(a2), cy + outer_r * math.sin(a2)))
        # 齿顶右 → 齿根右
        a3 = a0 + half_tip
        points.append((cx + outer_r * math.cos(a3), cy + outer_r * math.sin(a3)))
        a4 = a0 + half_gap
        points.append((cx + inner_r * math.cos(a4), cy + inner_r * math.sin(a4)))

    return points


def _draw_gear(draw, cx, cy, inner_r, outer_r, n_teeth, color, phase_offset=0.0):
    """绘制一个完整的齿轮（填充 + 中心孔）。"""
    pts = _gear_polygon(cx, cy, inner_r, outer_r, n_teeth, phase_offset)
    draw.polygon(pts, fill=color)

    # 中心孔（用背景色覆盖，模拟镂空）
    hole_r = inner_r * 0.28
    draw.ellipse(
        [cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r],
        fill=HOLE_COLOR,
    )

    # 中心小圆点（装饰）
    dot_r = inner_r * 0.10
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill=color,
    )


def generate_icon():
    """生成 256x256 图标。"""
    img = Image.new("RGBA", (SIZE, SIZE), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img)

    # 小齿轮齿数少，旋转半个齿距让齿与大齿轮齿槽啮合
    small_phase = math.pi / SMALL_TEETH

    _draw_gear(draw, *BIG_CENTER, BIG_INNER, BIG_OUTER, BIG_TEETH, BIG_COLOR)
    _draw_gear(draw, *SMALL_CENTER, SMALL_INNER, SMALL_OUTER, SMALL_TEETH, SMALL_COLOR, small_phase)

    # 输出
    png_path = "tea_agent/_gui/icon.png"
    ico_path = "tea_agent/_gui/icon.ico"
    img.save(png_path, "PNG")
    img.save(ico_path, "ICO", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"✅ {png_path}")
    print(f"✅ {ico_path}")


if __name__ == "__main__":
    generate_icon()

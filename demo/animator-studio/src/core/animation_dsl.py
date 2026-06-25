"""
动画脚本 DSL v2 — 增强版：图片/路径/挤压拉伸/复合运动

DSL 是一个 JSON 对象，描述一个完整的动画。

顶层:
    { "title": "...", "scenes": [Scene, ...] }

Scene:
    {
        "duration": 5,              // 秒
        "bg": ["#c1", "#c2"],       // 背景渐变
        "narration": "旁白文字",     // 可选，用于 TTS
        "elements": [ Element, ... ]
    }

Element — 通用属性:
    "type": "shape" | "text" | "emoji" | "image" | "group"
    "x": 0.5,           // 相对坐标 0-1
    "y": 0.5,
    "opacity": 1.0,     // 0-1
    "rotation": 0,      // 角度
    "scaleX": 1.0,      // 水平缩放
    "scaleY": 1.0,      // 垂直缩放 (用于 squash/stretch)

Shape 元素:
    "shape": "circle"|"rect"|"triangle"|"star"|"polygon"|"heart"|"cloud"|"drop"
    "r" / "w" / "h"     // 尺寸
    "fill": "#ff6b6b", "stroke": "#333", "strokeWidth": 2
    "sides": 6          // polygon 边数

Text 元素:
    "text": "Hello", "fontSize": 36, "font": "Arial", "fill": "#fff"

Emoji 元素:
    "emoji": "🐼", "fontSize": 60

Image 元素（本地素材）:
    "type": "image"
    "src": "C:/path/to/image.png"     // 本地图片路径
    "w": 100, "h": 100                // 绘制尺寸
    或
    "src_base64": "data:image/png;base64,..."  // base64 内联

Group 元素（复合对象）:
    "type": "group"
    "children": [ Element, ... ]      // 子元素列表
    // 子元素坐标相对于组中心

Animation — 增强版:
    {
        "prop": "x",                  // 属性名
        "from": 0.2, "to": 0.8,       // 起始/结束值
        "duration": 2,                // 秒
        "delay": 0,                   // 延迟
        "easing": "easeOut"|"easeIn"|"easeInOut"|"linear"|"bounce"|"elastic"|"backOut"|"backInOut"
        "loop": true,                 // 往返循环
        "yoyo": true                  // 同 loop，去+回算一次

    // 路径动画（prop="path" 时）:
    {
        "prop": "path",
        "points": [                    // 贝塞尔曲线控制点
            {"x":0.1,"y":0.5},         // 起点
            {"x":0.3,"y":0.2},         // 控制点1
            {"x":0.7,"y":0.8},         // 控制点2
            {"x":0.9,"y":0.5}          // 终点
        ],
        "duration": 3,
        "easing": "easeInOut"
    }

    // 挤压拉伸（bounce 时自动）:
    {
        "prop": "squash",
        "intensity": 0.3,             // 挤压幅度 0-1
        "duration": 0.3               // 每次碰撞时长
    }

    // 浮动/漂移（通用运动）:
    {
        "type": "float",              // 自动生成正弦浮动
        "amplitude": 10,              // 浮动幅度 px
        "speed": 1.5,                 // 速度
        "axis": "y"                   // x/y/both
    }
"""

import json
import os
import base64
from typing import Optional, List


class DSLValidationError(Exception):
    """DSL 校验错误"""


# ── 校验 ──

VALID_SHAPES = {"circle", "rect", "triangle", "star", "polygon", "heart", "cloud", "drop"}
VALID_TYPES = {"shape", "text", "emoji", "image", "group"}
VALID_EASINGS = {"linear", "easeOut", "easeIn", "easeInOut", "bounce", "elastic", "backOut", "backInOut"}
VALID_PROPS = {"x", "y", "r", "w", "h", "opacity", "rotation", "scaleX", "scaleY"}


def validate_dsl(dsl: dict) -> list:
    """校验 DSL，返回错误列表"""
    errors = []
    if not isinstance(dsl, dict):
        return ["顶层必须是 JSON 对象"]
    scenes = dsl.get("scenes", [])
    if not scenes:
        errors.append("缺少 scenes 字段或为空")
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"场景 [{i}] 必须是对象"); continue
        dur = scene.get("duration", 0)
        if not isinstance(dur, (int, float)) or dur <= 0:
            errors.append(f"场景 [{i}] duration 必须 > 0")
        _validate_elements(scene.get("elements", []), i, errors, f"场景 [{i}]")
    return errors


def _validate_elements(els, scene_idx, errors, prefix):
    for j, el in enumerate(els or []):
        if not isinstance(el, dict):
            errors.append(f"{prefix} 元素 [{j}] 必须是对象"); continue
        etype = el.get("type")
        if etype not in VALID_TYPES:
            errors.append(f"{prefix} 元素 [{j}] type 无效: {etype}")
        if etype == "shape":
            shape = el.get("shape")
            if shape not in VALID_SHAPES:
                errors.append(f"{prefix} 元素 [{j}] shape 无效: {shape}")
        if etype == "image" and not el.get("src") and not el.get("src_base64"):
            errors.append(f"{prefix} 元素 [{j}] image 需提供 src 或 src_base64")
        if etype == "group":
            _validate_elements(el.get("children", []), scene_idx, errors, f"{prefix} 元素 [{j}]")
        _validate_animations(el.get("animations", []), j, errors, prefix)


def _validate_animations(anims, el_idx, errors, prefix):
    for k, a in enumerate(anims or []):
        if not isinstance(a, dict):
            errors.append(f"{prefix} 元素 [{el_idx}] 动画 [{k}] 必须是对象"); continue
        prop = a.get("prop")
        if prop == "path":
            pts = a.get("points", [])
            if len(pts) < 2:
                errors.append(f"{prefix} 元素 [{el_idx}] 动画 [{k}] path 至少需要 2 个点")
        elif prop != "squash":
            if prop not in VALID_PROPS:
                errors.append(f"{prefix} 元素 [{el_idx}] 动画 [{k}] prop 无效: {prop}")
        easing = a.get("easing")
        if easing and easing not in VALID_EASINGS:
            errors.append(f"{prefix} 元素 [{el_idx}] 动画 [{k}] easing 无效: {easing}")


# ── 本地图片 → base64 转换 ──

def image_to_base64(image_path: str) -> Optional[str]:
    """将本地图片转为 data URL"""
    if not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        ext = os.path.splitext(image_path)[1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}.get(ext, "image/png")
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def embed_local_images(dsl: dict) -> dict:
    """将 DSL 中所有 image 元素的 src 转为 src_base64"""
    for scene in dsl.get("scenes", []):
        for el in scene.get("elements", []):
            _embed_image(el)
    return dsl


def _embed_image(el):
    if el.get("type") == "image" and el.get("src") and not el.get("src_base64"):
        b64 = image_to_base64(el["src"])
        if b64:
            el["src_base64"] = b64
    if el.get("type") == "group":
        for child in el.get("children", []):
            _embed_image(child)


# ── 格式化 ──

def format_dsl_preview(dsl: dict, max_scenes: int = 3) -> str:
    scenes = dsl.get("scenes", [])
    lines = [
        f"🎬 {dsl.get('title', '未命名动画')}",
        f"  共 {len(scenes)} 个场景, {sum(s.get('duration',0) for s in scenes)}秒",
    ]
    for i, s in enumerate(scenes[:max_scenes]):
        els = s.get("elements", [])
        el_desc = []
        for e in els[:6]:
            t = e.get("type", "")
            if t == "emoji": el_desc.append(e.get("emoji", ""))
            elif t == "image": el_desc.append("🖼️")
            elif t == "group": el_desc.append(f"📦({len(e.get('children',[]))})")
            elif t == "shape": el_desc.append(e.get("shape", "?"))
            elif t == 'text': el_desc.append('"' + str(e.get('text','')) + '"')
            else: el_desc.append(t)
        lines.append(f"  [{i+1}] {s.get('duration',0)}s {s.get('narration','')[:30]} | {' '.join(el_desc)}")
    if len(scenes) > max_scenes:
        lines.append(f"  ... 还有 {len(scenes)-max_scenes} 个场景")
    return "\n".join(lines)


# ── DSL → 场景配置 ──

def dsl_to_scene_config(dsl: dict) -> dict:
    scenes = dsl.get("scenes", [])
    result = []
    for s in scenes:
        scene = {
            "duration": s.get("duration", 5),
            "bg": s.get("bg", ["#0a0a1a", "#1a0a2a"]),
            "narration": s.get("narration", ""),
            "elements": s.get("elements", []),
        }
        if s.get("title"):
            scene["title"] = s["title"]
        result.append(scene)
    return {
        "type": "dsl_scenes",
        "scenes": result,
        "title": dsl.get("title", "LLM 动画"),
    }


# ── DSL 示例（few-shot）──

EXAMPLE_DSL_BOUNCE = {
    "title": "弹跳的小球",
    "scenes": [{
        "duration": 4, "bg": ["#0a0a1a", "#1a1a2a"],
        "narration": "一个红色小球在屏幕上弹跳，落地时被压扁",
        "elements": [{
            "type": "shape", "shape": "circle",
            "x": 0.3, "y": 0.2, "r": 40,
            "fill": "#ff4757", "stroke": "#ff6b81", "strokeWidth": 3,
            "animations": [
                {"prop": "y", "from": 0.15, "to": 0.75, "duration": 0.8, "easing": "easeIn", "loop": True},
                {"prop": "scaleY", "from": 1, "to": 0.6, "duration": 0.15, "easing": "easeIn", "delay": 0.7, "loop": True},
                {"prop": "scaleX", "from": 1, "to": 1.4, "duration": 0.15, "easing": "easeIn", "delay": 0.7, "loop": True},
            ]
        }, {
            "type": "shape", "shape": "rect",
            "x": 0.3, "y": 0.78, "w": 100, "h": 6,
            "fill": "rgba(255,255,255,0.2)"
        }]
    }]
}

EXAMPLE_DSL_PATH = {
    "title": "蝴蝶飞舞",
    "scenes": [{
        "duration": 5, "bg": ["#0a1a2a", "#1a2a4a"],
        "narration": "一只蝴蝶在花丛中沿着弧形路径飞舞",
        "elements": [{
            "type": "emoji", "emoji": "🦋",
            "x": 0.1, "y": 0.5, "fontSize": 50,
            "animations": [
                {"prop": "path", "points": [
                    {"x":0.1,"y":0.5},{"x":0.3,"y":0.2},{"x":0.6,"y":0.7},
                    {"x":0.8,"y":0.3},{"x":0.9,"y":0.5}
                ], "duration": 4, "easing": "easeInOut"},
                {"prop": "rotation", "from": -5, "to": 5, "duration": 0.5, "loop": True}
            ]
        }, {
            "type": "emoji", "emoji": "🌸", "x": 0.2, "y": 0.75, "fontSize": 30
        }, {
            "type": "emoji", "emoji": "🌺", "x": 0.7, "y": 0.7, "fontSize": 30
        }]
    }]
}

EXAMPLE_DSL_GROUP = {
    "title": "跳舞的机器人",
    "scenes": [{
        "duration": 6, "bg": ["#1a0a2a", "#0a0a1a"],
        "narration": "一个机器人随着节奏跳舞，手臂上下摆动",
        "elements": [{
            "type": "group",
            "x": 0.5, "y": 0.45,
            "children": [
                {"type": "shape", "shape": "rect", "w": 60, "h": 80, "fill": "#6bcbff", "x": 0, "y": 0, "r": 8},
                {"type": "shape", "shape": "circle", "r": 28, "fill": "#fff", "x": 0, "y": -55},
                {"type": "shape", "shape": "rect", "w": 12, "h": 50, "fill": "#6bcbff", "x": -40, "y": -10, "r": 4,
                 "animations": [{"prop": "rotation", "from": -30, "to": 30, "duration": 0.6, "loop": True}]},
                {"type": "shape", "shape": "rect", "w": 12, "h": 50, "fill": "#6bcbff", "x": 40, "y": -10, "r": 4,
                 "animations": [{"prop": "rotation", "from": 30, "to": -30, "duration": 0.6, "loop": True}]},
                {"type": "shape", "shape": "rect", "w": 20, "h": 60, "fill": "#4a4a5a", "x": -12, "y": 80, "r": 4},
                {"type": "shape", "shape": "rect", "w": 20, "h": 60, "fill": "#4a4a5a", "x": 12, "y": 80, "r": 4},
            ],
            "animations": [
                {"prop": "y", "from": 0.45, "to": 0.4, "duration": 0.4, "easing": "easeOut", "loop": True},
            ]
        }]
    }]
}

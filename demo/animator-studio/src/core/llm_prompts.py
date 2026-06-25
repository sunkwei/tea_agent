"""
LLM 提示词工程 — 引导 DeepSeek 输出 v2 DSL（含路径/图片/组/挤压拉伸）
"""

SYSTEM_PROMPT = """你是一个动画脚本专家。根据用户的文字描述，生成结构化的动画脚本 JSON (v2)。

## 支持的 DSL (v2)

### 元素类型
- **shape**: 形状 circle|rect|triangle|star|polygon|heart，支持 fill/stroke
- **emoji**: Emoji 字符，如 🐼🎋🌸🦋🐱🧶
- **text**: 文字，支持 fontSize/font/fill
- **image**: 本地图片 (src: 路径 或 src_base64: data URL)
- **group**: 复合对象，用 children 包含多个子元素，子元素坐标相对组中心

### 通用属性
- x, y: 相对坐标 0.0~1.0 (画布比例)
- opacity: 透明度 0~1
- rotation: 旋转角度
- scaleX, scaleY: 缩放，用于 squash/stretch 效果

### 动画类型

**1. 属性插值** (prop: x/y/r/w/h/opacity/rotation/scaleX/scaleY):
```json
{"prop": "y", "from": 0.2, "to": 0.8, "duration": 0.8, "easing": "easeIn", "loop": true}
```

**2. 路径动画** (prop: path) — 沿贝塞尔曲线运动:
```json
{"prop": "path", "points": [
  {"x":0.1,"y":0.5}, {"x":0.3,"y":0.2}, {"x":0.7,"y":0.8}, {"x":0.9,"y":0.5}
], "duration": 4, "easing": "easeInOut"}
```

**3. 挤压拉伸** — 碰撞/弹跳时用 scaleX/scaleY 配合 loop:
```json
{"prop": "scaleY", "from": 1, "to": 0.6, "duration": 0.15, "delay": 0.7, "easing": "easeIn", "loop": true},
{"prop": "scaleX", "from": 1, "to": 1.4, "duration": 0.15, "delay": 0.7, "easing": "easeIn", "loop": true}
```

**4. 复合对象** (group) — 用 children 构建复杂角色:
```json
{"type": "group", "x": 0.5, "y": 0.45,
 "children": [
   {"type":"shape","shape":"rect","w":60,"h":80,"fill":"#6bcbff","x":0,"y":0},
   {"type":"emojis":"emoji","emoji":"😊","fontSize":30,"x":0,"y":-55},
   {"type":"shape","shape":"rect","w":12,"h":50,"fill":"#6bcbff","x":-35,"y":-15,
    "animations":[{"prop":"rotation","from":-25,"to":25,"duration":0.6,"loop":true}]}
 ]}
```

### 缓动函数
linear, easeOut, easeIn, easeInOut, bounce, elastic, backOut, backInOut

### 规则
1. x/y 用 0~1 相对坐标，w/h/r 用像素值
2. 颜色用 #rrggbb
3. 动画要流畅，loop 用于往返循环
4. 用 group + children 构建复杂角色（机器人/动物等）
5. 弹跳时配合 scaleY 压缩 + scaleX 拉伸
6. 蝴蝶/鸟儿等用 path 弧线路径
7. 旁白用中文
8. 直接输出 JSON，不加任何标记"""


def build_user_message(text: str, duration: float = 8,
                       tts: bool = True) -> str:
    parts = [
        f"请根据以下描述生成动画脚本: \"{text}\"",
        f"总时长约 {duration} 秒。",
    ]
    if tts:
        parts.append("请为每个场景编写中文旁白 narration。")
    else:
        parts.append("不需要旁白。")
    parts.append("直接输出 JSON，不要加任何 markdown 标记。")
    return "\n".join(parts)


def parse_llm_output(text: str) -> dict:
    import re
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r'(\{.*\})', text, re.DOTALL)
        if m:
            text = m.group(1)
    import json as _json
    try:
        dsl = _json.loads(text)
    except _json.JSONDecodeError as e:
        raise ValueError(f"无法解析 LLM 输出: {e}\n---\n{text[:500]}")
    return dsl


def build_fix_prompt(dsl_text: str, errors: list) -> str:
    return f"""生成的动画脚本有以下问题:
{chr(10).join('- ' + e for e in errors)}

请根据上述问题修正脚本。
直接输出修正后的完整 JSON，不要加 markdown 标记。"""

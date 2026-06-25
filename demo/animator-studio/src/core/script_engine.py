"""
脚本引擎 — 将 DSL 转换为可播放的动画 HTML

流程:
    DSL (JSON) → 注入 animation.html template → 可播放 HTML
"""
import os
import json
import time
import copy
from pathlib import Path
from typing import Optional

from src.core.animation_dsl import (validate_dsl, format_dsl_preview,                                     dsl_to_scene_config, embed_local_images)


# 模板路径
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / ".." / "animator" / "templates"
_TEMPLATE_FILE = _TEMPLATE_DIR / "animation.html"

# 备选：使用 animator-studio 自己的模板
_OWN_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dsl_animation.html"


def _get_template() -> str:
    """获取动画 HTML 模板"""
    # 优先用增强后的 DSL 模板
    if _OWN_TEMPLATE.exists():
        with open(_OWN_TEMPLATE, "r", encoding="utf-8") as f:
            return f.read()
    # 回退到 animator 的模板
    if _TEMPLATE_FILE.exists():
        with open(_TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    raise FileNotFoundError(f"动画模板未找到 (尝试: {_OWN_TEMPLATE} / {_TEMPLATE_FILE})")


class ScriptEngine:
    """DSL → HTML 转换引擎"""

    def __init__(self):
        self._template = None

    @property
    def template(self) -> str:
        if self._template is None:
            self._template = _get_template()
        return self._template

    def render(self, dsl: dict, text: str = "",
               tts: bool = True, output_path: Optional[str] = None) -> str:
        """
        将 DSL 渲染为 HTML 动画文件

        参数:
            dsl: 动画脚本 (DSL JSON)
            text: 原始描述文字
            tts: 是否启用语音
            output_path: 输出路径

        返回:
            HTML 文件路径
        """
        # 校验
        errors = validate_dsl(dsl)
        if errors:
            raise ValueError(f"DSL 校验失败:\n" + "\n".join(f"  - {e}" for e in errors))

        # 转换为场景配置
        scene_cfg = dsl_to_scene_config(dsl)
        scene_cfg["tts"] = tts

        total_dur = sum(s.get("duration", 5) for s in scene_cfg["scenes"])

        # 加载模板并注入
        html = self.template
        scene_cfg = embed_local_images(scene_cfg)
        config_json = json.dumps(scene_cfg, ensure_ascii=False)
        desc = text or dsl.get("title", "LLM 动画")

        html = html.replace("{{CONFIG_JSON}}", config_json)
        html = html.replace("{{DESCRIPTION}}", desc[:60])
        html = html.replace("{{DURATION}}", str(total_dur))

        # 输出
        if not output_path:
            fname = f"llm_{int(time.time())}.html"
            output_path = str(Path.cwd() / "output" / fname)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        # 摘要
        print(f"✅ LLM 动画 HTML: {output_path}")
        print(f"   ├─ 描述: {desc[:40]}")
        print(f"   ├─ 场景: {len(scene_cfg['scenes'])} 个, 共 {total_dur}s")
        print(f"   ├─ TTS: {'开启' if tts else '关闭'}")
        print(f"   └─ DSL 摘要:\n{format_dsl_preview(dsl)}")

        return os.path.abspath(output_path)


# 全局单例
engine = ScriptEngine()

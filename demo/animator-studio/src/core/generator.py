"""
动画生成 — 包装 animator 引擎，提供更丰富的扩展能力
"""
import os
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from src.config import config, ANIMATIONS_DIR, VIDEOS_DIR


# 延迟导入 animator
_ANIMATOR_AVAILABLE = None


def _check_animator():
    global _ANIMATOR_AVAILABLE
    if _ANIMATOR_AVAILABLE is not None:
        return _ANIMATOR_AVAILABLE
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
        from animator import AnimationGenerator  # noqa
        _ANIMATOR_AVAILABLE = True
        return True
    except ImportError:
        _ANIMATOR_AVAILABLE = False
        return False


class Generator:
    """
    动画生成器 — 包装 animator.AnimationGenerator

    扩展功能:
      - 自动 ID/路径管理
      - 生成记录持久化
      - 批量生成
      - 模板缓存
    """

    def __init__(self):
        self._gen = None
        self._records = {}  # id -> metadata

    def _ensure_gen(self):
        if not _check_animator():
            raise RuntimeError(
                "animator 模块不可用。请确保先安装依赖。\n"
                "  pip install -e demo/animator"
            )
        if self._gen is None:
            from animator import AnimationGenerator
            self._gen = AnimationGenerator()
        return self._gen

    def generate(self, text: str, duration: Optional[float] = None,
                 tts: bool = True, story: Optional[bool] = None,
                 meta: Optional[dict] = None) -> dict:
        """
        根据文字生成动画 HTML

        返回:
            {
                "id": "uuid",
                "text": "...",
                "duration": 5.0,
                "html_path": "...",
                "type": "story|particles|...",
                "scenes": [...],  # story 模式
                "created_at": "...",
                "url": "/player/<id>"
            }
        """
        gen = self._ensure_gen()
        duration = duration or config.default_duration
        config.ensure_dirs()

        # 判断是否为故事模式
        if story is None:
            story = self._detect_story(text)

        if story:
            html_path = gen.generate_story(
                text=text,
                tts=tts,
                output_path=str(ANIMATIONS_DIR / f"story_{int(time.time())}.html"),
            )
            # 计算实际时长
            actual_dur = sum(s.get("dur", 6) for s in gen.PHONE_STORY_SCENES)
        else:
            html_path = gen.generate(
                text=text,
                duration=duration,
                output_path=str(ANIMATIONS_DIR / f"anim_{int(time.time())}.html"),
            )
            actual_dur = duration

        # 生成记录
        record_id = str(uuid.uuid4())[:8]
        record = {
            "id": record_id,
            "text": text,
            "duration": actual_dur,
            "html_path": html_path,
            "type": "story" if story else "auto",
            "tts": tts,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "url": f"/player/{record_id}",
        }
        if story:
            record["scenes"] = gen.PHONE_STORY_SCENES

        self._records[record_id] = record
        return record

    def _detect_story(self, text: str) -> bool:
        story_kw = ["手机", "进化", "发展", "历程", "历史",
                     "大哥大", "翻盖", "折叠", "触屏"]
        return any(k in text for k in story_kw)

    def list_animations(self) -> list:
        return list(self._records.values())

    def get(self, anim_id: str) -> Optional[dict]:
        return self._records.get(anim_id)

    def get_by_path(self, html_path: str) -> Optional[dict]:
        for r in self._records.values():
            if r["html_path"] == html_path:
                return r
        return None


# 全局单例
generator = Generator()

# ── LLM 生成快捷入口 ──
_LLM_CLIENT = None

def _get_llm():
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        from src.core.llm_client import llm as _llm
        _LLM_CLIENT = _llm
    return _LLM_CLIENT


def llm_generate(text: str, duration: float = 8,
                 tts: bool = True, max_retries: int = 2) -> dict:
    """
    使用 LLM 生成动画（一站式接口）

    流程: 文字描述 → LLM → DSL → ScriptEngine → HTML

    返回:
        {
            "id": "...",
            "text": "...",
            "duration": ...,
            "html_path": "...",
            "type": "llm",
            "dsl": {...},       # LLM 生成的 DSL
            "created_at": "...",
            "url": "/player/<id>"
        }
    """
    from src.core.llm_prompts import (
        SYSTEM_PROMPT, build_user_message, parse_llm_output, build_fix_prompt
    )
    from src.core.animation_dsl import validate_dsl
    from src.core.script_engine import engine

    client = _get_llm()

    # 调用 LLM
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(text, duration, tts)},
    ]
    print(f"🤖 调用 LLM (deepseek-v4-flash)...")
    response = client.chat(
        messages=messages,
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    # 解析
    dsl = parse_llm_output(response)
    errors = validate_dsl(dsl)

    # 重试
    retry = 0
    while errors and retry < max_retries:
        retry += 1
        print(f"⚠️  DSL 校验失败 ({len(errors)} 个问题), 重试 {retry}/{max_retries}...")
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": build_fix_prompt(response, errors)})
        response = client.chat(messages=messages)
        dsl = parse_llm_output(response)
        errors = validate_dsl(dsl)

    if errors:
        raise ValueError(
            "LLM 无法生成合法动画脚本:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    # 渲染 HTML
    config.ensure_dirs()
    html_path = engine.render(
        dsl=dsl,
        text=text,
        tts=tts,
        output_path=str(ANIMATIONS_DIR / f"llm_{int(time.time())}.html"),
    )

    # 生成记录
    record_id = str(uuid.uuid4())[:8]
    total_dur = sum(s.get("duration", 5) for s in dsl.get("scenes", []))
    record = {
        "id": record_id,
        "text": text,
        "duration": total_dur,
        "html_path": html_path,
        "type": "llm",
        "dsl": dsl,
        "tts": tts,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": f"/player/{record_id}",
    }
    generator._records[record_id] = record
    return record

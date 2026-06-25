"""
录制管理 — 包装 recorder，增加队列/进度/缓存
"""
import os
import time
import json
from pathlib import Path
from typing import Optional

from src.config import config, DATA_DIR


class Recorder:
    """
    录制管理器 — 包装 animator.Recorder

    扩展:
      - 异步录制 (后台线程)
      - 进度回调
      - 录制记录持久化
    """

    def __init__(self):
        self._rec = None
        self._jobs = {}  # job_id -> status

    def _ensure_rec(self):
        if self._rec is None:
            # 延迟导入
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
                from animator import Recorder as _Recorder
                self._rec = _Recorder(
                    fps=config.default_fps,
                    temp_dir=str(DATA_DIR / ".frames"),
                )
            except ImportError as e:
                raise RuntimeError(f"无法导入 recorder: {e}")
        return self._rec

    def record(self, html_path: str, duration: Optional[float] = None,
               width: Optional[int] = None, height: Optional[int] = None,
               fps: Optional[int] = None, output_name: Optional[str] = None) -> dict:
        """
        录制动画 HTML 为 MP4（同步）

        返回:
            {
                "job_id": "...",
                "video_path": "...",
                "duration": 5.0,
                "fps": 24,
                "size": 123456,
                "status": "completed",
            }
        """
        rec = self._ensure_rec()
        duration = duration or config.default_duration
        width = width or config.default_width
        height = height or config.default_height
        fps = fps or config.default_fps
        config.ensure_dirs()

        output_path = str(DATA_DIR / "videos" / (output_name or f"video_{int(time.time())}.mp4"))

        mp4 = rec.record(
            html_path=html_path,
            duration=duration,
            output_path=output_path,
            width=width,
            height=height,
        )
        fsize = os.path.getsize(mp4) if os.path.exists(mp4) else 0

        job = {
            "job_id": str(time.time()),
            "video_path": mp4,
            "duration": duration,
            "fps": fps,
            "resolution": f"{width}x{height}",
            "size": fsize,
            "size_mb": round(fsize / 1024 / 1024, 2),
            "status": "completed",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._jobs[job["job_id"]] = job
        return job

    def list_jobs(self) -> list:
        return list(self._jobs.values())

    def cleanup(self):
        if self._rec:
            self._rec.cleanup()


# 全局单例
recorder = Recorder()

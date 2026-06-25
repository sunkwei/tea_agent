"""
配置管理 — 加载环境变量/命令行/默认值
"""
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ANIMATIONS_DIR = DATA_DIR / "animations"
VIDEOS_DIR = DATA_DIR / "videos"

# 默认配置
DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8080,
    "debug": True,
    "output_dir": str(ANIMATIONS_DIR),
    "video_dir": str(VIDEOS_DIR),
    "default_duration": 5,
    "default_fps": 24,
    "default_width": 1280,
    "default_height": 720,
    "ffmpeg_cmd": "ffmpeg",
    "record_enabled": False,  # 默认不录制
    "tts_enabled": True,      # 默认含语音
}


class Config:
    """配置对象，支持 env 覆盖"""

    def __init__(self):
        self._data = dict(DEFAULTS)
        # 从环境变量覆盖
        for key in self._data:
            env_key = f"ANIMATOR_{key.upper()}"
            if env_key in os.environ:
                val = os.environ[env_key]
                # 类型转换
                if isinstance(self._data[key], bool):
                    val = val.lower() in ("1", "true", "yes")
                elif isinstance(self._data[key], int):
                    val = int(val)
                self._data[key] = val

    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"Config has no '{name}'")

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def as_dict(self):
        return dict(self._data)

    def ensure_dirs(self):
        """确保输出目录存在"""
        ANIMATIONS_DIR.mkdir(parents=True, exist_ok=True)
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


# 全局单例
config = Config()

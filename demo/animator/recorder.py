"""
录制模块 — 将 HTML 动画录制为 MP4 视频

核心流程:
    1. 使用 Playwright 打开 HTML 动画
    2. 定时截图帧
    3. 用 ffmpeg 合成 MP4

依赖:
    - playwright (pip install playwright && playwright install chromium)
    - ffmpeg (需在 PATH 中)
"""

import os
import re
import sys
import json
import subprocess
import tempfile
import time
import shutil
from pathlib import Path


class Recorder:
    """HTML 动画 → MP4 录制器"""

    # ffmpeg 路径
    FFMPEG_CMD = "ffmpeg"

    def __init__(self, fps: int = 30, quality: int = 23,
                 temp_dir: str = None, ffmpeg_cmd: str = None):
        """
        参数:
            fps: 帧率 (默认 30)
            quality: CRF 质量 0-51, 越小质量越高 (默认 23)
            temp_dir: 临时帧目录 (默认系统临时目录)
            ffmpeg_cmd: ffmpeg 命令路径 (默认自动查找)
        """
        self.fps = fps
        self.quality = quality
        self.temp_dir = temp_dir or tempfile.mkdtemp(prefix="anim_rec_")
        self.ffmpeg_cmd = ffmpeg_cmd or self._find_ffmpeg()

    def _find_ffmpeg(self) -> str:
        """查找 ffmpeg 可执行文件"""
        # 尝试常见路径
        candidates = ["ffmpeg", "ffmpeg.exe"]
        for cmd in candidates:
            try:
                subprocess.run([cmd, "-version"], capture_output=True, check=True)
                return cmd
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        # Windows 常见安装路径
        win_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]
        for p in win_paths:
            if os.path.exists(p):
                return p
        raise RuntimeError(
            "ffmpeg 未找到。请安装 ffmpeg 并确保其在 PATH 中。\n"
            "  Windows: 下载 https://ffmpeg.org/download.html 并加入 PATH\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )

    def _get_html_url(self, html_path: str) -> str:
        """将文件路径转为 file:// URL（含 autoplay 参数）"""
        abs_path = os.path.abspath(html_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"HTML 文件不存在: {abs_path}")
        return f"file:///{abs_path.replace(os.sep, '/')}?autoplay=1"

    def record(self, html_path: str, duration: float,
               output_path: str = None,
               width: int = 1280, height: int = 720) -> str:
        """
        录制 HTML 动画为 MP4 视频

        参数:
            html_path: 动画 HTML 文件路径
            duration: 录制时长（秒）
            output_path: 输出 MP4 路径，默认自动生成
            width: 录制宽度
            height: 录制高度

        返回:
            MP4 文件路径
        """
        html_url = self._get_html_url(html_path)

        # 默认输出路径
        if not output_path:
            base = os.path.splitext(os.path.basename(html_path))[0]
            output_path = f"{base}_{duration}s.mp4"

        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        print(f"🎬 开始录制动画...")
        print(f"   ├─ HTML: {html_path}")
        print(f"   ├─ 时长: {duration}s")
        print(f"   ├─ 分辨率: {width}x{height}")
        print(f"   ├─ 帧率: {self.fps}fps")
        print(f"   └─ 输出: {output_path}")

        # 使用 Playwright 截图帧
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "需要安装 playwright: pip install playwright && "
                "playwright install chromium"
            )

        # 创建帧目录
        frames_dir = os.path.join(self.temp_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)

        total_frames = int(duration * self.fps)

        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    f"--window-size={width},{height}",
                ]
            )

            # 创建页面并设置视口
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page = context.new_page()

            # 加载页面
            print(f"   ⏳ 加载页面...")
            try:
                page.goto(html_url, wait_until="networkidle", timeout=15000)
            except Exception as e:
                print(f"   ⚠️ 页面加载超时，继续: {e}")

            # 等待动画初始帧
            time.sleep(0.5)

            # 逐帧截图
            print(f"   📸 逐帧截图 (共 {total_frames} 帧)...")
            frame_interval = 1.0 / self.fps
            start_time = time.time()

            for frame_idx in range(total_frames):
                # 计算在这一帧应该截图的时间点
                target_time = frame_idx * frame_interval

                # 计算需要等待的时间
                elapsed = time.time() - start_time
                wait_time = target_time - elapsed
                if wait_time > 0:
                    time.sleep(wait_time)

                # 截图
                frame_file = os.path.join(frames_dir, f"frame_{frame_idx:06d}.png")
                try:
                    page.screenshot(path=frame_file, full_page=False)
                except Exception as e:
                    print(f"   ⚠️ 截图失败 (帧 {frame_idx}): {e}")
                    continue

                # 进度显示
                if frame_idx % max(1, total_frames // 10) == 0:
                    pct = (frame_idx + 1) / total_frames * 100
                    print(f"      [{pct:3.0f}%] 帧 {frame_idx + 1}/{total_frames}")

            # 关闭浏览器
            context.close()
            browser.close()

        # 用 ffmpeg 合成 MP4
        print(f"   🎞️ 合成 MP4...")
        mp4_path = self._frames_to_mp4(frames_dir, output_path, width, height)

        # 清理临时帧
        try:
            shutil.rmtree(frames_dir)
        except PermissionError:
            pass

        file_size = os.path.getsize(mp4_path)
        print(f"✅ 录制完成!")
        print(f"   ├─ 文件: {mp4_path}")
        print(f"   ├─ 大小: {file_size / 1024 / 1024:.1f} MB")
        print(f"   └─ 时长: {duration}s @ {self.fps}fps")

        return mp4_path

    def _frames_to_mp4(self, frames_dir: str, output_path: str,
                       width: int, height: int) -> str:
        """将帧序列合成为 MP4"""
        cmd = [
            self.ffmpeg_cmd,
            "-y",  # 覆盖输出
            "-framerate", str(self.fps),
            "-i", os.path.join(frames_dir, "frame_%06d.png"),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(self.quality),
            "-pix_fmt", "yuv420p",
            "-s", f"{width}x{height}",
            "-movflags", "+faststart",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                print(f"   ⚠️ ffmpeg 警告/错误:")
                for line in result.stderr.split("\n")[-10:]:
                    if line.strip():
                        print(f"      {line.strip()}")
        except subprocess.TimeoutExpired:
            print("   ⚠️ ffmpeg 超时，但可能已生成部分文件")
        except FileNotFoundError:
            raise RuntimeError(
                f"ffmpeg 命令未找到: {self.ffmpeg_cmd}\n"
                "请安装 ffmpeg: https://ffmpeg.org/download.html"
            )

        if not os.path.exists(output_path):
            # 尝试替代方案：使用临时输出
            fallback = output_path.replace(".mp4", "_temp.mp4")
            if os.path.exists(fallback):
                shutil.move(fallback, output_path)
            else:
                # 列出 frames_dir 中的文件数
                frame_count = len(os.listdir(frames_dir))
                raise RuntimeError(
                    f"MP4 合成失败 (ffmpeg). 帧目录有 {frame_count} 帧。\n"
                    f"请检查 ffmpeg 是否正确安装。"
                )

        return output_path

    def cleanup(self):
        """清理临时目录"""
        if os.path.exists(self.temp_dir) and "anim_rec_" in self.temp_dir:
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass


# ── 命令行测试 ──
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="录制 HTML 动画为 MP4")
    parser.add_argument("html", help="动画 HTML 文件路径")
    parser.add_argument("-d", "--duration", type=float, default=5,
                        help="录制时长（秒）")
    parser.add_argument("-o", "--output", help="输出 MP4 路径")
    parser.add_argument("--fps", type=int, default=30, help="帧率")
    parser.add_argument("--width", type=int, default=1280, help="宽度")
    parser.add_argument("--height", type=int, default=720, help="高度")
    parser.add_argument("--quality", type=int, default=23, help="CRF 质量")

    args = parser.parse_args()

    rec = Recorder(fps=args.fps, quality=args.quality)
    try:
        path = rec.record(
            html_path=args.html,
            duration=args.duration,
            output_path=args.output,
            width=args.width,
            height=args.height,
        )
        print(f"\n🎉 MP4 文件: {path}")
    finally:
        rec.cleanup()

"""
Webview 显示模块 — 在原生窗口中显示 HTML 动画

支持:
    - 窗口显示 (GUI)
    - 全屏模式
    - 无头模式 (仅后台渲染)
"""

import os
import threading
import time


class WebviewPlayer:
    """使用 pywebview 显示 HTML 动画"""

    def __init__(self, title: str = "动画画布",
                 width: int = 1280, height: int = 720,
                 fullscreen: bool = False):
        self.title = title
        self.width = width
        self.height = height
        self.fullscreen = fullscreen
        self._window = None

    def play(self, html_path: str) -> None:
        """
        在 webview 窗口中播放动画

        参数:
            html_path: HTML 文件路径 (绝对或相对路径)
        """
        abs_path = os.path.abspath(html_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"HTML 文件不存在: {abs_path}")

        # 尝试导入 pywebview
        try:
            import webview
        except ImportError:
            print("⚠️ pywebview 未安装，将使用浏览器打开")
            self._open_browser(abs_path)
            return

        # 创建窗口
        self._window = webview.create_window(
            title=self.title,
            url=f"file:///{abs_path.replace(os.sep, '/')}",
            width=self.width,
            height=self.height,
            fullscreen=self.fullscreen,
            resizable=True,
            minimized=False,
        )
        webview.start(debug=False)

    def play_async(self, html_path: str) -> threading.Thread:
        """
        在后台线程中播放（非阻塞）

        返回:
            threading.Thread 对象
        """
        t = threading.Thread(target=self.play, args=(html_path,), daemon=True)
        t.start()
        time.sleep(1)  # 等待窗口启动
        return t

    def _open_browser(self, abs_path: str) -> None:
        """回退方案：用系统浏览器打开"""
        import webbrowser
        file_url = f"file:///{abs_path.replace(os.sep, '/')}"
        print(f"🌐 在浏览器中打开: {file_url}")
        webbrowser.open(file_url)


# ── 命令行测试 ──
if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not os.path.exists(path):
        print("用法: python player.py <html_path>")
        print("请指定一个已有的 HTML 文件")
        sys.exit(1)
    player = WebviewPlayer(fullscreen="--fullscreen" in sys.argv)
    player.play(path)

"""
Tea Agent GUI2 — PySide6 + QML 桌面界面。

替代老旧的 Tkinter GUI。使用 QWebEngineView 渲染聊天 Markdown，
完美支持 HTML5/CSS3，解决 tkinterweb 的兼容性问题。

用法:
    python -m tea_agent.gui2                          # 启动 GUI
    python -m tea_agent.gui2 --port 8080               # 指定端口（供 Web 模式备用）
    python -m tea_agent.gui2 --debug                   # 开发者工具开启

架构:
    gui2/
    ├── __init__.py          ← 入口：QApplication + QML Engine
    ├── _backend.py          ← Python↔QML 桥接层 (QObject)
    ├── _markdown_bridge.py  ← 复用现有 markdown→HTML 渲染
    ├── server.py            ← 保留：Bottle 后端（pywebview 兼容）
    ├── qml/
    │   ├── main.qml         ← 主窗口
    │   ├── Sidebar.qml      ← 主题列表侧栏
    │   ├── ChatView.qml     ← QWebEngineView 聊天区
    │   ├── InputArea.qml    ← 消息输入区
    │   └── Theme.qml        ← 颜色主题定义
    └── frontend/            ← 保留：Web 前端（pywebview 兼容）
"""

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property

# ── 配置日志 ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gui2")

# ── 确保项目路径 ─────────────────────────────────────────
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


class ThemeObject(QObject):
    """QML 主题对象 — 所有属性为 constant，在 QML 中以 `theme` 访问。

    改为模块级类以解决 Python 内联类的 QML 属性可见性问题。
    """
    def __init__(self, parent=None):
        super().__init__(parent)

    # ── 颜色 ──────────────────────────
    @Property(str, constant=True)
    def bgColor(self): return "#f5f5f5"
    @Property(str, constant=True)
    def sidebarBg(self): return "#ffffff"
    @Property(str, constant=True)
    def sidebarHover(self): return "#e8f0fe"
    @Property(str, constant=True)
    def sidebarSelected(self): return "#cce0ff"
    @Property(str, constant=True)
    def chatBg(self): return "#ffffff"
    @Property(str, constant=True)
    def inputBg(self): return "#f8f9fa"
    @Property(str, constant=True)
    def primaryText(self): return "#202124"
    @Property(str, constant=True)
    def secondaryText(self): return "#5f6368"
    @Property(str, constant=True)
    def accentColor(self): return "#1a73e8"
    @Property(str, constant=True)
    def accentHover(self): return "#1557b0"
    @Property(str, constant=True)
    def borderColor(self): return "#dadce0"
    @Property(str, constant=True)
    def dividerColor(self): return "#e8eaed"
    @Property(str, constant=True)
    def successColor(self): return "#34a853"
    @Property(str, constant=True)
    def warningColor(self): return "#fbbc04"
    @Property(str, constant=True)
    def errorColor(self): return "#ea4335"
    @Property(str, constant=True)
    def thinkBg(self): return "#fef3c7"
    @Property(str, constant=True)
    def thinkBorder(self): return "#f59e0b"
    @Property(str, constant=True)
    def toolBg(self): return "#ecfdf5"
    @Property(str, constant=True)
    def toolBorder(self): return "#10b981"
    @Property(str, constant=True)
    def userBubbleBg(self): return "#e3f2fd"
    @Property(str, constant=True)
    def aiBubbleBg(self): return "#f1f8e9"

    # ── 字体 ──────────────────────────
    @Property(str, constant=True)
    def fontFamily(self): return "Segoe UI, Noto Sans SC, Microsoft YaHei, sans-serif"
    @Property(str, constant=True)
    def monoFont(self): return "Cascadia Code, JetBrains Mono, Consolas, monospace"
    @Property(int, constant=True)
    def titleSize(self): return 20
    @Property(int, constant=True)
    def headingSize(self): return 15
    @Property(int, constant=True)
    def bodySize(self): return 14
    @Property(int, constant=True)
    def smallSize(self): return 12
    @Property(int, constant=True)
    def inputSize(self): return 14

    # ── 间距 ──────────────────────────
    @Property(int, constant=True)
    def sidebarWidth(self): return 260
    @Property(int, constant=True)
    def borderRadius(self): return 8
    @Property(int, constant=True)
    def smallRadius(self): return 4
    @Property(int, constant=True)
    def padding(self): return 12
    @Property(int, constant=True)
    def spacing(self): return 8

    # ── 暗黑模式 ──────────────────────
    @Property(bool, constant=True)
    def isDark(self): return False


def main():
    """主入口：初始化 Qt → 加载 QML → 进入事件循环。"""
    parser = argparse.ArgumentParser(description="Tea Agent Qt GUI")
    parser.add_argument("--debug", action="store_true", help="启用 QML 调试控制台")
    parser.add_argument("--port", type=int, default=0, help="服务器端口（保留，暂未使用）")
    args = parser.parse_args()

    # ── 可选调试：先设环境变量 ──
    if args.debug:
        import os
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "9222"
        logger.info("QML Inspector: http://127.0.0.1:9222")

    # ── 设置 Qt Quick Controls 样式为 Fusion（支持自定义 background） ──
    import os as _os
    if "QT_QUICK_CONTROLS_STYLE" not in _os.environ:
        _os.environ["QT_QUICK_CONTROLS_STYLE"] = "Fusion"

    # ── Step 1: 初始化 Qt WebEngine（必须在 QApp 创建前或创建后立即调用） ──
    from PySide6.QtWebEngineQuick import QtWebEngineQuick
    QtWebEngineQuick.initialize()
    logger.info("Qt WebEngine initialized")

    # ── Step 2: 创建 QApplication ──
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Tea Agent")
    app.setApplicationVersion("0.10.14")
    app.setOrganizationName("TeaAgent")

    # ── Step 3: 创建 Python 后端对象（必须在 Engine 前创建，但 Engine 后注入） ──
    from tea_agent.gui2._backend import BackendBridge
    from tea_agent.gui2._markdown_bridge import MarkdownBridge

    backend = BackendBridge()
    markdownBridge = MarkdownBridge()
    theme = ThemeObject()       # 模块级类

    # ── Step 4: 创建 QML Engine + 注入上下文 ──
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", backend)
    ctx.setContextProperty("markdownBridge", markdownBridge)
    ctx.setContextProperty("theme", theme)

    # ── Step 5: 加载 QML ──
    qml_path = Path(__file__).parent / "qml" / "main.qml"
    if not qml_path.exists():
        logger.error(f"QML file not found: {qml_path}")
        sys.exit(1)

    url = QUrl.fromLocalFile(str(qml_path.resolve()))
    engine.load(url)

    if not engine.rootObjects():
        logger.error("Failed to load QML root objects")
        for e in engine.errors():
            logger.error(f"  QML Error: {e.toString()}")
        sys.exit(1)

    logger.info(f"QML loaded from: {qml_path}")

    # ── Step 6: 进入事件循环 ──
    exit_code = app.exec()

    # ── Step 7: 清理 ──
    backend.cleanup()
    logger.info("Qt GUI exited")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

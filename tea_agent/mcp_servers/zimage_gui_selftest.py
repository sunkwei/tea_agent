#!/usr/bin/env python
# version: 1.0.0
"""Z-Image GUI 无头自测：offscreen 平台下走完「预热 → 生成 2 张 → 出图 → 放大窗口」全流程。

    python zimage_gui_selftest.py [日志路径]
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "_gui_selftest.log"


def log(*a):
    line = f"[{time.strftime('%H:%M:%S')}] " + " ".join(str(x) for x in a)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import zimage_gui as gui  # noqa: E402


def wait(cond, timeout: float, tick: int = 200) -> bool:
    """轮询等待条件成立（保持事件循环转动）。"""
    loop = QEventLoop()
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if cond():
            return True
        QTimer.singleShot(tick, loop.quit)
        loop.exec()
    return False


def main() -> int:
    t_all = time.time()
    gui.engine._warmup()
    log("warmup", round(time.time() - t_all, 1))

    app = QApplication(sys.argv)
    win = gui.MainWindow()
    win.show()
    log("window built; 预热管线中…")

    ok = wait(lambda: win.status.text().startswith("模型就绪") or "失败" in win.status.text(), timeout=600)
    log(f"preload ok={ok}", win.status.text())
    if not ok:
        return 2

    # 三档分辨率按钮互斥性
    btns = win.res_group.buttons()
    log("分辨率按钮:", [b.text() for b in btns], "默认选中:", win.res_group.checkedButton().text())
    btns[1].setChecked(True)
    log("切到竖版后 checked:", win.res_group.checkedButton().text(), "| 互斥:", sum(b.isChecked() for b in btns) == 1)
    btns[0].setChecked(True)

    # 张数控件
    win.count.setValue(2)
    log("张数:", win.count.value(), "范围:", win.count.minimum(), "-", win.count.maximum())

    got: list[list[str]] = []
    win.generation_finished.connect(lambda paths: got.append(paths))

    win.prompt.setPlainText("青花瓷茶杯，白瓷，蓝色缠枝莲纹样，浅灰背景，影棚打光，产品摄影")
    t0 = time.time()
    win.start_generate()
    log("已触发生成；进度条范围", win.progress.minimum(), "-", win.progress.maximum())

    seen: list[str] = []

    def progressed() -> bool:
        txt = win.status.text()
        if txt != (seen[-1] if seen else ""):
            seen.append(txt)
        return bool(got)

    ok = wait(progressed, timeout=900)
    log(f"生成完成 ok={ok} 用时={time.time() - t0:.1f}s 状态={win.status.text()}")
    log("进度更新次数:", len(seen), "样例:", seen[:2], "…", seen[-1:])

    if not ok:
        return 3
    paths = got[0]
    log("产物:", paths)
    log("缩略图数量:", len(win._thumbs), "| 结果区控件数:", win.grid.count())
    for p in paths:
        log(f"  存在={Path(p).exists()} 大小={Path(p).stat().st_size / 1024:.0f}KB {Path(p).name}")

    # 放大窗口（不进入模态循环，只构造 + 触发一次另存为到临时文件）
    dlg = gui.ImageDialog(paths[0])
    zoom = dlg.findChild(gui.ZoomView)
    log("放大窗口 缩放=%.2f 尺寸=%dx%d" % (zoom._scale, zoom.width(), zoom.height()))

    saved = Path(os.environ["TEMP"]) / f"zimage_save_test_{int(time.time())}.png"
    from PySide6.QtGui import QPixmap

    ok_save = QPixmap(paths[0]).save(str(saved))
    log(f"另存为路径可用={ok_save} 文件存在={saved.exists()} 大小={saved.stat().st_size / 1024:.0f}KB")
    dlg.deleteLater()

    log("ALL_DONE", f"总用时 {time.time() - t_all:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

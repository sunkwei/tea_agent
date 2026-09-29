#!/usr/bin/env python
# version: 2.0.0
"""Z-Image-Turbo 文生图 GUI（tkinter，零第三方 GUI 依赖）。

布局（上中下）
    上：结果区——缩略图，点击弹出放大窗口（按图片比例开窗），可另存为本地文件
    中：控制区——进度条（生成轮次）、三档分辨率互斥按钮、生成张数
    下：提示词输入——Enter 生成，Shift+Enter 换行

推理引擎复用 zimage_server（同一份实现，与 MCP 不会走偏）。
tkinter 在 Windows 上默认按 96 DPI 渲染，高分屏会糊，故启动先声明 DPI 感知。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import zimage_server as engine  # noqa: E402

OUT_DIR = Path(os.environ.get("ZIMAGE_OUTPUT_DIR") or (Path.cwd() / "output" / "zimage"))
THUMB = 260  # 缩略图边长上限
GAP = 12
FONT_SCALE = 1.45  # 全局字号放大倍数（可用环境变量 ZIMAGE_FONT_SCALE 覆盖）
BG, PANEL, FG, MUTED = "#1b1b1b", "#232323", "#e6e6e6", "#8a8a8a"
RESOLUTIONS = [("1024 × 1024", 1024, 1024), ("720 × 1280", 720, 1280), ("1280 × 720", 1280, 720)]


def font_scale() -> float:
    try:
        return max(1.0, float(os.environ.get("ZIMAGE_FONT_SCALE", FONT_SCALE)))
    except ValueError:
        return FONT_SCALE


def scaled(size: int) -> int:
    """把某个写死的字号按全局倍数放大（给 Canvas 文本项用）。"""
    return max(8, int(round(size * font_scale())))


def apply_font_scale() -> None:
    """放大 Tk 命名字体——未显式指定字体的控件会自动跟随。"""
    import tkinter.font as tkfont

    for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
        try:
            f = tkfont.nametofont(name)
        except Exception:
            continue
        size = f.cget("size")
        if size:  # 负值表示像素单位，同样按倍数缩放
            f.configure(size=max(8, int(round(size * font_scale()))))


def enable_dpi_awareness() -> None:
    """Windows 高分屏必须显式声明，否则整窗被系统拉伸模糊。"""
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def load_scaled(path: str, box: tuple[int, int]):
    """按外围框等比缩放，返回 PIL Image（不依赖 Tk）。"""
    from PIL import Image

    im = Image.open(path)
    im.thumbnail(box, Image.LANCZOS)
    return im


def dialog_geometry(iw: int, ih: int, screen: tuple[int, int]) -> tuple[int, int, int, int]:
    """按图片比例算弹窗几何（含居中坐标）。纯函数，便于单测。"""
    sw, sh = screen
    max_w, max_h = int(sw * 0.8), int(sh * 0.85)
    chrome = 110  # 信息栏 + 按钮栏占位
    scale = min(max_w / iw, max(1, max_h - chrome) / ih, 1.0)
    w, h = max(520, int(iw * scale)), int(ih * scale) + chrome
    return (sw - w) // 2, (sh - h) // 3, w, h


# ────────────────────────────── 生成线程 ──────────────────────────────
class GenThread(threading.Thread):
    """后台生成；结果经队列回主线程（tkinter 控件只能主线程碰）。"""

    def __init__(self, q: queue.Queue, prompt: str, width: int, height: int, num_images: int) -> None:
        super().__init__(daemon=True)
        self.q, self.prompt, self.width, self.height, self.num_images = q, prompt, width, height, num_images

    def run(self) -> None:
        import json

        engine.set_progress_hook(lambda d, t, text: self.q.put(("progress", d, t, text)))
        try:
            data = json.loads(
                engine.zimage_generate(
                    prompt=self.prompt,
                    width=self.width,
                    height=self.height,
                    num_images=self.num_images,
                    output_dir=str(OUT_DIR),
                )
            )
        except Exception as e:
            self.q.put(("failed", f"{type(e).__name__}: {e}"))
            return
        finally:
            engine.set_progress_hook(None)  # 钩子持有本对象引用，务必解除

        self.q.put(("done", data) if data.get("ok") else ("failed", data.get("error", "未知错误")))


# ────────────────────────────── 放大窗口 ──────────────────────────────
class ZoomDialog(tk.Toplevel):
    """放大预览：按图片比例开窗，滚轮缩放、按住拖动、可另存为。"""

    MIN, MAX = 0.05, 8.0

    def __init__(self, master: tk.Misc, path: str) -> None:
        super().__init__(master)
        from PIL import Image, ImageTk

        self._Image, self._ImageTk = Image, ImageTk
        self._path = path
        self._im = Image.open(path).convert("RGB")
        self._scale = 1.0
        self._offset = [0.0, 0.0]  # 图像左上角在画布上的位置
        self._drag: tuple[float, float] | None = None
        self._user_adjusted = False
        self._photo = None

        self.title(f"预览 — {Path(path).name}")
        gx, gy, gw, gh = dialog_geometry(self._im.width, self._im.height, (self.winfo_screenwidth(), self.winfo_screenheight()))
        self.geometry(f"{gw}x{gh}+{gx}+{gy}")
        self.configure(bg=BG)
        self.transient(master)

        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        # Windows 的 <MouseWheel> 只投给焦点控件，故鼠标移入即抢焦点
        self.canvas.bind("<Enter>", lambda _e: self.canvas.focus_set())
        self.canvas.bind("<Configure>", lambda _e: None if self._user_adjusted else self._fit())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag", None))
        self.canvas.bind("<Double-Button-1>", lambda _e: self._fit())

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Label(bar, text="滚轮缩放 · 按住拖动 · 双击复位", bg=PANEL, fg=MUTED).pack(side="left", padx=10, pady=6)
        tk.Button(bar, text="关闭", width=8, command=self.destroy).pack(side="right", padx=6, pady=4)
        tk.Button(bar, text="另存为本地文件…", command=self._save_as).pack(side="right", padx=6, pady=4)
        tk.Button(bar, text="适应窗口", width=10, command=self._fit).pack(side="right", padx=6, pady=4)
        tk.Label(self, text=f"原图已保存于：{path}", bg=BG, fg=MUTED, anchor="w").pack(fill="x", padx=10, pady=(0, 6))

        self.after(60, self._fit)  # 等控件拿到真实尺寸后再适配

    # ── 视图 ──
    def _fit(self) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 20 or ch <= 20:
            return
        self._scale = min((cw - 24) / self._im.width, (ch - 24) / self._im.height, 1.0)
        self._user_adjusted = False
        self._center()

    def _center(self) -> None:
        self._offset = [
            (self.canvas.winfo_width() - self._im.width * self._scale) / 2,
            (self.canvas.winfo_height() - self._im.height * self._scale) / 2,
        ]
        self._render()

    def _render(self) -> None:
        w = max(1, int(self._im.width * self._scale))
        h = max(1, int(self._im.height * self._scale))
        self._photo = self._ImageTk.PhotoImage(self._im.resize((w, h), self._Image.LANCZOS))
        self.canvas.delete("img")
        self.canvas.create_image(self._offset[0], self._offset[1], anchor="nw", image=self._photo, tags="img")

    def _wheel(self, e) -> None:
        factor = 1.15 if e.delta > 0 else 1 / 1.15
        new = max(self.MIN, min(self.MAX, self._scale * factor))
        if new == self._scale:
            return
        # 以光标为锚点：光标下的图像坐标保持不变
        self._offset = [e.x - (e.x - self._offset[0]) * (new / self._scale), e.y - (e.y - self._offset[1]) * (new / self._scale)]
        self._scale = new
        self._user_adjusted = True
        self._render()

    def _press(self, e) -> None:
        self._drag = (e.x, e.y)

    def _move(self, e) -> None:
        if self._drag is None:
            return
        self._offset[0] += e.x - self._drag[0]
        self._offset[1] += e.y - self._drag[1]
        self._drag = (e.x, e.y)
        self._user_adjusted = True
        self._render()

    # ── 另存为 ──
    def _save_as(self) -> None:
        src = Path(self._path)
        target = filedialog.asksaveasfilename(
            parent=self,
            title="另存为",
            initialdir=str(src.parent),
            initialfile=src.name,
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg"), ("WebP 图片", "*.webp")],
        )
        if not target:
            return
        try:
            fmt = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}.get(Path(target).suffix.lstrip(".").lower(), "PNG")
            self._im.save(target, format=fmt)
            messagebox.showinfo("已保存", f"已保存到：\n{target}", parent=self)
        except Exception as e:
            messagebox.showerror("保存失败", f"{type(e).__name__}: {e}", parent=self)


# ────────────────────────────── 主窗口 ──────────────────────────────
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Z-Image-Turbo 文生图")
        self.geometry("1180x980")
        self.minsize(760, 640)
        self.configure(bg=BG)
        apply_font_scale()  # 必须在 _build() 之前：控件创建时即取当前字号
        self._thumbs: list[tuple[tk.Canvas, str, object]] = []
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        self._t0 = 0.0
        self._res = (RESOLUTIONS[0][1], RESOLUTIONS[0][2])
        self._build()
        self.after(80, self._pump)
        self._preload()

    # ── 布局 ──
    def _build(self) -> None:
        # ① 结果区
        top = tk.Frame(self, bg=BG)
        top.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.canvas = tk.Canvas(top, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(top, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._relayout())
        self.canvas.bind("<Enter>", lambda _e: self.canvas.focus_set())
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self._empty = self.canvas.create_text(0, 0, text="还没有图片 —— 在下方输入提示词，按 Enter 开始生成", fill="#777", font=("Microsoft YaHei UI", scaled(12)))

        # ② 控制区
        mid = tk.Frame(self, bg=BG)
        mid.pack(fill="x", padx=10, pady=(8, 0))
        self.progress = ttk.Progressbar(mid, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x")
        self.status = tk.Label(mid, text="正在加载模型…", bg=BG, fg=MUTED, anchor="w")
        self.status.pack(fill="x", pady=(2, 4))

        ctrl = tk.Frame(mid, bg=BG)
        ctrl.pack(fill="x")
        tk.Label(ctrl, text="分辨率", bg=BG, fg=FG).pack(side="left")
        self._res_var = tk.IntVar(value=0)
        self._rbts: list[tk.Radiobutton] = []
        for i, (label, w, h) in enumerate(RESOLUTIONS):
            # 互斥由同一 IntVar 的 radiobutton 保证（三选一）
            rb = tk.Radiobutton(
                ctrl, text=label, value=i, variable=self._res_var, command=lambda w=w, h=h: self._set_res(w, h),
                bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                highlightthickness=0, indicatoron=False, width=11, relief="raised", bd=1,
            )
            rb.pack(side="left", padx=(6, 0))
            self._rbts.append(rb)
        tk.Label(ctrl, text="张数", bg=BG, fg=FG).pack(side="left", padx=(20, 4))
        self.count = tk.Spinbox(ctrl, from_=1, to=4, width=3, justify="center", bg=PANEL, fg=FG, buttonbackground=PANEL, insertbackground=FG)
        self.count.pack(side="left")
        self.go = tk.Button(ctrl, text="生成", width=10, command=self.start_generate, bg="#3a6ea5", fg="white", activebackground="#4a7eb5", relief="raised", bd=1)
        self.go.pack(side="right")

        # ③ 提示词
        self.prompt = tk.Text(self, height=4, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", wrap="word", padx=8, pady=6)
        self.prompt.pack(fill="x", padx=10, pady=(8, 0))
        self.prompt.bind("<Return>", self._on_return)
        tk.Label(self, text="Enter 生成 · Shift+Enter 换行 · 点击图片放大后可选另存为", bg=BG, fg="#666", anchor="w").pack(fill="x", padx=10, pady=(2, 8))

    def _on_return(self, e) -> str:
        if not (e.state & 0x1):  # Shift 未按下
            self.start_generate()
            return "break"  # 阻止插入换行
        return ""  # 放行，Text 自行换行

    def _set_res(self, w: int, h: int) -> None:
        self._res = (w, h)

    # ── 缩略图 ──
    def _show_images(self, paths: list[str]) -> None:
        self.canvas.delete("thumb")
        self._thumbs = []
        if paths:
            self.canvas.itemconfigure(self._empty, state="hidden")
            for p in paths:
                im = load_scaled(p, (THUMB, THUMB))
                holder = self._ImageTk().PhotoImage(im)
                item = self.canvas.create_image(0, 0, anchor="nw", image=holder, tags=("thumb", f"f:{p}"))
                self.canvas.tag_bind(item, "<Button-1>", lambda _e, p=p: ZoomDialog(self, p))
                self.canvas.tag_bind(item, "<Enter>", lambda _e: self.canvas.configure(cursor="hand2"))
                self.canvas.tag_bind(item, "<Leave>", lambda _e: self.canvas.configure(cursor=""))
                self._thumbs.append((item, holder))
        else:
            self.canvas.itemconfigure(self._empty, state="normal")
        self._relayout()

    def _ImageTk(self):
        from PIL import ImageTk

        return ImageTk

    def _relayout(self) -> None:
        cw = max(self.canvas.winfo_width(), 1)
        cols = max(1, cw // (THUMB + GAP))
        if not self._thumbs:
            self.canvas.coords(self._empty, cw // 2, 120)
            self.canvas.configure(scrollregion=(0, 0, cw, 260))
            return
        for i, (item, _h) in enumerate(self._thumbs):
            x, y = GAP + (i % cols) * (THUMB + GAP), GAP + (i // cols) * (THUMB + GAP)
            self.canvas.coords(item, x, y)
            self.canvas.tag_lower(item)
        rows = (len(self._thumbs) + cols - 1) // cols
        self.canvas.configure(scrollregion=(0, 0, cw, GAP + rows * (THUMB + GAP)))

    # ── 预热 ──
    def _preload(self) -> None:
        def work() -> None:
            try:
                _pipe, strategy, warn = engine.get_pipe()
                note = f"{strategy.get('quantization')} 量化 / offload={strategy.get('offload')} / {strategy.get('vram_gb')}GiB"
                self._q.put(("loaded", note + (f" ⚠️ {warn}" if warn else "")))
            except Exception as e:
                self._q.put(("preload_failed", f"{type(e).__name__}: {e}"))

        self.progress.configure(mode="indeterminate")
        self.progress.start(60)
        threading.Thread(target=work, daemon=True).start()

    # ── 生成 ──
    def start_generate(self) -> None:
        if self._busy:
            return
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            self._status("提示词为空，请先输入内容", "#e66")
            return
        w, h = self._res
        n = int(self.count.get())
        self._t0 = time.time()
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=n * engine.TURBO_STEPS, value=0)
        self._status(f"开始生成 {n} 张 {w} × {h} …")
        self._busy = True
        self._set_enabled(False)
        GenThread(self._q, prompt, w, h, n).start()

    def _set_enabled(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.go.configure(state=state)
        self.count.configure(state=state)
        for rb in self._rbts:  # 必须持有引用：控件在嵌套 Frame 里，遍历子控件找不到
            rb.configure(state=state)

    def _status(self, text: str, color: str = MUTED) -> None:
        self.status.configure(text=text, fg=color)

    # ── 主线程泵 ──
    def _pump(self) -> None:
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]
                if kind == "loaded":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=100, value=0)
                    self._status(f"模型就绪（{msg[1]}），可以开始生成")
                elif kind == "preload_failed":
                    self.progress.stop()
                    self._status(f"模型加载失败：{msg[1]}", "#e66")
                elif kind == "progress":
                    _, done, total, text = msg
                    self.progress.configure(maximum=total, value=done)
                    elapsed = time.time() - self._t0
                    eta = elapsed / done * (total - done) if done else 0
                    self._status(f"{text} · 已用 {elapsed:.0f}s · 预计剩余 {eta:.0f}s")
                elif kind == "done":
                    self._on_done(msg[1])
                elif kind == "failed":
                    self._on_failed(msg[1])
        except queue.Empty:
            pass
        self.after(80, self._pump)

    def _on_done(self, data: dict) -> None:
        self._busy = False
        self._set_enabled(True)
        paths = data.get("images", [])
        self._show_images(paths)
        color = "#e93" if data.get("warn") else "#5c5"
        extra = f" ⚠️ {data['warn']}" if data.get("warn") else ""
        self._status(
            f"完成 {len(paths)} 张 · {data.get('size')} · 用时 {data.get('elapsed_sec')}s · seed={data.get('seed')} · "
            f"{data.get('quantization')}{' + offload' if data.get('offload') else ''}{extra}",
            color,
        )

    def _on_failed(self, msg: str) -> None:
        self._busy = False
        self._set_enabled(True)
        self.progress.configure(value=0)
        self._status(f"生成失败：{msg}", "#e66")
        messagebox.showerror("生成失败", msg, parent=self)


def main() -> None:
    enable_dpi_awareness()
    engine._warmup()  # 重型导入留在主线程：线程内首次导入在 Windows 上会挂死
    App().mainloop()


if __name__ == "__main__":
    main()

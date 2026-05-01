## llm generated tool func, created Fri May  1 09:48:55 2026
# version: 1.0.1


def toolkit_screenshot(action: str, region: str = None, monitor: int = None, output: str = None, quality: int = 90):
    """
    跨平台智能截屏 — 自动适配 Wayland/X11/macOS/Windows
    Wayland 区域截屏策略：先全屏截取，再用 PIL 裁剪（绕开各工具的交互限制）
    """
    import os, subprocess, tempfile, shutil
    from datetime import datetime
    from pathlib import Path

    def _detect_env():
        ds = os.environ.get("XDG_SESSION_TYPE", "").lower()
        de = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if not ds and os.environ.get("WAYLAND_DISPLAY"):
            ds = "wayland"
        return ds, de

    def _find_tool(*names):
        for name in names:
            path = shutil.which(name)
            if path: return path
        return None

    def _crop_image(src, dst, geo):
        """用 PIL 裁剪图片"""
        x, y, w, h = map(int, geo.split(","))
        try:
            from PIL import Image
            img = Image.open(src)
            img = img.crop((x, y, x+w, y+h))
            img.save(dst, quality=quality)
            return True
        except ImportError:
            pass
        # fallback: ImageMagick convert
        cv = _find_tool("convert")
        if cv:
            r = subprocess.run([cv, src, "-crop", f"{w}x{h}+{x}+{y}", dst],
                              capture_output=True, timeout=15)
            return r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 100
        return False

    def _wayland_fullscreen(out_path):
        """Wayland 全屏截取"""
        ds, de = _detect_env()

        # KDE → spectacle
        if "kde" in de or "plasma" in de:
            spec = _find_tool("spectacle")
            if spec:
                r = subprocess.run([spec, "-f", "-o", out_path, "-b", "-n"],
                                   capture_output=True, timeout=10)
                if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                    return out_path

        # GNOME → gnome-screenshot
        gs = _find_tool("gnome-screenshot")
        if gs:
            r = subprocess.run([gs, "-f", out_path], capture_output=True, timeout=10)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                return out_path

        # wlroots → grim
        grim = _find_tool("grim")
        if grim:
            r = subprocess.run([grim, out_path], capture_output=True, timeout=10)
            if r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                return out_path

        return None

    def _x11_screenshot(out_path, geo=None):
        try:
            import mss
            with mss.mss() as sct:
                if geo:
                    x, y, w, h = map(int, geo.split(","))
                    monitor = {"top": y, "left": x, "width": w, "height": h}
                else:
                    monitor = sct.monitors[0]
                # mss region capture
                if geo:
                    sct.shot(output=out_path, mon=-1)
                    return _crop_image(out_path, out_path, geo) if True else out_path
                else:
                    sct.shot(output=out_path)
                if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                    return out_path
        except ImportError:
            pass

        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            if geo:
                x, y, w, h = map(int, geo.split(","))
                img = img.crop((x, y, x+w, y+h))
            img.save(out_path, quality=quality)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                return out_path
        except ImportError:
            pass

        xs = _find_tool("xfce4-screenshooter")
        if xs:
            subprocess.run([xs, "-f", out_path, "--fullscreen"], capture_output=True, timeout=10)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
                if geo:
                    tmp = out_path + ".full"
                    os.rename(out_path, tmp)
                    if _crop_image(tmp, out_path, geo):
                        os.remove(tmp)
                        return out_path
                return out_path
        return None

    def _list_monitors():
        ds, de = _detect_env()
        monitors = []
        xr = _find_tool("xrandr")
        if xr:
            r = subprocess.run([xr, "--query"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.split("\n"):
                if " connected" in line:
                    parts = line.split()
                    name = parts[0]
                    geo = ""
                    for p in parts:
                        if "x" in p and "+" in p and p[0].isdigit():
                            geo = p
                            break
                    monitors.append({"name": name, "geometry": geo, "primary": "primary" in line})
        wr = _find_tool("wlr-randr")
        if wr:
            r = subprocess.run([wr], capture_output=True, text=True, timeout=5)
            current = {}
            for line in r.stdout.split("\n"):
                line = line.strip()
                if line and not line.startswith(" "):
                    if current: monitors.append(current)
                    current = {"name": line.split()[0]}
                elif "Position:" in line:
                    current["geometry"] = line.split("Position:")[-1].strip()
                elif "Enabled:" in line and "yes" in line:
                    current["enabled"] = True
            if current: monitors.append(current)
        return monitors

    # === 主逻辑 ===
    if action == "list_monitors":
        monitors = _list_monitors()
        ds, de = _detect_env()
        return {"monitors": monitors, "display_server": ds, "desktop": de, "count": len(monitors)}

    ds, de = _detect_env()

    if not output:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join(tempfile.gettempdir(), f"screenshot_{ts}.png")

    geo = None
    if action == "region" and region:
        geo = region
    elif action == "monitor" and monitor:
        monitors = _list_monitors()
        if monitor <= len(monitors):
            m = monitors[monitor - 1]
            if m.get("geometry"):
                import re
                nums = re.findall(r'\d+', m["geometry"])
                if len(nums) >= 4:
                    geo = f"{nums[0]},{nums[1]},{nums[2]},{nums[3]}"

    result = None
    method = "unknown"

    # 策略：Wayland 全屏截取 + PIL 裁剪
    if ds == "wayland":
        full = _wayland_fullscreen(output)
        if full:
            if geo:
                tmp_full = output + ".full"
                os.rename(output, tmp_full)
                if _crop_image(tmp_full, output, geo):
                    os.remove(tmp_full)
                    result = output
                    method = "wayland+crop"
                else:
                    os.rename(tmp_full, output)
                    result = output
                    method = "wayland-full(fallback)"
            else:
                result = output
                method = "wayland-native"
    elif ds == "x11":
        result = _x11_screenshot(output, geo)
        method = "x11"
    else:
        if shutil.which("screencapture"):
            # macOS
            cmd = ["screencapture"]
            if geo:
                x, y, w, h = geo.split(",")
                cmd += ["-R", f"{x},{y},{w},{h}"]
            cmd.append(output)
            r = subprocess.run(cmd, capture_output=True, timeout=10)
            if r.returncode == 0 and os.path.exists(output) and os.path.getsize(output) > 100:
                result = output
            method = "macos"
        else:
            result = _x11_screenshot(output, geo)
            method = "windows/fallback"

    if result and os.path.exists(result):
        size = os.path.getsize(result)
        return {"success": True, "path": result, "size": size, "size_kb": round(size/1024,1),
                "method": method, "display_server": ds, "desktop": de}
    else:
        return {"success": False, "error": f"所有截屏方式均失败 (ds={ds}, de={de})",
                "tried": method, "tip": "Wayland用户请安装 spectacle、gnome-screenshot 或 grim"}


def meta_toolkit_screenshot() -> dict:
    return {"type": "function", "function": {"name": "toolkit_screenshot", "description": "跨平台智能截屏工具。自动检测 Wayland/X11/macOS/Windows 并选择最佳截屏方式。Wayland 下自动使用系统自带工具（spectacle/gnome-screenshot/grim），彻底解决 Python 截屏库黑屏问题。支持全屏、区域、指定显示器。", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["full", "region", "monitor", "list_monitors"], "description": "full=全屏, region=指定区域(x,y,w,h), monitor=指定显示器, list_monitors=列出显示器"}, "region": {"type": "string", "description": "[region] 截取区域，格式 'x,y,w,h'（如 '100,200,800,600'）"}, "monitor": {"type": "integer", "description": "[monitor] 显示器索引，1=主屏, 2=第二屏..."}, "output": {"type": "string", "description": "输出文件路径，默认自动生成临时文件"}, "quality": {"type": "integer", "description": "JPEG 质量 1-100，默认 90。仅对 JPEG 有效"}}, "required": ["action"]}}}

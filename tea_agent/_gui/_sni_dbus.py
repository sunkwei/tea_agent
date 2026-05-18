"""
@2026-07-07 gen by tea_agent, StatusNotifierItem D-Bus 实现
从 gui.py L579-679 提取：KDE Plasma 6 原生托盘图标 D-Bus 服务
"""

import os as _os
import logging

logger = logging.getLogger("main_db_gui")

try:
    import dbus
    import dbus.service
    import dbus.mainloop.glib
    from gi.repository import GLib
    HAS_SNI = True
except ImportError:
    HAS_SNI = False


if HAS_SNI:
    class StatusNotifierItemDBus(dbus.service.Object):
        """StatusNotifierItem D-Bus 服务，替代 pystray，原生兼容 KDE Plasma 6"""

        def __init__(self, app_id, title, icon_pixmap_ar32, on_activate, on_context_menu):
            self._app_id = app_id
            self._title = title
            self._icon_data = icon_pixmap_ar32  # ARGB32 bytes
            self._on_activate = on_activate
            self._on_context_menu = on_context_menu
            self._loop = None
            self._thread = None

            # 初始化 D-Bus
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SessionBus()
            bus_name = dbus.service.BusName(
                f"org.kde.StatusNotifierItem-{_os.getpid()}-{app_id}",
                bus=self._bus
            )
            super().__init__(bus_name, "/StatusNotifierItem")
            self._bus_name = bus_name

            # 注册到 StatusNotifierWatcher
            self._register_to_watcher()

        def _register_to_watcher(self):
            try:
                watcher = self._bus.get_object(
                    "org.kde.StatusNotifierWatcher",
                    "/StatusNotifierWatcher"
                )
                watcher_iface = dbus.Interface(watcher, "org.kde.StatusNotifierWatcher")
                watcher_iface.RegisterStatusNotifierItem(self._bus_name.get_name())
            except Exception as e:
                logger.warning(f"注册 StatusNotifierWatcher 失败: {e}")

        # ---- D-Bus 属性 ----
        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
        def Get(self, iface, prop):
            return self._get_property(iface, prop)

        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return {p: self._get_property(iface, p) for p in [
                "Category", "Id", "Title", "Status", "WindowId",
                "IconName", "IconPixmap", "ItemIsMenu", "Menu"
            ]}

        def _get_property(self, iface, prop):
            if iface != "org.kde.StatusNotifierItem":
                return None
            props = {
                "Category": "ApplicationStatus",
                "Id": self._app_id,
                "Title": self._title,
                "Status": "Active",
                "WindowId": 0,
                "IconName": "",
                "IconPixmap": dbus.Array([
                    dbus.Struct((32, 32, dbus.ByteArray(self._icon_data)), signature="(iiay)")
                ], signature="(iiay)"),
                "ItemIsMenu": dbus.Boolean(False),
                "Menu": dbus.ObjectPath("/NO_DBUSMENU"),
            }
            return props.get(prop)

        # ---- D-Bus 方法 ----
        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def Activate(self, x, y):
            """左键单击 - 激活窗口"""
            self._on_activate()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def ContextMenu(self, x, y):
            """右键菜单"""
            self._on_context_menu(x, y)

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii", out_signature="")
        def SecondaryActivate(self, x, y):
            """中键点击 - 等同于左键"""
            self._on_activate()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="is", out_signature="")
        def Scroll(self, delta, orientation):
            pass

        def run(self):
            """在后台线程启动 GLib 事件循环"""
            self._loop = GLib.MainLoop()
            self._loop.run()

        def stop(self):
            """停止托盘图标"""
            if self._loop:
                self._loop.quit()
                self._loop = None
"""
@2026-07-05 gen by tea_agent, Helper classes for TkGUI
"""

from html.parser import HTMLParser
import logging

logger = logging.getLogger(__name__)

class _TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = False

    def handle_starttag(self, tag, attrs):
        self.result = True

    def handle_endtag(self, tag):
        pass

    def get_result(self):
        return self.result

try:
    import dbus
    import dbus.service
    HAS_DBUS = True
except ImportError:
    HAS_DBUS = False

if HAS_DBUS:
    class StatusNotifierItemDBus(dbus.service.Object):
        """StatusNotifierItem D-Bus 服务，替代 pystray，原生兼容 KDE Plasma 6"""
        def __init__(self, app_id, title, icon_pixmap_ar32, on_activate, on_context_menu):
            self.app_id = app_id
            self.title = title
            self.icon_pixmap_ar32 = icon_pixmap_ar32
            self.on_activate = on_activate
            self.on_context_menu = on_context_menu
            bus = dbus.SessionBus()
            bus_name = dbus.service.BusName("org.kde.StatusNotifierItem", bus=bus)
            super().__init__(bus_name, f"/StatusNotifierItem")
            self._register_to_watcher()

        def _register_to_watcher(self):
            pass

        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="ss", out_signature="v")
        def Get(self, iface, prop):
            return self._get_property(iface, prop)

        @dbus.service.method("org.freedesktop.DBus.Properties", in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):
            return {}

        def _get_property(self, iface, prop):
            return None

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii")
        def Activate(self, x, y):
            if self.on_activate: self.on_activate()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii")
        def ContextMenu(self, x, y):
            if self.on_context_menu: self.on_context_menu()

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii")
        def SecondaryActivate(self, x, y):
            pass

        @dbus.service.method("org.kde.StatusNotifierItem", in_signature="ii")
        def Scroll(self, delta, orientation):
            pass
else:
    class StatusNotifierItemDBus:
        pass

"""
تولید تصویر از رابط کاربری (برای بازبینی ظاهر بدون باز کردن پنجره).
اجرا: python tools/screenshot.py [output.png]
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from PySide6.QtCore import Qt, QTimer                                # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase                        # noqa: E402
from PySide6.QtWidgets import QApplication                            # noqa: E402

import app.core.vpn as vpn                                            # noqa: E402

LIVE = "--live" in sys.argv

# حالت پیش‌فرض: کنترلر خاموش می‌شود تا تصویر سریع و قطعی باشد.
# با --live خود برنامه واقعی اجرا و پس از اتصال عکس گرفته می‌شود.
if not LIVE:
    vpn.VPNController.start = lambda self: None
    vpn.VPNController.stop = lambda self: None
    vpn.VPNController.wait = lambda self, *a: True
    vpn.VPNController.request_disconnect = lambda self: None

from app.ui.main_window import MainWindow                             # noqa: E402
from main import _load_palette                                        # noqa: E402


# داده‌ی نمونه برای تصویربرداری — عمداً از IPهای مستندسازی (TEST-NET) استفاده
# می‌شود تا هیچ سرور واقعی‌ای در تصویر یا مخزن نیاید.
DEMO_NODES = [
    {"id": "a1", "protocol": "vless", "server": "192.0.2.10", "port": 443,
     "remark": "🇩🇪 DE-Frankfurt | نمونه", "latency": 640,
     "speed_kbps": 12840, "working": True},
    {"id": "a2", "protocol": "hysteria2", "server": "192.0.2.20", "port": 8443,
     "remark": "🇫🇮 FI-Helsinki | Mehras", "latency": 812,
     "speed_kbps": 9720, "working": True},
    {"id": "a3", "protocol": "trojan", "server": "198.51.100.30", "port": 443,
     "remark": "🇨🇦 CA-Montreal | نمونه", "latency": 935,
     "speed_kbps": 5400, "working": True},
    {"id": "a4", "protocol": "vless", "server": "198.51.100.40", "port": 8443,
     "remark": "🇳🇱 NL-Amsterdam | Reality", "latency": 1180,
     "speed_kbps": 6100, "working": True},
    {"id": "a5", "protocol": "vmess", "server": "203.0.113.50", "port": 2053,
     "remark": "🇺🇸 US-Ashburn | ws+tls", "latency": 1490,
     "speed_kbps": None, "working": True},
    {"id": "a6", "protocol": "ss", "server": "203.0.113.60", "port": 15731,
     "remark": "🇹🇷 TR-Istanbul", "latency": 1844,
     "speed_kbps": 2100, "working": True},
    {"id": "a7", "protocol": "vless", "server": "192.0.2.70", "port": 8443,
     "remark": "🇸🇬 SG-Singapore", "latency": None,
     "speed_kbps": None, "working": False},
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else ROOT / "assets" / "ui-preview.png"
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.RightToLeft)
    fonts = set()
    for f in (ROOT / "fonts").glob("*.ttf"):
        fid = QFontDatabase.addApplicationFont(str(f))
        fonts.update(QFontDatabase.applicationFontFamilies(fid))
    app.setFont(QFont("Vazirmatn" if "Vazirmatn" in fonts else "Segoe UI", 10))
    _load_palette(app)

    win = MainWindow()
    win.resize(1120, 780)
    win.show()

    def shoot():
        win.grab().save(str(out))
        print("saved:", out)
        app.quit()

    if LIVE:
        # خود برنامه واقعی: منتظر اتصال یا حداکثر ۱۲۰ ثانیه
        win.settings["set_system_proxy"] = False
        win.controller.update_settings(win.settings)
        deadline = [0]

        def poll():
            deadline[0] += 1
            if win.current or deadline[0] > 120:
                QTimer.singleShot(6000, shoot)
            else:
                QTimer.singleShot(1000, poll)

        print("live mode: waiting for connection...")
        QTimer.singleShot(1500, poll)
    elif "--dialogs" in sys.argv:
        from app.ui.main_window import SettingsDialog, TelegramDialog

        settings_dlg = SettingsDialog(win.settings, win)
        settings_dlg.show()
        telegram_dlg = TelegramDialog(win.settings["mixed_port"], False, win)
        telegram_dlg.show()

        def shoot_dialogs():
            settings_dlg.grab().save(str(out.parent / "ui-settings.png"))
            telegram_dlg.grab().save(str(out.parent / "ui-telegram.png"))
            print("saved dialogs to", out.parent)
            app.quit()

        QTimer.singleShot(900, shoot_dialogs)
    else:
        win.on_nodes(DEMO_NODES)
        win.on_connected(DEMO_NODES[0])
        win.on_stats({"rate_down": 1_240_000, "rate_up": 96_000,
                      "total_down": 734_003_200, "total_up": 41_000_000,
                      "latency": 640, "uptime": 754})
        win.on_targets({"تلگرام": {"ok": True, "latency": 712},
                        "اینستاگرام": {"ok": True, "latency": 845},
                        "یوتیوب": {"ok": True, "latency": 690}})
        for i in range(60):
            win.graph.push(abs(60 - i) * 18_000 + (i % 7) * 26_000)
        win.on_status("متصل به DE-Frankfurt | @itsTiTANVPN")
        QTimer.singleShot(900, shoot)
    app.exec()


if __name__ == "__main__":
    main()

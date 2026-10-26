"""
نقطه‌ی ورود «وی پی ان شخصی مهراس».

اجرا:  python main.py   (یا دوبار کلیک روی run.bat)
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_crash_log(exc_info):
    try:
        from app.config import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "startup_error.log", "w", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(*exc_info)))
    except Exception:
        pass


def _load_fonts(app):
    from PySide6.QtGui import QFont, QFontDatabase
    from app.config import FONTS_DIR

    families = set()
    if FONTS_DIR.exists():
        for path in sorted(FONTS_DIR.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid >= 0:
                families.update(QFontDatabase.applicationFontFamilies(fid))
    family = "Vazirmatn" if "Vazirmatn" in families else (
        next(iter(families), None) or "Segoe UI")
    app.setFont(QFont(family, 10))


def _load_icon(app):
    from PySide6.QtGui import QIcon
    from app.config import ASSETS_DIR
    for name in ("icon.ico", "icon.png"):
        path = ASSETS_DIR / name
        if path.exists():
            app.setWindowIcon(QIcon(str(path)))
            return


def _load_palette(app):
    """پالت تیره‌ی یکنواخت — Fusion بدون آن، نواحی داخلی جدول/دیالوگ سفید می‌شوند."""
    from PySide6.QtGui import QColor, QPalette
    from app.ui.theme import COLORS

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(COLORS["bg"]))
    pal.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    pal.setColor(QPalette.Base, QColor(COLORS["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(COLORS["surface2"]))
    pal.setColor(QPalette.Text, QColor(COLORS["text"]))
    pal.setColor(QPalette.Button, QColor(COLORS["surface2"]))
    pal.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(COLORS["surface2"]))
    pal.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(COLORS["text_faint"]))
    pal.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor(COLORS["accent2"]))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(COLORS["text_faint"]))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(COLORS["text_faint"]))
    app.setPalette(pal)


def main():
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox

        from app.config import APP_NAME
        from app.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        app.setStyle("Fusion")                 # رندر یکنواخت QSS روی ویندوز
        app.setLayoutDirection(Qt.RightToLeft)
        _load_fonts(app)
        _load_palette(app)
        _load_icon(app)

        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except Exception:
        _write_crash_log(sys.exc_info())
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None, "خطای راه‌اندازی",
                "برنامه با خطا مواجه شد.\nجزئیات در data/logs/startup_error.log")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()

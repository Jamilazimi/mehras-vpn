"""
پنجره‌ی اصلی «وی پی ان شخصی مهراس».

یک صفحه‌ی ساده و تمیز: دکمه‌ی بزرگ اتصال، آمار زنده، وضعیت سه سایت هدف و
فهرست گره‌های سالم. همه‌ی کارهای سنگین در کنترلر (رشته‌ی جدا) انجام می‌شود.
"""
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSizePolicy, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app.config import (APP_NAME, APP_VERSION, ASSETS_DIR, BASE_DIR,
                        DEFAULT_SETTINGS)
from app.core import engine, selector, sources
from app.core.vpn import VPNController
from app.ui.theme import COLORS, build_qss
from app.ui.widgets import (Card, Divider, PowerButton, SiteChip, SpeedGraph,
                            StatCard, StatusBar, fmt_bytes, fmt_speed, fmt_uptime)
from app.utils.logger import log

FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
MAX_ROWS = 400
LRM = "\u200e"

PROTOCOL_LABEL = {
    "vless": "VLESS", "vmess": "VMess", "trojan": "Trojan", "ss": "SS",
    "hysteria2": "Hysteria2", "tuic": "TUIC", "anytls": "AnyTLS",
}

STATE_TEXT = {
    "idle": ("آماده‌ی اتصال", "برای شروع، دکمه‌ی وسط را بزنید"),
    "connecting": ("در حال اتصال...", "لطفاً چند لحظه صبر کنید"),
    "connected": ("متصل هستید", ""),
    "scanning": ("در حال جستجو...", "گره‌های سالم در حال پیدا شدن هستند"),
    "error": ("خطا", ""),
}


def flag_from_remark(remark: str) -> str:
    """کد کشور از پرچم/نام سرور — ویندوز پرچم ایموجی را رندر نمی‌کند،
    بنابراین همان حروف دو‌حرفی (DE, NL, ...) را نشان می‌دهیم."""
    remark = remark or ""
    m = FLAG_RE.search(remark)
    if m:
        return "".join(chr(ord(ch) - 0x1F1E6 + ord("A")) for ch in m.group(0))
    m2 = re.search(r"\b([A-Z]{2})\b", remark)
    return m2.group(1) if m2 else "—"


def display_name(text: str, limit: int = 60) -> str:
    """نام گره برای نمایش: پرچم‌ها حذف می‌شوند و اگر با حرف لاتین شروع شود
    LRM می‌گیرد تا «@channel» و «US-...» در متن راست‌به‌چپ جابه‌جا نشود."""
    text = FLAG_RE.sub("", text or "")
    text = re.sub(r"\s{2,}", " ", text).strip(" -|،")
    text = text or "سرور بدون نام"
    if ord(text[0]) < 0x0590:                 # شروع با حرف/نشانه‌ی لاتین
        text = LRM + text
    return text[:limit]


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = dict(settings)
        self.setWindowTitle("تنظیمات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("تنظیمات مهراس")
        title.setObjectName("appTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("پروکسی سیستم و مرورگر (ساده)", "proxy")
        self.cmb_mode.addItem("حالت کامل TUN — کل سیستم (نیازمند مدیر)", "tun")
        idx = 1 if self.settings.get("mode") == "tun" else 0
        self.cmb_mode.setCurrentIndex(idx)
        form.addRow("حالت اتصال:", self.cmb_mode)

        self.chk_sysproxy = QCheckBox("اعمال خودکار پروکسی روی ویندوز")
        self.chk_sysproxy.setChecked(bool(self.settings.get("set_system_proxy", True)))
        form.addRow("", self.chk_sysproxy)

        self.chk_bypass = QCheckBox("سایت‌های ایرانی مستقیم باز شوند (سریع‌تر)")
        self.chk_bypass.setChecked(bool(self.settings.get("bypass_iran", True)))
        form.addRow("", self.chk_bypass)

        self.chk_auto = QCheckBox("اتصال خودکار هنگام اجرا")
        self.chk_auto.setChecked(bool(self.settings.get("auto_connect", True)))
        form.addRow("", self.chk_auto)

        self.chk_switch = QCheckBox("جابه‌جایی خودکار به گره‌ی بهتر")
        self.chk_switch.setChecked(bool(self.settings.get("auto_switch", True)))
        form.addRow("", self.chk_switch)

        self.spin_health = QSpinBox()
        self.spin_health.setRange(10, 300)
        self.spin_health.setSuffix(" ثانیه")
        self.spin_health.setValue(int(self.settings.get("health_check_seconds", 20)))
        form.addRow("فاصله‌ی بررسی سلامت:", self.spin_health)

        self.spin_refresh = QSpinBox()
        self.spin_refresh.setRange(10, 720)
        self.spin_refresh.setSuffix(" دقیقه")
        self.spin_refresh.setValue(int(self.settings.get("refresh_interval_minutes", 60)))
        form.addRow("فاصله‌ی اسکن دوره‌ای:", self.spin_refresh)

        self.spin_nodes = QSpinBox()
        self.spin_nodes.setRange(40, 400)
        self.spin_nodes.setSingleStep(20)
        self.spin_nodes.setValue(int(self.settings.get("max_test_nodes", 180)))
        form.addRow("حداکثر گره برای تست:", self.spin_nodes)

        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65000)
        self.spin_port.setValue(int(self.settings.get("mixed_port", 10808)))
        form.addRow("پورت محلی:", self.spin_port)

        root.addLayout(form)

        # --- اشتراک/کانفیگ شخصی ---
        sub_title = QLabel("اشتراک یا کانفیگ شخصی (اختیاری)")
        sub_title.setObjectName("sectionTitle")
        root.addWidget(sub_title)
        sub_hint = QLabel(
            "هر خط یک آدرس اشتراک (https://…) یا یک لینک کانفیگ "
            "(vless://، trojan://، ss://، hysteria2://…). این گره‌ها اول تست "
            "می‌شوند و اولویت بالاتری دارند.")
        sub_hint.setWordWrap(True)
        sub_hint.setStyleSheet(f"color:{COLORS['text_faint']}; font-size:11px;")
        root.addWidget(sub_hint)
        self.txt_subscriptions = QPlainTextEdit()
        self.txt_subscriptions.setPlaceholderText(
            "https://example.com/subscription\nvless://…")
        self.txt_subscriptions.setFixedHeight(86)
        self.txt_subscriptions.setPlainText("\n".join(sources.load_custom_lines()))
        root.addWidget(self.txt_subscriptions)

        hint = QLabel(
            "در حالت TUN همه‌ی برنامه‌ها (از جمله تلگرام) بدون تنظیم اضافه عبور "
            "می‌کنند، اما ویندوز اجازه‌ی مدیر می‌خواهد. در حالت پروکسی، تلگرام را "
            "با دکمه‌ی «تلگرام» در صفحه‌ی اصلی تنظیم کنید.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{COLORS['text_faint']}; font-size:11.5px;")
        root.addWidget(hint)

        if not engine.is_admin():
            warn = QLabel("این برنامه الان با دسترسی مدیر اجرا نشده است؛ حالت TUN "
                          "فعال نخواهد شد (به‌طور خودکار به پروکسی برمی‌گردد).")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color:{COLORS['warning']}; font-size:11px;")
            root.addWidget(warn)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("ذخیره")
        btns.button(QDialogButtonBox.Cancel).setText("انصراف")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def values(self) -> dict:
        out = dict(self.settings)
        out["mode"] = self.cmb_mode.currentData()
        out["set_system_proxy"] = self.chk_sysproxy.isChecked()
        out["bypass_iran"] = self.chk_bypass.isChecked()
        out["auto_connect"] = self.chk_auto.isChecked()
        out["auto_switch"] = self.chk_switch.isChecked()
        out["health_check_seconds"] = self.spin_health.value()
        out["refresh_interval_minutes"] = self.spin_refresh.value()
        out["max_test_nodes"] = self.spin_nodes.value()
        out["mixed_port"] = self.spin_port.value()
        return out

    def subscriptions(self) -> list:
        return [line.strip() for line in
                self.txt_subscriptions.toPlainText().splitlines() if line.strip()]


class TelegramDialog(QDialog):
    """راهنمای کوتاه اتصال تلگرام + کپی آدرس پروکسی + اجرای تلگرام."""

    def __init__(self, port, tun_active, parent=None):
        super().__init__(parent)
        self.port = int(port)
        self.setWindowTitle("اتصال تلگرام")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(470)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        title = QLabel("اتصال تلگرام دسکتاپ")
        title.setObjectName("appTitle")
        root.addWidget(title)

        if tun_active:
            tip = QLabel("حالت TUN فعال است؛ تلگرام بدون هیچ تنظیمی خودکار عبور "
                         "می‌کند. اگر باز نشد، یک بار تلگرام را ببندید و باز کنید.")
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color:{COLORS['success']};")
            root.addWidget(tip)
        else:
            tip = QLabel("تلگرام از پروکسی ویندوز پیروی نمی‌کند و باید یک بار "
                         "دستی تنظیم شود:")
            tip.setWordWrap(True)
            root.addWidget(tip)

        address_card = Card(soft=True)
        addr_lay = QHBoxLayout(address_card)
        addr_lay.setContentsMargins(14, 10, 14, 10)
        addr_lay.setSpacing(10)
        addr = QLabel(f"127.0.0.1 : {self.port}")
        addr.setStyleSheet("font-size:17px; font-weight:800;")
        addr.setTextInteractionFlags(Qt.TextSelectableByMouse)
        addr_lay.addWidget(addr)
        addr_lay.addStretch()
        btn_copy = QPushButton("کپی آدرس")
        btn_copy.setObjectName("primary")
        btn_copy.clicked.connect(self.copy_address)
        addr_lay.addWidget(btn_copy)
        root.addWidget(address_card)

        steps = QLabel(
            "۱) در تلگرام: Settings ← Advanced ← Connection type\n"
            "۲) گزینه‌ی «TCP with custom proxy» را انتخاب کنید\n"
            "۳) نوع: SOCKS5     Host: 127.0.0.1     Port: "
            f"{self.port}\n"
            "۴) Save؛ کنار نام شما باید نشان اتصال ظاهر شود")
        steps.setStyleSheet(f"color:{COLORS['text_dim']}; line-height:170%;")
        steps.setWordWrap(True)
        root.addWidget(steps)

        row = QHBoxLayout()
        btn_open = QPushButton("باز کردن تلگرام")
        btn_open.setObjectName("ghost")
        btn_open.clicked.connect(self.open_telegram)
        row.addWidget(btn_open)
        row.addStretch()
        btn_close = QPushButton("باشه")
        btn_close.setObjectName("primary")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        root.addLayout(row)

    def copy_address(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(f"127.0.0.1:{self.port}")
        self.setWindowTitle("اتصال تلگرام — آدرس کپی شد ✓")

    def open_telegram(self):
        import os
        import subprocess
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Telegram Desktop" / "Telegram.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Telegram Desktop" / "Telegram.exe",
            Path("C:/Program Files/Telegram Desktop/Telegram.exe"),
        ]
        for path in candidates:
            if path.exists():
                try:
                    subprocess.Popen([str(path)])
                    return
                except Exception:
                    continue
        QMessageBox.information(self, "تلگرام",
                                "فایل تلگرام پیدا نشد. برنامه را دستی باز کنید و "
                                "مراحل بالا را انجام دهید.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = selector.load_settings()
        self.nodes = []
        self.current = None
        self._filter = "working"
        self._search = ""

        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(1120, 780)
        self.setMinimumSize(960, 660)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(build_qss())

        icon_path = ASSETS_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()

        self.controller = VPNController(self.settings, self)
        self._wire()
        self.controller.start()

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._connected_at = 0.0

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root_widget = QWidget()
        root_widget.setObjectName("root")
        self.setCentralWidget(root_widget)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(14)

        root.addLayout(self._build_header())

        middle = QHBoxLayout()
        middle.setSpacing(14)
        middle.addWidget(self._build_connection_card())
        middle.addWidget(self._build_stats_card(), 1)
        root.addLayout(middle, 0)

        root.addWidget(self._build_servers_card(), 1)
        root.addLayout(self._build_footer())

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(12)

        logo = QLabel("م")
        logo.setFixedSize(46, 46)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {COLORS['accent']}, stop:1 {COLORS['accent2']});"
            "border-radius: 13px; color:#fff; font-size:22px; font-weight:900;")
        row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("appTitle")
        sub = QLabel("اتصال امن و پرسرعت به اینترنت آزاد")
        sub.setObjectName("appSub")
        titles.addWidget(t)
        titles.addWidget(sub)
        row.addLayout(titles)
        row.addStretch()

        self.lbl_engine = QLabel("")
        self.lbl_engine.setObjectName("appSub")
        row.addWidget(self.lbl_engine)

        self.btn_guide = QPushButton("راهنمای استفاده")
        self.btn_guide.setObjectName("ghost")
        self.btn_guide.clicked.connect(self.on_open_guide)
        row.addWidget(self.btn_guide)

        self.btn_settings = QPushButton("⚙  تنظیمات")
        self.btn_settings.setObjectName("ghost")
        self.btn_settings.clicked.connect(self.on_settings)
        row.addWidget(self.btn_settings)
        return row

    def _build_connection_card(self):
        card = Card()
        card.setFixedWidth(330)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignTop)

        self.power = PowerButton()
        self.power.clicked.connect(self.on_power_clicked)
        wrapper = QHBoxLayout()
        wrapper.addStretch()
        wrapper.addWidget(self.power)
        wrapper.addStretch()
        lay.addLayout(wrapper)

        self.lbl_state = QLabel(STATE_TEXT["idle"][0])
        self.lbl_state.setObjectName("heroState")
        self.lbl_state.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_state)

        self.lbl_sub = QLabel(STATE_TEXT["idle"][1])
        self.lbl_sub.setObjectName("heroSub")
        self.lbl_sub.setAlignment(Qt.AlignCenter)
        self.lbl_sub.setWordWrap(True)
        lay.addWidget(self.lbl_sub)

        lay.addSpacing(4)
        self.btn_action = QPushButton("اتصال هوشمند")
        self.btn_action.setObjectName("primary")
        self.btn_action.setMinimumHeight(44)
        self.btn_action.clicked.connect(self.on_action_clicked)
        lay.addWidget(self.btn_action)

        secondary = QHBoxLayout()
        secondary.setSpacing(8)
        self.btn_scan = QPushButton("↻  اسکن تازه")
        self.btn_scan.setObjectName("ghost")
        self.btn_scan.setMinimumHeight(38)
        self.btn_scan.clicked.connect(self.on_refresh)
        secondary.addWidget(self.btn_scan)

        self.btn_telegram = QPushButton("تلگرام")
        self.btn_telegram.setObjectName("ghost")
        self.btn_telegram.setMinimumHeight(38)
        self.btn_telegram.setToolTip("تنظیم پروکسی تلگرام دسکتاپ")
        self.btn_telegram.clicked.connect(self.on_telegram_help)
        secondary.addWidget(self.btn_telegram)
        lay.addLayout(secondary)

        self.lbl_mode = QLabel("")
        self.lbl_mode.setObjectName("appSub")
        self.lbl_mode.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_mode)
        return card

    def _build_stats_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("وضعیت اتصال")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch()
        self.lbl_total_traffic = QLabel("حجم امروز: ۰")
        self.lbl_total_traffic.setObjectName("appSub")
        head.addWidget(self.lbl_total_traffic)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.stat_ping = StatCard("پینگ", "—", "ms")
        self.stat_down = StatCard("دانلود", "—", "")
        self.stat_up = StatCard("آپلود", "—", "")
        self.stat_time = StatCard("مدت اتصال", "—", "")
        grid.addWidget(self.stat_ping, 0, 0)
        grid.addWidget(self.stat_down, 0, 1)
        grid.addWidget(self.stat_up, 0, 2)
        grid.addWidget(self.stat_time, 0, 3)
        lay.addLayout(grid)

        self.graph = SpeedGraph()
        lay.addWidget(self.graph, 1)

        lay.addWidget(Divider())
        sites_head = QHBoxLayout()
        st = QLabel("دسترسی سایت‌ها از داخل تونل")
        st.setObjectName("sectionTitle")
        sites_head.addWidget(st)
        sites_head.addStretch()
        lay.addLayout(sites_head)

        sites_row = QHBoxLayout()
        sites_row.setSpacing(8)
        self.chips = {}
        for target in self.settings.get("target_sites", []):
            chip = SiteChip(target.get("name", ""))
            self.chips[target.get("name", "")] = chip
            sites_row.addWidget(chip)
        lay.addLayout(sites_row)
        return card

    def _build_servers_card(self):
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("سرورها")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        self.lbl_count = QLabel("۰ گره سالم")
        self.lbl_count.setObjectName("appSub")
        head.addWidget(self.lbl_count)
        head.addStretch()

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("جستجو در سرورها...")
        self.txt_search.setFixedWidth(180)
        self.txt_search.textChanged.connect(self.on_search)
        head.addWidget(self.txt_search)

        self.cmb_filter = QComboBox()
        self.cmb_filter.addItem("فقط سالم", "working")
        self.cmb_filter.addItem("همه", "all")
        self.cmb_filter.setFixedWidth(110)
        self.cmb_filter.currentIndexChanged.connect(self.on_filter)
        head.addWidget(self.cmb_filter)

        self.btn_refresh = QPushButton("به‌روزرسانی")
        self.btn_refresh.setObjectName("ghost")
        self.btn_refresh.clicked.connect(lambda: self.on_refresh(deep=True))
        head.addWidget(self.btn_refresh)
        lay.addLayout(head)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["وضعیت", "نام سرور", "پروتکل", "تأخیر", "سرعت", "کشور"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSortingEnabled(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setHighlightSections(False)
        for col, width in ((0, 96), (2, 104), (3, 88), (4, 116), (5, 68)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self.on_row_activated)
        self.table.setToolTip("برای اتصال روی سرور دوبار کلیک کنید")
        lay.addWidget(self.table, 1)
        return card

    def _build_footer(self):
        row = QHBoxLayout()
        row.setSpacing(12)
        self.statusbar = StatusBar()
        row.addWidget(self.statusbar, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(220)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        row.addWidget(self.progress)
        return row

    # ------------------------------------------------------------- سیگنال‌ها
    def _wire(self):
        self.controller.status.connect(self.on_status)
        self.controller.progress.connect(self.on_progress)
        self.controller.nodes_updated.connect(self.on_nodes)
        self.controller.connected.connect(self.on_connected)
        self.controller.disconnected.connect(self.on_disconnected)
        self.controller.stats.connect(self.on_stats)
        self.controller.targets.connect(self.on_targets)
        self.controller.error.connect(self.on_error)
        self.controller.state_changed.connect(self.on_state)

        engine_version = engine.version() if engine.is_installed() else ""
        if engine_version:
            engine_version = engine_version.replace("sing-box version", "هسته:")
        self.lbl_engine.setText(engine_version or "هسته نصب نشده")
        self._update_mode_label()

        self._reset_sites()
        self.on_state("idle")

    def _update_mode_label(self):
        mode = self.settings.get("mode", "proxy")
        port = self.settings.get("mixed_port", 10808)
        if mode == "tun":
            self.lbl_mode.setText("حالت کامل TUN (کل سیستم)")
        else:
            self.lbl_mode.setText(f"پروکسی سیستم • SOCKS5 127.0.0.1:{port}")

    # ------------------------------------------------------------- رویدادها
    def on_state(self, state):
        # وسط اسکن پس‌زمینه، اگر متصل هستیم وضعیت «متصل» را حفظ کن
        if state == "scanning" and self.current:
            return
        self.power.set_state("connecting" if state in ("connecting", "scanning")
                             else ("connected" if state == "connected" else "idle"))
        text, sub = STATE_TEXT.get(state, ("", ""))
        self.lbl_state.setText(text)
        if state != "connected":
            self.lbl_sub.setText(sub)
        if state == "connected":
            self.btn_action.setText("قطع اتصال")
            self.btn_action.setObjectName("danger")
        else:
            self.btn_action.setText("اتصال هوشمند")
            self.btn_action.setObjectName("primary")
        self.btn_action.style().unpolish(self.btn_action)
        self.btn_action.style().polish(self.btn_action)
        if state == "idle":
            self._connected_at = 0.0

    def on_status(self, message):
        tone = "dim"
        low = message
        if any(k in low for k in ("متصل", "سالم")):
            tone = "ok"
        if any(k in low for k in ("خطا", "ناموفق", "نشد")):
            tone = "err"
        if any(k in low for k in ("در حال", "شروع", "تست", "دریافت", "بررسی")):
            tone = "busy"
        self.statusbar.set_text(message, tone)

    def on_error(self, message):
        self.statusbar.set_text(f"⚠ {message}", "err")

    def on_progress(self, phase, cur, total):
        total = max(1, int(total))
        value = int(min(100, cur * 100 / total))
        self.progress.setValue(value)
        if phase and cur < total:
            self.statusbar.set_text(f"{phase} — {cur}/{total}", "busy")

    def on_nodes(self, nodes):
        self.nodes = nodes or []
        self._render_table()

    def on_connected(self, node):
        self.current = node
        self._connected_at = time.time()
        self.on_state("connected")
        remark = display_name(node.get("remark") or "", 46)
        self.lbl_sub.setText(remark)
        if node.get("latency"):
            self.stat_ping.set_value(int(node["latency"]), "ms")
        self.statusbar.set_text(
            f"متصل به {node.get('protocol', '').upper()} • {node.get('server')}",
            "ok")
        self._render_table()

    def on_disconnected(self):
        self.current = None
        self._connected_at = 0.0
        self.on_state("idle")
        self.stat_ping.set_value("—", "ms")
        for name, chip in self.chips.items():
            chip.set_state(None)
        self.graph.push(0)
        self._render_table()

    def on_stats(self, data):
        rate_down = data.get("rate_down", 0)
        rate_up = data.get("rate_up", 0)
        self.stat_down.set_value(fmt_speed(rate_down))
        self.stat_up.set_value(fmt_speed(rate_up))
        self.graph.push(rate_down)
        if data.get("latency"):
            self.stat_ping.set_value(int(data["latency"]), "ms")
        total = (data.get("total_down") or 0) + (data.get("total_up") or 0)
        self.lbl_total_traffic.setText(f"مصرف این اتصال: {fmt_bytes(total)}")

    def on_targets(self, result):
        for name, chip in self.chips.items():
            info = result.get(name) or {}
            if not info:
                chip.set_state(None)
            else:
                chip.set_state(bool(info.get("ok")), info.get("latency"))

    def _reset_sites(self):
        for chip in self.chips.values():
            chip.set_state(None)

    def _tick_clock(self):
        if self._connected_at:
            self.stat_time.set_value(fmt_uptime(time.time() - self._connected_at))
        if self.current:
            self.lbl_sub.setText(display_name(self.current.get("remark") or "", 46))

    # --------------------------------------------------------------- جدول
    def on_filter(self):
        self._filter = self.cmb_filter.currentData()
        self._render_table()

    def on_search(self):
        self._search = self.txt_search.text().strip().lower()
        self._render_table()

    def _render_table(self):
        nodes = self.nodes
        if self._filter == "working":
            nodes = [n for n in nodes if n.get("working")]
        if self._search:
            nodes = [n for n in nodes
                     if self._search in (n.get("remark") or "").lower()
                     or self._search in (n.get("server") or "").lower()
                     or self._search in (n.get("protocol") or "").lower()]
        shown = nodes[:MAX_ROWS]
        working = sum(1 for n in self.nodes if n.get("working"))
        self.lbl_count.setText(
            f"سالم {LRM}{working}{LRM} • کل {LRM}{len(self.nodes)}")

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        for node in shown:
            row = self.table.rowCount()
            self.table.insertRow(row)
            ok = bool(node.get("working"))
            status = QTableWidgetItem("● متصل" if (self.current and
                                                  node.get("id") == self.current.get("id"))
                                      else ("● سالم" if ok else "● ناموفق"))
            color = COLORS["success"] if ok else COLORS["text_faint"]
            if self.current and node.get("id") == self.current.get("id"):
                color = COLORS["accent2"]
            status.setForeground(QColor(color))
            self.table.setItem(row, 0, status)

            name = display_name(node.get("remark")
                                or f"{node.get('server')}:{node.get('port')}", 60)
            name_item = QTableWidgetItem(name)
            name_item.setToolTip(f"{node.get('server')}:{node.get('port')}\n"
                                 f"{node.get('protocol', '').upper()}")
            name_item.setData(Qt.UserRole, node.get("id"))
            self.table.setItem(row, 1, name_item)
            proto = PROTOCOL_LABEL.get(node.get("protocol"), node.get("protocol") or "")
            self.table.setItem(row, 2, QTableWidgetItem(f"{LRM}{proto}"))
            lat = node.get("latency")
            lat_item = QTableWidgetItem(f"{LRM}{int(lat)} ms" if lat else "—")
            if lat:
                lat_item.setForeground(QColor(
                    COLORS["success"] if lat < 900 else
                    COLORS["warning"] if lat < 1800 else COLORS["danger"]))
            self.table.setItem(row, 3, lat_item)
            speed = node.get("speed_kbps")
            self.table.setItem(row, 4, QTableWidgetItem(
                f"{LRM}{int(speed)} kbps" if speed else "—"))
            self.table.setItem(row, 5, QTableWidgetItem(
                flag_from_remark(node.get("remark") or "")))
        self.table.setUpdatesEnabled(True)

        if not shown:
            self.statusbar.set_text(
                "سروری برای نمایش نیست — «اسکن گره‌های تازه» را بزنید.", "warn")

    def on_row_activated(self, index):
        item = self.table.item(index.row(), 1)
        if not item:
            return
        node_id = item.data(Qt.UserRole)
        node = next((n for n in self.nodes if n.get("id") == node_id), None)
        if node:
            self.statusbar.set_text(f"در حال اتصال به {node.get('remark', '')[:40]}...",
                                    "busy")
            self.controller.request_connect(node)

    # --------------------------------------------------------------- دکمه‌ها
    def on_power_clicked(self):
        if self.current:
            self.controller.request_disconnect()
        else:
            self.controller.request_connect_best()

    def on_action_clicked(self):
        if self.current:
            self.controller.request_disconnect()
        else:
            self.controller.request_connect_best()

    def on_refresh(self, deep=False):
        self.statusbar.set_text("شروع اسکن تازه...", "busy")
        self.controller.request_refresh(deep=bool(deep))

    def on_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.Accepted:
            new = dlg.values()
            old_subs = sources.load_custom_lines()
            new_subs = dlg.subscriptions()
            if new_subs != old_subs:
                sources.save_custom_lines(new_subs)
            self.settings = selector.settings_with_defaults(new)
            selector.save_settings(self.settings)
            self.controller.update_settings(self.settings)
            self._update_mode_label()
            if new_subs != old_subs:
                self.statusbar.set_text(
                    "اشتراک شخصی ذخیره شد — شروع اسکن با گره‌های شما...", "ok")
                self.controller.request_refresh(deep=False)
            else:
                self.statusbar.set_text("تنظیمات ذخیره شد.", "ok")

    def on_open_guide(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        for candidate in (BASE_DIR / "docs" / "راهنمای-مهراس.pdf",
                          BASE_DIR / "docs" / "mehras-guide.pdf"):
            if candidate.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                return
        QMessageBox.information(
            self, "راهنما",
            "فایل راهنما در پوشه docs پیدا نشد.\n"
            "می‌توانید از دکمه‌ی «تلگرام» در همین صفحه، تنظیمات لازم را ببینید.")

    def on_telegram_help(self):
        port = self.settings.get("mixed_port", 10808)
        tun_active = engine.is_tun_active()
        TelegramDialog(port, tun_active, self).exec()

    # --------------------------------------------------------------- خروج
    def closeEvent(self, event):
        try:
            self.controller.stop()
            self.controller.request_disconnect()
            self.controller.wait(9000)
        except Exception as e:
            log.warning(f"controller shutdown: {e}")
        try:
            engine.stop()
        except Exception:
            pass
        try:
            from app.utils import system_proxy
            system_proxy.clear_proxy()
        except Exception:
            pass
        event.accept()
        if self.controller.isRunning():
            log.warning("controller still running at exit")
            import os
            os._exit(0)

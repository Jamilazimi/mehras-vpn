"""
سیستم طراحی «مهراس» — رنگ‌ها، فاصله‌ها و شیت استایل (QSS).

یک تم تیره‌ی آرام و حرفه‌ای (شبیه کلاینت‌های مدرن VPN) با کارت‌های
گرد، تایپوگرافی وزیرمتن و تأکید آبی/فیروزه‌ای.
"""

COLORS = {
    "bg": "#0a0e16",
    "bg2": "#0e1420",
    "surface": "#131a29",
    "surface2": "#182234",
    "surface3": "#1e2a3f",
    "border": "#26344b",
    "border_soft": "#1d2839",
    "text": "#e9effb",
    "text_dim": "#93a3bd",
    "text_faint": "#63748f",
    "accent": "#4c8dff",
    "accent2": "#22d3ee",
    "success": "#2fd47a",
    "danger": "#ff5d6c",
    "warning": "#ffb020",
    "purple": "#a78bfa",
}

RADIUS = 16
FONT_FAMILY = '"Vazirmatn", "Segoe UI", "Segoe UI Emoji", "Segoe UI Symbol", "Tahoma"'


def build_qss(c: dict = None) -> str:
    c = c or COLORS
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {c['text']};
    outline: none;
}}
QWidget#root {{
    background: {c['bg']};
}}
QDialog {{
    background: {c['bg2']};
}}
QLabel {{
    background: transparent;
}}
QLabel#appTitle {{
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.3px;
}}
QLabel#appSub {{
    color: {c['text_faint']};
    font-size: 11.5px;
}}
QLabel#sectionTitle {{
    color: {c['text_dim']};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#heroState {{
    font-size: 26px;
    font-weight: 800;
}}
QLabel#heroSub {{
    color: {c['text_dim']};
    font-size: 13px;
}}
QLabel#statLabel {{
    color: {c['text_faint']};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#statValue {{
    font-size: 19px;
    font-weight: 800;
}}
QLabel#statUnit {{
    color: {c['text_faint']};
    font-size: 11px;
}}

/* ---------- کارت‌ها ---------- */
QFrame#card {{
    background: {c['surface']};
    border: 1px solid {c['border_soft']};
    border-radius: {RADIUS}px;
}}
QFrame#cardSoft {{
    background: {c['surface2']};
    border: 1px solid {c['border_soft']};
    border-radius: 12px;
}}
QFrame#divider {{
    background: {c['border_soft']};
    max-height: 1px;
    border: none;
}}

/* ---------- دکمه‌ها ---------- */
QPushButton {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 11px;
    padding: 9px 16px;
    font-weight: 700;
    color: {c['text']};
}}
QPushButton:hover {{
    background: {c['surface3']};
    border-color: {c['accent']};
}}
QPushButton:pressed {{
    background: {c['surface']};
}}
QPushButton:disabled {{
    color: {c['text_faint']};
    background: {c['surface']};
    border-color: {c['border_soft']};
}}
QPushButton#primary {{
    background: {c['accent']};
    border: none;
    color: #ffffff;
}}
QPushButton#primary:hover {{
    background: #5d99ff;
}}
QPushButton#primary:disabled {{
    background: #2b3a55;
    color: {c['text_faint']};
}}
QPushButton#danger {{
    background: transparent;
    border: 1px solid {c['danger']};
    color: {c['danger']};
}}
QPushButton#danger:hover {{
    background: rgba(255, 93, 108, 0.12);
}}
QPushButton#ghost {{
    background: transparent;
    border: 1px solid {c['border']};
    color: {c['text_dim']};
    font-weight: 600;
}}
QPushButton#ghost:hover {{
    color: {c['text']};
    border-color: {c['accent']};
}}
QPushButton#icon {{
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 6px;
    font-size: 16px;
}}
QPushButton#icon:hover {{
    background: {c['surface3']};
}}

/* ---------- جدول ---------- */
QTableWidget {{
    background: {c['surface']};
    border: none;
    gridline-color: transparent;
    selection-background-color: {c['surface3']};
    selection-color: {c['text']};
    alternate-background-color: {c['bg2']};
    font-size: 12.5px;
}}
QTableWidget::item {{
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid {c['border_soft']};
}}
QTableWidget::item:selected {{
    background: {c['surface3']};
    color: {c['text']};
}}
QTableWidget QTableCornerButton::section {{
    background: {c['surface']};
    border: none;
}}
QHeaderView {{
    background: {c['surface']};
}}
QHeaderView::section {{
    background: {c['surface']};
    color: {c['text_faint']};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {c['border']};
    font-weight: 700;
    font-size: 11.5px;
}}
QTableCornerButton::section {{
    background: transparent;
    border: none;
}}

/* ---------- ورودی‌ها ---------- */
QComboBox, QSpinBox, QLineEdit {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 7px 11px;
    min-height: 20px;
    font-weight: 600;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c['text_dim']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    selection-background-color: {c['accent']};
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QCheckBox {{
    spacing: 8px;
    font-weight: 600;
    color: {c['text_dim']};
}}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid {c['border']};
    background: {c['surface2']};
}}
QCheckBox::indicator:hover {{
    border-color: {c['accent']};
}}
QCheckBox::indicator:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    image: none;
}}

/* ---------- نوار پیشرفت ---------- */
QProgressBar {{
    background: {c['surface2']};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c['accent']}, stop:1 {c['accent2']});
    border-radius: 4px;
}}

/* ---------- اسکرول ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['text_faint']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border']};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0; background: transparent;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QToolTip {{
    background: {c['surface2']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 6px 9px;
    font-size: 12px;
}}
QMenu {{
    background: {c['surface2']};
    border: 1px solid {c['border']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 7px;
}}
QMenu::item:selected {{
    background: {c['surface3']};
}}
QMessageBox {{
    background: {c['bg2']};
}}
QMessageBox QLabel {{
    font-size: 13px;
}}
"""

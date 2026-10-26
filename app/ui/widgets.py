"""
ویجت‌های اختصاصی رابط کاربری مهراس: دکمه‌ی قدرت، کارت آمار، نشان سایت‌ها،
نمودار سرعت زنده و نوار وضعیت.
"""
import math

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation,
                            QRectF, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.ui.theme import COLORS


# ---------------------------------------------------------------------------
# کمک‌تابع‌های قالب‌بندی
# ---------------------------------------------------------------------------
# LRM (U+200E) ابتدای رشته‌های «عدد + یکای لاتین» تا در متن راست‌به‌چپ،
# ترتیب 640 ms به هم نریزد و به شکل ms 640 نمایش داده نشود.
LRM = "\u200e"


def fmt_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{LRM}{n:.1f} {unit}" if unit != "B" else f"{LRM}{int(n)} B"
        n /= 1024
    return f"{LRM}{n:.1f} TB"


def fmt_speed(byte_per_sec: float) -> str:
    """بایت بر ثانیه → رشته‌ی خوانا (KB/s یا MB/s)."""
    b = float(byte_per_sec or 0)
    if b < 1024:
        return f"{LRM}{int(b)} B/s"
    if b < 1024 * 1024:
        return f"{LRM}{b / 1024:.0f} KB/s"
    return f"{LRM}{b / (1024 * 1024):.2f} MB/s"


def fmt_uptime(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{LRM}{h:02d}:{m:02d}:{s:02d}"
    return f"{LRM}{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# کارت
# ---------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, parent=None, soft=False):
        super().__init__(parent)
        self.setObjectName("cardSoft" if soft else "card")


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("divider")
        self.setFixedHeight(1)


# ---------------------------------------------------------------------------
# دکمه‌ی قدرت (دایره‌ی بزرگ با حلقه‌ی متحرک)
# ---------------------------------------------------------------------------
class PowerButton(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(190, 190)
        self.setCursor(Qt.PointingHandCursor)
        self._state = "idle"          # idle | connecting | connected
        self._phase = 0.0
        self._hover = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str):
        if state != self._state:
            self._state = state
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.045) % 1.0
        if self._state != "connected" or self._hover:
            self.update()

    # --- تعامل ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    # --- ترسیم ---
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cx, cy = w / 2, self.height() / 2
        radius = w / 2 - 6

        accent = {
            "idle": QColor(COLORS["accent"]),
            "connecting": QColor(COLORS["warning"]),
            "connected": QColor(COLORS["success"]),
        }[self._state]

        # هاله‌ی نرم
        glow = QRadialGradient(QPointF(cx, cy), radius)
        c1 = QColor(accent)
        c1.setAlpha(70 if self._state != "idle" else 45)
        glow.setColorAt(0.62, c1)
        c1b = QColor(accent)
        c1b.setAlpha(0)
        glow.setColorAt(1.0, c1b)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        # حلقه‌ی پایه
        ring = QColor(accent)
        ring.setAlpha(90)
        pen = QPen(ring, 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius - 9, radius - 9)

        # حلقه‌ی متحرک
        if self._state == "connecting":
            grad = QConicalGradient(QPointF(cx, cy), self._phase * 360)
            grad.setColorAt(0.0, QColor(COLORS["warning"]))
            g2 = QColor(COLORS["warning"])
            g2.setAlpha(0)
            grad.setColorAt(0.6, g2)
            grad.setColorAt(1.0, g2)
            pen = QPen(grad, 4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(cx - radius + 9, cy - radius + 9,
                             (radius - 9) * 2, (radius - 9) * 2), 0, 120 * 16)
        elif self._state == "connected":
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 150), 3)
            p.setPen(pen)
            p.drawEllipse(QPointF(cx, cy), radius - 9, radius - 9)

        # بدنه‌ی دکمه
        body = QLinearGradient(cx, cy - 62, cx, cy + 62)
        base = QColor(COLORS["surface2"] if self._state != "connected"
                      else COLORS["surface3"])
        body.setColorAt(0.0, base.lighter(112 if self._hover else 100))
        body.setColorAt(1.0, QColor(COLORS["surface"]))
        p.setBrush(body)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), radius - 20, radius - 20)

        # آیکون
        p.setPen(QPen(accent, 6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self._state == "connected":
            self._draw_check(p, cx, cy, radius)
        else:
            self._draw_power(p, cx, cy, radius)

        # متن داخل دکمه
        p.setPen(QColor(COLORS["text_dim"]))
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        f.setBold(True)
        p.setFont(f)
        label = {"idle": "اتصال", "connecting": "در حال اتصال",
                 "connected": "قطع اتصال"}[self._state]
        p.drawText(QRectF(cx - radius, cy + 34, radius * 2, 24),
                   Qt.AlignCenter, label)
        p.end()

    def _draw_power(self, p, cx, cy, radius):
        r = 27
        rect = QRectF(cx - r, cy - r - 2, r * 2, r * 2)
        p.drawArc(rect, 60 * 16, 300 * 16)
        p.drawLine(QPointF(cx, cy - r - 4), QPointF(cx, cy + 4))

    def _draw_check(self, p, cx, cy, radius):
        path = QPainterPath()
        path.moveTo(cx - 22, cy + 1)
        path.lineTo(cx - 6, cy + 17)
        path.lineTo(cx + 24, cy - 16)
        p.drawPath(path)


# ---------------------------------------------------------------------------
# کارت آمار
# ---------------------------------------------------------------------------
class StatCard(QWidget):
    def __init__(self, label, value="—", unit="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.lbl = QLabel(label)
        self.lbl.setObjectName("statLabel")
        # یک برچسب غنی برای اینکه «عدد + یکا» در متن راست‌به‌چپ جابه‌جا نشود
        self.val = QLabel("—")
        self.val.setObjectName("statValue")
        self.val.setTextFormat(Qt.RichText)
        self.val.setLayoutDirection(Qt.LeftToRight)
        lay.addWidget(self.lbl)
        lay.addWidget(self.val)

    def set_value(self, value, unit=""):
        unit_html = ""
        if unit:
            unit_html = (f'<span style="font-size:11px; font-weight:600;'
                         f' color:{COLORS["text_faint"]}"> {unit}</span>')
        self.val.setText(f"{LRM}{value}{unit_html}")


# ---------------------------------------------------------------------------
# نشان سایت‌ها (تلگرام/اینستاگرام/یوتیوب)
# ---------------------------------------------------------------------------
class SiteChip(QFrame):
    def __init__(self, name="", parent=None):
        super().__init__(parent)
        self.setObjectName("cardSoft")
        self.setMinimumHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{COLORS['text_faint']}; font-size:15px;")
        self.name = QLabel(name)
        self.name.setStyleSheet("font-weight:700;")
        self.lat = QLabel("")
        self.lat.setStyleSheet(f"color:{COLORS['text_faint']}; font-size:11px;")
        lay.addWidget(self.dot)
        lay.addWidget(self.name)
        lay.addStretch()
        lay.addWidget(self.lat)

    def set_state(self, ok, latency=None):
        if ok is None:
            color = COLORS["text_faint"]
            self.lat.setText("—")
        elif ok:
            color = COLORS["success"]
            self.lat.setText(f"{int(latency)} ms" if latency else "باز")
        else:
            color = COLORS["danger"]
            self.lat.setText("بسته")
        self.dot.setStyleSheet(f"color:{color}; font-size:15px;")


# ---------------------------------------------------------------------------
# نمودار سرعت زنده
# ---------------------------------------------------------------------------
class SpeedGraph(QWidget):
    def __init__(self, parent=None, points=90, color=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._points = points
        self._values = [0.0] * points
        self._color = QColor(color or COLORS["accent2"])
        self._peak = 1024.0

    def push(self, value: float):
        self._values.append(max(0.0, float(value or 0)))
        if len(self._values) > self._points:
            self._values = self._values[-self._points:]
        self._peak = max(2048.0, max(self._values))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if w < 10 or h < 10:
            p.end()
            return
        # خطوط راهنما
        grid = QColor(COLORS["border_soft"])
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            y = h * i / 4
            p.drawLine(QPointF(0, y), QPointF(w, y))

        n = len(self._values)
        step = w / max(1, n - 1)
        path = QPainterPath()
        path.moveTo(0, h)
        for i, v in enumerate(self._values):
            ratio = min(1.0, v / self._peak)
            y = h - ratio * (h - 6) - 2
            path.lineTo(i * step, y)
        path.lineTo(w, h)
        path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        top = QColor(self._color)
        top.setAlpha(120)
        grad.setColorAt(0.0, top)
        bot = QColor(self._color)
        bot.setAlpha(0)
        grad.setColorAt(1.0, bot)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawPath(path)

        line = QPainterPath()
        for i, v in enumerate(self._values):
            ratio = min(1.0, v / self._peak)
            y = h - ratio * (h - 6) - 2
            if i == 0:
                line.moveTo(0, y)
            else:
                line.lineTo(i * step, y)
        p.setPen(QPen(self._color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)
        p.end()


# ---------------------------------------------------------------------------
# نوار وضعیت پایین
# ---------------------------------------------------------------------------
class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color:{COLORS['text_faint']};")
        self.text = QLabel("آماده")
        self.text.setStyleSheet(f"color:{COLORS['text_dim']}; font-size:12px;")
        lay.addWidget(self.dot)
        lay.addWidget(self.text, 1)

    def set_text(self, text, tone="dim"):
        colors = {"dim": COLORS["text_dim"], "ok": COLORS["success"],
                  "warn": COLORS["warning"], "err": COLORS["danger"],
                  "busy": COLORS["accent2"]}
        color = colors.get(tone, COLORS["text_dim"])
        self.text.setText(text)
        self.text.setStyleSheet(f"color:{color}; font-size:12px;")
        self.dot.setStyleSheet(f"color:{color};")

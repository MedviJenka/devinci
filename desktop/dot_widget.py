import math
from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint
from PyQt6.QtGui import QPainter, QRadialGradient, QColor, QPen, QBrush, QCursor
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

SIZE = 72
RADIUS = 16


class DotWidget(QWidget):

    def __init__(self, on_quit):
        super().__init__()
        self._state = "standby"
        self._t = 0.0
        self._drag_pos: QPoint | None = None
        self._on_quit = on_quit

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(SIZE, SIZE)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - SIZE - 32, geo.bottom() - SIZE - 60)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_state(self, state: str):
        self._state = state

    def _tick(self):
        self._t += 0.016
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = SIZE / 2.0
        t = self._t

        match self._state:
            case "standby":
                # soft blue pulse — always visible
                s = 0.75 + 0.25 * (0.5 + 0.5 * math.sin(t * math.tau / 2.4))
                self._glow(p, cx, cy, RADIUS * s, QColor(80, 140, 255), alpha=190)

            case "listening":
                hue = int((t * 80) % 360)
                color = QColor.fromHsv(hue, 235, 255)
                s = 0.88 + 0.12 * math.sin(t * math.tau / 0.45)
                self._glow(p, cx, cy, RADIUS * s, color, alpha=210)

            case "processing":
                s = 0.9 + 0.1 * abs(math.sin(t * math.tau / 0.38))
                self._glow(p, cx, cy, RADIUS * s, QColor(255, 148, 0), alpha=200)
                self._arc(p, cx, cy, RADIUS + 11, t)

            case "speaking":
                hue = int(250 + 55 * math.sin(t * 1.4))
                color = QColor.fromHsv(hue % 360, 200, 255)
                s = 0.9 + 0.1 * math.sin(t * math.tau / 0.28)
                self._glow(p, cx, cy, RADIUS * s, color, alpha=210)
                self._ripples(p, cx, cy, t)

        p.end()

    def _glow(self, p: QPainter, cx: float, cy: float, r: float, color: QColor, alpha: int):
        gr = QRadialGradient(cx, cy, r * 2.4)
        gr.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
        gr.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(gr))
        p.drawEllipse(QRectF(cx - r * 2.4, cy - r * 2.4, r * 4.8, r * 4.8))

        cr = QRadialGradient(cx - r * 0.3, cy - r * 0.3, r)
        bright = QColor(
            min(255, color.red() + 85),
            min(255, color.green() + 85),
            min(255, color.blue() + 85),
            245,
        )
        cr.setColorAt(0.0, bright)
        cr.setColorAt(0.55, color)
        cr.setColorAt(1.0, QColor(color.red() // 2, color.green() // 2, color.blue() // 2, 210))
        p.setBrush(QBrush(cr))
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    def _arc(self, p: QPainter, cx: float, cy: float, r: float, t: float):
        deg = int(t * 200) % 360
        p.setPen(QPen(QColor(255, 200, 0, 230), 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), deg * 16, 110 * 16)

    def _ripples(self, p: QPainter, cx: float, cy: float, t: float):
        for i in range(3):
            phase = (t * 1.1 + i / 3.0) % 1.0
            r = RADIUS + 3 + phase * (SIZE / 2 - RADIUS - 5)
            alpha = int(190 * (1.0 - phase))
            p.setPen(QPen(QColor(160, 80, 255, alpha), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    # ── interaction ───────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _e):
        self._drag_pos = None
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1e1e2e; color:#cdd6f4; border:1px solid #45475a; border-radius:6px; }"
            "QMenu::item { padding:6px 18px; } QMenu::item:selected { background:#313244; }"
        )
        quit_act = menu.addAction("Quit Claude Listener")
        if menu.exec(e.globalPos()) == quit_act:
            self._on_quit()

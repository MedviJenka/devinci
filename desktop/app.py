import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QBrush
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from desktop.dot_widget import DotWidget
from desktop.pipeline import PipelineThread


_STATE_COLORS = {
    "standby":    QColor(80, 140, 255),
    "listening":  QColor(0,   220, 130),
    "processing": QColor(255, 148, 0),
    "speaking":   QColor(160, 80,  255),
}


def _make_tray_icon(color: QColor) -> QIcon:
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(3, 3, 16, 16)
    p.end()
    return QIcon(px)


def run():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    pipeline = PipelineThread()

    def quit_app():
        pipeline.stop()
        pipeline.wait(2000)
        app.quit()

    dot = DotWidget(on_quit=quit_app)

    # ── system tray ───────────────────────────────────────────────────────────
    tray = QSystemTrayIcon(app)
    tray.setIcon(_make_tray_icon(_STATE_COLORS["standby"]))
    tray.setToolTip("Claude Listener")

    tray_menu = QMenu()
    tray_menu.setStyleSheet(
        "QMenu { background:#1e1e2e; color:#cdd6f4; border:1px solid #45475a; border-radius:6px; }"
        "QMenu::item { padding:6px 18px; } QMenu::item:selected { background:#313244; }"
    )
    tray_menu.addAction("Claude Listener — running")
    tray_menu.actions()[0].setEnabled(False)
    tray_menu.addSeparator()
    tray_menu.addAction("Quit", quit_app)
    tray.setContextMenu(tray_menu)
    tray.show()

    # ── wire state signal ─────────────────────────────────────────────────────
    def on_state(state: str):
        dot.set_state(state)
        tray.setIcon(_make_tray_icon(_STATE_COLORS.get(state, _STATE_COLORS["standby"])))
        tray.setToolTip(f"Claude Listener — {state}")

    pipeline.state_changed.connect(on_state)

    dot.show()
    dot.raise_()
    dot.activateWindow()
    pipeline.start()

    sys.exit(app.exec())

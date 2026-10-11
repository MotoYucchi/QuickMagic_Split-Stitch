"""GUI launcher entrypoint."""

from __future__ import annotations

import sys
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication
from splitstitch.gui.main_window import MainWindow


def launch_gui() -> None:
    """Launch PySide6 application event loop."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette for consistent OS-neutral dark theme
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(15, 23, 42))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(241, 245, 249))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 41, 59))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(15, 23, 42))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(241, 245, 249))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(15, 23, 42))
    palette.setColor(QPalette.ColorRole.Text, QColor(241, 245, 249))
    palette.setColor(QPalette.ColorRole.Button, QColor(51, 65, 85))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(241, 245, 249))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(239, 68, 68))
    palette.setColor(QPalette.ColorRole.Link, QColor(56, 189, 248))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(37, 99, 235))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    app.setApplicationName("Split & Stitch for QuickMagicMotion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

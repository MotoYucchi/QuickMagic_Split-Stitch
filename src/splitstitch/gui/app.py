"""GUI launcher entrypoint."""

from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from splitstitch.gui.main_window import MainWindow


def launch_gui() -> None:
    """Launch PySide6 application event loop."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("Split & Stitch for QuickMagicMotion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())

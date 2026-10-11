import os
import pytest
from PySide6.QtWidgets import QApplication

# Set offscreen platform for headless test execution
os.environ["QT_QPA_PLATFORM"] = "offscreen"


def test_main_window_initialization():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    from splitstitch.gui.main_window import MainWindow

    window = MainWindow()
    assert window.windowTitle() == "Split & Stitch for QuickMagicMotion"
    assert window.tabs.count() == 2
    assert window.tabs.tabText(0) == "1. 動画分割 (Split)"
    assert window.tabs.tabText(1) == "2. モーション結合 (Stitch)"
    assert window.split_video_edit is not None
    assert window.stitch_manifest_edit is not None
    assert window.btn_run_split is not None
    assert window.btn_run_stitch is not None

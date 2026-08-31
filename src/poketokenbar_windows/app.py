from __future__ import annotations

import ctypes
import os
import sys

from .windows import APP_NAME


def _configure_windows_identity() -> None:
    if os.name != "nt":
        return
    try:
        app_id = "PokeTokenBar.Windows.Isolated" if os.environ.get("PTB_STATE_DIR", "").strip() else "PokeTokenBar.Windows"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def _hide_console_window() -> None:
    if os.name != "nt":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except (AttributeError, OSError):
        pass


def main() -> int:
    _configure_windows_identity()
    _hide_console_window()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from .ui import TrayController, application_icon

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    icon = application_icon()
    app.setWindowIcon(icon)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("PokeTokenBar")
    app.setQuitOnLastWindowClosed(False)

    controller = TrayController(app)
    # Request the main window on an interactive launch. TrayController defers
    # the actual show until the first real usage/limit snapshot is rendered.
    controller.show_window()

    app._poketokenbar_controller = controller  # keep QObject graph alive
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

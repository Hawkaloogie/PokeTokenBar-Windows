from __future__ import annotations

import ctypes
import os
import sys


def _configure_windows_identity() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PokeTokenBar.Windows")
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
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from .ui import TrayController, application_icon

    app = QApplication(sys.argv)
    icon = application_icon()
    app.setWindowIcon(icon)
    app.setApplicationName("PokeTokenBar Windows")
    app.setApplicationDisplayName("PokeTokenBar Windows")
    app.setOrganizationName("PokeTokenBar")
    app.setQuitOnLastWindowClosed(False)

    controller = TrayController(app)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        # Remote Desktop / restricted shells can temporarily hide the notification area.
        controller.window.show()

    app._poketokenbar_controller = controller  # keep QObject graph alive
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

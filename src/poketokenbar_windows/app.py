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


def _single_instance_key() -> str:
    """Socket name for this install.

    An isolated state dir gets its own key, so a test or a second profile can
    still run alongside the real app.
    """
    isolated = os.environ.get("PTB_STATE_DIR", "").strip()
    suffix = str(abs(hash(isolated)) % 10_000_000) if isolated else "main"
    return f"PokeTokenBar-Windows-{suffix}"


def _claim_single_instance(app, on_second_launch):
    """Return a listening server, or None when another instance already owns it.

    Launching again raises the existing window rather than doing nothing
    silently, which is what people expect from a tray app.
    """
    from PySide6.QtNetwork import QLocalServer, QLocalSocket

    key = _single_instance_key()
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(300):
        # Someone is already home: ask them to show themselves, then leave.
        probe.write(b"show")
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None
    # A crashed instance can leave the name behind; reclaim it.
    QLocalServer.removeServer(key)
    server = QLocalServer(app)
    if not server.listen(key):
        # Could not claim it and could not connect to it - fail open rather
        # than refuse to start at all.
        return server
    def _greet() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.readyRead.connect(lambda: None)
            connection.disconnected.connect(connection.deleteLater)
        on_second_launch()
    server.newConnection.connect(_greet)
    return server


def _stored_theme() -> str:
    from PySide6.QtCore import QSettings
    return str(QSettings("PokeTokenBar", "PokeTokenBar").value("theme", "system"))


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

    # A matching QPalette underneath the stylesheet: QSS wins wherever it
    # applies, but system-drawn bits (native menus, some dialogs) fall back to
    # the palette, and a light default there looks broken on a dark app.
    from .theme import apply_base_palette
    apply_base_palette(app, str(_stored_theme()))

    controller = TrayController(app)

    server = _claim_single_instance(app, controller.show_window)
    if server is None:
        # Another copy is already running and has been asked to show itself.
        return 0

    # Request the main window on an interactive launch. TrayController defers
    # the actual show until the first real usage/limit snapshot is rendered.
    controller.show_window()

    app._poketokenbar_controller = controller  # keep QObject graph alive
    app._poketokenbar_server = server
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

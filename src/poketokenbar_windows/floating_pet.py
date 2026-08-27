from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QContextMenuEvent, QMouseEvent, QMovie, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMenu, QVBoxLayout, QWidget

from .pet_logic import (
    PET_ALERT_TTL_MS,
    PET_DEFAULT_SIZE,
    ScreenRect,
    choose_pet_alert,
    dump_alert_memory,
    evaluate_pet_alerts,
    load_alert_memory,
    normalize_pet_size,
    pet_hover_text,
    recover_pet_position,
    settings_bool,
)
from .windows import APP_NAME, apply_floating_tool_window_style, native_window_styles


PET_ENABLED_KEY = "floating_pet/enabled"
PET_SIZE_KEY = "floating_pet/size"
PET_X_KEY = "floating_pet/position_x"
PET_Y_KEY = "floating_pet/position_y"
PET_ALERTS_KEY = "floating_pet/alerts_enabled"
PET_ALERT_MEMORY_KEY = "floating_pet/alert_memory"


def _egg_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = max(4, size // 8)
    rect = (margin + size // 16, margin, size - 2 * margin - size // 8, size - 2 * margin)
    painter.setBrush(QColor("#f7ead0"))
    painter.setPen(QPen(QColor("#c4a574"), max(2, size // 32)))
    painter.drawEllipse(*rect)
    painter.setPen(Qt.PenStyle.NoPen)
    for color, nx, ny, scale in (
        ("#6eb8b0", 0.32, 0.28, 0.18),
        ("#7ec8c0", 0.58, 0.42, 0.14),
        ("#5aa39c", 0.40, 0.55, 0.12),
    ):
        painter.setBrush(QColor(color))
        diameter = max(3, int(rect[2] * scale))
        painter.drawEllipse(
            int(rect[0] + rect[2] * nx - diameter / 2),
            int(rect[1] + rect[3] * ny - diameter / 2),
            diameter,
            diameter,
        )
    painter.end()
    return pixmap


class FloatingPetWindow(QWidget):
    clicked = Signal()
    hide_requested = Signal()
    hover_changed = Signal(bool)
    position_committed = Signal(int, int)

    def __init__(self, size: int):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setObjectName("FloatingPetWindow")
        self.setWindowTitle(f"{APP_NAME} Pet")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.label.setStyleSheet("background: transparent;")
        self.movie: QMovie | None = None
        self.sprite_path: Path | None = None
        self.is_egg = True
        self.pet_size = normalize_pet_size(size)
        self._press_global: QPoint | None = None
        self._start_position: QPoint | None = None
        self._dragging = False
        self.set_pet_size(self.pet_size)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_floating_tool_window_style(int(self.winId()))

    def set_pet_size(self, size: int) -> None:
        self.pet_size = normalize_pet_size(size)
        self.setFixedSize(self.pet_size, self.pet_size)
        self.label.setGeometry(0, 0, self.pet_size, self.pet_size)
        self._render_current_frame()

    def set_sprite(self, path: Path | None, *, is_egg: bool) -> None:
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        self.sprite_path = path
        self.is_egg = is_egg
        self.label.clear()
        if path is not None and path.exists() and path.suffix.lower() == ".gif":
            movie = QMovie(str(path), parent=self)
            if movie.isValid():
                movie.frameChanged.connect(self._render_current_frame)
                self.movie = movie
                movie.start()
                return
            movie.deleteLater()
        self._render_current_frame()

    def _render_current_frame(self, *_args) -> None:
        pixmap = QPixmap()
        if self.movie is not None:
            pixmap = self.movie.currentPixmap()
        elif self.sprite_path is not None and self.sprite_path.exists():
            pixmap = QPixmap(str(self.sprite_path))
        if pixmap.isNull():
            pixmap = _egg_pixmap(self.pet_size) if self.is_egg else QPixmap()
        if pixmap.isNull():
            self.label.setText("●")
            self.label.setStyleSheet("background: transparent; color: #ef4444; font-size: 42px;")
            return
        self.label.setText("")
        self.label.setStyleSheet("background: transparent;")
        self.label.setPixmap(
            pixmap.scaled(
                self.pet_size,
                self.pet_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    def set_animation_running(self, running: bool) -> None:
        if self.movie is None:
            return
        if running:
            self.movie.start()
        else:
            self.movie.stop()
            self._render_current_frame()

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.hover_changed.emit(True)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.hover_changed.emit(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._start_position = self.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._press_global is not None
            and self._start_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
            if self._dragging:
                self.move(self._start_position + delta)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._press_global is not None:
            was_dragging = self._dragging
            self._press_global = None
            self._start_position = None
            self._dragging = False
            if was_dragging:
                self.position_committed.emit(self.x(), self.y())
            else:
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        self.hover_changed.emit(False)
        menu = QMenu(self)
        open_action = menu.addAction("Open PokeTokenBar")
        hide_action = menu.addAction("Hide")
        selected = menu.exec(event.globalPos())
        if selected is open_action:
            self.clicked.emit()
        elif selected is hide_action:
            self.hide_requested.emit()


class _CalloutBase(QFrame):
    def __init__(self):
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            "QFrame { background: #fffdf9; border: 1px solid #d8d2c8; border-radius: 10px; }"
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_floating_tool_window_style(int(self.winId()))


class HoverCallout(_CalloutBase):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel()
        self.label.setObjectName("HoverCalloutText")
        self.label.setStyleSheet("border: none; color: #26221d;")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(280)
        layout.addWidget(self.label)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.adjustSize()


class AlertBubble(_CalloutBase):
    def __init__(self):
        super().__init__()
        self.setObjectName("AlertBubble")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setMaximumWidth(240)
        self.title.setStyleSheet("border: none;")
        self.body.setStyleSheet("border: none; color: #4b5563;")
        layout.addWidget(self.title)
        layout.addWidget(self.body)

    def set_alert(self, alert) -> None:
        self.title.setText(alert.title)
        self.body.setText(alert.body)
        color = "#b91c1c" if alert.severity == "critical" else "#b45309"
        self.title.setStyleSheet(f"border: none; color: {color};")
        self.adjustSize()


class FloatingPetController(QObject):
    enabled_changed = Signal(bool)
    size_changed = Signal(int)
    alerts_enabled_changed = Signal(bool)

    def __init__(
        self,
        app: QApplication,
        settings,
        on_open: Callable[[], None],
    ):
        super().__init__()
        self.app = app
        self.settings = settings
        self.on_open = on_open
        self.enabled = settings_bool(settings.value(PET_ENABLED_KEY, False), False)
        self.alerts_enabled = settings_bool(settings.value(PET_ALERTS_KEY, True), True)
        self.size = normalize_pet_size(settings.value(PET_SIZE_KEY, PET_DEFAULT_SIZE))
        self.result: Any | None = None
        self.alert_memory = load_alert_memory(settings.value(PET_ALERT_MEMORY_KEY, ""))
        self.pet = FloatingPetWindow(self.size)
        self.hover = HoverCallout()
        self.bubble = AlertBubble()
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.bubble.hide)
        self.pet.clicked.connect(self.on_open)
        self.pet.hide_requested.connect(lambda: self.set_enabled(False))
        self.pet.hover_changed.connect(self._on_hover)
        self.pet.position_committed.connect(self._save_position)
        self.app.screenAdded.connect(self._screen_added)
        self.app.screenRemoved.connect(lambda _screen: self._screens_changed())
        for screen in self.app.screens():
            self._observe_screen(screen)
        self._restore_position()
        self._apply_visibility()

    def _observe_screen(self, screen) -> None:
        screen.geometryChanged.connect(lambda _rect: self._screens_changed())
        screen.availableGeometryChanged.connect(lambda _rect: self._screens_changed())

    def _screen_added(self, screen) -> None:
        self._observe_screen(screen)
        self._screens_changed()

    def _screen_rects(self) -> list[ScreenRect]:
        return [
            ScreenRect(rect.x(), rect.y(), rect.width(), rect.height())
            for rect in (screen.availableGeometry() for screen in self.app.screens())
        ]

    def _restore_position(self) -> None:
        x = self.settings.value(PET_X_KEY, float("nan"))
        y = self.settings.value(PET_Y_KEY, float("nan"))
        target = recover_pet_position(x, y, self.size, self._screen_rects())
        self.pet.move(*target)
        self._save_position(*target)

    def _screens_changed(self) -> None:
        target = recover_pet_position(self.pet.x(), self.pet.y(), self.size, self._screen_rects())
        self.pet.move(*target)
        self._save_position(*target)
        self._position_auxiliary_windows()

    def _save_position(self, x: int, y: int) -> None:
        target = recover_pet_position(x, y, self.size, self._screen_rects())
        if target != (x, y):
            self.pet.move(*target)
        self.settings.setValue(PET_X_KEY, target[0])
        self.settings.setValue(PET_Y_KEY, target[1])
        self.settings.sync()
        self._position_auxiliary_windows()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        self.settings.setValue(PET_ENABLED_KEY, enabled)
        self.settings.sync()
        self._apply_visibility()
        self.enabled_changed.emit(enabled)
        if enabled and self.result is not None:
            self._render_result(evaluate_alerts=True)

    def set_size(self, size: int) -> None:
        normalized = normalize_pet_size(size)
        if self.size == normalized:
            return
        self.size = normalized
        self.settings.setValue(PET_SIZE_KEY, normalized)
        self.pet.set_pet_size(normalized)
        self._screens_changed()
        self.settings.sync()
        self.size_changed.emit(normalized)

    def set_alerts_enabled(self, enabled: bool) -> None:
        self.alerts_enabled = bool(enabled)
        self.settings.setValue(PET_ALERTS_KEY, self.alerts_enabled)
        self.settings.sync()
        if not self.alerts_enabled:
            self.bubble_timer.stop()
            self.bubble.hide()
        self.alerts_enabled_changed.emit(self.alerts_enabled)

    def _apply_visibility(self) -> None:
        if self.enabled:
            self.pet.show()
            self.pet.raise_()
            self.pet.set_animation_running(True)
            QTimer.singleShot(0, lambda: apply_floating_tool_window_style(int(self.pet.winId())))
        else:
            self.bubble_timer.stop()
            self.hover.hide()
            self.bubble.hide()
            self.pet.set_animation_running(False)
            self.pet.hide()

    def update(self, result: Any) -> None:
        self.result = result
        self._render_result(evaluate_alerts=True)

    def _render_result(self, *, evaluate_alerts: bool) -> None:
        if self.result is None:
            return
        self.pet.set_sprite(self.result.pet_sprite_path, is_egg=self.result.pet_is_egg)
        self.hover.set_text(pet_hover_text(self.result.snapshot, self.result.limits))
        if not self.enabled:
            self.pet.set_animation_running(False)
            return
        self.pet.set_animation_running(True)
        self.pet.show()
        if evaluate_alerts and self.alerts_enabled:
            alerts, self.alert_memory = evaluate_pet_alerts(self.result.limits, self.alert_memory)
            self.settings.setValue(PET_ALERT_MEMORY_KEY, dump_alert_memory(self.alert_memory))
            self.settings.sync()
            alert = choose_pet_alert(alerts)
            if alert is not None:
                self.hover.hide()
                self.bubble.set_alert(alert)
                self._position_auxiliary_windows()
                self.bubble.show()
                self.bubble.raise_()
                self.bubble_timer.start(PET_ALERT_TTL_MS)

    def _on_hover(self, hovering: bool) -> None:
        if not hovering or not self.enabled or self.bubble.isVisible() or self.result is None:
            self.hover.hide()
            return
        self.hover.set_text(pet_hover_text(self.result.snapshot, self.result.limits))
        self._position_auxiliary_windows()
        self.hover.show()
        self.hover.raise_()

    def _place_above(self, window: QWidget) -> None:
        screen = self.app.screenAt(self.pet.geometry().center()) or self.app.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        size = window.sizeHint().expandedTo(window.size())
        window.resize(size)
        x = self.pet.x() + (self.pet.width() - window.width()) // 2
        x = min(available.right() - window.width(), max(available.left(), x))
        y = self.pet.y() - window.height() - 8
        if y < available.top():
            y = min(available.bottom() - window.height(), self.pet.y() + self.pet.height() + 8)
        window.move(x, y)

    def _position_auxiliary_windows(self) -> None:
        self._place_above(self.hover)
        self._place_above(self.bubble)

    def shutdown(self) -> None:
        self.bubble_timer.stop()
        if self.pet.movie is not None:
            self.pet.movie.stop()
        self.hover.close()
        self.bubble.close()
        self.pet.close()

    def qa_snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "visible": self.pet.isVisible(),
            "size": self.size,
            "position": [self.pet.x(), self.pet.y()],
            "hwnd": int(self.pet.winId()),
            "native_styles": native_window_styles(int(self.pet.winId())),
            "qt_window_flags": int(self.pet.windowFlags()),
            "translucent_background": self.pet.testAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground
            ),
            "movie_valid": bool(self.pet.movie is not None and self.pet.movie.isValid()),
            "sprite_path": str(self.pet.sprite_path) if self.pet.sprite_path is not None else None,
            "screens": [
                {
                    "name": screen.name(),
                    "available_geometry": [
                        screen.availableGeometry().x(),
                        screen.availableGeometry().y(),
                        screen.availableGeometry().width(),
                        screen.availableGeometry().height(),
                    ],
                    "device_pixel_ratio": screen.devicePixelRatio(),
                    "logical_dpi": screen.logicalDotsPerInch(),
                }
                for screen in self.app.screens()
            ],
        }

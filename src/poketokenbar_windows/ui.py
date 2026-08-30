from __future__ import annotations

import copy
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QMovie, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .formatting import (
    compact_tokens,
    limit_reset_expiry,
    limit_reset_tray_warning,
    money,
    provider_limit_rows,
)
from .floating_pet import (
    PET_ALERTS_KEY,
    PET_ENABLED_KEY,
    PET_SIZE_KEY,
    FloatingPetController,
)
from .limits import fetch_all_limits
from .models import ProviderLimits, UsageSnapshot
from .notifications import (
    COMPANION_NOTIFICATIONS_KEY,
    CRITICAL_MAX,
    CRITICAL_MIN,
    CRITICAL_THRESHOLD_KEY,
    DEFAULT_COMPANION_NOTIFICATIONS,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_LIMIT_NOTIFICATIONS,
    DEFAULT_WARNING_THRESHOLD,
    LIMIT_NOTIFICATIONS_KEY,
    THRESHOLD_STEP,
    WARNING_MAX,
    WARNING_MIN,
    WARNING_THRESHOLD_KEY,
    companion_notification,
    evaluate_limit_alerts,
    normalize_critical_threshold,
    normalize_warning_threshold,
)
from .pet_logic import PET_DEFAULT_SIZE, PET_MAX_SIZE, PET_MIN_SIZE, PET_SIZE_STEP, normalize_pet_size, settings_bool
from .pokemon import EGG_HATCH_THRESHOLD, PokeAPIClient, egg_price, phase_threshold
from .state import (
    GameState,
    StateStore,
    apply_limit_rewards,
    apply_usage,
    buy_egg,
    buy_item,
    companion_progress_percent,
    owned_representative_options,
    representative_subject,
    set_representative,
    usage_delta,
    use_item,
)
from .usage import PROVIDER_LABELS, scan_all
from .windows import APP_NAME, apply_native_window_icon, autostart_enabled, cache_dir, set_autostart, state_dir


@dataclass(slots=True)
class RefreshResult:
    snapshot: UsageSnapshot
    limits: dict[str, ProviderLimits]
    scan_errors: dict[str, str]
    state: GameState
    events: list[str]
    sprite_path: Path | None
    display_name: str
    pet_sprite_path: Path | None
    pet_display_name: str
    pet_is_egg: bool


def application_settings() -> QSettings:
    """Use an isolated INI backend for QA while preserving production registry settings."""
    if os.environ.get("PTB_STATE_DIR", "").strip():
        path = state_dir() / "settings.ini"
        path.parent.mkdir(parents=True, exist_ok=True)
        return QSettings(str(path), QSettings.Format.IniFormat)
    return QSettings("PokeTokenBar", "PokeTokenBar-Windows")


def tray_tooltip(result: RefreshResult) -> str:
    text = f"{compact_tokens(result.snapshot.today_tokens)} today"
    if result.state.mon:
        text += f" · {result.display_name}"
    else:
        text += " · egg"
    text += f" · {companion_progress_percent(result.state)}%"

    warnings: list[tuple[float, str]] = []
    for limits in result.limits.values():
        warning = limit_reset_tray_warning(limits)
        expiry = limit_reset_expiry(limits)
        if warning and expiry is not None:
            warnings.append((expiry.timestamp(), warning))
    if warnings:
        text += f" · {min(warnings, key=lambda item: item[0])[1]}"
    return f"{APP_NAME} · {text}"


class Bridge(QObject):
    refreshed = Signal(object)
    failed = Signal(str)


def _pokeball_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = max(1, size // 16)
    diameter = size - margin * 2
    band = max(2, size // 10)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#e53935"))
    painter.drawPie(margin, margin, diameter, diameter, 0, 180 * 16)
    painter.setBrush(QColor("#fafafa"))
    painter.drawPie(margin, margin, diameter, diameter, 180 * 16, 180 * 16)
    painter.setBrush(QColor("#202124"))
    painter.drawRect(margin, size // 2 - band // 2, diameter, band)
    outline = QPen(QColor("#202124"))
    outline.setWidth(max(2, size // 14))
    painter.setPen(outline)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(margin, margin, diameter, diameter)
    radius = max(3, size // 6)
    painter.setPen(QPen(QColor("#202124"), max(2, size // 16)))
    painter.setBrush(QColor("#fafafa"))
    painter.drawEllipse(size // 2 - radius, size // 2 - radius, radius * 2, radius * 2)
    painter.end()
    return pixmap


def _pokeball_ico_bytes() -> bytes:
    images: list[tuple[int, bytes]] = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        _pokeball_pixmap(size).save(buffer, "PNG")
        images.append((size, bytes(ba.data())))
    count = len(images)
    offset = 6 + 16 * count
    directory = bytearray(b"\x00\x00\x01\x00") + count.to_bytes(2, "little")
    payload = bytearray()
    for size, png in images:
        stored = 0 if size >= 256 else size
        directory += bytes((stored, stored, 0, 0, 1, 0, 32, 0))
        directory += len(png).to_bytes(4, "little")
        directory += offset.to_bytes(4, "little")
        payload += png
        offset += len(png)
    return bytes(directory) + bytes(payload)


def application_icon() -> QIcon:
    icon_path = cache_dir() / "app.ico"
    try:
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        icon_path.write_bytes(_pokeball_ico_bytes())
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    except OSError:
        pass
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_pokeball_pixmap(size))
    return icon


def _egg_pixmap(size: int = 128) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size // 8
    egg = (margin + size // 16, margin, size - margin * 2 - size // 8, size - margin * 2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 28))
    painter.drawEllipse(egg[0] + size // 24, egg[1] + size // 8, egg[2], egg[3])
    painter.setBrush(QColor("#f7ead0"))
    painter.setPen(QPen(QColor("#c4a574"), max(2, size // 32)))
    painter.drawEllipse(*egg)
    painter.setPen(Qt.PenStyle.NoPen)
    spots = (
        ("#6eb8b0", 0.32, 0.28, 0.18),
        ("#7ec8c0", 0.58, 0.42, 0.14),
        ("#5aa39c", 0.40, 0.55, 0.12),
        ("#8fd4cc", 0.28, 0.48, 0.10),
        ("#6eb8b0", 0.55, 0.22, 0.10),
    )
    for color, nx, ny, nr in spots:
        painter.setBrush(QColor(color))
        diameter = int(egg[2] * nr)
        painter.drawEllipse(
            int(egg[0] + egg[2] * nx - diameter / 2),
            int(egg[1] + egg[3] * ny - diameter / 2),
            diameter,
            diameter,
        )
    painter.setBrush(QColor(255, 255, 255, 90))
    painter.drawEllipse(
        int(egg[0] + egg[2] * 0.28),
        int(egg[1] + egg[3] * 0.16),
        int(egg[2] * 0.22),
        int(egg[3] * 0.16),
    )
    painter.end()
    return pixmap


def _pokeball_icon(size: int = 64) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pokeball_pixmap(size))
    icon.addPixmap(_pokeball_pixmap(32))
    icon.addPixmap(_pokeball_pixmap(16))
    return icon


def _sprite_pixmap(path: Path | None, box: int = 96) -> QPixmap:
    pix = QPixmap()
    if path is not None and path.exists():
        if path.suffix.lower() == ".gif":
            movie = QMovie(str(path))
            if movie.isValid():
                movie.jumpToFrame(0)
                pix = movie.currentPixmap()
        else:
            pix = QPixmap(str(path))
    if pix.isNull():
        return QPixmap()
    return pix.scaled(box, box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


def _muted_pixmap(pix: QPixmap) -> QPixmap:
    if pix.isNull():
        return pix
    image = pix.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            grey = int(0.3 * color.red() + 0.59 * color.green() + 0.11 * color.blue())
            color.setRgb(grey, grey, grey, int(color.alpha() * 0.4))
            image.setPixelColor(x, y, color)
    return QPixmap.fromImage(image)


def _icon_from_sprite(path: Path | None, *, fallback_egg: bool = False) -> QIcon:
    pix = _sprite_pixmap(path, 128)
    if pix.isNull():
        pix = _egg_pixmap(128) if fallback_egg else _pokeball_pixmap(128)
    return QIcon(pix)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)


def _data_cache_dir() -> Path:
    path = cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _autostart_enabled() -> bool:
    return autostart_enabled()


def _set_autostart(enabled: bool) -> None:
    set_autostart(enabled)


class MetricCard(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        self.title = QLabel(title)
        self.value = QLabel("-")
        font = self.value.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.value.setFont(font)
        layout.addWidget(self.title)
        layout.addWidget(self.value)


class MainWindow(QMainWindow):
    refresh_requested = Signal()
    limit_notifications_changed = Signal(bool)
    warning_threshold_changed = Signal(int)
    critical_threshold_changed = Signal(int)
    companion_notifications_changed = Signal(bool)
    floating_pet_enabled_changed = Signal(bool)
    floating_pet_size_changed = Signal(int)
    floating_pet_alerts_changed = Signal(bool)
    representative_changed = Signal(object)

    def __init__(self, state: GameState, settings: QSettings, api: PokeAPIClient):
        super().__init__()
        self.state = state
        self.settings = settings
        self.api = api
        self.movie: QMovie | None = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(application_icon())
        self.setMinimumSize(520, 640)
        self.resize(560, 740)

        tabs = QTabWidget()
        tabs.addTab(self._build_home(), "Home")
        tabs.addTab(self._build_collection(), "Collection")
        tabs.addTab(self._build_bag_shop(), "Bag & Shop")
        tabs.addTab(self._wrap_scroll(self._build_settings()), "Settings")
        self.setCentralWidget(tabs)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_native_window_icon(int(self.winId()), cache_dir() / "app.ico")

    def _build_home(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        hero = QHBoxLayout()
        self.sprite = QLabel()
        self.sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sprite.setFixedSize(128, 128)
        self.sprite.setStyleSheet("QLabel { background: #f6f3ee; border-radius: 16px; }")
        self.sprite.setPixmap(_egg_pixmap(112))
        hero.addWidget(self.sprite)
        meta = QVBoxLayout()
        self.name_label = QLabel("Pokemon Egg")
        f = self.name_label.font()
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        self.name_label.setFont(f)
        self.detail_label = QLabel("Use tokens to hatch it")
        self.progress_label = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        meta.addWidget(self.name_label)
        meta.addWidget(self.detail_label)
        meta.addWidget(self.progress_label)
        meta.addWidget(self.progress)
        meta.addStretch(1)
        hero.addLayout(meta, 1)
        layout.addLayout(hero)

        metrics = QGridLayout()
        self.today_card = MetricCard("Today")
        self.cost_card = MetricCard("Est. cost")
        self.week_card = MetricCard("This week")
        self.wallet_card = MetricCard("Shop wallet")
        metrics.addWidget(self.today_card, 0, 0)
        metrics.addWidget(self.cost_card, 0, 1)
        metrics.addWidget(self.week_card, 1, 0)
        metrics.addWidget(self.wallet_card, 1, 1)
        layout.addLayout(metrics)

        heading = QHBoxLayout()
        label = QLabel("Providers")
        lf = label.font(); lf.setBold(True); label.setFont(lf)
        heading.addWidget(label)
        heading.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)

        self.providers_list = QListWidget()
        layout.addWidget(self.providers_list, 1)

        limits_label = QLabel("Official limits")
        lf = limits_label.font(); lf.setBold(True); limits_label.setFont(lf)
        layout.addWidget(limits_label)
        self.limits_list = QListWidget()
        self.limits_list.setMaximumHeight(150)
        layout.addWidget(self.limits_list)
        return root

    def _build_collection(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        inner = QTabWidget()
        inner.addTab(self._wrap_scroll(self._build_dex_page()), "Pokédex")
        inner.addTab(self._wrap_scroll(self._build_catch_page()), "Catch log")
        layout.addWidget(inner)
        return root

    def _wrap_scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(widget)
        return scroll

    def _build_dex_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.dex_empty = QLabel("No Pokemon hatched yet")
        self.dex_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.dex_empty)
        self.dex_grid = QGridLayout()
        self.dex_grid.setSpacing(10)
        layout.addLayout(self.dex_grid)
        layout.addStretch(1)
        return page

    def _build_catch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        self.catch_empty = QLabel("No Pokemon hatched yet")
        self.catch_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.catch_empty)
        self.catch_list = QVBoxLayout()
        self.catch_list.setSpacing(10)
        layout.addLayout(self.catch_list)
        layout.addStretch(1)
        return page

    def _build_bag_shop(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.wallet_shop_label = QLabel()
        font = self.wallet_shop_label.font(); font.setBold(True); self.wallet_shop_label.setFont(font)
        layout.addWidget(self.wallet_shop_label)

        self.bag_label = QLabel()
        layout.addWidget(self.bag_label)

        actions = QGridLayout()
        self.use_candy_btn = QPushButton("Use Rare Candy")
        self.use_mint_btn = QPushButton("Use Mint")
        self.buy_candy_btn = QPushButton("Buy Rare Candy · 500M")
        self.buy_mint_btn = QPushButton("Buy Mint · 100M")
        self.buy_charm_btn = QPushButton("Buy Shiny Charm · 3B")
        self.buy_egg_btn = QPushButton("Buy Egg · 1B")
        self.buy_uncommon_egg_btn = QPushButton(f"Buy Uncommon Egg · {compact_tokens(egg_price('uncommon'))}")
        self.buy_rare_egg_btn = QPushButton(f"Buy Rare Egg · {compact_tokens(egg_price('rare'))}")
        for index, button in enumerate([
            self.use_candy_btn, self.use_mint_btn, self.buy_candy_btn, self.buy_mint_btn,
            self.buy_charm_btn, self.buy_egg_btn, self.buy_uncommon_egg_btn, self.buy_rare_egg_btn,
        ]):
            actions.addWidget(button, index // 2, index % 2)
        layout.addLayout(actions)
        layout.addStretch(1)
        return root

    def _build_settings(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        row = QHBoxLayout()
        row.addWidget(QLabel("Refresh interval"))
        self.interval_combo = QComboBox()
        for minutes in (1, 2, 5, 10, 15):
            self.interval_combo.addItem(f"{minutes} min", minutes)
        current = int(self.settings.value("refresh_minutes", 5))
        idx = self.interval_combo.findData(current)
        self.interval_combo.setCurrentIndex(max(0, idx))
        self.interval_combo.currentIndexChanged.connect(self._save_interval)
        row.addWidget(self.interval_combo)
        row.addStretch(1)
        layout.addLayout(row)

        self.autostart_check = QCheckBox("Start automatically after login")
        self.autostart_check.setChecked(_autostart_enabled())
        self.autostart_check.toggled.connect(self._toggle_autostart)
        layout.addWidget(self.autostart_check)

        notifications_heading = QLabel("Notifications")
        notifications_font = notifications_heading.font()
        notifications_font.setBold(True)
        notifications_heading.setFont(notifications_font)
        layout.addWidget(notifications_heading)

        self.limit_notifications_check = QCheckBox("Limit alerts")
        self.limit_notifications_check.setChecked(
            settings_bool(
                self.settings.value(LIMIT_NOTIFICATIONS_KEY, DEFAULT_LIMIT_NOTIFICATIONS),
                DEFAULT_LIMIT_NOTIFICATIONS,
            )
        )
        self.limit_notifications_check.toggled.connect(self._limit_notifications_toggled)
        layout.addWidget(self.limit_notifications_check)

        self.warning_threshold_row = QWidget()
        warning_layout = QHBoxLayout(self.warning_threshold_row)
        warning_layout.setContentsMargins(20, 0, 0, 0)
        warning_layout.addWidget(QLabel("Warning"))
        self.warning_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.warning_threshold_slider.setRange(WARNING_MIN, WARNING_MAX)
        self.warning_threshold_slider.setSingleStep(THRESHOLD_STEP)
        self.warning_threshold_slider.setPageStep(THRESHOLD_STEP)
        warning_value = normalize_warning_threshold(
            self.settings.value(WARNING_THRESHOLD_KEY, DEFAULT_WARNING_THRESHOLD)
        )
        self.warning_threshold_slider.setValue(warning_value)
        self.warning_threshold_value = QLabel(f"{warning_value}%")
        self.warning_threshold_value.setMinimumWidth(38)
        self.warning_threshold_slider.valueChanged.connect(self._warning_threshold_value_changed)
        warning_layout.addWidget(self.warning_threshold_slider, 1)
        warning_layout.addWidget(self.warning_threshold_value)
        layout.addWidget(self.warning_threshold_row)

        self.critical_threshold_row = QWidget()
        critical_layout = QHBoxLayout(self.critical_threshold_row)
        critical_layout.setContentsMargins(20, 0, 0, 0)
        critical_layout.addWidget(QLabel("Critical"))
        self.critical_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.critical_threshold_slider.setRange(CRITICAL_MIN, CRITICAL_MAX)
        self.critical_threshold_slider.setSingleStep(THRESHOLD_STEP)
        self.critical_threshold_slider.setPageStep(THRESHOLD_STEP)
        critical_value = normalize_critical_threshold(
            self.settings.value(CRITICAL_THRESHOLD_KEY, DEFAULT_CRITICAL_THRESHOLD)
        )
        self.critical_threshold_slider.setValue(critical_value)
        self.critical_threshold_value = QLabel(f"{critical_value}%")
        self.critical_threshold_value.setMinimumWidth(38)
        self.critical_threshold_slider.valueChanged.connect(self._critical_threshold_value_changed)
        critical_layout.addWidget(self.critical_threshold_slider, 1)
        critical_layout.addWidget(self.critical_threshold_value)
        layout.addWidget(self.critical_threshold_row)

        self.companion_notifications_check = QCheckBox(
            "Companion events (hatch / evolve / graduate)"
        )
        self.companion_notifications_check.setChecked(
            settings_bool(
                self.settings.value(
                    COMPANION_NOTIFICATIONS_KEY,
                    DEFAULT_COMPANION_NOTIFICATIONS,
                ),
                DEFAULT_COMPANION_NOTIFICATIONS,
            )
        )
        self.companion_notifications_check.toggled.connect(
            self.companion_notifications_changed.emit
        )
        layout.addWidget(self.companion_notifications_check)
        self._set_limit_threshold_rows_visible(self.limit_notifications_check.isChecked())

        pet_heading = QLabel("Floating desktop pet")
        pet_font = pet_heading.font()
        pet_font.setBold(True)
        pet_heading.setFont(pet_font)
        layout.addWidget(pet_heading)

        self.floating_pet_check = QCheckBox("Show the interactive pet on the desktop")
        self.floating_pet_check.setChecked(
            settings_bool(self.settings.value(PET_ENABLED_KEY, False), False)
        )
        self.floating_pet_check.toggled.connect(self._pet_enabled_toggled)
        layout.addWidget(self.floating_pet_check)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Pet size"))
        self.pet_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.pet_size_slider.setRange(PET_MIN_SIZE, PET_MAX_SIZE)
        self.pet_size_slider.setSingleStep(PET_SIZE_STEP)
        self.pet_size_slider.setPageStep(PET_SIZE_STEP)
        self.pet_size_slider.setTickInterval(PET_SIZE_STEP)
        initial_size = normalize_pet_size(self.settings.value(PET_SIZE_KEY, PET_DEFAULT_SIZE))
        self.pet_size_slider.setValue(initial_size)
        self.pet_size_slider.valueChanged.connect(self._pet_size_value_changed)
        self.pet_size_value = QLabel(f"{initial_size}px")
        self.pet_size_value.setMinimumWidth(42)
        size_row.addWidget(self.pet_size_slider, 1)
        size_row.addWidget(self.pet_size_value)
        layout.addLayout(size_row)

        self.floating_pet_alerts_check = QCheckBox("Show transient usage and full-reset bubbles")
        self.floating_pet_alerts_check.setChecked(
            settings_bool(self.settings.value(PET_ALERTS_KEY, True), True)
        )
        self.floating_pet_alerts_check.toggled.connect(self.floating_pet_alerts_changed.emit)
        layout.addWidget(self.floating_pet_alerts_check)

        representative_row = QHBoxLayout()
        representative_row.addWidget(QLabel("Pet Pokémon"))
        self.representative_combo = QComboBox()
        self.representative_combo.setMinimumWidth(220)
        self.representative_combo.currentIndexChanged.connect(self._representative_selection_changed)
        representative_row.addWidget(self.representative_combo, 1)
        layout.addLayout(representative_row)
        self._render_representative_settings()
        self._set_pet_controls_enabled(self.floating_pet_check.isChecked())

        note = QLabel(
            "Data is read locally from supported AI coding tools. Pokemon metadata and sprites are fetched "
            "from PokeAPI/PokeAPI sprites. Claude/Codex official limit checks use their existing local credentials/processes."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return root

    def _save_interval(self) -> None:
        self.settings.setValue("refresh_minutes", self.interval_combo.currentData())
        self.refresh_requested.emit()

    def _toggle_autostart(self, enabled: bool) -> None:
        try:
            _set_autostart(enabled)
        except OSError as exc:
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not enabled)
            self.autostart_check.blockSignals(False)
            QMessageBox.warning(self, "Autostart", str(exc))

    def _limit_notifications_toggled(self, enabled: bool) -> None:
        self._set_limit_threshold_rows_visible(enabled)
        self.limit_notifications_changed.emit(enabled)

    def _set_limit_threshold_rows_visible(self, visible: bool) -> None:
        self.warning_threshold_row.setVisible(visible)
        self.critical_threshold_row.setVisible(visible)

    def _warning_threshold_value_changed(self, value: int) -> None:
        normalized = normalize_warning_threshold(value)
        if normalized != value:
            self.warning_threshold_slider.blockSignals(True)
            self.warning_threshold_slider.setValue(normalized)
            self.warning_threshold_slider.blockSignals(False)
        self.warning_threshold_value.setText(f"{normalized}%")
        self.warning_threshold_changed.emit(normalized)

    def _critical_threshold_value_changed(self, value: int) -> None:
        normalized = normalize_critical_threshold(value)
        if normalized != value:
            self.critical_threshold_slider.blockSignals(True)
            self.critical_threshold_slider.setValue(normalized)
            self.critical_threshold_slider.blockSignals(False)
        self.critical_threshold_value.setText(f"{normalized}%")
        self.critical_threshold_changed.emit(normalized)

    def _pet_enabled_toggled(self, enabled: bool) -> None:
        self._set_pet_controls_enabled(enabled)
        self.floating_pet_enabled_changed.emit(enabled)

    def _set_pet_controls_enabled(self, enabled: bool) -> None:
        self.pet_size_slider.setEnabled(enabled)
        self.pet_size_value.setEnabled(enabled)
        self.floating_pet_alerts_check.setEnabled(enabled)

    def _pet_size_value_changed(self, value: int) -> None:
        normalized = normalize_pet_size(value)
        if normalized != value:
            self.pet_size_slider.blockSignals(True)
            self.pet_size_slider.setValue(normalized)
            self.pet_size_slider.blockSignals(False)
        self.pet_size_value.setText(f"{normalized}px")
        self.floating_pet_size_changed.emit(normalized)

    def _representative_selection_changed(self, index: int) -> None:
        if index < 0:
            return
        self.representative_changed.emit(self.representative_combo.itemData(index))

    def _render_representative_settings(self) -> None:
        if not hasattr(self, "representative_combo"):
            return
        selected = (
            None
            if self.state.representative_species_id is None
            else (self.state.representative_species_id, bool(self.state.representative_is_shiny))
        )
        self.representative_combo.blockSignals(True)
        self.representative_combo.clear()
        self.representative_combo.addItem("Current egg / Pokémon", None)
        selected_index = 0
        for subject in owned_representative_options(self.state):
            assert subject.species_id is not None
            name = self.api.localized_name(subject.species_id, self.state.language)
            label = f"{'✨ ' if subject.is_shiny else ''}#{subject.species_id:03d} {name}"
            data = (subject.species_id, subject.is_shiny)
            self.representative_combo.addItem(label, data)
            if data == selected:
                selected_index = self.representative_combo.count() - 1
        self.representative_combo.setCurrentIndex(selected_index)
        self.representative_combo.blockSignals(False)

    def sync_floating_pet_settings(self, *, enabled: bool | None = None, size: int | None = None) -> None:
        if enabled is not None and self.floating_pet_check.isChecked() != enabled:
            self.floating_pet_check.blockSignals(True)
            self.floating_pet_check.setChecked(enabled)
            self.floating_pet_check.blockSignals(False)
            self._set_pet_controls_enabled(enabled)
        if size is not None and self.pet_size_slider.value() != size:
            self.pet_size_slider.blockSignals(True)
            self.pet_size_slider.setValue(size)
            self.pet_size_slider.blockSignals(False)
            self.pet_size_value.setText(f"{size}px")

    def set_state(self, state: GameState) -> None:
        self.state = state
        self._render_bag_shop()
        self._render_collection()
        self._render_representative_settings()

    def render(self, result: RefreshResult) -> None:
        self.state = result.state
        snapshot = result.snapshot
        self.today_card.value.setText(compact_tokens(snapshot.today_tokens))
        self.cost_card.value.setText(money(snapshot.today_cost))
        self.week_card.value.setText(compact_tokens(snapshot.week_tokens))
        self.wallet_card.value.setText(compact_tokens(result.state.wallet))

        self.providers_list.clear()
        if not snapshot.providers:
            self.providers_list.addItem("No supported local usage logs found yet")
        for key, usage in sorted(snapshot.providers.items(), key=lambda item: item[1].today_tokens, reverse=True):
            label = PROVIDER_LABELS.get(key, key.title())
            self.providers_list.addItem(
                f"{label}: {compact_tokens(usage.today_tokens)} today · "
                f"{compact_tokens(usage.week_tokens)} week · {money(usage.today_cost)}"
            )
        for key, error in result.scan_errors.items():
            self.providers_list.addItem(f"{PROVIDER_LABELS.get(key, key)} scan warning: {error}")

        self.limits_list.clear()
        any_limits = False
        for key, limits in result.limits.items():
            label = PROVIDER_LABELS.get(key, key.title())
            for row in provider_limit_rows(label, limits):
                any_limits = True
                item = QListWidgetItem(row.text)
                if row.urgency != "neutral":
                    item.setForeground(QColor("#b91c1c" if row.urgency == "critical" else "#b45309"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.limits_list.addItem(item)
        if not any_limits:
            self.limits_list.addItem("No official limit data available")

        self.name_label.setText(result.display_name)
        if result.state.mon is None:
            self.detail_label.setText("Pokemon Egg" + (f" · {result.state.egg_tier.title()}+" if result.state.egg_tier else ""))
            value = result.state.egg_usage
            target = EGG_HATCH_THRESHOLD
            self._set_sprite(result.sprite_path, egg=True)
        else:
            mon = result.state.mon
            shiny = "✨ " if mon.is_shiny else ""
            self.detail_label.setText(f"{shiny}{mon.rarity.title()} · {mon.nature} nature · stage {mon.stage_index + 1}/{len(mon.path_ids)}")
            value = mon.used_at_stage
            target = phase_threshold(mon.rarity, len(mon.path_ids), mon.stage_index)
            self._set_sprite(result.sprite_path)
        ratio = min(1.0, value / max(1, target))
        self.progress.setValue(round(ratio * 1000))
        self.progress_label.setText(f"{compact_tokens(value)} / {compact_tokens(target)}")
        self._render_collection()
        self._render_bag_shop()
        self._render_representative_settings()
        self.refresh_button.setEnabled(True)

    def _set_sprite(self, path: Path | None, *, egg: bool = False) -> None:
        if self.movie is not None:
            self.movie.stop()
            self.movie = None
        if path is not None and path.exists():
            if path.suffix.lower() == ".gif":
                movie = QMovie(str(path))
                movie.setScaledSize(QSize(112, 112))
                self.sprite.setPixmap(QPixmap())
                self.sprite.setMovie(movie)
                self.movie = movie
                movie.start()
                return
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.sprite.setMovie(QMovie())
                self.sprite.setPixmap(
                    pix.scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
                )
                return
        self.sprite.setMovie(QMovie())
        self.sprite.setPixmap(_egg_pixmap(112) if egg else _pokeball_pixmap(112))

    def _render_collection(self) -> None:
        _clear_layout(self.dex_grid)
        _clear_layout(self.catch_list)
        catches = list(self.state.catches)
        self.dex_empty.setVisible(not catches)
        self.catch_empty.setVisible(not catches)
        if not catches:
            return

        current = self._current_catch()
        owned = self._owned_species()
        for column, species_id in enumerate(sorted(owned)):
            self.dex_grid.addWidget(
                self._dex_cell(species_id, shiny=owned[species_id]),
                column // 4,
                column % 4,
            )

        for catch in reversed(catches):
            self.catch_list.addWidget(self._catch_card(catch, current is catch))

    def _current_catch(self):
        mon = self.state.mon
        if mon is None:
            return None
        for catch in reversed(self.state.catches):
            if catch.base_id == mon.base_id and catch.nature == mon.nature and catch.is_shiny == mon.is_shiny:
                return catch
        return None

    def _owned_species(self) -> dict[int, bool]:
        owned: dict[int, bool] = {}
        for subject in owned_representative_options(self.state):
            assert subject.species_id is not None
            owned[subject.species_id] = owned.get(subject.species_id, False) or subject.is_shiny
        return owned

    def _dex_cell(self, species_id: int, *, shiny: bool) -> QFrame:
        cell = QFrame()
        cell.setFrameShape(QFrame.Shape.StyledPanel)
        cell.setStyleSheet("QFrame { background: #f7f5f2; border: 1px solid #e7e2da; border-radius: 12px; }")
        layout = QVBoxLayout(cell)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sprite = QLabel()
        sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sprite.setFixedSize(80, 80)
        path = self.api.sprite_path(species_id, shiny=shiny, animated=False)
        pix = _sprite_pixmap(path, 72)
        sprite.setPixmap(pix if not pix.isNull() else _pokeball_pixmap(72))
        name = QLabel(self.api.localized_name(species_id, self.state.language))
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = name.font()
        font.setBold(True)
        name.setFont(font)
        number = QLabel(f"{'✨ ' if shiny else ''}#{species_id:03d}")
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number.setStyleSheet("color: #6b7280;")
        layout.addWidget(sprite)
        layout.addWidget(number)
        layout.addWidget(name)
        return cell

    def _catch_card(self, catch, is_current: bool) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet("QFrame { background: #fbfaf8; border: 1px solid #e7e2da; border-radius: 14px; }")
        layout = QVBoxLayout(card)
        path_ids = catch.path_ids or [catch.species_id]
        owned_index = self.state.mon.stage_index if (is_current and self.state.mon is not None) else len(path_ids) - 1
        owned_index = max(0, min(owned_index, len(path_ids) - 1))
        display_id = path_ids[owned_index]
        owned_name = self.api.localized_name(display_id, self.state.language)

        header = QHBoxLayout()
        title = QLabel(owned_name)
        tf = title.font()
        tf.setPointSize(tf.pointSize() + 3)
        tf.setBold(True)
        title.setFont(tf)
        header.addWidget(title)
        header.addStretch(1)
        owned_badge = QLabel("Owned")
        owned_badge.setStyleSheet("QLabel { background: #dcfce7; color: #166534; border-radius: 8px; padding: 2px 8px; }")
        header.addWidget(owned_badge)
        if is_current:
            badge = QLabel("Current")
            badge.setStyleSheet("QLabel { background: #dbeafe; color: #1d4ed8; border-radius: 8px; padding: 2px 8px; }")
            header.addWidget(badge)
        if catch.is_shiny:
            header.addWidget(QLabel("✨"))
        layout.addLayout(header)

        summary = QLabel(
            f"You have {owned_name} only · stage {owned_index + 1} of {len(path_ids)}"
            if owned_index + 1 < len(path_ids)
            else f"Fully evolved {owned_name}"
        )
        summary.setStyleSheet("color: #4b5563;")
        layout.addWidget(summary)

        line = QHBoxLayout()
        line.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for index, species_id in enumerate(path_ids):
            if index:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #9ca3af; font-size: 16px;")
                line.addWidget(arrow)
            have = index <= owned_index
            current_stage = index == owned_index
            stage = QWidget()
            stage_layout = QVBoxLayout(stage)
            stage_layout.setContentsMargins(0, 0, 0, 0)
            stage_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sprite = QLabel()
            sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sprite.setFixedSize(72, 72)
            path = self.api.sprite_path(species_id, shiny=catch.is_shiny, animated=False) if have else self.api.sprite_path(species_id, animated=False)
            pix = _sprite_pixmap(path, 64)
            if pix.isNull():
                pix = _pokeball_pixmap(64)
            if not have:
                pix = _muted_pixmap(pix)
            sprite.setPixmap(pix)
            if current_stage:
                sprite.setStyleSheet("QLabel { background: #dcfce7; border: 2px solid #16a34a; border-radius: 10px; }")
            elif not have:
                sprite.setStyleSheet("QLabel { background: #f3f4f6; border-radius: 10px; }")
            if have:
                stage_name = QLabel(self.api.localized_name(species_id, self.state.language))
                status = QLabel("You have this" if current_stage else "Previous form")
                status.setStyleSheet("color: #166534;" if current_stage else "color: #6b7280;")
            else:
                stage_name = QLabel("???")
                status = QLabel("Not owned")
                status.setStyleSheet("color: #9ca3af;")
                stage_name.setStyleSheet("color: #9ca3af;")
            stage_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stage_layout.addWidget(sprite)
            stage_layout.addWidget(stage_name)
            stage_layout.addWidget(status)
            line.addWidget(stage)
        line.addStretch(1)
        layout.addLayout(line)

        meta = QLabel(
            f"#{display_id:03d} · {catch.rarity.title()} · {catch.nature} · {catch.caught_at[:10]}"
        )
        meta.setStyleSheet("color: #6b7280;")
        layout.addWidget(meta)
        return card

    def _render_bag_shop(self) -> None:
        self.wallet_shop_label.setText(f"Wallet: {compact_tokens(self.state.wallet)} tokens")
        inv = self.state.inventory
        self.bag_label.setText(
            f"Bag: 🍬 {inv.get('rare_candy', 0)} Rare Candy · 🌿 {inv.get('mint', 0)} Mint · "
            f"✨ {'active' if self.state.shiny_charm_active else 'no Shiny Charm'}"
        )
        self.use_candy_btn.setEnabled(inv.get("rare_candy", 0) > 0)
        self.use_mint_btn.setEnabled(inv.get("mint", 0) > 0 and self.state.mon is not None)
        self.buy_charm_btn.setEnabled(not self.state.shiny_charm_active)


class TrayController(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = application_settings()
        self.store = StateStore()
        self.state = self.store.load()
        self.api = PokeAPIClient(_data_cache_dir())
        self.state_lock = threading.Lock()
        self.bridge = Bridge()
        self.bridge.refreshed.connect(self._on_refreshed)
        self.bridge.failed.connect(self._on_failed)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="poketokenbar-refresh")
        self.refresh_running = False
        self.refresh_pending = False
        self.last_result: RefreshResult | None = None
        self.qa_capture_scheduled = False
        self.limit_alert_tiers: dict[str, int] = {}
        self.limit_notifications_enabled = settings_bool(
            self.settings.value(LIMIT_NOTIFICATIONS_KEY, DEFAULT_LIMIT_NOTIFICATIONS),
            DEFAULT_LIMIT_NOTIFICATIONS,
        )
        self.companion_notifications_enabled = settings_bool(
            self.settings.value(
                COMPANION_NOTIFICATIONS_KEY,
                DEFAULT_COMPANION_NOTIFICATIONS,
            ),
            DEFAULT_COMPANION_NOTIFICATIONS,
        )
        self.warning_threshold = normalize_warning_threshold(
            self.settings.value(WARNING_THRESHOLD_KEY, DEFAULT_WARNING_THRESHOLD)
        )
        self.critical_threshold = normalize_critical_threshold(
            self.settings.value(CRITICAL_THRESHOLD_KEY, DEFAULT_CRITICAL_THRESHOLD)
        )

        self.window = MainWindow(self.state, self.settings, self.api)
        self.window.refresh_requested.connect(self._refresh_and_reschedule)
        self.window.limit_notifications_changed.connect(self._set_limit_notifications)
        self.window.warning_threshold_changed.connect(self._set_warning_threshold)
        self.window.critical_threshold_changed.connect(self._set_critical_threshold)
        self.window.companion_notifications_changed.connect(self._set_companion_notifications)
        self._wire_shop_buttons()

        self.tray = QSystemTrayIcon(_pokeball_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        open_action = QAction("Open PokeTokenBar", self)
        open_action.triggered.connect(self.show_window)
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(open_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.floating_pet = FloatingPetController(
            self.app,
            self.settings,
            self.show_window,
            warning_percent=self.warning_threshold,
            critical_percent=self.critical_threshold,
        )
        self.window.floating_pet_enabled_changed.connect(self.floating_pet.set_enabled)
        self.window.floating_pet_size_changed.connect(self.floating_pet.set_size)
        self.window.floating_pet_alerts_changed.connect(self.floating_pet.set_alerts_enabled)
        self.window.representative_changed.connect(self._select_representative)
        self.floating_pet.enabled_changed.connect(
            lambda enabled: self.window.sync_floating_pet_settings(enabled=enabled)
        )
        self.floating_pet.size_changed.connect(
            lambda size: self.window.sync_floating_pet_settings(size=size)
        )
        self.window.sync_floating_pet_settings(
            enabled=self.floating_pet.enabled,
            size=self.floating_pet.size,
        )

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self._reschedule()
        QTimer.singleShot(0, self.refresh)

    def _wire_shop_buttons(self) -> None:
        self.window.use_candy_btn.clicked.connect(lambda: self._use_item("rare_candy"))
        self.window.use_mint_btn.clicked.connect(lambda: self._use_item("mint"))
        self.window.buy_candy_btn.clicked.connect(lambda: self._buy_item("rare_candy"))
        self.window.buy_mint_btn.clicked.connect(lambda: self._buy_item("mint"))
        self.window.buy_charm_btn.clicked.connect(lambda: self._buy_item("shiny_charm"))
        self.window.buy_egg_btn.clicked.connect(lambda: self._buy_egg(None))
        self.window.buy_uncommon_egg_btn.clicked.connect(lambda: self._buy_egg("uncommon"))
        self.window.buy_rare_egg_btn.clicked.connect(lambda: self._buy_egg("rare"))

    def _refresh_and_reschedule(self) -> None:
        self._reschedule()
        self.refresh()

    def _reschedule(self) -> None:
        minutes = int(self.settings.value("refresh_minutes", 5))
        self.timer.start(max(1, minutes) * 60_000)

    def _set_limit_notifications(self, enabled: bool) -> None:
        self.limit_notifications_enabled = bool(enabled)
        self.settings.setValue(LIMIT_NOTIFICATIONS_KEY, self.limit_notifications_enabled)
        self.settings.sync()

    def _set_companion_notifications(self, enabled: bool) -> None:
        self.companion_notifications_enabled = bool(enabled)
        self.settings.setValue(
            COMPANION_NOTIFICATIONS_KEY,
            self.companion_notifications_enabled,
        )
        self.settings.sync()

    def _set_warning_threshold(self, value: int) -> None:
        self.warning_threshold = normalize_warning_threshold(value)
        self.settings.setValue(WARNING_THRESHOLD_KEY, self.warning_threshold)
        self.settings.sync()
        self.floating_pet.set_alert_thresholds(
            self.warning_threshold,
            self.critical_threshold,
        )

    def _set_critical_threshold(self, value: int) -> None:
        self.critical_threshold = normalize_critical_threshold(value)
        self.settings.setValue(CRITICAL_THRESHOLD_KEY, self.critical_threshold)
        self.settings.sync()
        self.floating_pet.set_alert_thresholds(
            self.warning_threshold,
            self.critical_threshold,
        )

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self.window.show()
        apply_native_window_icon(int(self.window.winId()), cache_dir() / "app.ico")
        self.window.raise_()
        self.window.activateWindow()

    def refresh(self) -> None:
        if self.refresh_running:
            self.refresh_pending = True
            return
        self.refresh_running = True
        self.window.refresh_button.setEnabled(False)
        self.executor.submit(self._refresh_worker)

    def _refresh_worker(self) -> None:
        try:
            snapshot, errors = scan_all()
            limits = fetch_all_limits()
            with self.state_lock:
                candidate = copy.deepcopy(self.state)
                delta = usage_delta(
                    candidate,
                    {provider: usage.today_tokens for provider, usage in snapshot.providers.items()},
                )
                events = apply_usage(candidate, delta, self.api) if delta else []
                events.extend(apply_limit_rewards(candidate, limits))
                mon = candidate.mon
                sprite = self.api.sprite_path(mon.current_id, shiny=mon.is_shiny) if mon else self.api.egg_sprite_path()
                pet_subject = representative_subject(candidate)
                pet_sprite = (
                    self.api.sprite_path(pet_subject.species_id, shiny=pet_subject.is_shiny)
                    if pet_subject.species_id is not None else self.api.egg_sprite_path()
                )
                self._prefetch_collection(candidate)
                display_name = self.api.localized_name(mon.current_id, candidate.language) if mon else "Pokemon Egg"
                pet_display_name = (
                    self.api.localized_name(pet_subject.species_id, candidate.language)
                    if pet_subject.species_id is not None else "Pokemon Egg"
                )
                self.store.save(candidate)
                self.state = candidate
                state = candidate
            self.bridge.refreshed.emit(RefreshResult(
                snapshot=snapshot,
                limits=limits,
                scan_errors=errors,
                state=state,
                events=events,
                sprite_path=sprite,
                display_name=display_name,
                pet_sprite_path=pet_sprite,
                pet_display_name=pet_display_name,
                pet_is_egg=pet_subject.is_egg,
            ))
        except Exception as exc:
            self.bridge.failed.emit(f"{type(exc).__name__}: {exc}")

    def _prefetch_collection(self, state: GameState) -> None:
        for catch in state.catches:
            for species_id in catch.path_ids or [catch.species_id]:
                try:
                    self.api.localized_name(species_id, state.language)
                    self.api.sprite_path(species_id, shiny=catch.is_shiny, animated=False)
                except Exception:
                    continue

    def _on_refreshed(self, result: RefreshResult) -> None:
        self.refresh_running = False
        self.last_result = result
        self.window.render(result)
        self.tray.setIcon(_pokeball_icon())
        self.tray.setToolTip(tray_tooltip(result))
        limit_alerts, self.limit_alert_tiers = evaluate_limit_alerts(
            result.limits,
            self.limit_alert_tiers,
            warning_percent=self.warning_threshold,
            critical_percent=self.critical_threshold,
        )
        if self.limit_notifications_enabled:
            for alert in limit_alerts:
                provider = PROVIDER_LABELS.get(alert.provider, alert.provider.title())
                title = "Limit imminent" if alert.severity == "critical" else "Limit warning"
                icon = (
                    QSystemTrayIcon.MessageIcon.Critical
                    if alert.severity == "critical"
                    else QSystemTrayIcon.MessageIcon.Warning
                )
                self.tray.showMessage(
                    title,
                    f"{provider} {alert.window_label} at {alert.used_percent:.0f}%",
                    icon,
                    6_000,
                )
        self.floating_pet.update(result)
        self._schedule_qa_capture()
        if self.companion_notifications_enabled:
            for event in result.events:
                notification = companion_notification(event, result.display_name)
                if notification is None:
                    continue
                if notification.use_sprite_icon:
                    icon = _icon_from_sprite(result.sprite_path)
                else:
                    icon = QSystemTrayIcon.MessageIcon.Information
                self.tray.showMessage(notification.title, notification.body, icon, 5_000)
        if self.refresh_pending:
            self.refresh_pending = False
            QTimer.singleShot(0, self.refresh)

    def _schedule_qa_capture(self) -> None:
        target = os.environ.get("PTB_QA_ARTIFACT_DIR", "").strip()
        if not target or self.qa_capture_scheduled:
            return
        self.qa_capture_scheduled = True
        QTimer.singleShot(1_000, lambda: self._write_qa_artifacts(Path(target)))

    def _write_qa_artifacts(self, target: Path) -> None:
        try:
            target.mkdir(parents=True, exist_ok=True)
            main_path = target / "main-window.png"
            settings_path = target / "settings-tab.png"
            pet_path = target / "floating-pet.png"
            hover_path = target / "hover-callout.png"
            self.window.grab().save(str(main_path), "PNG")
            tabs = self.window.centralWidget()
            if isinstance(tabs, QTabWidget):
                current_tab = tabs.currentIndex()
                tabs.setCurrentIndex(tabs.count() - 1)
                QApplication.processEvents()
                self.window.grab().save(str(settings_path), "PNG")
                tabs.setCurrentIndex(current_tab)
            self.floating_pet.pet.grab().save(str(pet_path), "PNG")
            self.floating_pet.hover.grab().save(str(hover_path), "PNG")
            report = {
                "pid": os.getpid(),
                "executable": sys.executable,
                "frozen": bool(getattr(sys, "frozen", False)),
                "settings_file": self.settings.fileName(),
                "state_file": str(self.store.path),
                "main_visible": self.window.isVisible(),
                "main_size": [self.window.width(), self.window.height()],
                "tray_visible": self.tray.isVisible(),
                "tray_tooltip": self.tray.toolTip(),
                "notifications": {
                    "limit_alerts": self.limit_notifications_enabled,
                    "warning_threshold": self.warning_threshold,
                    "critical_threshold": self.critical_threshold,
                    "companion_events": self.companion_notifications_enabled,
                    "deduplicated_limit_windows": len(self.limit_alert_tiers),
                },
                "pet": self.floating_pet.qa_snapshot(),
            }
            tmp = target / "qa-report.tmp"
            tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
            tmp.replace(target / "qa-report.json")
        except Exception:
            self.qa_capture_scheduled = False

    def _on_failed(self, message: str) -> None:
        self.refresh_running = False
        self.window.refresh_button.setEnabled(True)
        self.tray.showMessage("PokeTokenBar refresh failed", message, QSystemTrayIcon.MessageIcon.Warning, 5000)
        if self.refresh_pending:
            self.refresh_pending = False
            QTimer.singleShot(0, self.refresh)

    def _mutate_state(self, operation: Callable[[GameState], tuple[bool, str] | tuple[bool, str, list[str]]]) -> bool:
        try:
            with self.state_lock:
                candidate = copy.deepcopy(self.state)
                outcome = operation(candidate)
                ok = bool(outcome[0])
                message = str(outcome[1])
                events = outcome[2] if len(outcome) > 2 else []
                if ok:
                    self.store.save(candidate)
                    self.state = candidate
        except Exception as exc:
            QMessageBox.warning(self.window, "PokeTokenBar", f"{type(exc).__name__}: {exc}")
            return False
        if not ok:
            QMessageBox.information(self.window, "PokeTokenBar", message)
            return False
        self.window.set_state(self.state)
        if events:
            self.refresh()
        return True

    def _buy_item(self, item: str) -> None:
        self._mutate_state(lambda state: buy_item(state, item))

    def _use_item(self, item: str) -> None:
        self._mutate_state(lambda state: use_item(state, item, self.api))

    def _buy_egg(self, tier: str | None) -> None:
        if self._mutate_state(lambda state: buy_egg(state, tier)):
            self.refresh()

    def _select_representative(self, selection: object) -> None:
        species_id: int | None = None
        is_shiny: bool | None = None
        if isinstance(selection, tuple) and len(selection) == 2:
            species_id = int(selection[0])
            is_shiny = bool(selection[1])
        try:
            with self.state_lock:
                candidate = copy.deepcopy(self.state)
                if not set_representative(candidate, species_id, is_shiny):
                    QMessageBox.information(
                        self.window,
                        "PokeTokenBar",
                        "That Pokémon is not currently owned.",
                    )
                    self.window.set_state(self.state)
                    return
                self.store.save(candidate)
                self.state = candidate
        except Exception as exc:
            QMessageBox.warning(self.window, "PokeTokenBar", f"{type(exc).__name__}: {exc}")
            return
        self.window.set_state(self.state)
        self.refresh()

    def quit(self) -> None:
        self.store.save(self.state)
        self.floating_pet.shutdown()
        self.tray.hide()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.app.quit()

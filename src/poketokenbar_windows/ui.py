from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QMovie, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .formatting import compact_tokens, money
from .limits import fetch_all_limits
from .models import ProviderLimits, UsageSnapshot
from .pokemon import EGG_HATCH_THRESHOLD, PokeAPIClient, egg_price, phase_threshold
from .state import GameState, StateStore, apply_limit_rewards, apply_usage, buy_egg, buy_item, usage_delta, use_item
from .usage import PROVIDER_LABELS, scan_all
from .windows import apply_native_window_icon, autostart_enabled, cache_dir, set_autostart


@dataclass(slots=True)
class RefreshResult:
    snapshot: UsageSnapshot
    limits: dict[str, ProviderLimits]
    scan_errors: dict[str, str]
    state: GameState
    events: list[str]
    sprite_path: Path | None
    display_name: str


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

    def __init__(self, state: GameState, settings: QSettings):
        super().__init__()
        self.state = state
        self.settings = settings
        self.movie: QMovie | None = None
        self.setWindowTitle("PokeTokenBar Windows")
        self.setWindowIcon(application_icon())
        self.setMinimumSize(480, 620)
        self.resize(520, 700)

        tabs = QTabWidget()
        tabs.addTab(self._build_home(), "Home")
        tabs.addTab(self._build_collection(), "Collection")
        tabs.addTab(self._build_bag_shop(), "Bag & Shop")
        tabs.addTab(self._build_settings(), "Settings")
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
        self.collection_list = QListWidget()
        layout.addWidget(self.collection_list)
        return root

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

    def set_state(self, state: GameState) -> None:
        self.state = state
        self._render_bag_shop()
        self._render_collection()

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
            for window in limits.windows:
                any_limits = True
                reset = window.resets_at.strftime("%a %H:%M") if window.resets_at else "reset unknown"
                plan = f" · {limits.plan}" if limits.plan else ""
                self.limits_list.addItem(f"{label}{plan} · {window.label}: {window.used_percent:.0f}% · {reset}")
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
        self.collection_list.clear()
        if not self.state.catches:
            self.collection_list.addItem("No Pokemon hatched yet")
            return
        for catch in reversed(self.state.catches):
            shiny = "✨ " if catch.is_shiny else ""
            current = catch.species_id
            self.collection_list.addItem(
                f"{shiny}#{current} · {catch.rarity.title()} · {catch.nature} · {catch.caught_at[:10]}"
            )

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
        self.settings = QSettings("PokeTokenBar", "PokeTokenBar-Windows")
        self.store = StateStore()
        self.state = self.store.load()
        self.api = PokeAPIClient(_data_cache_dir())
        self.state_lock = threading.Lock()
        self.bridge = Bridge()
        self.bridge.refreshed.connect(self._on_refreshed)
        self.bridge.failed.connect(self._on_failed)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="poketokenbar-refresh")
        self.refresh_running = False
        self.last_result: RefreshResult | None = None

        self.window = MainWindow(self.state, self.settings)
        self.window.refresh_requested.connect(self._refresh_and_reschedule)
        self._wire_shop_buttons()

        self.tray = QSystemTrayIcon(_pokeball_icon(), self)
        self.tray.setToolTip("PokeTokenBar Windows")
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
                display_name = self.api.localized_name(mon.current_id, candidate.language) if mon else "Pokemon Egg"
                self.store.save(candidate)
                self.state = candidate
                state = candidate
            self.bridge.refreshed.emit(RefreshResult(snapshot, limits, errors, state, events, sprite, display_name))
        except Exception as exc:
            self.bridge.failed.emit(f"{type(exc).__name__}: {exc}")

    def _on_refreshed(self, result: RefreshResult) -> None:
        self.refresh_running = False
        self.last_result = result
        self.window.render(result)
        text = f"{compact_tokens(result.snapshot.today_tokens)} today"
        if result.state.mon:
            text += f" · {result.display_name}"
            if result.sprite_path and result.sprite_path.suffix.lower() == ".png":
                self.tray.setIcon(QIcon(str(result.sprite_path)))
            else:
                self.tray.setIcon(_pokeball_icon())
        else:
            text += " · egg"
            self.tray.setIcon(_pokeball_icon())
        self.tray.setToolTip(f"PokeTokenBar Windows · {text}")
        for event in result.events:
            if event.startswith("hatched:"):
                self.tray.showMessage("Pokemon hatched!", result.display_name, QSystemTrayIcon.MessageIcon.Information, 5000)
            elif event.startswith("evolved:"):
                self.tray.showMessage("Evolution!", result.display_name, QSystemTrayIcon.MessageIcon.Information, 5000)
            elif event.startswith("graduated:"):
                self.tray.showMessage("Pokemon graduated!", "A new egg is ready.", QSystemTrayIcon.MessageIcon.Information, 5000)
            elif event.startswith("candy:"):
                parts = event.split(":", 3)
                count = parts[1] if len(parts) > 1 else "1"
                self.tray.showMessage("Rare Candy earned!", f"You earned {count} Rare Candy.", QSystemTrayIcon.MessageIcon.Information, 5000)

    def _on_failed(self, message: str) -> None:
        self.refresh_running = False
        self.window.refresh_button.setEnabled(True)
        self.tray.showMessage("PokeTokenBar refresh failed", message, QSystemTrayIcon.MessageIcon.Warning, 5000)

    def _mutate_state(self, operation: Callable[[GameState], tuple[bool, str] | tuple[bool, str, list[str]]]) -> None:
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
            return
        if not ok:
            QMessageBox.information(self.window, "PokeTokenBar", message)
            return
        self.window.set_state(self.state)
        if events:
            self.refresh()

    def _buy_item(self, item: str) -> None:
        self._mutate_state(lambda state: buy_item(state, item))

    def _use_item(self, item: str) -> None:
        self._mutate_state(lambda state: use_item(state, item, self.api))

    def _buy_egg(self, tier: str | None) -> None:
        self._mutate_state(lambda state: buy_egg(state, tier))

    def quit(self) -> None:
        self.store.save(self.state)
        self.tray.hide()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.app.quit()

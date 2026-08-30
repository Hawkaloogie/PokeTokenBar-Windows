from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .pokemon import (
    EGG_HATCH_THRESHOLD,
    MINT_PRICE,
    NATURES,
    RARE_CANDY_PRICE,
    RARE_CANDY_XP,
    SHINY_CHARM_PRICE,
    PokeAPIClient,
    egg_price,
    phase_threshold,
)
from .windows import state_dir


@dataclass(slots=True)
class MonState:
    base_id: int
    path_ids: list[int]
    stage_index: int
    used_at_stage: int
    rarity: str
    is_shiny: bool
    nature: str

    @property
    def current_id(self) -> int:
        if not self.path_ids:
            return self.base_id
        return self.path_ids[min(self.stage_index, len(self.path_ids) - 1)]


@dataclass(slots=True)
class CatchRecord:
    species_id: int
    base_id: int
    path_ids: list[int]
    rarity: str
    is_shiny: bool
    nature: str
    caught_at: str


@dataclass(slots=True)
class GameState:
    version: int = 1
    egg_usage: int = 0
    egg_tier: str | None = None
    mon: MonState | None = None
    catches: list[CatchRecord] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=lambda: {"rare_candy": 0, "mint": 0, "shiny_charm": 0})
    install_baseline_set: bool = False
    used_since_install: int = 0
    spent_tokens: int = 0
    claimed_today_tokens_by_provider: dict[str, int] | None = None
    last_day: str = ""  # legacy aggregate baseline (pre-0.1 state)
    last_today_tokens: int = 0  # legacy aggregate baseline (pre-0.1 state)
    representative_species_id: int | None = None
    language: str = "en"
    claimed_limit_windows: list[str] = field(default_factory=list)
    candy_feature_seeded: bool = False

    @property
    def wallet(self) -> int:
        return max(0, self.used_since_install - self.spent_tokens)

    @property
    def shiny_charm_active(self) -> bool:
        return self.inventory.get("shiny_charm", 0) > 0


def companion_progress_percent(state: GameState) -> int:
    """Return whole-percent progress for the active egg or Pokemon stage."""
    if state.mon is None:
        value = state.egg_usage
        target = EGG_HATCH_THRESHOLD
    else:
        mon = state.mon
        value = mon.used_at_stage
        target = phase_threshold(mon.rarity, len(mon.path_ids), mon.stage_index)
    return min(100, max(0, value * 100 // max(1, target)))


class StateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or state_dir() / "state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> GameState:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return GameState()
        if not isinstance(raw, dict):
            return GameState()
        try:
            mon_raw = raw.get("mon")
            mon = MonState(**mon_raw) if isinstance(mon_raw, dict) else None
            catches = [CatchRecord(**item) for item in raw.get("catches", []) if isinstance(item, dict)]
            state = GameState(
                version=int(raw.get("version", 1)),
                egg_usage=int(raw.get("egg_usage", 0)),
                egg_tier=raw.get("egg_tier"),
                mon=mon,
                catches=catches,
                inventory={str(k): int(v) for k, v in (raw.get("inventory") or {}).items()},
                install_baseline_set=bool(raw.get("install_baseline_set", False)),
                used_since_install=int(raw.get("used_since_install", 0)),
                spent_tokens=int(raw.get("spent_tokens", 0)),
                claimed_today_tokens_by_provider=(
                    {str(k): max(0, int(v)) for k, v in raw["claimed_today_tokens_by_provider"].items()}
                    if isinstance(raw.get("claimed_today_tokens_by_provider"), dict) else None
                ),
                last_day=str(raw.get("last_day", "")),
                last_today_tokens=int(raw.get("last_today_tokens", 0)),
                representative_species_id=raw.get("representative_species_id"),
                language=str(raw.get("language", "en")),
                claimed_limit_windows=[str(v) for v in raw.get("claimed_limit_windows", [])],
                candy_feature_seeded=bool(raw.get("candy_feature_seeded", False)),
            )
            for key in ("rare_candy", "mint", "shiny_charm"):
                state.inventory.setdefault(key, 0)
            return state
        except (TypeError, ValueError, AttributeError):
            return GameState()

    def save(self, state: GameState) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


def usage_delta(
    state: GameState,
    today_tokens: int | dict[str, int],
    today: date | None = None,
) -> int:
    """Return newly-observed real token usage without crediting pre-install history.

    Upstream tracks a per-provider high-water mark so a temporarily missing provider
    cannot make another provider's usage look new.  An integer is accepted for the
    small public helper/tests and is treated as one aggregate provider.
    """
    today = today or datetime.now().astimezone().date()
    key = today.isoformat()
    if isinstance(today_tokens, int):
        current = {"__aggregate__": max(0, today_tokens)}
    else:
        current = {str(provider): max(0, int(value)) for provider, value in today_tokens.items()}

    # Do not establish the installation baseline until there is an actual provider
    # snapshot.  The first valid snapshot is a baseline only: tokens used before
    # installing the app are never retroactively granted as growth/shop currency.
    if not state.install_baseline_set:
        if not current:
            return 0
        state.install_baseline_set = True
        state.claimed_today_tokens_by_provider = dict(current)
        state.last_day = key
        state.last_today_tokens = sum(current.values())
        return 0

    ledger = state.claimed_today_tokens_by_provider
    if ledger is None:
        # Migration from an aggregate-only state cannot be split safely.  Seed the
        # current provider values rather than guessing and double-crediting history.
        state.claimed_today_tokens_by_provider = dict(current)
        state.last_day = key
        state.last_today_tokens = sum(current.values())
        return 0

    delta = 0
    if state.last_day != key:
        # Daily counters reset at midnight.  Known providers that are absent from the
        # first refresh keep a zero baseline so their usage is counted if they reappear.
        new_ledger = {provider: 0 for provider in ledger}
        for provider, value in current.items():
            new_ledger[provider] = value
            delta += value
        state.claimed_today_tokens_by_provider = new_ledger
    else:
        for provider, value in current.items():
            previous = ledger.get(provider)
            if previous is None:
                # A newly detected provider is seeded, not retroactively credited.
                ledger[provider] = value
                continue
            if value < previous:
                # Rebase only this provider on log truncation/regression.
                ledger[provider] = value
                continue
            delta += value - previous
            ledger[provider] = value

    state.last_day = key
    state.last_today_tokens = sum(current.values())
    state.used_since_install += delta
    return delta


def apply_usage(state: GameState, delta: int, api: PokeAPIClient) -> list[str]:
    events: list[str] = []
    remaining = max(0, delta)
    while remaining > 0:
        if state.mon is None:
            need = max(0, EGG_HATCH_THRESHOLD - state.egg_usage)
            take = min(remaining, need)
            state.egg_usage += take
            remaining -= take
            if state.egg_usage < EGG_HATCH_THRESHOLD:
                break
            hatch = api.hatch(minimum_rarity=state.egg_tier, shiny_charm=state.shiny_charm_active)
            state.mon = MonState(
                base_id=hatch.base_id,
                path_ids=hatch.path_ids,
                stage_index=0,
                used_at_stage=0,
                rarity=hatch.rarity,
                is_shiny=hatch.is_shiny,
                nature=hatch.nature,
            )
            state.egg_usage = 0
            state.egg_tier = None
            state.catches.append(CatchRecord(
                species_id=hatch.base_id,
                base_id=hatch.base_id,
                path_ids=hatch.path_ids,
                rarity=hatch.rarity,
                is_shiny=hatch.is_shiny,
                nature=hatch.nature,
                caught_at=datetime.now().astimezone().isoformat(),
            ))
            events.append(f"hatched:{hatch.base_id}")
            continue

        mon = state.mon
        threshold = phase_threshold(mon.rarity, len(mon.path_ids), mon.stage_index)
        need = max(0, threshold - mon.used_at_stage)
        take = min(remaining, need)
        mon.used_at_stage += take
        remaining -= take
        if mon.used_at_stage < threshold:
            break
        mon.used_at_stage = 0
        if mon.stage_index < len(mon.path_ids) - 1:
            mon.stage_index += 1
            if state.catches:
                state.catches[-1].species_id = mon.current_id
            events.append(f"evolved:{mon.current_id}")
            continue

        # Final form completed: archive it and start a fresh egg; overflow carries.
        events.append(f"graduated:{mon.current_id}")
        state.mon = None
        state.egg_usage = 0
        state.egg_tier = None
    return events


def buy_item(state: GameState, item: str) -> tuple[bool, str]:
    prices = {"rare_candy": RARE_CANDY_PRICE, "mint": MINT_PRICE, "shiny_charm": SHINY_CHARM_PRICE}
    if item not in prices:
        return False, "Unknown item"
    if item == "shiny_charm" and state.shiny_charm_active:
        return False, "Shiny Charm is already active"
    price = prices[item]
    if state.wallet < price:
        return False, "Not enough tokens"
    state.spent_tokens += price
    state.inventory[item] = state.inventory.get(item, 0) + 1
    return True, "Purchased"


def use_item(state: GameState, item: str, api: PokeAPIClient) -> tuple[bool, str, list[str]]:
    if state.inventory.get(item, 0) <= 0:
        return False, "Item not in bag", []
    if item == "rare_candy":
        state.inventory[item] -= 1
        events = apply_usage(state, RARE_CANDY_XP, api)
        return True, "Rare Candy used", events
    if item == "mint":
        if state.mon is None:
            return False, "No Pokemon to use a Mint on", []
        import random
        options = [nature for nature in NATURES if nature != state.mon.nature]
        state.mon.nature = random.choice(options or NATURES)
        state.inventory[item] -= 1
        if state.catches:
            state.catches[-1].nature = state.mon.nature
        return True, "Nature changed", []
    return False, "Passive items cannot be used", []


def buy_egg(state: GameState, tier: str | None) -> tuple[bool, str]:
    price = egg_price(tier)
    if state.wallet < price:
        return False, "Not enough tokens"
    state.spent_tokens += price
    if state.mon is not None and state.catches:
        # The upstream Pokédex synthesizes the currently-raised Pokemon and only
        # persists it on graduation. Buying a fresh egg discards that active catch.
        last = state.catches[-1]
        if last.base_id == state.mon.base_id and last.path_ids == state.mon.path_ids:
            state.catches.pop()
    state.mon = None
    state.egg_usage = 0
    state.egg_tier = tier
    return True, "Fresh egg ready"


def apply_limit_rewards(state: GameState, limits: dict[str, Any]) -> list[str]:
    """Grant Rare Candy once when an official limit window reaches 100%.

    The first successful limits snapshot is a seed only, matching upstream: an app
    installed while an account is already at 100% must not receive retroactive candy.
    """
    grants: list[str] = []
    claimed = set(state.claimed_limit_windows)
    at_cap: list[tuple[str, Any, str]] = []
    for provider, status in limits.items():
        for window in getattr(status, "windows", []):
            if window.used_percent < 100:
                continue
            reset_key = window.resets_at.isoformat() if window.resets_at else "no-reset"
            key = f"{provider}|{window.label}|{reset_key}"
            at_cap.append((provider, window, key))

    if not state.candy_feature_seeded:
        claimed.update(key for _, _, key in at_cap)
        state.candy_feature_seeded = True
        state.claimed_limit_windows = sorted(claimed)[-500:]
        return []

    for provider, window, key in at_cap:
        if key in claimed:
            continue
        weekly = "week" in window.label.lower()
        count = 5 if weekly else 1
        state.inventory["rare_candy"] = state.inventory.get("rare_candy", 0) + count
        claimed.add(key)
        grants.append(f"candy:{count}:{provider}:{window.label}")
    # Bound persistence in case a long-running install accumulates years of windows.
    state.claimed_limit_windows = sorted(claimed)[-500:]
    return grants

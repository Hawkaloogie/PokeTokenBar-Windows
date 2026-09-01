from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .pokemon import (
    EGG_HATCH_THRESHOLD,
    GRADUATION_TOTALS,
    MINT_PRICE,
    NATURES,
    RARE_CANDY_PRICE,
    RARE_CANDY_XP,
    SHINY_CHARM_PRICE,
    PokeAPIClient,
    egg_price,
    normalize_generation,
    phase_threshold,
)
from .windows import state_dir


# 3 adds `party` and `generation_filter`. An OLDER build loads a v3 file
# without error but its save() re-serializes only the fields it knows about,
# silently dropping both on its next autosave, so the loader keeps a one-time
# backup when it sees a newer file than it understands.
STATE_VERSION = 3

# One main plus five benched companions, matching a six-slot game party.
PARTY_BENCH_SIZE = 5
PARTY_TOTAL_SIZE = PARTY_BENCH_SIZE + 1


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
    version: int = STATE_VERSION
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
    representative_is_shiny: bool | None = None
    language: str = "en"
    claimed_limit_windows: list[str] = field(default_factory=list)
    candy_feature_seeded: bool = False
    # None = hatch from every available generation (1-5); an int restricts
    # future hatches to that generation only. Applies at hatch time, so a
    # Pokemon already being raised is unaffected by a change here.
    generation_filter: int | None = None
    # The bench: up to PARTY_BENCH_SIZE companions kept alongside `mon`, which
    # is always the main. Bench members keep their own growth counters frozen -
    # only the main is fed by tokens and Rare Candy - so swapping a Pokemon in
    # resumes it exactly where it left off. None marks an empty slot.
    party: list[MonState | None] = field(
        default_factory=lambda: [None] * PARTY_BENCH_SIZE
    )

    @property
    def wallet(self) -> int:
        return max(0, self.used_since_install - self.spent_tokens)

    @property
    def shiny_charm_active(self) -> bool:
        return self.inventory.get("shiny_charm", 0) > 0


@dataclass(slots=True, frozen=True)
class RepresentativeSubject:
    species_id: int | None
    is_shiny: bool = False

    @property
    def is_egg(self) -> bool:
        return self.species_id is None


def _current_catch(state: GameState) -> CatchRecord | None:
    mon = state.mon
    if mon is None:
        return None
    for catch in reversed(state.catches):
        if (
            catch.base_id == mon.base_id
            and catch.path_ids == mon.path_ids
            and catch.nature == mon.nature
            and catch.is_shiny == mon.is_shiny
        ):
            return catch
    return None


def owned_representative_options(state: GameState) -> list[RepresentativeSubject]:
    """Return every actually-owned species/variant eligible as representative."""
    current = _current_catch(state)
    owned: set[tuple[int, bool]] = set()
    for catch in state.catches:
        path = catch.path_ids or [catch.species_id]
        if catch is current and state.mon is not None:
            limit = min(len(path), max(0, state.mon.stage_index) + 1)
        else:
            limit = len(path)
        for species_id in path[:limit]:
            if isinstance(species_id, int) and species_id > 0:
                owned.add((species_id, bool(catch.is_shiny)))
    return [RepresentativeSubject(species_id, shiny) for species_id, shiny in sorted(owned)]


def representative_subject(state: GameState) -> RepresentativeSubject:
    """Resolve the display subject without ever changing the actively-raised Pokemon."""
    options = owned_representative_options(state)
    requested_id = state.representative_species_id
    if isinstance(requested_id, int) and requested_id > 0:
        candidates = [item for item in options if item.species_id == requested_id]
        if state.representative_is_shiny is not None:
            exact = next(
                (item for item in candidates if item.is_shiny == state.representative_is_shiny),
                None,
            )
            if exact is not None:
                return exact
        if candidates:
            # Legacy saves only stored the species ID. Prefer the shiny variant when
            # available so migrating cannot silently discard its appearance.
            return next((item for item in candidates if item.is_shiny), candidates[0])

    if state.mon is not None:
        return RepresentativeSubject(state.mon.current_id, state.mon.is_shiny)
    return RepresentativeSubject(None, False)


def set_representative(
    state: GameState,
    species_id: int | None,
    is_shiny: bool | None = None,
) -> bool:
    """Select an owned representative, or ``None`` to follow the active companion."""
    if species_id is None:
        state.representative_species_id = None
        state.representative_is_shiny = None
        return True
    candidates = [item for item in owned_representative_options(state) if item.species_id == species_id]
    if is_shiny is not None:
        candidates = [item for item in candidates if item.is_shiny == bool(is_shiny)]
    if not candidates:
        return False
    selected = next((item for item in candidates if item.is_shiny), candidates[0])
    state.representative_species_id = selected.species_id
    state.representative_is_shiny = selected.is_shiny
    return True


def normalize_representative(state: GameState) -> None:
    """Migrate a legacy selection to an owned variant or recover to current mode."""
    species_id = state.representative_species_id
    if species_id is None:
        state.representative_is_shiny = None
        return
    options = [item for item in owned_representative_options(state) if item.species_id == species_id]
    selected = None
    if state.representative_is_shiny is not None:
        selected = next(
            (item for item in options if item.is_shiny == state.representative_is_shiny),
            None,
        )
    if selected is None and options:
        selected = next((item for item in options if item.is_shiny), options[0])
    if selected is None:
        state.representative_species_id = None
        state.representative_is_shiny = None
        return
    state.representative_species_id = selected.species_id
    state.representative_is_shiny = selected.is_shiny


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


def _coerce_mon(raw: Any) -> MonState | None:
    """Build a MonState from untrusted JSON, or None if it cannot be trusted.

    Dataclasses do not validate types, so MonState(**item) happily accepts
    path_ids="nonsense" and only explodes later inside the renderer, far from
    the load. Every field is coerced and range-checked here so a bad record
    degrades to an empty slot at load time instead of crashing the UI on the
    next party action.
    """
    if not isinstance(raw, dict):
        return None
    try:
        base_id = int(raw["base_id"])
        path_source = raw["path_ids"]
        if isinstance(path_source, (str, bytes)) or not isinstance(path_source, (list, tuple)):
            return None
        path_ids = [int(value) for value in path_source]
        stage_index = int(raw["stage_index"])
        used_at_stage = int(raw["used_at_stage"])
        rarity = str(raw["rarity"])
        nature = str(raw["nature"])
        is_shiny = bool(raw["is_shiny"])
    except (KeyError, TypeError, ValueError):
        return None
    if base_id <= 0 or not path_ids or any(value <= 0 for value in path_ids):
        return None
    if rarity not in GRADUATION_TOTALS:
        return None
    return MonState(
        base_id=base_id,
        path_ids=path_ids,
        stage_index=max(0, min(stage_index, len(path_ids) - 1)),
        used_at_stage=max(0, used_at_stage),
        rarity=rarity,
        is_shiny=is_shiny,
        nature=nature,
    )


def _coerce_catch(raw: Any) -> CatchRecord | None:
    """Same treatment for a Pokedex entry: degrade one row, never the archive."""
    if not isinstance(raw, dict):
        return None
    try:
        species_id = int(raw["species_id"])
        base_id = int(raw["base_id"])
        path_source = raw["path_ids"]
        if isinstance(path_source, (str, bytes)) or not isinstance(path_source, (list, tuple)):
            return None
        path_ids = [int(value) for value in path_source]
        rarity = str(raw["rarity"])
        nature = str(raw["nature"])
        caught_at = str(raw["caught_at"])
        is_shiny = bool(raw["is_shiny"])
    except (KeyError, TypeError, ValueError):
        return None
    if species_id <= 0 or base_id <= 0:
        return None
    return CatchRecord(
        species_id=species_id,
        base_id=base_id,
        path_ids=path_ids or [species_id],
        rarity=rarity,
        is_shiny=is_shiny,
        nature=nature,
        caught_at=caught_at,
    )


def _load_party(raw: Any) -> list[MonState | None]:
    """Rebuild the bench from disk, tolerating junk, shortfalls and overflow.

    A malformed slot degrades to empty rather than failing the whole load - a
    corrupt bench should never cost someone their main Pokemon and Pokedex.
    """
    slots: list[MonState | None] = []
    if isinstance(raw, list):
        for item in raw[:PARTY_BENCH_SIZE]:
            slots.append(_coerce_mon(item))
    slots.extend([None] * (PARTY_BENCH_SIZE - len(slots)))
    return slots


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
            mon = _coerce_mon(raw.get("mon"))
            catch_source = raw.get("catches")
            catches = [
                record
                for record in (
                    _coerce_catch(item)
                    for item in (catch_source if isinstance(catch_source, list) else [])
                )
                if record is not None
            ]
            party = _load_party(raw.get("party"))
            representative_raw = raw.get("representative_species_id")
            try:
                representative_species_id = int(representative_raw) if representative_raw is not None else None
                if representative_species_id is not None and representative_species_id <= 0:
                    representative_species_id = None
            except (TypeError, ValueError):
                representative_species_id = None
            shiny_raw = raw.get("representative_is_shiny")
            representative_is_shiny = shiny_raw if isinstance(shiny_raw, bool) else None
            state = GameState(
                version=STATE_VERSION,
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
                representative_species_id=representative_species_id,
                representative_is_shiny=representative_is_shiny,
                language=str(raw.get("language", "en")),
                claimed_limit_windows=[str(v) for v in raw.get("claimed_limit_windows", [])],
                candy_feature_seeded=bool(raw.get("candy_feature_seeded", False)),
                generation_filter=normalize_generation(raw.get("generation_filter")),
                party=party,
            )
            for key in ("rare_candy", "mint", "shiny_charm"):
                state.inventory.setdefault(key, 0)
            normalize_representative(state)
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
            hatch = api.hatch(
                minimum_rarity=state.egg_tier,
                shiny_charm=state.shiny_charm_active,
                generation=state.generation_filter,
            )
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

        # Final form completed: bench it if there is room, then start a fresh
        # egg so incoming tokens always have somewhere to go. Overflow carries.
        events.append(f"graduated:{mon.current_id}")
        if add_to_party(state, mon) is None:
            # Bench full: the Pokemon still lives in the Pokedex, and can be
            # put on the bench by hand once a slot is freed.
            events.append(f"party_full:{mon.current_id}")
        state.mon = None
        # egg_usage and egg_tier are consumed by the hatch branch above, so
        # they are left alone here; clearing them would discard a paid tier the
        # player parked by swapping, and forfeit egg progress they earned.
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
        if (
            last.base_id == state.mon.base_id
            and last.path_ids == state.mon.path_ids
            # Never drop an entry a benched companion still relies on, or the
            # bench member becomes a ghost with no Pokedex record.
            and not any(_identity(member) == _identity(last) for member in _normalize_party(state))
        ):
            state.catches.pop()
    state.mon = None
    state.egg_usage = 0
    state.egg_tier = tier
    normalize_representative(state)
    return True, "Fresh egg ready"


def _normalize_party(state: GameState) -> list[MonState | None]:
    """Guarantee the bench is exactly PARTY_BENCH_SIZE slots long."""
    slots = list(state.party or [])[:PARTY_BENCH_SIZE]
    slots.extend([None] * (PARTY_BENCH_SIZE - len(slots)))
    state.party = slots
    return slots


def party_members(state: GameState) -> list[MonState | None]:
    """The full six-slot party: main first, then the bench in slot order."""
    return [state.mon, *_normalize_party(state)]


def party_open_slot(state: GameState) -> int | None:
    """Index of the first empty bench slot, or None when the bench is full."""
    for index, member in enumerate(_normalize_party(state)):
        if member is None:
            return index
    return None


def add_to_party(state: GameState, mon: MonState) -> int | None:
    """Drop a Pokemon into the first free bench slot. None when there is none."""
    slot = party_open_slot(state)
    if slot is None:
        return None
    state.party[slot] = mon
    return slot


def clear_party_slot(state: GameState, slot: int) -> bool:
    """Empty one bench slot. The Pokemon stays in the Pokedex."""
    slots = _normalize_party(state)
    if not 0 <= slot < len(slots) or slots[slot] is None:
        return False
    state.party[slot] = None
    normalize_representative(state)
    return True


def swap_main(state: GameState, slot: int) -> bool:
    """Exchange the main Pokemon with a bench slot, keeping both growth counters.

    Each Pokemon carries its own stage_index and used_at_stage, so benching one
    freezes its progress and swapping it back resumes exactly where it stopped.
    Swapping never spends or refunds tokens.
    """
    slots = _normalize_party(state)
    if not 0 <= slot < len(slots):
        return False
    incoming = slots[slot]
    if incoming is None and state.mon is None:
        return False
    state.party[slot] = state.mon
    state.mon = incoming
    # Egg progress and a paid egg tier are deliberately NOT cleared here.
    # egg_usage only accrues while `mon` is None and is consumed at hatch, so
    # parking it costs nothing - whereas zeroing it silently destroyed a tier
    # the player may have paid billions of tokens for.
    normalize_representative(state)
    return True


def party_slot_from_catch(catch: CatchRecord) -> MonState:
    """Build a bench-ready Pokemon from a Pokedex entry, at its owned stage."""
    path_ids = list(catch.path_ids or [catch.species_id])
    try:
        stage_index = path_ids.index(catch.species_id)
    except ValueError:
        stage_index = len(path_ids) - 1
    return MonState(
        base_id=catch.base_id,
        path_ids=path_ids,
        stage_index=max(0, min(stage_index, len(path_ids) - 1)),
        used_at_stage=0,
        rarity=catch.rarity,
        is_shiny=catch.is_shiny,
        nature=catch.nature,
    )


def _identity(member: MonState | CatchRecord | None) -> tuple | None:
    """A value that identifies one owned Pokemon across MonState/CatchRecord."""
    if member is None:
        return None
    return (
        int(member.base_id),
        tuple(int(value) for value in (member.path_ids or [])),
        bool(member.is_shiny),
        str(member.nature),
    )


def catch_in_use(state: GameState, catch: CatchRecord, *, ignore_slot: int | None = None) -> bool:
    """True when this Pokedex entry is already the main or sitting on the bench.

    Without this the picker happily benches a second copy of the Pokemon that
    is currently growing, producing two independent clones of one Pokemon.
    """
    target = _identity(catch)
    if target is None:
        return False
    if _identity(state.mon) == target:
        return True
    for index, member in enumerate(_normalize_party(state)):
        if index == ignore_slot:
            continue
        if _identity(member) == target:
            return True
    return False


def assign_party_slot(state: GameState, slot: int, catch: CatchRecord) -> bool:
    """Put an owned Pokedex entry onto a bench slot, replacing whatever is there.

    Refuses if that Pokemon is already the main or already benched elsewhere -
    one Pokemon must never occupy two slots at once.
    """
    slots = _normalize_party(state)
    if not 0 <= slot < len(slots):
        return False
    if catch_in_use(state, catch, ignore_slot=slot):
        return False
    state.party[slot] = party_slot_from_catch(catch)
    normalize_representative(state)
    return True


def set_generation_filter(state: GameState, generation: Any) -> int | None:
    """Restrict future hatches to one generation, or None for all of them.

    Takes effect on the next hatch only - a Pokemon already being raised keeps
    growing normally, and the current egg still hatches under the new filter.
    """
    state.generation_filter = normalize_generation(generation)
    return state.generation_filter


def apply_limit_rewards(state: GameState, limits: dict[str, Any]) -> list[str]:
    """Grant Rare Candy on a stable below-100 -> 100% limit transition.

    Reset timestamps can drift by a second between otherwise identical Codex
    snapshots, so they must never identify a reward window.  This mirrors the
    upstream edge-triggered map: a capped window remains claimed until a later
    refresh observes it below 100%, which rearms the next cap.
    """

    def reward_key(provider: str, window: Any) -> str:
        identity = getattr(window, "identifier", None) or str(window.label).lower()
        return f"{provider}|{identity}"

    def reward_eligible(window: Any) -> bool:
        label = str(window.label).lower()
        if "spend" in label:
            return False
        duration = getattr(window, "duration_minutes", None)
        if duration is not None:
            return True
        return label in {"5-hour", "weekly"} or "luna reserve" in label

    def previously_claimed(claims: set[str], provider: str, window: Any, key: str) -> bool:
        if key in claims:
            return True
        # Migration from the old reset-timestamp identity.  Suppress at most the
        # currently capped window; once it drops below 100% the legacy key is gone.
        legacy_key = f"{provider}|{window.label}"
        legacy_prefix = legacy_key + "|"
        return legacy_key in claims or any(claim.startswith(legacy_prefix) for claim in claims)

    grants: list[str] = []
    previous_claims = set(state.claimed_limit_windows)
    at_cap: list[tuple[str, Any, str]] = []
    for provider, status in limits.items():
        for window in getattr(status, "windows", []):
            if window.used_percent < 100 or not reward_eligible(window):
                continue
            at_cap.append((provider, window, reward_key(provider, window)))

    if not state.candy_feature_seeded:
        state.candy_feature_seeded = True
        state.claimed_limit_windows = sorted(key for _, _, key in at_cap)
        return []

    active_claims = {
        key
        for provider, window, key in at_cap
        if previously_claimed(previous_claims, provider, window, key)
    }
    for provider, window, key in at_cap:
        if key in active_claims:
            continue
        duration = getattr(window, "duration_minutes", None)
        weekly = (
            (duration is not None and duration > 1_440)
            or "week" in window.label.lower()
            or "luna reserve" in window.label.lower()
        )
        count = 5 if weekly else 1
        state.inventory["rare_candy"] = state.inventory.get("rare_candy", 0) + count
        active_claims.add(key)
        grants.append(f"candy:{count}:{provider}:{window.label}")
    state.claimed_limit_windows = sorted(key for _, _, key in at_cap)
    return grants

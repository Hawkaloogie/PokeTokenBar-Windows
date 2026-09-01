"""Value-matched trading.

A trade must be a fair swap. You cannot hand over a fresh Pidgey and receive a
Mewtwo, so every Pokemon carries a trade value built from three things the game
already tracks:

  rarity        - what the species is worth at all
  how far it is raised - a fully evolved Pokemon cost real tokens to get there
  shiny         - scarcity

An offer will only accept a Pokemon whose value meets what it is giving away.
Raising a Pokemon is therefore the way to trade upward: a fully evolved Rare
outvalues a freshly hatched one by a wide margin, which is what makes "raise it
or trade it" an actual decision.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable

from .pokemon import GENERATIONS, RARITY_RANK, generation_bounds

# Each tier is worth several of the tier below, so climbing takes real effort.
RARITY_VALUE: dict[str, float] = {
    "common": 1.0,
    "uncommon": 3.0,
    "rare": 8.0,
    "legendary": 25.0,
}
# A fully evolved Pokemon is worth double its freshly hatched self.
GROWTH_BONUS = 1.0
SHINY_MULTIPLIER = 4.0
# Offers ask for slightly less than they give, or nothing would ever be worth
# taking. Small enough that it cannot be laddered into a free legendary.
TRADE_DISCOUNT = 0.9

RARITY_LABELS = ("common", "uncommon", "rare", "legendary")


def growth_fraction(path_length: int, stage_index: int) -> float:
    """How far up its line a Pokemon is, from 0.0 (fresh) to 1.0 (final form)."""
    stages = max(1, int(path_length))
    if stages <= 1:
        return 1.0
    return max(0.0, min(1.0, int(stage_index) / (stages - 1)))


def trade_value(
    rarity: str,
    path_length: int = 1,
    stage_index: int = 0,
    is_shiny: bool = False,
) -> float:
    """What a Pokemon is worth in a trade."""
    base = RARITY_VALUE.get(str(rarity), RARITY_VALUE["common"])
    grown = base * (1.0 + GROWTH_BONUS * growth_fraction(path_length, stage_index))
    return grown * (SHINY_MULTIPLIER if is_shiny else 1.0)


def value_of(record: Any) -> float:
    """Trade value of a CatchRecord or MonState."""
    if record is None:
        return 0.0
    path = getattr(record, "path_ids", None) or []
    species = getattr(record, "species_id", None) or getattr(record, "base_id", 0)
    try:
        stage = path.index(species) if species in path else len(path) - 1
    except (ValueError, AttributeError):
        stage = 0
    return trade_value(
        getattr(record, "rarity", "common"),
        len(path) or 1,
        max(0, stage),
        bool(getattr(record, "is_shiny", False)),
    )


def describe_value(value: float) -> str:
    """Plain wording for a value threshold, so the ask is legible."""
    for rarity in reversed(RARITY_LABELS):
        fresh = RARITY_VALUE[rarity]
        if value >= fresh * (1.0 + GROWTH_BONUS):
            return f"a fully raised {rarity.title()}"
        if value >= fresh:
            return f"a {rarity.title()}"
    return "almost anything"


@dataclass(slots=True)
class TradeOffer:
    """One standing offer: give something worth enough, receive `gives_id`."""

    gives_id: int
    gives_rarity: str
    gives_path: list[int]
    gives_shiny: bool
    wants_value: float

    @property
    def gives_value(self) -> float:
        return trade_value(self.gives_rarity, len(self.gives_path) or 1, 0, self.gives_shiny)

    def accepts(self, record: Any) -> bool:
        return value_of(record) >= self.wants_value

    def describe_wanted(self) -> str:
        return describe_value(self.wants_value)


def eligible_catches(state: Any, offer: TradeOffer) -> list[int]:
    """Indexes of Pokedex entries that can pay for this offer.

    Favourites are never eligible, and neither is the Pokemon currently being
    raised - losing either to a trade would be a nasty surprise.
    """
    main = getattr(state, "mon", None)
    main_key = None
    if main is not None:
        main_key = (main.base_id, tuple(main.path_ids or []), bool(main.is_shiny))
    result: list[int] = []
    for index, catch in enumerate(getattr(state, "catches", []) or []):
        if getattr(catch, "is_favourite", False):
            continue
        if main_key is not None:
            if (catch.base_id, tuple(catch.path_ids or []), bool(catch.is_shiny)) == main_key:
                continue
        if offer.accepts(catch):
            result.append(index)
    return result


def _species_pool(generation_filter: Any) -> range:
    low, high = generation_bounds(generation_filter)
    return range(low, high + 1)


def generate_offers(
    api: Any,
    count: int = 3,
    *,
    generation_filter: Any = None,
    seed: Any = None,
    max_attempts: int = 120,
) -> list[TradeOffer]:
    """Build a fresh set of offers.

    `seed` makes a set reproducible, so the same 5-hour window always shows the
    same offers no matter how often the app is restarted.
    """
    rng = random.Random(seed)
    pool = _species_pool(generation_filter)
    offers: list[TradeOffer] = []
    seen: set[int] = set()
    for _ in range(max_attempts):
        if len(offers) >= count:
            break
        species_id = rng.randint(pool.start, pool.stop - 1)
        if species_id in seen:
            continue
        try:
            hatched = api.hatch_species(species_id)
        except Exception:  # noqa: BLE001
            continue
        seen.add(species_id)
        if hatched.rarity == "legendary":
            # A legendary would demand another legendary to pay for it, which
            # no one can do until they have one. They stay hatch-only, which
            # also keeps them worth something.
            continue
        offer_value = trade_value(
            hatched.rarity, len(hatched.path_ids) or 1, 0, False
        )
        offers.append(
            TradeOffer(
                gives_id=hatched.base_id,
                gives_rarity=hatched.rarity,
                gives_path=list(hatched.path_ids),
                gives_shiny=False,
                wants_value=round(offer_value * TRADE_DISCOUNT, 3),
            )
        )
    return offers


def offer_to_dict(offer: TradeOffer) -> dict:
    return {
        "gives_id": offer.gives_id,
        "gives_rarity": offer.gives_rarity,
        "gives_path": list(offer.gives_path),
        "gives_shiny": bool(offer.gives_shiny),
        "wants_value": float(offer.wants_value),
    }


def offer_from_dict(raw: Any) -> TradeOffer | None:
    """Rebuild one offer from disk, or None when it cannot be trusted."""
    if not isinstance(raw, dict):
        return None
    try:
        path_source = raw["gives_path"]
        if isinstance(path_source, (str, bytes)) or not isinstance(path_source, (list, tuple)):
            return None
        offer = TradeOffer(
            gives_id=int(raw["gives_id"]),
            gives_rarity=str(raw["gives_rarity"]),
            gives_path=[int(v) for v in path_source],
            gives_shiny=bool(raw["gives_shiny"]),
            wants_value=float(raw["wants_value"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if offer.gives_id <= 0 or not offer.gives_path:
        return None
    if offer.gives_rarity not in RARITY_VALUE:
        return None
    return offer


def load_offers(raw: Any) -> list[TradeOffer]:
    if not isinstance(raw, list):
        return []
    rebuilt = [offer_from_dict(item) for item in raw]
    return [offer for offer in rebuilt if offer is not None]

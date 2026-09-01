from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EGG_HATCH_THRESHOLD = 5_000_000
GRADUATION_TOTALS = {
    "common": 750_000_000,
    "uncommon": 1_875_000_000,
    "rare": 3_000_000_000,
    "legendary": 6_000_000_000,
}
# Must exceed RARE_CANDY_PRICE or buying candy is strictly worse than waiting -
# it was 100M for 500M, a 5x loss nobody had a reason to ever pay. Worth buying
# at 1.5x, but deliberately well short of a full line (750M for a common) so one
# purchase accelerates progress instead of skipping it.
RARE_CANDY_XP = 300_000_000
RARE_CANDY_PRICE = 200_000_000
MINT_PRICE = 100_000_000
SHINY_CHARM_PRICE = 3_000_000_000
FRESH_EGG_PRICE = 1_000_000_000
# One reroll per window. Deliberately about a quarter of a fresh egg: enough
# that you weigh it against an egg, cheap enough to use when a set is useless.
TRADE_REROLL_PRICE = 250_000_000
SHINY_DENOMINATOR = 64
SHINY_CHARM_DENOMINATOR = 48
DITTO_SPECIES_ID = 132

NATURES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]

# How fast the game runs. A heavy Claude Code user burns hundreds of millions
# of tokens a day; someone using it casually would wait months for one hatch.
#
# This is a SPEED BOOST, not a discount. Every price and threshold stays at its
# real value, and every number shown is the user's actual token usage - the
# easier tiers simply make each token count for more when it is credited.
PACE_DIVISORS: dict[str, int] = {
    "casual": 50,
    "light": 10,
    "standard": 1,
}
DEFAULT_PACE = "standard"
PACE_LABELS: dict[str, str] = {
    "casual": "Casual - light Claude use (50x faster)",
    "light": "Light - occasional Claude use (10x faster)",
    "standard": "Standard - heavy Claude use",
}


# Difficulty ordering, hardest last. Dropping to an easier pace makes every
# Pokemon already collected far cheaper in hindsight, so it costs a reset;
# raising difficulty is always free.
PACE_DIFFICULTY: dict[str, int] = {
    "casual": 0,
    "light": 1,
    "standard": 2,
}


def pace_difficulty(pace: Any) -> int:
    return PACE_DIFFICULTY[normalize_pace(pace)]


def is_pace_downgrade(current: Any, target: Any) -> bool:
    """True when moving from `current` to `target` makes the game easier."""
    return pace_difficulty(target) < pace_difficulty(current)


def normalize_pace(value: Any) -> str:
    """Coerce a stored pace into a known one, defaulting to standard."""
    if isinstance(value, str) and value in PACE_DIVISORS:
        return value
    return DEFAULT_PACE


def pace_divisor(pace: Any = DEFAULT_PACE) -> int:
    return PACE_DIVISORS[normalize_pace(pace)]


def pace_multiplier(pace: Any = DEFAULT_PACE) -> int:
    """How much each real token counts for at this pace."""
    return PACE_DIVISORS[normalize_pace(pace)]


def boosted(tokens: int, pace: Any = DEFAULT_PACE) -> int:
    """Credit real token usage at the current pace."""
    return max(0, int(tokens)) * pace_multiplier(pace)


def scaled(amount: int, pace: Any = DEFAULT_PACE) -> int:
    """Kept for compatibility. Prices and thresholds no longer scale."""
    return amount


def egg_hatch_threshold(pace: Any = DEFAULT_PACE) -> int:
    return scaled(EGG_HATCH_THRESHOLD, pace)


def graduation_total(rarity: str, pace: Any = DEFAULT_PACE) -> int:
    return scaled(GRADUATION_TOTALS[rarity], pace)


def rare_candy_xp(pace: Any = DEFAULT_PACE) -> int:
    return scaled(RARE_CANDY_XP, pace)


def item_price(item: str, pace: Any = DEFAULT_PACE) -> int:
    """Shop price for one item at the current pace."""
    base = {
        "rare_candy": RARE_CANDY_PRICE,
        "mint": MINT_PRICE,
        "shiny_charm": SHINY_CHARM_PRICE,
        "trade_reroll": TRADE_REROLL_PRICE,
    }[item]
    return scaled(base, pace)


def trade_reroll_price(pace: Any = DEFAULT_PACE) -> int:
    return scaled(TRADE_REROLL_PRICE, pace)


RARITY_RANK = {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3}

# National Pokedex species-ID ranges. The hatch pool stops at #649 because the
# animated sprite set this app pulls (generation-v black-white) only covers
# generations 1-5; later generations have no artwork to display.
GENERATIONS: list[tuple[int, str, int, int]] = [
    (1, "Kanto", 1, 151),
    (2, "Johto", 152, 251),
    (3, "Hoenn", 252, 386),
    (4, "Sinnoh", 387, 493),
    (5, "Unova", 494, 649),
]
GENERATION_MIN_ID = GENERATIONS[0][2]
GENERATION_MAX_ID = GENERATIONS[-1][3]


# The three original starter Pokemon of each generation, in Pokedex order
# (grass, fire, water) - the choice a real game opens with.
STARTERS: dict[int, list[int]] = {
    1: [1, 4, 7, 25],    # Bulbasaur, Charmander, Squirtle, Pikachu (Yellow)
    2: [152, 155, 158],  # Chikorita, Cyndaquil, Totodile
    3: [252, 255, 258],  # Treecko, Torchic, Mudkip
    4: [387, 390, 393],  # Turtwig, Chimchar, Piplup
    5: [495, 498, 501],  # Snivy, Tepig, Oshawott
}


def starters_for(generation: int | None) -> list[int]:
    """Starters available under a cap: that generation's and every earlier one."""
    normalized = normalize_generation(generation)
    cap = normalized if normalized is not None else max(STARTERS)
    return [
        species
        for gen in sorted(STARTERS)
        if gen <= cap
        for species in STARTERS[gen]
    ]


def starters_of_generation(generation: int) -> list[int]:
    """Just one generation's starters, for the questionnaire's second choice."""
    return list(STARTERS.get(normalize_generation(generation) or 0, []))


def generation_of(species_id: int) -> int | None:
    """Generation number for a species ID, or None when outside the pool."""
    for number, _region, low, high in GENERATIONS:
        if low <= species_id <= high:
            return number
    return None


def generation_region(number: int | None) -> str | None:
    """Region name for a generation number, or None when unknown."""
    for gen, region, _low, _high in GENERATIONS:
        if gen == number:
            return region
    return None


def generation_label(species_id: int) -> str:
    """Human-readable generation tag, e.g. 'Gen 2 - Johto'."""
    number = generation_of(species_id)
    if number is None:
        return "Unknown generation"
    return f"Gen {number} - {generation_region(number)}"


def normalize_generation(value: Any) -> int | None:
    """Coerce a stored value into a valid generation number, else None (= All)."""
    if value is None or isinstance(value, bool):
        # bool is an int subclass, so True would otherwise become "Gen 1".
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if generation_region(number) is not None else None


def generation_bounds(number: int | None) -> tuple[int, int]:
    """Species-ID range to roll within.

    The generation setting is a CAP, not an exact match: choosing Gen 3 means
    everything up to and including Hoenn can hatch, not Hoenn alone.
    """
    for gen, _region, _low, high in GENERATIONS:
        if gen == number:
            return GENERATION_MIN_ID, high
    return GENERATION_MIN_ID, GENERATION_MAX_ID


def generation_cap_label(number: int | None) -> str:
    """How the cap reads in the UI, e.g. 'Up to Gen 3 (Kanto-Hoenn)'."""
    if normalize_generation(number) is None:
        return "All generations (1-5)"
    first = GENERATIONS[0][1]
    region = generation_region(number)
    if number == 1:
        return f"Gen 1 only ({first})"
    return f"Up to Gen {number} ({first}-{region})"


def rarity_from(capture_rate: int, is_legendary: bool, is_mythical: bool) -> str:
    if is_legendary or is_mythical:
        return "legendary"
    if capture_rate <= 45:
        return "rare"
    if capture_rate <= 120:
        return "uncommon"
    return "common"


def phase_threshold(
    rarity: str, total_forms: int, stage_index: int, pace: Any = DEFAULT_PACE
) -> int:
    k = max(1, total_forms)
    i = stage_index + 1
    denominator = k * (k + 1) / 2.0
    return max(1, round(graduation_total(rarity, pace) * i / denominator))


def egg_price(tier: str | None = None, pace: Any = DEFAULT_PACE) -> int:
    if tier is None:
        return scaled(FRESH_EGG_PRICE, pace)
    return scaled(
        round(FRESH_EGG_PRICE * GRADUATION_TOTALS[tier] / GRADUATION_TOTALS["common"]),
        pace,
    )


def _species_id(url_or_name: Any) -> int | None:
    if isinstance(url_or_name, dict):
        url_or_name = url_or_name.get("url")
    if not isinstance(url_or_name, str):
        return None
    match = re.search(r"/pokemon-species/(\d+)/?", url_or_name)
    return int(match.group(1)) if match else None


@dataclass(slots=True)
class HatchResult:
    base_id: int
    path_ids: list[int]
    rarity: str
    nature: str
    is_shiny: bool
    capture_rate: int


class PokeAPIClient:
    def __init__(self, cache_dir: Path, timeout: float = 12.0):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.json_dir = cache_dir / "api"
        self.sprite_dir = cache_dir / "sprites"
        self.json_dir.mkdir(parents=True, exist_ok=True)
        self.sprite_dir.mkdir(parents=True, exist_ok=True)

    def _json(self, url: str, cache_key: str) -> dict[str, Any]:
        path = self.json_dir / f"{cache_key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        request = urllib.request.Request(url, headers={"User-Agent": "PokeTokenBar-Windows/0.1", "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError("PokéAPI returned a non-object response")  # noqa: TRY004
        try:
            path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
        return data

    def species(self, species_id: int) -> dict[str, Any]:
        return self._json(f"https://pokeapi.co/api/v2/pokemon-species/{species_id}", f"species-{species_id}")

    def evolution_chain(self, chain_url: str) -> dict[str, Any]:
        # The URL is data, not a trusted literal: it comes straight out of a
        # PokeAPI JSON response (live or cached on disk), so a compromised
        # API, a TLS-intercepting middlebox, or a tampered cache file could
        # hand back a file:// path or an arbitrary host. Refuse anything that
        # is not an HTTPS request to the real API before ever calling urlopen.
        parsed = urllib.parse.urlparse(chain_url if isinstance(chain_url, str) else "")
        if parsed.scheme != "https" or parsed.hostname != "pokeapi.co":
            raise ValueError(f"Refusing to fetch evolution chain from untrusted URL: {chain_url!r}")
        match = re.search(r"/evolution-chain/(\d+)/?", chain_url)
        key = f"evolution-{match.group(1) if match else abs(hash(chain_url))}"
        return self._json(chain_url, key)

    def localized_name(self, species_id: int, language: str = "en") -> str:
        try:
            data = self.species(species_id)
        except Exception:  # noqa: BLE001
            return f"#{species_id}"
        names = data.get("names") if isinstance(data.get("names"), list) else []
        preferred = [language]
        if language == "ja":
            preferred = ["ja-Hrkt", "ja"]
        preferred.append("en")
        for code in preferred:
            for item in names:
                if not isinstance(item, dict):
                    continue
                lang = item.get("language")
                if isinstance(lang, dict) and lang.get("name") == code and isinstance(item.get("name"), str):
                    return item["name"]
        return str(data.get("name") or f"#{species_id}").replace("-", " ").title()

    def _random_path(self, node: dict[str, Any]) -> list[int]:
        species_id = _species_id(node.get("species"))
        if species_id is None or species_id > 649:
            return []
        children = [c for c in node.get("evolves_to", []) if isinstance(c, dict)]
        supported = [c for c in children if (_species_id(c.get("species")) or 9999) <= 649]
        if not supported:
            return [species_id]
        child = random.choice(supported)
        suffix = self._random_path(child)
        return [species_id] + suffix

    def hatch_species(self, species_id: int, shiny_charm: bool = False) -> HatchResult:
        """Build a companion for one chosen species - used by the setup starter.

        Same shape as hatch(), but the species is picked by the player rather
        than rolled, so no capture-rate weighting is applied.
        """
        species = self.species(species_id)
        capture_rate = int(species.get("capture_rate") or 0)
        rarity = rarity_from(
            capture_rate,
            bool(species.get("is_legendary")),
            bool(species.get("is_mythical")),
        )
        path = [species_id]
        chain_ref = species.get("evolution_chain")
        if isinstance(chain_ref, dict) and isinstance(chain_ref.get("url"), str):
            try:
                chain = self.evolution_chain(chain_ref["url"])
                root = chain.get("chain")
                if isinstance(root, dict):
                    candidate = self._random_path(root)
                    if candidate and species_id in candidate:
                        path = candidate[candidate.index(species_id):]
            except Exception:  # noqa: BLE001
                path = [species_id]
        denominator = SHINY_CHARM_DENOMINATOR if shiny_charm else SHINY_DENOMINATOR
        return HatchResult(
            base_id=species_id,
            path_ids=path,
            rarity=rarity,
            nature=random.choice(NATURES),
            is_shiny=random.randrange(denominator) == 0,
            capture_rate=capture_rate,
        )

    def hatch(
        self,
        minimum_rarity: str | None = None,
        shiny_charm: bool = False,
        max_attempts: int = 1200,
        generation: int | None = None,
        max_seconds: float = 45.0,
    ) -> HatchResult:
        """Roll a hatch, retrying rejected candidates against live PokeAPI data.

        Bounded by wall-clock time (`max_seconds`), not just attempt count.
        `max_attempts` alone caps the worst case at roughly
        `max_attempts * self.timeout` - about four hours at the defaults - if
        every attempt happens to hit an unreachable host that hangs for the
        full 12s timeout before failing. An elapsed-time deadline bounds that
        worst case directly regardless of whether attempts fail slow
        (timeouts) or fast (rejected candidates, connection refused), which a
        consecutive-failure counter would not: a run of timeouts interleaved
        with a few instant rejections could still reset a failure streak
        while burning most of the deadline. On timeout the caller gets a
        RuntimeError and is expected to leave the state it was mutating
        unsaved, so the pending egg is retried on the next refresh rather
        than lost.
        """
        minimum_rank = RARITY_RANK.get(minimum_rarity or "common", 0)
        low, high = generation_bounds(normalize_generation(generation))
        last_error: Exception | None = None
        deadline = time.monotonic() + max(0.0, max_seconds)
        for _ in range(max_attempts):
            if time.monotonic() >= deadline:
                last_error = last_error or TimeoutError(
                    f"Hatch search exceeded its {max_seconds:.0f}s deadline"
                )
                break
            species_id = random.randint(low, high)
            if species_id == DITTO_SPECIES_ID:
                continue
            try:
                species = self.species(species_id)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            if species.get("evolves_from_species") is not None:
                continue
            capture_rate = int(species.get("capture_rate") or 0)
            rarity = rarity_from(capture_rate, bool(species.get("is_legendary")), bool(species.get("is_mythical")))
            if RARITY_RANK[rarity] < minimum_rank:
                continue
            # Upstream weights hatches by official capture rate. Rejection sampling
            # gives each base species probability proportional to capture_rate.
            if random.randint(1, 255) > max(1, min(255, capture_rate)):
                continue
            chain_ref = species.get("evolution_chain")
            if not isinstance(chain_ref, dict) or not isinstance(chain_ref.get("url"), str):
                continue
            try:
                chain = self.evolution_chain(chain_ref["url"])
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            root = chain.get("chain")
            if not isinstance(root, dict):
                continue
            path = self._random_path(root)
            if not path or path[0] != species_id:
                continue
            denominator = SHINY_CHARM_DENOMINATOR if shiny_charm else SHINY_DENOMINATOR
            return HatchResult(
                base_id=species_id,
                path_ids=path,
                rarity=rarity,
                nature=random.choice(NATURES),
                is_shiny=random.randrange(denominator) == 0,
                capture_rate=capture_rate,
            )
        if last_error:
            raise RuntimeError(f"Could not hatch a Pokemon: {last_error}")
        raise RuntimeError("Could not find an eligible Pokemon hatch candidate")

    def sprite_path(self, species_id: int, shiny: bool = False, animated: bool = True) -> Path | None:
        variant = "shiny-" if shiny else ""
        suffix = "gif" if animated else "png"
        path = self.sprite_dir / f"{species_id}-{variant}{'animated' if animated else 'static'}.{suffix}"
        if path.exists() and path.stat().st_size > 0:
            return path
        if animated:
            middle = "animated/shiny" if shiny else "animated"
            url = (
                "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"
                f"versions/generation-v/black-white/{middle}/{species_id}.gif"
            )
        else:
            middle = "shiny/" if shiny else ""
            url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{middle}{species_id}.png"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PokeTokenBar-Windows/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                blob = response.read()
            if not blob:
                return None
            path.write_bytes(blob)
            return path
        except (OSError, urllib.error.URLError, TimeoutError):
            if animated:
                return self.sprite_path(species_id, shiny=shiny, animated=False)
            return None

    def egg_sprite_path(self) -> Path | None:
        path = self.sprite_dir / "egg-static.png"
        if path.exists() and path.stat().st_size > 0:
            return path
        url = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/egg.png"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PokeTokenBar-Windows/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                blob = response.read()
            if not blob:
                return None
            path.write_bytes(blob)
            return path
        except (OSError, urllib.error.URLError, TimeoutError):
            return None

    def item_sprite_path(self, item_name: str) -> Path | None:
        """Fetch a static PokeAPI item sprite without bundling third-party art."""
        normalized = item_name.strip().lower()
        if not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError("Invalid PokeAPI item name")
        path = self.sprite_dir / f"item-{normalized}.png"
        if path.exists() and path.stat().st_size > 0:
            return path
        url = (
            "https://raw.githubusercontent.com/PokeAPI/sprites/master/"
            f"sprites/items/{normalized}.png"
        )
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "PokeTokenBar-Windows/0.1"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                blob = response.read()
            if not blob:
                return None
            path.write_bytes(blob)
            return path
        except (OSError, urllib.error.URLError, TimeoutError):
            return None

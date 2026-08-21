from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class ModelRate:
    input: float
    output: float
    cache_write: float
    cache_read: float

    @classmethod
    def per_million(cls, input_: float, output: float, cache_write: float, cache_read: float) -> "ModelRate":
        scale = 1_000_000.0
        return cls(input_ / scale, output / scale, cache_write / scale, cache_read / scale)


ZERO = ModelRate(0.0, 0.0, 0.0, 0.0)

# Mirrored from upstream ModelPricing.swift at the time this Windows port was made.
TABLE: dict[str, ModelRate] = {
    "claude-opus-4-8": ModelRate.per_million(5, 25, 6.25, 0.5),
    "claude-opus-4-7": ModelRate.per_million(5, 25, 6.25, 0.5),
    "claude-sonnet-4-6": ModelRate.per_million(3, 15, 3.75, 0.3),
    "claude-haiku-4-5-20251001": ModelRate.per_million(1, 5, 1.25, 0.1),
    "claude-fable-5": ZERO,
    "gpt-5.5": ModelRate.per_million(5, 30, 0, 0.5),
    "gemini-2.5-pro": ModelRate.per_million(1.25, 10, 0, 0.3125),
    "gemini-2.5-flash": ModelRate.per_million(0.30, 2.5, 0, 0.075),
    "gemini-2.0-flash": ModelRate.per_million(0.10, 0.4, 0, 0.025),
}


def rate_for(model: str) -> ModelRate:
    if model in TABLE:
        return TABLE[model]
    name = model.lower()
    if name.startswith("grok") or name.startswith("antigravity/"):
        return ZERO
    if "opus" in name:
        return ModelRate.per_million(5, 25, 6.25, 0.5)
    if "sonnet" in name:
        return ModelRate.per_million(3, 15, 3.75, 0.3)
    if "haiku" in name:
        return ModelRate.per_million(1, 5, 1.25, 0.1)
    if any(part in name for part in ("gpt", "codex", "o4", "o3")):
        return ModelRate.per_million(5, 30, 0, 0.5)
    if name.startswith("gemini"):
        if "pro" in name:
            return ModelRate.per_million(1.25, 10, 0, 0.3125)
        if "flash" in name:
            return ModelRate.per_million(0.30, 2.5, 0, 0.075)
    return ZERO


def cost_for(model: str, input_tokens: int, output_tokens: int, cache_write_tokens: int, cache_read_tokens: int) -> float:
    rate = rate_for(model)
    return (
        input_tokens * rate.input
        + output_tokens * rate.output
        + cache_write_tokens * rate.cache_write
        + cache_read_tokens * rate.cache_read
    )

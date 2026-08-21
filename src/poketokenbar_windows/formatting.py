from __future__ import annotations


def compact_tokens(value: int) -> str:
    sign = "-" if value < 0 else ""
    n = abs(float(value))
    if n >= 1_000_000_000:
        return f"{sign}{n / 1_000_000_000:.1f}B".replace(".0B", "B")
    if n >= 1_000_000:
        return f"{sign}{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{sign}{n / 1_000:.1f}K".replace(".0K", "K")
    return f"{sign}{int(n)}"


def money(value: float) -> str:
    if value < 0.005:
        return "$0.00"
    return f"${value:,.2f}"

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .models import ProviderLimits


ResetUrgency = Literal["neutral", "warning", "critical"]


@dataclass(slots=True, frozen=True)
class LimitDisplayRow:
    text: str
    occurs_at: datetime | None
    urgency: ResetUrgency = "neutral"


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


def format_limit_datetime(value: datetime) -> str:
    return value.strftime("%a %d %b, %H:%M")


def _reset_title_and_scope(title: str | None) -> tuple[str, str | None]:
    label = (title or "Rate-limit reset").strip()
    if label.endswith(")") and " (" in label:
        label, raw_scope = label.rsplit(" (", 1)
        scope = raw_scope[:-1].strip()
        return label.strip(), scope or None
    return label, None


def _next_reset_credit(limits: ProviderLimits):
    if limits.reset_credits_available <= 0 or not limits.reset_credits:
        return None
    dated = [credit for credit in limits.reset_credits if credit.expires_at is not None]
    return min(dated, key=lambda credit: credit.expires_at) if dated else limits.reset_credits[0]


def limit_reset_expiry(limits: ProviderLimits) -> datetime | None:
    credit = _next_reset_credit(limits)
    return credit.expires_at if credit else None


def _now_for(reference: datetime, now: datetime | None) -> datetime:
    current = now or datetime.now().astimezone()
    if reference.tzinfo is None and current.tzinfo is not None:
        return current.replace(tzinfo=None)
    if reference.tzinfo is not None and current.tzinfo is None:
        return current.replace(tzinfo=reference.tzinfo)
    if reference.tzinfo is not None:
        return current.astimezone(reference.tzinfo)
    return current


def limit_reset_urgency(limits: ProviderLimits, now: datetime | None = None) -> ResetUrgency:
    expiry = limit_reset_expiry(limits)
    if expiry is None:
        return "neutral"

    remaining = expiry - _now_for(expiry, now)
    if remaining <= timedelta(hours=72):
        return "critical"

    weekly_reset = next(
        (
            window.resets_at
            for window in limits.windows
            if window.label.lower() == "weekly" and window.resets_at is not None
        ),
        None,
    )
    expires_before_weekly = weekly_reset is not None and expiry.timestamp() < weekly_reset.timestamp()
    if expires_before_weekly or remaining < timedelta(days=7):
        return "warning"
    return "neutral"


def limit_reset_summary(limits: ProviderLimits) -> str:
    count = limits.reset_credits_available
    if count <= 0:
        return ""

    next_credit = _next_reset_credit(limits)
    if count == 1:
        label, scope = _reset_title_and_scope(next_credit.title if next_credit else None)
        if not label.lower().endswith("available"):
            label += " available"
        parts = [label]
        if scope:
            parts.append(scope.replace("5 hr", "5h"))
        expiry_label = "expires"
    else:
        parts = [f"{count} resets available"]
        expiry_label = "first expires"

    if next_credit and next_credit.expires_at:
        parts.append(f"{expiry_label} {format_limit_datetime(next_credit.expires_at)}")
    else:
        parts.append("expiry unknown")
    return " · ".join(parts)


def limit_reset_tray_warning(limits: ProviderLimits, now: datetime | None = None) -> str:
    expiry = limit_reset_expiry(limits)
    urgency = limit_reset_urgency(limits, now)
    if expiry is None or urgency == "neutral":
        return ""
    marker = "🔴" if urgency == "critical" else "🟠"
    return f"{marker} reset expires {format_limit_datetime(expiry)}"


def provider_limit_rows(
    provider_label: str,
    limits: ProviderLimits,
    now: datetime | None = None,
) -> list[LimitDisplayRow]:
    window_rows: list[LimitDisplayRow] = []
    plan = f" · {limits.plan}" if limits.plan else ""
    for window in limits.windows:
        reset = format_limit_datetime(window.resets_at) if window.resets_at else "unknown"
        window_rows.append(
            LimitDisplayRow(
                text=(
                    f"{provider_label}{plan} · {window.label}: "
                    f"{window.remaining_percent:.0f}% left · resets {reset}"
                ),
                occurs_at=window.resets_at,
            )
        )

    rows = sorted(
        window_rows,
        key=lambda row: (
            row.occurs_at is None,
            row.occurs_at.timestamp() if row.occurs_at is not None else float("inf"),
        ),
    )

    reset_summary = limit_reset_summary(limits)
    if reset_summary:
        urgency = limit_reset_urgency(limits, now)
        marker = "⚠ " if urgency != "neutral" else ""
        rows.append(
            LimitDisplayRow(
                text=f"[{marker}{provider_label} · {reset_summary}]",
                occurs_at=limit_reset_expiry(limits),
                urgency=urgency,
            )
        )

    return rows

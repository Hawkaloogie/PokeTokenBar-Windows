from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import LimitWindow, ProviderLimits
from .windows import hidden_subprocess_kwargs, resolve_gui_binary


CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw >= 100_000_000_000:
            raw /= 1000.0
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).astimezone()
        except (OSError, ValueError, OverflowError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _plan_display(subscription_type: str | None, tier: str | None) -> str | None:
    if not subscription_type:
        return None
    base = subscription_type[:1].upper() + subscription_type[1:]
    if tier:
        for part in tier.split("_"):
            if part.endswith("x") and part[:-1].isdigit():
                return f"{base} {part}"
    return base


def _claude_credential_paths() -> list[Path]:
    home = Path.home()
    paths: list[Path] = []
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if part:
                paths.append(Path(part).expanduser() / ".credentials.json")
    paths.extend([home / ".config/claude/.credentials.json", home / ".claude/.credentials.json"])
    return paths


def _read_claude_oauth() -> tuple[str, str | None, str | None] | None:
    for path in _claude_credential_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("claudeAiOauth"), dict):
            continue
        oauth = data["claudeAiOauth"]
        token = oauth.get("accessToken")
        if not isinstance(token, str) or not token:
            continue
        expires = _parse_datetime(oauth.get("expiresAt"))
        if expires is not None and expires.timestamp() <= datetime.now().astimezone().timestamp() + 60:
            continue
        return token, oauth.get("subscriptionType"), oauth.get("rateLimitTier")
    return None


def fetch_claude_limits(timeout: float = 12.0) -> ProviderLimits:
    credential = _read_claude_oauth()
    if credential is None:
        return ProviderLimits(provider="claude", error="Claude OAuth credentials not found")
    token, subscription_type, rate_limit_tier = credential
    request = urllib.request.Request(
        CLAUDE_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "User-Agent": "PokeTokenBar-Windows/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        return ProviderLimits(provider="claude", error=f"Claude limits HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return ProviderLimits(provider="claude", error=f"Claude limits: {exc}")
    if not isinstance(data, dict):
        return ProviderLimits(provider="claude", error="Claude limits returned an unexpected payload")

    windows: list[LimitWindow] = []
    for key, label in (("five_hour", "5-hour"), ("seven_day", "Weekly")):
        raw = data.get(key)
        if isinstance(raw, dict) and raw.get("utilization") is not None:
            try:
                used = float(raw["utilization"])
            except (TypeError, ValueError):
                continue
            windows.append(LimitWindow(label=label, used_percent=used, resets_at=_parse_datetime(raw.get("resets_at"))))

    # Newer Claude usage responses can include a generalized limits[] list.
    for item in data.get("limits", []) if isinstance(data.get("limits"), list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if windows and kind in {"session", "weekly_all"}:
            continue
        percent = item.get("percent")
        if percent is None:
            continue
        try:
            used = float(percent)
        except (TypeError, ValueError):
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        display = model.get("display_name") if isinstance(model, dict) else None
        label = str(display or item.get("group") or kind or "Limit").replace("_", " ").title()
        windows.append(LimitWindow(label=label, used_percent=used, resets_at=_parse_datetime(item.get("resets_at"))))

    return ProviderLimits(
        provider="claude",
        plan=_plan_display(subscription_type, rate_limit_tier),
        windows=windows,
    )


def _find_codex() -> str | None:
    override = os.environ.get("CODEX_BIN")
    if override and Path(override).expanduser().exists():
        return str(Path(override).expanduser())
    candidates = [
        Path.home() / ".codex/bin/codex",
        Path.home() / ".codex/bin/codex.exe",
        Path.home() / ".local/bin/codex",
        Path("/usr/local/bin/codex"),
        Path("/usr/bin/codex"),
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("codex")


def _codex_request_lines() -> str:
    messages = [
        {
            "method": "initialize",
            "id": 0,
            "params": {
                "clientInfo": {"name": "poketokenbar_windows", "title": "PokeTokenBar Windows", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "account/rateLimits/read", "id": 1, "params": {}},
    ]
    return "".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages)


def _codex_window(raw: Any, label: str) -> LimitWindow | None:
    if not isinstance(raw, dict):
        return None
    used = raw.get("usedPercent")
    if used is None:
        used = raw.get("used_percent")
    try:
        percent = float(used)
    except (TypeError, ValueError):
        return None
    duration = raw.get("windowDurationMins") or raw.get("window_duration_mins")
    if duration == 300:
        label = "5-hour"
    elif duration == 10080:
        label = "Weekly"
    resets = raw.get("resetsAt") if raw.get("resetsAt") is not None else raw.get("resets_at")
    return LimitWindow(label=label, used_percent=percent, resets_at=_parse_datetime(resets))


def fetch_codex_limits(timeout: float = 20.0) -> ProviderLimits:
    binary = _find_codex()
    if binary is None:
        return ProviderLimits(provider="codex", error="codex executable not found")
    binary = resolve_gui_binary(binary)
    try:
        proc = subprocess.run(
            [binary, "app-server", "--stdio"],
            input=_codex_request_lines(),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProviderLimits(provider="codex", error=f"Codex limits: {exc}")

    payload: dict[str, Any] | None = None
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("id") == 1:
            result = obj.get("result")
            payload = result if isinstance(result, dict) else obj
            break
    if payload is None:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no JSON-RPC response"
        return ProviderLimits(provider="codex", error=f"Codex limits: {detail}")

    rate_limits = payload.get("rateLimits") or payload.get("rate_limits") or payload
    snapshots: list[dict[str, Any]] = []
    if isinstance(rate_limits, dict):
        snapshots.append(rate_limits)
    by_id = payload.get("rateLimitsByLimitId") or payload.get("rate_limits_by_limit_id")
    if isinstance(by_id, dict):
        for key in sorted(by_id):
            item = by_id[key]
            if isinstance(item, dict) and item not in snapshots:
                snapshots.append(item)

    windows: list[LimitWindow] = []
    plan: str | None = None
    for index, snapshot in enumerate(snapshots):
        name = str(snapshot.get("limitName") or snapshot.get("limitId") or ("Codex" if index == 0 else "Codex limit"))
        plan = plan or snapshot.get("planType")
        primary = _codex_window(snapshot.get("primary"), f"{name} primary")
        secondary = _codex_window(snapshot.get("secondary"), f"{name} secondary")
        if primary:
            windows.append(primary)
        if secondary:
            windows.append(secondary)
        individual = snapshot.get("individualLimit") or snapshot.get("individual_limit")
        if isinstance(individual, dict):
            remaining = individual.get("remainingPercent") or individual.get("remaining_percent")
            try:
                used = max(0.0, min(100.0, 100.0 - float(remaining)))
            except (TypeError, ValueError):
                used = None
            if used is not None:
                windows.append(LimitWindow(label=f"{name} spend", used_percent=used, resets_at=_parse_datetime(individual.get("resetsAt") or individual.get("resets_at"))))

    return ProviderLimits(provider="codex", plan=str(plan).title() if plan else None, windows=windows)


def fetch_all_limits() -> dict[str, ProviderLimits]:
    # Called from a worker thread by the UI, so sequential network/process access is fine.
    return {"claude": fetch_claude_limits(), "codex": fetch_codex_limits()}

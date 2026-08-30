from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.request import Request

from .models import UsageEntry
from .windows import state_dir

FILTERED_URL = "https://cursor.com/api/dashboard/get-filtered-usage-events"
PAGE_SIZE = 100
MAX_PAGES = 200
REQUEST_TIMEOUT = 10.0
CACHE_MAX_AGE_SECONDS = 6 * 60 * 60
Transport = Callable[[Request], tuple[bytes, int] | None]


@dataclass(slots=True)
class CursorUsageResult:
    entries: list[UsageEntry]
    is_authoritative: bool
    error: str | None = None


def _int(value: Any) -> int:
    try:
        if value is None or isinstance(value, bool):
            return 0
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        return None if math.isnan(out) else out
    except (TypeError, ValueError, OverflowError):
        return None


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _parse_datetime(value: Any) -> datetime | None:
    from .usage import _parse_datetime as parse_dt

    return parse_dt(value)


def jwt_subject(jwt: str) -> str | None:
    parts = jwt.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    pad = (4 - len(payload) % 4) % 4
    payload += "=" * pad
    payload = payload.replace("-", "+").replace("_", "/")
    try:
        data = json.loads(base64.b64decode(payload, validate=False))
    except (ValueError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    sub = data.get("sub")
    return sub if isinstance(sub, str) and sub else None


def workos_session_cookie(access_token: str) -> str:
    if "::" in access_token or "%3A%3A" in access_token:
        return access_token
    sub = jwt_subject(access_token)
    if sub:
        return f"{sub}::{access_token}"
    return access_token


def cache_account_identifier(token: str) -> str:
    decoded = unquote(token)
    if "::" in decoded:
        subject = decoded.split("::", 1)[0]
        if subject:
            return f"subject:{subject}"
    sub = jwt_subject(decoded)
    if sub:
        return f"subject:{sub}"
    digest = hashlib.sha256(decoded.encode("utf-8")).hexdigest()
    return f"token:{digest}"


def epoch_millisecond_string(moment: datetime) -> str:
    return str(round(moment.timestamp() * 1000))


def has_next_page(
    pagination: dict[str, Any] | None,
    *,
    total_count: int | None,
    page: int,
    event_count: int,
    page_size: int = PAGE_SIZE,
) -> bool:
    if isinstance(pagination, dict):
        explicit = pagination.get("hasNextPage")
        if isinstance(explicit, bool):
            return explicit
        num_pages = pagination.get("numPages")
        if isinstance(num_pages, int):
            return page < num_pages
    if total_count is not None:
        return page * page_size < total_count
    return event_count >= page_size


def parse_cursor_bubble(obj: dict[str, Any], *, key: str, since: datetime) -> UsageEntry | None:
    from .usage import _entry

    tokens = obj.get("tokenCount")
    if not isinstance(tokens, dict):
        return None
    input_tokens = _int(tokens.get("inputTokens"))
    output_tokens = _int(tokens.get("outputTokens"))
    if input_tokens + output_tokens <= 0:
        return None
    date = _parse_datetime(obj.get("createdAt"))
    if date is None or date < since:
        return None
    return _entry(
        id=f"cursor|{key}",
        date=date,
        provider="cursor",
        model=str(obj.get("modelType") or "unknown"),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def parse_usage_event(event: dict[str, Any], *, row_index: int, since: datetime) -> UsageEntry | None:
    from .usage import _entry

    date = _usage_event_date(event)
    if date is None or date < since:
        return None
    model = _string(event.get("model")) or "unknown"
    stable_id = _string(event.get("id")) or _string(event.get("eventId")) or _string(event.get("requestId"))
    usage = event.get("tokenUsage") if isinstance(event.get("tokenUsage"), dict) else {}
    cents = _float(usage.get("totalCents"))
    stamp = _string(event.get("timestamp")) or date.isoformat()
    entry_id = f"cursor|api|{stable_id}" if stable_id else f"cursor|api|{stamp}|{model}|{row_index}"
    return _entry(
        id=entry_id,
        date=date,
        provider="cursor",
        model=model,
        input_tokens=_int(usage.get("inputTokens")),
        output_tokens=_int(usage.get("outputTokens")),
        cache_write_tokens=_int(usage.get("cacheWriteTokens")),
        cache_read_tokens=_int(usage.get("cacheReadTokens")),
        explicit_cost=None if cents is None else cents / 100.0,
    )


def _usage_event_date(event: dict[str, Any]) -> datetime | None:
    raw = event.get("timestamp")
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.isdigit() or (stripped.replace(".", "", 1).isdigit() and stripped.count(".") < 2):
            return _parse_datetime(float(stripped))
        return _parse_datetime(stripped)
    return _parse_datetime(raw)


last_scan_warning: str | None = None


def _normalize_secret(value: Any) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[0] in "{\"[":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, str) and parsed.strip():
            return parsed.strip()
        if isinstance(parsed, dict):
            for key in ("accessToken", "token", "value"):
                inner = parsed.get(key)
                if isinstance(inner, str) and inner.strip():
                    return inner.strip()
    return text


def cursor_auth_access_token(databases: list[Path] | None = None) -> str | None:
    from .usage import _open_sqlite_ro, cursor_database_candidates

    override = os.environ.get("CURSOR_SESSION_TOKEN", "").strip()
    if override:
        return override
    keys = (
        "cursorAuth/accessToken",
        "cursorAuth/cachedAccessToken",
        "cursorAuth/webAccessToken",
    )
    paths = databases or cursor_database_candidates()
    for db in paths:
        conn = _open_sqlite_ro(db)
        if conn is None:
            continue
        try:
            for key in keys:
                row = conn.execute("SELECT value FROM ItemTable WHERE key = ? LIMIT 1", (key,)).fetchone()
                token = _normalize_secret(row[0]) if row else None
                if token:
                    return token
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key LIKE 'cursorAuth/%Token' LIMIT 1"
            ).fetchone()
            token = _normalize_secret(row[0]) if row else None
            if token:
                return token
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return None


def _apply_auth(request: Request, token: str, mode: str) -> None:
    if mode == "cookie":
        request.add_header("Cookie", f"WorkosCursorSessionToken={workos_session_cookie(token)}")
    else:
        request.add_header("Authorization", f"Bearer {token}")


def _default_transport(request: Request) -> tuple[bytes, int] | None:
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.read(), int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except OSError:
            body = b""
        return body, int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def fetch_filtered_events(
    token: str,
    since: datetime,
    *,
    now: datetime | None = None,
    transport: Transport | None = None,
) -> tuple[list[UsageEntry] | None, str | None]:
    send = transport or _default_transport
    start = epoch_millisecond_string(since)
    end = epoch_millisecond_string(now or datetime.now(timezone.utc).astimezone())
    collected: list[UsageEntry] = []
    page = 1
    global_index = 0
    auth_modes = ["cookie", "bearer"]
    auth_index = 0

    while page <= MAX_PAGES:
        body = json.dumps({
            "teamId": 0,
            "startDate": start,
            "endDate": end,
            "page": page,
            "pageSize": PAGE_SIZE,
        }).encode("utf-8")
        request = Request(FILTERED_URL, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", "Mozilla/5.0")
        request.add_header("Origin", "https://cursor.com")
        request.add_header("Referer", "https://cursor.com/dashboard/usage")
        _apply_auth(request, token, auth_modes[auth_index])
        sent = send(request)
        if sent is None:
            return None, f"transport error on page {page}"
        data, status = sent
        if status in (401, 403):
            auth_index += 1
            if auth_index >= len(auth_modes):
                return None, f"auth rejected for all modes (last http {status})"
            continue
        if status < 200 or status > 299:
            preview = data[:160].decode("utf-8", errors="replace").replace("\n", " ")
            return None, f"http {status} on page {page} ({len(data)} bytes) {preview}"
        try:
            object_ = json.loads(data)
        except json.JSONDecodeError:
            return None, f"invalid JSON on page {page} ({len(data)} bytes)"
        if not isinstance(object_, dict):
            return None, f"unexpected JSON on page {page}"
        events = object_.get("usageEventsDisplay")
        if not isinstance(events, list):
            events = object_.get("usageEvents")
        if not isinstance(events, list):
            events = object_.get("events")
        if not isinstance(events, list):
            keys = ",".join(sorted(object_))
            return None, f"missing usageEvents/events on page {page} (keys: {keys})"
        for event in events:
            if isinstance(event, dict):
                entry = parse_usage_event(event, row_index=global_index, since=since)
                if entry is not None:
                    collected.append(entry)
            global_index += 1
        pagination = object_.get("pagination") if isinstance(object_.get("pagination"), dict) else None
        total = object_.get("totalUsageEventsCount")
        total_count = int(total) if isinstance(total, (int, float)) and not isinstance(total, bool) else None
        if not has_next_page(pagination, total_count=total_count, page=page, event_count=len(events)):
            from .usage import _dedup_keep_max

            return _dedup_keep_max(collected), None
        if not events:
            return None, f"pagination indicated next page but page {page} was empty"
        page += 1
    return None, f"pagination exceeded {MAX_PAGES} pages"


def _cache_path() -> Path:
    return state_dir() / "cursor-usage-api-cache.json"


def _entry_to_cache(entry: UsageEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "date": entry.date.isoformat(),
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_write_tokens": entry.cache_write_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "explicit_cost": entry.explicit_cost,
    }


def _entry_from_cache(obj: dict[str, Any]) -> UsageEntry | None:
    from .usage import _entry

    date = _parse_datetime(obj.get("date"))
    if date is None:
        return None
    return _entry(
        id=str(obj.get("id") or ""),
        date=date,
        provider="cursor",
        model=str(obj.get("model") or "unknown"),
        input_tokens=_int(obj.get("input_tokens")),
        output_tokens=_int(obj.get("output_tokens")),
        cache_write_tokens=_int(obj.get("cache_write_tokens")),
        cache_read_tokens=_int(obj.get("cache_read_tokens")),
        explicit_cost=_float(obj.get("explicit_cost")),
    )


def _load_cache(account: str, since: datetime) -> CursorUsageResult | None:
    path = _cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cached_account = data.get("accountIdentifier")
    if cached_account not in (None, account):
        return None
    covered = _parse_datetime(data.get("coveredSince"))
    if covered is not None and covered > since:
        return None
    fetched = _parse_datetime(data.get("fetchedAt"))
    if fetched is None:
        return None
    age = datetime.now(timezone.utc).astimezone() - fetched
    if age.total_seconds() > CACHE_MAX_AGE_SECONDS:
        return None
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        return None
    entries: list[UsageEntry] = []
    for item in raw_entries:
        if isinstance(item, dict):
            entry = _entry_from_cache(item)
            if entry is not None and entry.date >= since:
                entries.append(entry)
    return CursorUsageResult(entries=entries, is_authoritative=covered is None or covered <= since)


def _store_cache(entries: list[UsageEntry], account: str, since: datetime) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetchedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "accountIdentifier": account,
        "coveredSince": since.isoformat(),
        "entries": [_entry_to_cache(entry) for entry in entries],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def fetch_dashboard_entries(
    since: datetime,
    *,
    transport: Transport | None = None,
) -> CursorUsageResult:
    if os.environ.get("CURSOR_USAGE_API", "1").strip() == "0":
        return CursorUsageResult(entries=[], is_authoritative=False, error="disabled")
    token = cursor_auth_access_token()
    if not token:
        return CursorUsageResult(entries=[], is_authoritative=False, error="no session token")
    account = cache_account_identifier(token)
    entries, error = fetch_filtered_events(token, since, transport=transport)
    if entries is not None:
        from .usage import _dedup_keep_max

        fresh = _dedup_keep_max(entries)
        _store_cache(fresh, account, since)
        return CursorUsageResult(entries=[e for e in fresh if e.date >= since], is_authoritative=True)
    cached = _load_cache(account, since)
    if cached is not None:
        return cached
    return CursorUsageResult(entries=[], is_authoritative=False, error=error)


def scan_cursor_local(since: datetime) -> list[UsageEntry]:
    from .usage import (
        _dedup_keep_max,
        _json_dict,
        _open_sqlite_ro,
        cursor_database_candidates,
    )

    entries: list[UsageEntry] = []
    for db in cursor_database_candidates():
        conn = _open_sqlite_ro(db)
        if conn is None:
            continue
        try:
            for _rowid, key, value in conn.execute(
                "SELECT rowid, key, value FROM cursorDiskKV WHERE key GLOB 'bubbleId:*'"
            ):
                obj = _json_dict(value)
                if obj is None:
                    continue
                entry = parse_cursor_bubble(obj, key=str(key), since=since)
                if entry is not None:
                    entries.append(entry)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return _dedup_keep_max(entries)


def scan_cursor(since: datetime) -> list[UsageEntry]:
    global last_scan_warning
    last_scan_warning = None
    api = fetch_dashboard_entries(since)
    if api.is_authoritative:
        return api.entries
    if api.error:
        last_scan_warning = api.error
    return scan_cursor_local(since)

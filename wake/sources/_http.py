# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Vendored from ref-checker/ref_checker/sources/_http.py
"""Shared HTTP helpers for source modules."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ..errors import RateLimited


def parse_retry_after(resp: Any) -> float | None:
    if resp is None:
        return None
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        secs = float(raw)
        return max(0.0, secs)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


def raise_for_rate_limit(resp: Any, source_name: str) -> None:
    """If *resp* is a 429, raise :class:`RateLimited` with parsed Retry-After."""
    status = getattr(resp, "status_code", None)
    if status != 429:
        return
    retry_after = parse_retry_after(resp)
    raise RateLimited(
        retry_after=retry_after,
        message=f"429 Too Many Requests from {source_name}"
        + (f" (Retry-After={retry_after}s)" if retry_after is not None else ""),
    )

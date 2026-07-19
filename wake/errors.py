# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Vendored from ref-checker/ref_checker/errors.py
"""Shared exception types for wake."""
from __future__ import annotations


class RateLimited(Exception):
    """Raised by a source when the upstream API returns HTTP 429.

    ``retry_after`` is the number of seconds the server asked us to wait
    before retrying (from the ``Retry-After`` header), or ``None`` if the
    header was missing or unparseable.
    """

    def __init__(self, retry_after: float | None = None, message: str = "") -> None:
        super().__init__(message or f"rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


class SeedNotFound(Exception):
    """Raised when a seed paper cannot be resolved to an OpenAlex work."""


class OpenAlexError(Exception):
    """Raised on unexpected OpenAlex API errors."""

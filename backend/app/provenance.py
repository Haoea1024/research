"""Stable hashes used to validate persisted translation provenance."""

from __future__ import annotations

import hashlib


def translation_source_hash(value: str | None) -> str:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

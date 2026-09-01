"""Stable, readable identifiers.

Ids are slugs rather than integers so that a failing test names the thing that
failed -- ``flat-1b-2bhk`` rather than ``unit_type 7``.  What matters is that
they are stable: a take-off line holds an id, so rows can be inserted, deleted
or re-sorted without moving anything (C-6).
"""

from __future__ import annotations

import re
import unicodedata


def slug(*parts: object) -> str:
    text = " ".join(str(p) for p in parts if p not in (None, ""))
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "unnamed"


class IdFactory:
    """Hands out unique slugs, suffixing on collision."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def make(self, *parts: object) -> str:
        base = slug(*parts)
        candidate, n = base, 1
        while candidate in self._seen:
            n += 1
            candidate = f"{base}-{n}"
        self._seen.add(candidate)
        return candidate

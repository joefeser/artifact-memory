"""Small synthetic-only helpers shared by checked conformance runners."""

from __future__ import annotations

import threading


class SyntheticReplayLedger:
    """Process-local fixture ledger; production admission requires durability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def claim(self, envelope_ref: str) -> bool:
        with self._lock:
            if envelope_ref in self._seen:
                return False
            self._seen.add(envelope_ref)
            return True

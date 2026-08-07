"""Small synthetic-only helpers shared by checked conformance runners."""

from __future__ import annotations

import copy
import threading
from typing import Any


class SyntheticReplayLedger:
    """Process-local fixture ledger; production admission requires durability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        self._receipts: dict[str, dict[str, Any]] = {}

    def claim(self, envelope_ref: str) -> bool:
        with self._lock:
            if envelope_ref in self._seen:
                return False
            self._seen.add(envelope_ref)
            return True

    def retain(self, acknowledgement_key: str, receipt: dict[str, Any]) -> dict[str, Any]:
        """Atomically retain and replay one synthetic canonical receipt."""
        with self._lock:
            if acknowledgement_key not in self._receipts:
                self._receipts[acknowledgement_key] = copy.deepcopy(receipt)
            return copy.deepcopy(self._receipts[acknowledgement_key])

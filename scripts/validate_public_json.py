#!/usr/bin/env python3
"""Validate JSON syntax in future schemas and synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOTS = (Path("artifact_memory/schemas"), Path("fixtures/synthetic"))


def main() -> int:
    candidates = [path for root in ROOTS if root.exists() for path in root.rglob("*.json")]
    failures = []
    for path in candidates:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            failures.append(f"{path}: {error}")
    if failures:
        print("PUBLIC JSON VALIDATION FAILED", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"public JSON validation passed: {len(candidates)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import re
import subprocess
from pathlib import Path

SUSPICIOUS_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|private[_-]?key)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
)
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".duckdb", ".parquet", ".feather"}
SENSITIVE_NAMES = {".env", ".env.local", "credentials.json", "secrets.json"}


def tracked_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=False,
    )
    return tuple(Path(item) for item in result.stdout.decode("utf-8").split("\0") if item)


def main() -> int:
    failures: list[str] = []
    for path in tracked_files():
        name = path.name.lower()
        if path.suffix.lower() in SENSITIVE_SUFFIXES or name in SENSITIVE_NAMES:
            failures.append(f"tracked sensitive file: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SUSPICIOUS_PATTERNS:
            if pattern.search(text):
                failures.append(f"possible secret pattern: {path}")
                break

    if failures:
        print("PUBLIC BOUNDARY CHECK FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PUBLIC BOUNDARY CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Byte-identical Python mirror of hit-sdd-bench `src/snapshot.ts` hashing.

E2 (Python/Docker harness) emits run artifacts that must be inspectable under the same
provenance discipline as E1 (Bun/TypeScript). That requires the content/directory hashes
to be *byte-identical* across the two implementations. This module reproduces the exact
algorithm in `src/snapshot.ts`:

- `hash_text` / `hash_file`: SHA-256 hex of the UTF-8 bytes (matches `hashBytes`).
- `hash_directory`: recursively collect files (skipping `.git` and `node_modules`),
  key each by POSIX relative path, value = SHA-256 of file bytes, ordered by sorted
  relative path, then SHA-256 over the *compact, insertion-ordered* JSON object — exactly
  what `JSON.stringify` produces (`{"k":"v",...}`, no spaces, raw unicode).

Cross-implementation golden vectors in `tests/test_hashing_roundtrip.py` pin byte-identity
against the TypeScript implementation; do not change canonicalization without regenerating
them from `src/snapshot.ts`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# Mirror of snapshot.ts IGNORED_DIRECTORIES.
IGNORED_DIRECTORIES = frozenset({".git", "node_modules"})


def hash_text(value: str | bytes) -> str:
    """SHA-256 hex of the UTF-8 bytes of `value` (mirrors snapshot.ts `hashText`)."""
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | os.PathLike[str]) -> str:
    """SHA-256 hex of a file's bytes (mirrors snapshot.ts `hashFile`)."""
    return hash_text(Path(path).read_bytes())


def _collect_files(directory: Path) -> list[Path]:
    """Recursively collect file Paths, skipping ignored directories (mirrors `collectFiles`)."""
    out: list[Path] = []
    for entry in directory.iterdir():
        if entry.is_dir():
            if entry.name in IGNORED_DIRECTORIES:
                continue
            out.extend(_collect_files(entry))
        elif entry.is_file():
            out.append(entry)
    return out


def _canonical_json(obj: dict[str, str]) -> str:
    """Compact, insertion-ordered JSON identical to JS `JSON.stringify` for str->str maps."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def hash_directory(directory: str | os.PathLike[str]) -> dict[str, object]:
    """Return {"hash", "files"} for a directory (mirrors snapshot.ts `hashDirectory`).

    `files` maps sorted POSIX relative path -> SHA-256 of file bytes; `hash` is the
    SHA-256 of the compact insertion-ordered JSON of `files`.
    """
    root = Path(directory)
    # snapshot.ts sorts full paths then keys by relpath (relative to root); common-prefix ⇒
    # relpath sort yields identical insertion order. ASCII paths ⇒ code-unit == code-point.
    pairs = sorted(
        ((fp.relative_to(root).as_posix(), fp) for fp in _collect_files(root)),
        key=lambda pair: pair[0],
    )
    files: dict[str, str] = {rel: hash_text(fp.read_bytes()) for rel, fp in pairs}
    return {"hash": hash_text(_canonical_json(files)), "files": files}


# snapshot.ts exposes `hashWorkspace` as an alias of `hashDirectory`.
hash_workspace = hash_directory

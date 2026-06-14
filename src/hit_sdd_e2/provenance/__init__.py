"""Provenance: byte-identical hashing mirror + (later) manifest/run-card emission.

The hashing here reproduces `hit-sdd-bench/src/snapshot.ts` so E2 run artifacts are
inspectable under the same discipline as E1. See `e2-provenance-schema-v1.json` in the
record repo for the shared contract.
"""

from hit_sdd_e2.provenance.hashing import (
    hash_directory,
    hash_file,
    hash_text,
    hash_workspace,
)

__all__ = ["hash_text", "hash_file", "hash_directory", "hash_workspace"]

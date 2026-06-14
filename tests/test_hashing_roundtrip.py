"""Cross-implementation golden test: Python hashing == TypeScript `src/snapshot.ts`.

Golden vectors were produced by running the TS `hashDirectory`/`hashText` on the
`tests/fixtures/sample` directory and the literals below. If the hashing canonicalization
changes on either side, regenerate these from `hit-sdd-bench/src/snapshot.ts`.
"""

from pathlib import Path

from hit_sdd_e2.provenance.hashing import hash_directory, hash_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample"

# Golden vectors from the TypeScript implementation (bun src/snapshot.ts).
GOLDEN_DIR_HASH = "4a735c59d1dc64c27761380014ea5c87e448d750c80608171590d9fa8d74ce71"
GOLDEN_FILES = {
    "a.txt": "b6a98d9ce9a2d9149288fa3df42d377c3e42737afdcdaf714e33c0a100b51060",
    "sub/b.txt": "f2c82decdd7181cf98945929a62598db7e6b477e11f6e0eb0ae97020eff151ad",
}
GOLDEN_TEXT_HELLO = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
GOLDEN_TEXT_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_hash_text_matches_ts():
    assert hash_text("hello") == GOLDEN_TEXT_HELLO
    assert hash_text("") == GOLDEN_TEXT_EMPTY
    # bytes and equivalent str must hash identically
    assert hash_text(b"hello") == GOLDEN_TEXT_HELLO


def test_hash_directory_matches_ts():
    snap = hash_directory(FIXTURE)
    assert snap["files"] == GOLDEN_FILES
    assert snap["hash"] == GOLDEN_DIR_HASH


def test_hash_directory_is_order_independent_of_filesystem():
    # Insertion order is sorted relpath, not filesystem enumeration order; recomputing
    # must be stable and equal to the golden hash.
    assert hash_directory(FIXTURE)["hash"] == GOLDEN_DIR_HASH

"""Boundary tests pinning the magic constants in `code_continuation_probe` / `extract_repro_target`.

These characterize the CURRENT behavior of the membership-inference probe's tunables so a later
extraction-to-named-constants is provably behavior-preserving:
  - extract_repro_target's `min_lines` threshold (the probe calls it with min_lines=8),
  - code_continuation_probe's `prefix_frac=0.45` -> `cut = max(3, round(len*prefix_frac))` split,
  - the `len(suffix.split()) < 15` held-out-token floor.

A patch builder gives exact control over the extracted region's line count and per-line word counts.
"""

from hit_sdd_e2.memorization.probe_exec import code_continuation_probe, extract_repro_target


def _src_patch(code_lines: list[str], path: str = "pkg/mod.py") -> str:
    """A unified diff whose only source hunk's ORIGINAL code is exactly `code_lines` (all context)."""
    n = len(code_lines)
    body = "\n".join(f" {ln}" for ln in code_lines)  # leading space = context line = original code
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,{n} +1,{n} @@ ctx\n{body}\n"


def _probe(code_lines):
    return code_continuation_probe({"repo": "x/y", "patch": _src_patch(code_lines)}, lambda p: "out")


# --- extract_repro_target min_lines threshold (isolated) ---
def test_extract_repro_target_min_lines_threshold():
    seven = [f"x{i} = {i}" for i in range(7)]
    eight = [f"x{i} = {i}" for i in range(8)]
    assert extract_repro_target(_src_patch(seven), min_lines=8) is None
    assert extract_repro_target(_src_patch(eight), min_lines=8) is not None


# --- the probe uses min_lines=8 (region shorter than 8 non-blank lines -> None) ---
def test_probe_requires_min_8_lines():
    seven = [f"alpha_{i} beta_{i} gamma_{i} delta_{i}" for i in range(7)]  # plenty of words, too few lines
    assert _probe(seven) is None
    eight = [f"alpha_{i} beta_{i} gamma_{i} delta_{i}" for i in range(8)]
    assert _probe(eight) is not None


# --- prefix_frac=0.45 -> cut = round(len*0.45) (pins the split point) ---
def test_prefix_frac_split_point():
    ten = [f"w{i}a w{i}b w{i}c" for i in range(10)]   # 3 words/line -> suffix has >=15 words
    r = _probe(ten)
    # round(10*0.45)=round(4.5)=4 -> prefix 4 lines, suffix 6
    assert len(r["prefix"].splitlines()) == 4
    assert len(r["suffix"].splitlines()) == 6

    eleven = [f"w{i}a w{i}b w{i}c" for i in range(11)]
    r2 = _probe(eleven)
    # round(11*0.45)=round(4.95)=5 -> prefix 5 lines, suffix 6
    assert len(r2["prefix"].splitlines()) == 5
    assert len(r2["suffix"].splitlines()) == 6


# --- suffix held-out-token floor: < 15 words -> None, == 15 -> proceeds (exact boundary) ---
def test_suffix_word_floor_is_15():
    prefix4 = ["p", "p", "p", "p"]                       # 4 prefix lines (cut=round(10*0.45)=4)
    suffix_14 = ["a b", "a b", "a b", "a b", "a b", "c d e f"]    # 5*2 + 4 = 14 words
    suffix_15 = ["a b", "a b", "a b", "a b", "a b", "c d e f g"]  # 5*2 + 5 = 15 words
    assert _probe(prefix4 + suffix_14) is None
    ok = _probe(prefix4 + suffix_15)
    assert ok is not None and len(ok["suffix"].split()) == 15

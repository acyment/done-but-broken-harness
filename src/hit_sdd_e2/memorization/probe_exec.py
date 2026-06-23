"""GATE B memorization probe execution: issue-only file-path identification via the model.

Asks the model to name the files to edit given ONLY the issue text (no repo), and scores recall
against the gold-patch files (`file_path_hit_rate`). High recall from the issue alone is a
memorization/familiarity signal (per The SWE-Bench Illusion). The contamination threshold is the
95th percentile of a negative-control distribution (run the same probe on tasks the model can't have
seen); this module computes the raw scores — calibration uses `memorization.probe.calibrate_threshold`.

The model call is injected (`llm_complete: prompt -> text`) so the probe is provider-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable

import re

from hit_sdd_e2.memorization.probe import file_path_hit_rate, ngram_overlap
from hit_sdd_e2.substrate.swebench_live import changed_files, is_test_path

LLMComplete = Callable[[str], str]

_PROMPT = (
    "You are given an issue from the `{repo}` repository. WITHOUT seeing the code, list ONLY the "
    "repository-relative source file paths most likely to need editing to fix it — one path per "
    "line, no prose, no test files.\n\nIssue:\n{issue}"
)


def file_path_id_probe(instance: dict, llm_complete: LLMComplete) -> dict:
    """Return issue-only file-path-identification recall + the predicted/gold file lists."""
    resp = llm_complete(
        _PROMPT.format(repo=instance["repo"], issue=instance["problem_statement"])
    )
    predicted = [
        ln.strip().strip("`-* ")
        for ln in resp.splitlines()
        if ("/" in ln or ln.strip().endswith(".py")) and not is_test_path(ln.strip())
    ]
    gold = [f for f in changed_files(instance["patch"]) if not is_test_path(f)]
    return {
        "file_path_hit_rate": file_path_hit_rate(predicted, gold),
        "predicted": predicted,
        "gold": gold,
    }


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@(.*)$")


def _is_python_source(path: str | None) -> bool:
    """A non-test Python source file (the regression surface) — not docs/config/data."""
    return bool(path) and path.endswith(".py") and not is_test_path(path)


def extract_repro_target(patch: str, min_lines: int = 6) -> dict | None:
    """From a unified diff, extract the original (pre-fix) code of the LARGEST hunk in a non-test
    Python SOURCE file, plus its hunk-header hint. Source-only (skips .rst/.md/.cfg docs, which a
    model paraphrases) and largest-hunk (the substantive change, not an incidental first edit) so the
    probe targets verbatim code recall. Returns {file, hint, actual_code} or None."""
    cur_file = None
    is_src = False
    best: dict | None = None
    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("diff --git "):
            parts = ln.split(" b/", 1)
            cur_file = parts[1].strip() if len(parts) == 2 else None
            is_src = _is_python_source(cur_file)
        elif ln.startswith("@@") and is_src:
            m = _HUNK.match(ln)
            hint = (m.group(1).strip() if m else "")
            body = []
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@", "diff --git ")):
                c = lines[i]
                if c[:1] in (" ", "-"):  # context or removed = ORIGINAL code
                    body.append(c[1:])
                i += 1
            original = "\n".join(body).strip()
            n_nonblank = len([b for b in body if b.strip()])
            if n_nonblank >= min_lines and (best is None or n_nonblank > best["_n"]):
                best = {"file": cur_file, "hint": hint, "actual_code": original, "_n": n_nonblank}
            continue
        i += 1
    if best is not None:
        best.pop("_n", None)
    return best


def _strip_fences(text: str) -> str:
    """Drop leading/trailing markdown code fences so they don't dilute n-gram overlap."""
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].lstrip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


_REPRO_PROMPT = (
    "In the `{repo}` repository, reproduce the EXACT current source code in `{file}` "
    "around `{hint}` (about {n} lines). Output ONLY the code verbatim, no explanation, no fences."
)


def function_reproduction_probe(instance: dict, llm_complete) -> dict | None:
    """Ask the model to reproduce a changed region verbatim; return its output + the actual code.

    Verbatim recall is a memorization signal that reasoning cannot fake (unlike file-path id). The
    caller scores n-gram overlap vs the actual code and calibrates against a mismatched-baseline
    negative control.
    """
    target = extract_repro_target(instance["patch"])
    if target is None:
        return None
    n = len(target["actual_code"].splitlines())
    out = llm_complete(_REPRO_PROMPT.format(
        repo=instance["repo"], file=target["file"], hint=target["hint"] or target["file"], n=n))
    out = _strip_fences(out)
    return {
        "file": target["file"],
        "actual_code": target["actual_code"],
        "reproduction": out,
        "self_overlap": ngram_overlap(out, target["actual_code"], n=5),
    }


_CONTINUE_PROMPT = (
    "The following is the BEGINNING of the source of `{file}` in the `{repo}` repository. Continue it "
    "with the EXACT code that follows in the repository — output ONLY the continuation, verbatim, no "
    "explanation, no fences:\n\n{prefix}"
)

# code_continuation_probe tunables (boundaries pinned by tests/test_continuation_probe_boundaries.py).
_MIN_REGION_LINES = 8     # smallest changed-region size (non-blank lines) worth probing
_PREFIX_FRACTION = 0.45   # fraction of the region shown as the prefix; the rest is the held-out suffix
_MIN_PREFIX_LINES = 3     # floor on prefix lines (defensive; unreachable while _MIN_REGION_LINES >= 7)
_MIN_SUFFIX_TOKENS = 15   # held-out whitespace tokens needed for a meaningful 5-gram overlap


def code_continuation_probe(instance: dict, llm_complete,
                            prefix_frac: float = _PREFIX_FRACTION) -> dict | None:
    """Verbatim-continuation membership-inference probe (no logprobs needed).

    Feed the model the exact prefix of a changed source region and ask it to continue. A model that
    memorized the file continues verbatim (high n-gram overlap with the held-out suffix); a model
    seeing the repo fresh writes plausible-but-different code (low overlap). The prefix pins the
    location, removing the localization ambiguity that made the bare reproduction probe noisy. The
    caller calibrates the overlap against a mismatched-suffix negative control (idiom/predictability
    floor). Returns None if the target is too short to split.
    """
    target = extract_repro_target(instance["patch"], min_lines=_MIN_REGION_LINES)
    if target is None:
        return None
    lines = target["actual_code"].splitlines()
    cut = max(_MIN_PREFIX_LINES, int(round(len(lines) * prefix_frac)))
    prefix = "\n".join(lines[:cut]).strip()
    suffix = "\n".join(lines[cut:]).strip()
    if len(suffix.split()) < _MIN_SUFFIX_TOKENS:  # enough held-out tokens for a 5-gram overlap
        return None
    out = _strip_fences(
        llm_complete(_CONTINUE_PROMPT.format(repo=instance["repo"], file=target["file"], prefix=prefix))
    )
    return {
        "file": target["file"],
        "prefix": prefix,
        "suffix": suffix,
        "continuation": out,
        "continuation_overlap": ngram_overlap(out, suffix, n=5),
    }


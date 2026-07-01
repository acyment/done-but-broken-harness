"""Generate an accurate public-API surface for the blind author by introspecting the repo at base_commit.

The surface MUST carry real signatures (`inspect.signature`), not hand-written ones — a transcribed arity
error propagates verbatim into the authored spec and sinks every scenario that shares the mistaken call
(observed: `add_named_policies_ex(sec, ptype, rules)` vs the real `(ptype, rules)`). This runs a read-only
introspection in the task's OWN container at base_commit and returns a formatted, blind surface block
(public members only; never the gold patch or tests). The author still receives the issue text separately.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Any

# Introspection body run inside the container. Emits one JSON blob describing each target's public members
# and their real signatures. argv[1]=targets ("module:symbol" or "module"), argv[2]=keyword filter list.
_INTROSPECT_PY = r"""
import inspect, json, sys, importlib
targets = json.loads(sys.argv[1]); kw = [k.lower() for k in json.loads(sys.argv[2])]
out = []
for t in targets:
    mod, _, sym = t.partition(":")
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        out.append({"target": t, "error": "import %s: %s: %s" % (mod, type(e).__name__, e)}); continue
    try:
        obj = getattr(m, sym) if sym else m
    except Exception as e:
        out.append({"target": t, "error": "getattr %s: %s" % (sym, e)}); continue
    entry = {"target": t, "kind": "class" if inspect.isclass(obj) else "module", "members": []}
    for n in sorted(x for x in dir(obj) if not x.startswith("_")):
        if kw and not any(k in n.lower() for k in kw):
            continue
        try:
            a = getattr(obj, n)
        except Exception:
            continue
        if not callable(a):
            continue
        try:
            sig = str(inspect.signature(a))
        except (ValueError, TypeError):
            sig = "(...)"
        doc = (inspect.getdoc(a) or "").strip().splitlines()
        entry["members"].append({"name": n, "sig": sig, "doc": (doc[0][:110] if doc else "")})
    out.append(entry)
print("__SURFACE__" + json.dumps(out))
"""


def render_surface(entries: list[dict[str, Any]]) -> str:
    """Format introspected targets into a surface block with real signatures."""
    lines = ["PUBLIC API (introspected from the repo at base_commit — these signatures are exact):"]
    for e in entries:
        if e.get("error"):
            lines.append(f"- {e['target']}: <introspection error: {e['error']}>")
            continue
        lines.append(f"- {e['kind']} `{e['target']}`:")
        if not e["members"]:
            lines.append("    (no public members matched)")
        for m in e["members"]:
            doc = f"  # {m['doc']}" if m["doc"] else ""
            lines.append(f"    - {m['name']}{m['sig']}{doc}")
    return "\n".join(lines)


def introspect_public_api(
    image: str,
    base_commit: str,
    targets: list[str],
    *,
    keyword_filter: list[str] | None = None,
    platform: str = "linux/amd64",
    timeout: int = 180,
) -> str:
    """Introspect `targets` (each `"module"` or `"module:symbol"`) in `image` at `base_commit`.

    `keyword_filter` keeps only public members whose name contains one of the (case-insensitive) keywords —
    use it to focus on the issue-relevant surface instead of dumping a whole class. Returns the rendered
    surface block (real signatures). Raises on a docker/parse failure so a bad surface never silently ships.
    """
    inner = (
        f"cd /testbed && git checkout -f {shlex.quote(base_commit)} >/dev/null 2>&1 && "
        f"python -c {shlex.quote(_INTROSPECT_PY)} "
        f"{shlex.quote(json.dumps(targets))} {shlex.quote(json.dumps(keyword_filter or []))}"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--platform", platform, image, "bash", "-lc", inner],
        capture_output=True, text=True, timeout=timeout,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("__SURFACE__"):
            return render_surface(json.loads(line[len("__SURFACE__"):]))
    raise RuntimeError(f"introspection produced no surface (rc={proc.returncode}): {proc.stderr[-400:]}")

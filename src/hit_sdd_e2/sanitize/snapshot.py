"""Adversarial snapshot sanitization for SWE-bench Live containers.

SWE-bench Live images ship `/testbed` checked out at `base_commit` but with the FULL git
clone intact: a live `origin` remote, remote-tracking branches, and tags that contain the
fix/future commits. An agent can `git show <fix>`, `git log origin/master`, or `git fetch`
to read the answer (the documented exploit). Sanitization detaches HEAD at base, deletes all
branches/remotes/tags/reflog, and `git gc --prune=now` to purge the now-unreachable future
objects — preserving the legitimate base-and-ancestors history. Network is separately denied
at run time (`--network none`).

Verified on spulec__freezegun-582: future commit goes REACHABLE -> PRUNED; remotes/tags 0;
`git rev-list --all --not HEAD` == 0; base ancestry (674 commits) intact.
"""

from __future__ import annotations

import json
import subprocess
import uuid


def sanitize_script(base_commit: str) -> str:
    """Bash run inside the container to strip all future/fix git history."""
    return f"""set -e
cd /testbed
git checkout -q --detach {base_commit}
git for-each-ref --format='%(refname)' refs/heads  | while read r; do git update-ref -d "$r"; done
for rem in $(git remote); do git remote remove "$rem"; done
git for-each-ref --format='%(refname)' refs/remotes | while read r; do git update-ref -d "$r"; done
git tag -l | while read t; do [ -n "$t" ] && git tag -d "$t" >/dev/null; done
git for-each-ref --format='%(refname)' refs/tags    | while read r; do git update-ref -d "$r"; done
git reflog expire --expire=now --all 2>/dev/null || true
git gc --prune=now >/dev/null 2>&1 || true
"""


def build_sanitized_image(
    base_image: str,
    base_commit: str,
    out_tag: str,
    platform: str = "linux/amd64",
) -> str:
    """Apply sanitization to `base_image` and commit a derived image `out_tag`. Returns its Id.

    The agent and oracle then run on the sanitized image with `--network none`.
    """
    cname = f"e2-sanitize-{uuid.uuid4().hex[:12]}"
    try:
        subprocess.run(
            ["docker", "run", "--name", cname, "--network", "none", "--platform", platform,
             base_image, "bash", "-c", sanitize_script(base_commit)],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(["docker", "commit", cname, out_tag], check=True, capture_output=True, text=True)
    finally:
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True, text=True)
    inspect = subprocess.run(
        ["docker", "image", "inspect", out_tag], check=True, capture_output=True, text=True,
    )
    return json.loads(inspect.stdout)[0]["Id"]


def verify_no_future_history(
    image: str,
    future_probe_sha: str,
    platform: str = "linux/amd64",
) -> dict:
    """Run git checks in `image`; assert the future probe SHA is unreachable and no extra refs."""
    script = f"""cd /testbed
echo "unreachable_from_head=$(git rev-list --all --not HEAD 2>/dev/null | wc -l | tr -d ' ')"
echo "remotes=$(git remote | wc -l | tr -d ' ')"
echo "tags=$(git tag | wc -l | tr -d ' ')"
echo "probe_reachable=$(git cat-file -e {future_probe_sha} 2>/dev/null && echo yes || echo no)"
"""
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--platform", platform, image, "bash", "-c", script],
        capture_output=True, text=True,
    )
    parsed = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    return {
        "no_future_reachable": parsed.get("unreachable_from_head") == "0"
        and parsed.get("probe_reachable") == "no",
        "no_remotes": parsed.get("remotes") == "0",
        "no_tags": parsed.get("tags") == "0",
        "raw": parsed,
    }


def network_is_blocked(image: str, platform: str = "linux/amd64") -> bool:
    """True iff an outbound connection fails under `--network none` (defense-in-depth check)."""
    probe = (
        "python -c \"import socket,sys; "
        "s=socket.socket(); s.settimeout(3); "
        "sys.exit(0 if s.connect_ex(('140.82.112.3',443))!=0 else 1)\""  # github IP; nonzero = blocked
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "--platform", platform, image, "bash", "-c", probe],
        capture_output=True, text=True,
    )
    return proc.returncode == 0

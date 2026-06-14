"""Guard test for the sanitization script (Docker paths validated live on freezegun-582)."""

from hit_sdd_e2.sanitize.snapshot import sanitize_script


def test_sanitize_script_strips_all_future_surfaces():
    s = sanitize_script("abc123")
    assert "git checkout -q --detach abc123" in s  # detach at base
    assert "refs/heads" in s and "refs/remotes" in s and "refs/tags" in s  # delete all ref classes
    assert "git remote remove" in s
    assert "git tag -d" in s
    assert "reflog expire --expire=now --all" in s
    assert "git gc --prune=now" in s  # purge now-unreachable future objects

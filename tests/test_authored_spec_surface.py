"""Unit tests for the introspected-surface renderer (pure; docker path is exercised live in the screen)."""

from __future__ import annotations

from hit_sdd_e2.authored_spec.surface import render_surface


def test_render_surface_carries_real_signatures_and_docs():
    s = render_surface([{"target": "casbin:Enforcer", "kind": "class", "members": [
        {"name": "add_named_policies_ex", "sig": "(self, ptype, rules)", "doc": "adds named rules"},
        {"name": "add_policies_ex", "sig": "(self, rules)", "doc": ""},
    ]}])
    assert "class `casbin:Enforcer`:" in s
    assert "add_named_policies_ex(self, ptype, rules)  # adds named rules" in s
    assert "add_policies_ex(self, rules)" in s


def test_render_surface_reports_import_error_and_empty():
    s = render_surface([
        {"target": "nope:Y", "error": "import nope: ModuleNotFoundError"},
        {"target": "pkg:Z", "kind": "class", "members": []},
    ])
    assert "introspection error: import nope" in s
    assert "(no public members matched)" in s

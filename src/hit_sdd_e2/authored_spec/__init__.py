"""Authored-spec offline pilot primitives for the E2 harness."""

from hit_sdd_e2.authored_spec.bundle import (
    AUTHORED_SPEC_DESIGN,
    AUTHORED_SPEC_ORACLE_SOURCE,
    AuthoredSpecBundle,
)
from hit_sdd_e2.authored_spec.compiler import compile_draft
from hit_sdd_e2.authored_spec.manifest import AuthoredCheck, CheckManifest
from hit_sdd_e2.authored_spec.scoring import AuthoredSpecScoreRecord, score_authored_spec_candidate

__all__ = [
    "AUTHORED_SPEC_DESIGN",
    "AUTHORED_SPEC_ORACLE_SOURCE",
    "AuthoredCheck",
    "AuthoredSpecBundle",
    "AuthoredSpecScoreRecord",
    "CheckManifest",
    "compile_draft",
    "score_authored_spec_candidate",
]

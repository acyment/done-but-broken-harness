"""Authored-spec bundle metadata for the E2 offline pilot.

The bundle is the sealed unit for the authored-spec study: prose spec, compiled black-box
checks, synthetic hardening battery, transcript, and gate reports. This module intentionally
does not run Docker or call providers; it only models and validates the artifact envelope.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hit_sdd_e2.provenance.hashing import hash_file, hash_text

AUTHORED_SPEC_DESIGN = "authored-spec-v1"
AUTHORED_SPEC_ORACLE_SOURCE = "authored_spec"
BUNDLE_SCHEMA = "authored-spec-bundle-v1"


@dataclass(frozen=True)
class AuthoredSpecBundle:
    instance_id: str
    spec_id: str
    spec_hash: str
    openspec_proposal_path: str
    check_manifest_path: str
    authoring_transcript_hash: str
    # Superseded: the current design replaced the mutation/synthetic-patch battery with the structural
    # tautology audit (gates.tautology_audit). Kept optional for back-compat and for studies that opt
    # back into a battery; empty string = no battery (hashed as "").
    synthetic_patch_battery_manifest_path: str = ""
    # Step-binding artifact (per-scenario step code + surface + then_reference + pinned converter version).
    # Covered by spec_hash so the sealed oracle fully determines the derived .feature/checks. "" = none.
    bindings_path: str = ""
    hardening_report: dict[str, Any] = field(default_factory=dict)
    flake_cert_report: dict[str, Any] = field(default_factory=dict)
    sealed_at: str | None = None
    schema_version: str = BUNDLE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthoredSpecBundle":
        if data.get("schema_version", BUNDLE_SCHEMA) != BUNDLE_SCHEMA:
            raise ValueError(f"unknown authored-spec bundle schema: {data.get('schema_version')!r}")
        return cls(
            instance_id=data["instance_id"],
            spec_id=data["spec_id"],
            spec_hash=data["spec_hash"],
            openspec_proposal_path=data["openspec_proposal_path"],
            check_manifest_path=data["check_manifest_path"],
            synthetic_patch_battery_manifest_path=data.get("synthetic_patch_battery_manifest_path", ""),
            bindings_path=data.get("bindings_path", ""),
            authoring_transcript_hash=data["authoring_transcript_hash"],
            hardening_report=dict(data.get("hardening_report") or {}),
            flake_cert_report=dict(data.get("flake_cert_report") or {}),
            sealed_at=data.get("sealed_at"),
            schema_version=data.get("schema_version", BUNDLE_SCHEMA),
        )

    @classmethod
    def load(cls, path: str | Path) -> "AuthoredSpecBundle":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def dump(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n")


def compute_spec_hash(
    *,
    openspec_proposal_text: str,
    check_manifest_text: str,
    synthetic_patch_battery_text: str = "",
    bindings_text: str = "",
) -> str:
    """Hash the authored oracle inputs as one deterministic sealed object.

    Covers the canonical OpenSpec proposal, the check manifest, and (`bindings_text`) the step-binding
    artifact — which carries the executable step code AND the pinned OpenSpec->Gherkin converter version,
    so a sealed `spec_hash` fully determines the derived `.feature`/checks. `synthetic_patch_battery_text`
    defaults to "" (superseded by the tautology audit) but stays in the payload for stability.
    """
    payload = {
        "openspec_proposal": openspec_proposal_text,
        "check_manifest": check_manifest_text,
        "synthetic_patch_battery": synthetic_patch_battery_text,
        "bindings": bindings_text,
    }
    return hash_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def compute_spec_hash_from_files(
    *,
    openspec_proposal_path: str | Path,
    check_manifest_path: str | Path,
    synthetic_patch_battery_manifest_path: str | Path = "",
    bindings_path: str | Path = "",
) -> str:
    def _read(p: str | Path) -> str:
        return Path(p).read_text() if p else ""

    return compute_spec_hash(
        openspec_proposal_text=Path(openspec_proposal_path).read_text(),
        check_manifest_text=Path(check_manifest_path).read_text(),
        synthetic_patch_battery_text=_read(synthetic_patch_battery_manifest_path),
        bindings_text=_read(bindings_path),
    )


def validate_bundle_hash(bundle: AuthoredSpecBundle, *, root: str | Path = ".") -> bool:
    root = Path(root)
    battery = bundle.synthetic_patch_battery_manifest_path
    actual = compute_spec_hash_from_files(
        openspec_proposal_path=root / bundle.openspec_proposal_path,
        check_manifest_path=root / bundle.check_manifest_path,
        synthetic_patch_battery_manifest_path=(root / battery) if battery else "",
        bindings_path=(root / bundle.bindings_path) if bundle.bindings_path else "",
    )
    return actual == bundle.spec_hash


def transcript_hash(transcript: dict[str, Any]) -> str:
    return hash_text(json.dumps(transcript, sort_keys=True, separators=(",", ":")))


def file_hash_or_empty(path: str | Path | None) -> str:
    return hash_file(path) if path else ""

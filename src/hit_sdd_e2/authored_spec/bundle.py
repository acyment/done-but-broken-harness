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
) -> str:
    """Hash the authored oracle inputs as one deterministic sealed object.

    `synthetic_patch_battery_text` defaults to "" (no battery — the tautology audit supersedes it);
    it stays in the payload so hashes remain stable for studies that do attach a battery.
    """
    payload = {
        "openspec_proposal": openspec_proposal_text,
        "check_manifest": check_manifest_text,
        "synthetic_patch_battery": synthetic_patch_battery_text,
    }
    return hash_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def compute_spec_hash_from_files(
    *,
    openspec_proposal_path: str | Path,
    check_manifest_path: str | Path,
    synthetic_patch_battery_manifest_path: str | Path = "",
) -> str:
    battery_text = (
        Path(synthetic_patch_battery_manifest_path).read_text()
        if synthetic_patch_battery_manifest_path
        else ""
    )
    return compute_spec_hash(
        openspec_proposal_text=Path(openspec_proposal_path).read_text(),
        check_manifest_text=Path(check_manifest_path).read_text(),
        synthetic_patch_battery_text=battery_text,
    )


def validate_bundle_hash(bundle: AuthoredSpecBundle, *, root: str | Path = ".") -> bool:
    root = Path(root)
    battery = bundle.synthetic_patch_battery_manifest_path
    actual = compute_spec_hash_from_files(
        openspec_proposal_path=root / bundle.openspec_proposal_path,
        check_manifest_path=root / bundle.check_manifest_path,
        synthetic_patch_battery_manifest_path=(root / battery) if battery else "",
    )
    return actual == bundle.spec_hash


def transcript_hash(transcript: dict[str, Any]) -> str:
    return hash_text(json.dumps(transcript, sort_keys=True, separators=(",", ":")))


def file_hash_or_empty(path: str | Path | None) -> str:
    return hash_file(path) if path else ""

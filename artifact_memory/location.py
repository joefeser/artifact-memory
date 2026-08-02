"""Portable logical locations separated from machine-local resolution."""

from __future__ import annotations

import re
from typing import Any

from .schema_resources import load_schema
from .validator import ValidationFailure, validate


AUTHORITY_BOUNDARY = "location observation grants no access, mutation, disclosure, or execution authority"
ARTIFACT_REF = re.compile(r"^artifact://[A-Za-z0-9._~-]+/[A-Za-z0-9._~-]+$")
CONTENT_REF = re.compile(r"^content://sha-256/[0-9a-f]{64}$")
ENDPOINT_REF = re.compile(r"^endpoint://[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)?$")
RELATIVE_PATH = re.compile(r"^(?!/)(?!.*(^|/)\.\.(?:/|$))(?!.*\\)(?!.*://)[A-Za-z0-9._~/-]+$")


def validate_logical_references(artifact_ref: str, content_ref: str, endpoint_ref: str, relative_path: str) -> None:
    """Fail closed when a portable reference contains location-specific syntax."""
    values = (
        ("artifact_ref", artifact_ref, ARTIFACT_REF),
        ("content_ref", content_ref, CONTENT_REF),
        ("endpoint_ref", endpoint_ref, ENDPOINT_REF),
        ("relative_path", relative_path, RELATIVE_PATH),
    )
    for field, value, pattern in values:
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise ValidationFailure("invalid-logical-reference", f"{field} is not a portable logical reference", f"$.{field}")


def validate_endpoint(endpoint: dict[str, Any]) -> None:
    validate(endpoint, load_schema("core", "storage-endpoint.v1.schema.json"))


def validate_discovery_evidence(evidence: dict[str, Any]) -> None:
    validate(evidence, load_schema("core", "endpoint-discovery-evidence.v1.schema.json"))


def validate_location_observation(observation: dict[str, Any]) -> None:
    validate(observation, load_schema("core", "location-observation.v2.schema.json"))
    validate_logical_references(
        observation["artifact_ref"],
        observation["content_ref"],
        observation["endpoint_ref"],
        observation["relative_path"],
    )
    presence = observation["presence_state"]
    verification = observation["verification_state"]
    if verification == "content-verified" and presence != "present":
        raise ValidationFailure("inconsistent-location-state", "content verification requires present bytes", "$.verification_state")
    if presence == "unavailable" and verification not in {"not-applicable", "unverified"}:
        raise ValidationFailure("inconsistent-location-state", "unavailable endpoints cannot carry a verification result", "$.verification_state")
    if presence == "absent" and verification == "content-verified":
        raise ValidationFailure("inconsistent-location-state", "absent bytes cannot be content verified", "$.verification_state")

"""Shared B05 alternative framework/status coherence; no linkage admission."""

from typing import Any


def alternative_envelope_issues(alternative: dict[str, Any]) -> tuple[str, ...]:
    typed = alternative.get("typed_analysis")
    if not isinstance(typed, dict):
        return ()
    return tuple(
        f"alternative {field} must agree with typed_analysis.{field}"
        for field in ("framework", "status")
        if alternative.get(field) != typed.get(field)
    )


def alternative_envelope_status(alternative: dict[str, Any]) -> str:
    if not isinstance(alternative.get("typed_analysis"), dict) or alternative_envelope_issues(alternative):
        return "missing"
    status = alternative.get("status")
    if status == "established":
        return "resolved"
    if status in {"unresolved", "review_required"}:
        return "unresolved"
    return "missing"


def combine_authority_status(nested: str, envelope: str) -> str:
    if "missing" in (nested, envelope):
        return "missing"
    if "unresolved" in (nested, envelope):
        return "unresolved"
    return "resolved"

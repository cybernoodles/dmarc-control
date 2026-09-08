from __future__ import annotations

from typing import Any


def classify_host(
    automatic: dict[str, Any], override: dict[str, Any] | None
) -> tuple[dict[str, Any], str]:
    """Apply human intent without attributing detector evidence to a manual name."""
    stored = override or {}
    mode = stored.get("classification_mode", "legacy_preserved" if override else "automatic")
    manual_name = stored.get("manual_service_name", stored.get("service_name"))
    manual = mode != "automatic" and bool(manual_name)
    detection = {
        **automatic,
        "automatic_detection": dict(automatic),
        "automatic_service": automatic["service"],
        "classification_mode": mode,
        "manual_service_name": manual_name if mode != "automatic" else None,
        "manual_override": manual,
    }
    if manual:
        detection.update(
            service=manual_name,
            confidence=None,
            confidence_label="Übernommen" if mode == "legacy_preserved" else "Manuell",
            evidence=[],
            evidence_details=[],
        )
    trust = stored.get("trust_status", "automatic")
    if trust == "automatic":
        trust = "automatic" if automatic["confidence"] >= 0.55 else "unconfirmed"
    return detection, trust

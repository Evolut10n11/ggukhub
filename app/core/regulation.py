from __future__ import annotations

from typing import Any

REGULATION_VERSION = "uk_zeleniy_sad_telegram_v1"


def build_report_composition_payload(
    *,
    source_session: dict[str, Any],
    normalized_report: dict[str, Any],
    category_label: str,
    is_mass_incident: bool,
    incident_id: int | None,
) -> dict[str, Any]:
    session_view = {
        "jk": source_session.get("jk"),
        "house": source_session.get("house"),
        "entrance": source_session.get("entrance"),
        "apartment": source_session.get("apartment"),
        "phone": source_session.get("phone"),
        "problem_text": source_session.get("problem_text"),
        "auto_category": source_session.get("auto_category"),
        "final_category": source_session.get("category"),
    }
    return {
        "regulation": {
            "version": REGULATION_VERSION,
            "channel": "telegram",
            "required_fields": [
                "jk",
                "house",
                "entrance",
                "apartment",
                "phone",
                "problem_text",
                "category",
            ],
            "forbidden_behavior": [
                "do_not_invent_deadlines",
                "do_not_invent_root_cause",
            ],
        },
        "session_input": session_view,
        "normalized_report": normalized_report,
        "classification": {
            "category": normalized_report.get("category"),
            "category_label": category_label,
        },
        "incident": {
            "is_mass": is_mass_incident,
            "incident_id": incident_id,
        },
    }


def build_bitrix_audit_payload(*, bitrix_id: str | None, status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "regulation": {
            "version": REGULATION_VERSION,
            "channel": "telegram",
        },
        "bitrix": {
            "status": status,
            "bitrix_id": bitrix_id,
            "error": error,
        },
    }


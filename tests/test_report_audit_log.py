from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.models import Base
from app.core.regulation import REGULATION_VERSION, build_report_composition_payload
from app.core.schemas import ReportAuditCreate, ReportCreate
from app.core.storage import Storage


def test_build_report_composition_payload_contains_regulation_and_fields() -> None:
    payload = build_report_composition_payload(
        source_session={
            "jk": "Pride Park",
            "house": "5",
            "entrance": "3",
            "apartment": "78",
            "phone": "+79001112233",
            "problem_text": "Лифт не работает",
            "auto_category": "elevator",
            "category": "elevator",
        },
        normalized_report={
            "local_report_id": 10,
            "jk": "Pride Park",
            "address": "дом 5, подъезд 3, кв 78",
            "category": "elevator",
        },
        category_label="Лифт",
        is_mass_incident=False,
        incident_id=None,
    )

    assert payload["regulation"]["version"] == REGULATION_VERSION
    assert payload["session_input"]["jk"] == "Pride Park"
    assert payload["normalized_report"]["category"] == "elevator"
    assert payload["classification"]["category_label"] == "Лифт"


@pytest.mark.asyncio
async def test_storage_persists_report_audit_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = Storage(session_factory)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        user = await storage.upsert_user(telegram_id=777001, name="Tester")
        report = await storage.create_report(
            ReportCreate(
                user_id=user.id,
                jk="Pride Park",
                address="дом 5, подъезд 3, кв 78",
                apt="78",
                phone="+79001112233",
                category="elevator",
                text="Лифт не работает",
                scope_key="pride park::elevator",
            )
        )

        await storage.create_report_audit(
            ReportAuditCreate(
                report_id=report.id,
                stage="report_created",
                regulation_version=REGULATION_VERSION,
                payload={"checklist": {"jk": True, "phone": True}},
            )
        )

        rows = await storage.get_report_audits(report.id)
        assert len(rows) == 1
        assert rows[0].stage == "report_created"
        assert rows[0].regulation_version == REGULATION_VERSION
        parsed = json.loads(rows[0].payload_json)
        assert parsed["checklist"]["jk"] is True
    finally:
        await engine.dispose()


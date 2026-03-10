from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.models import Base
from app.core.storage import Storage
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.responders.models import GeneratedResponse, ResponseGeneratorSource
from app.telegram.dialog.finalization import DialogReportFinalizer
from app.telegram.dialog.models import DialogSessionData


class _ResponderStub:
    async def build_report_created(self, local_id: int, bitrix_id: str | None) -> GeneratedResponse:
        _ = bitrix_id
        return GeneratedResponse(
            text=f"Заявка {local_id} зарегистрирована.",
            source=ResponseGeneratorSource.RULES,
            metadata={
                "responder_mode": "rules",
                "fallback_used": False,
                "rule_vs_llm_path": "rules",
                "timeout_occurred": False,
            },
        )


class _BitrixStub:
    enabled = False

    async def create_ticket(self, report, user) -> str:
        raise AssertionError("bitrix sync should not run in finalize_report test")


class _NotifierStub:
    async def send_message(self, telegram_id: int, text: str) -> None:
        _ = telegram_id, text


@pytest.mark.asyncio
async def test_dialog_finalizer_returns_structured_confirmation_metadata(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'finalization.db'}", connect_args={"check_same_thread": False})
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = Storage(session_factory)
    incidents = IncidentService(storage=storage, detector=SpikeDetector(window_minutes=15, threshold=999))
    user = await storage.upsert_user(telegram_id=501001, name="Tester")

    finalizer = DialogReportFinalizer(
        storage=storage,
        incidents=incidents,
        responder=_ResponderStub(),
        bitrix_service=_BitrixStub(),
        notifier=_NotifierStub(),
        label_resolver=lambda code: {"elevator": "Лифт", "other": "Другое"}.get(code, code),
        confirmation_budget_ms=3200,
    )

    result = await finalizer.finalize_report(
        user=user,
        data=DialogSessionData(
            jk="Pride Park",
            house="5",
            entrance="3",
            apartment="78",
            phone="+79990001122",
            problem_text="Лифт не работает",
            category="elevator",
        ),
    )

    assert result.confirmation.local_report_id == result.report.id
    assert result.confirmation.category == "elevator"
    assert result.confirmation.responder_mode == "rules"
    assert result.confirmation.fallback_used is False
    assert "Сводка по заявке" in result.confirmation.summary
    assert result.confirmation.metadata["flow_name"] == "report_created"
    assert result.confirmation.metadata["step_name"] == "confirmation_reply"
    assert result.confirmation.metadata["budget_ms"] == 3200
    assert result.confirmation.metadata["bitrix_sync_outcome"] == "disabled"

    await engine.dispose()

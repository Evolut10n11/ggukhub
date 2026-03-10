from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bitrix.client import BitrixApiClient, BitrixClientError
from app.bitrix.service import BitrixTicketService
from app.config.settings import Settings
from app.core.classifier import CategoryClassifier
from app.core.llm_category import LLMCategoryResolver
from app.core.models import Base, Report, User
from app.core.services import AppServices
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.core.utils import load_json
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.responders.rule_responder import RuleResponder
from app.telegram.handlers.dialog import _process_text_dialog


class _SpeechStub:
    enabled = False


class _BitrixWebhookStub:
    pass


class _NotifierStub:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, telegram_id: int, text: str) -> None:
        self.messages.append((telegram_id, text))


class _BitrixCreateStub:
    enabled = True

    def __init__(self, *, bitrix_id: str) -> None:
        self.bitrix_id = bitrix_id
        self.calls: list[dict[str, Any]] = []

    async def create_ticket(self, report: Report, user: User) -> str:
        self.calls.append(
            {
                "report_id": report.id,
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "jk": report.jk,
                "address": report.address,
                "apt": report.apt,
                "phone": report.phone,
                "category": report.category,
                "text": report.text,
            }
        )
        return self.bitrix_id


class _BitrixFailStub:
    enabled = True

    async def create_ticket(self, report: Report, user: User) -> str:
        _ = report, user
        raise BitrixClientError("bitrix gateway unavailable")


class _MessageStub:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id, full_name=f"User {user_id}", username=None)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        _ = reply_markup
        self.answers.append(text)


async def _build_services(db_path: Path, *, bitrix_client: Any, notifier: _NotifierStub) -> tuple[AppServices, Any]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = Settings(
        telegram_bot_token="test-token",
        use_llm=False,
        incident_threshold=999,
        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
    )
    classifier = CategoryClassifier.from_file(Path("data/categories.json"))
    llm_category = LLMCategoryResolver(settings, classifier)
    storage = Storage(session_factory)
    incidents = IncidentService(storage=storage, detector=SpikeDetector(window_minutes=15, threshold=999))

    services = AppServices(
        settings=settings,
        storage=storage,
        classifier=classifier,
        llm_category=llm_category,
        incidents=incidents,
        responder=RuleResponder(),
        speech=_SpeechStub(),
        bitrix_client=SimpleNamespace(enabled=bitrix_client.enabled),
        bitrix_service=bitrix_client,
        bitrix_webhook=_BitrixWebhookStub(),
        notifier=notifier,
        housing_complexes=list(load_json(Path("data/housing_complexes.json"))),
        tariffs=TariffDirectory(Path("data/tariffs.json")),
    )
    return services, engine


async def _run_full_dialog_flow(services: AppServices, *, user_id: int, phone: str) -> list[str]:
    flow = [
        "привет",
        "ЖК Pride Park",
        "5",
        "3",
        "78",
        phone,
        "Лифт не работает",
        "да",
    ]
    replies: list[str] = []
    for text in flow:
        message = _MessageStub(user_id=user_id)
        await _process_text_dialog(message, services, text, from_voice=False)
        replies.extend(message.answers)
    return replies


@pytest.mark.asyncio
async def test_bitrix_client_create_ticket_builds_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        telegram_bot_token="x",
        use_llm=False,
        bitrix_webhook_url="https://bitrix.example/rest/1/webhook",
    )
    api_client = BitrixApiClient(settings)
    client = BitrixTicketService(settings=settings, client=api_client)
    report = Report(
        id=42,
        user_id=1,
        jk="Pride Park",
        address="дом 5, подъезд 3, кв 78",
        apt="78",
        phone="+79990001122",
        category="elevator",
        text="Лифт не работает",
        scope_key="pride park::elevator",
    )
    user = User(id=1, telegram_id=123456789, name="Tester")

    captured: dict[str, Any] = {}

    async def fake_call(method: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["method"] = method
        captured["payload"] = payload
        return {"result": 90001}

    monkeypatch.setattr(api_client, "call", fake_call)

    bitrix_id = await client.create_ticket(report=report, user=user)
    assert bitrix_id == "90001"
    assert captured["method"] == settings.bitrix_ticket_method

    fields = captured["payload"]["fields"]
    assert "#42" in str(fields[settings.bitrix_field_title])
    assert "Лифт не работает" in str(fields[settings.bitrix_field_description])
    assert "Категория: elevator" in str(fields[settings.bitrix_field_description])
    assert fields[settings.bitrix_field_jk] == "Pride Park"
    assert fields[settings.bitrix_field_address] == "дом 5, подъезд 3, кв 78"
    assert fields[settings.bitrix_field_category] == "elevator"
    assert fields[settings.bitrix_field_telegram_id] == "123456789"
    assert fields[settings.bitrix_field_local_report_id] == "42"
    assert fields["PHONE"] == [{"VALUE": "+79990001122", "VALUE_TYPE": "WORK"}]


@pytest.mark.asyncio
async def test_dialog_flow_creates_report_and_persists_bitrix_id(tmp_path: Path) -> None:
    db_path = tmp_path / "bitrix_sync_ok.db"
    notifier = _NotifierStub()
    bitrix_stub = _BitrixCreateStub(bitrix_id="B24-7001")
    services, engine = await _build_services(db_path, bitrix_client=bitrix_stub, notifier=notifier)

    try:
        replies = await _run_full_dialog_flow(services, user_id=300_001, phone="+79990001122")
        await services.dialog_runtime.wait_background_tasks()

        assert bitrix_stub.calls, "Bitrix create_ticket was not called"
        call = bitrix_stub.calls[0]
        assert call["jk"] == "Pride Park"
        assert call["address"] == "дом 5, подъезд 3, кв 78"
        assert call["category"] == "elevator"
        assert call["text"] == "Лифт не работает"

        report_with_user = await services.storage.get_report_with_user_by_bitrix_id("B24-7001")
        assert report_with_user is not None
        report, user = report_with_user
        assert report.bitrix_id == "B24-7001"
        assert report.status == "new"
        assert user.telegram_id == 300_001

        audits = await services.storage.get_report_audits(report.id)
        stages = [item.stage for item in audits]
        assert "report_created" in stages
        assert "bitrix_synced" in stages

        assert any("Проверьте, пожалуйста, заявку перед отправкой" in text for text in replies)
        assert any("Сводка по заявке" in text for text in replies)
        assert any("Bitrix24" in text for text in replies)
        assert any("B24-7001" in text for _, text in notifier.messages)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dialog_flow_bitrix_failure_keeps_local_report_and_logs_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "bitrix_sync_fail.db"
    notifier = _NotifierStub()
    services, engine = await _build_services(db_path, bitrix_client=_BitrixFailStub(), notifier=notifier)

    try:
        _ = await _run_full_dialog_flow(services, user_id=300_002, phone="+79990002233")
        await services.dialog_runtime.wait_background_tasks()

        user = await services.storage.get_user_by_telegram_id(300_002)
        assert user is not None

        async with services.storage._session_factory() as session:
            stmt = select(Report).where(Report.user_id == user.id).order_by(Report.id.desc())
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()

        assert report is not None
        assert report.bitrix_id is None

        audits = await services.storage.get_report_audits(report.id)
        stages = [item.stage for item in audits]
        assert "report_created" in stages
        assert "bitrix_sync_failed" in stages

        assert any("Передачу в Bitrix24 уточняю вручную" in text for _, text in notifier.messages)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_is_not_created_until_final_confirmation(tmp_path: Path) -> None:
    db_path = tmp_path / "bitrix_wait_confirm.db"
    notifier = _NotifierStub()
    bitrix_stub = _BitrixCreateStub(bitrix_id="B24-9001")
    services, engine = await _build_services(db_path, bitrix_client=bitrix_stub, notifier=notifier)

    try:
        flow = [
            "привет",
            "ЖК Pride Park",
            "5",
            "3",
            "78",
            "+79990001122",
            "Лифт не работает",
        ]
        replies: list[str] = []
        for text in flow:
            message = _MessageStub(user_id=300_003)
            await _process_text_dialog(message, services, text, from_voice=False)
            replies.extend(message.answers)

        user = await services.storage.get_user_by_telegram_id(300_003)
        assert user is not None

        async with services.storage._session_factory() as session:
            stmt = select(Report).where(Report.user_id == user.id).order_by(Report.id.desc())
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()

        assert report is None
        assert any("Проверьте, пожалуйста, заявку перед отправкой" in text for text in replies)
        assert not bitrix_stub.calls
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_correction_step_allows_fixing_category_before_creation(tmp_path: Path) -> None:
    db_path = tmp_path / "bitrix_edit_before_confirm.db"
    notifier = _NotifierStub()
    bitrix_stub = _BitrixCreateStub(bitrix_id="B24-9002")
    services, engine = await _build_services(db_path, bitrix_client=bitrix_stub, notifier=notifier)

    try:
        flow = [
            "привет",
            "ЖК Pride Park",
            "5",
            "3",
            "78",
            "+79990001122",
            "Лифт не работает",
            "нет",
            "Нет воды",
            "да",
        ]
        for text in flow:
            message = _MessageStub(user_id=300_004)
            await _process_text_dialog(message, services, text, from_voice=False)

        await services.dialog_runtime.wait_background_tasks()
        user = await services.storage.get_user_by_telegram_id(300_004)
        assert user is not None

        async with services.storage._session_factory() as session:
            stmt = select(Report).where(Report.user_id == user.id).order_by(Report.id.desc())
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()

        assert report is not None
        assert report.category == "water_off"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_BITRIX_LIVE_TESTS") != "1",
    reason="Set RUN_BITRIX_LIVE_TESTS=1 to run live Bitrix smoke",
)
async def test_bitrix_live_create_ticket_smoke() -> None:
    if not os.getenv("BITRIX_WEBHOOK_URL"):
        pytest.skip("BITRIX_WEBHOOK_URL is not configured")

    settings = Settings(
        telegram_bot_token="x",
        use_llm=False,
        bitrix_webhook_url=os.getenv("BITRIX_WEBHOOK_URL"),
    )
    client = BitrixTicketService(settings=settings, client=BitrixApiClient(settings))
    report = Report(
        id=99001,
        user_id=1,
        jk="Pride Park",
        address="дом 5, подъезд 3, кв 78",
        apt="78",
        phone="+79990009900",
        category="elevator",
        text="Smoke test: лифт не работает",
        scope_key="pride park::elevator",
    )
    user = User(id=1, telegram_id=99001, name="Bitrix Live Smoke")

    bitrix_id = await client.create_ticket(report=report, user=user)
    assert isinstance(bitrix_id, str)
    assert bitrix_id.strip()

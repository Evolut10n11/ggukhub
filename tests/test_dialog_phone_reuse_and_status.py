from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.core.classifier import CategoryClassifier
from app.core.models import Base, Report
from app.core.schemas import ReportCreate
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


class _BitrixStub:
    enabled = False


class _BitrixWebhookStub:
    pass


class _NotifierStub:
    async def send_message(self, telegram_id: int, text: str) -> None:
        _ = telegram_id, text
        return None


class _MessageStub:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id, full_name=f"User {user_id}", username=None)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        _ = reply_markup
        self.answers.append(text)


async def _build_services(db_path: Path) -> tuple[AppServices, object]:
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
    )
    classifier = CategoryClassifier.from_file(Path("data/categories.json"))
    storage = Storage(session_factory)
    incidents = IncidentService(storage=storage, detector=SpikeDetector(window_minutes=15, threshold=999))

    services = AppServices(
        settings=settings,
        storage=storage,
        classifier=classifier,
        llm_category=SimpleNamespace(resolve=_never_resolve),
        incidents=incidents,
        responder=RuleResponder(),
        speech=_SpeechStub(),
        bitrix_client=_BitrixStub(),
        bitrix_service=_BitrixStub(),
        bitrix_webhook=_BitrixWebhookStub(),
        notifier=_NotifierStub(),
        housing_complexes=list(load_json(Path("data/housing_complexes.json"))),
        tariffs=TariffDirectory(Path("data/tariffs.json")),
    )
    return services, engine


async def _never_resolve(problem_text: str) -> None:
    _ = problem_text
    return None


async def _send_user_text(services: AppServices, user_id: int, text: str) -> list[str]:
    message = _MessageStub(user_id=user_id)
    await _process_text_dialog(message, services, text, from_voice=False)
    return message.answers


async def _latest_report_for_telegram_user(services: AppServices, telegram_id: int) -> Report | None:
    user = await services.storage.get_user_by_telegram_id(telegram_id)
    if user is None:
        return None

    async with services.storage._session_factory() as session:
        stmt = select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc(), Report.id.desc())
        result = await session.execute(stmt)
        return result.scalars().first()


async def _get_report_by_id(services: AppServices, report_id: int) -> Report:
    async with services.storage._session_factory() as session:
        stmt = select(Report).where(Report.id == report_id)
        result = await session.execute(stmt)
        return result.scalar_one()


async def _set_report_status(services: AppServices, report_id: int, status: str) -> None:
    async with services.storage._session_factory() as session:
        stmt = select(Report).where(Report.id == report_id)
        report = (await session.execute(stmt)).scalar_one()
        report.status = status
        await session.commit()


async def _create_report_for_user(
    services: AppServices,
    *,
    telegram_id: int,
    address: str,
    status: str = "new",
    category: str = "elevator",
    text: str = "Лифт не работает",
) -> Report:
    user = await services.storage.upsert_user(telegram_id=telegram_id, name=f"User {telegram_id}")
    report = await services.storage.create_report(
        ReportCreate(
            user_id=user.id,
            jk="Pride Park",
            address=address,
            apt="1",
            phone="+79990001122",
            category=category,
            text=text,
            scope_key=f"pride park::{category}",
        )
    )
    if status != "new":
        await _set_report_status(services, report.id, status)
        return await _get_report_by_id(services, report.id)
    return report


@pytest.mark.asyncio
async def test_saved_phone_is_confirmed_after_problem_text(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "phone_reuse_confirm.db")
    try:
        user = await services.storage.upsert_user(telegram_id=410_001, name="User 410001")
        await services.storage.update_user_phone(user.id, "+79990001122")

        assert await _send_user_text(services, 410_001, "привет")
        await _send_user_text(services, 410_001, "ЖК Pride Park")
        await _send_user_text(services, 410_001, "5")
        await _send_user_text(services, 410_001, "3")
        apartment_replies = await _send_user_text(services, 410_001, "78")
        assert any("Опишите" in text for text in apartment_replies)
        assert not any("телефон" in text.lower() for text in apartment_replies)

        problem_replies = await _send_user_text(services, 410_001, "Лифт не работает")
        assert any("+79990001122" in text for text in problem_replies)
        assert any("Использовать" in text for text in problem_replies)

        review_replies = await _send_user_text(services, 410_001, "да")
        assert any("Проверьте, пожалуйста, заявку перед отправкой" in text for text in review_replies)
        assert any("Телефон: +79990001122" in text for text in review_replies)

        await _send_user_text(services, 410_001, "да")
        report = await _latest_report_for_telegram_user(services, 410_001)
        assert report is not None
        assert report.phone == "+79990001122"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_saved_phone_reject_allows_entering_new_phone(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "phone_reuse_replace.db")
    try:
        user = await services.storage.upsert_user(telegram_id=410_002, name="User 410002")
        await services.storage.update_user_phone(user.id, "+79990001122")

        for text in ("привет", "ЖК Pride Park", "5", "3", "78", "Лифт не работает"):
            await _send_user_text(services, 410_002, text)

        phone_prompt_replies = await _send_user_text(services, 410_002, "нет")
        assert any("телефон" in text.lower() for text in phone_prompt_replies)

        review_replies = await _send_user_text(services, 410_002, "+79990002233")
        assert any("Телефон: +79990002233" in text for text in review_replies)

        await _send_user_text(services, 410_002, "да")
        report = await _latest_report_for_telegram_user(services, 410_002)
        user_after = await services.storage.get_user_by_telegram_id(410_002)
        assert report is not None
        assert user_after is not None
        assert report.phone == "+79990002233"
        assert user_after.phone == "+79990002233"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_saved_phone_step_accepts_freeform_new_phone(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "phone_reuse_freeform.db")
    try:
        user = await services.storage.upsert_user(telegram_id=410_003, name="User 410003")
        await services.storage.update_user_phone(user.id, "+79990001122")

        for text in ("привет", "ЖК Pride Park", "5", "3", "78", "Лифт не работает"):
            await _send_user_text(services, 410_003, text)

        review_replies = await _send_user_text(services, 410_003, "+79990003344")
        assert any("Телефон: +79990003344" in text for text in review_replies)

        await _send_user_text(services, 410_003, "да")
        report = await _latest_report_for_telegram_user(services, 410_003)
        user_after = await services.storage.get_user_by_telegram_id(410_003)
        assert report is not None
        assert user_after is not None
        assert report.phone == "+79990003344"
        assert user_after.phone == "+79990003344"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_correction_keyword_category_opens_category_selection(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "correction_category_keyword.db")
    try:
        flow = (
            "привет",
            "ЖК Pride Park",
            "1",
            "1",
            "1",
            "+79990001122",
            "Лифт не работает",
            "нет",
        )
        for text in flow:
            await _send_user_text(services, 410_007, text)

        category_prompt = await _send_user_text(services, 410_007, "Категорию")
        assert any("Выберите категорию" in text for text in category_prompt)
        assert not any("Проблема: Категорию" in text for text in category_prompt)

        review_replies = await _send_user_text(services, 410_007, "Нет воды")
        combined = "\n".join(review_replies)
        assert "Тип: Нет воды" in combined
        assert "Проблема: Лифт не работает" in combined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_other_category_review_shows_available_category_options(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "other_category_options.db")
    try:
        user = await services.storage.upsert_user(telegram_id=410_071, name="User 410071")
        await services.storage.update_user_phone(user.id, "+79990001122")

        for text in ("привет", "ЖК Pride Park", "1", "1", "1", "Шумно в подъезде"):
            await _send_user_text(services, 410_071, text)

        review_replies = await _send_user_text(services, 410_071, "да")
        combined = "\n".join(review_replies)
        assert "Тип: Другое" in combined
        assert "Доступные типы заявок:" in combined
        assert "Нет воды" in combined
        assert "Уборка" in combined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_correction_prompt_lists_available_categories(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "correction_prompt_category_options.db")
    try:
        flow = (
            "привет",
            "ЖК Pride Park",
            "1",
            "1",
            "1",
            "+79990001122",
            "Шумно в подъезде",
        )
        for text in flow:
            await _send_user_text(services, 410_072, text)

        replies = await _send_user_text(services, 410_072, "нет")
        combined = "\n".join(replies)
        assert "Доступные типы заявок:" in combined
        assert "Лифт" in combined
        assert "Домофон" in combined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_problem_text_is_rejected_from_idle(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "problem_idle_validation.db")
    try:
        replies = await _send_user_text(services, 410_008, "1")
        assert any("Нужно коротко и по делу" in text for text in replies)

        user = await services.storage.get_user_by_telegram_id(410_008)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "idle"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_problem_text_is_rejected_on_problem_step(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "problem_step_validation.db")
    try:
        for text in ("привет", "ЖК Pride Park", "1", "1", "1", "+79990001122"):
            await _send_user_text(services, 410_009, text)

        replies = await _send_user_text(services, 410_009, "1")
        assert any("Нужно коротко и по делу" in text for text in replies)

        user = await services.storage.get_user_by_telegram_id(410_009)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_problem"

        review_replies = await _send_user_text(services, 410_009, "Лифт не работает")
        assert any("Проверьте, пожалуйста, заявку перед отправкой" in text for text in review_replies)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_abusive_problem_text_is_rejected_on_problem_step(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "problem_abuse_validation.db")
    try:
        for text in ("привет", "ЖК Pride Park", "1", "1", "1", "+79990001122"):
            await _send_user_text(services, 410_010, text)

        replies = await _send_user_text(services, 410_010, "Сука, опять лифт не работает")
        assert any("без оскорблений" in text for text in replies)

        user = await services.storage.get_user_by_telegram_id(410_010)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_problem"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_offtopic_problem_text_is_rejected_from_idle(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "problem_offtopic_idle.db")
    try:
        replies = await _send_user_text(services, 410_011, "Включите музыку крутую")
        assert any("только с заявками по дому" in text for text in replies)

        user = await services.storage.get_user_by_telegram_id(410_011)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "idle"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_offtopic_problem_text_is_rejected_on_problem_step(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "problem_offtopic_step.db")
    try:
        for text in ("привет", "ЖК Pride Park", "1", "1", "1", "+79990001122"):
            await _send_user_text(services, 410_012, text)

        replies = await _send_user_text(services, 410_012, "Включите музыку крутую")
        assert any("только с заявками по дому" in text for text in replies)

        user = await services.storage.get_user_by_telegram_id(410_012)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_problem"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_smell_in_corridor_is_classified_as_cleaning_in_review(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "smell_corridor_cleaning.db")
    try:
        user = await services.storage.upsert_user(telegram_id=410_013, name="User 410013")
        await services.storage.update_user_phone(user.id, "+79990001122")

        for text in ("привет", "ЖК Grand Comfort", "1", "1", "1", "Пахнет в коридоре"):
            _ = await _send_user_text(services, 410_013, text)

        replies = await _send_user_text(services, 410_013, "да")

        combined = "\n".join(replies)
        assert "Тип: Уборка" in combined
        assert "Проблема: Пахнет в коридоре" in combined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_status_request_uses_latest_active_report_and_keeps_draft(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "status_active_lookup.db")
    try:
        active_report = await _create_report_for_user(
            services,
            telegram_id=410_004,
            address="дом 5, подъезд 1, кв 10",
            status="new",
        )
        closed_report = await _create_report_for_user(
            services,
            telegram_id=410_004,
            address="дом 9, подъезд 2, кв 1",
            status="resolved",
        )

        for text in ("привет", "ЖК Pride Park", "5"):
            await _send_user_text(services, 410_004, text)

        user = await services.storage.get_user_by_telegram_id(410_004)
        assert user is not None
        snapshot_before = await services.storage.get_session(user.id)

        replies = await _send_user_text(services, 410_004, "Что с моей заявкой?")
        combined = "\n".join(replies)
        assert f"Номер: {active_report.id}" in combined
        assert f"Номер: {closed_report.id}" not in combined
        assert "Черновик новой заявки сохранила" in combined

        snapshot_after = await services.storage.get_session(user.id)
        assert snapshot_after.step == snapshot_before.step
        assert snapshot_after.data == snapshot_before.data

        async with services.storage._session_factory() as session:
            result = await session.execute(select(Report).where(Report.user_id == user.id))
            assert len(result.scalars().all()) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_status_request_falls_back_to_latest_report_when_no_active(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "status_latest_lookup.db")
    try:
        first_report = await _create_report_for_user(
            services,
            telegram_id=410_005,
            address="дом 1, подъезд 1, кв 1",
            status="resolved",
        )
        latest_report = await _create_report_for_user(
            services,
            telegram_id=410_005,
            address="дом 2, подъезд 1, кв 2",
            status="done",
        )

        replies = await _send_user_text(services, 410_005, "Статус заявки")
        combined = "\n".join(replies)
        assert f"Номер: {latest_report.id}" in combined
        assert f"Номер: {first_report.id}" not in combined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_status_request_handles_absent_reports(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "status_no_reports.db")
    try:
        replies = await _send_user_text(services, 410_006, "Что с моей заявкой?")
        assert any("не нашла" in text.lower() for text in replies)
    finally:
        await engine.dispose()

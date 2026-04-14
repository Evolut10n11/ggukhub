from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.core.models import Base, User
from app.core.schemas import ReportCreate
from app.core.storage import Storage
from app.max.operator import MaxOperatorService


class _NotifierStub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, int, int | None, str]] = []

    async def send_user_message(self, user: User, text: str) -> bool:
        self.messages.append((user.platform, user.platform_user_id, user.messenger_chat_id, text))
        return True


class _MaxClientStub:
    def __init__(self) -> None:
        self.direct_messages: list[tuple[int, str, object | None]] = []
        self.chat_messages: list[tuple[int, str]] = []

    async def send_direct_message(self, user_id: int, text: str, *, attachments=None, format: str = "markdown") -> dict[str, object]:
        _ = format
        self.direct_messages.append((user_id, text, attachments))
        return {"success": True}

    async def send_message(self, chat_id: int | None, text: str, *, user_id: int | None = None, attachments=None, format: str = "markdown") -> dict[str, object]:
        _ = user_id, attachments, format
        self.chat_messages.append((int(chat_id or 0), text))
        return {"success": True}


@pytest.mark.asyncio
async def test_max_operator_service_notifies_operator_about_new_report(tmp_path: Path) -> None:
    db_path = tmp_path / "max_operator_notify.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = Storage(session_factory)
    notifier = _NotifierStub()
    service = MaxOperatorService(
        Settings(
            telegram_bot_token="123456:TEST",
            max_bot_token="max-token",
            max_operator_phones="+79955406640,+79955406641",
        ),
        storage,
        notifier,
    )
    service._client = _MaxClientStub()  # type: ignore[assignment]

    try:
        operator_one = await storage.upsert_platform_user(
            platform="max",
            platform_user_id=9001,
            platform_chat_id=91001,
            name="Operator One",
        )
        operator_two = await storage.upsert_platform_user(
            platform="max",
            platform_user_id=9002,
            platform_chat_id=91002,
            name="Operator Two",
        )
        await storage.update_user_phone(operator_one.id, "+79955406640")
        await storage.update_user_phone(operator_two.id, "89955406641")

        user = await storage.upsert_platform_user(
            platform="max",
            platform_user_id=7001,
            platform_chat_id=8800555,
            name="MAX Resident",
        )
        report = await storage.create_report(
            ReportCreate(
                user_id=user.id,
                jk="Прайд Парк",
                address="дом 5, подъезд 2, кв 17",
                apt="17",
                phone="+79990001122",
                category="accident",
                text="Лифт не работает",
                scope_key="pride-park::accident",
            )
        )

        await service.notify_new_report(report, user)

        assert len(service._client.direct_messages) == 2  # type: ignore[attr-defined]
        first = service._client.direct_messages[0]  # type: ignore[attr-defined]
        assert first[0] == 9001
        assert "Новая заявка №1" in first[1]
        assert "Лифт не работает" in first[1]
        assert first[2] is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_max_operator_service_replies_and_closes_report(tmp_path: Path) -> None:
    db_path = tmp_path / "max_operator_reply.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = Storage(session_factory)
    notifier = _NotifierStub()
    service = MaxOperatorService(
        Settings(
            telegram_bot_token="123456:TEST",
            max_bot_token="max-token",
            max_operator_phones="+79955406640",
        ),
        storage,
        notifier,
    )
    service._client = _MaxClientStub()  # type: ignore[assignment]

    try:
        operator = await storage.upsert_platform_user(
            platform="max",
            platform_user_id=9001,
            platform_chat_id=99001,
            name="Operator",
        )
        await storage.update_user_phone(operator.id, "+79955406640")

        user = await storage.upsert_platform_user(
            platform="max",
            platform_user_id=7001,
            platform_chat_id=8800555,
            name="MAX Resident",
        )
        report = await storage.create_report(
            ReportCreate(
                user_id=user.id,
                jk="Прайд Парк",
                address="дом 5, подъезд 2, кв 17",
                apt="17",
                phone="+79990001122",
                category="accident",
                text="Лифт не работает",
                scope_key="pride-park::accident",
            )
        )

        handled_reply = await service.handle_operator_message(50001, 9001, "/reply 1 Мастер уже едет")
        handled_close = await service.handle_operator_message(50001, 9001, "/close 1 Проблема решена")

        report_payload = await storage.get_report_with_user(report.id)
        assert report_payload is not None
        updated_report, _ = report_payload

        assert handled_reply is True
        assert handled_close is True
        assert updated_report.status == "closed"
        assert notifier.messages == [
            ("max", 7001, 8800555, "Ответ по заявке №1:\nМастер уже едет"),
            ("max", 7001, 8800555, "Заявка №1 закрыта.\nПроблема решена"),
        ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_max_operator_service_activates_operator_by_phone_message(tmp_path: Path) -> None:
    db_path = tmp_path / "max_operator_activate.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    storage = Storage(session_factory)
    notifier = _NotifierStub()
    service = MaxOperatorService(
        Settings(
            telegram_bot_token="123456:TEST",
            max_bot_token="max-token",
            max_operator_phones="+79955406640",
        ),
        storage,
        notifier,
    )
    service._client = _MaxClientStub()  # type: ignore[assignment]

    try:
        activated = await service.handle_operator_message(99001, 9001, "+7 (995) 540-66-40")
        user = await storage.get_user_by_platform_id(platform="max", platform_user_id=9001)

        assert activated is True
        assert user is not None
        assert user.phone == "+79955406640"
        assert await service.is_operator(9001) is True
        assert service._client.chat_messages[0] == (99001, "Режим оператора активирован по номеру телефона. Теперь доступны /queue, /take, /reply и /close.")  # type: ignore[attr-defined]
    finally:
        await engine.dispose()

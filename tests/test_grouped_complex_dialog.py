from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.core.buildings import BuildingRegistry, ComplexInfo, HouseInfo
from app.core.classifier import CategoryClassifier
from app.core.models import Base
from app.core.schemas import SessionPayload
from app.core.services import AppServices
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.responders.rule_responder import RuleResponder
from app.telegram.dialog.models import DialogSessionData, DialogTransport
from app.telegram.dialog.service import DialogService


async def _build_services(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    storage = Storage(async_sessionmaker(engine, expire_on_commit=False))
    disabled = SimpleNamespace(enabled=False)
    services = AppServices(
        settings=Settings(telegram_bot_token="test-token"),
        storage=storage,
        classifier=CategoryClassifier.from_file(Path("data/categories.json")),
        incidents=IncidentService(storage=storage, detector=SpikeDetector(window_minutes=15, threshold=999)),
        responder=RuleResponder(),
        speech=disabled,
        bitrix_client=disabled,
        bitrix_service=disabled,
        bitrix_webhook=disabled,
        notifier=disabled,
        building_registry=BuildingRegistry.from_file(Path("data/housing_complexes.json")),
        tariffs=TariffDirectory(Path("data/tariffs.json")),
    )
    return services, engine


def _make_transport(user_id: int) -> tuple[DialogTransport, list[str]]:
    sent: list[str] = []

    async def send_text(text: str, reply_markup: object | None) -> None:
        sent.append(text)

    async def clear_inline_keyboard() -> None:
        pass

    return DialogTransport(
        platform_user_id=user_id,
        display_name="Resident",
        send_text=send_text,
        clear_inline_keyboard=clear_inline_keyboard,
    ), sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("complex_name", "index", "address"),
    [
        ("Еврокласс", 3, "Быстрецкая, д.18, к.4"),
        ("Гранд Комфорт", 0, "Гранд Комфорт - 1"),
        ("Гранд Комфорт", 1, "Гранд Комфорт - 2"),
        ("Гранд Комфорт", 2, "Гранд Комфорт - 3"),
    ],
)
@pytest.mark.parametrize("selection", ["button", "text"])
async def test_grouped_house_with_unknown_counts_accepts_manual_details(
    tmp_path: Path, complex_name: str, index: int, address: str, selection: str,
) -> None:
    services, engine = await _build_services(tmp_path / "grouped_house.db")
    try:
        dialog = DialogService(services)
        transport, _ = _make_transport(600_001)
        await dialog.start(transport, include_welcome=False)
        await dialog.select_housing_complex(transport, complex_name)
        if selection == "button":
            await dialog.select_house(transport, index)
        else:
            await dialog.process_text(transport, address)
        user = await services.storage.get_user_by_platform_id(platform="telegram", platform_user_id=600_001)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_entrance"
        assert snapshot.data["jk"] == complex_name
        assert snapshot.data["house"] == address
        assert not snapshot.data.get("entrance")

        await dialog.process_text(transport, "7")
        await dialog.process_text(transport, "99999")
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_phone"
        assert snapshot.data["entrance"] == "7"
        assert snapshot.data["apartment"] == "99999"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_counts_also_work_for_single_house_and_entrance_callback(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "single_house.db")
    try:
        services.building_registry = BuildingRegistry(
            complexes=[ComplexInfo(name="Новый ЖК", houses=[HouseInfo("Новый дом", None, None)])],
        )
        dialog = DialogService(services)
        transport, _ = _make_transport(600_002)
        await dialog.start(transport, include_welcome=False)
        await dialog.select_housing_complex(transport, "Новый ЖК")
        await dialog.select_entrance(transport, "4")
        await dialog.process_text(transport, "123")
        user = await services.storage.get_user_by_platform_id(platform="telegram", platform_user_id=600_002)
        assert user is not None
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_phone"
        assert snapshot.data["house"] == "Новый дом"
        assert snapshot.data["entrance"] == "4"
        assert snapshot.data["apartment"] == "123"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_house_keeps_known_entrance_and_apartment_limits(tmp_path: Path) -> None:
    services, engine = await _build_services(tmp_path / "known_limits.db")
    try:
        dialog = DialogService(services)
        transport, _ = _make_transport(600_003)
        await dialog.start(transport, include_welcome=False)
        await dialog.select_housing_complex(transport, "Еврокласс")
        await dialog.select_house(transport, 0)
        user = await services.storage.get_user_by_platform_id(platform="telegram", platform_user_id=600_003)
        assert user is not None
        await dialog.process_text(transport, "3")
        assert (await services.storage.get_session(user.id)).step == "awaiting_entrance"
        await dialog.process_text(transport, "2")
        await dialog.process_text(transport, "451")
        assert (await services.storage.get_session(user.id)).step == "awaiting_apartment"
        await dialog.process_text(transport, "450")
        assert (await services.storage.get_session(user.id)).step == "awaiting_phone"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("legacy_jk", "legacy_house", "group", "canonical_house"),
    [
        ("Еврокласс-4", "18", "Еврокласс", "Быстрецкая, д.18, к.4"),
        ("Гранд Комфорт-2", "2", "Гранд Комфорт", "Гранд Комфорт - 2"),
        ("Гранд Комфорт-3", "3", "Гранд Комфорт", "Гранд Комфорт - 3"),
        ("Гранд Комфорт-2", "улица Примерная, д.7", "Гранд Комфорт", "улица Примерная, д.7"),
    ],
)
async def test_legacy_saved_address_reuses_group_and_preserves_specific_address(
    tmp_path: Path, legacy_jk: str, legacy_house: str, group: str, canonical_house: str,
) -> None:
    services, engine = await _build_services(tmp_path / "legacy_address.db")
    try:
        user = await services.storage.upsert_user(telegram_id=600_004, name="Resident")
        await services.storage.update_user_address(
            user.id, jk=legacy_jk, house=legacy_house, entrance="2", apartment="45",
        )
        dialog = DialogService(services)
        transport, sent = _make_transport(600_004)
        await dialog.start(transport, include_welcome=False)
        snapshot = await services.storage.get_session(user.id)
        assert snapshot.step == "awaiting_address_reuse_confirm"
        assert snapshot.data["jk"] == group
        assert snapshot.data["house"] == canonical_house
        assert f"ЖК: {group}\n" in sent[-1]
        assert f"Дом: {canonical_house}" in sent[-1]

        await services.storage.save_session(
            user_id=user.id,
            payload=SessionPayload(step="awaiting_house", data={"jk": legacy_jk}),
        )
        houses = await dialog.get_house_list_for_user("telegram", 600_004)
        assert houses == services.building_registry.houses_for_complex(group)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("complex_name", "raw_house", "expected_house"),
    [
        ("Еврокласс", "18", "18"),
        ("Еврокласс", "1", "1"),
        ("Еврокласс", "Быстрецкая, д.18, к.4", "Быстрецкая, д.18, к.4"),
        ("Гранд Комфорт", "2", "Гранд Комфорт - 2"),
        ("Гранд Комфорт", "20", "20"),
    ],
)
async def test_voice_house_number_resolves_only_a_unique_exact_match(
    tmp_path: Path, complex_name: str, raw_house: str, expected_house: str,
) -> None:
    services, engine = await _build_services(tmp_path / "voice_house.db")
    try:
        dialog = DialogService(services)
        data = DialogSessionData(jk=complex_name, house=raw_house)
        dialog._resolve_voice_house(data)
        assert data.house == expected_house
    finally:
        await engine.dispose()

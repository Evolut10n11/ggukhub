from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.core.classifier import CategoryClassifier
from app.core.models import Base
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
        return None


class _MessageStub:
    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(id=user_id, full_name=f"User {user_id}", username=None)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup: object | None = None) -> None:
        self.answers.append(text)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[idx]


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
        incident_threshold=999,
    )
    classifier = CategoryClassifier.from_file(Path("data/categories.json"))
    storage = Storage(session_factory)
    incidents = IncidentService(storage=storage, detector=SpikeDetector(window_minutes=15, threshold=999))

    services = AppServices(
        settings=settings,
        storage=storage,
        classifier=classifier,
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


async def _run_single_user_flow(services: AppServices, user_id: int) -> tuple[list[float], list[str]]:
    flow = [
        "привет",
        "ЖК Pride Park",
        "5",
        "3",
        "78",
        f"+7999000{user_id % 10000:04d}",
        "лифт не работает",
        "да",
    ]

    latencies: list[float] = []
    replies: list[str] = []
    for text in flow:
        message = _MessageStub(user_id=user_id)
        start = time.perf_counter()
        await _process_text_dialog(message, services, text, from_voice=False)
        latencies.append(time.perf_counter() - start)
        replies.extend(message.answers)
    return latencies, replies


@pytest.mark.asyncio
async def test_concurrent_20_users_flow_latency(tmp_path: Path) -> None:
    db_path = tmp_path / "load_20_users.db"
    services, engine = await _build_services(db_path)
    try:
        start = time.perf_counter()
        results = await asyncio.gather(*[_run_single_user_flow(services, user_id=50_000 + i) for i in range(20)])
        total_elapsed = time.perf_counter() - start
    finally:
        await engine.dispose()

    all_latencies = [item for latencies, _ in results for item in latencies]
    avg_latency = sum(all_latencies) / len(all_latencies)
    p95_latency = _p95(all_latencies)
    max_latency = max(all_latencies)

    # Every user should get final confirmation with report summary.
    for _, replies in results:
        assert any("Сводка по заявке:" in text for text in replies)

    print(
        "\n20-user load stats:",
        f"total={total_elapsed:.3f}s",
        f"avg_step={avg_latency:.3f}s",
        f"p95_step={p95_latency:.3f}s",
        f"max_step={max_latency:.3f}s",
    )

    # Conservative thresholds for local dev machine to catch major regressions.
    assert total_elapsed < 8.0
    assert p95_latency < 1.2

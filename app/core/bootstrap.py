from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bitrix.client import BitrixApiClient
from app.bitrix.service import BitrixTicketService, BitrixWebhookService
from app.config import Settings, get_settings
from app.core.classifier import CategoryClassifier
from app.core.db import DatabaseRuntime, create_database_runtime
from app.core.services import AppServices
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.core.utils import load_json
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.responders.rule_responder import RuleResponder
from app.speech.client import SpeechToTextClient
from app.telegram.notifier import TelegramNotifier


def build_services(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession],
) -> AppServices:
    cfg = settings or get_settings()
    classifier = CategoryClassifier.from_file(cfg.categories_path)
    housing_complexes = load_json(cfg.complexes_path)
    tariffs = TariffDirectory(cfg.tariffs_path)

    storage = Storage(session_factory)
    detector = SpikeDetector(window_minutes=cfg.incident_window_minutes, threshold=cfg.incident_threshold)
    incidents = IncidentService(storage=storage, detector=detector)
    responder = RuleResponder()
    speech = SpeechToTextClient(cfg)
    notifier = TelegramNotifier(cfg.telegram_bot_token)
    bitrix_client = BitrixApiClient(cfg)
    bitrix_service = BitrixTicketService(settings=cfg, client=bitrix_client)
    bitrix_webhook = BitrixWebhookService(settings=cfg, storage=storage, notifier=notifier)

    return AppServices(
        settings=cfg,
        storage=storage,
        classifier=classifier,
        incidents=incidents,
        responder=responder,
        speech=speech,
        bitrix_client=bitrix_client,
        bitrix_service=bitrix_service,
        bitrix_webhook=bitrix_webhook,
        notifier=notifier,
        housing_complexes=list(housing_complexes),
        tariffs=tariffs,
    )


def build_runtime(settings: Settings | None = None) -> tuple[DatabaseRuntime, AppServices]:
    cfg = settings or get_settings()
    db = create_database_runtime(cfg)
    services = build_services(settings=cfg, session_factory=db.session_factory)
    return db, services

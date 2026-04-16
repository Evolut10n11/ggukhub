from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bitrix.client import BitrixApiClient
from app.bitrix.connector import BitrixConnectorService
from app.bitrix.service import BitrixTicketService, BitrixWebhookService
from app.config import Settings, get_settings
from app.core.classifier import CategoryClassifier
from app.core.db import DatabaseRuntime, create_database_runtime
from app.core.notifier import UserNotifier
from app.core.services import AppServices
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.core.buildings import BuildingRegistry
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.max.operator import MaxOperatorService
from app.responders.rule_responder import RuleResponder
from app.speech.client import SpeechToTextClient


def build_services(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession],
) -> AppServices:
    cfg = settings or get_settings()
    classifier = CategoryClassifier.from_file(cfg.categories_path)
    building_registry = BuildingRegistry.from_file(cfg.complexes_path)
    tariffs = TariffDirectory(cfg.tariffs_path)

    storage = Storage(session_factory)
    detector = SpikeDetector(window_minutes=cfg.incident_window_minutes, threshold=cfg.incident_threshold)
    incidents = IncidentService(storage=storage, detector=detector)
    responder = RuleResponder()
    speech = SpeechToTextClient(cfg)
    notifier = UserNotifier(cfg)
    max_operator_service = MaxOperatorService(cfg, storage, notifier)
    bitrix_client = BitrixApiClient(cfg)
    bitrix_service = BitrixTicketService(settings=cfg, client=bitrix_client)
    bitrix_webhook = BitrixWebhookService(settings=cfg, storage=storage, notifier=notifier)
    bitrix_connector = BitrixConnectorService(settings=cfg, client=bitrix_client, storage=storage)

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
        building_registry=building_registry,
        tariffs=tariffs,
        max_operator_service=max_operator_service,
        bitrix_connector=bitrix_connector,
    )


def build_runtime(settings: Settings | None = None) -> tuple[DatabaseRuntime, AppServices]:
    cfg = settings or get_settings()
    db = create_database_runtime(cfg)
    services = build_services(settings=cfg, session_factory=db.session_factory)
    return db, services

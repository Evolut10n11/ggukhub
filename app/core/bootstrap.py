from __future__ import annotations

from app.bitrix.client import BitrixClient
from app.bitrix.service import BitrixWebhookService
from app.config import Settings, get_settings
from app.core.classifier import CategoryClassifier
from app.core.db import AsyncSessionFactory
from app.core.llm_category import LLMCategoryResolver
from app.core.services import AppServices
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.core.utils import load_json
from app.incidents.detector import SpikeDetector
from app.incidents.service import IncidentService
from app.responders.factory import create_responder
from app.speech.client import SpeechToTextClient
from app.telegram.notifier import TelegramNotifier


def build_services(settings: Settings | None = None) -> AppServices:
    cfg = settings or get_settings()
    classifier = CategoryClassifier.from_file(cfg.categories_path)
    llm_category = LLMCategoryResolver(cfg, classifier)
    housing_complexes = load_json(cfg.complexes_path)
    tariffs = TariffDirectory(cfg.tariffs_path)

    storage = Storage(AsyncSessionFactory)
    detector = SpikeDetector(window_minutes=cfg.incident_window_minutes, threshold=cfg.incident_threshold)
    incidents = IncidentService(storage=storage, detector=detector)
    responder = create_responder(cfg)
    speech = SpeechToTextClient(cfg)
    notifier = TelegramNotifier(cfg.telegram_bot_token)
    bitrix_client = BitrixClient(cfg)
    bitrix_webhook = BitrixWebhookService(settings=cfg, storage=storage, notifier=notifier)

    return AppServices(
        settings=cfg,
        storage=storage,
        classifier=classifier,
        llm_category=llm_category,
        incidents=incidents,
        responder=responder,
        speech=speech,
        bitrix_client=bitrix_client,
        bitrix_webhook=bitrix_webhook,
        notifier=notifier,
        housing_complexes=list(housing_complexes),
        tariffs=tariffs,
    )

from __future__ import annotations

from dataclasses import dataclass

from app.bitrix.client import BitrixClient
from app.bitrix.service import BitrixWebhookService
from app.config import Settings
from app.core.classifier import CategoryClassifier
from app.core.llm_category import LLMCategoryResolver
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.incidents.service import IncidentService
from app.responders.base import BaseResponder
from app.speech.client import SpeechToTextClient
from app.telegram.notifier import TelegramNotifier


@dataclass(slots=True)
class AppServices:
    settings: Settings
    storage: Storage
    classifier: CategoryClassifier
    llm_category: LLMCategoryResolver
    incidents: IncidentService
    responder: BaseResponder
    speech: SpeechToTextClient
    bitrix_client: BitrixClient
    bitrix_webhook: BitrixWebhookService
    notifier: TelegramNotifier
    housing_complexes: list[str]
    tariffs: TariffDirectory

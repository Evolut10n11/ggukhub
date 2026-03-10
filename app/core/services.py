from __future__ import annotations

from dataclasses import dataclass, field

from app.bitrix.client import BitrixApiClient
from app.bitrix.service import BitrixTicketService, BitrixWebhookService
from app.config import Settings
from app.core.category_resolution import CategoryResolver
from app.core.classifier import CategoryClassifier
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.incidents.service import IncidentService
from app.responders.base import BaseResponder
from app.speech.client import SpeechToTextClient
from app.telegram.dialog.runtime import DialogRuntimeState
from app.telegram.notifier import TelegramNotifier


@dataclass(slots=True)
class ClassificationDeps:
    classifier: CategoryClassifier
    llm_category: CategoryResolver


@dataclass(slots=True)
class ResponderDeps:
    responder: BaseResponder
    notifier: TelegramNotifier


@dataclass(slots=True)
class BitrixDeps:
    client: BitrixApiClient
    service: BitrixTicketService
    webhook: BitrixWebhookService


@dataclass(slots=True)
class DialogDeps:
    storage: Storage
    classifier: CategoryClassifier
    llm_category: CategoryResolver
    incidents: IncidentService
    responder: BaseResponder
    bitrix_service: BitrixTicketService
    notifier: TelegramNotifier
    speech: SpeechToTextClient
    housing_complexes: list[str]
    dialog_runtime: DialogRuntimeState


@dataclass(slots=True)
class AppServices:
    settings: Settings
    storage: Storage
    classifier: CategoryClassifier
    llm_category: CategoryResolver
    incidents: IncidentService
    responder: BaseResponder
    speech: SpeechToTextClient
    bitrix_client: BitrixApiClient
    bitrix_service: BitrixTicketService
    bitrix_webhook: BitrixWebhookService
    notifier: TelegramNotifier
    housing_complexes: list[str]
    tariffs: TariffDirectory
    dialog_runtime: DialogRuntimeState = field(default_factory=DialogRuntimeState)

    def classification_deps(self) -> ClassificationDeps:
        return ClassificationDeps(
            classifier=self.classifier,
            llm_category=self.llm_category,
        )

    def responder_deps(self) -> ResponderDeps:
        return ResponderDeps(
            responder=self.responder,
            notifier=self.notifier,
        )

    def bitrix_deps(self) -> BitrixDeps:
        return BitrixDeps(
            client=self.bitrix_client,
            service=self.bitrix_service,
            webhook=self.bitrix_webhook,
        )

    def dialog_deps(self) -> DialogDeps:
        return DialogDeps(
            storage=self.storage,
            classifier=self.classifier,
            llm_category=self.llm_category,
            incidents=self.incidents,
            responder=self.responder,
            bitrix_service=self.bitrix_service,
            notifier=self.notifier,
            speech=self.speech,
            housing_complexes=list(self.housing_complexes),
            dialog_runtime=self.dialog_runtime,
        )

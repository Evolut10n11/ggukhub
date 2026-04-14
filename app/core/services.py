from __future__ import annotations

from dataclasses import dataclass, field

from app.bitrix.client import BitrixApiClient
from app.bitrix.service import BitrixTicketService, BitrixWebhookService
from app.config import Settings
from app.core.buildings import BuildingRegistry
from app.core.classifier import CategoryClassifier
from app.core.notifier import UserNotifier
from app.core.storage import Storage
from app.core.tariffs import TariffDirectory
from app.incidents.service import IncidentService
from app.max.operator import MaxOperatorService
from app.responders.rule_responder import RuleResponder
from app.speech.client import SpeechToTextClient
from app.telegram.dialog.runtime import DialogRuntimeState


@dataclass(slots=True)
class BitrixDeps:
    client: BitrixApiClient
    service: BitrixTicketService
    webhook: BitrixWebhookService


@dataclass(slots=True)
class DialogDeps:
    storage: Storage
    classifier: CategoryClassifier
    incidents: IncidentService
    responder: RuleResponder
    bitrix_service: BitrixTicketService
    notifier: UserNotifier
    speech: SpeechToTextClient
    building_registry: BuildingRegistry
    dialog_runtime: DialogRuntimeState
    max_operator_service: MaxOperatorService | None = None


@dataclass(slots=True)
class AppServices:
    settings: Settings
    storage: Storage
    classifier: CategoryClassifier
    incidents: IncidentService
    responder: RuleResponder
    speech: SpeechToTextClient
    bitrix_client: BitrixApiClient
    bitrix_service: BitrixTicketService
    bitrix_webhook: BitrixWebhookService
    notifier: UserNotifier
    building_registry: BuildingRegistry
    tariffs: TariffDirectory
    max_operator_service: MaxOperatorService | None = None
    dialog_runtime: DialogRuntimeState = field(default_factory=DialogRuntimeState)

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
            incidents=self.incidents,
            responder=self.responder,
            bitrix_service=self.bitrix_service,
            notifier=self.notifier,
            speech=self.speech,
            building_registry=self.building_registry,
            dialog_runtime=self.dialog_runtime,
            max_operator_service=self.max_operator_service,
        )

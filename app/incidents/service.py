from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.models import Report
from app.core.storage import Storage
from app.incidents.detector import SpikeDetector

INCIDENT_PUBLIC_MESSAGE = (
    "Похоже, сейчас много обращений по этому вопросу. "
    "Я зафиксировала заявку и буду держать в курсе. "
    "Уточните, пожалуйста, ЖК и адрес (дом/подъезд/кв), чтобы проверить, затронуто ли вас."
)


@dataclass(slots=True)
class IncidentDecision:
    is_mass: bool
    is_new_incident: bool
    incident_id: int | None
    public_message: str | None


class IncidentService:
    def __init__(self, storage: Storage, detector: SpikeDetector):
        self._storage = storage
        self._detector = detector

    async def evaluate_report(self, report: Report) -> IncidentDecision:
        active = await self._storage.get_active_incident(report.scope_key)
        if active is not None:
            if report.address.strip():
                await self._storage.link_incident_report(active.id, report.id)
            return IncidentDecision(
                is_mass=True,
                is_new_incident=False,
                incident_id=active.id,
                public_message=active.public_message,
            )

        now = datetime.now(timezone.utc)
        since = now - self._detector.window
        timestamps = await self._storage.get_recent_report_timestamps(report.scope_key, since=since)
        if not self._detector.is_spike(timestamps=timestamps, now=now):
            return IncidentDecision(is_mass=False, is_new_incident=False, incident_id=None, public_message=None)

        incident = await self._storage.create_incident(
            scope_key=report.scope_key,
            category=report.category,
            public_message=INCIDENT_PUBLIC_MESSAGE,
        )
        if report.address.strip():
            await self._storage.link_incident_report(incident.id, report.id)

        return IncidentDecision(
            is_mass=True,
            is_new_incident=True,
            incident_id=incident.id,
            public_message=incident.public_message,
        )

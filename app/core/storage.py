from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

from app.core.enums import IncidentStatus, ReportStatus, is_active_report_status
from app.core.models import BitrixEvent, Incident, IncidentEvent, Report, ReportAuditLog, SessionState, User
from app.core.schemas import ReportAuditCreate, ReportCreate, ReportLookupResult, SessionPayload
from app.core.utils import dump_json


class Storage:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def health_check(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def upsert_user(self, telegram_id: int, name: str | None) -> User:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user is None:
                user = User(telegram_id=telegram_id, name=name)
                session.add(user)
            elif name and user.name != name:
                user.name = name
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_user_phone(self, user_id: int, phone: str) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user.phone = phone
                await session.commit()

    async def update_user_bitrix_contact_id(self, user_id: int, contact_id: str) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user.bitrix_contact_id = contact_id
                await session.commit()

    async def get_session(self, user_id: int) -> SessionPayload:
        async with self._session_factory() as session:
            stmt: Select[tuple[SessionState]] = select(SessionState).where(SessionState.user_id == user_id)
            result = await session.execute(stmt)
            session_state = result.scalar_one_or_none()
            if session_state is None:
                payload = SessionPayload()
                session_state = SessionState(user_id=user_id, state_json=payload.model_dump_json())
                session.add(session_state)
                await session.commit()
                return payload
            return SessionPayload.model_validate_json(session_state.state_json)

    async def save_session(self, user_id: int, payload: SessionPayload) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[SessionState]] = select(SessionState).where(SessionState.user_id == user_id)
            result = await session.execute(stmt)
            session_state = result.scalar_one_or_none()
            serialized = payload.model_dump_json()
            if session_state is None:
                session_state = SessionState(user_id=user_id, state_json=serialized)
                session.add(session_state)
            else:
                session_state.state_json = serialized
            await session.commit()

    async def count_active_reports_by_apt(self, address: str, apt: str) -> int:
        async with self._session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(Report)
                .where(Report.address == address, Report.apt == apt)
                .where(Report.status == ReportStatus.NEW.value)
            )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def count_active_reports_by_phone(self, phone: str) -> int:
        async with self._session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(Report)
                .where(Report.phone == phone)
                .where(Report.status == ReportStatus.NEW.value)
            )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def create_report(self, payload: ReportCreate) -> Report:
        async with self._session_factory() as session:
            report = Report(**payload.model_dump())
            session.add(report)
            await session.commit()
            await session.refresh(report)
            return report

    async def create_report_with_audit(
        self,
        report_payload: ReportCreate,
        audit_payload: ReportAuditCreate | None,
    ) -> Report:
        async with self._session_factory() as session:
            report = Report(**report_payload.model_dump())
            session.add(report)
            await session.flush()
            if audit_payload is not None:
                item = ReportAuditLog(
                    report_id=report.id,
                    stage=audit_payload.stage,
                    regulation_version=audit_payload.regulation_version,
                    payload_json=dump_json(audit_payload.payload),
                )
                session.add(item)
            await session.commit()
            await session.refresh(report)
            return report

    async def set_report_bitrix_id(self, report_id: int, bitrix_id: str) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Report]] = select(Report).where(Report.id == report_id)
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            if report:
                report.bitrix_id = str(bitrix_id)
                await session.commit()

    async def create_report_audit(self, payload: ReportAuditCreate) -> ReportAuditLog:
        async with self._session_factory() as session:
            item = ReportAuditLog(
                report_id=payload.report_id,
                stage=payload.stage,
                regulation_version=payload.regulation_version,
                payload_json=dump_json(payload.payload),
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def get_report_audits(self, report_id: int) -> list[ReportAuditLog]:
        async with self._session_factory() as session:
            stmt = (
                select(ReportAuditLog)
                .where(ReportAuditLog.report_id == report_id)
                .order_by(ReportAuditLog.created_at.asc(), ReportAuditLog.id.asc())
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_report_with_user_by_bitrix_id(self, bitrix_id: str) -> tuple[Report, User] | None:
        async with self._session_factory() as session:
            stmt = select(Report, User).join(User, Report.user_id == User.id).where(Report.bitrix_id == str(bitrix_id))
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            return row[0], row[1]

    async def update_report_status_by_bitrix_id(self, bitrix_id: str, status: str) -> Report | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Report]] = select(Report).where(Report.bitrix_id == str(bitrix_id))
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            if report is None:
                return None
            report.status = status
            await session.commit()
            await session.refresh(report)
            return report

    async def get_latest_report_summary(self, user_id: int) -> ReportLookupResult | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Report]] = (
                select(Report)
                .where(Report.user_id == user_id)
                .order_by(Report.created_at.desc(), Report.id.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            return self._to_report_lookup_result(report)

    async def get_latest_active_report_summary(self, user_id: int) -> ReportLookupResult | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Report]] = (
                select(Report)
                .where(Report.user_id == user_id)
                .order_by(Report.created_at.desc(), Report.id.desc())
            )
            result = await session.execute(stmt)
            for report in result.scalars():
                if is_active_report_status(report.status):
                    return self._to_report_lookup_result(report)
            return None

    async def get_recent_report_timestamps(self, scope_key: str, since: datetime) -> list[datetime]:
        async with self._session_factory() as session:
            stmt = select(Report.created_at).where(Report.scope_key == scope_key).where(Report.created_at >= since)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_active_incident(self, scope_key: str) -> Incident | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Incident]] = (
                select(Incident)
                .where(Incident.scope_key == scope_key)
                .where(Incident.status == IncidentStatus.ACTIVE.value)
                .order_by(Incident.started_at.desc())
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_incident(self, scope_key: str, category: str, public_message: str) -> Incident:
        async with self._session_factory() as session:
            existing = await session.execute(
                select(Incident)
                .where(Incident.scope_key == scope_key)
                .where(Incident.status == IncidentStatus.ACTIVE.value)
            )
            found = existing.scalar_one_or_none()
            if found is not None:
                return found

            incident = Incident(
                scope_key=scope_key,
                category=category,
                status=IncidentStatus.ACTIVE.value,
                public_message=public_message,
            )
            session.add(incident)
            await session.commit()
            await session.refresh(incident)
            return incident

    async def link_incident_report(self, incident_id: int, report_id: int) -> None:
        async with self._session_factory() as session:
            stmt = select(IncidentEvent).where(IncidentEvent.incident_id == incident_id).where(IncidentEvent.report_id == report_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return
            link = IncidentEvent(incident_id=incident_id, report_id=report_id)
            session.add(link)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.debug("Duplicate incident-report link: incident=%s report=%s", incident_id, report_id)

    async def create_bitrix_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        signature_valid: bool,
        bitrix_id: str | None,
        status: str | None,
        report_id: int | None,
    ) -> BitrixEvent:
        async with self._session_factory() as session:
            event = BitrixEvent(
                event_type=event_type,
                payload_json=dump_json(payload),
                signature_valid=signature_valid,
                bitrix_id=bitrix_id,
                status=status,
                report_id=report_id,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return event

    @staticmethod
    def _to_report_lookup_result(report: Report | None) -> ReportLookupResult | None:
        if report is None:
            return None
        return ReportLookupResult(
            report_id=report.id,
            created_at=report.created_at,
            status=report.status,
            category=report.category,
            address=report.address,
            jk=report.jk,
            bitrix_id=report.bitrix_id,
        )

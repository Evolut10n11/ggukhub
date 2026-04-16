from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

from app.core.enums import IncidentStatus, ReportStatus, is_active_report_status
from app.core.models import BitrixEvent, Incident, IncidentEvent, OperatorChat, Report, ReportAuditLog, SessionState, User
from app.core.schemas import ReportAuditCreate, ReportCreate, ReportLookupResult, SessionPayload
from app.core.utils import dump_json, normalize_phone

TELEGRAM_PLATFORM = "telegram"
MAX_PLATFORM = "max"


class Storage:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def health_check(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def upsert_user(self, telegram_id: int, name: str | None) -> User:
        return await self.upsert_platform_user(
            platform=TELEGRAM_PLATFORM,
            platform_user_id=telegram_id,
            name=name,
        )

    async def upsert_platform_user(
        self,
        *,
        platform: str,
        platform_user_id: int,
        name: str | None,
        platform_chat_id: int | None = None,
    ) -> User:
        normalized_platform = _normalize_platform(platform)
        legacy_user_id = _legacy_user_key(normalized_platform, platform_user_id)
        async with self._session_factory() as session:
            user = await self._find_user_by_platform_identity(
                session,
                platform=normalized_platform,
                platform_user_id=platform_user_id,
                legacy_user_id=legacy_user_id,
            )
            if user is None:
                user = User(
                    telegram_id=legacy_user_id,
                    name=name,
                    messenger_platform=normalized_platform,
                    messenger_user_id=platform_user_id,
                    messenger_chat_id=platform_chat_id if normalized_platform == MAX_PLATFORM else None,
                )
                session.add(user)
            else:
                if name and user.name != name:
                    user.name = name
                if normalized_platform == MAX_PLATFORM and user.telegram_id != legacy_user_id:
                    user.telegram_id = legacy_user_id
                user.messenger_platform = normalized_platform
                user.messenger_user_id = platform_user_id
                if normalized_platform == MAX_PLATFORM and platform_chat_id is not None:
                    user.messenger_chat_id = platform_chat_id
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> User | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.telegram_id == telegram_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_by_platform_id(self, *, platform: str, platform_user_id: int) -> User | None:
        normalized_platform = _normalize_platform(platform)
        legacy_user_id = _legacy_user_key(normalized_platform, platform_user_id)
        async with self._session_factory() as session:
            return await self._find_user_by_platform_identity(
                session,
                platform=normalized_platform,
                platform_user_id=platform_user_id,
                legacy_user_id=legacy_user_id,
            )

    async def get_user_by_id(self, user_id: int) -> User | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_users_by_phone_numbers(self, *, platform: str, phones: set[str]) -> list[User]:
        normalized_platform = _normalize_platform(platform)
        normalized_phones = {normalize_phone(phone) for phone in phones if phone.strip()}
        normalized_phones.discard(None)
        if not normalized_phones:
            return []
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.messenger_platform == normalized_platform)
            result = await session.execute(stmt)
            users = list(result.scalars().all())
            return [user for user in users if normalize_phone(user.phone or "") in normalized_phones]

    async def update_user_phone(self, user_id: int, phone: str) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user.phone = phone
                await session.commit()

    async def update_user_address(
        self,
        user_id: int,
        *,
        jk: str | None,
        house: str | None,
        entrance: str | None,
        apartment: str | None,
    ) -> None:
        async with self._session_factory() as session:
            stmt: Select[tuple[User]] = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                user.jk = jk
                user.house = house
                user.entrance = entrance
                user.apartment = apartment
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

    async def count_weekly_reports_by_apt(self, address: str, apt: str) -> int:
        async with self._session_factory() as session:
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            stmt = (
                select(func.count())
                .select_from(Report)
                .where(Report.address == address, Report.apt == apt)
                .where(Report.created_at >= week_ago)
            )
            result = await session.execute(stmt)
            return result.scalar() or 0

    async def count_weekly_reports_by_phone(self, phone: str) -> int:
        async with self._session_factory() as session:
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            stmt = (
                select(func.count())
                .select_from(Report)
                .where(Report.phone == phone)
                .where(Report.created_at >= week_ago)
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

    async def get_report_with_user(self, report_id: int) -> tuple[Report, User] | None:
        async with self._session_factory() as session:
            stmt = select(Report, User).join(User, Report.user_id == User.id).where(Report.id == report_id)
            result = await session.execute(stmt)
            row = result.first()
            if row is None:
                return None
            return row[0], row[1]

    async def update_report_status(self, report_id: int, status: str) -> Report | None:
        async with self._session_factory() as session:
            stmt: Select[tuple[Report]] = select(Report).where(Report.id == report_id)
            result = await session.execute(stmt)
            report = result.scalar_one_or_none()
            if report is None:
                return None
            report.status = status
            await session.commit()
            await session.refresh(report)
            return report

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

    async def list_recent_reports_with_users(
        self,
        *,
        platform: str | None = None,
        active_only: bool = False,
        limit: int = 10,
    ) -> list[tuple[Report, User]]:
        async with self._session_factory() as session:
            stmt = (
                select(Report, User)
                .join(User, Report.user_id == User.id)
                .order_by(Report.created_at.desc(), Report.id.desc())
                .limit(limit * 3)
            )
            if platform is not None:
                stmt = stmt.where(User.messenger_platform == _normalize_platform(platform))
            result = await session.execute(stmt)
            rows: list[tuple[Report, User]] = []
            for report, user in result.all():
                if active_only and not is_active_report_status(report.status):
                    continue
                rows.append((report, user))
                if len(rows) >= limit:
                    break
            return rows

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

    # ── Operator chat sessions ──

    async def create_operator_chat(
        self,
        *,
        user_id: int,
        max_chat_id: int,
        max_user_id: int,
        report_id: int | None = None,
        bitrix_id: str | None = None,
    ) -> OperatorChat:
        async with self._session_factory() as session:
            chat = OperatorChat(
                user_id=user_id,
                max_chat_id=max_chat_id,
                max_user_id=max_user_id,
                report_id=report_id,
                bitrix_id=bitrix_id,
                status="active",
            )
            session.add(chat)
            await session.commit()
            await session.refresh(chat)
            return chat

    async def get_active_operator_chat_by_max_user(self, max_user_id: int) -> OperatorChat | None:
        async with self._session_factory() as session:
            stmt = (
                select(OperatorChat)
                .where(OperatorChat.max_user_id == max_user_id, OperatorChat.status == "active")
                .order_by(OperatorChat.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_active_operator_chat_by_external_id(self, external_user_id: str) -> OperatorChat | None:
        """Find active operator chat by external user ID (max_{user_id})."""
        if not external_user_id.startswith("max_"):
            return None
        try:
            max_user_id = int(external_user_id[4:])
        except ValueError:
            return None
        return await self.get_active_operator_chat_by_max_user(max_user_id)

    async def close_operator_chat(self, chat_id: int) -> None:
        async with self._session_factory() as session:
            stmt = select(OperatorChat).where(OperatorChat.id == chat_id)
            result = await session.execute(stmt)
            chat = result.scalar_one_or_none()
            if chat:
                chat.status = "closed"
                chat.closed_at = datetime.now(timezone.utc)
                await session.commit()

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

    async def _find_user_by_platform_identity(
        self,
        session: AsyncSession,
        *,
        platform: str,
        platform_user_id: int,
        legacy_user_id: int,
    ) -> User | None:
        stmt = (
            select(User)
            .where(User.messenger_platform == platform)
            .where(User.messenger_user_id == platform_user_id)
        )
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        stmt = select(User).where(User.telegram_id == legacy_user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is not None:
            return user

        if platform != MAX_PLATFORM:
            return None

        # Support legacy MAX rows created before messenger metadata existed.
        stmt = select(User).where(User.telegram_id == platform_user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


def _normalize_platform(platform: str | None) -> str:
    value = str(platform or TELEGRAM_PLATFORM).strip().lower()
    if value == MAX_PLATFORM:
        return MAX_PLATFORM
    return TELEGRAM_PLATFORM


def _legacy_user_key(platform: str, platform_user_id: int) -> int:
    if platform == MAX_PLATFORM:
        return -abs(int(platform_user_id))
    return int(platform_user_id)

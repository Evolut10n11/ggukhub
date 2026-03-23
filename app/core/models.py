from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BIGINT, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.enums import IncidentStatus, ReportStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BIGINT, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    bitrix_contact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped["SessionState"] = relationship(back_populates="user", uselist=False)
    reports: Mapped[list["Report"]] = relationship(back_populates="user")


class SessionState(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="sessions")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    jk: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str] = mapped_column(String(255))
    apt: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    scope_key: Mapped[str] = mapped_column(String(512), index=True)
    status: Mapped[str] = mapped_column(String(64), default=ReportStatus.NEW.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    bitrix_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="reports")
    incident_events: Mapped[list["IncidentEvent"]] = relationship(back_populates="report")
    audit_logs: Mapped[list["ReportAuditLog"]] = relationship(back_populates="report")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(512), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default=IncidentStatus.ACTIVE.value, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    public_message: Mapped[str] = mapped_column(Text)
    eta: Mapped[str | None] = mapped_column(String(255), nullable=True)

    events: Mapped[list["IncidentEvent"]] = relationship(back_populates="incident")

    __table_args__ = (Index("ix_incidents_scope_status", "scope_key", "status"),)

class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="events")
    report: Mapped[Report] = relationship(back_populates="incident_events")

    __table_args__ = (UniqueConstraint("incident_id", "report_id", name="uq_incident_event_report"),)


class BitrixEvent(Base):
    __tablename__ = "bitrix_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    bitrix_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportAuditLog(Base):
    __tablename__ = "report_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    regulation_version: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    report: Mapped[Report] = relationship(back_populates="audit_logs")

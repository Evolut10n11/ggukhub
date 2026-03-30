from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.enums import report_status_label
from app.telegram.dialog.models import DialogStep


@dataclass(slots=True)
class ReportReviewView:
    category_label: str
    jk: str | None
    house: str | None
    entrance: str | None
    apartment: str | None
    phone: str | None
    problem_text: str | None
    category_options_hint: str | None = None
    mc_name: str | None = None
    mc_dispatcher_phone: str | None = None
    mc_emergency_phone: str | None = None


@dataclass(slots=True)
class ReportSummaryView:
    report_id: int
    category_label: str
    jk: str | None
    house: str
    entrance: str | None
    apartment: str
    bitrix_enabled: bool
    bitrix_id: str | None = None
    bitrix_sync_outcome: str | None = None
    mc_name: str | None = None
    mc_dispatcher_phone: str | None = None
    mc_emergency_phone: str | None = None


@dataclass(slots=True)
class ReportLookupView:
    report_id: int
    status: str | None
    created_at: datetime
    category_label: str
    address: str
    jk: str | None
    bitrix_id: str | None
    bitrix_status_label: str | None = None
    bitrix_date_modify: str | None = None
    bitrix_comments: list[dict[str, str]] | None = None


@dataclass(slots=True)
class CreatedReportReplyParts:
    standard_reply: str
    summary: str
    incident_message: str | None = None
    incident_report_id: int | None = None
    include_missing_jk_note: bool = False


def build_report_review(view: ReportReviewView) -> str:
    lines = [
        "Проверьте, пожалуйста, заявку перед отправкой:",
        f"Тип: {view.category_label}",
        f"ЖК: {view.jk or 'не указан'}",
        f"Дом: {view.house or 'не указан'}",
        f"Подъезд: {view.entrance or 'не указан'}",
        f"Квартира: {view.apartment or 'не указана'}",
        f"Телефон: {view.phone or 'не указан'}",
        f"Проблема: {view.problem_text or 'не указана'}",
    ]
    if view.mc_name:
        lines.append(f"УК: {view.mc_name}")
        if view.mc_dispatcher_phone:
            lines.append(f"Диспетчерская: {view.mc_dispatcher_phone} (круглосуточно)")
        if view.mc_emergency_phone:
            lines.append(f"Аварийный: {view.mc_emergency_phone}")
    if view.category_options_hint:
        lines.extend(["", view.category_options_hint])
    lines.extend(
        [
            "",
            "Если все верно, подтвердите заявку. Если нет, выберите исправление.",
            "Можно исправить адрес, телефон, описание проблемы или категорию одним сообщением.",
        ]
    )
    return "\n".join(lines)


def build_category_options_hint(category_labels: list[str]) -> str:
    options = [label.strip() for label in category_labels if label.strip()]
    if not options:
        return ""
    return "Доступные типы заявок: " + ", ".join(options) + "."


def build_saved_phone_prompt(phone: str | None) -> str:
    saved_phone = str(phone or "").strip()
    if not saved_phone:
        return "Не нашла сохраненный номер. Укажите телефон для связи в формате +7XXXXXXXXXX."
    return (
        f"Для связи у меня сохранен номер {saved_phone}.\n"
        "Использовать его для этой заявки или указать другой?"
    )


def build_report_summary(view: ReportSummaryView) -> str:
    bitrix_sync_outcome = view.bitrix_sync_outcome or ("queued" if view.bitrix_enabled else "disabled")
    lines = [
        "Сводка по заявке:",
        f"Тип: {view.category_label}",
        f"ЖК: {view.jk or 'не указан'}",
        f"Дом: {view.house}",
        f"Подъезд: {view.entrance or 'не указан'}",
        f"Квартира: {view.apartment}",
    ]
    if view.mc_name:
        lines.append(f"УК: {view.mc_name}")
        if view.mc_dispatcher_phone:
            lines.append(f"Диспетчерская: {view.mc_dispatcher_phone} (круглосуточно)")
        if view.mc_emergency_phone:
            lines.append(f"Аварийный: {view.mc_emergency_phone}")
    if view.bitrix_id:
        lines.append(f"Статус: создана (Bitrix24 №{view.bitrix_id})")
    else:
        lines.append("Статус: создана")
    if bitrix_sync_outcome == "queued" and not view.bitrix_id:
        lines.append("Bitrix24: передаю заявку, номер пришлю отдельным сообщением.")
    elif bitrix_sync_outcome == "failed":
        lines.append("Bitrix24: не удалось передать автоматически, уточняю вручную.")
    elif bitrix_sync_outcome == "disabled":
        lines.append("Bitrix24: интеграция сейчас выключена.")
    return "\n".join(lines)


def build_created_report_reply(parts: CreatedReportReplyParts) -> str:
    chunks = [parts.standard_reply]
    if parts.incident_message:
        chunks.append(parts.incident_message)
        if parts.incident_report_id is not None:
            chunks.append(f"Номер заявки: {parts.incident_report_id}.")
    chunks.append(parts.summary)
    reply = "\n\n".join(chunk for chunk in chunks if chunk)
    if parts.include_missing_jk_note:
        reply += "\n\nЕсли сможете, дополнительно напишите ЖК — я добавлю в заявку."
    return reply


def build_report_lookup_reply(view: ReportLookupView) -> str:
    created_at = view.created_at.astimezone().strftime("%d.%m.%Y %H:%M")
    lines = [
        "Нашла последнюю заявку:",
        f"Номер: {view.report_id}",
        f"Статус: {report_status_label(view.status)}",
        f"Создана: {created_at}",
        f"Тип: {view.category_label}",
        f"Адрес: {view.address}",
    ]
    if view.jk:
        lines.append(f"ЖК: {view.jk}")
    if view.bitrix_id:
        lines.append(f"Bitrix24: {view.bitrix_id}")
    if view.bitrix_status_label:
        lines.append(f"Статус в Bitrix24: {view.bitrix_status_label}")
    if view.bitrix_date_modify:
        lines.append(f"Обновлена: {view.bitrix_date_modify}")
    if view.bitrix_comments:
        lines.append("")
        lines.append("Последние комментарии:")
        for c in view.bitrix_comments:
            lines.append(f"  — {c.get('comment', '')}")
    return "\n".join(lines)


def build_resume_prompt(step: DialogStep) -> str | None:
    prompts = {
        DialogStep.AWAITING_JK: "Черновик новой заявки сохранила. Чтобы продолжить, выберите ЖК.",
        DialogStep.AWAITING_HOUSE: "Черновик новой заявки сохранила. Чтобы продолжить, напишите дом.",
        DialogStep.AWAITING_ENTRANCE: "Черновик новой заявки сохранила. Чтобы продолжить, укажите подъезд.",
        DialogStep.AWAITING_APARTMENT: "Черновик новой заявки сохранила. Чтобы продолжить, укажите квартиру.",
        DialogStep.AWAITING_PHONE: "Черновик новой заявки сохранила. Чтобы продолжить, отправьте телефон.",
        DialogStep.AWAITING_PROBLEM: "Черновик новой заявки сохранила. Чтобы продолжить, опишите проблему.",
        DialogStep.AWAITING_PHONE_REUSE_CONFIRM: (
            "Черновик новой заявки сохранила. Чтобы продолжить, подтвердите сохраненный номер или отправьте новый."
        ),
        DialogStep.AWAITING_REPORT_CONFIRM: (
            "Черновик новой заявки сохранила. Чтобы продолжить, подтвердите сводку или выберите исправление."
        ),
        DialogStep.AWAITING_REPORT_CORRECTION: (
            "Черновик новой заявки сохранила. Чтобы продолжить, напишите, что нужно исправить."
        ),
    }
    return prompts.get(step)

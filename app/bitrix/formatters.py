from __future__ import annotations

from app.core.models import Report


def build_ticket_title(report: Report) -> str:
    return f"Обращение через MAX {report.text}"


def build_ticket_description(report: Report) -> str:
    return (
        f"{report.text}\n\n"
        f"Категория: {report.category}\n"
        f"ЖК: {report.jk or 'не указан'}\n"
        f"Адрес: {report.address}\n"
        f"Квартира: {report.apt}\n"
        f"Телефон: {report.phone}"
    )

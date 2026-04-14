from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import Settings
from app.core.enums import ReportStatus, report_status_label
from app.core.models import Report, User
from app.core.notifier import UserNotifier
from app.core.storage import Storage
from app.core.utils import normalize_phone
from app.max.client import MaxBotClient
from app.max.keyboards import MaxKeyboardFactory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OperatorPendingAction:
    kind: str
    report_id: int


class MaxOperatorService:
    def __init__(self, settings: Settings, storage: Storage, notifier: UserNotifier) -> None:
        self._settings = settings
        self._storage = storage
        self._notifier = notifier
        self._operator_phones = _parse_operator_phones(settings.max_operator_phones)
        self._operator_ids = _parse_operator_ids(settings.max_operator_user_ids)
        has_operator_targets = bool(self._operator_ids or self._operator_phones)
        self._client = MaxBotClient(settings) if settings.max_enabled and has_operator_targets else None
        self._kb = MaxKeyboardFactory()
        self._pending: dict[int, OperatorPendingAction] = {}

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def is_operator(self, user_id: int) -> bool:
        if user_id in self._operator_ids:
            return True
        if not self._operator_phones:
            return False
        user = await self._storage.get_user_by_platform_id(platform="max", platform_user_id=user_id)
        if user is None:
            return False
        return _normalize_stored_phone(user.phone) in self._operator_phones

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    async def notify_new_report(self, report: Report, user: User) -> None:
        if not self.enabled or user.platform != "max":
            return
        text = self._build_new_report_text(report, user)
        attachments = self._kb.operator_report_keyboard(report.id)
        operator_ids = await self._resolve_operator_recipient_ids()
        if not operator_ids:
            logger.warning("MAX operator recipients are not configured or not linked to saved phones")
            return
        for operator_id in operator_ids:
            try:
                await self._client.send_direct_message(operator_id, text, attachments=attachments)  # type: ignore[union-attr]
            except Exception:
                logger.warning("Failed to notify MAX operator %s about report %s", operator_id, report.id, exc_info=True)

    async def handle_operator_message(self, chat_id: int, user_id: int, text: str) -> bool:
        stripped = text.strip()
        if not await self.is_operator(user_id):
            activated = await self._activate_operator_by_phone(chat_id, user_id, stripped)
            if activated:
                return True
            return False

        pending = self._pending.get(user_id)
        if pending is not None and stripped and not stripped.startswith("/"):
            self._pending.pop(user_id, None)
            if pending.kind == "reply":
                await self._reply_to_report(chat_id, pending.report_id, stripped)
                return True
            if pending.kind == "close":
                await self._close_report(chat_id, pending.report_id, stripped)
                return True

        if not stripped.startswith("/"):
            await self._send_chat_message(chat_id, "Используйте /queue, /take, /reply или /close.")
            return True

        command, report_id, tail = _parse_operator_command(stripped)
        if command in {"/ops", "/operator", "/help"}:
            await self._send_help(chat_id)
            return True
        if command in {"/queue", "/open"}:
            await self._send_queue(chat_id)
            return True
        if command == "/take" and report_id is not None:
            await self._take_report(chat_id, report_id)
            return True
        if command == "/reply" and report_id is not None:
            if tail:
                await self._reply_to_report(chat_id, report_id, tail)
            else:
                self._pending[user_id] = OperatorPendingAction(kind="reply", report_id=report_id)
                await self._send_chat_message(chat_id, f"Напишите следующим сообщением ответ для заявки №{report_id}.")
            return True
        if command == "/close" and report_id is not None:
            if tail:
                await self._close_report(chat_id, report_id, tail)
            else:
                self._pending[user_id] = OperatorPendingAction(kind="close", report_id=report_id)
                await self._send_chat_message(chat_id, f"Напишите следующим сообщением финальный ответ для заявки №{report_id}.")
            return True
        await self._send_help(chat_id)
        return True

    async def handle_operator_callback(self, chat_id: int, user_id: int, payload: str) -> bool:
        if not await self.is_operator(user_id):
            return False
        if payload.startswith("op_take:"):
            await self._take_report(chat_id, int(payload.split(":", 1)[1]))
            return True
        if payload.startswith("op_reply:"):
            report_id = int(payload.split(":", 1)[1])
            self._pending[user_id] = OperatorPendingAction(kind="reply", report_id=report_id)
            await self._send_chat_message(chat_id, f"Напишите следующим сообщением ответ для заявки №{report_id}.")
            return True
        if payload.startswith("op_close:"):
            report_id = int(payload.split(":", 1)[1])
            self._pending[user_id] = OperatorPendingAction(kind="close", report_id=report_id)
            await self._send_chat_message(chat_id, f"Напишите следующим сообщением финальный ответ для заявки №{report_id}.")
            return True
        return False

    async def _take_report(self, chat_id: int, report_id: int) -> None:
        payload = await self._storage.get_report_with_user(report_id)
        if payload is None:
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не найдена.")
            return
        report, user = payload
        if user.platform != "max":
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не относится к MAX.")
            return
        await self._storage.update_report_status(report.id, ReportStatus.IN_PROGRESS.value)
        await self._notifier.send_user_message(user, f"Заявка №{report.id} взята в работу.")
        await self._send_chat_message(chat_id, f"Заявка №{report.id} переведена в статус «{report_status_label(ReportStatus.IN_PROGRESS.value)}».")

    async def _reply_to_report(self, chat_id: int, report_id: int, text: str) -> None:
        payload = await self._storage.get_report_with_user(report_id)
        if payload is None:
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не найдена.")
            return
        report, user = payload
        if user.platform != "max":
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не относится к MAX.")
            return
        await self._storage.update_report_status(report.id, ReportStatus.IN_PROGRESS.value)
        await self._notifier.send_user_message(user, f"Ответ по заявке №{report.id}:\n{text}")
        await self._send_chat_message(chat_id, f"Ответ по заявке №{report.id} отправлен пользователю.")

    async def _close_report(self, chat_id: int, report_id: int, text: str) -> None:
        payload = await self._storage.get_report_with_user(report_id)
        if payload is None:
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не найдена.")
            return
        report, user = payload
        if user.platform != "max":
            await self._send_chat_message(chat_id, f"Заявка №{report_id} не относится к MAX.")
            return
        await self._storage.update_report_status(report.id, ReportStatus.CLOSED.value)
        user_message = f"Заявка №{report.id} закрыта.\n{text}" if text else f"Заявка №{report.id} закрыта."
        await self._notifier.send_user_message(user, user_message)
        await self._send_chat_message(chat_id, f"Заявка №{report.id} закрыта и отправлена пользователю.")

    async def _send_help(self, chat_id: int) -> None:
        await self._send_chat_message(
            chat_id,
            (
                "Команды оператора:\n"
                "/queue — показать открытые заявки\n"
                "/take <id> — взять заявку в работу\n"
                "/reply <id> <текст> — ответить пользователю\n"
                "/close <id> <текст> — закрыть заявку и отправить финальный ответ"
            ),
        )

    async def _send_queue(self, chat_id: int) -> None:
        items = await self._storage.list_recent_reports_with_users(platform="max", active_only=True, limit=10)
        if not items:
            await self._send_chat_message(chat_id, "Открытых заявок из MAX сейчас нет.")
            return
        lines = ["Открытые заявки MAX:"]
        for report, user in items:
            lines.append(
                f"№{report.id} [{report_status_label(report.status)}] {report.category} | {report.address} | {user.name or user.platform_user_id}"
            )
        await self._send_chat_message(chat_id, "\n".join(lines))

    async def _send_chat_message(self, chat_id: int, text: str) -> None:
        if not self.enabled:
            return
        await self._client.send_message(chat_id, text)  # type: ignore[union-attr]

    async def _activate_operator_by_phone(self, chat_id: int, user_id: int, text: str) -> bool:
        if not self._operator_phones:
            return False
        normalized_phone = _normalize_stored_phone(text)
        if normalized_phone not in self._operator_phones:
            return False
        user = await self._storage.upsert_platform_user(
            platform="max",
            platform_user_id=user_id,
            name=None,
            platform_chat_id=chat_id,
        )
        await self._storage.update_user_phone(user.id, normalized_phone)
        await self._send_chat_message(
            chat_id,
            "Режим оператора активирован по номеру телефона. Теперь доступны /queue, /take, /reply и /close.",
        )
        await self._send_help(chat_id)
        return True

    async def _resolve_operator_recipient_ids(self) -> set[int]:
        operator_ids = set(self._operator_ids)
        if self._operator_phones:
            users = await self._storage.list_users_by_phone_numbers(platform="max", phones=self._operator_phones)
            operator_ids.update(user.platform_user_id for user in users if user.platform == "max")
        return operator_ids

    @staticmethod
    def _build_new_report_text(report: Report, user: User) -> str:
        lines = [
            f"Новая заявка №{report.id}",
            f"Статус: {report_status_label(report.status)}",
            f"Житель: {user.name or user.platform_user_id}",
            f"Адрес: {report.address}",
            f"Категория: {report.category}",
            f"Телефон: {report.phone}",
            "Описание:",
            report.text,
            "",
            "Дальше можно нажать кнопку ниже или использовать команды /take, /reply, /close.",
        ]
        return "\n".join(lines)


def _parse_operator_ids(raw: str) -> set[int]:
    return {int(value.strip()) for value in raw.split(",") if value.strip().isdigit()}


def _parse_operator_phones(raw: str) -> set[str]:
    phones: set[str] = set()
    for value in raw.split(","):
        normalized = normalize_phone(value.strip())
        if normalized:
            phones.add(normalized)
    return phones


def _normalize_stored_phone(value: str | None) -> str | None:
    if not value:
        return None
    return normalize_phone(value)


def _parse_operator_command(text: str) -> tuple[str, int | None, str | None]:
    parts = text.split(maxsplit=2)
    command = parts[0].lower()
    report_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
    tail = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else None
    return command, report_id, tail

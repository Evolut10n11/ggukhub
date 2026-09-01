from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence


SUPPORTED_COMMANDS: tuple[str, ...] = (
    "помощь",
    "авария",
    "заявка",
    "домофон",
    "лифт",
    "уборка",
    "вода",
    "отопление",
)

MAX_COMMANDS: tuple[dict[str, str], ...] = (
    {"name": "помощь", "description": "Справка и список команд"},
    {"name": "авария", "description": "Сообщить об аварийной ситуации"},
    {"name": "заявка", "description": "Создать обычную заявку"},
    {"name": "домофон", "description": "Проблема с домофоном"},
    {"name": "лифт", "description": "Проблема с лифтом"},
    {"name": "уборка", "description": "Проблема с уборкой"},
    {"name": "вода", "description": "Проблема с водоснабжением"},
    {"name": "отопление", "description": "Проблема с отоплением"},
)

RouteAction = Literal["ignore", "message", "help", "callback", "bot_started"]


@dataclass(frozen=True, slots=True)
class MaxBotIdentity:
    user_id: int | None = None
    username: str | None = None


@dataclass(frozen=True, slots=True)
class MaxRouteDecision:
    action: RouteAction
    reason: str
    text: str = ""
    command: str | None = None
    command_args: str = ""
    chat_type: str | None = None
    message_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.action != "ignore"


def route_max_update(update: Mapping[str, Any], identity: MaxBotIdentity) -> MaxRouteDecision:
    """Deterministically decide whether an update may reach dialog/business logic."""
    update_type = str(update.get("update_type") or "")
    if update_type == "message_callback":
        callback = _mapping(update.get("callback"))
        callback_user = _mapping(callback.get("user") or callback.get("sender"))
        if _is_bot_sender(callback_user, identity):
            return MaxRouteDecision("ignore", "ignored_bot_sender")
        return MaxRouteDecision("callback", "accepted_callback")

    if update_type == "bot_started":
        user = _mapping(update.get("user"))
        if _is_bot_sender(user, identity):
            return MaxRouteDecision("ignore", "ignored_bot_sender")
        return MaxRouteDecision("bot_started", "accepted_bot_started")

    if update_type != "message_created":
        return MaxRouteDecision("ignore", "ignored_irrelevant_update")

    message = _mapping(update.get("message"))
    sender = _mapping(message.get("sender"))
    recipient = _mapping(message.get("recipient"))
    body = _mapping(message.get("body"))
    chat_type = str(recipient.get("chat_type") or "").casefold() or None
    message_id = _string_or_none(body.get("mid"))

    if _is_bot_sender(sender, identity):
        return MaxRouteDecision(
            "ignore", "ignored_bot_sender", chat_type=chat_type, message_id=message_id
        )
    if chat_type == "channel" or not sender:
        return MaxRouteDecision(
            "ignore", "ignored_channel_message", chat_type=chat_type, message_id=message_id
        )

    text = str(body.get("text") or "").strip()
    if chat_type == "dialog":
        command, command_args = _parse_command(text)
        supported_command = command if command in SUPPORTED_COMMANDS else None
        return MaxRouteDecision(
            "message",
            "accepted_command" if supported_command else "accepted_dialog",
            text=text,
            command=supported_command,
            command_args=command_args if supported_command else "",
            chat_type=chat_type,
            message_id=message_id,
        )

    # Unknown recipient types are ignored deliberately. Treating an unknown type as
    # a dialog would reopen the group-spam failure this gate is meant to prevent.
    if chat_type != "chat":
        return MaxRouteDecision(
            "ignore", "ignored_unknown_chat_type", chat_type=chat_type, message_id=message_id
        )

    link_type = str(_mapping(message.get("link")).get("type") or "").casefold()
    if link_type == "forward":
        return MaxRouteDecision(
            "ignore", "ignored_forwarded_message", chat_type=chat_type, message_id=message_id
        )

    command, command_args = _parse_command(text)
    if command in SUPPORTED_COMMANDS:
        return MaxRouteDecision(
            "message",
            "accepted_command",
            text=text,
            command=command,
            command_args=command_args,
            chat_type=chat_type,
            message_id=message_id,
        )

    if _is_reply_to_bot(message, identity):
        if not text:
            return MaxRouteDecision(
                "ignore", "ignored_empty_message", chat_type=chat_type, message_id=message_id
            )
        return MaxRouteDecision(
            "message", "accepted_reply", text=text, chat_type=chat_type, message_id=message_id
        )

    mentioned, cleaned_text = _extract_current_bot_mention(body, text, identity)
    if mentioned:
        cleaned_command, cleaned_args = _parse_command(cleaned_text)
        if not cleaned_text:
            return MaxRouteDecision(
                "help", "accepted_mention", chat_type=chat_type, message_id=message_id
            )
        return MaxRouteDecision(
            "message",
            "accepted_command" if cleaned_command in SUPPORTED_COMMANDS else "accepted_mention",
            text=cleaned_text,
            command=cleaned_command if cleaned_command in SUPPORTED_COMMANDS else None,
            command_args=cleaned_args if cleaned_command in SUPPORTED_COMMANDS else "",
            chat_type=chat_type,
            message_id=message_id,
        )

    return MaxRouteDecision(
        "ignore", "ignored_unaddressed_group_message", chat_type=chat_type, message_id=message_id
    )


def update_deduplication_key(update: Mapping[str, Any]) -> str | None:
    update_type = str(update.get("update_type") or "")
    if update_type in {"message_created", "message_callback"}:
        message = _mapping(update.get("message"))
        mid = _mapping(message.get("body")).get("mid")
        if mid:
            if update_type == "message_callback":
                callback_id = _mapping(update.get("callback")).get("callback_id")
                return f"callback:{callback_id or mid}"
            return f"message:{mid}"

    callback_id = _mapping(update.get("callback")).get("callback_id")
    if callback_id:
        return f"callback:{callback_id}"

    if update_type == "bot_started":
        user_id = _mapping(update.get("user")).get("user_id")
        chat_id = update.get("chat_id")
        timestamp = update.get("timestamp")
        if user_id and chat_id and timestamp:
            return f"bot_started:{chat_id}:{user_id}:{timestamp}"
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _same_user_id(value: Any, expected: int | None) -> bool:
    if value is None or expected is None:
        return False
    return str(value) == str(expected)


def _is_bot_sender(sender: Mapping[str, Any], identity: MaxBotIdentity) -> bool:
    return sender.get("is_bot") is True or _same_user_id(sender.get("user_id"), identity.user_id)


def _parse_command(text: str) -> tuple[str | None, str]:
    match = re.match(r"^/([^\s/]+)(?:\s+([\s\S]*))?$", text.strip())
    if not match:
        return None, ""
    return match.group(1).casefold(), (match.group(2) or "").strip()


def _is_reply_to_bot(message: Mapping[str, Any], identity: MaxBotIdentity) -> bool:
    if identity.user_id is None:
        return False
    link = _mapping(message.get("link"))
    if str(link.get("type") or "").casefold() != "reply":
        return False
    linked_sender = _mapping(link.get("sender"))
    if not linked_sender:
        linked_sender = _mapping(_mapping(link.get("message")).get("sender"))
    return _same_user_id(linked_sender.get("user_id"), identity.user_id)


def _extract_current_bot_mention(
    body: Mapping[str, Any], text: str, identity: MaxBotIdentity
) -> tuple[bool, str]:
    patterns: list[re.Pattern[str]] = []
    if identity.user_id is not None:
        user_id = re.escape(str(identity.user_id))
        patterns.extend(
            (
                re.compile(rf"\[[^\]]+\]\(max://user/{user_id}\)", re.IGNORECASE),
                re.compile(
                    rf"<a\s+[^>]*href=[\"']max://user/{user_id}[\"'][^>]*>.*?</a>",
                    re.IGNORECASE | re.DOTALL,
                ),
                re.compile(rf"max://user/{user_id}", re.IGNORECASE),
            )
        )
    username = str(identity.username or "").strip().lstrip("@")
    if username:
        patterns.append(
            re.compile(rf"(?<![\w@])@{re.escape(username)}(?![\w])", re.IGNORECASE)
        )

    mentioned = False
    cleaned = text
    for pattern in patterns:
        cleaned, count = pattern.subn(" ", cleaned)
        mentioned = mentioned or count > 0

    if _has_structured_mention(body, identity):
        mentioned = True
        for mention in _structured_mentions(body):
            mention_username = str(mention.get("username") or "").strip().lstrip("@")
            if mention_username and _same_user_id(mention.get("user_id"), identity.user_id):
                cleaned = re.sub(
                    rf"(?<![\w@])@{re.escape(mention_username)}(?![\w])",
                    " ",
                    cleaned,
                    flags=re.IGNORECASE,
                )

    return mentioned, re.sub(r"\s+", " ", cleaned).strip(" ,:\t\r\n")


def _structured_mentions(body: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    mentions: list[Mapping[str, Any]] = []
    for field in ("mentions", "entities"):
        values = body.get(field)
        if isinstance(values, list):
            for value in values:
                item = _mapping(value)
                if str(item.get("type") or "mention").casefold() == "mention":
                    mentions.append(_mapping(item.get("payload")) or item)
    attachments = body.get("attachments")
    if isinstance(attachments, list):
        for value in attachments:
            item = _mapping(value)
            if str(item.get("type") or "").casefold() == "mention":
                mentions.append(_mapping(item.get("payload")) or item)
    return mentions


def _has_structured_mention(body: Mapping[str, Any], identity: MaxBotIdentity) -> bool:
    return any(
        _same_user_id(mention.get("user_id"), identity.user_id)
        for mention in _structured_mentions(body)
    )

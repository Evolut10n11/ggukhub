from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.core.buildings import BuildingRegistry, ComplexInfo, HouseInfo
from app.max.client import MaxBotClient
from app.max.keyboards import MaxKeyboardFactory
from app.max.polling import MaxPolling
from app.max.routing import MaxBotIdentity, route_max_update
from app.telegram.keyboards import (
    TelegramKeyboardFactory,
    build_category_confirm_keyboard,
    build_category_select_keyboard,
    build_entrance_keyboard,
    build_house_keyboard,
    build_jk_keyboard,
    build_phone_reuse_keyboard,
    build_report_confirm_keyboard,
)


def _max_rows(attachments: list[dict[str, object]]) -> list[list[tuple[str, str]]]:
    rows = attachments[0]["payload"]["buttons"]  # type: ignore[index]
    return [[(button["text"], button["payload"]) for button in row] for row in rows]  # type: ignore[index]


def _tg_rows(markup) -> list[list[tuple[str, str]]]:
    return [[(button.text, button.callback_data) for button in row] for row in markup.inline_keyboard]


class _DialogServiceStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.active_dialog = False

    async def select_housing_complex(self, transport, complex_name: str) -> None:
        _ = transport
        self.calls.append(("select_housing_complex", complex_name))

    async def show_standalone_houses(self, transport) -> None:
        _ = transport
        self.calls.append(("show_standalone_houses", None))

    async def mark_unknown_housing_complex(self, transport) -> None:
        _ = transport
        self.calls.append(("mark_unknown_housing_complex", None))

    async def select_house(self, transport, idx: int) -> None:
        _ = transport
        self.calls.append(("select_house", idx))

    async def paginate_houses(self, transport, page: int) -> None:
        _ = transport
        self.calls.append(("paginate_houses", page))

    async def select_entrance(self, transport, entrance: str) -> None:
        _ = transport
        self.calls.append(("select_entrance", entrance))

    async def confirm_category(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_category", None))

    async def request_manual_category(self, transport) -> None:
        _ = transport
        self.calls.append(("request_manual_category", None))

    async def select_category(self, transport, category: str) -> None:
        _ = transport
        self.calls.append(("select_category", category))

    async def confirm_report(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_report", None))

    async def request_report_correction(self, transport) -> None:
        _ = transport
        self.calls.append(("request_report_correction", None))

    async def confirm_saved_phone(self, transport) -> None:
        _ = transport
        self.calls.append(("confirm_saved_phone", None))

    async def request_new_phone(self, transport) -> None:
        _ = transport
        self.calls.append(("request_new_phone", None))

    async def start(self, transport, *, include_welcome: bool) -> None:
        _ = transport
        self.active_dialog = True
        self.calls.append(("start", include_welcome))

    async def process_text(self, transport, text: str, from_voice: bool = False) -> None:
        _ = transport, from_voice
        self.calls.append(("process_text", text))

    async def has_active_dialog(self, platform: str, platform_user_id: int) -> bool:
        _ = platform, platform_user_id
        return self.active_dialog


class _MaxClientStub:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []
        self.answered_callbacks: list[str] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        attachments=None,
        format: str = "markdown",
        reply_to_mid: str | None = None,
    ) -> dict[str, object]:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "attachments": attachments,
                "format": format,
                "reply_to_mid": reply_to_mid,
            }
        )
        return {"success": True}

    async def answer_callback(self, callback_id: str, *, notification: str | None = None) -> dict[str, object]:
        _ = notification
        self.answered_callbacks.append(callback_id)
        return {"success": True}


def test_max_shared_inline_keyboards_match_telegram() -> None:
    max_factory = MaxKeyboardFactory()
    telegram_factory = TelegramKeyboardFactory()

    complexes = [f"Complex {index}" for index in range(10)]
    houses = [HouseInfo(address=f"Дом {index}", entrances=4, apartments=20) for index in range(10)]

    assert _max_rows(max_factory.jk_keyboard(complexes, page=0)) == _tg_rows(build_jk_keyboard(complexes, page=0))
    assert _max_rows(max_factory.jk_keyboard(complexes, page=1)) == _tg_rows(build_jk_keyboard(complexes, page=1))
    assert _max_rows(max_factory.house_keyboard(houses, page=0)) == _tg_rows(build_house_keyboard(houses, page=0))
    assert _max_rows(max_factory.house_keyboard(houses, page=1)) == _tg_rows(build_house_keyboard(houses, page=1))
    assert _max_rows(max_factory.entrance_keyboard(6)) == _tg_rows(build_entrance_keyboard(6))
    assert _max_rows(max_factory.category_confirm_keyboard()) == _tg_rows(build_category_confirm_keyboard())
    assert _max_rows(max_factory.category_select_keyboard()) == _tg_rows(build_category_select_keyboard())
    assert _max_rows(max_factory.report_confirm_keyboard()) == _tg_rows(build_report_confirm_keyboard())
    assert _max_rows(max_factory.phone_reuse_keyboard("+79990001122")) == _tg_rows(build_phone_reuse_keyboard("+79990001122"))
    assert _max_rows(max_factory.new_report_keyboard()) == _tg_rows(telegram_factory.new_report_keyboard())
    assert _max_rows(max_factory.back_to_menu_keyboard()) == _tg_rows(telegram_factory.back_to_menu_keyboard())


@pytest.mark.asyncio
async def test_max_jk_page_callback_sends_requested_page_keyboard() -> None:
    settings = Settings(telegram_bot_token="test-token", max_bot_token="max-token")
    registry = BuildingRegistry(
        complexes=[ComplexInfo(name=f"Complex {index}") for index in range(18)],
        standalone_houses=[],
    )
    services = SimpleNamespace(building_registry=registry)
    poller = MaxPolling(settings, services)  # type: ignore[arg-type]
    poller._dialog_service = _DialogServiceStub()  # type: ignore[assignment]
    poller._client = _MaxClientStub()  # type: ignore[assignment]

    update = {
        "callback": {
            "callback_id": "cb-1",
            "payload": "jk_page:1",
            "user": {"user_id": 101, "name": "Tester"},
        },
        "message": {"recipient": {"chat_id": 202}},
    }

    await poller._handle_callback(update)

    assert poller._client.answered_callbacks == ["cb-1"]  # type: ignore[attr-defined]
    assert len(poller._client.sent_messages) == 1  # type: ignore[attr-defined]

    sent = poller._client.sent_messages[0]  # type: ignore[attr-defined]
    assert sent["chat_id"] == 202
    assert "жилой комплекс" in str(sent["text"])
    assert sent["attachments"] == MaxKeyboardFactory(
        redirect_bot_url=settings.max_redirect_bot_url
    ).jk_keyboard(registry.complex_names, page=1)


@pytest.mark.asyncio
async def test_max_callback_routes_match_expected_dialog_actions() -> None:
    settings = Settings(telegram_bot_token="test-token", max_bot_token="max-token")
    registry = BuildingRegistry(
        complexes=[ComplexInfo(name=f"Complex {index}") for index in range(3)],
        standalone_houses=[],
    )
    services = SimpleNamespace(building_registry=registry)
    poller = MaxPolling(settings, services)  # type: ignore[arg-type]
    poller._dialog_service = _DialogServiceStub()  # type: ignore[assignment]
    poller._client = _MaxClientStub()  # type: ignore[assignment]

    cases = [
        ("jk_pick:1", ("select_housing_complex", "Complex 1")),
        ("jk_standalone", ("show_standalone_houses", None)),
        ("jk_unknown", ("mark_unknown_housing_complex", None)),
        ("house:2", ("select_house", 2)),
        ("house_p:3", ("paginate_houses", 3)),
        ("ent:4", ("select_entrance", "4")),
        ("cat_yes", ("confirm_category", None)),
        ("cat_other", ("request_manual_category", None)),
        ("cat_pick:complaint", ("select_category", "complaint")),
        ("report_yes", ("confirm_report", None)),
        ("report_edit", ("request_report_correction", None)),
        ("phone_reuse_yes", ("confirm_saved_phone", None)),
        ("phone_reuse_other", ("request_new_phone", None)),
        ("new_report", ("start", True)),
        ("back_to_menu", ("start", True)),
        ("back_to_menu_status", ("process_text", "Статус заявки")),
    ]

    for index, (payload, expected) in enumerate(cases, start=1):
        before = len(poller._dialog_service.calls)  # type: ignore[attr-defined]
        await poller._handle_callback(
            {
                "callback": {
                    "callback_id": f"cb-{index}",
                    "payload": payload,
                    "user": {"user_id": 101, "name": "Tester"},
                },
                "message": {"recipient": {"chat_id": 202}},
            }
        )
        assert poller._dialog_service.calls[before] == expected  # type: ignore[attr-defined]


_BOT_IDENTITY = MaxBotIdentity(user_id=700, username="УКбот")


def _message_update(
    text: str,
    *,
    mid: str = "mid-1",
    chat_type: str = "chat",
    sender_id: int = 100,
    is_bot: bool = False,
    link: dict[str, object] | None = None,
    body_extra: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {"mid": mid, "text": text}
    body.update(body_extra or {})
    message: dict[str, object] = {
        "sender": {"user_id": sender_id, "is_bot": is_bot, "name": "Житель"},
        "recipient": {"chat_id": 200, "chat_type": chat_type},
        "body": body,
    }
    if link is not None:
        message["link"] = link
    return {"update_type": "message_created", "message": message}


def test_max_group_routing_decision_table() -> None:
    unaddressed = route_max_update(_message_update("У меня не работает домофон"), _BOT_IDENTITY)
    mentioned = route_max_update(_message_update("@УКбот не работает домофон"), _BOT_IDENTITY)
    command = route_max_update(_message_update("/домофон"), _BOT_IDENTITY)
    reply = route_max_update(
        _message_update(
            "дом 5, подъезд 2",
            link={"type": "reply", "sender": {"user_id": 700, "is_bot": True}},
        ),
        _BOT_IDENTITY,
    )
    other_mention = route_max_update(_message_update("@сосед не работает домофон"), _BOT_IDENTITY)
    bot_sender = route_max_update(
        _message_update("@УКбот привет", is_bot=True), _BOT_IDENTITY
    )
    channel = route_max_update(
        _message_update("/заявка", chat_type="channel"), _BOT_IDENTITY
    )
    forwarded_command = route_max_update(
        _message_update(
            "/домофон", link={"type": "forward", "sender": {"user_id": 300}}
        ),
        _BOT_IDENTITY,
    )

    assert (unaddressed.accepted, unaddressed.reason) == (
        False,
        "ignored_unaddressed_group_message",
    )
    assert (mentioned.accepted, mentioned.text) == (True, "не работает домофон")
    assert (command.reason, command.command) == ("accepted_command", "домофон")
    assert reply.reason == "accepted_reply"
    assert not other_mention.accepted
    assert bot_sender.reason == "ignored_bot_sender"
    assert channel.reason == "ignored_channel_message"
    assert forwarded_command.reason == "ignored_forwarded_message"


def test_max_dialog_structured_mention_callback_and_empty_input_routing() -> None:
    dialog = route_max_update(
        _message_update("У меня не работает домофон", chat_type="dialog"), _BOT_IDENTITY
    )
    dialog_command = route_max_update(
        _message_update("/вода", chat_type="dialog"), _BOT_IDENTITY
    )
    structured_mention = route_max_update(
        _message_update(
            "не работает домофон",
            body_extra={"mentions": [{"type": "mention", "user_id": 700}]},
        ),
        _BOT_IDENTITY,
    )
    empty_mention = route_max_update(_message_update("@УКбот"), _BOT_IDENTITY)
    attachment = route_max_update(
        _message_update("", body_extra={"attachments": [{"type": "image"}]}),
        _BOT_IDENTITY,
    )
    callback = route_max_update(
        {
            "update_type": "message_callback",
            "callback": {"callback_id": "cb-1", "user": {"user_id": 100}},
        },
        _BOT_IDENTITY,
    )
    edited = route_max_update({"update_type": "message_edited"}, _BOT_IDENTITY)

    assert (dialog.reason, dialog.text) == (
        "accepted_dialog",
        "У меня не работает домофон",
    )
    assert (dialog_command.reason, dialog_command.command) == ("accepted_command", "вода")
    assert structured_mention.reason == "accepted_mention"
    assert empty_mention.action == "help"
    assert not attachment.accepted
    assert callback.reason == "accepted_callback"
    assert edited.reason == "ignored_irrelevant_update"


class _RespondingDialogServiceStub(_DialogServiceStub):
    async def process_text(self, transport, text: str, from_voice: bool = False) -> None:
        _ = from_voice
        self.calls.append(("process_text", text))
        await transport.send_text("Ответ", None)

    async def start(self, transport, *, include_welcome: bool) -> None:
        self.active_dialog = True
        self.calls.append(("start", include_welcome))
        await transport.send_text("Начинаем заявку", None)


def _routing_poller() -> tuple[MaxPolling, _RespondingDialogServiceStub, _MaxClientStub]:
    settings = Settings(max_bot_token="token")
    services = SimpleNamespace(speech=SimpleNamespace(enabled=False))
    poller = MaxPolling(settings, services)  # type: ignore[arg-type]
    dialog = _RespondingDialogServiceStub()
    client = _MaxClientStub()
    poller._dialog_service = dialog  # type: ignore[assignment]
    poller._client = client  # type: ignore[assignment]
    poller._identity = _BOT_IDENTITY
    return poller, dialog, client


@pytest.mark.asyncio
async def test_max_polling_gate_blocks_group_chatter_before_dialog_and_llm() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("У меня не работает домофон"))
    assert dialog.calls == []
    assert client.sent_messages == []


@pytest.mark.asyncio
async def test_max_group_dialog_accepts_plain_text_after_request_started() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("/заявка", mid="mid-start"))

    await poller._handle_update(_message_update("42", mid="mid-apartment"))

    assert dialog.calls == [("start", False), ("process_text", "42")]
    assert len(client.sent_messages) == 2
    assert client.sent_messages[1]["reply_to_mid"] == "mid-apartment"


@pytest.mark.asyncio
async def test_max_active_group_dialog_is_scoped_to_initiating_user() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("/заявка", mid="mid-start"))

    await poller._handle_update(
        _message_update("сообщение другого участника", mid="mid-other", sender_id=101)
    )

    assert dialog.calls == [("start", False)]
    assert len(client.sent_messages) == 1


@pytest.mark.asyncio
async def test_max_mention_is_cleaned_and_response_replies_to_source() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("@УКбот не работает домофон"))
    assert dialog.calls == [("process_text", "не работает домофон")]
    assert len(client.sent_messages) == 1
    assert client.sent_messages[0]["reply_to_mid"] == "mid-1"


@pytest.mark.asyncio
async def test_max_duplicate_mid_produces_exactly_one_call_and_response() -> None:
    poller, dialog, client = _routing_poller()
    update = _message_update("@УКбот не работает домофон")
    await poller._handle_update(update)
    await poller._handle_update(update)
    assert len(dialog.calls) == 1
    assert len(client.sent_messages) == 1


@pytest.mark.asyncio
async def test_max_thematic_command_starts_seeded_scenario() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("/домофон"))
    assert dialog.calls == [("process_text", "Не работает домофон")]
    assert len(client.sent_messages) == 1


@pytest.mark.asyncio
async def test_max_empty_mention_sends_help_without_dialog_or_llm() -> None:
    poller, dialog, client = _routing_poller()
    await poller._handle_update(_message_update("@УКбот"))
    assert dialog.calls == []
    assert len(client.sent_messages) == 1
    assert "/помощь" in str(client.sent_messages[0]["text"])


@pytest.mark.asyncio
async def test_max_transport_coalesces_dialog_output_into_one_message() -> None:
    poller, _, client = _routing_poller()
    transport = poller._make_transport(200, 100, "Житель", reply_to_mid="mid-1")
    await transport.send_text("Первая часть", None)
    await transport.send_text("Вторая часть", [{"type": "inline_keyboard"}])
    await transport.flush()
    assert len(client.sent_messages) == 1
    assert client.sent_messages[0]["text"] == "Первая часть\n\nВторая часть"
    assert client.sent_messages[0]["reply_to_mid"] == "mid-1"


@pytest.mark.asyncio
async def test_max_client_encodes_reply_link() -> None:
    client = MaxBotClient(Settings(max_bot_token="token"))
    client._post = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]
    await client.send_message(200, "Ответ", reply_to_mid="mid-1")
    client._post.assert_awaited_once_with(
        "messages",
        params={"chat_id": 200},
        json={
            "text": "Ответ",
            "format": "markdown",
            "link": {"type": "reply", "mid": "mid-1"},
        },
    )

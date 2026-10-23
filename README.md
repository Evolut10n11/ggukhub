# Ассистент УК «Зелёный сад» (v0)

Telegram-бот для управляющей компании «Зелёный сад».
Принимает обращения жителей, классифицирует по категориям и создаёт заявки в Bitrix24.

## Справочник ЖК

Названия для выбора и распознавания загружаются из `data/housing_complexes.json` при запуске.
В меню «Еврокласс» доступны Быстрецкая, д.18, корпуса 1–4.
В меню «Гранд Комфорт» доступны «Гранд Комфорт - 1», «Гранд Комфорт - 2» и «Гранд Комфорт - 3».
Нумерованные названия распознаются и при вводе текстом, включая пробелы, тире и латинские варианты.
У «Еврокласс-4» и трёх объектов «Гранд Комфорт» количество подъездов и квартир пока не заполнено:
бот запрашивает их вручную. Объекты «Гранд Комфорт» идентифицируются по выбранному названию;
почтовые адреса для них пока не внесены.
После изменения справочника нужно перезапустить процесс бота.

## Стек

- Python 3.10+
- aiogram 3 (Telegram)
- FastAPI + uvicorn (API, webhooks)
- SQLAlchemy 2 + aiosqlite (SQLite)
- Bitrix24 REST API

## Быстрый старт

```bash
python -m venv venv
source venv/bin/activate   # Linux / macOS
venv\Scripts\activate      # Windows

pip install -r requirements.txt
cp .env.example .env
# Заполните TELEGRAM_BOT_TOKEN и BITRIX_WEBHOOK_URL
```

## Запуск

```bash
# API + Telegram polling в одном процессе
python -m app.run_stack

# Или по отдельности
python -m app.run_api    # только FastAPI
python -m app.run_bot    # только Telegram polling
```

С `uv`:
```bash
uv sync
uv run green-garden-stack
```

## Переменные окружения

См. `.env.example`. Основные:

| Переменная | Описание |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Токен бота |
| `BITRIX_WEBHOOK_URL` | URL вебхука Bitrix24 |
| `DATABASE_URL` | Строка подключения к БД (по умолчанию `sqlite:///./var/app.db`) |
| `SPEECH_ENABLED` | Включить распознавание голоса (`true` / `false`) |
| `TELEGRAM_USE_WEBHOOK` | Webhook-режим вместо polling (`true` / `false`) |

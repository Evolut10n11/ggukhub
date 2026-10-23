# Ассистент УК «Зелёный сад» (v0)

Telegram-бот для управляющей компании «Зелёный сад».
Принимает обращения жителей, классифицирует по категориям и создаёт заявки в Bitrix24.

## Справочник ЖК

Названия для выбора и распознавания загружаются из `data/housing_complexes.json` при запуске.
Справочник включает [«Еврокласс-4»](https://www.green-garden.ru/catalog/evroklass_4/),
[«Гранд Комфорт»](https://www.green-garden.ru/mos/catalog/zhukovsky/),
[«Гранд Комфорт-2»](https://www.green-garden.ru/mos/catalog/zhukovsky-2/) и
[«Гранд Комфорт-3»](https://www.green-garden.ru/mos/catalog/zhukovsky-3/).
Для этих ЖК список домов пока не заполнен: бот уточняет дом, подъезд и квартиру у жителя.
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

# Ассистент УК "Зелёный сад" (v0)

Текстовый ассистент для УК "Зелёный сад" на Python:
- Telegram-бот (`aiogram`)
- Backend API + webhook endpoints (`FastAPI`)
- Интеграция с Bitrix24 (создание/обновление заявок + приём событий)
- Детектор массовых обращений (15 минут / порог 5)
- Классификация категорий на основе правил (`RuleResponder`)

На v0 **нет** LLM/RAG/MCP/rerank/Langfuse.

## Структура
```text
.
├─ app
│  ├─ config
│  ├─ telegram
│  ├─ bitrix
│  ├─ core
│  ├─ incidents
│  ├─ responders
│  ├─ speech
│  ├─ main.py
│  ├─ run_api.py
│  ├─ run_bot.py
│  └─ run_stack.py
├─ data
│  ├─ housing_complexes.json
│  ├─ categories.json
│  └─ tariffs.json
├─ tests
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
└─ requirements-speech.txt
```

## Быстрый старт
1. Создайте окружение:
```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

Опциональные профили:
```bash
pip install -r requirements-speech.txt   # локальный faster-whisper (STT)
pip install -r requirements-dev.txt      # pytest
```

3. Настройте переменные:
```bash
cp .env.example .env
# заполните TELEGRAM_BOT_TOKEN и остальные переменные
```

4. Запустите:
```bash
# API + Telegram polling в одном процессе
python -m app.run_stack

# или по отдельности:
python -m app.run_api    # только FastAPI
python -m app.run_bot    # только Telegram polling
```

По умолчанию SQLite БД и lock-файл создаются в `var/` при первом запуске.

## Ubuntu + uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run green-garden-stack
```

Доступные entrypoint-ы:
```bash
uv run green-garden-api
uv run green-garden-bot
uv run green-garden-stack
```

`green-garden-stack` поднимает API и Telegram polling в одном процессе. Если `TELEGRAM_USE_WEBHOOK=true`, runner запускает только API, потому что webhook-бот уже обслуживается внутри FastAPI.

## Endpoints
- `GET /health` — healthcheck
- `POST /bitrix/webhook` — входящие события из Bitrix24
- `POST /telegram/webhook` — webhook для Telegram (если `TELEGRAM_USE_WEBHOOK=true`)
- `GET /reports/{report_id}/audit` — журнал формирования заявки

## Регламент заявки (аудит)
- При создании заявки бот сохраняет в БД паспорт формирования:
  - какие поля пришли из сессии (`jk`, `дом`, `подъезд`, `квартира`, `телефон`, `текст`)
  - как они нормализованы в итоговую заявку
  - итоговая категория и признак массового инцидента
- Записи лежат в таблице `report_audit_logs` с версией регламента `uk_zeleniy_sad_telegram_v1`.
- После попытки отправки в Bitrix24 добавляется запись:
  - `bitrix_synced` (успех)
  - `bitrix_sync_failed` (ошибка)

## Голос в Telegram
- Бот принимает голосовые сообщения и переводит их в текст.
- Для включения:
  - `SPEECH_ENABLED=true`
  - `SPEECH_BASE_URL=local://faster-whisper`
  - `SPEECH_MODEL=small`
  - `SPEECH_DEVICE=cpu`
  - `SPEECH_COMPUTE_TYPE=int8`
- Установка: `pip install -r requirements-speech.txt`
- Альтернатива через API: `SPEECH_BASE_URL=https://api.openai.com/v1`, `SPEECH_MODEL=gpt-4o-transcribe`, `SPEECH_API_KEY=<ключ>`.

## Ускорение отправки заявки
- Бот отвечает пользователю сразу после локальной регистрации, а отправка в Bitrix24 идёт в фоне.
- После успешной передачи бот присылает отдельное сообщение с номером Bitrix24.

## Тесты
```bash
pip install -r requirements-dev.txt
pytest -q
```

Через `uv`:
```bash
uv sync --extra dev
uv run pytest -q
```

Live-smoke с реальным Bitrix24 (опционально):
```bash
export RUN_BITRIX_LIVE_TESTS=1
pytest -q tests/test_bitrix_ticket_flow.py -k live
```

Покрыто:
- rule-based классификация категорий
- большая матрица классификации (494 кейса)
- детектор массовости (порог/окно)
- детектор фраз приветствия/прощания
- Bitrix24 интеграция (создание/обновление заявок)
- диалоговые сценарии (заполнение, валидация, подтверждение, коррекция)
- голосовые сообщения (STT)
- нагрузочный тест (20 параллельных пользователей)

# UK "Zelyony Sad" AI Assistant (v0 Skeleton)

Каркас текстового AI-ассистента для УК "Зелёный сад" на Python:
- Telegram-бот (`aiogram`)
- Backend API + webhook endpoints (`FastAPI`)
- Интеграция с Bitrix24 (создание/обновление заявок + прием событий)
- Детектор массовых обращений (15 минут / порог 5)
- Промпт-стиль "Заботливая поддержка" (RuleResponder + LLMResponder)

LLM-слой перестроен на:
- `pydantic-ai`
- `pydantic-ai-langfuse-extras` (model/prompt/tracing adapters)

На v0 **нет** RAG/MCP/rerank.

## Структура
```text
.
├─ app
│  ├─ config
│  ├─ telegram
│  ├─ bitrix
│  ├─ core
│  ├─ incidents
│  ├─ prompts
│  ├─ responders
│  ├─ main.py
│  └─ run_bot.py
├─ data
│  ├─ housing_complexes.json
│  ├─ categories.json
│  └─ tariffs.json
├─ tests
├─ .env.example
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ requirements-speech.txt
└─ requirements-llm.txt
```

## Быстрый старт (без Docker)
1. Создайте окружение:
```bash
python -m venv venv
```
или
```bash
uv venv
```

2. Активируйте окружение и установите базовые зависимости:
```bash
pip install -r requirements.txt
```

Опциональные профили:
```bash
pip install -r requirements-speech.txt   # local faster-whisper
pip install -r requirements-llm.txt      # Qwen / Langfuse / pydantic-ai
pip install -r requirements-dev.txt      # полный dev/test-профиль
```

Если хотите вести проект через `uv`, используйте:
```bash
uv sync
uv sync --extra speech
uv sync --extra llm
uv sync --extra dev
```

3. Настройте переменные:
```bash
cp .env.example .env
```

4. Для локальной разработки запустите API:
```bash
uvicorn app.main:app --reload
```

5. Для production используйте обычный запуск без `--reload`:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

6. Запустите Telegram-бота (polling):
```bash
python -m app.run_bot
```

7. Если нужен один процесс и одно окно для FastAPI + Telegram polling:
```bash
python -m app.run_stack
```

По умолчанию локальная SQLite БД и lock-файл создаются в каталоге `var/`, а не в корне проекта.

## Ubuntu + uv
Для сервера на Ubuntu можно идти через `uv` без ручного `pip`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
uv run green-garden-stack
```

Доступные entrypoint'ы:
```bash
uv run green-garden-api
uv run green-garden-bot
uv run green-garden-stack
```

`green-garden-stack` поднимает API и Telegram polling в одном процессе. Если `TELEGRAM_USE_WEBHOOK=true`, этот runner запускает только API, потому что webhook-бот уже обслуживается внутри FastAPI.

## LLM-профиль (обязательные репо `pydantic-ai` + `pydantic-ai-langfuse-extras`)
LLM-профиль требует Python `>=3.12` (ограничение `pydantic-ai-langfuse-extras`).

Установка:
```bash
pip install -r requirements-llm.txt
```

Если нет доступа к Gitea, можно ставить из локальных клонов:
```bash
pip install <path-to-local-clone>/pydantic-ai
pip install <path-to-local-clone>/pydantic-ai-langfuse-extras
```

## DSPy: автогенерация системного промпта
Если нужно сгенерировать системный промпт автоматически под текущую задачу:
```bash
pip install -r requirements-dspy.txt
python scripts/generate_system_prompt_dspy.py --output app/prompts/system.dspy.txt
```

Скрипт использует:
- `LLM_BASE_URL` (должен оканчиваться на `/v1`)
- `LLM_MODEL` (в проекте допускается `Qwen3.5-35B-A3B`)
- `LLM_API_KEY` (опционально для локального gateway)

## Langfuse: подтянуть reference-репозитории
Для обновления локальных репозиториев `pydantic-ai` и `pydantic-ai-langfuse-extras`:
```powershell
pwsh ./scripts/sync_langfuse_repos.ps1
```
По умолчанию они синхронизируются в `%USERPROFILE%\git`.

## Langfuse: синхронизация промпта из репозитория
Чтобы "привязать репозиторий" к Langfuse в рабочем процессе, синхронизируйте промпт напрямую из проекта:
```powershell
python scripts/sync_prompt_to_langfuse.py
```

Скрипт:
- берет `LANGFUSE_PROMPT_FILE` (по умолчанию `app/prompts/system.dspy.txt`);
- создает новую версию `LANGFUSE_PROMPT_NAME` с label `LANGFUSE_PROMPT_LABEL`;
- прикладывает git-метаданные (`branch/commit/remote/dirty`) в `config` prompt-версии;
- пропускает публикацию, если контент и commit не изменились.

## Endpoints
- `GET /health` — healthcheck
- `POST /bitrix/webhook` — входящие события из Bitrix24 (generic receiver + secret check + log)
- `POST /telegram/webhook` — webhook для Telegram (если `TELEGRAM_USE_WEBHOOK=true`)
- `GET /reports/{report_id}/audit` — журнал формирования заявки по регламенту (этапы `report_created`, `bitrix_synced|bitrix_sync_failed`)

## Регламент заявки (аудит)
- При создании заявки бот сохраняет в БД "паспорт формирования":
  - какие поля пришли из сессии (`jk`, `дом`, `подъезд`, `квартира`, `телефон`, `текст`)
  - как они нормализованы в итоговую заявку
  - итоговая категория и признак массового инцидента
- Записи лежат в таблице `report_audit_logs` с версией регламента `uk_zeleniy_sad_telegram_v1`.
- После попытки отправки в Bitrix24 добавляется отдельная запись:
  - `bitrix_synced` (успех)
  - `bitrix_sync_failed` (ошибка)

## LLM
- По умолчанию: `USE_LLM=false`, работает `RuleResponder`.
- LLM-режим разрешен только с моделью `Qwen3.5-35B-A3B`.
- `LLM_BASE_URL` нужно задать явно, например `http://localhost:8080/v1` или URL вашего OpenAI-compatible gateway.
- Лимит ответа модели: `LLM_MAX_TOKENS=12288` (можно поднять выше при необходимости).
- Размер few-shot контекста: `LLM_FEW_SHOT_LIMIT=20` (по умолчанию берутся все доступные примеры).
- При заполнении `LANGFUSE_*` включается tracing через `pydantic-ai-langfuse-extras`.
- В LLMResponder включен оркестраторный режим: `uk_orchestrator_agent` вызывает tool `compose_confirmation`, после чего работает `uk_writer_agent`. Это дает более читаемое дерево трасс в Langfuse.

## Голос в Telegram
- Бот умеет принимать `voice`-сообщения и переводить их в текст перед обычной обработкой диалога.
- Для включения выставьте:
  - `SPEECH_ENABLED=true`
  - `SPEECH_BASE_URL=local://faster-whisper`
  - `SPEECH_MODEL=small`
  - `SPEECH_DEVICE=cpu`
  - `SPEECH_COMPUTE_TYPE=int8`
- После распознавания бот отправляет пользователю текст и продолжает сценарий заявки.
- Установка локального STT: `pip install -r requirements-speech.txt`
- Альтернатива через API: можно задать `SPEECH_BASE_URL=https://api.openai.com/v1`, `SPEECH_MODEL=gpt-4o-transcribe`, `SPEECH_API_KEY=<key>`.

## Ускорение отправки заявки
- Бот отвечает пользователю сразу после локальной регистрации заявки, а отправка в Bitrix24 идет в фоне.
- После успешной передачи бот присылает отдельное сообщение с номером Bitrix24.
- Для более быстрого LLM-ответа уменьшите `LLM_MAX_TOKENS` до `256-512` и `LLM_FEW_SHOT_LIMIT` до `4-8`.

## Тесты
Полный прогон тестов требует `pip install -r requirements-dev.txt`.

```bash
pytest -q
```

Через `uv`:
```bash
uv sync --extra dev
uv run pytest -q
```

Qwen-тесты:
```bash
pytest -q tests/test_llm_responder_qwen.py
```

Bitrix-тесты (формирование payload + e2e сохранение `bitrix_id`):
```bash
pytest -q tests/test_bitrix_ticket_flow.py -k "not live"
```

Live-smoke с реальным Qwen (опционально):
```bash
set QWEN_TEST_BASE_URL=http://localhost:8080/v1
set RUN_QWEN_LIVE_TESTS=1
pytest -q tests/test_llm_responder_qwen.py -k live
```

Live-smoke с Langfuse (опционально):
```bash
set QWEN_TEST_BASE_URL=http://localhost:8080/v1
set RUN_LANGFUSE_LIVE_TESTS=1
pytest -q tests/test_langfuse_live.py
```

Live-smoke с реальным Bitrix24 (опционально, создаст реальную тестовую заявку):
```bash
set RUN_BITRIX_LIVE_TESTS=1
pytest -q tests/test_bitrix_ticket_flow.py -k live
```

Набор из 10 live-сценариев Langfuse:
```bash
set QWEN_TEST_BASE_URL=http://localhost:8080/v1
set RUN_LANGFUSE_LIVE_TESTS=1
pytest -q -s tests/test_langfuse_10_scenarios_live.py
```

Покрыто:
- rule-based классификация категорий
- большая матрица классификации (494 кейса по категориям и реальным формулировкам)
- детектор массовости (порог/окно)
- детектор фраз приветствия/прощания

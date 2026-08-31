# Graph Report - green-garden-uk-assistant-v0  (2026-08-31)

## Corpus Check
- 74 files · ~22,050 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 670 nodes · 2149 edges · 29 communities (28 shown, 1 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 184 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `774ff261`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- dialog/service.py
- Storage
- DialogService
- bitrix/service.py
- AppServices
- run_stack.py
- HouseInfo
- MaxPolling
- finalization.py
- bootstrap.py
- core/services.py
- BitrixApiClient
- MaxBotClient
- SpeechToTextClient
- SpikeDetector
- KeyboardFactory
- DialogRuntimeState
- RuleResponder
- Ассистент УК «Зелёный сад» (v0)
- green-garden-uk-assistant

## God Nodes (most connected - your core abstractions)
1. `DialogService` - 69 edges
2. `Storage` - 61 edges
3. `AppServices` - 57 edges
4. `BitrixTicketService` - 48 edges
5. `DialogSessionData` - 47 edges
6. `DialogTransport` - 46 edges
7. `User` - 41 edges
8. `Report` - 29 edges
9. `DialogReportFinalizer` - 26 edges
10. `ExtractedReportContext` - 26 edges

## Surprising Connections (you probably didn't know these)
- `BitrixTicketService` --uses--> `BitrixClientError`  [INFERRED]
  app/bitrix/service.py → app/bitrix/client.py
- `BitrixWebhookService` --uses--> `BitrixClientError`  [INFERRED]
  app/bitrix/service.py → app/bitrix/client.py
- `DialogConfirmationResult` --uses--> `BitrixClientError`  [INFERRED]
  app/telegram/dialog/finalization.py → app/bitrix/client.py
- `DialogReportFinalizationResult` --uses--> `BitrixClientError`  [INFERRED]
  app/telegram/dialog/finalization.py → app/bitrix/client.py
- `DialogReportFinalizer` --uses--> `BitrixClientError`  [INFERRED]
  app/telegram/dialog/finalization.py → app/bitrix/client.py

## Import Cycles
- None detected.

## Communities (29 total, 1 thin omitted)

### Community 0 - "dialog/service.py"
Cohesion: 0.06
Nodes (62): CategoryClassifier, Path, report_status_label(), Path, compose_scope_key(), load_json(), normalize_phone(), normalize_text() (+54 more)

### Community 1 - "Storage"
Cohesion: 0.07
Nodes (29): BitrixSyncStatus, IncidentStatus, is_active_report_status(), Enum, str, ReportAuditStage, ReportStatus, Base (+21 more)

### Community 2 - "DialogService"
Cohesion: 0.14
Nodes (9): User, DialogSessionData, DialogTransport, Any, BaseModel, DialogService, Any, Try to match extracted house number to a full address in the registry. (+1 more)

### Community 3 - "bitrix/service.py"
Cohesion: 0.10
Nodes (35): build_ticket_description(), build_ticket_title(), BitrixCommentPayloadInput, BitrixContactPayloadInput, BitrixLeadContactLinkInput, BitrixLeadGetPayloadInput, BitrixLeadInfo, BitrixNotifyPayloadInput (+27 more)

### Community 4 - "AppServices"
Cohesion: 0.14
Nodes (45): AppServices, _ack_callback(), address_reuse_no_handler(), address_reuse_yes_handler(), back_to_menu_handler(), back_to_menu_status_handler(), callback_fallback_handler(), _callback_message() (+37 more)

### Community 5 - "run_stack.py"
Cohesion: 0.11
Nodes (33): configure_logging(), _is_process_alive(), process_lock(), Path, AppRuntime, create_app_runtime(), _bind_runtime(), _check_body_size() (+25 more)

### Community 6 - "HouseInfo"
Cohesion: 0.12
Nodes (18): HouseInfo, _cb_button(), _display_name(), _inline_keyboard_attachment(), MaxKeyboardFactory, Any, Wrap button rows into MAX inline_keyboard attachment., Builds MAX inline_keyboard attachments matching KeyboardFactory protocol. (+10 more)

### Community 7 - "MaxPolling"
Cohesion: 0.14
Nodes (21): _BufferedMaxTransport, MaxPolling, Any, Handle 'bot_started' event — user pressed Start or opened chat for first time., Collect all dialog output and emit one MAX message for one input event., Long-polling loop for MAX Bot API., _extract_current_bot_mention(), _has_structured_mention() (+13 more)

### Community 8 - "finalization.py"
Cohesion: 0.17
Nodes (16): build_bitrix_audit_payload(), build_report_composition_payload(), Any, ReportCreate, build_address(), DialogConfirmationResult, DialogReportFinalizationResult, DialogReportFinalizer (+8 more)

### Community 9 - "bootstrap.py"
Cohesion: 0.13
Nodes (11): get_settings(), Settings, build_runtime(), build_engine_kwargs(), create_database_runtime(), DatabaseRuntime, ensure_database_parent_dir(), Path (+3 more)

### Community 10 - "core/services.py"
Cohesion: 0.13
Nodes (14): BitrixWebhookService, build_services(), async_sessionmaker, AsyncSession, BuildingRegistry, ComplexInfo, ManagementCompanyInfo, Path (+6 more)

### Community 11 - "BitrixApiClient"
Cohesion: 0.17
Nodes (11): BitrixApiClient, BitrixApiResponseError, BitrixClientError, BitrixConfigurationError, BitrixHttpStatusError, BitrixResponseFormatError, BitrixTransportError, Any (+3 more)

### Community 12 - "MaxBotClient"
Cohesion: 0.19
Nodes (8): MaxApiError, MaxBotClient, Any, AsyncClient, RuntimeError, Thin HTTP client for MAX Bot API (platform-api2.max.ru)., Get download URL for a file attachment., Response

### Community 13 - "SpeechToTextClient"
Cohesion: 0.21
Nodes (6): Any, AsyncBaseTransport, RuntimeError, Pre-load the local Whisper model at startup to avoid cold-start delay., SpeechToTextClient, SpeechToTextError

### Community 14 - "SpikeDetector"
Cohesion: 0.25
Nodes (4): datetime, SpikeDetector, IncidentDecision, IncidentService

### Community 15 - "KeyboardFactory"
Cohesion: 0.27
Nodes (3): KeyboardFactory, Any, Protocol

### Community 16 - "DialogRuntimeState"
Cohesion: 0.19
Nodes (5): DialogRuntimeState, Any, Lock, Task, WeakValueDictionary

### Community 17 - "RuleResponder"
Cohesion: 0.31
Nodes (5): FlowTelemetry, Any, start_flow_telemetry(), GeneratedResponse, RuleResponder

### Community 18 - "Ассистент УК «Зелёный сад» (v0)"
Cohesion: 0.33
Nodes (5): Ассистент УК «Зелёный сад» (v0), Быстрый старт, Запуск, Переменные окружения, Стек

## Knowledge Gaps
- **5 isolated node(s):** `green-garden-uk-assistant`, `Стек`, `Быстрый старт`, `Запуск`, `Переменные окружения`
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppServices` connect `AppServices` to `dialog/service.py`, `Storage`, `DialogService`, `bitrix/service.py`, `run_stack.py`, `MaxPolling`, `bootstrap.py`, `core/services.py`, `BitrixApiClient`, `RuleResponder`?**
  _High betweenness centrality (0.208) - this node is a cross-community bridge._
- **Why does `DialogService` connect `DialogService` to `dialog/service.py`, `Storage`, `AppServices`, `HouseInfo`, `MaxPolling`, `finalization.py`, `core/services.py`, `KeyboardFactory`?**
  _High betweenness centrality (0.113) - this node is a cross-community bridge._
- **Why does `Storage` connect `Storage` to `dialog/service.py`, `bitrix/service.py`, `AppServices`, `finalization.py`, `bootstrap.py`, `core/services.py`, `SpikeDetector`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `DialogService` (e.g. with `BuildingRegistry` and `HouseInfo`) actually correct?**
  _`DialogService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `Storage` (e.g. with `BitrixTicketService` and `BitrixWebhookService`) actually correct?**
  _`Storage` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `AppServices` (e.g. with `AppRuntime` and `BitrixApiClient`) actually correct?**
  _`AppServices` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `BitrixTicketService` (e.g. with `BitrixApiClient` and `BitrixClientError`) actually correct?**
  _`BitrixTicketService` has 23 INFERRED edges - model-reasoned connections that need verification._
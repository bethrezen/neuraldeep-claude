# Архитектура NeuralDeep для Claude Code

Полное описание того, как устроен проект, что делает каждый компонент и как данные проходят через систему.

## Общая схема

```
[Клиент] → [Claude CLI / Desktop]
                ↓ (OpenAI-compatible API)
        [Local Gateway:8787]
                ↓ (прямой HTTPS, без прокси)
    ┌───────────┴───────────┐
    │                       │
[NeuralDeep API]   [MCP Services]
(model routing)    (search/images/music/...)
```

## Компоненты

### 1. Gateway (neuraldeep_claude/gateway.py)

Локальный HTTP-сервер на `127.0.0.1:8787`. Это основной шлюз, который перенаправляет запросы Claude в NeuralDeep.

**Что делает:**

| Функция | Описание |
|---------|----------|
| **Прокси /v1/messages** | Переводит OpenAI-format запросы в формат NeuralDeep, отправляет upstream, возвращает SSE-ответы обратно клиенту |
| **Прокси /v1/models** | Обёртка над каталогом NeuralDeep, добавляет информацию о биллинге, effort и 1M window для UI |
| **Token count** | Приблизительный подсчёт токенов (NeuralDeep не публикует tokenizer endpoint) |
| **Заголовки ответа** | Кастомные заголовки: x-window, x-wallet, x-quota-reset, x-neuraldeep-token-count |
| **Shutdown endpoint** | Безопасная остановка при перезапуске (проверяет active requests) |

**Особенности реализации:**

- `ThreadingHTTPServer` — обработка каждого запроса в отдельном потоке
- `ping_thread` — keep</think>-alive каждые 15 секунд во время стриминга (SSE ping события)
- Семафоры по биллингу (`subscription`/`wallet`) — ограничивают параллельность до announced limits провайдера. Без произвольного уменьшения.
- Cancellation propagation — разрыв клиентского соединения отменяет upstream-запрос через shutdown сокета
- Redaction ключей — все ошибки redact'ят ключи подписки и кошелька перед выводом в лог

**Аутентификация клиента:** проверяет либо `X-API-Key`, либо `Authorization: Bearer <token>`; токен генерируется случайно при установке (8 символов), хранится только локально.

### 2. Protocol (neuraldeep_claude/protocol.py)

Мост форматов между OpenAI Messages API и NeuralDeep.

| Действие | Что происходит |
|----------|---------------|
| `to_openai()` | Конвертирует тело запроса Claude в формат, принимаемый NeuralDeep. Преобразует role system/user/assistant, инструменты, effort/thinking параметры (Qwen `enable_thinking`, Kimi `thinking.keep`, GLM `clear_thinking`, DeepSeek `thinking.type`) |
| `from_openai()` | Обратная конвертация ответа NeuralDeep в формат Claude (response.format.Message) |
| `stream_openai()` | Генерация SSE событий для стриминговых ответов: delta events, tool_use, message_delta, message_stop |

### 3. Catalog (neuraldeep_claude/catalog.py)

Хранение и маршрутизация моделей.

```
.v1/models + /v1/limits (NeuralDeep)
    ↓
.catalog.json (локальный кэш)
    ├── Модель: id, name, upstream_id, billing (subscription/wallet)
    ├── Limits: parallel_limit по каждому billing mode
    ├── Picker policy (config/picker-policy.json)
    └── Effort mapping (config/family-capabilities.json)
```

**resolve()** — преобразует имя модели из любого формата (клиентский, Native, alias, suffix) в canonical upstream ID.

**discovery_data()** — формирует ответ `/v1/models` для Claude Code, показывая доступные комбинации model × billing.

### 4. Services (neuraldeep_claude/services.py)

Система модульных MCP-сервисов. Каждый сервис — это независимый stdio MCP процесс.

**Группы сервисов:**

| Группа | Инструменты | Назначение |
|--------|------------|-------------|
| search | web_search, read_page, crawl_site, telegram_search | Поиск по вебу, чтение страниц, Telegram |
| ocr | ocr_extract, ocr_status, ocr_result, ocr_balance | Асинхронный OCR PDF/изображений |
| images | image_generate, image_edit, image_upscale, image_enhance... | Генерация и редактирование изображений |
| music | music_generate, music_status, music_result | Генерация музыки Lyria 3 Pro |
| tts | speak, voices | Text-to-Speech (Qwen3-TTS, ESpeech для русского) |
| transcription | transcribe | Распознавание речи (Whisper, Podlodka Turbo, GigaAmV3) |
| diarization | diarize | Разделение спикеров в аудио |
| embeddings | embed | Векторизация текста |
| rerank | rerank | Ранжирование документов (bge-reranker, Qwen3-Reranker) |
| pii | anonymize, deanonymize | Анонимизация персональных данных |
| decisions | decide | Классификация/ранжирование без генерации текста |
| drift | drift_ask, drift_conversations... | AI-агент Drift (отдельный токен dft_*) |
| book | book_list, book_toc, book_chapter... | Книжная библиотека агентов |
| speechcore | speechcore_upload, speechcore_*... | Длинная транскрипция до 2GB |
| browser | Playwright MCP | Независимый браузерный MCP (72 инструмента, без Cloud) |

**Управление сервисами:**

- Конфигурация `.local/services.json` — список включённых групп
- Конфигурация `.local/service-tools.json` — per-operation переключатели
- `config/service-policy.json` — умолчания по умолчанию (например, avatar disabled по выбору пользователя после тестовой ошибки)

Каждый service group запускается как отдельный subprocess с stdin/stdout MCP JSON-RPC интерфейсом.

### 5. CLI Launcher (neuraldeep_claude/cli.py, scripts/nd.py)

Интерфейс командной строки для управления проектом.

**Команды nd.py:**

```bash
python3 scripts/nd.py install --activate    # Установка и активация
python3 scripts/nd.py launch               # Запуск gateway + CLI
python3 scripts/nd.py desktop launch       # Запуск gateway + Desktop
python3 scripts/nd.py services list        # Список сервисов
python3 scripts/nd.py services enable/disable <names>
python3 scripts/nd.py services probe       # Read-only проверка сервисов
python3 scripts/nd.py services smoke --execute  # Полное тестирование
python3 scripts/nd.py models update        # Обновить каталог моделей
python3 scripts/nd.py restart              # Перезапуск gateway
```

### 6. Config System (neuraldeep_claude/config.py)

Хранение конфигурации:

| Файл | Назначение |
|------|-----------|
| `.env` | API ключи, опциональные токены (единственное место для секретов) |
| `.local/token.json` | Локальный токен аутентификации gateway (генерируется автоматически) |
| `.local/services.json` | Активные сервисы |
| `.local/model-overrides.json` | Ручные переопределения моделей |
| `.local/pricing-fx.json` | Курс USD/RUB ЦБ с датой и источником |
| `.local/desktop-pricing.json` | Native pricing для Desktop |
| `.local/backups/` | Копии оригинальных настроек Claude |

### 7. Title Helpers (neuraldeep_claude/title_helpers.py)

Генерация коротких названий сессий Desktop с помощью нейросети.

| Шаблон | Описание |
|--------|----------|
| coding session | На основе diff/коммит сообщения для coding сессий |
| generic session | На основе контекста для остальных |
| git branch name | Красивое название ветки |

Использует helper-модель из `config/helper-models.json` (по умолчанию Qwen 3.6 35B noreason по подписке).

### 8. Desktop Integration (neuraldeep_claude/desktop.py, desktop_runtime.py)

Интеграция с Claude Desktop:

| Параметр Desktop | Значение | Почему |
|------------------|----------|-------|
| Model discovery | Включён | Читает `/v1/models` gateway; отсутствие `inferenceModels` prevents accidental allowlist |
| Tool search | force | Нативный client-side ToolSearch поддерживается адаптером |
| Allow built-in browser | Enabled | Local-browser MCP с 72 инструментами |
| Advanced file analysis | Включён | Требуется VM, проверено отдельно |
| Cost display | Enabled | Wallet тарифы RUB → USD через курс ЦБ; subscription = $0 extra tokens |
| Sandbox | Disabled | `allowUnsandboxedCommands=true` |
| Electron sandbox | Отключён | `--no-sandbox` launcher flag |
| Auto updates | Сохранён | Обычный updater работает; Linux обновляется системным менеджером пакетов |
| Essential telemetry | Отключён | Отдельный от nonessential |
| Nonessential telemetry | Отключён | Но disableNonessentialServices=false сохраняет иконки коннекторов |

**Desktop Runtime** — проверяет integrity engine (checksum/raw payload), сравнивает со standalone CLI версии, пишет status в receipt.

### 9. Egress Monitor (neuraldeep_claude/egress.py)

Отслеживание исходящих соединений. Журнал сохраняется в `.local/egress-events.jsonl`. Логгируются: endpoint, method, billing_mode, response_code.

### 10. Transport (neuraldeep_claude/transport.py)

Низкоуровневый HTTP-транспорт:

- `ProxyHandler({})` — явное отключение всех прокси окружения (http_proxy, https_proxy, no_proxy игнорируются)
- `_NoRedirect` handler — запрещает редиректы (предотвращает утечку credentials)
- Timeout per request: обычно 300 сек для сервисов, 1800 сек для upload/Drift
- Retry logic: отсутствует (как задумано — no automatic fallback or retry of chargeable requests)

## Жизненный цикл запроса

```
1. Claude Code/Desktop отправляет POST /v1/messages
   ├─ Авторизация: X-API-Key == local_token
   └─ Content-Length <= 256MB

2. Gateway получает запрос
   ├─ Match title templates? → routing через helper_model
   ├─ resolve() → canonical upstream model ID
   ├─ Проверка semaphores по billing mode
   └─ Создаёт RequestCancellation

3. Превращение в upstream
   ├─ to_openai(body, model, upstream_id)
   │  ├─ role mappings
   │  ├─ tool call format conversion
   │  └─ reasoning params (effort/thinking by family)
   └─ Sends POST /v1/chat/completions to api.neuraldeep.ru

4. Получение ответа
   ├─ Streaming (SSE): sse_chunks() → stream_openai() → write_event() → SSE ping loop
   └─ Non-streaming: json.load() → from_openai() → send_json(200)

5. Уведомление об окончании
   ├─ message_delta → metric event
   └─ message_stop → release semaphore, decrement active_requests
```

## Структура файлов

```
neuraldeep-claude/
├── .env                        # Секреты (НЕ коммитить)
├── .env.example                # Шаблон для копирования
├── .gitignore                  # Исключает .env, .local/ (кроме .gitkeep)
│
├── neuraldeep_claude/          # Основной код (Python package)
│   ├── __init__.py
│   ├── __main__.py             # Entry point: python -m neuraldeep_claude
│   ├── cli.py                  # main() for CLI commands
│   ├── config.py               # Dotenv loader, atomic writes, key management
│   ├── catalog.py              # Model catalog cache & routing
│   ├── protocol.py             # OpenAI ↔ NeuralDeep translation
│   ├── gateway.py              # ThreadingHTTPServer at :8787
│   ├── services.py             # MCP service adapters + probe/smoke
│   ├── transport.py            # Low-level HTTP with proxy bypass
│   ├── title_helpers.py        # Session title generation
│   ├── desktop.py              # Desktop config management
│   ├── desktop_runtime.py      # Engine version/integrity check
│   ├── egress.py               # Outbound connection monitoring
│   ├── helper_models.py        # Helper model routing (classifier, titles)
│   ├── local_browser.py        # Playwright MCP integration
│   ├── pricing.py              # Currency conversion for Desktop UI
│   └── skills.py               # Skill injection into profiles
│
├── config/                     # Дефолтная конфигурация
│   ├── family-capabilities.json   # Effort mapping by model family
│   ├── helper-models.json         # Classifier + title helper model IDs
│   ├── model-overrides.json       # User manual overrides
│   ├── picker-policy.json         # Which models appear in picker
│   └── service-policy.json        # Default enabled/disabled tools
│
├── dist/                       # Портативный ZIP-архив
│   └── neuraldeep-claude-portable.zip
│
├── docs/                       # Документация
│   ├── BROWSER.md               # Browser MCP details
│   ├── EFFORT.md                # Effort/resolution mapping reference
│   ├── NETWORK-POLICY.md        # How networking/proxy settings work
│   ├── SERVICES.md              # Service configuration guide
│   ├── VALIDATION-*.md          # Validation results
│   └── research-*.md            # Research notes
│
├── scripts/                    # Утилиты
│   ├── nd.py                    # Main installer/launcher script
│   ├── probe-claude.py          # Claude protocol smoke tests
│   ├── probe-models.py          # Model probing script
│   ├── probe-desktop.py         # Desktop feature probes
│   ├── probe-desktop-session.py # Desktop session execution test
│   ├── probe-effort.py          # Effort level validation
│   ├── probe-offline.py         # Offline help text extraction
│   ├── package.py               # Portable ZIP builder
│   └── audit-effort.py          # Effort profile auditing
│
├── tests/                      # Unit tests
│   ├── test_core.py
│   ├── test_gateway.py
│   ├── test_catalog_metadata.py
│   ├── test_helper_models.py
│   ├── test_effort.py
│   ├── test_pricing.py
│   ├── test_services.py
│   └── ... (другие modle testing files)
│
├── install.sh                  # Linux/macOS installer wrapper
├── install.ps1                 # Windows PowerShell installer
├── update-models.sh            # Model catalog update (Linux)
├── update-models.ps1           # Model catalog update (Windows)
├── pyproject.toml              # Package metadata (setuptools)
└── README.md                   # Быстрый старт и overview
```

## Точка входа

```
python3 scripts/nd.py install --activate     # Installer
python3 scripts/nd.py launch                  # Starts gateway + CLI
python3 -m neuraldeep_claude                  # Direct gateway start
python3 neuraldeep_claude/services.py mcp <group>  # Standalone MCP server
```

## Безопасность

| Механизм | Где применяется |
|----------|-----------------|
| API keys в одном файле | Только `.env`, never persisted in logs |
| Token redaction | Ошибки и логи красят ключи через `_redact()` |
| No proxy | `ProxyHandler({})`, `_NoRedirect` handler |
| Local-only binding | Gateway слушает только 127.0.0.1:8787 |
| Atomic JSON writes | Temp file + replace pattern предотвращает race conditions |
| Private data flag | `atomic_json(root, data, private=True)` не включает в ZIP |

## Обновление

Шлюз обновляется вместе с обновлением кода проекта. Launcher проверяет gateway через hook перед каждым запуском. Каталог моделей можно обновлять вручную через `update-models.sh` или `nd.py models update`.

Обычный CLI сохранён и может обновляться системным менеджером пакетов (Linux) или встроенным updater'ом (Windows/macOS).

# NeuralDeep для Claude Code

**Локальный шлюз**, который подключает все модели и сервисы [NeuralDeep](https://neuraldeep.ru) к **Claude Code** (CLI) и **Claude Desktop**.

## Что это даёт

| Возможности | Описание |
|---|---|
| 🤖 Все модели NeuralDeep | Qwen 3.8, GPT-OSS, DeepSeek V4, GLM 5.3, Kimi K3, Claude 5.5 и другие — в одном интерфейсе |
| 💰 Две оплаты | Подписка (фиксированная) и кошелёк (оплата за токены) |
| 🔧 Модульные сервисы | Поиск, OCR, изображения, музыка, TTS, транскрипция, эмбеддинги, Rerank, PII, Drift — включайте что нужно |
| 🌐 Без прокси | Прямое подключение к API NeuralDeep, окружение игнорируется |
| 📦 Переносимость | Работает на Linux, Windows, macOS; не требует глобальной установки |

## Быстрый старт

### Шаг 1. Зависимости

```bash
# Python 3.10+ — обязательно
python3 --version

# Node.js 18+ — только если нужен браузерный MCP Playwright
node --version
```

### Шаг 2. Получите ключи NeuralDeep

Регистрация на [neuraldeep.ru](https://neuraldeep.ru). Ключи найдутся в личном кабинете:

- **API Key (Subscription)** — для моделей по подписке
- **Wallet Key** — для моделей с оплатой за токены

### Шаг 3. Скопируйте проект

```bash
git clone https://github.com/YOUR_USERNAME/neuraldeep-claude.git
cd neuraldeep-claude
```

Или просто скопируйте папку на другой компьютер.

### Шаг 4. Настройте ключи

```bash
cp .env.example .env
```

Откройте `.env` и вставьте свои ключи:

```dotenv
NEURALDEEP_API_KEY_SUBSCRIPTION=ваш_ключ_подписки_начинается_с_nds_...
NEURALDEEP_API_KEY_WALLET=ваш_ключ_кошелька_начинается_с_ndw_...
```

Опционально (для Drift):

```dotenv
NEURALDEEP_DRIFT_TOKEN=dft_ваш_токен_drift
```

### Шаг 5. Активируйте

```bash
./install.sh --activate
```

Если PowerShell заблокирован на Windows:

```powershell
py -3 scripts/nd.py install --activate
```

> `--activate` сохраняет копию оригинальной настройки Claude Code и переключает её на NeuralDeep Gateway. Флаг без значения создаёт launcher и навыки, но не переключает основную конфигурацию.

## Использование

### Claude Code CLI

Всё как обычно — `claude`. Просто работает через NeuralDeep:

```bash
claude "Помоги написать код"

# Явный выбор модели:
claude /model          # открыть пикер моделей

# Обновить каталог моделей:
./update-models.sh
```

### NeuralDeep Launcher

Отдельная команда для явного управления:

```bash
# Обычный запуск через gateway
python3 scripts/nd.py launch

# С конкретной моделью
python3 scripts/nd.py launch --model qwen3.8-27b

# По кошельку
python3 scripts/nd.py launch --model gpt-oss-120b@wallet

# В Desktop
python3 scripts/nd.py desktop launch
```

### Сервисы NeuralDeep

Управление модульными сервисами:

```bash
# Список сервисов
python3 scripts/nd.py services list

# Включить / выключить
python3 scripts/nd.py services disable music images
python3 scripts/nd.py services enable all

# Проверка доступности
python3 scripts/nd.py services probe

# Полное тестирование (тратит квоты!)
python3 scripts/nd.py services smoke --groups all --execute
```

## Архитектура

```
┌──────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Claude Code │ ◄──────►│  Local Gateway   │────────►│  NeuralDeep API │
│  / Desktop   │  OpenAI  │  127.0.0.1:8787  │  Direct │  api.neuraldeep.ru│
└──────────────┘ Protocol │                  │         └─────────────────┘
                           │  MCP Services    │────────►
                           │  (search,images, │         ┌─────────────────┐
                           │   music,...)     │────────►│  Other Neura…    │
                           └──────────────────┘         └─────────────────┘
```

Шлюз переводит запросы Claude в формат NeuralDeep, маршрутизирует по моделям и биллингу, управляет effort/thinking, генерирует короткие заголовки сессий — всё локально, без сторонних зависимостей.

Полная архитектура: [ARCHITECTURE.md](ARCHITECTURE.md)

## Установка

| ОС | Требования | Команда |
|----|-----------|---------|
| Linux/macOS | Python 3.10+, Node.js 18+ | `./install.sh --activate` |
| Windows | Python 3.10+, Node.js 18+ | `.\install.ps1 --activate` |
| Любая ОС | Только Python 3.10+ | `python3 scripts/nd.py install --activate` |

Launcher создаётся в `.local/bin/` (Linux/macOS) или `%LOCALAPPDATA%\NeuralDeep\bin\` (Windows). Можно добавить в PATH.

## Важные детали

- **Ключи только в одном `.env`** — нигде больше не хранятся
- **Sandbox отключён** — команды выполняются без ограничений папок
- **Effort**: `/effort low|medium|high|xhigh|max` работает штатно
- **Модели**: список обновляется автоматически, есть ручной `update-models.sh`
- **Desktop**: графический effort для регулируемых моделей, список из каталога NeuralDeep обновляется скриптом. Tool Search, браузер и тарифы включены

## Диагностика

```bash
# Шлюз
curl http://127.0.0.1:8787/health

# Логи шлюза
cat .local/gateway.log

# Каталог моделей
python3 scripts/nd.py models list
python3 scripts/nd.py models show qwen3.8-27b
```

## Безопасность

- Прокси окружения отключены на уровне транспорта
- Ключи redacted в логах и ошибках
- Токен шлюза — случайный 8-символьный, не является ключом NeuralDeep
- Локальный адрес только (127.0.0.1), снаружи недоступен

## Лицензия

Проект распространяется «как есть». Используйте на свой риск.

## Вопросы?

См. полные документы:
- [Архитектура](ARCHITECTURE.md) — как всё работает внутри
- [Браузер](docs/BROWSER.md) — Playwright MCP
- Effort/Thinking: [EFFORT.md](docs/EFFORT.md)
- Сервисы: [SERVICES.md](docs/SERVICES.md)
- Политика сети: [NETWORK-POLICY.md](docs/NETWORK-POLICY.md)

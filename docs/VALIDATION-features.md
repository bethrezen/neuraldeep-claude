# Дополнение: полноценный Desktop Code и новый picker

Текущее изменение: Desktop штатно установил engine 2.1.309. Первая полноценная Code-сессия через NeuralDeep выполнила исправление файла, неизменённые тесты, read-only MCP и двух параллельных субагентов, но получила статус `PASS_WITH_AUTO_CLASSIFIER_TIMEOUTS`. Это не чистое подтверждение стабильности Auto. Текущий отдельный классификатор — `qwen3.6-35b-a3b-noreason` по подписке: его отдельная проверка в native engine и последующая focused-проверка в настоящем Desktop прошли. Во второй проверке получены native classifier accepts у Agent, SubagentHandback и Bash, два реальных теста OK, ноль safety warnings и финальный `DESKTOP_CLASSIFIER_OK 5050`; четыре classifier-запроса заняли 1,12–3,96 секунды. Permission checks сохранены. Источник и границы проверки: [VALIDATION-desktop-session.md](VALIDATION-desktop-session.md).

По отдельному выбору пользователя включён `desktop_title_model=nd/qwen3.6-35b-a3b-noreason@subscription`. Gateway узнаёт только два полных native title-шаблона Desktop 4.4212.0; обычный Code, explicit effort и неизвестные формы остаются на исходной модели. Wallet fallback отсутствует. `null` отключает правило на следующих совпавших вызовах без перезапуска Desktop, в отличие от настройки Auto classifier. Живые exact coding/generic title-запросы с искусственными описаниями прошли за 0,587/4,487 с, по одной попытке, внутри native 15 с: `.local/title-helper-validation/20261103T062835785874Z/review.json`. Новый полный Desktop run ещё не завершён; этот результат не заменяет его.

Gateway отменяет upstream через shutdown реального сокета при обнаруженном разрыве SSE-клиента. Локальные HTTP tests покрывают ожидание заголовков, остановившееся тело и освобождение слота. Новые token/time caps не добавлены; detection зависит от записи события/keepalive, а незавершённый DNS/TCP/TLS setup сохраняет прежний connect timeout. Полный локальный suite после подключения title helper: 221 PASS.

Picker, discovery и pricing теперь содержат 44 пункта: 12 по подписке и 32 по кошельку, одна модель/оплата; 15 пунктов имеют эффективный 1M context. Effort выбирается штатным `/effort`. Четыре недоступных Qwen скрыты, retired alias удалён без перенаправления, Avatar отключён отдельно, свежая проверка GPT-OSS прошла. Сохранение per-model effort при обновлении каталога проверено. [Mapping и живая проверка](EFFORT.md).

Установщик сохраняет оба запрета телеметрии Desktop, но устанавливает `disableNonessentialServices=false`: native schema относит к этому отдельному флагу иконки, hosted previews, MCP App widgets и Linux spellcheck. `disableAutoUpdates=false` возвращает обычную политику обновлений (в этой Linux-сборке — системный пакетный менеджер). Override `modelCatalogUrl` удалён: подписанный каталог обновляется и кешируется штатно. `bootstrapEnabled` не переопределяется, URL не добавляется. Изменения возвращают возможности; они не подтверждают исправление отправки Code. После правки установщика новая политика отдельно сохранена в основной профиль с backup, без перезапуска приложения; полное перечитывание проверяется при следующем обычном запуске. Миграция записана в `.local/native-policy-migration.json`. Старые no-fetch receipts ниже описывают предыдущую политику.

Ниже — предыдущие этапы и их результаты; строки о MISSING engine или старом числе маршрутов относятся к историческим снимкам.

# Предыдущий этап конфигурации — 2 ноября 2026

После последнего уточнения пользователя оставлена простая схема:
оригинальный Claude Code → локальный NeuralDeep gateway → NeuralDeep напрямую.
Служебная активность уменьшается обычными флагами телеметрии и ошибок.
Отдельный сетевой фильтр и proxy-обёртка удалены из запуска; прежний
принадлежащий проекту фильтр на 18790 остановлен через idle shutdown.
Общий relay 20171 не останавливался и не перенастраивался.

## Состояние на том этапе

- Оригинальная ссылка `~/.local/bin/claude` восстановлена из исходного backup
  и указывает на настоящий CLI. Установщик больше её не заменяет.
- Обычный `claude` использует NeuralDeep из основных settings: local API
  127.0.0.1:8787, Qwen 3.8 27B subscription по умолчанию, полный picker/MCP,
  ToolSearch force, sandbox disabled. Настройки proxy в файл не записываются.
- Оригинальный CLI выполнил один обычный запрос через основные настройки:
  ответ `ND_NATIVE_OK`, `is_error=false`, модель
  `nd/qwen3.8-27b@subscription`, один turn. Receipt:
  `.local/final-native-cli.json`. Общая длительность 56.916 с; gateway
  зарегистрировал 55.94 с ожидания заголовков провайдера, то есть эта
  задержка относится к upstream inference, а не к сетевому фильтру.
- `autoUpdates=true`; широкие флаги, блокировавшие updater, удалены.
  Реальный `claude update` прошёл: проверка latest, версия 2.1.316 актуальна.
- Все семь переключателей Desktop включены. Ручного `inferenceModels` нет,
  discovery получает 117 маршрутов; 57 имеют эффективный 1M context.
- Native Desktop pricing содержит 117 строк: wallet RUB → USD по датированному
  курсу ЦБ; подписка — нулевая дополнительная цена токенов без абонплаты.
  Неподтверждённая цена cache creation не выдумывается.
- Встроенные подписанные metadata клиента сохранены; произвольные NeuralDeep
  metadata публикуются в расширении gateway, без подделки signed catalog.
- Sandbox Code и Electron выключен; analysis VM сохранена. Пользователь
  оставил права `/dev/vhost-vsock` без изменений, поэтому её исполнение на
  этом Linux пока недоступно.
- Отдельный local-browser MCP после упрощения повторно проверен: 72 tools,
  обычная public navigation, accessibility snapshot, PNG; proxy/filter
  configuration отсутствует. Receipt: `.local/browser-validation/direct-receipt.json`.
- Навыки nd-design, nd-workflow и nd-browser установлены с актуальным runtime.
- Состояние итоговых настроек: `.local/final-simple-config.json`.
- Итоговый boundary check `.local/final-boundary-check.json`: защищённые
  relay/Codex файлы и их права совпали, parent proxy env не изменён, relay
  active и HTTPS через 20171 вернул 200.

Полноценная native Desktop Code session ещё не проверена: приложению нужен
свой engine 2.1.309, который отсутствует в cache. Штатная подготовка engine
больше не блокируется нашим фильтром; cache marker или версия бинарника не
подменялись. Домашний native UI и discovery ранее проверены отдельно.
Standalone CLI `/cost` остаётся штатной оценкой неизвестной модели; скрытый
host-managed pricing mode не включён ради сохранения обычного CLI.

## Предыдущие проверки и история уточнений

Ниже сохранены результаты до последнего упрощения. Они доказывают discovery,
ToolSearch, прямой transport и отдельные native пути, но их guard/network
boundary и старый CLI overlay не являются текущей production-конфигурацией.
Исходные receipts и неуспешные попытки не изменены.


Состояние установки проверено 2 ноября 2026. Нативные версии: Claude Code
2.1.316 и Desktop 4.4212.0, Linux x86_64. Код установки переносимый; запуска
нативных Windows/macOS в этой среде не было.

## Установленная конфигурация

`modelDiscoveryEnabled`, `modelPrefer1mContext`,
`inferenceModelPricingEnabled`, `modelCatalogEnabled`, `toolSearchEnabled`,
`builtinBrowserEnabled`, `chatAdvancedFileAnalysisEnabled`, `chatTabEnabled`
равны `true`. `inferenceModels` отсутствует, иначе native приложение использует
его как полный allowlist и не добавляет новые найденные модели.

Gateway Models API отдаёт 117 уникальных маршрутов: модель × оплата × effort.
Первая — Qwen 3.8 27B по подписке. 57 маршрутов имеют эффективное входное
окно не меньше 1M, 91 маршрут относится к кошельку. Все opaque IDs обратно
разрешаются в исходный NeuralDeep ID, billing и effort. Реальные capabilities,
ограничения, тарифы RUB, thinking flags и достоверность полей находятся в
расширении `neuraldeep`; native discovery parser принимает лишь часть полей.

Native pricing содержит 117 строк. Wallet RUB-тарифы пересчитаны для USD UI
по официальному курсу ЦБ 80.9734 RUB/USD с effective date 2026-11-03,
опубликованному на момент запроса 2026-11-02. Это оценка UI; рублёвый биллинг
провайдера не меняется. Подписка имеет нулевую дополнительную цену токенов,
без фиксированной абонплаты. Cache write = 0 — обязательное поле интерфейса,
соответствующее нулю cache creation tokens адаптера; это не опубликованный
тариф создания кеша. Quote/provenance/omissions сохранены в
`.local/pricing-fx.json` и `.local/desktop-pricing.json`.

Model catalog использует неизменённый подписанный seed 3373 из самого
приложения. Native sentinel `https://model-catalog.invalid/unreadable`
не выполняет fetch. Подписанный catalog относится к Claude; custom NeuralDeep
metadata в него не подделываются. CLI `CLAUDE_CODE_MODEL_CATALOG=0`
выключает fetched/served catalog, сохраняя compiled baked metadata клиента.

Code command sandbox: `sandbox.enabled=false`,
`sandbox.allowUnsandboxedCommands=true`. Desktop не задаёт ограничение папок
или egress, которое принудительно вернуло бы этот sandbox. CLI launcher
применяет приватный command-level settings overlay после разбора supplied
settings; проект не может отменить принудительные значения. Пользовательские
параметры сохраняются, временный файл удаляется после завершения процесса.
Electron launcher передаёт `--no-sandbox`; analysis VM сохранена.

## Исполненные проверки

- Полная установка `python scripts/nd.py install --activate` завершилась
  успешно; актуальные flags, 15 MCP и навыки `nd-design`, `nd-workflow`,
  `nd-browser` установлены в основные профили. Вывод:
  `.local/features-install-output.log`.
- Обычный установленный wrapper принял пользовательский `--settings`,
  пытающийся включить sandbox и выключить tool search, и выполнил настоящий
  native `--version`: `2.1.316 (Claude Code)`. Принудительное объединение,
  сохранение настроек, приватные права, concurrent isolation и cleanup
  отдельно проверены unit tests. После запуска временных settings не осталось.
- Настоящий native ToolSearch: одна поисковая команда, `tool_reference`,
  реальный локальный MCP echo, ожидаемый ответ. Доступные upstream-схемы
  менялись 1 → 2 → 2 в трёх inference requests. Receipt:
  `.local/offline-validation/20261102T175007710217Z/receipt.json`.
- Настоящий Desktop в проверенном network/PID namespace записал
  `Model discovery: 117 found in 57ms; picker = 117 (discovery)`,
  `ConfigHealth: healthy`, seed catalog без fetch. Запуск включал собственную
  native проверку credentials: один Qwen subscription запрос с max_tokens=1.
  Ноль успешных или pending non-loopback connections, ноль разрешённых
  внешних соединений guard. Сохранены исходный INCOMPLETE старого probe и
  отдельный post-run review, который корректно классифицирует implicit
  connection probe; исходные receipts не заменены задним числом.
- Screenshot `screen-07.png` в
  `.local/desktop-validation/features-20261102T175346552383Z/` показывает
  native Home, Gateway banner, Chat composer и выбранный Qwen по подписке.
  Dropdown не открывался и UI-действия не выполнялись; полная интерактивная
  проверка списка не заявляется. Подробности — `visual-review.json` рядом.
- Отдельный официальный Playwright MCP 0.0.84 публикует 72 инструмента:
  public navigation, accessibility snapshot и PNG реально проверены.
  Попытка Anthropic-навигации заблокирована guard до upstream. Проверены
  реальные Chromium args: proxy18790, direct NeuralDeep bypass, no-sandbox,
  headless, отдельный временный профиль. После закрытия своих процессов не
  осталось. Receipt: `.local/browser-validation/receipt.json`.
- Содержимое и права шести защищённых файлов relay/Codex до/после установки
  совпали; proxy-переменные родительского процесса не изменены. Relay active,
  HTTPS через 127.0.0.1:20171 вернул 200. Receipt:
  `.local/features-boundary-after.json`. В этом процессе не были заданы
  DBUS/XDG variables: для read-only systemctl использован существующий
  `/run/user/1000/bus`; сервис не перезапускался и не перенастраивался.

## Подтверждённые ограничения

Advanced file analysis требует VM. На этом Linux `/dev/vhost-vsock` доступен
группе kvm, в которую пользователь не входит. Пользователь явно выбрал
оставить права ОС без изменений. Переключатель и VM preference включены;
исполнение VM/analysis здесь пока не работает и не объявляется проверенным.

Публичные сайты во встроенном браузере требуют native классификации через
Anthropic. Пользователь выбрал сохранить запрет: встроенный браузер
настроен для локальных превью, публичный веб доступен через independent MCP.
Проверка отдельного MCP не выдаётся за интерактивный тест native preview.

Desktop требует собственный Code engine 2.1.309. Его pinned cache отсутствует;
локальный standalone 2.1.316 не является поддерживаемым substitute. Native
download с Anthropic блокируется, оригинального офлайн `.zst` в проверенных
локальных каталогах не найдено. `desktop_runtime.inspect` фиксирует MISSING
по embedded manifest; cache, `.verified` и binary version не подделывались.
Native Desktop Code session пока не запускалась. Готовый CLI работает отдельно.

Сетевая граница остаётся выбранной пользователем: per-Claude destination
guard без постоянного OS firewall/network sandbox. Произвольный native/helper
код может игнорировать proxy; абсолютная изоляция всех sockets не заявляется.

Точные consumers/исходные смещения: [исследование Desktop](research-desktop-features-20261102.md).
Отдельные lifecycle-доказательства: [ToolSearch](research-tool-search.md),
[браузер](BROWSER.md), [сетевая политика](NETWORK-POLICY.md).

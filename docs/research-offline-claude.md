# Claude Code без обращений к Anthropic: локальный аудит 2.1.316

После нового запрета пользователя все наши активные тестовые Claude-процессы
остановлены. Для этого аудита CLI **не запускался**, обращения к Anthropic,
официальной документации по HTTP, OAuth, каталогу, telemetry и updater не
выполнялись. Использован читаемый vendor JavaScript, встроенный в уже
установленный бинарник. Это первичный источник фактической установленной версии,
но не доказательство поведения будущих версий.

Источник: `/home/bethrezen/.local/share/claude/versions/2.1.316`, 314 MiB.
SHA256: `fd13c70000fec3f2116dfbcbb6121210b4a29328bf0e46210a59dd594a67d824`.
Ни бинарник, ни сохранённые учётные данные этим аудитом не изменялись.
Смещения ниже — нулевые байтовые смещения именно этого файла; они нужны для
воспроизводимого read-only поиска, а не являются строками исходного репозитория.

**Набора environment flags недостаточно, чтобы обещать «никогда ни одного
пакета к Anthropic».** Флаги отключают известные подсистемы, но дополнительные
потоки используют собственные URL/учётные записи. Для строгого требования нужен
отдельный fail-closed сетевой барьер вокруг Claude и его дочерних процессов;
проверять его следует до возобновления нативных запусков.

## Подтверждённые флаги

| Переменная | Значение | Что установлено по локальному источнику |
|---|---|---|
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Основной privacy mode `essential-traffic`; включает общий запрет несущественного трафика. Смещение 273618614, `r7t()` / `_t()` |
| `DISABLE_TELEMETRY` | `1` | Выбирает более узкий mode `no-telemetry`; сам по себе слабее предыдущего. Смещение 273618696 |
| `DO_NOT_TRACK` | `1` | Альтернативный путь к `no-telemetry`, проверяется через boolean parser. Смещение 273618753 |
| `DISABLE_ERROR_REPORTING` | `1` | Ошибки не передаются штатному error dispatcher; также отключается отдельный error reporting gate. Смещения 273621033 и 282524537 |
| `DISABLE_AUTOUPDATER` | `1` | Updater возвращает skip reason; общий nonessential-флаг также даёт skip reason. Смещение 276631256, `SBe()` / `hy()` |
| `DISABLE_GROWTHBOOK` | `1` | Отключает GrowthBook/feature-fetch gate `Dm()`. Смещение 277415366 |
| `CLAUDE_CODE_ENABLE_TELEMETRY` | отсутствует или `0` | Это отдельное включение OTel. Не следует оставлять `1`; проверяется совместно с OTEL exporters. Смещение 290578062 |

В `r7t()` первые две переменные проверяются на наличие непустой строки,
поэтому для них **`"0"` не является надёжным способом выключения**: для
включения запрета используйте `"1"`, для снятия — удаление переменной. У других
настроек может использоваться typed boolean parser. Не переносите правила
парсинга одной переменной на все остальные.

Консервативный env-фрагмент для процесса Claude:

```json
{
  "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
  "DISABLE_TELEMETRY": "1",
  "DO_NOT_TRACK": "1",
  "DISABLE_ERROR_REPORTING": "1",
  "DISABLE_AUTOUPDATER": "1",
  "DISABLE_GROWTHBOOK": "1",
  "CLAUDE_CODE_ENABLE_TELEMETRY": "0"
}
```

Это фрагмент исследования, а не заявление, что он уже применён или проверен
живым запуском. Пользовательские managed settings могут добавлять OTel exporters
и другие endpoint-настройки; их эффективную конфигурацию надо учитывать отдельно.

## OAuth и авторизация

Для NeuralDeep штатная модель авторизации — **непустой локальный**
`ANTHROPIC_API_KEY` к локальному `ANTHROPIC_BASE_URL`. Это токен локального
шлюза, а не один из двух NeuralDeep-ключей. Настоящие Hub-ключи остаются только
в `.env` интеграции. Следует выбирать один источник авторизации, убирая из
окружения конкретного Claude-процесса конфликтующий `ANTHROPIC_AUTH_TOKEN`.

Ранее прочитанная справка самой 2.1.316 для `--bare` прямо указывает, что в этом
режиме Anthropic auth читается только из API key или apiKeyHelper, а OAuth и
keychain не читаются. Однако bare также исключает hooks, LSP, plugin sync,
background prefetch и часть других возможностей. В нашем фактическом bare smoke
native Skill tool не предоставлялся. Поэтому bare — диагностический вариант,
а не незаметная замена полной рабочей конфигурации.

Обычный режим нельзя считать безопасным от OAuth только на основании наличия
API key: в предыдущих диагностических логах были попытки OAuth/bootstrap и
first-party telemetry. Отдельные источники credentials и функции remote tools
имеют собственные правила привязки к сохранённому входу; смещение 274829994.
**Не удалять и не отзывать сохранённые login/keychain записи**, которыми могут
пользоваться другие профили/провайдеры. Очистка должна быть scoped к env/descriptor
нового Claude-процесса, а не общей конфигурацией соседних приложений.

Следует проверить и исключить нежелательное наследование следующих семейств:

- `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`,
  `CLAUDE_CODE_OAUTH_SCOPES`, `CLAUDE_CODE_OAUTH_CLIENT_ID`.
- `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`,
  `CLAUDE_CODE_SESSIONS_OAUTH_TOKEN`, `CLAUDE_CODE_SDK_HAS_OAUTH_REFRESH`,
  `CLAUDE_CODE_SDK_HAS_SESSIONS_OAUTH_REFRESH`.
- Удалённые bridge/session credentials и host credentials — если они относятся
  к Anthropic и не являются необходимой явно выбранной авторизацией конкретного
  провайдера. Не объявлять любое неизвестное provider credential ошибочным.

Определения соответствующих credential/env-групп находятся около смещений
274377887–274380010. Наличие переменной в этом перечне не доказывает, что она
установлена на машине: значения секретов для исследования не выводились.

## Произвольный localhost OAuth URL в release не поддержан

`CLAUDE_CODE_CUSTOM_OAUTH_URL` существует, но production 2.1.316 проверяет
строгий allowlist и для произвольного localhost бросает ошибку. Допустимы только:

- `https://beacon.claude-ai.staging.ant.dev`
- `https://claude.fedstart.com`
- `https://claude-staging.fedstart.com`

Смещение 273601135, `u9e` / `nn()`. Это не полезный механизм для запрета
Anthropic: разрешённые адреса тоже относятся к экосистеме Anthropic. Ставить
заведомо недопустимый URL для «перехвата OAuth» приведёт к ошибке приложения.

`CLAUDE_LOCAL_OAUTH_API_BASE` / `...APPS_BASE` / `...CONSOLE_BASE` встречаются в
dev-конфигурации, но выбор среды в данном бинарнике скомпилирован как `prod`
(около 273597866). Их нельзя выдавать за подтверждённый runtime-переключатель
release-сборки в offline OAuth.

`CLAUDE_CODE_API_BASE_URL`, `CLAUDE_CODE_GB_BASE_URL`, отдельные artifact/memory/
bridge URL существуют. Они относятся к разным клиентам и не являются одним
универсальным redirect для всех запросов. Например, OAuth-конфигурация содержит
отдельный `MCP_PROXY_URL` и постоянный client-metadata URL
(`claude.ai/oauth/claude-code-client-metadata`), около 273599647. Переопределение
только inference `ANTHROPIC_BASE_URL` не покрывает такие подсистемы.

Не устанавливать `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=true`: он заставляет
клиент считать сторонний base first-party. Проверки `Pu()`/`GK()` и классификация
base находятся около 273846281. Это ослабило бы корректное различение провайдеров.

## Дополнительные gate и функциональные последствия

`DISABLE_LOGIN_COMMAND=1` и `DISABLE_LOGOUT_COMMAND=1` скрывают соответствующие
команды, но **не являются доказательством отсутствия фонового OAuth**; смещение
284912474. Аналогично `DISABLE_FEEDBACK_COMMAND`, `DISABLE_BUG_COMMAND`,
`DISABLE_UPGRADE_COMMAND` могут убрать пользовательские entry points, но не
заменяют общий запрет сети. `CLAUDE_CODE_DISABLE_LAUNCHER_SIGN_IN=1` отключает
специфический launcher sign-in, а не все виды авторизации; смещение 275545332.

Nonessential mode явно отключает cloud sessions, feedback/publishing и скачивание
Anthropic-hosted plugin archives. Это совместимо с запретом пользователя на
Anthropic, но нельзя одновременно обещать доступность этих hosted-функций.
Локальные skills, файлы, MCP и субагенты — отдельные возможности, которые должны
сохраняться и проверяться после сетевой изоляции.

Отключение GrowthBook может менять доступность feature-gated функций; при
`DISABLE_TELEMETRY` существует отдельный механизм чтения локального GB disk cache
(`CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF`, около 277415464), но его наличие
не даёт права считать все флаги актуальными или гарантировать dynamic workflows.
Сетевой барьер и разрешённые локальные функции надо проверять раздельно.

## Граница защиты

До следующего запуска требуется политика, которая отказывает запрещённым
Anthropic назначениям **до сетевого соединения** и распространяется на native
CLI и его дочерние процессы. После неё можно выполнять минимальный smoke и
проверять реальные события/соединения. Попытка соединения, заблокированная
барьером, — это обнаруженная несовместимость клиента с выбранным режимом, а не
разрешение тихо пропустить трафик.

Shared `127.0.0.1:20171` relay через `nl.notevil.ai:8888`, его service/script/
independent settings, а также proxy ChatGPT/Codex должны оставаться нетронутыми.
Данный аудит их не менял. Прямые запросы NeuralDeep обеспечивает собственный
transport `ProxyHandler({})`; это не требует общесистемного удаления proxy.


## Cold-machine gates: Workflow, Agent Teams и Skill (дополнительный source audit)

Проверено 2026-11-02 чтением того же установленного native-бинарника 2.1.316
с SHA256 выше. Нативный CLI, Desktop, JavaScript из бинарника и сетевые запросы
для этой части аудита **не запускались**. Это результат статического чтения
primary source установленной версии; живую проверку после новой сетевой политики
следует хранить отдельной квитанцией. Старые live-результаты Workflow/Agent
в `VALIDATION-cli.md` относятся к более ранней политике и её не доказывают.

### Что в действительности делает `DISABLE_GROWTHBOOK`

Флаг выключает не только загрузку: стандартные feature readers перестают читать
payload/disk cache и возвращают переданный call-site default. В частности:

- `Dm()` требует отсутствие `DISABLE_GROWTHBOOK`, байтовое смещение 277415343.
- Альтернативный reader `MBi()` для
  `CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF` **тоже** требует отсутствие
  `DISABLE_GROWTHBOOK`, смещение 277415391. Он не восстанавливает cache при
  `DISABLE_GROWTHBOOK=1`.
- `getFeatureValueWithSource(e,n)` при отключённых readers возвращает `n` с
  источником `disabled` до обращения к payload/disk, смещение 277150801.
- `getFeatureValueBlocking(e,n)` возвращает `n` до initialize, смещение 277150435.
- `checkGateCachedOrBlocking(e)` возвращает false до cache, смещение 277151592.

Поэтому сохранённые значения feature cache не являются основанием обещать
сохранение произвольной gated-функции. Для нужных нам локальных Workflow и
Agent Teams их собственные call-site defaults, однако, равны **true**.
Им не требуется ни прежний login/cache, ни удалённая загрузка флагов.

В этом release методы `getEnvironmentOverrides()` и `readConfigOverrides()`
стандартного GrowthBook client возвращают соответственно null/undefined,
смещения 277140766 и 277141199. Наличие строки
`CLAUDE_INTERNAL_FC_OVERRIDES` в binary/dependencies само по себе не доказывает
работающий общий override. Для данной настройки он не нужен, не применяется и
не предлагается. Binary patch и запись фальшивого feature cache не используются.

### Подтверждённая конфигурация локальных Workflow

Определения env `CLAUDE_CODE_WORKFLOWS` и
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` находятся около смещений 273644386 и
273639173. Первый использует typed triBool, второй typed bool. Значение `"1"`
является штатным способом включения.

В module 278253462–278256806 Workflow availability читает
`tengu_workflows_enabled` с default=true. При
`CLAUDE_CODE_WORKFLOWS=1` это значение используется и как availability, и как
defaultOn. Native runtime-check `Vh()` из импортированного
`chunk-cgr0tezp.js` в этой standalone Bun-сборке возвращает true,
смещение 273504877. Это не утверждение о сторонних Node/Deno repack-сборках.

Следующие **top-level** settings подтверждены реальной schema установленной
версии, смещения 274284158–274286100:

```json
{
  "enableWorkflows": true,
  "disableWorkflows": false,
  "workflowSizeGuideline": "unrestricted",
  "workflowKeywordTriggerEnabled": true
}
```

`workflowSizeGuideline` принимает ровно `unrestricted`, `small`, `medium`,
`large`. Это рекомендация модели по размеру графа, не исполнительный hard limit.
`unrestricted` убирает эту рекомендацию. `workflowKeywordTriggerEnabled` включает
локальный keyword `ultracode`; этот параметр не заменяет сам Workflow tool.

Независимыми условиями остаются `CLAUDE_CODE_DISABLE_WORKFLOWS`, user/managed
`disableWorkflows`, `enableWorkflows` и org restriction `allow_workflows`.
Управляемый запрет организации нельзя отменять настройкой интеграции. Отсутствие
remote feature cache не является таким запретом; в обычном cold profile без
restrictive policy hint общий org-policy reader по умолчанию разрешает ключи
(около 278003776). Существующий managed/org policy не очищается и не подменяется.

Реальный env `CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` принимает целое 1..256,
смещение parser 273690575. Consumer около 297019805 использует override;
без него default является CPU-derived значением с clamp 2..16, функция `yi`
около 297013205. Поэтому 256 — максимальное принимаемое конфигурацией значение,
а строка `unlimited` невалидна. В binary также есть независимый guard 1000
`agent()` calls и отдельный semaphore 50. Advisory unrestricted не удаляет
эти native пределы и не меняет ограничения провайдера/доступной памяти.

### Agent Teams и Skill без remote flag cache

Agent Teams availability находится около 282460909: после локального
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (либо native аргумента `--agent-teams`)
он читает `tengu_amber_flint` с **default=true**. Следовательно,
`DISABLE_GROWTHBOOK=1` сохраняет этот путь доступным без cache. Это наличие
инструментов; правильность исполнения конкретной моделью проверяется отдельно.

Native `Skill` tool около 291629057 использует availability `!Wb()`.
`Wb()` около 273451962 читает только
`host.launchOptions.disableSlashCommands()`. GrowthBook gate в этой проверке
отсутствует. Не следует включать `--disable-slash-commands` или использовать
режим с урезанной customization surface ради сетевой политики. Разрешения
инструментов, user-invocable-only skills, managed rules и правила конкретного
skill продолжают применяться независимо.

Bundled-skills фильтр около 275074560 отдельно учитывает
`CLAUDE_CODE_DISABLE_BUNDLED_SKILLS`, setting `disableBundledSkills` и org key
`allow_bundled_skills`. Для последнего policy registry содержит
`onCacheMiss: "allow"`, смещение 278000475; managed/compliance запрет всё ещё
имеет силу. Локальный core allowlist включает `workflow-authoring`, module около
275074300. Наличие Skill tool не создаёт отсутствующий `/design` skill: его
локальная установка/доступность и реальная работа требуют отдельной проверки.

Рабочее решение для этих трёх возможностей не требует ослаблять
`DISABLE_GROWTHBOOK`, давать доступ к Anthropic domains, копировать vendor cache
или менять binary. Сетевой барьер и последующая cold-profile runtime проверка
нужны независимо: данный source audit не является измеренным доказательством
отсутствия сетевых пакетов или завершения агентных задач.

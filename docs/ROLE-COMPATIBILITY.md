# Динамический контекст Desktop в OpenAI Chat

В проверенном эпизоде Code Desktop передал результаты обоих агентов, но Qwen
продолжал отвечать, что они ещё работают. Повторение фактического запроса
показало проблему ролей backend: поздние `system` messages не учитывались так
же, как обычные сообщения истории. Это не исправлялось повторным ожиданием
или отключением safety classifier.

Шлюз приводит такой контекст к стандартной структуре Chat:

| Входной контекст | Передача backend |
|---|---|
| `body.system` | Начало единственного initial `system`, текст сохранён |
| Дополнительные настоящие `system` и `developer` instructions | В том же initial `system`, после исходных правил, в исходном порядке |
| Native envelope `Another Claude session sent a message while you were working:` + `<agent-message from="…">…</agent-message>` | `user` data на текущем месте истории, полный текст сохранён |
| Native завершение Dynamic workflow в Desktop engine 2.1.309 с точным guard `[SYSTEM NOTIFICATION - NOT USER INPUT]` | Guard остаётся в initial `system`, весь `<task-notification>` передаётся как хронологические `user` data |
| Результаты инструментов | `tool` непосредственно после соответствующего assistant tool-call group |

Распознаётся только точный native envelope в message с ролью `system`, включая
закрывающий `</agent-message>`. Подстрока в середине policy или незаконченный
envelope остаётся control text. `body.system` и `developer` никогда не
понижаются до user-role по этому признаку. Поэтому исходные classifier
policies и управляющие инструкции остаются в System, а отчёт другого агента
не приобретает их приоритет.

Внутри hand-back не удаляются и не переписываются предупреждения
`the safety classifier was unavailable`, итоговые значения, status и usage.
Если report пришёл во время ещё не завершённого tool-call group, он размещается
сразу после полного набора tool results и перед следующим обычным содержимым:
это сохраняет допустимую OpenAI последовательность, не пряча отчёт в System.

В полной сессии от 3 ноября оба участника Workflow завершились и Desktop
доставил их результаты через позднее `system`-сообщение. Основная модель
после этого повторила, что ждёт участников. Точное восстановление запроса
подтвердило, что прежний шлюз перенёс и provenance guard, и весь результат
Workflow в начало System. Для наблюдаемого формата теперь разделяются guard
и данные. Правило требует точного no-human-input guard, заголовка завершённого
Dynamic workflow и целого закрытого блока с результатом. В результате,
диагностике и статистике текст сохраняется дословно. Варианты с другим guard,
незавершённым уведомлением или дополнительным управляющим текстом после него
сохраняют обычную обработку System. Регрессия также проверяет, что доставка
данных ждёт последнего результата параллельной группы инструментов.

Повтор точного сохранённого запроса через обновлённый шлюз на Qwen 3.8 27B
по подписке (native `high` → NeuralDeep `xhigh`) завершился за 111,69 с.
Модель обновила план и вызвала Edit для `calc.py`, предложив исправить границу
диапазона суммирования. Поток завершился без ошибок. В этом повторе инструменты
не выполнялись. Локальные свидетельства сохранены в
`.local/desktop-session-validation/20261103T063051207548Z/workflow-completion-replay.json`
и соседнем SSE-файле.

Повторение исходного эпизода в трёх вариантах сохранено под
`.local/desktop-session-validation/20261102T190235657558Z/role-replay-*.json`.
Вариант с исходными поздними System повторял устаревшее состояние; перенос
только двух agent reports в User позволил модели учитывать завершение и
продолжить Edit. Перенос всех instructions в User не принят как решение,
поскольку это изменило бы приоритет управляющего контекста.

Unit tests проверяют один initial System, сохранение всех control texts,
точное содержимое hand-back с warning, приоритет classifier/developer
instructions и корректный порядок parallel tool results. Live replay нового
нормализатора также прошёл: `canonical-context-acceptance-review.json` в том же
каталоге фиксирует `PASS_REPLAY_OF_EXACT_NATIVE_REQUEST`, один initial System,
два хронологических agent reports и корректно предложенный Edit. Replay не
исполнял инструменты (`tools_executed=false`). Последующая focused-сессия
настоящего Desktop также прошла: родитель принял отчёт фонового агента и
продолжил работу, выполнил два реальных shell-теста и завершился маркером
`DESKTOP_CLASSIFIER_OK 5050`, без safety warnings. Это отдельный native сценарий
с одним агентом, а не повтор всей первоначальной проверки с двумя агентами,
правкой кода и MCP. Его результат записан в
[VALIDATION-desktop-session.md](VALIDATION-desktop-session.md).

Отдельно проверен native Auto classifier в Desktop engine 2.1.309: его `MEe`
передаёт policy через `body.system`, а `bbr` формирует transcript/action только
как `user` messages. Необязательный CLAUDE.md context также имеет роль `user`.
Поэтому для этой структуры нормализатор сохраняет прежние роли и тексты;
дополнительных System в конец classifier history этот native путь не создаёт.
Восемь записанных live classifier stages имели по два upstream messages
(initial System и User). Полные исходящие bodies этого private benchmark
не сохранялись: вывод о структуре основан на коде настоящего engine,
метаданных запросов и отдельном regression test, а не на сравнении скрытых
payloads побайтно.

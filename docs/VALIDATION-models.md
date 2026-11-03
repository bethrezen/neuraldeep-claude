# Живые проверки моделей NeuralDeep

Актуализация после выбора пользователя: picker содержит 44 базовых пункта без effort-дублей. Четыре Qwen ∞ с отказом 401 скрыты до успешной повторной проверки. `qwen-flash-next-ru` удалён без перенаправления: старые настройки нужно заменить вручную. GPT-OSS-120B по подписке при целевом повторе 2 ноября прошёл все шесть сценариев (текст, инструменты, roundtrip и low/medium/high); receipt `.local/model-probes/20261102T184910946241Z.json`. Исходная матрица и её неудачи ниже сохранены как история.

Проверки выполнены 2 ноября 2026 года с прямым сетевым доступом к NeuralDeep, без HTTP/SOCKS-прокси. Подписка и кошелёк проверялись отдельными ключами. Разрешение на платные проверки кошелька получено пользователем в основном чате.

Начало: 2026-11-02T18:19:11.069078+03:00. Завершение первичной матрицы: 2026-11-02T18:21:33.799389+03:00.

Проверено **49 комбинаций модель/оплата** из снимка каталога. Первичная матрица содержит **207 запросов**: 201 PASS, 5 HTTP-отказов и 1 пустой финальный ответ. Дополнительно выполнен целевой повтор из двух запросов для gpt-oss-120b по подписке; оба повторных запроса прошли. Исходная ошибка сохранена.

**Доступность:** 44 маршрута дали правильный текстовый ответ в реальном SSE. Из них 43 прошли все назначенные проверки с первого раза; gpt-oss-120b по подписке имел один пустой финальный ответ после инструментов, затем прошёл целевой повтор. Пять дополнительных маршрутов недоступны: четыре Qwen ∞ отклонены с HTTP 401, устаревший alias qwen-flash-next-ru отклонён с HTTP 404.

**Покрытие:** текст по SSE — 49; вызовы инструментов — 44; продолжение после результатов инструментов — 44; vision — 34; отдельные effort — 36. Несколько tool calls в одном ответе вернули 41 из 44 проверенных маршрутов. Это отдельный результат от параллельных субагентов Claude CLI.

Матрица проверяла короткие реальные запросы через тот же protocol.to_openai/from_openai/stream_openai, который использует локальный шлюз. Для текста запрашивался ровно OK; для инструментов — echo с двумя значениями и следующий ход с tool_result; для vision — распознавание красного тестового квадрата. Проверены текущие модельные parameters, в том числе экспериментальные thinking/preserve-флаги. Максимальный выход в этих пробах — 4096 токенов, ограниченный опубликованным output, когда он меньше.

## Результаты по маршрутам

| Модель | Оплата | SSE текст | Инструменты | Продолжение | Vision | Effort |
|---|---|---|---|---|---|---|
| `claude-haiku-5.5` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `claude-opus-5.5` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `claude-sonnet-5.5` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `deepseek-v4-flash` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, high: PASS, max: PASS |
| `deepseek-v4-flash-b24` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, high: PASS, max: PASS |
| `deepseek-v4-flash-vision-exp` | ₽ кошелёк | PASS | PASS | PASS | PASS | low: PASS, high: PASS, max: PASS |
| `deepseek-v4-pro` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, high: PASS, max: PASS |
| `deepseek-v4.1-flash` | ₽ кошелёк | PASS | PASS | PASS | PASS | low: PASS, high: PASS, max: PASS |
| `gemma-4-31b` | подписка | PASS | PASS | PASS | PASS | — |
| `gemma-4-31b` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `gemma-4-31b-noreason` | подписка | PASS | PASS | PASS | PASS | — |
| `gemma-4-31b-noreason` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `gemma-b24` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `glm-5.2` | ₽ кошелёк | PASS | PASS | PASS | — | — |
| `glm-5.3` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, high: PASS, max: PASS |
| `glm-5.3-flash` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `glm-5.3-flashx` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `gpt-oss-120b` | подписка | PASS | PASS | FAIL_EMPTY_FINAL → PASS при повторе | — | low: PASS, medium: PASS, high: PASS |
| `gpt-oss-120b` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, medium: PASS, high: PASS |
| `gpt-oss-20b` | подписка | PASS | PASS | PASS | — | low: PASS, medium: PASS, high: PASS |
| `gpt-oss-20b` | ₽ кошелёк | PASS | PASS | PASS | — | low: PASS, medium: PASS, high: PASS |
| `kimi-k2.6` | подписка | PASS | PASS | PASS | PASS | — |
| `kimi-k2.6` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `kimi-k2.7-code` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `kimi-k3` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `kimi-k3.1-pro` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `minimax-m2.5` | ₽ кошелёк | PASS | PASS | PASS | — | — |
| `qwen-flash-next-ru` | подписка | HTTP 404 | — | — | — | — |
| `qwen3.6-35b-a3b` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.6-35b-a3b` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.6-35b-a3b-noreason` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.6-35b-a3b-noreason` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.6-fp8` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.6-fp8` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.6-fp8-noreason` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.6-fp8-noreason` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.6-unlim` | подписка | HTTP 401 | — | — | — | — |
| `qwen3.6-unlim-noreason` | подписка | HTTP 401 | — | — | — | — |
| `qwen3.6-unlim-xl` | подписка | HTTP 401 | — | — | — | — |
| `qwen3.6-unlim-xl-noreason` | подписка | HTTP 401 | — | — | — | — |
| `qwen3.7-flash` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.7-plus` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.8-27b` | подписка | PASS | PASS | PASS | PASS | low: PASS, medium: PASS, xhigh: PASS |
| `qwen3.8-27b` | ₽ кошелёк | PASS | PASS | PASS | PASS | low: PASS, medium: PASS, xhigh: PASS |
| `qwen3.8-27b-noreason` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.8-27b-noreason` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.8-flash` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |
| `qwen3.8-flash-next-ru` | подписка | PASS | PASS | PASS | PASS | — |
| `qwen3.8-flash-next-ru` | ₽ кошелёк | PASS | PASS | PASS | PASS | — |

## Ограничения доказательств

- PASS для effort означает, что запрос с этим значением принят и завершён правильным ответом. API не подтвердил фактически применённый уровень. Это особенно существенно для Qwen 3.8, где публичные источники NeuralDeep противоречат друг другу. Принятие thinking/preserve-флагов также не доказывает, что шлюз применяет каждый из них.
- Короткие пробы не проверяют физический предел контекста, точность tokenizer/count_tokens, длинные coding-сессии, устойчивость качества или все интерфейсы Desktop/Design. Приёмка клиента и его /compact выполняется отдельно в основном чате.
- GPT-OSS-120B по подписке однажды вернул end_turn и reasoning без финального текста. Это не упор в тестовый токеновый бюджет: usage output78. Повтор дал нормальный ответ, но исходный сбой сохраняется как свидетельство нестабильности.
- Опции Qwen ∞ XL присутствуют в /limits аккаунта, однако supplied subscription key отклоняет все четыре option-модели. Наличие опции аккаунта не доказывает привязку модели к этому ключу. Точную настройку allowed models/options должен исправить сервис/кабинет; локальное переименование не исправляет авторизацию.
- qwen-flash-next-ru — добавленный старый alias; сервер его не знает. Актуальное qwen3.8-flash-next-ru прошло подписку и кошелёк.
- У B24 тесты прошли в разрешённом временном окне. Это не отменяет документированное ограничение расписания.
- Исходные snapshots/receipts не переписаны ради улучшения результата. Файл .local/model-probes.json хранит время, usage, длины ответов, хеши и ошибки без API-ключей и содержимого рабочих диалогов. В нём отдельно записан targeted_retries.

## Воспроизведение

Переносимый скрипт: `scripts/probe-models.py`. По умолчанию он только показывает план без запросов и без чтения ключей. Примеры:

```bash
python scripts/probe-models.py --billing all
python scripts/probe-models.py --billing subscription --execute
python scripts/probe-models.py --billing wallet --execute
```

С `--execute` он берёт ключи из единого `.env`, использует прямой transport, четыре работника по умолчанию и текущий подписочный RPM. Кошелёк оплачивает реальные вызовы. Параметры `--workers`, `--max-tokens` и `--timeout` задают параметры диагностики. Каждый запуск сохраняет отдельный исторический receipt в `.local/model-probes/`, а `.local/model-probes.json` указывает на последний результат; предыдущий latest перед заменой архивируется. Код возврата ненулевой при любой неуспешной проверке.

Машинные статусы этого запуска дополнительно записаны в `.local/model-probe-status.json`; они не заменяют исходные ошибки.


Дополнительная проверка кабинета 2026-11-02: у ключа «Основной» опция Qwen ∞ XL уже включена, а выбор моделей стоит «Все модели». Настройки не менялись. Следовательно, причина четырёх HTTP 401 не установлена; нельзя приписывать их выключенному пользователем доступу. Наблюдение сохранено в `.local/provider-account-observation.json`.

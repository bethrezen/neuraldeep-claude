# Effort и thinking: первичные источники, 2 ноября 2026

Машиночитаемая таблица: `config/family-capabilities.json`. Это описания
производителей моделей. Для стороннего маршрута NeuralDeep указан статус
`upstream-documented-neuraldeep-experimental`: приём HTTP-параметра и его
фактическое применение — разные свойства. Пустой список effort означает, что
документированный дискретный регулятор не найден; вымышленные уровни не
добавлялись.

| Модель | Канонические effort | Default upstream | Thinking/сохранение |
|---|---|---|---|
| Claude Opus 5.5 | low, medium, high, xhigh, max | medium | Adaptive всегда включён |
| Claude Sonnet 5.5 | low, medium, high, xhigh, max | high | Adaptive; between_tools разрешён до high |
| Claude Haiku 5.5 | low, medium, high, xhigh, max | medium | Adaptive; disabled разрешён до high |
| GLM 5.3 / Flash / FlashX | low, high, max | max | Только enabled; clear_thinking=false сохраняет историю |
| GLM 5.2 | high, max | max | Enabled/disabled; имеются алиасы, см. ниже |
| Kimi K3 / K3.1 Pro | low, high, max | max в обычном API | Всегда thinking; полный assistant message возвращается неизменным |
| Kimi K2.6 | Дискретные уровни не документированы | enabled | thinking.type enabled/disabled |
| Kimi K2.7 Code | Дискретные уровни не документированы | enabled | Thinking выключить нельзя |
| Qwen 3.8 Flash | low, medium, xhigh | xhigh | enable_thinking и preserve_thinking |
| Qwen 3.7 Plus / Flash | Дискретные уровни не установлены | thinking enabled | ON/OFF, числовой thinking_budget, preserve_thinking |
| MiniMax M2.5 | Не регулируется | Всегда thinking | Сохранять полное содержимое `<think>` и tool_calls |

## Claude 5.5

Родной Anthropic API принимает `output_config.effort`; NeuralDeep предоставляет
OpenAI-совместимый маршрут, поэтому шлюз передаёт его OpenAI-полем
`reasoning_effort`. Само отображение этого поля в селекторе не доказывает
преобразование провайдером. Opus отклоняет отключение thinking на любом уровне.
Sonnet `between_tools` и Haiku `disabled` несовместимы с xhigh/max; для смены
effort между ходами следует оставить adaptive. [Официальная таблица
Anthropic](https://platform.claude.com/docs/en/build-with-claude/effort).

## GLM

У обычного API GLM 5.3, Flash и FlashX канонические значения low/high/max;
параметры Flash/FlashX соответствуют GLM 5.3. GLM 5.2 также принимает low,
medium, xhigh, minimal, none: low/medium превращаются в high, xhigh в max;
**minimal и none выключают thinking**. Они записаны отдельно от настоящих
уровней рассуждения, чтобы не изображать ещё два разных бюджета.
Алиасы Coding Plan отличаются; их нельзя переносить на обычный API без
проверки. [Deep Thinking](https://docs.z.ai/guides/capabilities/thinking),
[Flash/FlashX](https://docs.z.ai/guides/vlm/glm-5.3-flash).

Preserved Thinking задаётся `thinking.clear_thinking=false` и требует вернуть
все `reasoning_content` без изменения порядка и содержимого.
[Thinking Mode](https://docs.z.ai/guides/capabilities/thinking-mode).

## Kimi

K3 и K3.1 Pro в обычном API имеют low/high/max с default=max. При миграции с
K2.x производитель требует убрать объект `thinking`, управляя только
`reasoning_effort`. В Coding Plan default=high; это отдельная конфигурация
другого продукта. История включает reasoning_content и tool_calls полностью.
[K3](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart),
[K3.1 Pro](https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart),
[Reasoning Effort](https://platform.kimi.ai/docs/guide/use-reasoning-effort),
[Coding Plan](https://www.kimi.com/code/docs/en/kimi-code/models).

K2.6: default thinking.type=enabled, можно disabled; температура фиксирована
1,0 с thinking, 0,6 без него. K2.7 Code: только enabled, температура 1,0.
У обеих моделей top_p=0,95. При thinking в официальном API `tool_choice`
поддерживает только auto/none: принудительные required/named могут отклоняться.
Их нельзя считать общим требованием инструмента для всех семейств.
[K2.6](https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart),
[K2.7 Code](https://platform.kimi.ai/docs/guide/kimi-k2-7-code-quickstart).

## Qwen

Qwen 3.8 Flash: high/max → xhigh, minimal → low, none отключает thinking.
`reasoning_effort` нельзя сочетать с `thinking_budget`. Для истории поддержан
`preserve_thinking=true`. Для Qwen 3.7 Plus/Flash документированы переключатель
thinking, сохранение и числовой бюджет; первичного подтверждения набора
дискретных уровней для этих двух моделей не найдено.
[API Reference](https://docs.qwencloud.com/api-reference/chat/openai-chat),
[Thinking](https://docs.qwencloud.com/developer-guides/text-generation/thinking),
[Qwen 3.8 Flash](https://docs.qwencloud.com/developer-guides/getting-started/latest-model).

Собственные Qwen-лейны NeuralDeep могут снимать параметры или менять default;
их документированные ограничения имеют приоритет над общим upstream-профилем.
[NeuralDeep Chat](https://neuraldeep.ru/docs/chat.md?ref=W9VMAZP).

## MiniMax

Официальный OpenAI API MiniMax прямо ограничивает действие `reasoning_effort`
моделью M3.1-Flash. На M2.x отключение thinking принимается, но игнорируется.
M2.5 нельзя честно снабдить low/medium/high как разными работающими бюджетами.
Полный assistant content с `<think>`-тегами и tool_calls нужно сохранять;
при разделении reasoning также возвращается reasoning_content.
[MiniMax OpenAI API](https://platform.minimax.io/docs/api-reference/text-openai-api).

## Живые пробы новых effort

Для новых уровней выполнена отдельная серия прямых запросов кошельком:
`protocol.to_openai`, короткий фиксированный промпт, max_tokens=4096, без
автоматических повторов. Отчёт `.local/new-effort-probes.json` различает
accepted, accepted_empty_content, rejected и сетевые ошибки; applied остаётся
unproven, поскольку ответ API не раскрывает доказательство фактического
применения запрошенного уровня. Все **32 запроса** приняты HTTP 200 и вернули
непустой content: по пять уровней трёх Claude 5.5 (15), по три GLM Flash/FlashX
(6), два канонических уровня GLM 5.2, по три Kimi K3/K3.1 Pro (6) и три Qwen
3.8 Flash. Это не заменяет сравнительного теста качества и токенов на разных
effort.

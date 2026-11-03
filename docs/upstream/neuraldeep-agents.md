# Подключение клиентов · OpenCode и tools — neuraldeep.ru API

> Раздел машиночитаемой справки. Все разделы: https://neuraldeep.ru/llms.txt · всё одним файлом: https://neuraldeep.ru/llms-full.txt

Base URL: `https://api.neuraldeep.ru/v1`
Auth: `Authorization: Bearer $YOUR_KEY`

#### Первый запуск клиента

Сначала проверьте ключ и API, затем настройте клиент. После успешного запроса переходите к [настройкам агента](https://neuraldeep.ru/docs/agent-config.md). Ниже в этом разделе примеры клиентов.

##### Ключ, адрес и модель

Откройте [кабинет](https://hub.neuraldeep.ru/app), раздел "Ключи", и создайте или скопируйте свой API-ключ. Базовый адрес для OpenAI-совместимого клиента - `https://api.neuraldeep.ru/v1`, с одним `/v1` на конце. Ключ не добавляйте в git и не публикуйте в логах или снимках экрана.

Точный идентификатор модели берите из `data[].id` ответа `GET /v1/models` с вашим ключом. Для API это имя без префикса провайдера, например `qwen3.6-35b-a3b`. Эффективное окно контекста зависит от ключа, поэтому публичной таблицы моделей недостаточно. Модель в этом списке ещё не означает, что ключ может её вызвать, например модели с оплатой по токенам видны и ключу в режиме "Подписка". Доступ окончательно подтверждает короткий запрос ниже.

##### Переменная окружения

Вставьте блок для своей оболочки целиком и нажмите Enter, затем введите ключ в скрытом приглашении. Так ключ не попадает в историю команд. Фигурные скобки, а в PowerShell конструкция `& { }`, заставляют оболочку прочитать весь блок до запроса ключа, не убирайте их. Без них в терминале, где вставка идёт построчно, следующая строка блока уходит в переменную вместо ключа, а набранный ключ выполняется как команда и сохраняется в истории.

```bash
{
  printf 'NeuralDeep API key: '
  IFS= read -rs NEURALDEEP_API_KEY
  printf '\n'
  export NEURALDEEP_API_KEY
  test -n "$NEURALDEEP_API_KEY" && printf 'NEURALDEEP_API_KEY is set\n'
}
```

```powershell
& {
  $secret = Read-Host 'NeuralDeep API key' -AsSecureString
  $env:NEURALDEEP_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
  -not [string]::IsNullOrWhiteSpace($env:NEURALDEEP_API_KEY)
}
```

Проверка выводит `NEURALDEEP_API_KEY is set` в bash/zsh или `True` в PowerShell, но не сам ключ. Переменная действует в текущем терминале и запущенных из него процессах. Запускайте клиент из этого терминала. Для графического приложения задайте переменную в его окружении запуска и перезапустите приложение. Файл `.env` сам по себе переменную в процесс не передаёт.

##### Проверка API до настройки клиента

В bash/zsh выполните два запроса. Первый печатает статус ответа и найденные модели Qwen 3.6, ожидаются `HTTP/2 200` или `HTTP/1.1 200` и строки с `qwen3.6-35b-a3b` и `qwen3.6-35b-a3b-noreason`. При другом статусе повторите запрос без `| grep ...`, чтобы увидеть текст ошибки.

```bash
curl --silent --show-error --include https://api.neuraldeep.ru/v1/models \
  -H "Authorization: Bearer $NEURALDEEP_API_KEY" \
  | grep -o -E '^HTTP/[0-9.]+ [0-9]+|"id": "qwen3[.]6-35b-a3b[^"]*"'

curl --silent --show-error --include https://api.neuraldeep.ru/v1/chat/completions \
  -H "Authorization: Bearer $NEURALDEEP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b-noreason","messages":[{"role":"user","content":"Reply with OK."}],"max_tokens":64}'
```

В PowerShell используйте отдельный блок, без bash-переносов строк и кавычек для curl.

```powershell
$headers = @{ Authorization = "Bearer $env:NEURALDEEP_API_KEY" }
$models = Invoke-RestMethod -Uri 'https://api.neuraldeep.ru/v1/models' -Headers $headers
$models.data | Select-Object id, limit

$body = @{
  model = 'qwen3.6-35b-a3b-noreason'
  messages = @(@{ role = 'user'; content = 'Reply with OK.' })
  max_tokens = 64
} | ConvertTo-Json -Depth 4
$reply = Invoke-RestMethod -Method Post -Uri 'https://api.neuraldeep.ru/v1/chat/completions' -Headers $headers -ContentType 'application/json' -Body $body
$reply.choices[0].message.content
```

Успешный чат-запрос возвращает HTTP 200 и короткий ответ в `choices[0].message.content`, обычно `OK`. Он расходует квоту или баланс ключа, как обычный запрос. Если проверка не прошла, сначала разберите HTTP-ошибку, а не меняйте конфиг клиента.

##### После первого ответа

Конструктор [настроек агента](https://neuraldeep.ru/docs/agent-config.md) использует живые лимиты из `GET /api/public/tier-limits`. Сначала выберите клиент и найдите его файл конфигурации. OpenCode получает полный конфиг с основной и вспомогательной моделями и ключом из окружения, другие профили могут быть фрагментами для существующего файла. Сделайте резервную копию и перенесите только нужные ключи, сохранив остальных провайдеров. Не все показанные числа выражены в конфиге каждого клиента, поддержка пауз, потоков и ретраев зависит от клиента и его версии.

#### Tool calling

Стандартный OpenAI tool-calling через `tools` + `tool_choice`. Модель решает когда звать инструмент, возвращает JSON с аргументами.

```python
from openai import OpenAI
client = OpenAI(api_key="$YOUR_KEY", base_url="https://api.neuraldeep.ru/v1")

tools = [{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Получает погоду в городе",
    "parameters": {
      "type": "object",
      "properties": {"city": {"type": "string"}},
      "required": ["city"],
    }
  }
}]

messages = [{"role":"user","content":"Какая погода в Москве?"}]
r = client.chat.completions.create(
    model="gpt-oss-120b",
    messages=messages,
    tools=tools,
    tool_choice="auto",
)
# r.choices[0].message.tool_calls → список вызовов
```

```bash
curl https://api.neuraldeep.ru/v1/chat/completions \
  -H "Authorization: Bearer $YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"gpt-oss-120b",
    "messages":[{"role":"user","content":"tell a short story"}],
    "stream": true,
    "max_tokens": 800
  }'
```

> Для многократных агентных итераций используй `user: session_id` чтобы сессия жила на одном upstream — prefix caching экономит токены до 10×.

#### Coding-агенты · coddy

[coddy](https://coddy.dev) - открытый агент в одном статичном Go-бинарнике: консоль, ACP-сервер для VS Code и Zed, HTTP-шлюз со встроенным веб-интерфейсом и Telegram. NeuralDeep у него не "ещё один OpenAI-совместимый провайдер", а собственный тип: ключ выдаёт вход в хаб, а остаток лимитов агент читает нашей ручкой `GET /v1/limits` и держит в футере (окна сессии и недели, время сброса, кошелёк).

```bash
curl -fsSL https://coddy.dev/install.sh | bash

# браузерный вход в хаб; на машине без браузера - тот же вход с --device
coddy providers login neuraldeep
```

Вход сам допишет провайдера и модели тарифа в `~/.coddy/config.yaml`. Ключ можно вписать и руками - он всегда сильнее сохранённого входа:

```yaml
providers:
  - name: "neuraldeep"
    type: "neuraldeep"
    api_key: "$YOUR_KEY"
    api_base: "https://api.neuraldeep.ru/v1"   # api.neuraldeep.tech/v1 - международное зеркало

models:
  - model: "neuraldeep/qwen3.6-35b-a3b"
    max_tokens: 8192

agent:
  model: "neuraldeep/qwen3.6-35b-a3b"
```

Используйте адрес API из своего кабинета. Навыки из нашего каталога coddy читает нативно: `~/.agents/skills` стоит у него в дефолтных `skills.dirs`, туда же кладёт паки `npx skillsbd install -g`. Числа таймаутов и потоков под твой тариф выдаёт конструктор в разделе "Настройки агента".

#### OpenCode

Конфиг [OpenCode](https://opencode.ai) лежит в `~/.config/opencode/opencode.json`, файл `opencode.json` в корне проекта его перекрывает. Готовый файл под ваш тариф и опции собирает [конструктор настроек агента](https://neuraldeep.ru/docs/agent-config.md), выберите в нём opencode и скопируйте результат. Ключ OpenCode берёт из переменной `NEURALDEEP_API_KEY`. Если конфиг уже есть, перенесите в него блок `provider.neuraldeep` и поля `model` и `small_model`.

#### Coding-агенты · OpenAI Codex CLI

[codex CLI](https://www.npmjs.com/package/@openai/codex) — терминальный coding-агент от OpenAI. Работает через `/v1/responses` (Responses API). На нашей стороне применены 3 файловых патча vLLM для поддержки `custom` tool types и multi-turn валидации (по issue [#33089](https://github.com/vllm-project/vllm/issues/33089)).

```toml
# ----------------- провайдер -----------------
[model_providers.neuraldeep]
name = "NeuralDeep Hub"
base_url = "https://api.neuraldeep.ru/v1"
wire_api = "responses"
experimental_bearer_token = "$YOUR_KEY"
# Альтернатива: env_key = "NEURALDEEP_API_KEY" + export в shell

# ----------------- профили -----------------
[profiles.neuraldeep]
model_provider = "neuraldeep"
model = "qwen3.6-35b-a3b"
# qwen3.6 → 256k ctx, нативные tool-calls, лучше для большой codebase

[profiles.neuraldeep-oss]
model_provider = "neuraldeep"
model = "gpt-oss-120b"
# gpt-oss-120b → 131k ctx, длинный reasoning
```

```bash
# TUI-режим с qwen3.6
codex --profile neuraldeep

# или с gpt-oss-120b
codex --profile neuraldeep-oss

# regулировка reasoning effort
codex --profile neuraldeep -c model_reasoning_effort=low
```

> **wire_api = "chat" больше не поддерживается** в новых codex (с конца 2025). Только `"responses"`. Если видишь ошибку `Error loading config.toml: wire_api = "chat" is no longer supported` — поменяй на responses.

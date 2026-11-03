# Озвучка · TTS API — neuraldeep.ru API

> Раздел машиночитаемой справки. Все разделы: https://neuraldeep.ru/llms.txt · всё одним файлом: https://neuraldeep.ru/llms-full.txt

Base URL: `https://api.neuraldeep.ru/v1`
Auth: `Authorization: Bearer $YOUR_KEY`

Тем же ключом — синтез речи под `/v1/audio/speech`: текст → аудио (WAV 24 kHz). Модель **Qwen3-TTS** на наших GPU в РФ. Доступно на **всех тарифах**, отдельная корзина — лимит считается в **символах** входного текста. Формат запроса **OpenAI-совместимый**, работает **синхронно**: отправил текст → сразу получил аудио-файл.

**8 голосов:** `vivian`, `serena`, `ono_anna`, `sohee` (жен) · `dylan`, `ryan`, `aiden`, `uncle_fu` (муж) — мультиязычные. **10 языков:** `Russian`, `English`, `German`, `French`, `Spanish`, `Italian`, `Chinese`, `Japanese`, `Korean`, `Portuguese` (+`Auto`). **Эмоцию и стиль** задаёшь свободным текстом в `instructions` («радостно», «спокойный диктор»). Список голосов: `GET /v1/audio/voices`. Остаток квоты приходит в каждом ответе заголовками `X-Quota-Day-Remaining` и `X-Quota-Month-Remaining`. Исчерпание: `429` с телом `quota_exceeded` и `Retry-After`.

**🇷🇺 Русский — с ударениями.** При `language=Russian` озвучку берёт отдельная модель **ESpeech** (F5 + RUAccent) — она **корректно ставит ударения и резолвит омографы** по контексту (открыл замо́к → вошёл в за́мок), там где обычные TTS мажут. Прочие языки — на Qwen3-TTS. Какой движок озвучил, видно в ответном заголовке `X-TTS-Engine` (`espeech`/`qwen`). Хочешь задать ударение вручную — поставь `+` перед ударным гласным (`«зам+ок»`); если `+` уже есть в тексте, авто-акцентизатор не вмешивается.

```bash
# синтез (голос serena, русский) → файл
curl -s https://api.neuraldeep.ru/v1/audio/speech \
  -H "Authorization: Bearer $YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"input":"Привет! Это синтез речи на наших серверах.","voice":"serena","language":"Russian"}' \
  -o speech.wav

# с эмоцией (через instructions)
curl -s https://api.neuraldeep.ru/v1/audio/speech \
  -H "Authorization: Bearer $YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"input":"Поздравляю с релизом!","voice":"vivian","language":"Russian","instructions":"радостно, с энтузиазмом"}' \
  -o happy.wav

# ударение вручную через «+» (зам+ок = запор) — RUAccent не вмешивается, если «+» уже есть
curl -s https://api.neuraldeep.ru/v1/audio/speech \
  -H "Authorization: Bearer $YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"input":"Он повесил амбарный зам+ок.","voice":"serena","language":"Russian"}' \
  -o stress.wav

# список голосов
curl https://api.neuraldeep.ru/v1/audio/voices -H "Authorization: Bearer $YOUR_KEY"
```

```python
import httpx

r = httpx.post(
    "https://api.neuraldeep.ru/v1/audio/speech",
    headers={"Authorization": "Bearer $YOUR_KEY"},
    json={"input": "Текст для озвучки.", "voice": "dylan", "language": "Russian"},
)
open("speech.wav", "wb").write(r.content)
```

> Лимит считается в символах текста (`len(input)`), а не в запросах. Клонирование голоса по образцу пока недоступно.

**Ограничения на вход и ошибки.**

- `input` обязателен, до 5 000 символов на вызов. Пустой текст `400`, длиннее `413`. Длинный текст режьте по предложениям и склеивайте аудио.
- Неизвестный `voice` даёт `400` со списком голосов. Голоса OpenAI (`alloy`, `nova` и другие) подменяются на близкие наши, поэтому OpenAI SDK работает как есть: `client.audio.speech.create(model="tts-1", voice="alloy", input=...)`. Какой голос озвучил, видно в заголовке `X-TTS-Voice`.
- Ответ: WAV, 24 кГц, моно, 16 бит. Ответ должен уложиться в 120 секунд.
- Попытка клонировать голос: `403`. Сбой синтеза: квота возвращается, приходит ошибка со статусом движка.

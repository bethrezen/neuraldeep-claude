# Диаризация · кто когда говорил — neuraldeep.ru API

> Раздел машиночитаемой справки. Все разделы: https://neuraldeep.ru/llms.txt · всё одним файлом: https://neuraldeep.ru/llms-full.txt

Base URL: `https://api.neuraldeep.ru/v1`
Auth: `Authorization: Bearer $YOUR_KEY`

Тем же ключом — разметка записи по спикерам под `/v1/audio/diarize`: аудио → отрезки «кто когда говорил». Модель **Nemotron-3-Diarization** на наших GPU в РФ, до **8 спикеров**, любой аудиоформат (WAV, MP3, OGG, M4A и другие), файл до 500 МБ и до 4 часов. Текст модель не распознаёт: для стенограммы по спикерам склейте ответ с `/v1/audio/transcriptions` по времени. Отдельная корзина — лимит считается в **минутах аудио**, округление вверх.

```bash
curl -s https://api.neuraldeep.ru/v1/audio/diarize \
  -H "Authorization: Bearer $NEURALDEEP_API_KEY" \
  -F file=@meeting.mp3
```

Ответ:

```json
{"duration": 61.0, "num_speakers": 2, "minutes_charged": 2,
 "segments": [{"speaker": "SPEAKER_0", "start": 1.1, "end": 5.75},
              {"speaker": "SPEAKER_1", "start": 17.28, "end": 21.26}]}
```

Номера спикеров идут по порядку первого появления. Поля формы: `response_format=rttm` вернёт стандартный RTTM, `min_duration=0.3` выбросит обрывки короче 0.3 с. Остаток минут: `GET /v1/audio/diarize/quota`, в блоках `day` и `month` поля `used`, `limit`, `remaining` и `reset_at`, как у поиска, OCR и картинок.

**Ограничения на вход и ошибки.** Пустой файл `400`, файл больше 500 МБ `413`, запись длиннее 4 часов `413`, нечитаемое аудио `400`, `response_format` кроме `json` и `rttm` даёт `400`. Ответ должен уложиться в 300 секунд. Кончились минуты: `429` с `X-Quota-Pool`, `X-Quota-Scope`, `X-Quota-Reset` и `Retry-After`. Пустой кошелёк у ключа в режиме «Кошелёк»: `402`. Сбой на нашей стороне: `502`.

Модель обучена без русского; на русской речи разметка спикеров и смен у нас совпала с эталоном, но первые секунды реплики иногда остаются без спикера.

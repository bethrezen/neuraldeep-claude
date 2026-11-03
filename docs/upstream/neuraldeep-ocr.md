# OCR · распознавание документов — neuraldeep.ru API

> Раздел машиночитаемой справки. Все разделы: https://neuraldeep.ru/llms.txt · всё одним файлом: https://neuraldeep.ru/llms-full.txt

Base URL: `https://api.neuraldeep.ru/v1`
Auth: `Authorization: Bearer $YOUR_KEY`

Тем же ключом — OCR для PDF и картинок (PNG/JPG/WEBP/BMP/TIFF). Эндпоинты под `/v1/ocr/*`. Доступно на **всех тарифах**, с отдельной от чата корзиной — лимит считается в **страницах**.

Работает **асинхронно**: загружаешь документ → получаешь `job` → опрашиваешь статус (не чаще раза в секунду) → забираешь результат в `markdown`/`json`/`text`. Для разметки по координатам есть PNG-preview страницы (та же система координат, что и bbox). Профиль один, `fast`: прежний `pro` снят, запрос с ним молча идёт как `fast`. Остаток страниц: `GET /v1/ocr/quota` или `GET /v1/ocr/balance`. Когда страницы кончились, придёт `429` с телом `quota_exceeded` и `Retry-After`.

**Ограничения на вход.**

- Файл до 50 МБ, иначе `413`. Пустой файл `400`.
- До 500 страниц в одном запросе, иначе `413`. Заранее это проверяется, только если передан `page_ranges`, без него страницы считаются после разбора документа.
- `page_ranges` строкой: `1-5,8,10-12`.
- Формат проверяет сам движок: неподдержанный файл вернёт `415` или `422`.
- Заголовок `Idempotency-Key` защищает от двойного списания при повторе. Тот же ключ вернёт сохранённый ответ с `idempotent_replay: true`, тот же ключ с другими параметрами даст `422`, а пока первый запрос в работе, `409`.
- Чужая или несуществующая задача: `404`. Пустой кошелёк у ключа в режиме «Кошелёк»: `402`.

```bash
# 1. загрузить (вернёт {"id":"job_...","page_count":N})
curl https://api.neuraldeep.ru/v1/ocr/extract \
  -H "Authorization: Bearer $YOUR_KEY" \
  -F "file=@invoice.pdf"
# (диапазон страниц: -F 'page_ranges=1-5,8')

# 2. статус задачи
curl https://api.neuraldeep.ru/v1/ocr/jobs/job_123 \
  -H "Authorization: Bearer $YOUR_KEY"

# 3. результат в markdown
curl "https://api.neuraldeep.ru/v1/ocr/jobs/job_123/result?format=markdown" \
  -H "Authorization: Bearer $YOUR_KEY"
```

```python
import time, httpx

H = {"Authorization": "Bearer $YOUR_KEY"}
# 1. загрузка
with open("invoice.pdf", "rb") as f:
    job = httpx.post(
        "https://api.neuraldeep.ru/v1/ocr/extract",
        headers=H, files={"file": f},
    ).json()
jid = job["id"]
print("страниц:", job["page_count"], "списано:", job["scan_pages_charged"])

# 2. поллинг (раз в секунду)
while True:
    st = httpx.get(f"https://api.neuraldeep.ru/v1/ocr/jobs/{jid}", headers=H).json()
    if st["status"] == "completed":
        break
    time.sleep(1)

# 3. результат
res = httpx.get(
    f"https://api.neuraldeep.ru/v1/ocr/jobs/{jid}/result",
    params={"format": "markdown"}, headers=H,
).json()
print(res["content"])
```

> Статус, результат и preview не списывают лимит, платите только за страницы при загрузке.

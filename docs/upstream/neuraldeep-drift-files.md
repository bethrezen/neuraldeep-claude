# Drift · файлы + sandbox preview — neuraldeep.ru API

> Раздел машиночитаемой справки. Все разделы: https://neuraldeep.ru/llms.txt · всё одним файлом: https://neuraldeep.ru/llms-full.txt

Base URL: `https://drift.neuraldeep.ru/v1`
Auth: `Authorization: Bearer dft_...`

У Drift'а свой workspace в MinIO (per-user, изолированный) и под капотом — Docker-sandbox с предустановленными `openpyxl / pandas / pdfplumber / pypdf / python-docx / Pillow / chardet / bs4 / lxml`. Аплоадишь файл — он попадает и в MinIO, и сразу в sandbox; модель видит **preview первых страниц/строк** в init-промпте без лишних tool-calls.

```bash
curl -X POST https://drift.neuraldeep.ru/v1/files/upload \
  -H "Authorization: Bearer dft_xxxxxxxx" \
  -F file=@./report.pdf
# → {"uploaded":[{"name":"report.pdf","path":"report.pdf","size":48863,
#                 "preview":"...первые 2 страницы PDF..."}]}
```

```python
import httpx
TOKEN = "dft_xxxxxxxx"
BASE  = "https://drift.neuraldeep.ru/v1"

# 1) upload
with open("report.pdf","rb") as f:
    up = httpx.post(f"{BASE}/files/upload",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                    files={"file": ("report.pdf", f, "application/pdf")}).json()
print("preview:", up["uploaded"][0]["preview"][:200])

# 2) ask agent — он уже видит preview в init prompt
r = httpx.post(f"{BASE}/chat/completions",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json={"model":"qwen3.6-35b-a3b","messages":[
        {"role":"user","content":"Резюмируй report.pdf"}
    ]}).json()
print(r["choices"][0]["message"]["content"])
```

> Preview-форматы: PDF → 2 страницы (pdfplumber), XLSX → первый лист 20 строк (openpyxl), CSV/TXT/JSON/MD → 6000 символов, DOCX → 6000 символов. Для остального — preview `null`, модель сама позовёт `read_file` или python в sandbox.

> **Лимиты:** 20 MB на файл, 8 файлов на запрос. Sandbox UTF-8, кириллица в именах работает.
> **analyze_image** работает *только* на растровых картинках (.png/.jpg/.webp/...). PDF читай через preview или `pdfplumber`.

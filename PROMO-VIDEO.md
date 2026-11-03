# Создание промо-видео для NeuralDeep для Claude Code

## Что это за проект

**NeuralDeep для Claude Code** — это локальный шлюз (переносимый), который подключает все модели и сервисы российской AI-платформы NeuralDeep к популярному CLI-инструменту Claude Code и десктопному приложению Claude Desktop.

Проект позволяет разработчикам в России получить доступ к моделям Qwen 3.8, GPT-OSS, DeepSeek, GLM, Kimi, Claude через знакомый интерфейс Claude Code, без сторонних прокси и с прямой интеграцией в API NeuralDeep.

## Ключевые сообщения

1. **«Все модели NeuralDeep в Claude Code»** — главная идея. Один шлюз, десятки моделей.
2. **Без прокси, без зависимостей** — прямое HTTPS-соединение, Python 3.10+ только.
3. **Модульные сервисы** — OCR, изображения, музыка, TTS, транскрипция, поиск и другие сервисы NeuralDeep работают как отдельные MCP инструменты.
4. **Переносимость** — Linux, Windows, macOS; `--activate` одной командой.

## Структура промо-видео (60 секунд)

### 0:00–0:08 — Проблема (Hook)
- Скриншот терминала с приглашением `$ claude ...`
- Текст на экране: «Хотите использовать российские AI-модели вместе с Claude Code?»
- Быстрая анимация: логотип NeuralDeep + Claude Code соединяются

### 0:08–0:18 — Решение
- Показываем простую установку: `.env` → `./install.sh --activate`
- Терминал показывает успешный запуск gateway на localhost:8787
- Пикер моделей в Claude Code: список Qwen, GPT-OSS, DeepSeek, Kimi...

### 0:18–0:35 — Архитектура
- Анимированная схема: `Claude Code → Local Gateway → NeuralDeep API`
- Подсветка: формат переводится, маршрутизация по billing, effort/thinking
- Показать что шлюз работает локально, прокси нет

### 0:35–0:50 — Сервисы (showcase)
- Быстрая нарезка карточек сервисов: OCR, Images, Music, TTS, Search
- Каждый сервис — отдельный значок/карточка с анимацией появления
- Команда: `python scripts/nd.py services enable all`

### 0:50–1:00 — Призыв к действию
- GitHub URL repo
- Быстрый гайд по установке в трёх строках
- Логотип NeuralDeep + слоган

## Ссылки на референсы стиля

Ищем вдохновение в промо-видео:
- **[Linear.app](https://linear.app)** — минималистичные tech-видео с плавными анимациями
- **[Vercel.com](https://vercel.com)** — тёмная тема, градиенты, код-презентация
- **[Cursor.sh](https://cursor.sh)** — AI-IDE promo с демонстрацией интерфейса
- **[Roo Code](https://roocode.com)** — AI coding tools demo style
- **[Supabase](https://supabase.com)** — open-source product promos

Ключевые элементы стиля:
- Тёмный фон (#0a0a0f или подобный)
- Градиенты: синий → голубой → фиолетовый
- Моноширинный шрифт для кода (JetBrains Mono, Fira Code)
- Плавные fade/slide анимации элементов
- Звуковое сопровождение: lo-fi ambient / electronic chill

## Музыка

Для фона подойдёт спокойный электронно-ambient трек без вокала. Варианты:

1. **Нейтральные библиотеки**: YouTube Audio Library, Free Music Archive, Incompetech
2. **Стиль**: lo-fi beats (60-80 BPM), ambient pads, subtle synth textures
3. **Темп**: медленно-средний — соответствует серьёзному инструменту разработки, не должен быть агрессивным
4. Для синтеза музыки можно использовать [NeuralDeep Music](https://neuraldeep.ru) через Lyria 3 Pro с промптом типа "calm ambient electronic background music, no vocals, lo-fi aesthetic, 70 bpm"

## Техническая реализация видео

### Способ A: After Effects / Fusion
- Таймлайн 60 секунд
- Шрифты: Inter (UI тексты), JetBrains Mono (код)
- Элементы: скриншоты терминала, схемы архитектуры, анимированные карточки

### Способ B: CSS/HTML демо (веб-видео)
- Промо-страница в `promo/index.html` уже создаёт интерактивную версию
- Запись экрана через OBS / ffmpeg → MP4
- Автопрокрутка секций с таймингами

### Способ C: Figma → Exports
- Создать макеты в Figma
- Export as PNG sequence
- Assemble in FFmpeg or Premiere

### Рекомендация
Начать с HTML-версии (`promo/index.html`) — она уже есть в проекте. Можно записать скрин с автопрокруткой через FFmpeg для быстрого MVP-видео, затем сделать полноценное видео в редакторе.

## Quick start записи экрана (FFmpeg)

```bash
# Автопрокрутка страницы на 60 секунд → запись 1920x1080
timeout 60 firefox promo/index.html &
sleep 2
ffmpeg -f x11grab -video_size 1920x1080 -i :0.0 \
       -f alsa -i pulse \
       -t 60 -c:v libx264 -preset ultrafast -crf 18 \
       -c:a aac -b:a 192k \
       output.mp4
kill %1 2>/dev/null
```

## Готовые материалы

| Файл | Описание |
|------|----------|
| [promo/index.html](promo/index.html) | Интерактивная промо-страница (готовая к записи) |
| [README.md](README.md) | Упрощённое описание для GitHub |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Полное описание архитектуры |
| [prompts/image-prompt.txt](image-prompt.txt) | Промпт для генерации промо-изображения |

## Checklist создания видео

- [ ] Набрать storyboard (подробную раскадровку)
- [ ] Подобрать/сгенерировать фоновую музыку
- [ ] Создать анимированный intro (логотип NeuralDeep × Claude Code)
- [ ] Записать скриншоты/скринкасты работы CLI
- [ ] Нарисовать анимированную схему архитектуры
- [ ] Создать карточки сервисов (OCR, Images, Music, TTS...)
- [ ] Добавить звуковые эффекты (клик, ввод команды, уведомление)
- [ ] Смонтажировать в редакторе (Premiere, DaVinci Resolve, Final Cut)
- [ ] Наложить музыку и звуковые эффекты
- [ ] Экспорт: 1920×1080, H.264, ~10 Mbps
- [ ] Добавить endcard с GitHub URL

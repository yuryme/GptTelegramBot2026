# Telegram AI-ассистент (напоминалка)

Исследовательский проект Telegram-бота, где бизнес-логика обработки пользовательских запросов вынесена в LLM-ассистента. Пользователь общается естественным языком, LLM формирует структурированные команды, а приложение валидирует и исполняет их.

## Текущий статус

- Локально работает.
- Тесты: `55 passed`.
- Текущее ограничение: лимиты OpenAI.
- Выполнен ручной VPS-деплой в режиме `polling` (без Docker).

## Ключевой функционал

- Создание напоминаний: одиночные, множественные, цикличные.
- Для циклических напоминаний используется модель `одна активная основная запись + перенос run_at через reschedule()`.
- Основная запись циклического напоминания хранит исходный `recurrence_rule`; цикл не разворачивается заранее в пачку основных записей.
- Для напоминаний с датой начиная с завтра выполняются два уведомления: за 1 час и в due time.
- Предуведомление за 1 час является внутренним и не отображается в пользовательских списках; для cyclic создается только для ближайшего запуска.
- Расчет повторов (`FREQ`, `INTERVAL`, `UNTIL`) выполняется единым механизмом; `UNTIL` реально ограничивает цикл.
- Просмотр списков: все, на сегодня, с фильтрами.
- Удаление напоминаний: по фильтру и последние `N`.
- Удаление по `#ID` (`reminder_id`) и soft-delete (физического удаления нет).
- Плановая отправка напоминаний фоновым планировщиком.
- LLM-only распознавание команд (без локальных «костылей» парсинга).
- Для `list_reminders` используется fast-path без дополнительных LLM-уточнений/нормализаций, чтобы уменьшить задержку ответа.
- При невалидном JSON от LLM выполняется LLM-recovery в строгий формат команды.
- Поддержан голосовой ввод (`voice`/`audio`): бот распознает речь через OpenAI STT и обрабатывает результат как обычный текстовый запрос.
- Текстовые и голосовые запросы после получения текста проходят единый кодовый путь бизнес-обработки.
- Для голосовых и текстовых команд с относительными днями (`сегодня/завтра/послезавтра`) добавлена защита от ошибочной даты `run_at`: дата берется из day-reference, время извлекается отдельно.
- Временная нормализация централизована в `app/services/temporal_normalizer.py`: единая точка для приведения day-reference/date/time перед исполнением create-команд.
- Усилен prompt интерпретации времени: поддержаны словесные формы (например, `в десять часов утра`, `в полдень`), а при неоднозначности AM/PM по умолчанию используется AM (`в десять` -> `10:00`).
- `_repair_create_command_dates()` применяется только для create-команды с одним reminder; для multi-reminder repair отключен.
- Режим доставки Telegram настраивается через `.env`: `webhook` или `polling`.
- В `/start` отображается клавиатура с кнопками:
  - `Показать напоминания на сегодня`
  - `Показать все напоминания`
  - `Настройка`
- В разделе `Настройка`:
  - `Модели`: выводит доступные модели, цену за `1M` токенов (по локальному справочнику) и позволяет выбрать активную модель для текущего процесса бота.
  - `Лимиты`: пытается показать лимит/расход/остаток по API-аккаунту; при недоступности billing endpoint показывает fallback с локальными лимитами.
- Безопасное удаление: массовое удаление запрещено без явного подтверждения `confirm_delete_all=true`.
- Циклические напоминания привязываются к серии (`series_id`) в таблице `reminder_series`.
- Журнал действий пользователя сохраняется в `reminder_actions` (аудит create/list/delete).

## Технологии

- `Python 3.12`
- `FastAPI` + `aiogram 3`
- `PostgreSQL` + `SQLAlchemy 2` + `Alembic`
- `APScheduler`
- `Pydantic v2`
- `pytest` + `pytest-asyncio`
- `Docker` / `docker compose`

## Архитектурные принципы

- `Schema-first`: LLM отдает JSON, который валидируется Pydantic-схемами.
- `Temporal normalization`: смысловая нормализация даты/времени выполняется отдельным слоем после валидации схемы и до бизнес-исполнения.
- `Semantic draft layer`: for create flows, LLM returns semantic draft JSON first, then deterministic Python compiles draft -> final executable command JSON.
- `Internal recurrence policy layer`: semantic draft compiler now builds explicit internal recurrence model (kind/interval/end) before mapping to legacy `recurrence_rule`.
- `Internal display policy layer`: pre-reminder behavior is represented by an internal display policy model (auto/disabled/minutes_before) without expanding public command JSON.
- Изменения интерпретации фраз делаются через prompt/схемы, а не через разрастание if/else-логики.
- Время хранится в UTC, пользовательская интерпретация времени учитывает `app_timezone`.
- Delete contract in `SYSTEM_PROMPT_RU` is explicitly enforced:
  - status values: `pending/done/deleted`
  - mass delete requires `confirm_delete_all=true`
  - delete by id uses `reminder_id`

## Важные текущие детали

- Диспетчер напоминаний: `app/services/reminder_dispatcher.py`.
- Единый фильтр выборки напоминаний: `SelectionFilter` в `app/services/reminder_service.py`.
- Планировщик запускается в `app/main.py` и периодически отправляет due-напоминания.
- Формат вывода списка в Telegram: `dd.mm.yyyy HH:MM` (без секунд).
- Локализация статусов в списке:
  - `pending` -> `в ожидании`
  - `done` -> `выполнено`
- Выбор модели через кнопку `Модели` действует в рамках текущего запущенного процесса (после рестарта возвращается значение из `OPENAI_MODEL`).
- Для локальной разработки поддержан отдельный тестовый Telegram-токен:
  - `TELEGRAM_BOT_TOKEN_TEST`
  - `TELEGRAM_USE_TEST_BOT=true` (в этом режиме бот использует тестовый токен).
- Модель распознавания речи задается через `OPENAI_TRANSCRIPTION_MODEL` (по умолчанию `gpt-4o-mini-transcribe`).
- Для Windows + PostgreSQL в async-режиме используется драйвер `asyncpg` (автопереключение при `DATABASE_URL=postgresql+psycopg://...`), чтобы исключить конфликт `ProactorEventLoop` в планировщике.
- В репозитории очищены временные локальные артефакты; каталоги рантайм-логов и локальные секреты исключены через `.gitignore`.

## Запуск локально

```bash
docker compose up -d --build
```

Переключение режима доставки Telegram:

```env
TELEGRAM_DELIVERY_MODE=webhook  # или polling
TELEGRAM_POLLING_DROP_PENDING_UPDATES=true
```

Проверка здоровья:

```bash
curl http://localhost:8000/healthz
```

## Рабочий процесс (локально -> сервер)

1. Разработка и эксперименты выполняются локально.
1.1. Изменения логики работы бота сначала согласовываются с пользователем, затем внедряются.
2. Локально проходят проверки (тесты/ручной smoke).
3. Изменения фиксируются в Git (`commit`) и отправляются в GitHub (`push`).
4. На сервер выкатывается ровно этот коммит.
5. После деплоя выполняется smoke-проверка на сервере:
   - `systemctl status telegram-reminder-bot`
   - `journalctl -u telegram-reminder-bot -n 50 --no-pager`
   - `curl http://127.0.0.1:8000/healthz`

Важно: сервер не синхронизируется с GitHub автоматически, деплой выполняется отдельным шагом.

## Защита кодировки (UTF-8)

- Политика репозитория:
  - `.editorconfig`: `charset = utf-8`, `end_of_line = lf`, `insert_final_newline = true`.
  - `.gitattributes`: единый `text eol=lf` для `*.py`, `*.md`, `*.yml`, `*.yaml`, `*.json`, `*.toml`, `*.ini`, `*.txt`.
  - Для исходников BOM запрещен.
- Локальные проверки (pre-commit):
  - `encoding-utf8-check` — файл обязан декодироваться как UTF-8.
  - `encoding-no-bom-check` — BOM запрещен для `*.py`, `*.json`, `*.yml`, `*.yaml`, `*.toml`, `*.md`.
  - `encoding-mojibake-check` — блокирует типичные паттерны битой кириллицы (`Р...`, `С...`, `Ð...`, `Ñ...`).
- CI gate:
  - отдельный job `encoding-check` в `.github/workflows/encoding-check.yml`;
  - запускается для `push` в `main` и `pull_request` в `main`;
  - повторяет те же три проверки и блокирует merge при ошибках.
- Диагностика и безопасная починка:
  - Проверка всего репозитория: `python scripts/check_encoding.py --check`
  - Точечная проверка: `python scripts/check_encoding.py --check --paths app tests`
  - Безопасная автопочинка известных случаев: `python scripts/check_encoding.py --fix`
  - Ограничение типа проверок: `--check-type utf8|bom|mojibake` (можно повторять флаг).
  - Исключения (allowlist): `scripts/encoding_allowlist.txt` в формате `issue_type:path_glob` или `path_glob`.
- Если проверка упала:
  - исправьте файл в UTF-8 без BOM;
  - удалите/исправьте подозрительную строку mojibake;
  - при осознанном исключении добавьте точечное правило в allowlist и укажите причину в комментарии.

## Документация

- План проекта: `PROJECT_PLAN.md`
- Локальный чек-лист: `docs/LOCAL_TESTING.md`
- Реестр ТЗ и согласований: `docs/tasks/INDEX.md`
- Правила хранения ТЗ: `docs/tasks/README.md`
- Шаблон нового ТЗ: `docs/tasks/templates/TASK_TEMPLATE.md`
- VPS-деплой: `deploy/DEPLOY_VPS.md`
- Управление сервисом с Windows: `scripts/bot_service.bat`

- Совместимость schema-first для create_reminders: при day_reference=specific_date принимаются оба ключа даты (date_value и legacy specific_date) с нормализацией во внутренний date_value.

## Recurring End Policy (Iteration 03+)

- Recurring reminders are no longer open-ended: runtime enforces `UNTIL` for recurring rules if user did not provide explicit end.
- Default deterministic end boundaries:
  - `HOURLY` -> end of start day.
  - `DAILY` -> end of start week (Sunday).
  - `WEEKLY` -> end of start month.
  - `MONTHLY` -> end of start year.
- Explicit user end still has priority (`until_date` / `until_datetime`).
- Ambiguous end expressions (e.g. `до следующей недели`, `пока не ...`) are rejected at compile stage to avoid silent wrong `UNTIL`.
- Interval extraction supports Russian forms with step (`каждые 2 часа`, `каждые 2 недели`, `каждые 2 месяца`).

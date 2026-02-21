# Telegram AI-ассистент (напоминалка)

Исследовательский проект Telegram-бота, где бизнес-логика обработки пользовательских запросов вынесена в LLM-ассистента. Пользователь общается естественным языком, LLM формирует структурированные команды, а приложение выполняет их через безопасный слой функций.

## Кратко о функционале

- Создание напоминаний: одиночные, множественные, цикличные.
- Просмотр списков: все, на сегодня, по статусу, по поиску, по временному интервалу.
- Удаление напоминаний: по фильтрам и с ограничением количества (например, последние `N`).
- Только точные указания времени (без "вечером", "перед обедом" и т.п.).
- Если день указан без времени:
  - для "сегодня" используется ближайший полный час от текущего момента;
  - для любого будущего дня ("завтра", "послезавтра", "во вторник" и т.д.) используется `08:00`.
- Русский язык во всем пользовательском взаимодействии.

## Подход к реализации

- `Schema-first`: команды LLM описываются строгими JSON/Pydantic-схемами.
- Бизнес-логика интерпретации фраз живет в prompt и LLM-слое.
- Код приложения валидирует команды, вызывает функции и работает с БД.
- Все изменения в поведении вносятся через prompt и схемы, а не через разрастание условной логики в коде.

## Планируемые средства реализации

- Язык: `Python 3.12`.
- Telegram: `aiogram 3`.
- Webhook/API слой: `FastAPI`.
- База данных: `PostgreSQL`.
- ORM и миграции: `SQLAlchemy 2` + `Alembic`.
- Схемы и валидация: `Pydantic v2`.
- Планировщик напоминаний: `APScheduler`.
- Тесты: `pytest` + `pytest-asyncio`.
- Контейнеризация: `Docker` + `docker compose`.
- Деплой: VPS (`nginx` + HTTPS + systemd/docker compose).

## Ограничения проекта

- Бюджет на модели: до `$10/месяц`.
- Единственный интерфейс: Telegram.
- Оффлайн-режим не требуется.

## Документация прогресса

- Подробный пошаговый план с чекбоксами: `PROJECT_PLAN.md`.
- По мере реализации чекбоксы и описание этапов будут обновляться.

## Быстрый старт (Этап 1)

- Локальный запуск API:
  - `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Проверка healthcheck:
  - `GET /healthz`
- Локальный запуск через Docker:
  - `docker compose up --build`
- Миграции:
  - `alembic upgrade head`

## Что добавлено на Этапе 2

- `Schema-first` команды LLM в `app/schemas/commands.py`.
- Валидация ответа модели и парсинг JSON-команд в `app/services/llm_service.py`.
- Базовый системный prompt на русском языке в `app/llm/prompts.py`.
- Правило времени по умолчанию:
  - `today` без времени -> ближайший полный час;
  - будущий день без времени -> `08:00`.

## Что добавлено на Этапе 3

- Сервис создания напоминаний `app/services/reminder_service.py`:
  - создание одного и нескольких напоминаний;
  - поддержка `recurrence_rule` для цикличных напоминаний.
- Репозиторий `app/repositories/reminder_repository.py` для сохранения в БД.
- Интеграция в Telegram-обработчик `app/telegram/handlers.py`:
  - получение команды от LLM;
  - создание напоминаний в БД;
  - отправка подтверждения пользователю.
- Тесты создания в `tests/test_reminder_service.py`.

## Что добавлено на Этапе 4

- Списки и фильтры в репозитории `app/repositories/reminder_repository.py`:
  - все;
  - на сегодня;
  - по статусу;
  - по поиску;
  - по временному интервалу.
- Сервисный слой списков `ReminderService.list_from_command(...)` в `app/services/reminder_service.py`.
- Поддержка команды `list_reminders` в Telegram-обработчике `app/telegram/handlers.py`.
- Тесты сценариев списка и фильтрации в `tests/test_list_service.py`.

## Что добавлено на Этапе 5

- Удаление напоминаний по фильтру и режиму последних `N`:
  - `app/services/reminder_service.py` (`delete_from_command`);
  - `app/repositories/reminder_repository.py` (`list_last_n`, `delete_by_ids`).
- Поддержка команды `delete_reminders` в `app/telegram/handlers.py`.
- Валидация схемы удаления в `app/schemas/commands.py`:
  - для `mode=last_n` поле `last_n` обязательно.
- Тесты удаления в `tests/test_delete_service.py`.

## Что добавлено на Этапе 6

- Логирование приложения:
  - `app/observability/logging_config.py`,
  - инициализация в `app/main.py`.
- Защита от дублей webhook:
  - `app/services/webhook_dedup.py`,
  - применение в `app/api/routes.py` по `update_id`.
- Контроль бюджета LLM и трекинг расхода:
  - `app/services/cost_control.py`,
  - подключение в `app/services/llm_service.py`.
- Ретраи LLM-вызова при временных ошибках (`RateLimit/Connection/Timeout`) в `app/services/llm_service.py`.
- Тесты инфраструктуры и бюджета:
  - `tests/test_dedup_and_cost.py`,
  - `tests/test_llm_budget.py`.

## Что добавлено на Этапе 7

- Production compose для VPS: `deploy/docker-compose.prod.yml`.
- Шаблон production-переменных: `deploy/.env.prod.example`.
- `nginx` конфиг для webhook и TLS: `deploy/nginx/telegram-bot.conf`.
- `systemd` unit для автозапуска: `deploy/systemd/telegram-reminder-bot.service`.
- Пошаговая инструкция деплоя: `deploy/DEPLOY_VPS.md`.

## Локальная проверка перед VPS

- Автоматический прогон: `scripts/local_integration_check.ps1`
- Чек-лист ручного smoke: `docs/LOCAL_TESTING.md`

## Анти-риски расходов (guardrails)

- Per-chat rate limit: ограничение частоты запросов пользователя.
- Fail-fast на `429` (лимит/квота OpenAI), без долгих повторов.
- Circuit breaker: временная пауза LLM-вызовов при серии ошибок.
- Alert-пороги бюджета: лог-предупреждения на `50%`, `80%`, `100%`.
- Пропуск устаревших webhook-апдейтов после простоя.

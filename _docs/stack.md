# Стек

Формат: Слой — Технология — Обоснование. Решение агента-разработчика; Арсен оспаривает любую строку.
ID моделей и цены в код не вписываются: берутся из настроек и таблицы `model_catalog`.

| Слой | Технология | Обоснование |
|---|---|---|
| Frontend (Mini App) | TypeScript, Next.js, React, Tailwind, Telegram WebApp SDK | Стек курса, один шаблон, тема из Telegram, адаптивность под телефон |
| Backend | Python 3.12, FastAPI, Uvicorn | Webhook и API Mini App в одном сервисе; единый язык с V1 и SDK Model Studio |
| Telegram | aiogram 3 + прямые вызовы Bot API для новых методов | Асинхронность, состояния; новые методы (`sendMessageDraft` и др.) вызываются напрямую, если библиотека их не знает |
| Очереди и задачи | Redis 7, arq | Долгие операции (генерации, исследования) идут в фоне, бот отвечает сразу; расписания |
| База данных | PostgreSQL 16, SQLAlchemy 2, Alembic | Транзакции для денег, миграции; Prisma не используется: один слой доступа к базе |
| Кэш | Redis | Лимиты, сессии Mini App, блокировки от двойных операций |
| Файловое хранилище | Локальный том с квотой, затем S3 Timeweb | Видео и архивы не помещаются на диск сервера |
| Авторизация | Telegram `initData` с проверкой HMAC и срока жизни | Вход без паролей; роли по Telegram ID из серверного реестра |
| AI/LLM | Модель семейства Qwen через OpenAI-совместимый API Model Studio; `dashscope` для медиа | Решение ТЗ; ID модели в `.env` (по ТЗ `qwen3.8-max`, подтверждается по каталогу), дешёвая модель для служебных задач |
| Песочница | Отдельный контейнер без сети, лимиты CPU и памяти, таймаут 60 с; Playwright для скриншотов | Сгенерированный код не может навредить серверу |
| Платежи | Telegram Stars (`XTR`) | Оплата внутри Telegram; идемпотентная запись по `telegram_payment_charge_id` |
| Инфраструктура | Docker Compose, Nginx, certbot, VPS Timeweb | Решения ТЗ; версия Python закреплена в образе |
| Мониторинг | `/health`, JSON-логи, алерт Арсену в Telegram, Zabbix-agent | Арсен узнаёт о падении раньше участников |
| Безопасность | `gitleaks` в pre-commit и CI, `.env` раздельные для test и prod | Секреты не попадают в Git, логи и чат |
| Мультиарендность и язык | `tenant_id` во всех таблицах, тексты в файлах i18n | White-label и английский язык позже без переписывания |

## Отличие от минимального стека курса

Курс (урок 02) требует для веб-приложения: TypeScript, Next.js, React, Tailwind, Docker, Dokploy, Yandex Object Storage, PostgreSQL, Prisma.
Для Mini App взяты TypeScript, Next.js, React, Tailwind, Docker и PostgreSQL. Вместо Dokploy и Yandex Object Storage стоят Docker Compose и S3 Timeweb (решение Арсена о хостинге), вместо Prisma — SQLAlchemy,
потому что ядро на Python и работает с базой одно. Навыки, которые собирают проекты клиентов, остаются на стеке курса.

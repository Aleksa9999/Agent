# С чего начать новому агенту

Если у тебя нет доступа к репозиторию, владелец передаст папку с документами и архив исходников `source/googlagent-source.zip`.

## Порядок чтения (30–40 минут)

1. `AGENTS.md`, `CLAUDE.md`: правила, раскладка кода, переменные окружения.
2. `_docs/decisions.md`: решения владельца (главный источник правды).
3. `_docs/handoff.md`: что сделано, где стенд, мины, открытые вопросы, что делать дальше.
4. `_docs/user-journey.md`: весь путь человека по продукту.
5. `_docs/project.md`, `_docs/skills-model.md`, `_docs/placement-test.md`, `_docs/stack.md`.
6. `_specs/wave-1-concept/spec.md` и `tasks/*.md`: критерии приёмки и статусы срезов.
7. Для работы над навыками: `_docs/author-guide.md`, `_docs/skill-building-guide.md`, `content/skills/_FORMAT.md`.
8. Для сервера: `deploy/README.md`.

## Первые действия

1. Установить зависимости (`pip install -r requirements-dev.txt`, в `miniapp/` выполнить `npm ci`) и запустить `make check`: должны пройти все проверки.
2. Взять первую незаблокированную задачу из `_specs/wave-1-concept/tasks/` (статус `todo`, все блокировки `done`), сменить статус на `in-progress`, реализовать, закрыть критерии, поставить `done`.
3. Каждый срез: тесты, `make check`, коммит `<область>: <описание>` с трейлером `Spec: wave-1-concept/NN`, пуш, обновление `_docs/handoff.md`.

## Шаблон первого сообщения новому агенту

```
Ты продолжаешь проект Googlagent (Telegram-бот и Mini App, студия SuperAi Studio).
Прочитай по порядку: AGENTS.md, CLAUDE.md, _docs/decisions.md, _docs/handoff.md, _docs/START-HERE.md.
Отвечай по-русски, коротко: владелец пишет с телефона. Секреты не проси и не печатай.
Начни с раздела «Что делать дальше» в handoff.md. Документ мне не пересказывай, сразу приступай.
Если файлов нет, скажи об этом и не выдумывай контекст.
```

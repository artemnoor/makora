---
name: makora-control
description: Управление проектом Макоры из Codex Desktop — анализ задания, документы, этапы, Махорага и агенты через общее состояние сайта и локальный API.
---

# Макора в текущем проекте

Прочитай `.makora/control.json`: repository, projectRoot, port. Используй Python из `<repository>/.venv`, контроллер `<repository>/scripts/makora.py`, передавая `--project-root <projectRoot>` перед командой.

Сначала выполни `status`. Если сервер недоступен — `launch`, затем проверь `status`. При занятом порте другого проекта остановись с объяснением. Сайт открыт на http://127.0.0.1:<port> и использует то же состояние. Для GET: `request /api/preparation` или `request /api/agents/state`. Для POST запиши UTF-8 JSON в файл и выполни `request <route> --json <file>`. Токен контроллер получает сам; не печатай и не сохраняй его.

Свободные инструкции пользователя сопоставляй с текущими этапами и доступными навыками. Отвечай здесь, изучая input/, artifacts/, reports/ и app/. Не сбрасывай проект ради нового сообщения. Не редактируй файлы состояния `.makora` вручную.

## Этапы и команды

- Анализ: POST `/api/preparation/1/start`, `{"brief":"полный текст задания"}`. Для этапов 2–4 передавай `{}` на `/api/preparation/<stage>/start`; сначала проверь утверждение предыдущего.
- Проверка результата: POST `/api/preparation/<stage>/refresh` с `{}`. Читай результат, ограничения и вопросы. Не отмечай отправленный запрос выполненной работой. При неопределённой доставке проверяй историю; не создавай дубликат.
- Утверждение: POST `/api/preparation/<stage>/approve` с `{}` после проверки результата и согласно поручению пользователя. Обязательные вопросы и ограничения не скрывай.
- Настройки моделей: GET `/api/preparation/agent-settings`, POST на тот же маршрут с актуальными projectId и roles. Сохраняй остальные роли. Используй каталог `/api/agents/status`.
- Прототип и разработка: POST `/api/preparation/development`, `{"stage":5}` или `{"stage":6}`.
- Махорага: GET `/api/agents/state`, POST `/api/agents/plans` с projectRoot (папка app/), brief (текст задания), context (утверждённые материалы). Для правок POST `/api/agents/plans/<id>/revise`, `{"feedback":"..."}`; утверждение `/api/agents/plans/<id>/approve`, `{}`. Используй возвращённый runId. Автопилот: `/api/agents/runs/<runId>/autopilot`, `{"enabled":true}` или false. Дополнительные маршруты и payload сверяй с `<repository>/makora_core/server.py` и `agents/runtime.py`.

Применяй установленные методические навыки: requirements-analysis, product-research, solution-design, system-design, development-planning, mock-environment, prototype-handoff по задаче. Схемы сохраняй в Mermaid .mmd. Если пользователь просит работу напрямую в Codex, выполняй её с этими навыками; для регистрации результата в конвейере используй доступный API, не выдавай файлы вне конвейера за утверждённый этап. Изменения требований согласуй с уже утверждёнными документами; укажи, какие этапы требуют обновления.

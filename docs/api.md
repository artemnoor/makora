# API и контроллер

[← Модели и навыки](configuration.md) · [README](../README.md) · [Ошибки и восстановление →](troubleshooting.md)

Это справочник действующего процесса v3 и связанных операций разработки. Сохранённые legacy-маршруты не означают, что они доступны как пользовательские функции новой доски.

## Адрес и ответы

Локальный сервер обычно доступен на `http://127.0.0.1:8000`; фактический порт находится в `.makora/control.json`.

JSON-ответ:

```json
{"ok": true, "result": {"status": "review"}}
```

Ошибка:

```json
{"ok": false, "error": {"code": "PREVIOUS_STAGE_REQUIRED", "message": "Сначала утверди предыдущий этап."}}
```

PDF и ZIP возвращаются бинарными файлами, а не такой JSON-обёрткой.

## Локальный доступ

Изменяющие запросы `/api/preparation...` и `/api/agents/...` требуют `X-Makora-Token`. Страница получает токен через `GET /api/agents/token` с `X-Makora-Request: token` и проверкой происхождения запроса. Сервер ограничивает Host/Origin локальным интерфейсом.

Не подставляйте токен в URL и не сохраняйте его в документации. Для JSON-операций из терминала удобнее контроллер: он получает токен сам и проверяет принадлежность порта проекту.

## Контроллер

Из корня установленного репозитория:

```powershell
./.venv/Scripts/python.exe scripts/makora.py --project-root 'C:\Projects\Campus' status
./.venv/Scripts/python.exe scripts/makora.py --project-root 'C:\Projects\Campus' launch
./.venv/Scripts/python.exe scripts/makora.py --project-root 'C:\Projects\Campus' request /api/agents/state
```

Для POST создайте UTF-8 JSON-файл. Например, повторная проверка уже готового пояснения:

```powershell
'{}' | Set-Content -Encoding utf8 refresh.json
./.venv/Scripts/python.exe scripts/makora.py --project-root 'C:\Projects\Campus' request /api/preparation/0/refresh --json refresh.json
```

`request` принимает JSON-ответы и пути без query string. Он не является универсальным загрузчиком бинарного PDF/ZIP или сырых файлов. Для них используйте кнопки сайта либо соответствующий HTTP-клиент с локальной авторизацией.

## Состояние и подготовка

| Метод и путь | Назначение / тело |
| --- | --- |
| `GET /api/preparation` | Состояние, `workflowVersion`, `stageOrder`, `availableStages`; сверка ожидающей сессии |
| `POST /api/preparation/{id}/start` | Запуск или уточнение: `brief`, `feedback`, `openInCodex` по контексту |
| `POST /api/preparation/{id}/refresh` | Перепроверка существующей сессии и файлов, `{}` |
| `POST /api/preparation/{id}/approve` | Утверждение проверенного этапа; необязательный `note` |
| `POST /api/preparation/{id}/open-codex` | Открыть существующий чат без повторной отправки задания, `{}` |
| `POST /api/preparation/{id}/cancel` | Контроллерная остановка подходящей сессии; не заменяет штатную остановку Desktop-чата |
| `POST /api/preparation/extract?name=brief.pdf` | Сырые байты PDF/DOCX/TXT/MD, извлечение текста |

Для текущих генерируемых этапов допустимы ID `0`, `2`, `3`, `5`, `4`. ID `1` — прежний анализ, новый процесс его не запускает. `6` и `7` не используют общий маршрут `start`: у пакета и разработки собственные операции.

Первое пояснение:

```json
{"brief": "Текст вашего кейса длиной не меньше 10 символов", "openInCodex": true}
```

## Аналоги и брейншторм

| Метод и путь | Назначение / тело |
| --- | --- |
| `POST /api/preparation/2/pdf` | PDF текущего разбора; `decisions` и `note` могут включать текущие комментарии |
| `POST /api/preparation/idea/start` | Создать/вернуть чат брейншторма; `openInCodex`, `decisions`, `note` |
| `POST /api/preparation/3/refresh` | Подхватить согласованные документы, не генерируя их заново |

`idea/start` допускает продолжение с результатом/ошибкой аналогов и сохраняет пометки о непроверенных данных. Он не завершает ещё работающую операцию поиска. Повторный вызов при уже существующем актуальном брейншторме не должен создавать дубликат.

Тип решения по аналогу — `borrow`, `adapt`, `avoid` или `research`; ключ — ID аналога из сохранённого JSON:

```json
{"openInCodex": true, "decisions": {"analog-id": {"action": "adapt", "comment": "Адаптировать фильтры"}}}
```

Это форма запроса, а не команда применить её к произвольному проекту: используйте фактические ID своего разбора.

## Пакет и возвращённый проект

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/preparation/package` | JSON с промптом, составом, текстами документов и digest пакета |
| `GET /api/preparation/archive` | Скачать ZIP материалов |
| `POST /api/preparation/result?name=site.zip` | Загрузить сырые байты ZIP проекта |
| `GET /api/preparation/result` | Скачать сохранённый возвратный ZIP |
| `POST /api/preparation/result/continue` | Проверить и подготовить Git-проект для следующего планирования |

Импорт не запускает приложение. Несовпадение исходных моков блокирует продолжение; изменения предлагаются через `new_mocks/`.

## План и лаборатории

| Метод и путь | Назначение / тело |
| --- | --- |
| `POST /api/preparation/planning/preferences` | Пожелания: `{"laboratories":["Описание сложной функции"]}` |
| `POST /api/preparation/4/start` | Планирование по возвращённому проекту |
| `POST /api/preparation/planning/execution` | Сохранить редакцию: `{"tasks":[...],"execution":{...}}` |
| `POST /api/preparation/4/approve` | Утвердить проверенный план |
| `POST /api/preparation/development` | Для v3 `{"stage":7}`: подготовить проект и очередь из утверждённого графа |
| `POST /api/agents/runs/{run}/laboratories/{lab}/preview` | Запустить локальный тестовый интерфейс |
| `POST /api/agents/runs/{run}/laboratories/{lab}/accept` | Принять готовые проверенные задачи лаборатории для текущего хеша |

`execution` содержит `skeletonTaskId` и `laboratories`; полная структура и требования — в [руководстве лабораторий](laboratories.md#пример-описания). Сохранение графа возвращает его в `review`. Уже созданная очередь не изменяется этой операцией.

## Агентный runtime

| Метод и путь | Операция |
| --- | --- |
| `GET /api/agents/status` | Подключение, каталог/состояние runtime |
| `GET /api/agents/state` | Запуски, сессии и события |
| `GET /api/agents/runs/{run}` | Один запуск |
| `GET /api/agents/sessions/{session}` | Одна сессия |
| `POST /api/agents/runs` | Создать очередь по задачам; основной v3 вызывает это через утверждённый план |
| `POST /api/agents/runs/{run}/autopilot` | `{"enabled":true}` или `false` |
| `POST /api/agents/runs/{run}/mahoraga` | Решение координатора по текущей очереди |
| `POST /api/agents/runs/{run}/tasks/{task}/worktree` | Подготовить рабочую папку |
| `POST /api/agents/runs/{run}/tasks/{task}/agents/{role}` | `builder`, `reviewer`, `test_designer`, `mahoraga` |
| `POST /api/agents/runs/{run}/tasks/{task}/tests` | Выполнить независимые тесты с разрешёнными путями |
| `GET /api/agents/runs/{run}/tasks/{task}/diff` | Изменённые файлы и diff |
| `POST /api/agents/runs/{run}/tasks/{task}/integrate` | `{"confirmed":true}`; проверки не отключаются |
| `POST /api/agents/runs/{run}/tasks/{task}/rebase` | Перенести на новую базу, с актуальными `allowedPaths` |
| `POST /api/agents/runs/{run}/tasks/{task}/resolve-conflicts` | Проверить фактически разрешённый конфликт |

Для повседневной работы используйте доску. Наличие API создания очереди не означает, что можно обойти проверки графа, Git-базы и приёмки.

## Настройки и вход

`GET/POST /api/preparation/agent-settings` получает и сохраняет профиль. POST требует актуального `projectId` и `roles`; существующие остальные роли сохраняются при частичном обновлении.

`GET /api/agents/auth` проверяет вход без выдачи учётных секретов. `POST /api/agents/auth/login` открывает предусмотренный локальный сценарий входа Windows. Это отдельная операция, а не способ исправить ошибку документа.

## Изменения артефактов

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/preparation/changes/context` | Файлы, владельцы этапов и `baseDigest` |
| `POST /api/preparation/changes` | Предложение: `request`, `targets`, `baseDigest`, предлагаемые `files` |
| `POST /api/preparation/changes/scan` | Сопоставить фактически изменённые зарегистрированные файлы |
| `GET /api/preparation/changes` | Список предложений |
| `GET /api/preparation/changes/{id}` | Предложение, diff и влияние |
| `POST /api/preparation/changes/{id}/apply` | `confirm:true`, выбранные `reviewStages` по отчёту влияния |
| `GET /api/preparation/changes/recovery` | Состояние незавершённой транзакции |
| `POST /api/preparation/changes/{id}/recovery` | Разрешение восстановления с подтверждением и ожидаемым хешем состояния |

Без предлагаемых `files` может выполняться только анализ влияния. Устаревшая база, конфликт и исключённые подтверждённые зависимости блокируют применение. Код из предложений не исполняется при их импорте.

## Совместимость

Старые `/api/agents/plans...`, маршруты прототипа, итераций ZIP и часть методов прежнего чата сохранены для других/исторических сценариев. В действующем одно-проектном интерфейсе создание/переключение проекта, выбор папки и отправка сообщений через прежний чат сайта отклоняются с `PROJECT_FIXED`.

Не стройте новый клиент на примерах старых отчётов без сверки с `server.py` и текущим `workflowVersion`.

## Смотрите также

- [Файлы и состояние](artifacts-and-state.md)
- [Модели и навыки](configuration.md)
- [Разработка Макоры](development.md)

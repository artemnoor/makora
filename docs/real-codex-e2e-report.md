# Отчёт проверки реального Codex App Server

Дата: 2026-10-30

## Проверка параллельных Builder и интерфейса

В отдельном временном Git-проекте запущены два реальных Builder `gpt-6-luna` с отдельными worktree: T01 thread `01a18dac-fbe0-79b1-bef7-995ab9b7035c`, T02 thread `01a18dad-3979-7630-8e1b-6cd7fc8c37f9`. На этапе старта статус Test Designer задан вручную, поэтому этот прогон проверяет только Builder. Контроллер одновременно показывал для двух сессий `delivered`; затем обе завершились `completed`. T01 создал `t01.py` со значением T01, T02 — `t02.py` со значением T02, пересечения файлов нет. Каждый выполнил `Start-Sleep -Seconds 30`. Журнал: `C:\CodexData\tmp\makora-parallel-check.log`; проект и состояние: `C:\Users\Артём\AppData\Local\Temp\makora-parallel-zti_joqh`. Точные интервалы исполнения команд не записаны: одновременно доставленные запросы сами по себе не доказывают перекрытие времени вычислений.

В настоящем браузере проверен ответ реального `/api/agents/token`: запрос с заголовком из same-origin получил 200, без заголовка — 403. Действия «Проверить в sandbox», «Запустить Reviewer» и «Подтвердить интеграцию» отправили ожидаемые запросы и значения; состояние экрана обновлялось. Для этих трёх действий серверные ответы подменялись тестовыми, браузерное взаимодействие с реальным запуском не проверялось.

Циклы исправлений в REAL отсутствуют: отдельного перевода замечаний Reviewer Builder, счётчика трёх попыток и передачи Махораге в текущем коде нет. Возможность отправки отдельного сообщения в thread не подтверждает цикл исправлений. Статус проверки: не реализовано.

## Актуальный результат: подтверждён одиночный цикл приёмки

Прогон `run-863b9c2c96a4` завершён через реальные методы контроллера. Test Designer и Builder использовали `gpt-6-luna` (идентификаторы ниже). Контроллер выполнил unittest в elevated Windows sandbox с абсолютным путём Python: 1 тест, `OK`, exitCode 0. Снимок проверенных файлов: SHA256 `322b17a32a9b9d63cf7c8a52c62fd426c61e01c4ab72f220a59acf7ead7902be`.

Повторный Reviewer получил содержимое фактических файлов и результаты sandbox-теста. Thread `01a18da8-3703-7002-a27e-f9f799faae2c`, turn `01a18da8-53c7-7383-9d7d-b4113c2909cc`; результат JSON `verdict=pass`, findings пуст. Отчёт привязан к тому же SHA256. `integrate_task(..., confirmed=True)` выполнил fast-forward только в исходном временном проекте: commit `26e9bbdbb0e32f216b800761c6b78b6804797baa`. Задача T01 получила `integrated`, зависимая T02 разблокирована. Для T02 успешно создан чистый worktree с baseCommit `26e9bbdbb0e32f216b800761c6b78b6804797baa`.

Методы `test_task` и `integrate_task` сохраняют доказательства и проверяют актуальность файлов, разрешённые пути, чистоту и исходную ревизию проекта. Без актуального теста, JSON-решения Reviewer, совпадения снимка и явного подтверждения интеграция запрещена. Действия добавлены в существующий REAL интерфейс. Проверена приёмка Python unittest; другие стеки, повторные исправления, параллельный прогон и браузерная проверка новых действий этим результатом не подтверждаются. Исторические записи ниже описывают прежние попытки.

## Повторная проверка 30 октября

### После настройки пользователем elevated sandbox

Повторная проверка последнего worktree `run-863b9c2c96a4/T01`: unittest запущен в elevated sandbox с абсолютным путём Python и прошёл (1 тест, код 0). Вызов по имени `python` ранее завершился ошибкой Windows 2, поскольку исполняемый файл не найден в окружении sandbox.

Reviewer на `gpt-6-luna`: thread `01a18da3-6eed-7ea3-89ab-f7a8d383f184`, turn `01a18da3-8b03-73e0-990a-310fceee00a3`; ответ завершился с `verdict: pass`, при этом сам Reviewer указал, что тесты им не запускались и VCS diff недоступен. Это не подтверждает полноценное ревью diff. Интеграция и разблокирование зависимой задачи не реализованы и не выполнялись; полный цикл остаётся неподтверждённым.

Настройка Windows elevated sandbox подтвердилась реальным запуском. Профиль адаптирован к требованию `:root=read`, исходный проект и конкретные соседние worktree запрещены; запись разрешена только в cwd агента. Запрет родительского workspace исключён: Windows ACL перекрывал разрешение вложенного cwd.

Общий Desktop App Server завершал turn `failed` без подробной причины. Добавлен опциональный `CODEX_APP_SERVER_BINARY`: отдельный App Server запускается через stdio и штатную авторизацию. С бинарником 0.166.0 реальная генерация на `gpt-6-luna` выполнена:

- Test Designer thread `01a18da0-853f-7273-9630-e7f02f9398f7` завершился и создал `TEST_DESIGN.md`.
- Builder thread `01a18da1-3583-78c0-8e31-6bafe226c5fe` завершился в отдельном Git worktree.
- В предыдущем прогоне Builder thread `01a18da0-261b-76a1-8196-ba021287dca5`, turn `01a18da0-51e2-7513-9fdf-b1a67ab2e990` фактически создал `greeting.py` и `test_greeting.py`; оба untracked файла обнаружены контроллером.
- Исходные данные последнего прогона: `C:\CodexData\tmp\makora-real-last.log`; состояние и история: `C:\Users\Артём\AppData\Local\Temp\makora-real-check-4qfboopb\workspace\agents\state.json`.
- Независимый запуск unittest через elevated `codex sandbox` в предыдущем worktree завершился кодом 1: `CreateProcessWithLogonW failed: 267`. Тесты приложения не считаются пройденными. Reviewer и интеграция не выполнялись.

Подтверждена реальная генерация файлов, но не полный цикл приёмки. Ни один результат не интегрирован автоматически.

### Исторический снимок до исправлений от 2026-10-30

Следующий ниже блок фиксирует более раннюю проверку и её блокеры. Он заменён актуальным успешным браузерным циклом GPT-6 Luna в разделе «Настоящий браузерный цикл исправлений на GPT-6 Luna» в конце этого отчёта.

Заменён устаревший `sandboxPolicy.readOnlyAccess` на именованный профиль `permissions=makora`, переданный через `thread/start.config`. Формат подтверждён JSON Schema, сгенерированной бинарником App Server 0.166.0, и [официальной документацией профилей](https://learn.chatgpt.com/docs/permissions). Профиль разрешает системный минимум и только каталог агента, сеть отключена. Пользовательские файлы авторизации не читались и не изменялись.

Новый реальный запуск теперь останавливается при подготовке Windows sandbox: `windows unelevated restricted-token sandbox cannot enforce split filesystem read restrictions directly; refusing to run unsandboxed`. Это новый подтверждённый блокер среды, а не ошибка токена или формата API. Проверка рекомендованного MXC командой `codex -c windows.sandbox=mxc sandbox --include-managed-config --permission-profile :workspace -- cmd.exe /d /c echo MXC_OK` завершилась кодом 1: `native MXC is unavailable on this executor`. Ubuntu WSL доступна, но отдельного Linux Codex и bubblewrap там не обнаружено (команда `codex` указывает на Windows npm launcher).

На момент этого исторического прогона требовалась настройка elevated sandbox с одобрением Windows администратора или отдельная Linux-среда. Позднее sandbox удалось запустить с настроенным Codex App Server; результаты приведены в актуальном разделе ниже.

Отдельный `codex exec` с моделью `gpt-6-luna` и read-only sandbox успешно ответил «готово», session ID `01a18d88-851f-7ba0-a3ba-9a3013e7feb4`. Это подтверждает доступность модели через CLI на момент проверки, но не проверяет агентный цикл Макоры.

При запуске Test Designer через Макору был создан thread `01a18d89-2e49-7a60-b82f-44d262348c3e`, однако App Server вернул `502`: `workspaceWrite.readOnlyAccess is no longer supported; use permissionProfile for restricted reads`. Builder не запускался; создание файлов, тесты, Reviewer, интеграция и параллельные агенты не проверены. Контроллер отмечает отправку с созданным thread как неподтверждённую, чтобы не повторять её автоматически. Совместимая политика ограниченного доступа ещё не реализована.

GitHub Actions для опубликованного коммита `38ac02e` завершился успешно: [запуск 41082836630](https://github.com/artemnoor/makora/actions/runs/41082836630). Локальные изменения после этого коммита в этом запуске CI не проверялись.

## Результат исторического прогона

Состояние: `blocked`.

Локальный Codex App Server версии `0.166.0` запустился, вернул каталог моделей с `gpt-6-luna`, создал постоянный thread и принял запрос Builder. Запрос завершился `systemError`: локальная авторизация Codex вернула HTTP 401 `token_revoked`. Каталог подтвердил, что модель известна этой установке, но реальный ответ модели не получен.

## Данные прогона

- Модель: `gpt-6-luna`
- Временный проект: `C:\CodexData\tmp\makora-luna-e2e-20261030`
- Изолированный worktree: `C:\CodexData\tmp\makora-agent-smoke\agents\worktrees\run-c534d22b7f62\T01`
- Ветка: `makora/run-c534d22b7f62/t01`
- Thread: `01a18d65-41d5-7d52-9d7e-db96de11fb84`
- Turn: `01a18d65-45b0-7c90-8f81-97299fa55dae`
- Operation: `631f4608-40e1-40b5-a598-5a40f1349501`
- Итоговый diff worktree: пустой; файлы проекта не созданы.

Первые два запроса были отклонены из-за несовпадения значений policy с установленной версией App Server. После настройки принятых значений thread и turn были созданы. Повторный запуск после этих исправлений дошёл до App Server, но остановился на `token_revoked`. Повторять запрос автоматически нельзя: результат отправки нельзя считать безопасно воспроизводимым без явной проверки истории.

## Что проверено

- Доступность локального App Server и его каталога моделей.
- Создание реального thread/turn для `gpt-6-luna`.
- Создание отдельного Git worktree и ветки для задачи.
- Отсутствие изменений в тестовом проекте после неудачного запуска.
- Изолированный контроллер и сценарии интерфейса проверяются отдельно; их успешные тесты не являются доказательством успешной генерации моделью.

## Что не проверено

- Успешный ответ Builder от GPT-6 Luna.
- Полный реальный цикл Test Designer → Builder → Reviewer.
- Параллельная работа двух Builder.
- Запуск тестов внутри изолированной песочницы и безопасная интеграция изменений.
- Видимость созданного App Server thread в интерфейсе Codex Desktop.

Чтобы повторить реальный прогон, сначала восстановить локальную авторизацию Codex, затем создать новый временный проект и новый run. Предыдущую отправку не переиспользовать как успешную.

## Повторная проверка после реализации цикла приёмки

Дата: 2026-10-30. Выполнен отдельный настоящий браузерный проход на Codex App Server 0.166.0 и `gpt-6-luna`; использован временный чистый Git-проект, созданный `tests/prepare_agent_e2e.py`. Проект: `C:\CodexData\tmp\makora-real-agent-e2e-21h9bwpr`; workspace контроллера: `C:\CodexData\tmp\makora-agent-e2e-workspace-4`.

Run `run-4c1aa9ca570f`, задача `T01` («Калькулятор»), интегрирована. Реальные завершённые thread/turn:

- Test Designer: thread `01a18dd2-c2ca-76f2-b220-71056ff20b7a`, turn `01a18dd2-ddaf-7f03-8be5-fc59fe7ca97a`.
- Builder: thread `01a18dd3-68b0-7c11-9dfc-677130adf020`, turn `01a18dd3-7e8b-7bd0-953e-530c55f883a1`.
- Reviewer: thread `01a18dd3-f710-7f92-b542-6647bfb802ec`, turn `01a18dd4-0c8c-71a0-ab10-95f7857b5109`.

Test Designer создал `TEST_DESIGN.md`, `test-manifest.json` и самостоятельный набор из 8 unittest. Контроллер собрал изолированную копию проекта и запустил именно `.makora-tests` через Codex elevated sandbox с абсолютным путём Python. Результат: 8 тестов, `OK`, exit code 0. Snapshot кода: SHA-256 `5f3ee388c0ef65487b834a2a835b4d9b510b80b6dd1b04192c08d3e899fbb767`; snapshot независимой suite: `3f87f536bf46ffa6a7d0a4fc8c6009ff8d26c9af90aa2656456f92945a7febee`. Reviewer ответил `pass`, findings пусты, оба snapshot digest совпали с проверенной версией. После подтверждения из браузерного сценария задача получила `integrated`; commit `e41b6b39fe8d3b6d0cbe477c4c069688a20b2cdf` одновременно оказался `HEAD` основной рабочей копии временного Git-проекта. Фактический файл `src/calculator.py` присутствует в ней.

Playwright прогнал полный демо-маршрут 1 → 2 → 3 → 4 и затем настоящий REAL workflow через браузерные кнопки. Скрипт завершился с результатом `analysis:10`, `research:5`, `solution:9`, `planning:9`, `mocks:5`, `approvedAndInvalidated:true`, `errors:[]`; в поле `realAgentRun` сохранены run ID, три thread ID, статус независимых тестов и integrated commit. Это реальное выполнение модели и тестов, не подмена ответов сервера.

## Изменения контроллера и проверенное покрытие

- Параллельная ветка: при продвижении run base можно создать новый worktree с последнего интегрированного коммита и перенести только разрешённые изменённые файлы. Старый worktree сохраняется. Непересекающиеся пути переносятся автоматически. Конфликтующие пути блокируют перенос; после ручного решения копируются в новую ветку, а тесты и review очищаются. Unit tests проверяют перенос непересекающихся изменений и отказ при конфликте без изменения исходных worktree.
- Независимые тесты: обязательны Markdown, JSON manifest и executable tests в `tests/` или `.makora-tests/`; manifest содержит argv-массивы без shell, ограниченный список runner и команду, которая явно запускает `.makora-tests`. Код и suite хешируются отдельно. Тесты выполняются в sandbox-копии исходников; project-owned test discovery не подменяет независимый набор.
- Цикл исправлений: `changes_requested` запускает до трёх follow-up Builder turns; каждое новое сообщение сбрасывает прежние test/review evidence. После неудачного Reviewer-ответа на третью попытку задача передаётся read-only агенту «Махорага» и ждёт решения человека. Unit test проверяет лимит и эскалацию. Дополнительно выполнен реальный repair-cycle на GPT-6 Luna: первый Reviewer запросил изменение; Builder получил follow-up в том же thread; независимые тесты запущены повторно; следующий Reviewer подтвердил результат. Подробности ниже.
- Универсальный runner: команды задаются в `test-manifest.json` для Python, Node, npm, Go, Cargo, .NET, Java, Maven, Gradle и pytest; запускаются без shell, в sandbox-копии. Успешного exit code недостаточно: manifest задаёт `minimumTests`, runner должен подтвердить число реально выполненных тестов по формату фреймворка или буквальному `countPrefix`. Python suite и Node `node:test` реально запущены в Codex sandbox. Внешняя установка зависимостей и сеть не поддерживаются; требуемые runtime и зависимости должны быть доступны локально.
- UI polling сверяет operation с сохранёнными thread и turn ID. Исправлен подтверждённый случай, когда App Server оставлял operation в `delivered`, хотя соответствующий turn был `completed`.

Финальная локальная проверка текущего diff: `python -m unittest discover -s tests -q` — 75 тестов, все пройдены; `node --check dist/agent-runtime-ui.js`, `node --check tests/browser-flow.js`, `py_compile` изменённых Python-файлов, `git diff --check` и `python scripts/check_skills.py` завершились с кодом 0. Для suite использован настроенный Codex App Server binary; независимые наборы Python и Node запускались в фактическом Windows sandbox.

## Настоящий браузерный цикл исправлений на GPT-6 Luna

Дата: 2026-10-30. Через REAL-интерфейс Playwright создан одноразовый чистый Git-проект `C:\CodexData\tmp\makora-real-agent-e2e-ex0ct8yh`; App Server 0.166.0, модель `gpt-6-luna`; run `run-fbd45b516717`, задача `T01`.

- Test Designer thread `01a18dee-9414-74c1-9ab8-cfc457d91469`, turn `01a18dee-ba5b-71b3-a7ee-f3de91d8af15` создал самостоятельный пакет из 2 тестов.
- Builder thread `01a18def-c6cf-7d02-8b57-373099291e2b`; после первого Reviewer Макора отправила follow-up в тот же thread. В controller state сохранён итоговый turn `01a18df0-c378-7f01-a526-493d01826da1`; событие `builder_fix_requested` зафиксировало цикл `1/3`.
- Первый Reviewer thread `01a18df0-8465-7ee0-996c-dd91aa6930c9`, turn `01a18df0-9d26-7ee0-9a4f-c6a75ea69c3d`, запросил правку ASCII-пунктуации. После follow-up Builder тесты были запущены заново: `2 passed`, `Ran 2 tests`, exit code 0, `minimumTests=2`.
- Второй Reviewer thread `01a18df2-8cc7-7a83-924b-1289630f8afe`, turn `01a18df2-a746-7e43-849b-5464e1f5bc95`, ответил `pass`, без findings. SHA-256 кода `102824d9d7fc662bb0bcf12a6df712d2197430850745799b03e93a65655ade75`; suite `9f6f0416a81e74212a7a9fd83c8a8c22a2972d2d7c0148394b5c517972e33419`. Browser verification подтвердил совпадение обоих digest.
- Изменения интегрированы после подтверждения в тестовом браузерном сценарии: commit `cafc9ac48143ee374d4fdfbbebda22e95207a587`, статус `integrated`, временный проект чистый, `src/slug.py` существует.

Playwright browser verification возвратил: `run-fbd45b516717`, `integrated`, `repairAttempts=1`, `executedTests=[2]`, reviewer `pass`; commit и digest совпали с controller state и `HEAD` временного Git-проекта. Это реальный Builder → Reviewer → Builder follow-up → повторные независимые тесты → Reviewer → Integration, не fake-provider.

Реальный случай, где все три repair attempts заканчиваются отказом и задача передаётся Махораге, отдельно на GPT-6 Luna не запускался; лимит, сброс evidence, блокировка и запуск read-only Mahoraga покрыты unit-тестами. Реальная одновременная генерация двумя Builder также не проверялась; параллельные ветки были проверены интеграционным тестом с разными worktree, refresh/retest и fast-forward интеграцией. Никакие изменения в remote GitHub не отправлялись.

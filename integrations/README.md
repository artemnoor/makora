# Сторонние интеграции

## `codex-desktop-local-api`

Исходный репозиторий: <https://github.com/artemnoor/codex-desktop-local-api>

Вендорный исходный коммит: см. [`UPSTREAM_COMMIT.txt`](../UPSTREAM_COMMIT.txt). Код находится в этом репозитории как обычные отслеживаемые файлы; вложенной Git-истории и submodule нет. Сохранённая исходная Git-история находится вне проекта в локальном каталоге `%CODEX_HOME%\tmp\makora-codex-desktop-local-api.git`.

Макора использует App Server API этого проекта для каталогов моделей, создания постоянных thread, отправки сообщений и чтения истории. Desktop app-tools bridge сохраняется для исходных функций интеграции, но агентные задачи не посылаются через навигацию Desktop между чатами.

### Обновление из upstream

1. Убедись, что в `integrations/codex-desktop-local-api/` нет локальных изменений, которые нельзя перезаписать.
2. Во временном каталоге выполни `git clone https://github.com/artemnoor/codex-desktop-local-api.git codex-desktop-local-api-upstream`.
3. Зафиксируй `git -C codex-desktop-local-api-upstream rev-parse HEAD` в `UPSTREAM_COMMIT.txt` после переноса исходных изменений.
4. Скопируй исходные файлы из клона поверх вендорной папки, не копируя `.git`. Затем заново примени небольшой Makora-specific diff, проверь запуск API, модели, контроль доступа и контрактные тесты.
5. Оставь интеграционный код обычными файлами в основном Git-репозитории. Не добавляй `.git` или submodule из временного клона.

Локальные изменения Макоры в upstream-файлах: App Server-only режим старта, same-origin loopback-проверка, Bearer-токен между контроллером и мостом, ограниченный `sandboxPolicy` для каждого агента и политика подтверждения `on-request`. Сверяйся с `git diff`/историей перед обновлением.

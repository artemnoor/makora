# Codex Desktop Local API

Локальный HTTP API для Codex Desktop и Codex App Server. Сервер слушает только `127.0.0.1`; HTML и веб-интерфейса в проекте нет. Desktop app-tools используются только для совместимых Desktop-функций, а управляемые задачи Макоры используют отдельные persistent thread через App Server.

## Запуск

Нужны Windows, запущенный Codex Desktop, PowerShell 7 и Node.js 22.13 или новее. В каталоге проекта:

```powershell
./start-api.ps1 -CodexDataDirectory 'C:\path\to\codex-data' -BridgeContextThreadId '<thread-id>'
```

Адрес по умолчанию: `http://127.0.0.1:4181`. Другой порт: `./start-api.ps1 -Port 4182`. Остановка — Ctrl+C в терминале процесса.

Укажите каталог данных и ID отдельного чата для bridge-контекста. Также можно задать переменные `CODEX_HOME` и `CODEX_APP_TOOLS_CONTEXT_THREAD_ID`. Контекст должен быть доступным чатом с сохранённым ходом. Если он удалён или Desktop обновил внутренний IPC, мост может перестать работать и потребовать перенастройки. После установки переменных достаточно запустить `./start-api.ps1`.

Для маршрута App Server без внутреннего Desktop IPC используй `./start-api.ps1 -AppServerOnly -Port 4182`. Создание задач, каталог моделей и чтение thread работают без bridge-контекста; Desktop-specific операции вернут состояние недоступности.

Запускайте только один экземпляр на выбранном порту. `GET /api/status` показывает состояние App Server; `GET /api/desktop/status` дополнительно проверяет наличие нужных Desktop-инструментов.

## Подключение сайта

Браузерные запросы принимаются только с loopback origin, чьи host и port совпадают с заголовком `Host`; запросы с других origin отклоняются. POST с телом принимает `application/json`. Если задан `CODEX_LOCAL_API_TOKEN`, каждый маршрут требует `Authorization: Bearer ...`; Макора включает его для своего локального процесса. Не выставляй порт в сеть.

```js
const api = 'http://127.0.0.1:4181';
async function request(path, options = {}) {
  const response = await fetch(api + path, options);
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error), result);
  return result;
}
const jsonPost = value => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(value),
});

// Создание уже отправляет первое сообщение: повторно его отправлять не нужно.
const created = await request('/api/threads', jsonPost({
  projectless: true, model: 'gpt-6-luna', prompt: 'Привет!',
}));
const threadId = created.id;
const operationId = created.operation.id;

async function waitForCompletion(id) {
  for (;;) {
    const operation = await request(`/api/operations/${id}`);
    if (operation.state === 'completed') return operation;
    if (['failed', 'unconfirmed'].includes(operation.state)) throw new Error(operation.state);
    await new Promise(resolve => setTimeout(resolve, 2800));
  }
}
await waitForCompletion(operationId);
// Отправка следующего сообщения в тот же чат:
const sent = await request(`/api/threads/${threadId}/messages`,
  jsonPost({ text: 'Продолжи, пожалуйста.' }));
await waitForCompletion(sent.operation.id);
const history = await request(`/api/threads/${threadId}?tail=1`);
```

Для обновлений без постоянного опроса каталога подключите `new EventSource(api + '/api/events')`. Событие `operation-updated` содержит состояние операции; `desktop-store-changed` означает, что клиенту следует обновить интересующую историю или список. При переподключении сервер повторяет до 100 последних событий по `Last-Event-ID`; `replay-reset` означает, что нужно заново прочитать состояние. События Desktop — сигнал изменений хранилища, а не гарантированный поток каждого токена.

## Маршруты

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/status`, `GET /api/desktop/status` | Состояние сервера и Desktop bridge. |
| `GET /api/models`, `GET /api/projects` | Доступные модели и проекты. |
| `GET /api/threads` | Недавние чаты Desktop; `scope=all` добавляет результаты App Server. При недоступности Desktop-каталога возвращается ошибка, а не подмена списка. |
| `GET /api/desktop-history?limit=30&cursor=…` | Страницы старых активных Desktop-чатов из индекса; следующий cursor находится в `nextCursor`. |
| `GET /api/projects/{id}/threads` | Чаты по проекту и его рабочим папкам; сопоставление по пути может отличаться от назначения в Desktop. |
| `GET /api/threads/{id}?tail=1` | Метаданные и недавняя история. `metadata=1` возвращает только метаданные. В истории есть `turns`, `olderTurns`, `historyMode`, `historyNextCursor`. |
| `GET /api/threads/{id}/items?limit=100&direction=desc&cursor=…` | Предыдущая страница элементов истории. Доступен также `/history` для страниц ходов. |
| `POST /api/threads` | Создать чат и отправить первый `prompt`; необязательны `model`, `name`, `projectless`, `projectId`, `cwd`. Не сочетайте `projectless` с `projectId`. |
| `POST /api/threads/{id}/messages` | Отправить `{ "text": "…" }` в Desktop. Для локального host `hostId` не нужен. Сервер сначала просит Desktop открыть целевой чат. |
| `POST /api/threads/{id}/desktop/open` | Открыть чат в Desktop без отправки сообщения. |
| `GET /api/operations/{id}` | Состояние подтверждения отправки: `accepted`, `delivered`, `completed`, `failed` или `unconfirmed`. |
| `GET /api/events` | SSE события, включая состояние операций и сигнал изменения Desktop-хранилища. |
| `GET /api/approvals`, `POST /api/approvals/{id}` | Запросы подтверждения App Server и ответ `{ "decision": "accept" }` или `"decline"`. |

Операции хранятся в памяти процесса. `accepted` подтверждает принятие запроса транспортом, `delivered` — появление текста пользователя в истории, `completed` — подтверждённый ответ. Пока операция выполняется, следующая отправка в тот же чат вернёт HTTP 409 с её `operationId`. Через три минуты без подтверждения возвращается `unconfirmed`; это не доказательство, что сообщение не было доставлено. После перезапуска операции не сохраняются — читайте историю чата.

Тайм-аут создания или отправки может вернуть `deliveryUnknown: true`: результат на стороне Desktop неизвестен. Проверьте список и историю перед повторной отправкой, иначе возможен дубликат. Автоматических повторных отправок сервер не делает. `transport: "app-server"` выбирает отдельный App Server явно; такие чаты не гарантированно появляются в живом Desktop.

`POST /api/projects` использует экспериментальный `project/create` App Server и не гарантирует регистрацию проекта в Desktop. Исторический индекс открывается в режиме только чтения; он отбирает Desktop-записи с `thread_source=user` и может не включать другие типы чатов. Сообщения читаются через App Server, данные Codex напрямую не редактируются.

Для App Server thread API принимает `approvalPolicy` (`on-request` по умолчанию), `sandbox` (`workspace-write` по умолчанию) и ограниченный `sandboxPolicy` для первого хода. Клиент должен задавать writable/readable roots сам; thread ID сохраняется независимо от HTTP operation ID. App Server thread могут не отображаться в Codex Desktop UI — это свойство транспорта, не ошибка в Макоре.

## Проверка и ограничения

На этой машине проверены создание отдельного projectless QA-чата на `gpt-6-luna`, следующее сообщение в том же чате, оба ответа в истории и оба состояния операции `completed`. Также проверены страницы старого каталога, каталог проектов и моделей, локальный CORS, SSE и повтор событий. Существующие пользовательские чаты для тестовых отправок не использовались.

Desktop app-tools — внутренний, недокументированный IPC, и его поведение может измениться. `list_threads` Desktop ограничен недавними записями, а история старых чатов зависит от внутренней схемы SQLite. Полная совместимость и немедленная синхронизация всех существующих чатов не гарантируются. При сбое используйте `/api/desktop/status` и сообщения об ошибках; не считайте результат `accepted` подтверждением ответа.

Если соединение с managed App Server daemon оборвётся, перезапустите API через `start-api.ps1`: автоматическое восстановление этого соединения пока не реализовано. Подключение к Desktop pipe повторяется при следующем запросе.

При исследовании использованы [официальная документация App Server](https://github.com/openai/codex/tree/main/codex-rs/app-server), [codex-app-server-web-chat](https://github.com/yangzehan/codex-app-server-web-chat), [codex_web_ui](https://github.com/nathan-chappell/codex_web_ui) и пользовательские отчёты [#33138](https://github.com/openai/codex/issues/33138), [#36363](https://github.com/openai/codex/issues/36363).

"""Run the real Mahoraga -> Codex Builder workflow in a disposable Windows Git project.

This script does not fake Codex responses or edit application source. It starts
Makora, submits the case through the public same-origin API, approves Mahoraga's
validated plan as the test harness user, then lets the bounded autopilot drive
Test Designer, Builder, sandbox tests, Reviewer, and safe integration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


MODEL = 'gpt-6-luna'
MAX_PLAN_REVISIONS = 2
CASE = '''# Проект «Тихий кампус»

Разработай небольшое локально запускаемое приложение для поиска свободных мест
для учёбы в университете. Оно хранит помещения в локальных тестовых данных,
возвращает список и фильтрует его по названию или характеристикам. Нужен рабочий
HTTP API, корректная обработка пустых результатов и некорректных запросов,
исполняемые независимые тесты и запуск без внешних коммерческих сервисов.

Самостоятельно выбери простой стек, структуру проекта, архитектуру и API-контракт.
Не предполагай, что в пустом репозитории есть конкретные папки или модули.
Разбей реализацию минимум на четыре исполняемые задачи, выдели минимум две
независимые задачи для параллельной работы и задачу финальной интеграции.
Для каждой задачи определи точные разрешённые пути приложения, контракт и
критерии готовности. Финальная проверка должна выполнять реальные функциональные
запросы или команды к приложению, включая успешный и отрицательный сценарии.
В JSON плана добавь машиночитаемый объект e2e. Для HTTP-приложения используй
mode=http и поля launch, portEnv, route, searchParameter, invalidQuery, nameField,
listKey. Для CLI используй mode=cli и commands — не менее двух argv-массивов с
expectedExitCode и проверкой успешного и ошибочного ввода. Выбери контракт с
учётом типа приложения; не добавляй HTTP-сервер к CLI без необходимости.
'''

SCENARIOS = {
    'task-manager': ('Task Manager', 'Создай локальное приложение для управления задачами и статусами: добавление, просмотр, изменение статуса, фильтр по статусу и обработка отсутствующих задач. Используй локальное хранилище/фикстуры без платных внешних сервисов. Нужны независимые исполняемые тесты и работающий интерфейс API или CLI.'),
    'expense-tracker': ('Expense Tracker', 'Создай локальное приложение для учёта расходов: добавление расходов с категорией и датой, список, фильтр по периоду/категории и сводная аналитика сумм. Обрабатывай пустые данные и некорректный ввод. Без внешних платных сервисов, с локальными данными и независимыми исполняемыми тестами.'),
    'inventory-system': ('Inventory System', 'Создай локальную систему складского учёта: каталог товаров, остатки, поступление и списание, поиск/фильтр и защита от отрицательного остатка. Используй локальные данные, без внешних платных сервисов; подготовь исполняемые независимые тесты.'),
    'event-manager': ('Event Manager', 'Создай локальное приложение управления мероприятиями: список событий, регистрация участника, просмотр участников и корректная обработка заполненного/несуществующего события. Используй локальные данные и независимые исполняемые тесты.'),
    'notes-api': ('Notes API', 'Создай локальный API заметок с тегами и поиском: создание, чтение списка, поиск по тексту/тегу, пустые результаты и некорректные запросы. Локальные данные, без платных внешних сервисов, независимые исполняемые тесты.'),
    'url-shortener': ('URL Shortener', 'Создай локальный сервис коротких ссылок: создание короткого кода, переход по коду, неизвестный код и проверка некорректного URL. Хранилище локальное, внешние сервисы запрещены, нужны независимые исполняемые тесты.'),
    'student-gradebook': ('Student Gradebook', 'Создай локальную систему учёта оценок студентов: студенты, предметы, добавление оценки, просмотр ведомости и расчёт среднего балла; обработай пустую ведомость и неверные оценки. Локальные данные, независимые исполняемые тесты.'),
    'file-analyzer': ('File Analyzer', 'Создай CLI для анализа локальных CSV и JSON файлов: распознавание/валидация входа, подсчёт записей, сводка по полям и понятная обработка повреждённого или пустого файла. Не задавай заранее структуру проекта. Нужны исполняемые независимые тесты и работающие реальные команды CLI.'),
    'booking-system': ('Booking System', 'Создай локальную систему бронирования помещений: список помещений и бронирований, создание/отмена брони и проверка конфликтов временных интервалов. Проверь границы интервалов и неизвестное помещение. Только локальные данные, независимые исполняемые тесты.'),
    'mini-crm': ('Mini CRM', 'Создай локальную мини-CRM: клиенты и сделки, просмотр, фильтрация клиентов/сделок и статистика по статусам/суммам. Обработай пустые результаты и некорректные данные. Локальное хранилище, без платных внешних сервисов, независимые исполняемые тесты.'),
}


class E2EFailure(RuntimeError):
    pass


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    # A fixed ``.tmp`` name can collide with a second writer, and Windows may
    # briefly deny replacement while antivirus/indexing has the destination
    # open. Use a per-write temp file and bounded retry; preserve the previous
    # valid evidence file if the OS keeps refusing the atomic replace.
    temp = path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        for attempt in range(8):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(min(0.05 * (2 ** attempt) + random.random() * 0.04, 1.0))
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def session_snapshots(sessions: list[dict], previous: list[dict] | None = None) -> list[dict]:
    """Keep every observed turn even when a follow-up replaces a session's current turn."""
    previous_by_id = {item.get('id'): item for item in previous or [] if item.get('id')}
    output = []
    turn_fields = ('operationId', 'turnId', 'requestedAt', 'acceptedAt', 'kind', 'status',
                   'executionObservedStartAt', 'executionObservedEndAt',
                   'executionObservedDurationMs', 'providerTurnTiming')
    for session in sessions:
        old = previous_by_id.get(session.get('id'), {})
        history: list[dict] = []
        by_turn: dict[tuple[str | None, str], dict] = {}

        def merge_turn(source: dict) -> None:
            turn_id = source.get('turnId')
            if not isinstance(turn_id, str) or not turn_id:
                return
            operation_id = source.get('operationId')
            key = (operation_id if isinstance(operation_id, str) else None, turn_id)
            current = by_turn.get(key)
            if current is None:
                current = {field: source.get(field) for field in turn_fields}
                by_turn[key] = current
                history.append(current)
            else:
                for field in turn_fields:
                    value = source.get(field)
                    if value is not None and value != {}:
                        current[field] = value

        for source in (old, session):
            for turn in source.get('turnHistory') or []:
                if isinstance(turn, dict):
                    merge_turn(turn)
            merge_turn(source)

        output.append({key: session.get(key) for key in (
            'id', 'role', 'taskId', 'threadId', 'turnId', 'operationId', 'model', 'cwd', 'status',
            'requestedAt', 'acceptedAt', 'executionObservedStartAt', 'executionObservedEndAt',
            'executionObservedDurationMs', 'providerTurnTiming', 'autopilotAppliedAt', 'actionResults', 'error')}
                       | {'turnHistory': history})
    return output


def confirmed_builder_pairs(sessions: list[dict], builder_snapshots: list[dict]) -> list[dict]:
    """Confirm concurrent Builders from distinct worktrees, real turn intervals, and changed files."""
    builders = [item for item in sessions if item.get('role') == 'builder']
    changed_files = {}
    snapshot_worktrees = {}
    for item in builder_snapshots:
        if not isinstance(item, dict) or not item.get('taskId'):
            continue
        task_id = item['taskId']
        if item.get('changedFiles'):
            changed_files.setdefault(task_id, set()).update(item['changedFiles'])
        if item.get('worktree'):
            snapshot_worktrees[task_id] = item['worktree']

    def parse(value):
        try:
            return dt.datetime.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    def intervals(session):
        turns = []
        for turn in session.get('turnHistory') or []:
            if not isinstance(turn, dict):
                continue
            start = parse(turn.get('executionObservedStartAt'))
            end = parse(turn.get('executionObservedEndAt'))
            if start and end and end > start:
                turns.append((start, end))
        if turns:
            return turns
        start = parse(session.get('executionObservedStartAt'))
        end = parse(session.get('executionObservedEndAt'))
        return [(start, end)] if start and end and end > start else []

    pairs = []
    for index, left in enumerate(builders):
        for right in builders[index + 1:]:
            left_task, right_task = left.get('taskId'), right.get('taskId')
            left_cwd = snapshot_worktrees.get(left_task) or left.get('cwd')
            right_cwd = snapshot_worktrees.get(right_task) or right.get('cwd')
            if (not left_task or not right_task or left_task == right_task or
                    not left.get('threadId') or not right.get('threadId') or left['threadId'] == right['threadId'] or
                    not left_cwd or not right_cwd or os.path.normcase(os.path.normpath(str(left_cwd))) ==
                    os.path.normcase(os.path.normpath(str(right_cwd))) or
                    not changed_files.get(left_task) or not changed_files.get(right_task)):
                continue
            overlaps = [max(0.0, (min(left_end, right_end) - max(left_start, right_start)).total_seconds())
                        for left_start, left_end in intervals(left)
                        for right_start, right_end in intervals(right)
                        if min(left_end, right_end) > max(left_start, right_start)]
            if overlaps:
                overlap = max(overlaps)
                pairs.append({'tasks': [left_task, right_task], 'threads': [left.get('threadId'), right.get('threadId')],
                              'worktrees': [left_cwd, right_cwd], 'overlapSeconds': round(overlap, 3),
                              'changedFiles': {left_task: sorted(changed_files[left_task]),
                                               right_task: sorted(changed_files[right_task])}})
    return pairs


def observed_builder_pairs(sessions: list[dict], builder_snapshots: list[dict],
                          observations: list[dict]) -> list[dict]:
    """Report lower-bound concurrency observed while real Builders had changed files.

    This is deliberately separate from completed-turn overlap: a safely blocked
    run may stop while turns are still active, so their exact end times are not
    known. Two simultaneous status samples plus changed files in both distinct
    worktrees provide a conservative, explicitly observation-based interval.
    """
    builders = {item.get('threadId'): item for item in sessions
                if item.get('role') == 'builder' and item.get('threadId') and item.get('taskId')}
    changed_files: dict[str, set[str]] = {}
    worktrees: dict[str, str] = {}
    for item in builder_snapshots:
        if not isinstance(item, dict) or not item.get('taskId'):
            continue
        task_id = str(item['taskId'])
        if isinstance(item.get('changedFiles'), list):
            changed_files.setdefault(task_id, set()).update(str(name) for name in item['changedFiles'] if isinstance(name, str))
        if item.get('worktree'):
            worktrees[task_id] = os.path.normcase(os.path.normpath(str(item['worktree'])))

    samples: dict[tuple[str, str], list[dt.datetime]] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        stamp = observation.get('at')
        try:
            at = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00')) if isinstance(stamp, str) else None
        except ValueError:
            at = None
        if at is None:
            continue
        thread_ids = sorted(set(observation.get('threadIds') or []))
        for index, first_id in enumerate(thread_ids):
            first = builders.get(first_id)
            if not first:
                continue
            for second_id in thread_ids[index + 1:]:
                second = builders.get(second_id)
                if not second or first.get('taskId') == second.get('taskId'):
                    continue
                task_a, task_b = str(first['taskId']), str(second['taskId'])
                tree_a = worktrees.get(task_a) or first.get('cwd')
                tree_b = worktrees.get(task_b) or second.get('cwd')
                if (not tree_a or not tree_b or os.path.normcase(os.path.normpath(str(tree_a))) ==
                        os.path.normcase(os.path.normpath(str(tree_b))) or
                        not changed_files.get(task_a) or not changed_files.get(task_b)):
                    continue
                samples.setdefault((first_id, second_id), []).append(at)

    result = []
    for (first_id, second_id), times in samples.items():
        if len(times) < 2:
            continue
        first, second = builders[first_id], builders[second_id]
        span = max(0.0, (max(times) - min(times)).total_seconds())
        if span <= 0:
            continue
        task_a, task_b = str(first['taskId']), str(second['taskId'])
        result.append({'tasks': [task_a, task_b], 'threads': [first_id, second_id],
                       'worktrees': [worktrees.get(task_a) or first.get('cwd'),
                                     worktrees.get(task_b) or second.get('cwd')],
                       'sampleCount': len(times), 'firstObservedAt': min(times).isoformat(),
                       'lastObservedAt': max(times).isoformat(), 'observedLowerBoundSeconds': round(span, 3),
                       'changedFiles': {task_a: sorted(changed_files[task_a]),
                                        task_b: sorted(changed_files[task_b])}})
    return result


def run_is_completed(run: dict) -> bool:
    """Require integrated tasks and the controller's explicit terminal status."""
    tasks = run.get('tasks')
    autopilot = run.get('mahoragaAutopilot') or {}
    return bool(tasks) and all(task.get('status') == 'integrated' for task in tasks) and autopilot.get('status') == 'completed'


def terminal_task_blocker(run: dict) -> str | None:
    """Return only blockers that should stop polling before Mahoraga can escalate."""
    terminal = {'failed', 'unconfirmed', 'review_unconfirmed', 'blocked_for_human', 'rebase_conflict'}
    for task in run.get('tasks') or []:
        if task.get('status') in terminal:
            return str(task.get('id') or task.get('status'))
    return None


def git(root: Path, *args: str) -> str:
    env = os.environ.copy()
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR',
                 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CEILING_DIRECTORIES'):
        env.pop(name, None)
    result = subprocess.run(['git', '-C', str(root), *args], text=True, encoding='utf-8', errors='replace',
                            capture_output=True, timeout=30, env=env)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or '(git returned a non-zero exit code without output)'
        raise E2EFailure(f'git {args[0]} failed (exit {result.returncode}): {detail[-1500:]}')
    return result.stdout.strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(url: str, method: str = 'GET', body: dict | None = None,
            token: str | None = None, origin: str | None = None, timeout: float = 30) -> dict | list:
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if origin:
        headers['Origin'] = origin
        headers['Sec-Fetch-Site'] = 'same-origin'
        headers['X-Makora-Request'] = 'token'
    if token:
        headers['X-Makora-Token'] = token
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode('utf-8', 'replace')
        try:
            parsed = json.loads(detail)
            detail = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        raise E2EFailure(f'{method} {url} returned HTTP {exc.code}: {detail}') from exc
    if isinstance(payload, dict):
        if 'result' in payload:
            return payload['result']
        return payload
    if isinstance(payload, list):
        return payload
    raise E2EFailure(f'{method} {url} did not return a JSON object or array')


def wait_for_luna_status(api: str, token: str, *, timeout: float = 60,
                         poll_interval: float = 0.5, fetch=request) -> dict:
    """Wait for the non-blocking status endpoint to finish its App Server warmup."""
    deadline = time.monotonic() + timeout
    last_status: dict = {}
    while time.monotonic() < deadline:
        value = fetch(api + '/status', token=token)
        if not isinstance(value, dict):
            raise E2EFailure('Agent status endpoint returned an invalid response.')
        last_status = value
        if value.get('model') == MODEL and value.get('modelAvailable') is True:
            return value
        if not value.get('warming'):
            error = value.get('error') or {}
            code = error.get('code') if isinstance(error, dict) else None
            raise E2EFailure(f'Required gpt-6-luna is not available; no fallback model is permitted. Status: {code or "model_missing"}.')
        time.sleep(poll_interval)
    error = last_status.get('error') or {}
    code = error.get('code') if isinstance(error, dict) else None
    raise E2EFailure(f'Required gpt-6-luna did not become available before warmup timeout. Status: {code or "still_warming"}.')


def redacted_approval_evidence(items: object) -> list[dict]:
    """Capture why the controller paused without persisting arbitrary command text."""
    output = []
    if not isinstance(items, list):
        return output
    for item in items:
        if not isinstance(item, dict):
            continue
        params = item.get('params') if isinstance(item.get('params'), dict) else {}
        record = {'requestId': item.get('requestId'), 'method': item.get('method')}
        for key in ('threadId', 'turnId', 'cwd', 'grantRoot', 'path', 'filePath', 'fileName'):
            value = params.get(key)
            if isinstance(value, str):
                record[key] = value[:500]
        command = params.get('command') or params.get('cmd')
        if command is not None:
            encoded = json.dumps(command, ensure_ascii=False, sort_keys=True, default=str)
            record['commandDigest'] = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
            record['commandLength'] = len(encoded)
        output.append(record)
    return output


def transitive_dependencies(tasks: list[dict]) -> dict[str, set[str]]:
    by_id = {task['id']: task for task in tasks}
    result: dict[str, set[str]] = {}

    def visit(task_id: str, stack: set[str]) -> set[str]:
        if task_id in result:
            return result[task_id]
        if task_id in stack:
            raise E2EFailure('Mahoraga plan contains a dependency cycle')
        stack.add(task_id)
        closure: set[str] = set()
        for dependency in by_id[task_id].get('dependsOn', []):
            closure.add(dependency)
            closure.update(visit(dependency, stack))
        stack.remove(task_id)
        result[task_id] = closure
        return closure

    for ident in by_id:
        visit(ident, set())
    return result


def _validate_app_argv(argv: object, *, max_length: int, label: str) -> list[str]:
    if (not isinstance(argv, list) or not 2 <= len(argv) <= max_length or
            not all(isinstance(value, str) and value and '\0' not in value for value in argv) or
            argv[0] not in ('python', 'python3', 'node')):
        raise E2EFailure(f'{label} must be a bounded argv array starting with python, python3, or node.')
    if any(value in ('-c', '-e', '--eval') for value in argv[1:]):
        raise E2EFailure(f'{label} may not use inline code execution.')
    if argv[1] == '-m':
        if argv[0] not in ('python', 'python3') or len(argv) < 3:
            raise E2EFailure(f'{label} has an invalid Python module launch.')
        module = argv[2]
        if (module in ('pip', 'ensurepip', 'venv') or
                not all(part.isidentifier() for part in module.split('.'))):
            raise E2EFailure(f'{label} may only launch a project application module.')
    elif argv[1].startswith('-'):
        raise E2EFailure(f'{label} may not use interpreter or runtime flags as the application entry point.')
    else:
        entrypoint = Path(argv[1].replace('\\', '/'))
        if entrypoint.is_absolute() or '..' in entrypoint.parts:
            raise E2EFailure(f'{label} application entry point must remain inside the project.')
    return argv


def _validate_http_contract(spec: dict) -> None:
    _validate_app_argv(spec.get('launch'), max_length=12, label='HTTP launch command')
    if not isinstance(spec.get('portEnv'), str) or not re.fullmatch(
            r'(?:[A-Za-z_][A-Za-z0-9_]{0,50}_)?PORT', spec['portEnv'], re.IGNORECASE):
        raise E2EFailure('Invalid HTTP port environment field.')
    requests = spec.get('requests')
    if requests is not None:
        if not isinstance(requests, list) or not 2 <= len(requests) <= 12:
            raise E2EFailure('HTTP requests contract must contain 2–12 ordered requests.')
        names: set[str] = set()
        success = False
        negative = False
        placeholder = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_-]{0,39})\.((?:json\.)?[A-Za-z][A-Za-z0-9_.-]{0,99})\}\}')
        for item in requests:
            if not isinstance(item, dict):
                raise E2EFailure('Each HTTP request contract item must be an object.')
            name, method, path = item.get('name'), item.get('method'), item.get('path')
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', name) or name in names:
                raise E2EFailure('HTTP request names must be unique safe identifiers.')
            if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                raise E2EFailure(f'{name}: unsupported HTTP method.')
            if not isinstance(path, str) or not 1 <= len(path) <= 300:
                raise E2EFailure(f'{name}: invalid relative HTTP path.')
            if (not path.startswith('/') or path.startswith('//') or '\\' in path or '#' in path or
                    re.match(r'(?i)^https?:', path) or any(part == '..' for part in urllib.parse.unquote(path).split('/'))):
                raise E2EFailure(f'{name}: HTTP path must stay on the local application origin.')
            for reference, field in placeholder.findall(path):
                if reference not in names:
                    raise E2EFailure(f'{name}: path references a request that has not run yet.')
            body = item.get('body')
            if body is not None and not isinstance(body, dict):
                raise E2EFailure(f'{name}: JSON request body must be an object.')
            expected_status = item.get('expectedStatus')
            if not isinstance(expected_status, int) or isinstance(expected_status, bool) or not 200 <= expected_status <= 599:
                raise E2EFailure(f'{name}: expectedStatus must be an HTTP status code.')
            expected_json = item.get('expectedJson', {})
            expected_headers = item.get('expectedHeaders', {})
            capture = item.get('capture', {})
            if not isinstance(expected_json, dict) or not all(isinstance(key, str) for key in expected_json):
                raise E2EFailure(f'{name}: expectedJson must map response field paths to exact expected values.')
            if not isinstance(expected_headers, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                                  for k, v in expected_headers.items()):
                raise E2EFailure(f'{name}: expectedHeaders must map header names to exact values.')
            if not isinstance(capture, dict):
                raise E2EFailure(f'{name}: capture must be an object mapping aliases to JSON response field paths.')
            if not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,39}', k)
                       and isinstance(v, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,99}', v)
                       for k, v in capture.items()):
                raise E2EFailure(f'{name}: invalid JSON/header assertions or capture fields.')
            if expected_status < 400:
                success = True
            else:
                negative = True
            names.add(name)
        if not negative:
            negative_request = spec.get('invalidRequest', spec.get('invalidQuery'))
            if isinstance(negative_request, dict):
                structured = any(key in negative_request for key in
                                 ('method', 'path', 'body', 'expectedStatus', 'expectedError'))
                if structured:
                    method = negative_request.get('method', 'GET')
                    path = negative_request.get('path', negative_request.get('route', spec.get('route', '/')))
                    body = negative_request.get('body')
                    status = negative_request.get('expectedStatus')
                    if (method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') or not isinstance(path, str) or
                            not path.startswith('/') or path.startswith('//') or '\\' in path or '#' in path or
                            any(part == '..' for part in urllib.parse.unquote(path).split('/')) or
                            body is not None and not isinstance(body, dict) or
                            status is not None and (not isinstance(status, int) or isinstance(status, bool) or not 400 <= status <= 499) or
                            negative_request.get('expectedError') is not None and not isinstance(negative_request.get('expectedError'), str)):
                        raise E2EFailure('Invalid ordered HTTP negative request contract.')
                    negative = True
        if not success or not negative:
            raise E2EFailure('HTTP requests need at least one successful and one negative response.')
        return

    for key in ('route', 'searchParameter', 'nameField'):
        if not isinstance(spec.get(key), str) or not spec[key] or len(spec[key]) > 120:
            raise E2EFailure(f'Invalid final HTTP contract field: {key}')
    if spec.get('listKey') is None:
        raise E2EFailure('A non-list HTTP API must declare ordered e2e.requests.')
    if (not spec['route'].startswith('/') or spec['route'].startswith('//') or '?' in spec['route'] or
            not isinstance(spec['listKey'], str) or not spec['listKey'] or len(spec['listKey']) > 120):
        raise E2EFailure('Invalid final HTTP endpoint or list response contract.')
    invalid_request = spec.get('invalidRequest')
    invalid_query = spec.get('invalidQuery')
    if invalid_request is None and isinstance(invalid_query, dict) and any(
            key in invalid_query for key in ('method', 'path', 'body', 'expectedStatus', 'expectedError')):
        invalid_request = invalid_query
        invalid_query = None
    if invalid_query is not None and (not isinstance(invalid_query, dict) or not invalid_query or
            not all(isinstance(key, str) and isinstance(value, (str, int)) for key, value in invalid_query.items()
                    if key != 'route') or
            'route' in invalid_query and not isinstance(invalid_query['route'], str)):
        raise E2EFailure('Invalid final HTTP query contract.')
    if invalid_request is not None:
        if not isinstance(invalid_request, dict):
            raise E2EFailure('Invalid final HTTP negative request contract.')
        method = invalid_request.get('method', 'GET')
        path = invalid_request.get('path', invalid_request.get('route', spec['route']))
        body = invalid_request.get('body')
        expected_status = invalid_request.get('expectedStatus')
        if (method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE') or not isinstance(path, str) or
                not path.startswith('/') or path.startswith('//') or '\\' in path or '#' in path or
                any(part == '..' for part in urllib.parse.unquote(path).split('/')) or
                body is not None and not isinstance(body, dict) or
                expected_status is not None and (not isinstance(expected_status, int) or isinstance(expected_status, bool)
                                                  or not 400 <= expected_status <= 499) or
                invalid_request.get('expectedError') is not None and not isinstance(invalid_request.get('expectedError'), str)):
            raise E2EFailure('Invalid final HTTP negative request contract.')
    elif invalid_query is None:
        raise E2EFailure('HTTP list contract needs invalidQuery or invalidRequest.')


def _verify_project_entrypoint(project: Path, argv: list[str], label: str) -> None:
    def is_internal_regular_file(candidate: Path) -> bool:
        try:
            parts = candidate.relative_to(project).parts
        except ValueError:
            return False
        cursor = project
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return False
        return candidate.is_file()

    if argv[1] == '-m':
        module_parts = argv[2].split('.')
        candidates = [project.joinpath(*module_parts).with_suffix('.py'),
                      project.joinpath(*module_parts, '__main__.py')]
        candidates = [candidate for candidate in candidates if is_internal_regular_file(candidate)]
        if not candidates:
            raise E2EFailure(f'{label} module does not resolve to an application file inside the project.')
        return
    relative = Path(argv[1].replace('\\', '/'))
    candidate = project / relative
    if any((project.joinpath(*relative.parts[:index])).is_symlink()
           for index in range(1, len(relative.parts) + 1)):
        raise E2EFailure(f'{label} entry point may not traverse a symlink.')
    entrypoint = candidate.resolve()
    try:
        entrypoint.relative_to(project.resolve())
    except ValueError as exc:
        raise E2EFailure(f'{label} entry point escapes the project.') from exc
    if not entrypoint.is_file():
        raise E2EFailure(f'{label} entry point does not exist as a regular project file.')


def validate_plan(proposal: dict, scenario_id: str | None = None) -> dict:
    if not isinstance(proposal, dict):
        raise E2EFailure('Mahoraga proposal must be a JSON object.')
    tasks = proposal.get('tasks')
    if not isinstance(tasks, list) or len(tasks) < 4:
        raise E2EFailure('PASS criterion failed: Mahoraga must propose at least four tasks')
    if not all(isinstance(task, dict) for task in tasks):
        raise E2EFailure('Every planned task must be a JSON object.')
    ordered_ids = [task.get('id') for task in tasks]
    if not all(isinstance(ident, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{1,39}', ident)
               for ident in ordered_ids):
        raise E2EFailure('Every planned task needs a valid string ID.')
    ids = set(ordered_ids)
    if len(ids) != len(tasks):
        raise E2EFailure('Mahoraga plan has missing or duplicate task IDs')
    for task in tasks:
        if (not isinstance(task.get('allowedPaths'), list) or not task['allowedPaths'] or
                not all(isinstance(path, str) and path for path in task['allowedPaths'])):
            raise E2EFailure(f"{task.get('id')}: Mahoraga omitted the safe file scope")
        if (not isinstance(task.get('contracts'), list) or not task['contracts'] or
                not all(isinstance(contract, str) and contract for contract in task['contracts']) or
                not isinstance(task.get('dependsOn', []), list) or
                not all(isinstance(dep, str) for dep in task.get('dependsOn', [])) or
                not isinstance(task.get('title'), str) or not task['title'].strip() or
                not isinstance(task.get('goal'), str) or not task['goal'].strip() or
                not isinstance(task.get('acceptance'), (str, list)) or
                isinstance(task.get('acceptance'), list) and
                not all(isinstance(item, str) and item.strip() for item in task['acceptance']) or
                isinstance(task.get('acceptance'), str) and not task['acceptance'].strip()):
            raise E2EFailure(f"{task.get('id')}: Mahoraga omitted contracts or acceptance criteria")
        unknown = set(task.get('dependsOn', [])) - ids
        if unknown:
            raise E2EFailure(f"{task.get('id')}: unknown dependencies: {sorted(unknown)}")
    e2e = proposal.get('e2e')
    if not isinstance(e2e, dict):
        raise E2EFailure('Mahoraga did not provide a machine-readable final smoke contract.')
    e2e_mode = e2e.get('mode', 'http')
    if e2e_mode not in ('http', 'cli'):
        raise E2EFailure('The e2e mode must be http or cli.')
    if e2e_mode == 'cli':
        commands = e2e.get('commands')
        if not isinstance(commands, list) or len(commands) < 2:
            raise E2EFailure('CLI e2e contract needs at least two safe argv commands with expectedExitCode.')
        for item in commands:
            if not isinstance(item, dict):
                raise E2EFailure('Every CLI e2e command must be an object.')
            _validate_app_argv(item.get('argv'), max_length=20, label='CLI command')
            if not isinstance(item.get('expectedExitCode'), int) or isinstance(item.get('expectedExitCode'), bool):
                raise E2EFailure('Every CLI command must include an integer expectedExitCode.')
            expected_text = item.get('expectedContains')
            if not isinstance(expected_text, str) or not expected_text.strip() or len(expected_text) > 300:
                raise E2EFailure('Every CLI command must include a short expectedContains output check.')
        if not any(item['expectedExitCode'] == 0 for item in commands) or not any(item['expectedExitCode'] != 0 for item in commands):
            raise E2EFailure('CLI e2e contract must cover a successful and an invalid-input command.')
        entrypoints = {tuple(item['argv'][:3] if item['argv'][1] == '-m' else item['argv'][:2])
                       for item in commands}
        if len(entrypoints) != 1:
            raise E2EFailure('CLI e2e commands must target the same application entry point.')
    else:
        _validate_http_contract(e2e)
        if scenario_id == 'booking-system':
            requests = e2e.get('requests')
            creates = [index for index, item in enumerate(requests or []) if isinstance(item, dict) and
                       item.get('method') in ('POST', 'PUT') and isinstance(item.get('expectedStatus'), int) and
                       item['expectedStatus'] < 400] if isinstance(requests, list) else []
            conflicts = [index for index, item in enumerate(requests or []) if isinstance(item, dict) and
                         item.get('method') == 'POST' and item.get('expectedStatus') == 409] if isinstance(requests, list) else []
            if not creates or not any(index > creates[0] for index in conflicts):
                raise E2EFailure('Booking E2E contract must create a valid reservation and then assert a rejected conflicting reservation through ordered HTTP requests.')
    closure = transitive_dependencies(tasks)
    independent_pair = next(((left, right) for index, left in enumerate(ordered_ids) for right in ordered_ids[index + 1:]
                             if left not in closure[right] and right not in closure[left]), None)
    if not independent_pair:
        raise E2EFailure('PASS criterion failed: plan has no two dependency-independent tasks')
    leaves = [task for task in tasks if not any(task['id'] in closure[other['id']] for other in tasks)]
    final_integration = next((task for task in leaves if closure[task['id']] and
                              any(word in (task.get('title', '') + ' ' + task.get('goal', '')).lower()
                                  for word in ('integrat', 'end-to-end', 'final', 'сквоз', 'интегр', 'финал'))), None)
    if not final_integration:
        raise E2EFailure('PASS criterion failed: no dependent final integration task in the plan')
    return {'taskCount': len(tasks), 'e2eMode': e2e_mode, 'independentPair': list(independent_pair),
            'finalIntegrationTask': final_integration['id'], 'dependencyClosure': {key: sorted(value) for key, value in closure.items()}}


def capture_task_changes(task: dict) -> dict | None:
    """Capture verifiable source changes from Makora-owned temporary worktrees only."""
    worktree = task.get('worktree')
    if not worktree or not Path(worktree).is_dir():
        return None
    root = Path(worktree)
    tracked = git(root, 'diff', '--name-only', 'HEAD').splitlines()
    untracked = git(root, 'ls-files', '--others', '--exclude-standard').splitlines()
    all_paths = list(dict.fromkeys(tracked + untracked))
    source_paths = [name for name in all_paths if '__pycache__' not in Path(name).parts and
                    Path(name).suffix.lower() != '.pyc']
    allowed = set(task.get('allowedPaths') or [])
    contents = {}
    for name in source_paths:
        if name not in allowed:
            continue
        path = root / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 200_000:
            try:
                contents[name] = path.read_text(encoding='utf-8')
            except (UnicodeError, OSError):
                contents[name] = '<unreadable or non-text file>'
    diff = git(root, 'diff', '--no-ext-diff', 'HEAD', '--', *[name for name in tracked if name in allowed]) if any(name in allowed for name in tracked) else ''
    material = {'taskId': task['id'], 'worktree': str(root), 'branch': task.get('branch'),
                'baseCommit': git(root, 'rev-parse', 'HEAD'), 'status': git(root, 'status', '--short'),
                'changedFiles': source_paths, 'diff': diff, 'fileContents': contents}
    material['digest'] = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return material


def capture_test_design(task: dict) -> dict | None:
    """Preserve the actual independent tests and their machine-readable run contract."""
    folder_value = task.get('testDesignDir')
    if not folder_value:
        return None
    folder = Path(folder_value)
    if not folder.is_dir():
        return {'taskId': task['id'], 'directory': str(folder), 'error': 'test design directory is missing'}
    names = ['TEST_DESIGN.md', 'test-manifest.json', 'TASK.md', 'CONTRACTS.md', 'ACCEPTANCE.md']
    names.extend(task.get('testDesignFiles') or [])
    artifacts = {}
    for name in dict.fromkeys(names):
        path = folder / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= 200_000:
            try:
                artifacts[name.replace('\\', '/')] = path.read_text(encoding='utf-8')
            except (UnicodeError, OSError):
                artifacts[name.replace('\\', '/')] = '<unreadable or non-text file>'
    return {'taskId': task['id'], 'directory': str(folder), 'files': artifacts,
            'digest': hashlib.sha256(json.dumps(artifacts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def final_http_smoke(project: Path, root: Path, binary: Path, spec: object) -> dict:
    """Run harness-owned HTTP checks against the integrated app in Codex sandbox."""
    if not isinstance(spec, dict):
        raise E2EFailure('The approved plan has no machine-readable e2e launch/API contract.')
    _validate_http_contract(spec)
    argv = spec['launch']
    executable = sys.executable if argv[0] in ('python', 'python3') else shutil.which('node')
    if not executable:
        raise E2EFailure('The planned runtime is not installed.')
    from makora_core.agents.acceptance import _materialize_project
    sandbox_root = root / 'final-http-sandbox'
    sandbox_root.mkdir()
    _materialize_project(None, project, {}, {}, sandbox_root)
    _verify_project_entrypoint(sandbox_root, argv, 'HTTP launch')
    spec_path = sandbox_root / '.makora-tests' / 'e2e-spec.json'
    spec_path.write_text(json.dumps({**spec, 'launch': [executable, *argv[1:]]}, ensure_ascii=False), encoding='utf-8')
    probe = sandbox_root / '.makora-tests' / 'e2e-http.py'
    probe.write_text(_HTTP_PROBE, encoding='utf-8')
    command = [str(binary), '-c', 'windows.sandbox=elevated', 'sandbox', '-C', str(sandbox_root),
               '--permission-profile', ':workspace', '--', sys.executable, str(probe)]
    try:
        probe_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        completed = subprocess.run(command, cwd=sandbox_root, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace', timeout=180, env=probe_env)
    except subprocess.TimeoutExpired as exc:
        raise E2EFailure(f'Final sandboxed HTTP probe timed out: {exc}') from exc
    output = (completed.stdout or '') + (completed.stderr or '')
    marker = 'MAKORA_E2E_JSON:'
    lines = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    result = {'command': command, 'exitCode': completed.returncode, 'output': output[-16000:],
              'sandbox': str(sandbox_root)}
    if lines:
        try:
            result['checks'] = json.loads(lines[-1])
        except json.JSONDecodeError:
            pass
    expected_checks = _expected_http_check_count(spec)
    if completed.returncode or not isinstance(result.get('checks'), list) or len(result['checks']) != expected_checks:
        raise E2EFailure('Final isolated HTTP smoke failed: ' + json.dumps(result, ensure_ascii=False))
    return result


def _expected_http_check_count(spec: dict) -> int:
    requests = spec.get('requests')
    if not isinstance(requests, list):
        return 4  # list, search, empty result, and invalid input
    count = len(requests)
    invalid = spec.get('invalidRequest', spec.get('invalidQuery'))
    if isinstance(invalid, dict) and any(key in invalid for key in
                                          ('method', 'path', 'body', 'expectedStatus', 'expectedError')):
        count += 1
    return count


def _next_integration_candidate(tasks: list[dict], base_commit: str | None) -> dict | None:
    """Return at most one approval candidate from a single state snapshot.

    Integration advances the run's base commit. A second candidate from the same
    API snapshot was checked against the old commit and could then fail with
    TASK_BASE_OUTDATED. The caller must fetch fresh state before approving again.
    """
    for task in tasks:
        review = task.get('review') or {}
        tests = task.get('tests') or {}
        if (task.get('status') == 'review_completed' and review.get('verdict') == 'pass' and
                tests.get('independent') is True and tests.get('status') == 'passed' and
                task.get('worktreeBase') == base_commit and
                review.get('digest') == tests.get('digest') and
                not task.get('harnessApprovalRecorded')):
            return task
    return None


def final_cli_smoke(project: Path, root: Path, binary: Path, spec: object) -> dict:
    """Run the approved app's successful and invalid-input CLI examples in Codex sandbox."""
    if not isinstance(spec, dict) or spec.get('mode') != 'cli':
        raise E2EFailure('The approved plan has no CLI smoke contract.')
    commands = spec.get('commands')
    if not isinstance(commands, list) or len(commands) < 2:
        raise E2EFailure('The CLI smoke contract must include success and error commands.')
    from makora_core.agents.acceptance import _materialize_project
    sandbox_root = root / 'final-cli-sandbox'
    sandbox_root.mkdir()
    _materialize_project(None, project, {}, {}, sandbox_root)
    entrypoints = []
    for index, item in enumerate(commands):
        argv = item.get('argv') if isinstance(item, dict) else None
        _validate_app_argv(argv, max_length=20, label=f'CLI command {index}')
        _verify_project_entrypoint(sandbox_root, argv, f'CLI command {index}')
        entrypoints.append(tuple(argv[:3] if argv[1] == '-m' else argv[:2]))
    if len(set(entrypoints)) != 1:
        raise E2EFailure('CLI smoke commands must run the same application entry point.')
    results = []
    for index, item in enumerate(commands):
        argv = item.get('argv') if isinstance(item, dict) else None
        _validate_app_argv(argv, max_length=20, label=f'CLI command {index}')
        executable = sys.executable if argv[0] in ('python', 'python3') else shutil.which('node')
        if not executable:
            raise E2EFailure('The planned CLI runtime is not installed.')
        expected_exit = item.get('expectedExitCode')
        if not isinstance(expected_exit, int) or isinstance(expected_exit, bool):
            raise E2EFailure(f'CLI command {index} has no integer expectedExitCode.')
        command = [str(binary), '-c', 'windows.sandbox=elevated', 'sandbox', '-C', str(sandbox_root),
                   '--permission-profile', ':workspace', '--', executable, *argv[1:]]
        try:
            completed = subprocess.run(command, cwd=sandbox_root, capture_output=True, text=True,
                                       encoding='utf-8', errors='replace', timeout=120,
                                       env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        except subprocess.TimeoutExpired as exc:
            raise E2EFailure(f'Final sandboxed CLI command {index} timed out: {exc}') from exc
        output = (completed.stdout or '') + (completed.stderr or '')
        expected_text = item.get('expectedContains')
        passed = completed.returncode == expected_exit and (
            not expected_text or isinstance(expected_text, str) and expected_text in output)
        results.append({'name': str(item.get('name') or f'command-{index + 1}'), 'command': command,
                        'exitCode': completed.returncode, 'expectedExitCode': expected_exit,
                        'expectedContains': expected_text, 'output': output[-8000:], 'passed': passed})
    if not any(item.get('expectedExitCode') == 0 for item in results) or not any(
            item.get('expectedExitCode') != 0 for item in results):
        raise E2EFailure('Final CLI smoke needs at least one success and one invalid-input command.')
    failed = [item for item in results if not item['passed']]
    if failed:
        raise E2EFailure('Final isolated CLI smoke failed: ' + json.dumps(failed, ensure_ascii=False))
    return {'mode': 'cli', 'sandbox': str(sandbox_root), 'checks': results}


_HTTP_PROBE = r'''import json, os, re, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
root = Path.cwd()
spec = json.loads((root / '.makora-tests/e2e-spec.json').read_text(encoding='utf-8'))
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
env = os.environ.copy()
env.pop('GITHUB_TOKEN', None)
env.pop('GH_TOKEN', None)
env[spec['portEnv']] = str(port)
process = subprocess.Popen(spec['launch'], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:' + str(port) + spec.get('route', '/')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
opener = urllib.request.build_opener(NoRedirect())
def request(method, path, params=None, body=None):
    url = 'http://127.0.0.1:' + str(port) + path
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    data = None if body is None else json.dumps(body).encode('utf-8')
    headers = {'Accept':'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=3) as response:
            raw = response.read().decode('utf-8')
            try: payload = json.loads(raw) if raw else None
            except json.JSONDecodeError: payload = raw
            return response.status, payload, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8')
        try: payload = json.loads(raw) if raw else None
        except json.JSONDecodeError: payload = raw
        return exc.code, payload, dict(exc.headers.items())
def items(value):
    return value[spec['listKey']] if spec.get('listKey') else value
def field(value, path):
    current = value
    for piece in path.split('.'):
        if not isinstance(current, dict) or piece not in current:
            raise AssertionError('Missing response field: ' + path)
        current = current[piece]
    return current
def matches_expected(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and matches_expected(actual[key], value)
                                                for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matches_expected(actual[index], value) for index, value in enumerate(expected))
    return actual == expected
try:
    for attempt in range(60):
        try:
            status, body, headers = request('GET', spec.get('route','/'))
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if process.poll() is not None:
                raise RuntimeError('Application exited before accepting HTTP requests')
            time.sleep(.5)
    else:
        raise RuntimeError('Application did not accept HTTP requests')
    checks = []
    if spec.get('requests'):
        captures = {}
        responses = {}
        reference_pattern = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_-]{0,39})\.((?:json\.)?[A-Za-z][A-Za-z0-9_.-]{0,99})\}\}')
        def resolve_reference(match):
            request_name, capture_ref = match.group(1), match.group(2)
            assert request_name in responses, 'Request references a request that has not run yet'
            if request_name in captures and capture_ref in captures[request_name]:
                value = captures[request_name][capture_ref]
            else:
                field_path = capture_ref[5:] if capture_ref.startswith('json.') else capture_ref
                value = field(responses[request_name], field_path)
            assert value is not None and value != '', 'Missing captured response value'
            return value
        def substitute_path(value):
            return reference_pattern.sub(lambda match: urllib.parse.quote(str(resolve_reference(match)), safe=''), value)
        def substitute_data(value):
            if isinstance(value, dict):
                return {key: substitute_data(item) for key, item in value.items()}
            if isinstance(value, list):
                return [substitute_data(item) for item in value]
            if isinstance(value, str):
                exact = reference_pattern.fullmatch(value)
                if exact:
                    return resolve_reference(exact)
                return reference_pattern.sub(lambda match: str(resolve_reference(match)), value)
            return value
        for item in spec['requests']:
            path = substitute_path(item['path'])
            request_body = substitute_data(item.get('body'))
            status, body, headers = request(item['method'], path, body=request_body)
            assert status == item['expectedStatus'], item['name'] + ': expected HTTP ' + str(item['expectedStatus']) + ', received ' + str(status)
            for key, expected in item.get('expectedJson', {}).items():
                expected = substitute_data(expected)
                assert matches_expected(field(body, key), expected), item['name'] + ': JSON field mismatch: ' + key
            lower_headers = {key.lower(): value for key, value in headers.items()}
            for key, expected in item.get('expectedHeaders', {}).items():
                expected = substitute_data(expected)
                assert lower_headers.get(key.lower()) == expected, item['name'] + ': response header mismatch: ' + key
            captured = {}
            for alias, field_path in item.get('capture', {}).items():
                value = field(body, field_path[5:] if field_path.startswith('json.') else field_path)
                assert value is not None and value != '', item['name'] + ': empty captured field: ' + field_path
                captured[alias] = value
            captures[item['name']] = captured
            responses[item['name']] = body
            checks.append({'case':item['name'], 'status':status, 'response':body, 'headers':headers, 'captures':captured})
        invalid = spec.get('invalidRequest', spec.get('invalidQuery'))
        if isinstance(invalid, dict):
            structured = any(key in invalid for key in ('method', 'path', 'body', 'expectedStatus', 'expectedError'))
            if structured:
                path = invalid.get('path', invalid.get('route', spec.get('route', '/')))
                path = substitute_path(path)
                method = invalid.get('method', 'GET')
                params = {key:value for key,value in invalid.items() if key not in
                          ('path','route','method','body','expectedStatus','expectedError')}
                status, body, headers = request(method, path, params=substitute_data(params),
                                                 body=substitute_data(invalid.get('body')))
                expected_status = invalid.get('expectedStatus')
                assert (400 <= status < 500 if expected_status is None else status == expected_status) and isinstance(body, dict), 'Negative request did not return the expected JSON client error'
                expected_error = invalid.get('expectedError')
                if expected_error:
                    if expected_error in body:
                        assert body[expected_error] not in (None, '', [], {}), 'Negative request returned an empty error field'
                    else:
                        assert expected_error in (body.get('error'), body.get('code'), body.get('detail')), 'Negative request returned an unexpected error code'
                checks.append({'case':'invalid', 'status':status, 'response':body, 'headers':headers})
    else:
        entries = items(body)
        assert status == 200 and isinstance(entries, list) and entries, 'List endpoint must return records'
        first = entries[0]
        name = first[spec['nameField']]
        assert isinstance(name, str) and name, 'First record must have a non-empty name'
        checks.append({'case':'list', 'status':status, 'response':body})
        search_value = first.get(spec['searchParameter'], name)
        params = {spec['searchParameter']: str(search_value)}
        status, body, headers = request('GET', spec['route'], params=params)
        results = items(body)
        if isinstance(first, dict) and 'id' in first:
            found = any(isinstance(item, dict) and item.get('id') == first['id'] for item in results)
        else:
            found = any(isinstance(item, dict) and item.get(spec['nameField']) == name for item in results)
        assert status == 200 and isinstance(results, list) and found, 'Filter/search did not return the selected record'
        checks.append({'case':'search', 'status':status, 'response':body})
        status, body, headers = request('GET', spec['route'], params={spec['searchParameter']:'makora-e2e-no-match-9f3a5f'})
        assert status == 200 and items(body) == [], 'Empty search did not return an empty list'
        checks.append({'case':'empty', 'status':status, 'response':body})
        negative = spec.get('invalidRequest')
        invalid = spec.get('invalidQuery')
        params = None
        path = spec['route']
        method = 'GET'
        request_body = None
        expected_status = None
        expected_error = None
        if negative is None and isinstance(invalid, dict) and any(key in invalid for key in ('method','path','body','expectedStatus','expectedError')):
            negative, invalid = invalid, None
        if negative is not None:
            path = negative.get('path', negative.get('route', path))
            method = negative.get('method', 'GET')
            request_body = negative.get('body')
            expected_status = negative.get('expectedStatus')
            expected_error = negative.get('expectedError')
            params = {key:value for key,value in negative.items() if key not in ('path','route','method','body','expectedStatus','expectedError')}
        else:
            if 'route' in invalid:
                path = invalid['route']
                params = {key:value for key,value in invalid.items() if key != 'route'}
            else:
                params = invalid
        status, body, headers = request(method, path, params=params, body=request_body)
        assert (400 <= status < 500 if expected_status is None else status == expected_status) and isinstance(body, dict), 'Negative request did not return the expected JSON client error'
        if expected_error:
            # Contracts may name either an error code/value (e.g. "insufficient_stock")
            # or a response field (e.g. "error"). Treat a field name as a presence
            # assertion, while preserving exact matching for the traditional code form.
            if expected_error in body:
                assert body[expected_error] not in (None, '', [], {}), 'Negative request returned an empty error field'
            else:
                assert expected_error in (body.get('error'), body.get('code'), body.get('detail')), 'Negative request returned an unexpected error code'
        checks.append({'case':'invalid', 'status':status, 'response':body})
    print('MAKORA_E2E_JSON:' + json.dumps(checks, ensure_ascii=False))
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
'''


def resume(args: argparse.Namespace) -> int:
    """Resume a preserved REAL run through public APIs after a controller code fix."""
    root = Path(args.resume_root).resolve()
    evidence_path = root / 'evidence.json'
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    project = Path(evidence['projectRoot']).resolve()
    workspace = Path(evidence['makoraWorkspace']).resolve()
    binary = Path(args.codex_binary or evidence.get('appServerBinary') or os.environ.get('CODEX_APP_SERVER_BINARY', '')).resolve()
    if os.name != 'nt' or not binary.is_file():
        raise E2EFailure('Resume requires Windows and the same configured Codex App Server binary.')
    if evidence.get('status') == 'pass':
        raise E2EFailure('This evidence bundle is already complete.')
    port = args.port or free_port()
    origin = f'http://127.0.0.1:{port}'
    evidence['resumeAttempts'] = evidence.get('resumeAttempts', []) + [{'at': utc_now(), 'origin': origin}]
    atomic_json(evidence_path, evidence)
    stdout_path = root / 'makora-resume.stdout.log'
    stderr_path = root / 'makora-resume.stderr.log'
    env = os.environ.copy()
    env['CODEX_APP_SERVER_BINARY'] = str(binary)
    command = [sys.executable, '-m', 'makora_core.server', '--static', 'dist', '--workspace', str(workspace),
               '--host', '127.0.0.1', '--port', str(port), '--agent-root', str(project)]
    with stdout_path.open('w', encoding='utf-8') as stdout, stderr_path.open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                   stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            api = origin + '/api/agents'
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise E2EFailure('Makora failed to restart from the preserved run state.')
                try:
                    if request(origin + '/api/status', timeout=2).get('available'):
                        break
                except Exception:
                    time.sleep(.5)
            else:
                raise E2EFailure('Makora did not become ready while resuming.')
            token = request(api + '/token', origin=origin).get('token')
            if not token:
                raise E2EFailure('Same-origin token endpoint returned no token after restart.')
            status = wait_for_luna_status(api, token)
            if status.get('model') != MODEL or status.get('modelAvailable') is not True:
                raise E2EFailure('gpt-6-luna is unavailable during resume; no fallback is permitted.')
            run_id = evidence['runId']
            paused = request(api + f'/runs/{run_id}/autopilot', 'POST', {'enabled': False}, token=token)
            # Re-evaluate the exact saved Reviewer turn after a controller fix.
            # GET uses the normal session refresh and does not create a new turn.
            saved = request(api + '/state', token=token)
            saved_run = next(item for item in saved['runs'] if item['id'] == run_id)
            for task in saved_run['tasks']:
                if task.get('status') == 'review_unconfirmed' and task.get('reviewerSessionId'):
                    checked = request(api + '/sessions/' + task['reviewerSessionId'], token=token)
                    evidence.setdefault('reviewRechecks', []).append({'at': utc_now(), 'taskId': task['id'],
                        'sessionId': checked['id'], 'threadId': checked.get('threadId'), 'turnId': checked.get('turnId')})
            autopilot = request(api + f'/runs/{run_id}/autopilot', 'POST', {'enabled': True}, token=token)
            evidence.setdefault('resumes', []).append({'at': utc_now(), 'publicAutopilotStatus': autopilot.get('status'),
                                                        'publicPauseStatus': paused.get('status'), 'model': status.get('model'),
                                                        'rearmedViaPublicApi': True})
            atomic_json(evidence_path, evidence)
            deadline = time.monotonic() + args.run_timeout
            while time.monotonic() < deadline:
                state = request(api + '/state', token=token)
                current = next(item for item in state['runs'] if item['id'] == run_id)
                sessions = [item for item in state['sessions'] if item.get('runId') == run_id]
                if any(item.get('model') != MODEL for item in sessions):
                    raise E2EFailure('A resumed agent used a model other than gpt-6-luna.')
                evidence['sessions'] = session_snapshots(sessions, evidence.get('sessions'))
                task_map = {item['id']: item for item in current['tasks']}
                for item in sessions:
                    if item.get('role') == 'builder':
                        snap = capture_task_changes(task_map[item['taskId']])
                        if snap and not any(old.get('digest') == snap['digest'] for old in evidence.get('builderSnapshots', [])):
                            evidence.setdefault('builderSnapshots', []).append(snap)
                for task in current['tasks']:
                    design = capture_test_design(task)
                    if design and not any(old.get('taskId') == task['id'] and old.get('digest') == design.get('digest')
                                           for old in evidence.get('testDesignArtifacts', [])):
                        evidence.setdefault('testDesignArtifacts', []).append(design)
                evidence['taskStatuses'] = [{'id': task['id'], 'status': task.get('status'), 'worktree': task.get('worktree'),
                    'worktreeBase': task.get('worktreeBase'), 'baseCommit': current.get('baseCommit'),
                    'testDesignDir': task.get('testDesignDir'), 'testDesignFiles': task.get('testDesignFiles'),
                    'tests': task.get('tests'), 'review': task.get('review'), 'integrationCommit': task.get('integratedCommit'),
                    'integrationRecommendation': task.get('integrationRecommendation')} for task in current['tasks']]
                evidence['autopilotState'] = current.get('mahoragaAutopilot')
                atomic_json(evidence_path, evidence)
                task = _next_integration_candidate(current['tasks'], current.get('baseCommit'))
                if task:
                    result = request(api + f"/runs/{run_id}/tasks/{task['id']}/integrate", 'POST',
                                     {'confirmed': True}, token=token)
                    task['harnessApprovalRecorded'] = True
                    evidence.setdefault('approvals', []).append({'type': 'integration', 'taskId': task['id'],
                        'actor': 'E2E harness user confirmation via public API', 'at': utc_now(), 'commit': result.get('commit')})
                    evidence.setdefault('integrations', []).append({'taskId': task['id'], **result})
                    atomic_json(evidence_path, evidence)
                final = request(api + f'/runs/{run_id}', token=token)
                if run_is_completed(final):
                    evidence['finalRun'] = final
                    evidence['finalGitStatus'] = git(project, 'status', '--porcelain')
                    evidence['finalCommit'] = git(project, 'rev-parse', 'HEAD')
                    evidence['gitHistory'] = git(project, 'log', '--oneline', '--max-count=30').splitlines()
                    evidence['finalFiles'] = git(project, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
                    evidence['finalWorkingTreeClean'] = not bool(evidence['finalGitStatus'])
                    evidence['apiSmoke'] = final_http_smoke(project, root, binary, evidence['plan'].get('e2e'))
                    builders = [item for item in evidence['sessions'] if item.get('role') == 'builder']
                    pairs = []
                    parse = lambda value: dt.datetime.fromisoformat(value) if value else None
                    snapshots = {item['taskId'] for item in evidence.get('builderSnapshots', []) if item.get('changedFiles')}
                    for index, left in enumerate(builders):
                        for right in builders[index + 1:]:
                            if left.get('taskId') == right.get('taskId') or left.get('cwd') == right.get('cwd'):
                                continue
                            left_start, right_start = parse(left.get('executionObservedStartAt')), parse(right.get('executionObservedStartAt'))
                            left_end, right_end = parse(left.get('executionObservedEndAt')), parse(right.get('executionObservedEndAt'))
                            if not all((left_start, right_start, left_end, right_end)):
                                continue
                            start, end = max(left_start, right_start), min(left_end, right_end)
                            overlap = max(0.0, (end - start).total_seconds())
                            if overlap > 0 and left['taskId'] in snapshots and right['taskId'] in snapshots:
                                pairs.append({'tasks': [left['taskId'], right['taskId']], 'threads': [left['threadId'], right['threadId']],
                                              'worktrees': [left['cwd'], right['cwd']], 'overlapSeconds': round(overlap, 3)})
                    evidence['confirmedParallelBuilderPairs'] = pairs
                    if not pairs:
                        raise E2EFailure('No two independent Builder sessions both showed code changes during overlapping active intervals.')
                    if not evidence['finalWorkingTreeClean']:
                        raise E2EFailure('Final temporary application repository has uncommitted changes.')
                    evidence['completedAt'] = utc_now()
                    evidence['status'] = 'pass'
                    atomic_json(evidence_path, evidence)
                    break
                auto = final.get('mahoragaAutopilot', {})
                if auto.get('status') in ('needs_human', 'failed', 'limit_reached'):
                    raise E2EFailure('Resumed autopilot stopped for human attention: ' + str(auto.get('lastError')))
                blocked_task = terminal_task_blocker(final)
                if blocked_task:
                    raise E2EFailure(f'Required task {blocked_task} is blocked; see preserved run state.')
                time.sleep(args.poll_seconds)
            else:
                raise E2EFailure('Resumed autonomous workflow exceeded the configured timeout.')
        except Exception as exc:
            evidence['completedAt'] = utc_now()
            evidence['status'] = 'fail' if isinstance(exc, E2EFailure) else 'blocked_or_error'
            evidence['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            atomic_json(evidence_path, evidence)
            raise
        finally:
            if process.poll() is None:
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10, check=False)
                    process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
    print(json.dumps({'status': evidence['status'], 'evidence': str(evidence_path), 'runId': evidence.get('runId'),
                      'integrations': evidence.get('integrations', []),
                      'parallelPairs': evidence.get('confirmedParallelBuilderPairs', [])}, ensure_ascii=False, indent=2))
    return 0


def run(args: argparse.Namespace) -> int:
    if os.name != 'nt':
        raise E2EFailure('This real sandbox E2E is Windows-only.')
    binary = Path(args.codex_binary or os.environ.get('CODEX_APP_SERVER_BINARY', '')).expanduser()
    if not binary.is_file():
        raise E2EFailure('Set CODEX_APP_SERVER_BINARY to the installed codex.exe; the script will not switch models or bypass the sandbox.')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    root = Path(args.output_root or Path('C:/m')).resolve() / f'makora-e2e-{stamp}-{uuid.uuid4().hex[:6]}'
    scenario_name, case_brief = SCENARIOS.get(args.scenario, SCENARIOS['task-manager'])
    project = root / 'application-project'
    workspace = root / 'makora-workspace'
    if len(str(project)) > 120:
        raise E2EFailure('Temporary project path is too deep for reliable Windows Git worktrees; use a shorter --output-root (for example C:/m).')
    root.mkdir(parents=True, exist_ok=False)
    project.mkdir()
    evidence_path = root / 'evidence.json'
    server_stdout = root / 'makora-server.stdout.log'
    server_stderr = root / 'makora-server.stderr.log'
    port = args.port or free_port()
    origin = f'http://127.0.0.1:{port}'
    evidence = {'startedAt': utc_now(), 'status': 'running', 'modelRequired': MODEL,
                'appServerBinary': str(binary), 'appServerVersion': None, 'projectRoot': str(project),
                'makoraWorkspace': str(workspace), 'scenarioId': args.scenario, 'case': scenario_name,
                'caseBrief': case_brief, 'origin': origin,
                'approvals': [], 'plan': None, 'runId': None, 'sessions': [], 'builderSnapshots': [],
                'parallelObservations': [], 'finalGitStatus': None, 'apiSmoke': [], 'failure': None}
    atomic_json(evidence_path, evidence)

    try:
        git(project, 'init', '--initial-branch=main')
        git(project, 'config', 'user.name', 'Makora E2E Harness')
        git(project, 'config', 'user.email', 'makora-e2e@localhost')
        (project / 'README.md').write_text('# Empty temporary project\n\nMakora will choose the application layout.\n', encoding='utf-8')
        git(project, 'add', 'README.md')
        git(project, 'commit', '-m', 'test fixture: empty project for Makora autonomous E2E')
        evidence['initialCommit'] = git(project, 'rev-parse', 'HEAD')
        evidence['initialFiles'] = git(project, 'ls-tree', '--name-only', 'HEAD').splitlines()
        atomic_json(evidence_path, evidence)
    except Exception as exc:
        evidence['completedAt'] = utc_now()
        evidence['status'] = 'fail'
        evidence['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        atomic_json(evidence_path, evidence)
        raise

    env = os.environ.copy()
    env['CODEX_APP_SERVER_BINARY'] = str(binary)
    command = [sys.executable, '-m', 'makora_core.server', '--static', 'dist', '--workspace', str(workspace),
               '--host', '127.0.0.1', '--port', str(port), '--agent-root', str(project)]
    with server_stdout.open('w', encoding='utf-8') as stdout, server_stderr.open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                   stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        try:
            api = origin + '/api/agents'
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise E2EFailure('Makora server exited during startup; inspect preserved stderr log.')
                try:
                    page_status = request(origin + '/api/status', timeout=2)
                    if page_status.get('available'):
                        break
                except Exception:
                    time.sleep(0.5)
            else:
                raise E2EFailure('Makora server did not become ready within 60 seconds.')

            token_result = request(api + '/token', origin=origin)
            token = token_result.get('token')
            if not token:
                raise E2EFailure('Same-origin Makora token endpoint returned no token.')
            status = wait_for_luna_status(api, token)
            evidence['appServerVersion'] = status.get('appServerVersion')
            evidence['modelAvailable'] = status.get('modelAvailable')
            evidence['model'] = status.get('model')
            if status.get('model') != MODEL or status.get('modelAvailable') is not True:
                raise E2EFailure('Required gpt-6-luna is not available; no fallback model is permitted.')
            atomic_json(evidence_path, evidence)

            e2e_guidance = ('Финальный контракт e2e должен иметь mode=cli и commands: минимум одна успешная команда и '
                            'одна команда с некорректным вводом, каждая с argv и expectedExitCode.'
                            if args.scenario == 'file-analyzer' else
                            'Выбери e2e.mode=http для HTTP-приложения или e2e.mode=cli для CLI; задай точный контракт '
                            'успешного и отрицательного функционального сценария. Для CRUD API опиши list/filter и negative request; '
                            'для API без list endpoint задай e2e.requests как упорядоченные реальные запросы с name, method, path, '
                            'expectedStatus, необязательными JSON body и expectedJson/expectedHeaders. В requests должны быть успешный и отрицательный ответы '
                            'либо добавь отдельный структурированный invalidQuery с method/path/expectedStatus. capture — объект alias→путь поля JSON, например {"studentId":"id"}; '
                            'в последующих запросах подставляй {{requestName.alias}}, например {{createStudent.studentId}}. Не используй массив capture. '
                            'HTTP negative request может задавать method/path/body/expectedStatus/expectedError; expectedError задавай либо как код/текст ошибки, либо как имя непустого поля ответа (например, "error").')
            if args.scenario == 'booking-system':
                e2e_guidance += (' Для сценария бронирования обязательно задай e2e.requests как упорядоченную последовательность: успешное создание брони для существующего помещения, затем конфликтующая бронь того же помещения на пересекающийся интервал с ожидаемым отказом. Не проверяй наличие бронирований до создания первой брони и не полагайся на непустой начальный список.')
            plan_session = request(api + '/plans', 'POST', {'projectRoot': str(project), 'brief': f'# {scenario_name}\n\n{case_brief}',
                                      'context': 'Пустой Git-проект. README описывает только то, что приложение ещё не создано. '
                                                 'Стек, структуру, API пути, модули и имена файлов выбери самостоятельно. '
                                                 'Данные приложения должны быть локальными фикстурами при необходимости. Формат каждого task: '
                                                 'dependsOn, contracts, mocks, allowedPaths — массивы строк (если существующих mock-файлов нет, mocks: []); '
                                                 'allowedPaths для КАЖДОЙ задачи, включая финальные проверки, должен содержать точные допустимые файлы. '
                                                 'не помещай пояснительный текст в mocks. title, goal, acceptance — строки. '
                                                 'Сначала задай задачу создания фикстур, если они нужны, и связывай с ней потребителей зависимостями. '
                                                 'Критерии самого тестового задания: не менее четырёх реальных задач; минимум две задачи должны быть независимыми по DAG и пригодными для одновременного Builder; включи связанную финальную интеграцию/проверку. Это критерии разбиения, не готовая архитектура. '
                                                 + e2e_guidance}, token=token, timeout=210)
            evidence['planner'] = {'sessionId': plan_session.get('id'), 'threadId': plan_session.get('threadId'),
                                   'turnId': plan_session.get('turnId'), 'model': plan_session.get('model'),
                                   'turnHistory': plan_session.get('turnHistory', [])}
            atomic_json(evidence_path, evidence)
            evidence['plannerRevisions'] = []
            plan_shape = None
            planner = None
            for revision_index in range(MAX_PLAN_REVISIONS + 1):
                plan_deadline = time.monotonic() + args.plan_timeout
                feedback = None
                while time.monotonic() < plan_deadline:
                    planner = request(api + '/sessions/' + plan_session['id'], token=token, timeout=30)
                    if planner.get('status') in ('failed', 'unconfirmed'):
                        raise E2EFailure('Mahoraga planner failed or became unconfirmed: ' +
                                         json.dumps(planner.get('error') or planner.get('planError'), ensure_ascii=False))
                    if planner.get('status') == 'completed':
                        if planner.get('planError'):
                            feedback = json.dumps(planner['planError'], ensure_ascii=False)
                        elif isinstance(planner.get('proposal'), dict):
                            try:
                                plan_shape = validate_plan(planner['proposal'], args.scenario)
                            except E2EFailure as exc:
                                feedback = str(exc)
                            else:
                                break
                        elif not planner.get('planRevisionPending'):
                            feedback = 'Планировщик завершил turn, но не вернул объект proposal и не указал диагностическую ошибку.'
                    if feedback:
                        evidence['plannerRevisions'].append({'attempt': revision_index, 'feedback': feedback,
                                                             'proposal': planner.get('proposal')})
                        break
                    evidence['plannerStatus'] = planner.get('status')
                    atomic_json(evidence_path, evidence)
                    time.sleep(args.poll_seconds)
                if plan_shape:
                    break
                if not feedback:
                    raise E2EFailure('Mahoraga did not return a plan before the configured timeout.')
                if revision_index >= MAX_PLAN_REVISIONS:
                    proposal = planner.get('proposal') if isinstance(planner, dict) else None
                    proposed_tasks = proposal.get('tasks') if isinstance(proposal, dict) else None
                    evidence['plan'] = {
                        'summary': proposal.get('summary') if isinstance(proposal, dict) else None,
                        'validation': {'valid': False, 'taskCount': len(proposed_tasks) if isinstance(proposed_tasks, list) else 0,
                                       'failure': feedback},
                        'e2e': proposal.get('e2e') if isinstance(proposal, dict) else None,
                        'risks': proposal.get('risks', []) if isinstance(proposal, dict) else [],
                        'openQuestions': proposal.get('openQuestions', []) if isinstance(proposal, dict) else [],
                        'tasks': [{'id': item.get('id'), 'title': item.get('title'), 'goal': item.get('goal'),
                                   'dependsOn': item.get('dependsOn', []), 'contracts': item.get('contracts', []),
                                   'allowedPaths': item.get('allowedPaths', []), 'acceptance': item.get('acceptance')}
                                  for item in proposed_tasks if isinstance(item, dict)]
                        if isinstance(proposed_tasks, list) else [],
                    }
                    atomic_json(evidence_path, evidence)
                    raise E2EFailure('Mahoraga plan remained invalid after two same-thread correction requests: ' + feedback)
                revision = request(api + '/plans/' + plan_session['id'] + '/revise', 'POST',
                                   {'feedback': feedback[:5000]}, token=token, timeout=30)
                evidence['plannerRevisions'][-1].update({'requestedAt': utc_now(),
                    'threadId': revision.get('threadId'), 'turnId': revision.get('turnId'),
                    'operationId': revision.get('operationId'), 'status': revision.get('status')})
                evidence['planner']['turnHistory'] = revision.get('turnHistory', evidence['planner'].get('turnHistory', []))
                atomic_json(evidence_path, evidence)
            if not plan_shape:
                raise E2EFailure('Mahoraga returned no valid plan.')
            evidence['plannerStatus'] = planner.get('status')
            evidence['planner']['turnHistory'] = planner.get('turnHistory', evidence['planner'].get('turnHistory', []))
            evidence['planner']['status'] = planner.get('status')
            evidence['plan'] = {'summary': planner['proposal'].get('summary'), 'validation': plan_shape,
                                'e2e': planner['proposal'].get('e2e'),
                                'risks': planner['proposal'].get('risks', []),
                                'openQuestions': planner['proposal'].get('openQuestions', []),
                                'tasks': [{'id': item['id'], 'title': item['title'], 'goal': item['goal'],
                                           'dependsOn': item.get('dependsOn', []), 'contracts': item.get('contracts', []),
                                           'allowedPaths': item.get('allowedPaths', []), 'acceptance': item.get('acceptance')}
                                          for item in planner['proposal']['tasks']]}
            atomic_json(evidence_path, evidence)
            run = request(api + '/plans/' + plan_session['id'] + '/approve', 'POST', {}, token=token)
            evidence['approvals'].append({'type': 'plan', 'actor': 'E2E harness user confirmation via public API',
                                          'at': utc_now(), 'runId': run['id']})
            evidence['runId'] = run['id']
            atomic_json(evidence_path, evidence)
            autopilot = request(api + '/runs/' + run['id'] + '/autopilot', 'POST', {'enabled': True}, token=token)
            evidence['autopilotStarted'] = {'status': autopilot.get('status'), 'at': utc_now(),
                                            'maxActions': 80, 'maxDecisions': 40, 'maxConcurrentAgents': 4,
                                            'maxConcurrentBuilders': 2}
            atomic_json(evidence_path, evidence)

            deadline = time.monotonic() + args.run_timeout
            previous_parallel = set()
            parallel_started = None
            while time.monotonic() < deadline:
                state = request(api + '/state', token=token)
                current_run = next(item for item in state['runs'] if item['id'] == run['id'])
                sessions = [item for item in state['sessions'] if item.get('runId') == run['id']]
                unexpected_models = sorted({item.get('model') for item in sessions if item.get('model') != MODEL})
                if unexpected_models:
                    raise E2EFailure('A real agent used a model other than the required gpt-6-luna: ' + repr(unexpected_models))
                evidence['sessions'] = session_snapshots(sessions, evidence.get('sessions'))
                tasks_by_id = {item['id']: item for item in current_run['tasks']}
                for item in sessions:
                    if item.get('role') != 'builder':
                        continue
                    task_snapshot = capture_task_changes(tasks_by_id[item['taskId']])
                    if task_snapshot:
                        previous = next((entry for entry in reversed(evidence['builderSnapshots'])
                                         if entry['digest'] == task_snapshot['digest']), None)
                        if not previous:
                            evidence['builderSnapshots'].append(task_snapshot)
                running_builders = {item['threadId'] for item in sessions if item.get('role') == 'builder' and item.get('status') == 'running'}
                if len(running_builders) >= 2:
                    snapshot = {'at': utc_now(), 'threadIds': sorted(running_builders)}
                    evidence['parallelObservations'].append(snapshot)
                    if running_builders != previous_parallel:
                        if parallel_started is not None:
                            evidence['parallelWindows'].append({'from': parallel_started, 'to': utc_now()})
                        parallel_started = utc_now()
                elif parallel_started is not None:
                    evidence.setdefault('parallelWindows', []).append({'from': parallel_started, 'to': utc_now()})
                    parallel_started = None
                previous_parallel = running_builders
                evidence['taskStatuses'] = [{'id': task['id'], 'status': task.get('status'), 'worktree': task.get('worktree'),
                                             'worktreeBase': task.get('worktreeBase'), 'baseCommit': current_run.get('baseCommit'),
                                             'testDesignDir': task.get('testDesignDir'), 'testDesignFiles': task.get('testDesignFiles'),
                                             'tests': task.get('tests'), 'review': task.get('review'),
                                             'integrationCommit': task.get('integratedCommit'),
                                             'integrationRecommendation': task.get('integrationRecommendation')}
                                            for task in current_run['tasks']]
                for task in current_run['tasks']:
                    design = capture_test_design(task)
                    if design:
                        prior = next((item for item in evidence.get('testDesignArtifacts', [])
                                      if item.get('taskId') == task['id'] and item.get('digest') == design.get('digest')), None)
                        if not prior:
                            evidence.setdefault('testDesignArtifacts', []).append(design)
                evidence['autopilotState'] = current_run.get('mahoragaAutopilot')
                atomic_json(evidence_path, evidence)

                # The test harness is the human approver. Integrate only after
                # current-base independent tests and Reviewer evidence are present.
                task = _next_integration_candidate(current_run['tasks'], current_run.get('baseCommit'))
                if task:
                    integrated = request(api + f"/runs/{run['id']}/tasks/{task['id']}/integrate", 'POST', {'confirmed': True}, token=token)
                    task['harnessApprovalRecorded'] = True
                    evidence['approvals'].append({'type': 'integration', 'taskId': task['id'],
                                                  'actor': 'E2E harness user confirmation via public API',
                                                  'at': utc_now(), 'commit': integrated.get('commit')})
                    evidence['integrations'] = evidence.get('integrations', []) + [{'taskId': task['id'], **integrated}]
                    atomic_json(evidence_path, evidence)

                final = request(api + '/runs/' + run['id'], token=token)
                if run_is_completed(final):
                    evidence['finalRun'] = final
                    break
                auto = final.get('mahoragaAutopilot', {})
                if auto.get('status') in ('needs_human', 'failed', 'limit_reached'):
                    try:
                        pending_approvals = request(api + '/approvals', token=token)
                        evidence['pendingCodexApprovalsAtStop'] = redacted_approval_evidence(pending_approvals)
                    except Exception as exc:
                        evidence['approvalEvidenceError'] = type(exc).__name__
                    atomic_json(evidence_path, evidence)
                    raise E2EFailure('Autopilot stopped for human attention: ' + str(auto.get('lastError')))
                blocked_task = terminal_task_blocker(final)
                if blocked_task:
                    raise E2EFailure(f'Required task {blocked_task} is blocked and needs a human decision; see preserved evidence.')
                time.sleep(args.poll_seconds)
            else:
                raise E2EFailure('Autonomous workflow exceeded the configured run timeout.')

            git_status = git(project, 'status', '--porcelain')
            if parallel_started is not None:
                evidence.setdefault('parallelWindows', []).append({'from': parallel_started, 'to': utc_now()})
                parallel_started = None
            windows = evidence.get('parallelWindows', [])
            durations = []
            for window in windows:
                start = dt.datetime.fromisoformat(window['from'])
                end = dt.datetime.fromisoformat(window['to'])
                durations.append(max(0.0, (end - start).total_seconds()))
            evidence['parallelOverlapSeconds'] = round(sum(durations), 3)
            if not evidence['parallelObservations'] or evidence['parallelOverlapSeconds'] <= 0:
                raise E2EFailure('Full E2E criterion failed: no observed interval with two active Builder sessions.')
            evidence['confirmedParallelBuilderPairs'] = confirmed_builder_pairs(
                evidence.get('sessions', []), evidence.get('builderSnapshots', []))
            if not evidence['confirmedParallelBuilderPairs']:
                raise E2EFailure('Full E2E criterion failed: parallel Builders did not both create files in distinct worktrees during overlapping turns.')
            evidence['finalGitStatus'] = git_status
            evidence['finalCommit'] = git(project, 'rev-parse', 'HEAD')
            evidence['gitHistory'] = git(project, 'log', '--oneline', '--decorate', '--max-count=30').splitlines()
            evidence['finalFiles'] = git(project, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
            evidence['finalWorkingTreeClean'] = not bool(git_status)
            if not evidence['finalWorkingTreeClean']:
                raise E2EFailure('Final temporary project worktree is not clean after integration.')
            e2e_contract = evidence['plan'].get('e2e')
            if isinstance(e2e_contract, dict):
                if e2e_contract.get('mode', 'http') == 'cli':
                    evidence['apiSmoke'] = final_cli_smoke(project, root, binary, e2e_contract)
                else:
                    evidence['apiSmoke'] = final_http_smoke(project, root, binary, e2e_contract)
            else:
                evidence['apiSmoke'] = {'status': 'covered_by_independent_project_tests',
                                        'note': 'CLI or non-HTTP project; functional commands were executed in the independent sandbox suite.'}
            evidence['completedAt'] = utc_now()
            evidence['status'] = 'pass'
            atomic_json(evidence_path, evidence)
        except Exception as exc:
            evidence['completedAt'] = utc_now()
            evidence['status'] = 'fail' if isinstance(exc, E2EFailure) else 'blocked_or_error'
            evidence['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            try:
                evidence['finalGitStatus'] = git(project, 'status', '--porcelain')
                evidence['finalCommit'] = git(project, 'rev-parse', 'HEAD')
                evidence['gitHistory'] = git(project, 'log', '--oneline', '--max-count=30').splitlines()
                evidence['finalFiles'] = git(project, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
            except Exception:
                pass
            atomic_json(evidence_path, evidence)
            raise
        finally:
            if process.poll() is None:
                try:
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10, check=False)
                    process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
    print(json.dumps({'status': evidence['status'], 'evidence': str(evidence_path),
                      'projectRoot': str(project), 'runId': evidence.get('runId'),
                      'taskCount': evidence.get('plan', {}).get('validation', {}).get('taskCount'),
                      'parallelSamples': len(evidence.get('parallelObservations', [])),
                      'integrations': evidence.get('integrations', [])}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    # Disposable projects and Codex child processes need no unrelated GitHub credentials.
    for name in ('GITHUB_TOKEN', 'GH_TOKEN'):
        os.environ.pop(name, None)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary', help='Codex App Server binary; defaults to CODEX_APP_SERVER_BINARY')
    parser.add_argument('--scenario', choices=sorted(SCENARIOS), default='task-manager', help='Independent real E2E project case')
    parser.add_argument('--output-root', help='Temporary root directory; defaults to C:/m to keep Windows Git worktree paths short')
    parser.add_argument('--resume-root', help='Resume a preserved evidence directory after a Makora controller fix')
    parser.add_argument('--port', type=int, help='Local Makora server port; defaults to an available port')
    parser.add_argument('--plan-timeout', type=int, default=900)
    parser.add_argument('--run-timeout', type=int, default=7200)
    parser.add_argument('--poll-seconds', type=float, default=1.0)
    args = parser.parse_args()
    try:
        return resume(args) if args.resume_root else run(args)
    except E2EFailure as exc:
        print(f'E2E BLOCKED/FAILED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

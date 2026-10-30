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
критерии готовности. Финальная проверка должна выполнять реальные HTTP-запросы
к приложению, включая фильтр, пустой результат и некорректный запрос.
В JSON плана добавь объект e2e для независимой итоговой проверки: launch — массив
argv запуска сервера (первый элемент python или node), portEnv — имя переменной
окружения для порта, route — путь списка, searchParameter — параметр поиска по
названию, invalidQuery — объект параметров, вызывающих HTTP 4xx, nameField —
поле названия записи, listKey — ключ массива в ответе или null для корневого
массива. Выбери эти значения самостоятельно вместе с архитектурой. Сервер
должен поддерживать локальный порт через указанную переменную окружения.
'''


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


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *args], text=True, encoding='utf-8', errors='replace',
                            capture_output=True, timeout=30)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or '(git returned a non-zero exit code without output)'
        raise E2EFailure(f'git {args[0]} failed (exit {result.returncode}): {detail[-1500:]}')
    return result.stdout.strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def request(url: str, method: str = 'GET', body: dict | None = None,
            token: str | None = None, origin: str | None = None, timeout: float = 30) -> dict:
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
    if not isinstance(payload, dict):
        raise E2EFailure(f'{method} {url} did not return a JSON object')
    if 'result' in payload:
        return payload['result']
    return payload


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


def validate_plan(proposal: dict) -> dict:
    tasks = proposal.get('tasks')
    if not isinstance(tasks, list) or len(tasks) < 4:
        raise E2EFailure('PASS criterion failed: Mahoraga must propose at least four tasks')
    ordered_ids = [task.get('id') for task in tasks if isinstance(task, dict)]
    ids = set(ordered_ids)
    if len(ids) != len(tasks):
        raise E2EFailure('Mahoraga plan has missing or duplicate task IDs')
    for task in tasks:
        if not task.get('allowedPaths'):
            raise E2EFailure(f"{task.get('id')}: Mahoraga omitted the safe file scope")
        if not task.get('contracts') or not task.get('acceptance'):
            raise E2EFailure(f"{task.get('id')}: Mahoraga omitted contracts or acceptance criteria")
        unknown = set(task.get('dependsOn', [])) - ids
        if unknown:
            raise E2EFailure(f"{task.get('id')}: unknown dependencies: {sorted(unknown)}")
    if not isinstance(proposal.get('e2e'), dict):
        raise E2EFailure('Mahoraga did not provide a machine-readable launch/API contract for final HTTP verification.')
    closure = transitive_dependencies(tasks)
    independent_pair = next(((left, right) for index, left in enumerate(ordered_ids) for right in ordered_ids[index + 1:]
                             if left not in closure[right] and right not in closure[left]), None)
    if not independent_pair:
        raise E2EFailure('PASS criterion failed: plan has no two dependency-independent tasks')
    leaves = [task for task in tasks if not any(task['id'] in closure[other['id']] for other in tasks)]
    final_integration = next((task for task in leaves if closure[task['id']] and
                              any(word in (task.get('title', '') + ' ' + task.get('goal', '')).lower()
                                  for word in ('integrat', 'end-to-end', 'final', 'сквоз', 'интеграц', 'финал'))), None)
    if not final_integration:
        raise E2EFailure('PASS criterion failed: no dependent final integration task in the plan')
    return {'taskCount': len(tasks), 'independentPair': list(independent_pair),
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
    argv = spec.get('launch')
    if (not isinstance(argv, list) or len(argv) < 2 or len(argv) > 12 or
            not all(isinstance(x, str) and x and '\0' not in x for x in argv) or
            argv[0] not in ('python', 'python3', 'node')):
        raise E2EFailure('The e2e launch command must be an argv array starting with python or node.')
    for key in ('portEnv', 'route', 'searchParameter', 'nameField'):
        if not isinstance(spec.get(key), str) or not spec[key] or len(spec[key]) > 120:
            raise E2EFailure(f'Invalid final HTTP contract field: {key}')
    if (not spec['route'].startswith('/') or spec['route'].startswith('//') or '?' in spec['route'] or
            not isinstance(spec.get('invalidQuery'), dict) or not spec['invalidQuery'] or
            not all(isinstance(k, str) and isinstance(v, (str, int)) for k, v in spec['invalidQuery'].items()) or
            spec.get('listKey') is not None and not isinstance(spec['listKey'], str)):
        raise E2EFailure('Invalid final HTTP endpoint or negative-query contract.')
    executable = sys.executable if argv[0] in ('python', 'python3') else shutil.which('node')
    if not executable:
        raise E2EFailure('The planned runtime is not installed.')
    from makora_core.agents.acceptance import _materialize_project
    sandbox_root = root / 'final-http-sandbox'
    sandbox_root.mkdir()
    _materialize_project(None, project, {}, {}, sandbox_root)
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
    output = completed.stdout + completed.stderr
    marker = 'MAKORA_E2E_JSON:'
    lines = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    result = {'command': command, 'exitCode': completed.returncode, 'output': output[-16000:],
              'sandbox': str(sandbox_root)}
    if lines:
        try:
            result['checks'] = json.loads(lines[-1])
        except json.JSONDecodeError:
            pass
    if completed.returncode or not isinstance(result.get('checks'), list) or len(result['checks']) != 4:
        raise E2EFailure('Final isolated HTTP smoke failed: ' + json.dumps(result, ensure_ascii=False))
    return result


_HTTP_PROBE = r'''import json, os, socket, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
root = Path.cwd()
spec = json.loads((root / '.makora-tests/e2e-spec.json').read_text(encoding='utf-8'))
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
env = os.environ.copy()
env[spec['portEnv']] = str(port)
process = subprocess.Popen(spec['launch'], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
base = 'http://127.0.0.1:' + str(port) + spec['route']
def get(params=None):
    url = base + ('?' + urllib.parse.urlencode(params) if params else '')
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8'))
def items(value):
    return value[spec['listKey']] if spec.get('listKey') else value
try:
    for attempt in range(60):
        try:
            status, body = get()
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if process.poll() is not None:
                raise RuntimeError('Application exited before accepting HTTP requests')
            time.sleep(.5)
    else:
        raise RuntimeError('Application did not accept HTTP requests')
    entries = items(body)
    assert status == 200 and isinstance(entries, list) and entries, 'List endpoint must return records'
    name = entries[0][spec['nameField']]
    assert isinstance(name, str) and name, 'First record must have a non-empty name'
    checks = [{'case':'list', 'status':status, 'response':body}]
    status, body = get({spec['searchParameter']: name})
    assert status == 200 and any(item.get(spec['nameField']) == name for item in items(body)), 'Search did not return the expected record'
    checks.append({'case':'search', 'status':status, 'response':body})
    status, body = get({spec['searchParameter']: 'makora-e2e-no-match-9f3a5f'})
    assert status == 200 and items(body) == [], 'Empty search did not return an empty list'
    checks.append({'case':'empty', 'status':status, 'response':body})
    status, body = get(spec['invalidQuery'])
    assert 400 <= status < 500 and isinstance(body, dict), 'Invalid query did not return a JSON 4xx error'
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
            status = request(api + '/status', token=token)
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
                evidence['sessions'] = [{'id': item['id'], 'role': item.get('role'), 'taskId': item.get('taskId'),
                    'threadId': item.get('threadId'), 'turnId': item.get('turnId'), 'model': item.get('model'),
                    'cwd': item.get('cwd'), 'status': item.get('status'), 'requestedAt': item.get('requestedAt'),
                    'acceptedAt': item.get('acceptedAt'), 'executionObservedStartAt': item.get('executionObservedStartAt'),
                    'executionObservedEndAt': item.get('executionObservedEndAt'),
                    'executionObservedDurationMs': item.get('executionObservedDurationMs'),
                    'providerTurnTiming': item.get('providerTurnTiming'), 'autopilotAppliedAt': item.get('autopilotAppliedAt'),
                    'actionResults': item.get('actionResults'), 'error': item.get('error')} for item in sessions]
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
                for task in current['tasks']:
                    review, tests = task.get('review') or {}, task.get('tests') or {}
                    if (task.get('status') == 'review_completed' and review.get('verdict') == 'pass' and
                        tests.get('independent') is True and tests.get('status') == 'passed' and
                        task.get('worktreeBase') == current.get('baseCommit') and
                        review.get('digest') == tests.get('digest') and not task.get('harnessApprovalRecorded')):
                        result = request(api + f"/runs/{run_id}/tasks/{task['id']}/integrate", 'POST',
                                         {'confirmed': True}, token=token)
                        task['harnessApprovalRecorded'] = True
                        evidence.setdefault('approvals', []).append({'type': 'integration', 'taskId': task['id'],
                            'actor': 'E2E harness user confirmation via public API', 'at': utc_now(), 'commit': result.get('commit')})
                        evidence.setdefault('integrations', []).append({'taskId': task['id'], **result})
                        atomic_json(evidence_path, evidence)
                final = request(api + f'/runs/{run_id}', token=token)
                if all(task.get('status') == 'integrated' for task in final['tasks']):
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
                if any(task.get('status') in ('failed', 'unconfirmed', 'review_unconfirmed', 'mahoraga_required', 'rebase_conflict')
                       for task in final['tasks']):
                    raise E2EFailure('A required task is blocked; see preserved run state.')
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
    root = Path(args.output_root or Path('C:/CodexData/tmp')).resolve() / f'makora-autonomous-e2e-{stamp}-{uuid.uuid4().hex[:6]}'
    project = root / 'quiet-campus-project'
    workspace = root / 'makora-workspace'
    root.mkdir(parents=True, exist_ok=False)
    project.mkdir()
    evidence_path = root / 'evidence.json'
    server_stdout = root / 'makora-server.stdout.log'
    server_stderr = root / 'makora-server.stderr.log'
    port = args.port or free_port()
    origin = f'http://127.0.0.1:{port}'
    evidence = {'startedAt': utc_now(), 'status': 'running', 'modelRequired': MODEL,
                'appServerBinary': str(binary), 'appServerVersion': None, 'projectRoot': str(project),
                'makoraWorkspace': str(workspace), 'case': 'Тихий кампус', 'origin': origin,
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
            status = request(api + '/status', token=token)
            evidence['appServerVersion'] = status.get('appServerVersion')
            evidence['modelAvailable'] = status.get('modelAvailable')
            evidence['model'] = status.get('model')
            if status.get('model') != MODEL or status.get('modelAvailable') is not True:
                raise E2EFailure('Required gpt-6-luna is not available; no fallback model is permitted.')
            atomic_json(evidence_path, evidence)

            plan_session = request(api + '/plans', 'POST', {'projectRoot': str(project), 'brief': CASE,
                                      'context': 'Пустой Git-проект. README описывает только то, что приложение ещё не создано. '
                                                 'Стек, структуру, API пути, модули и имена файлов выбери самостоятельно. '
                                                 'Данные помещений должны быть локальными фикстурами. Формат каждого task: '
                                                 'dependsOn, contracts, mocks, allowedPaths — массивы строк (если существующих mock-файлов нет, mocks: []); '
                                                 'allowedPaths для КАЖДОЙ задачи, включая финальные проверки, должен содержать точные допустимые файлы. '
                                                 'не помещай пояснительный текст в mocks. title, goal, acceptance — строки. '
                                                 'Сначала задай задачу создания фикстур, если они нужны, и связывай с ней потребителей зависимостями.'}, token=token, timeout=210)
            evidence['planner'] = {'sessionId': plan_session.get('id'), 'threadId': plan_session.get('threadId'),
                                   'turnId': plan_session.get('turnId'), 'model': plan_session.get('model')}
            atomic_json(evidence_path, evidence)
            plan_deadline = time.monotonic() + args.plan_timeout
            while time.monotonic() < plan_deadline:
                planner = request(api + '/sessions/' + plan_session['id'], token=token, timeout=30)
                if planner.get('status') == 'completed' and planner.get('proposal'):
                    break
                if planner.get('status') in ('failed', 'unconfirmed') or planner.get('planError'):
                    raise E2EFailure('Mahoraga planner failed or needs clarification: ' + json.dumps(planner.get('error') or planner.get('planError'), ensure_ascii=False))
                evidence['plannerStatus'] = planner.get('status')
                atomic_json(evidence_path, evidence)
                time.sleep(args.poll_seconds)
            else:
                raise E2EFailure('Mahoraga did not return a plan before the configured timeout.')

            plan_shape = validate_plan(planner['proposal'])
            evidence['plannerStatus'] = planner.get('status')
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
                evidence['sessions'] = [{'id': item['id'], 'role': item.get('role'), 'taskId': item.get('taskId'),
                                         'threadId': item.get('threadId'), 'turnId': item.get('turnId'),
                                         'model': item.get('model'), 'cwd': item.get('cwd'), 'status': item.get('status'),
                                         'requestedAt': item.get('requestedAt'), 'acceptedAt': item.get('acceptedAt'),
                                         'executionObservedStartAt': item.get('executionObservedStartAt'),
                                         'executionObservedEndAt': item.get('executionObservedEndAt'),
                                         'executionObservedDurationMs': item.get('executionObservedDurationMs'),
                                         'providerTurnTiming': item.get('providerTurnTiming'),
                                         'autopilotAppliedAt': item.get('autopilotAppliedAt'),
                                         'actionResults': item.get('actionResults'), 'error': item.get('error')}
                                        for item in sessions]
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
                for task in current_run['tasks']:
                    review = task.get('review') or {}
                    tests = task.get('tests') or {}
                    if (task.get('status') == 'review_completed' and review.get('verdict') == 'pass' and
                            tests.get('independent') is True and tests.get('status') == 'passed' and
                            task.get('worktreeBase') == current_run.get('baseCommit') and
                            review.get('digest') == tests.get('digest') and
                            not task.get('harnessApprovalRecorded')):
                        integrated = request(api + f"/runs/{run['id']}/tasks/{task['id']}/integrate", 'POST', {'confirmed': True}, token=token)
                        task['harnessApprovalRecorded'] = True
                        evidence['approvals'].append({'type': 'integration', 'taskId': task['id'],
                                                      'actor': 'E2E harness user confirmation via public API',
                                                      'at': utc_now(), 'commit': integrated.get('commit')})
                        evidence['integrations'] = evidence.get('integrations', []) + [{'taskId': task['id'], **integrated}]
                        atomic_json(evidence_path, evidence)

                final = request(api + '/runs/' + run['id'], token=token)
                if all(task.get('status') == 'integrated' for task in final['tasks']):
                    evidence['finalRun'] = final
                    break
                auto = final.get('mahoragaAutopilot', {})
                if auto.get('status') in ('needs_human', 'failed', 'limit_reached'):
                    raise E2EFailure('Autopilot stopped for human attention: ' + str(auto.get('lastError')))
                if any(task.get('status') in ('failed', 'unconfirmed', 'review_unconfirmed', 'mahoraga_required', 'rebase_conflict')
                       for task in final['tasks']):
                    raise E2EFailure('A required task is blocked and needs diagnosis; see preserved evidence.')
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
            evidence['finalGitStatus'] = git_status
            evidence['finalCommit'] = git(project, 'rev-parse', 'HEAD')
            evidence['gitHistory'] = git(project, 'log', '--oneline', '--decorate', '--max-count=30').splitlines()
            evidence['finalFiles'] = git(project, 'ls-tree', '-r', '--name-only', 'HEAD').splitlines()
            evidence['finalWorkingTreeClean'] = not bool(git_status)
            if not evidence['finalWorkingTreeClean']:
                raise E2EFailure('Final temporary project worktree is not clean after integration.')
            evidence['apiSmoke'] = final_http_smoke(project, root, binary, evidence['plan'].get('e2e'))
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary', help='Codex App Server binary; defaults to CODEX_APP_SERVER_BINARY')
    parser.add_argument('--output-root', help='Temporary root directory; defaults to C:/CodexData/tmp')
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

"""Snapshot-bound independent tests and guarded integration for agent worktrees."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath


MAX_FILE_BYTES = 200_000
MAX_SUITE_BYTES = 2_000_000
ALLOWED_TEST_RUNNERS = {"python", "python3", "pytest", "node", "npm", "go", "cargo", "dotnet", "java", "mvn", "gradle"}
TEST_COUNT_PATTERNS = {
    "unittest": r"\bRan\s+(\d+)\s+tests?\b",
    "pytest": r"(?m)^(\d+)\s+passed\b",
    "node:test": r"(?m)^# pass\s+(\d+)\s*$",
    "jest": r"(?m)^Tests:\s+(\d+)\s+passed\b",
    "vitest": r"(?m)^\s*Tests\s+(\d+)\s+passed\b",
    "cargo test": r"test result: [^\r\n]*?(\d+) passed;",
    "dotnet test": r"(?:Passed:\s*(\d+)|Passed!\s*-\s*Failed:\s*\d+,\s*Passed:\s*(\d+))",
    "maven surefire": r"Tests run:\s*(\d+)",
    "gradle test": r"(\d+) tests? completed",
    "junit5": r"(\d+) tests? successful",
}


def _runner_name(value):
    return Path(value).name.lower().removesuffix('.exe')


def _executed_tests(framework, output, manifest):
    """Return a positive test count only when runner output proves tests executed."""
    custom_prefix = manifest.get('countPrefix')
    if custom_prefix is not None:
        if not isinstance(custom_prefix, str) or not custom_prefix or len(custom_prefix) > 120:
            return None
        values=[]
        for index in range(len(output)):
            if output.startswith(custom_prefix,index):
                match=re.match(r'\s*(\d+)',output[index+len(custom_prefix):])
                if match: values.append(int(match.group(1)))
        return sum(values) or None
    key=str(framework).strip().lower()
    if key=='go test':
        return len(re.findall(r'^--- PASS:',output,re.MULTILINE)) or None
    pattern=TEST_COUNT_PATTERNS.get(key)
    if not pattern:
        return None
    values=[]
    for match in re.finditer(pattern,output,re.MULTILINE|re.IGNORECASE):
        values.extend(int(group) for group in match.groups() if group is not None)
    return sum(values) or None


def snapshot(runtime, run_id, task_id, allowed_paths):
    from .runtime import AgentRuntimeError
    run = runtime._run(run_id)
    task = next(t for t in run['tasks'] if t['id'] == task_id)
    root = Path(task['worktree'])
    changed = runtime.run_diff(run_id, task_id)['changedFiles']
    if not changed:
        raise AgentRuntimeError('NO_CHANGES', 'Нет изменений для приёмки.', 409)
    allowed = set(allowed_paths)
    files = {}
    for name in changed:
        path = PurePosixPath(name)
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if (name not in allowed or path.is_absolute() or '..' in path.parts or
                any(p.startswith('.') for p in path.parts) or path.suffix.lower() in {'.env','.pem','.key','.pfx'}):
            raise AgentRuntimeError('UNAPPROVED_PATH', f'Не разрешён файл: {name}', 409)
        target = root.joinpath(*path.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise AgentRuntimeError('UNSAFE_PATH', name, 409)
        data = target.read_bytes() if target.exists() else None
        if data is not None and (len(data) > MAX_FILE_BYTES or b'\0' in data):
            raise AgentRuntimeError('UNSUPPORTED_FILE', name, 409)
        files[name] = data.decode('utf-8') if data is not None else None
    if not files:
        raise AgentRuntimeError('NO_CHANGES', 'Нет файлов для приёмки.',409)
    digest = _digest(files)
    return task, root, files, digest


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _suite(task):
    from .runtime import AgentRuntimeError
    source = task.get('testDesignDir')
    if not source:
        raise AgentRuntimeError('INDEPENDENT_TESTS_MISSING', 'У задачи нет набора независимых тестов Test Designer.', 409)
    try:
        folder = Path(source).resolve(strict=True)
    except OSError as exc:
        raise AgentRuntimeError('INDEPENDENT_TESTS_MISSING', 'Папка независимых тестов не найдена.', 409) from exc
    manifest_path = folder / 'test-manifest.json'
    design_path = folder / 'TEST_DESIGN.md'
    for artifact in (manifest_path, design_path):
        if (artifact.is_symlink() or not artifact.resolve().is_relative_to(folder) or
                not artifact.is_file() or artifact.stat().st_size > MAX_FILE_BYTES):
            raise AgentRuntimeError('INDEPENDENT_TESTS_MISSING', 'Манифест и описание тестов должны быть обычными локальными файлами допустимого размера.', 409)
    try:
        manifest = json.loads(manifest_path.read_text('utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError('TEST_MANIFEST_INVALID', 'Манифест независимых тестов содержит некорректный JSON.', 409) from exc
    if not isinstance(manifest, dict):
        raise AgentRuntimeError('TEST_MANIFEST_INVALID', 'Корнем манифеста должен быть JSON-объект.', 409)
    files = task.get('testDesignFiles') or manifest.get('files')
    if isinstance(files, list):
        files = [name for name in files if name not in ('TEST_DESIGN.md', 'test-manifest.json')]
    if not isinstance(files, list) or not files or not all(isinstance(name, str) for name in files):
        raise AgentRuntimeError('INDEPENDENT_TESTS_MISSING', 'Нет исполняемых независимых тестов Test Designer.', 409)
    data = {}
    total = 0
    for name in files:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ('tests', '.makora-tests'):
            raise AgentRuntimeError('TEST_SUITE_UNSAFE', f'Недопустимый путь теста {name}', 409)
        target = folder.joinpath(*path.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(folder) or not target.is_file():
            raise AgentRuntimeError('TEST_SUITE_MISSING', f'Тестовый файл отсутствует: {name}', 409)
        blob = target.read_bytes()
        total += len(blob)
        if len(blob) > MAX_FILE_BYTES or b'\0' in blob or total > MAX_SUITE_BYTES:
            raise AgentRuntimeError('TEST_SUITE_TOO_LARGE', 'Независимый тестовый набор превышает разрешённый размер.', 409)
        data[path.as_posix()] = blob.decode('utf-8')
    # Provide the exact immutable design context that Test Designer used to author the
    # executable suite. Bind it to the suite digest so review/retest cannot silently
    # drift when the task, contract, acceptance criteria, or runner manifest changes.
    for name, target in (('TEST_DESIGN.md', design_path), ('test-manifest.json', manifest_path),
                         ('TASK.md', folder / 'TASK.md'), ('CONTRACTS.md', folder / 'CONTRACTS.md'),
                         ('ACCEPTANCE.md', folder / 'ACCEPTANCE.md')):
        if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_FILE_BYTES:
            raise AgentRuntimeError('TEST_CONTEXT_MISSING', f'Файл контекста независимого набора отсутствует или небезопасен: {name}', 409)
        data[f'.makora-tests/context/{name}'] = target.read_text('utf-8')
    commands = manifest.get('commands')
    if not isinstance(commands, list) or not commands or len(commands) > 10:
        raise AgentRuntimeError('TEST_MANIFEST_INVALID', 'Манифест не содержит команд запуска.', 409)
    minimum_tests = manifest.get('minimumTests', 1)
    if not isinstance(minimum_tests, int) or isinstance(minimum_tests, bool) or not 1 <= minimum_tests <= 100_000:
        raise AgentRuntimeError('TEST_MANIFEST_INVALID', 'minimumTests должен быть целым числом от 1 до 100000.', 409)
    for command in commands:
        if (not isinstance(command, list) or len(command) < 2 or len(command) > 80 or
                not all(isinstance(arg, str) and arg and '\0' not in arg for arg in command) or
                '.makora-tests' not in ' '.join(command)):
            raise AgentRuntimeError('TEST_MANIFEST_INVALID', 'Команда должна быть массивом argv без shell и запускать .makora-tests.', 409)
        if _runner_name(command[0]) not in ALLOWED_TEST_RUNNERS:
            raise AgentRuntimeError('TEST_RUNNER_DENIED', f'Запуск {command[0]} не разрешён.', 409)
    return folder, manifest, data, _digest(data)


def _codex_binary():
    from .runtime import AgentRuntimeError
    binary = os.environ.get('CODEX_APP_SERVER_BINARY')
    if not binary or not Path(binary).is_file():
        raise AgentRuntimeError('SANDBOX_REQUIRED', 'Настрой CODEX_APP_SERVER_BINARY: независимые тесты нельзя запускать на хосте.', 409)
    return binary


def _materialize_project(runtime, root, files, suite_data, destination):
    """Build an isolated source snapshot from committed base plus exactly approved changes."""
    from .runtime import AgentRuntimeError
    archive = subprocess.run(['git', '-C', str(root), 'archive', '--format=tar', 'HEAD'], capture_output=True, timeout=30)
    if archive.returncode:
        raise AgentRuntimeError('TEST_SNAPSHOT_FAILED', archive.stderr.decode('utf-8', 'replace')[-2000:], 409)
    import tarfile
    import io
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode='r:') as tar:
            for member in tar.getmembers():
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination.resolve()) or not (member.isfile() or member.isdir()):
                    raise AgentRuntimeError('TEST_SNAPSHOT_UNSAFE', 'Архив проекта содержит небезопасный путь или тип файла.', 409)
            tar.extractall(destination, filter='data')
    except (tarfile.TarError, OSError) as exc:
        raise AgentRuntimeError('TEST_SNAPSHOT_FAILED', str(exc), 409) from exc
    for name, content in files.items():
        target = destination.joinpath(*PurePosixPath(name).parts)
        if content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
    suite_root = destination / '.makora-tests'
    suite_root.mkdir()
    for name, content in suite_data.items():
        relative = PurePosixPath(name)
        target = suite_root.joinpath(*relative.parts[1:])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')


def _sandbox_parent(runtime):
    """Keep sandbox snapshots under the controller workspace unless explicitly configured."""
    configured = os.environ.get('MAKORA_TEST_SANDBOX_ROOT')
    parent = Path(configured).expanduser() if configured else runtime.workspace / 'test-sandboxes'
    parent.mkdir(parents=True, exist_ok=True)
    return parent.resolve()


def _argv(command):
    executable = _runner_name(command[0])
    if executable in ('python', 'python3'):
        return [sys.executable if os.name == 'nt' else shutil.which(command[0]) or sys.executable, *command[1:]]
    resolved = shutil.which(command[0])
    if not resolved:
        from .runtime import AgentRuntimeError
        raise AgentRuntimeError('TEST_RUNNER_MISSING', f'Исполняемый файл {command[0]} не найден.', 409)
    return [resolved, *command[1:]]


def test_task(runtime, run_id, task_id, allowed_paths):
    from .runtime import AgentRuntimeError, _now
    with runtime._lock:
        task, root, files, digest = snapshot(runtime, run_id, task_id, allowed_paths)
        run = runtime._run(run_id)
        if runtime._run_git(root, 'rev-parse', 'HEAD') != task.get('worktreeBase', run['baseCommit']):
            raise AgentRuntimeError('TASK_BASE_OUTDATED', 'База задачи устарела. Обнови ветку и повтори независимые тесты и ревью.', 409)
        if task.get('worktreeBase', run['baseCommit']) != run['baseCommit']:
            raise AgentRuntimeError('TASK_BASE_OUTDATED', 'Задача основана на старой версии проекта. Обнови базу и повтори независимые тесты.', 409)
        if task['status'] not in ('review_pending','review_completed','tests_failed','tests_passed','changes_requested','review_unconfirmed'):
            raise AgentRuntimeError('TEST_NOT_READY', 'Builder ещё не завершён.', 409)
        spec_dir, manifest, suite_data, suite_digest = _suite(task)
        task.pop('review', None)
        task.pop('reviewDigest', None)
        task.pop('reviewSuiteDigest', None)
        binary = _codex_binary()
        outputs = []
        with tempfile.TemporaryDirectory(prefix='makora-independent-tests-', dir=_sandbox_parent(runtime)) as temporary:
            sandbox_root = Path(temporary).resolve()
            _materialize_project(runtime, root, files, suite_data, sandbox_root)
            for raw_command in manifest['commands']:
                argv = _argv(raw_command)
                command = [binary, '-c', 'windows.sandbox=elevated', 'sandbox', '-C', str(sandbox_root), '--permission-profile', ':workspace', '--', *argv]
                try:
                    result = subprocess.run(command, cwd=sandbox_root, capture_output=True, text=True, timeout=180)
                    output = (result.stdout + result.stderr)[-16000:]
                    executed = _executed_tests(manifest['framework'], output, manifest)
                    minimum = manifest.get('minimumTests', 1)
                    passed = result.returncode == 0 and executed is not None and executed >= minimum
                    outputs.append({'command': argv, 'exitCode': result.returncode, 'status': 'passed' if passed else 'failed',
                                    'executedTests': executed or 0, 'minimumTests': minimum,
                                    'verificationError': None if passed else ('Тесты не подтверждены выводом runner или их меньше minimumTests.' if result.returncode == 0 else None),
                                    'output': output})
                except subprocess.TimeoutExpired as exc:
                    outputs.append({'command': argv, 'status': 'failed', 'output': str(exc)})
                    break
        passed = bool(outputs) and all(item['status'] == 'passed' for item in outputs)
        evidence = {'status':'passed' if passed else 'failed','independent':True,'framework':manifest['framework'],
                    'commands':outputs,'digest':digest,'suiteDigest':suite_digest,'at':_now()}
        task['allowedPaths'] = list(allowed_paths)
        task['tests'] = evidence
        task['status'] = 'tests_passed' if passed else 'tests_failed'
        runtime._save()
        return evidence


def integrate(runtime, run_id, task_id, confirmed):
    from .runtime import AgentRuntimeError, _now
    with runtime._lock:
        run = runtime._run(run_id)
        task = next(t for t in run['tasks'] if t['id']==task_id)
        task, root, files, digest = snapshot(runtime,run_id,task_id,task.get('allowedPaths',[]))
        tests = task.get('tests',{})
        review = task.get('review',{})
        if (confirmed is not True or tests.get('status')!='passed' or tests.get('independent') is not True or
                review.get('verdict')!='pass' or review.get('digest')!=digest):
            raise AgentRuntimeError('INTEGRATION_GATE', 'Нужны подтверждение, независимый тест и Reviewer для текущих файлов.',409)
        _, _, _, suite_digest = _suite(task)
        if (confirmed is not True or tests.get('status')!='passed' or tests.get('independent') is not True or
                tests.get('digest')!=digest or tests.get('suiteDigest')!=suite_digest or review.get('verdict')!='pass' or
                review.get('digest')!=digest or review.get('suiteDigest')!=suite_digest):
            raise AgentRuntimeError('INTEGRATION_GATE', 'Нужны подтверждение, независимый тест и Reviewer для текущих файлов и текущей версии тестов.',409)
        project = Path(run['projectRoot'])
        if runtime._run_git(project,'status','--porcelain') or runtime._run_git(project,'rev-parse','HEAD') != run['baseCommit']:
            raise AgentRuntimeError('PROJECT_CHANGED','Исходная ветка изменилась; требуется повторная приёмка.',409)
        if runtime._run_git(root,'rev-parse','HEAD') != task.get('worktreeBase',run['baseCommit']):
            raise AgentRuntimeError('TASK_BASE_OUTDATED','База задачи устарела. Обнови ветку и повтори приёмку.',409)
        if task.get('worktreeBase') != run['baseCommit']:
            raise AgentRuntimeError('TASK_BASE_OUTDATED','Сначала обнови задачу на текущую базу и повтори тесты и ревью.',409)
        runtime._run_git(root,'add','--',*files.keys())
        runtime._run_git(root,'commit','-m',f'Makora: integrate {task_id}')
        revision = runtime._run_git(root,'rev-parse','HEAD')
        runtime._run_git(project,'merge','--ff-only',revision)
        task.update(status='integrated',integration='integrated',integratedCommit=revision,integratedAt=_now())
        run['baseCommit']=revision
        runtime._save()
        return {'status':'integrated','commit':revision,'unlocked':[t['id'] for t in run['tasks'] if task_id in t['dependsOn'] and all(next(x for x in run['tasks'] if x['id']==d)['status']=='integrated' for d in t['dependsOn'])]}

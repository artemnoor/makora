"""Evidence-bound acceptance of explicit task files; no host execution fallback."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


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
        if name not in allowed or path.is_absolute() or '..' in path.parts or any(p.startswith('.') for p in path.parts) or path.suffix.lower() in {'.env','.pem','.key','.pfx'}:
            raise AgentRuntimeError('UNAPPROVED_PATH', f'Не разрешён файл: {name}', 409)
        target = root.joinpath(*path.parts)
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise AgentRuntimeError('UNSAFE_PATH', name, 409)
        data = target.read_bytes() if target.exists() else None
        if data is not None and (len(data) > 200000 or b'\0' in data):
            raise AgentRuntimeError('UNSUPPORTED_FILE', name, 409)
        files[name] = data.decode('utf-8') if data is not None else None
    if not files:
        raise AgentRuntimeError('NO_CHANGES', 'Нет файлов для приёмки.',409)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return task, root, files, digest


def test_task(runtime, run_id, task_id, allowed_paths):
    from .runtime import AgentRuntimeError, _now
    with runtime._lock:
        task, root, files, digest = snapshot(runtime, run_id, task_id, allowed_paths)
        if task['status'] not in ('review_pending','review_completed','tests_failed','tests_passed'):
            raise AgentRuntimeError('TEST_NOT_READY', 'Builder ещё не завершён.', 409)
        binary = os.environ.get('CODEX_APP_SERVER_BINARY')
        if not binary or not Path(binary).is_file():
            raise AgentRuntimeError('SANDBOX_REQUIRED', 'Настрой CODEX_APP_SERVER_BINARY для изолированного запуска тестов.', 409)
        command = [binary, '-c', 'windows.sandbox=elevated', 'sandbox', '-C', str(root), '--permission-profile', ':workspace', '--', sys.executable, '-B', '-m', 'unittest', 'discover', '-v']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            output = result.stdout + result.stderr
            passed = result.returncode == 0 and 'Ran ' in output and 'Ran 0 tests' not in output and '\nOK' in output
            evidence = {'status':'passed' if passed else 'failed','exitCode':result.returncode,'output':output[-16000:],'digest':digest,'at':_now(),'command':command}
        except subprocess.TimeoutExpired:
            evidence = {'status':'failed','output':'Sandbox test timeout','digest':digest,'at':_now()}
        task['allowedPaths'] = allowed_paths
        task['tests'] = evidence
        task['status'] = 'tests_passed' if evidence['status']=='passed' else 'tests_failed'
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
        if confirmed is not True or tests.get('status')!='passed' or tests.get('digest')!=digest or review.get('verdict')!='pass' or review.get('digest')!=digest:
            raise AgentRuntimeError('INTEGRATION_GATE', 'Нужны подтверждение, актуальные тесты и Reviewer для этой версии файлов.',409)
        project = Path(run['projectRoot'])
        if runtime._run_git(project,'status','--porcelain') or runtime._run_git(project,'rev-parse','HEAD') != run['baseCommit']:
            raise AgentRuntimeError('PROJECT_CHANGED','Исходная ветка изменилась; требуется повторная приёмка.',409)
        runtime._run_git(root,'add','--',*files.keys())
        runtime._run_git(root,'commit','-m',f'Makora: integrate {task_id}')
        revision = runtime._run_git(root,'rev-parse','HEAD')
        runtime._run_git(project,'merge','--ff-only',revision)
        task.update(status='integrated',integration='integrated',integratedCommit=revision,integratedAt=_now())
        run['baseCommit']=revision
        runtime._save()
        return {'status':'integrated','commit':revision,'unlocked':[t['id'] for t in run['tasks'] if task_id in t['dependsOn'] and all(next(x for x in run['tasks'] if x['id']==d)['status']=='integrated' for d in t['dependsOn'])]}

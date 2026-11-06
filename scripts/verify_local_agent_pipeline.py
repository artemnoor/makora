"""Opt-in real-model verification in a disposable repository, never the user's app."""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from makora_core.agents.runtime import AgentRuntime, configure_codex_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real-model', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    configure_codex_binary()
    previous = json.loads(args.output.read_text('utf-8')) if args.resume else None
    home = Path(previous['project']).parent if previous else Path(tempfile.mkdtemp(prefix='makora-pipeline-')).resolve()
    project = home / 'app'
    project.mkdir(exist_ok=True)
    (project / 'README.md').write_text('# Disposable greeting function verification\n', encoding='utf-8')
    (project / 'SPEC.md').write_text('greeting.py: greet(name: str) -> str. Strip whitespace, return Hello, <name>!. Empty names raise ValueError, non-string names raise TypeError. No side effects.\n', encoding='utf-8')
    def git(*argv):
        return subprocess.run(['git', '-C', str(project), *argv], capture_output=True, text=True, check=True).stdout
    if not previous:
        git('init', '--initial-branch=main')
        git('config', 'user.name', 'Makora Verification')
        git('config', 'user.email', 'verify@localhost')
        git('add', '.')
        git('commit', '-m', 'Disposable verification fixture')
    runtime = AgentRuntime(home / 'state', Path(__file__).resolve().parents[1] / 'integrations/codex-desktop-local-api', [project])
    report = previous or {'project': str(project), 'checks': []}
    def record(phase, **details):
        report['checks'].append({'phase': phase, **details})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report['checks'][-1], ensure_ascii=False), flush=True)
    def wait(session):
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            result = runtime.refresh_session(session['id'])
            if result['status'] in ('completed', 'failed', 'unconfirmed'):
                record(session['role'], status=result['status'], threadId=result['threadId'],
                       error=result.get('error'), planError=result.get('planError'))
                if result['status'] != 'completed':
                    raise RuntimeError(f"{session['role']} {result['status']}")
                return result
            time.sleep(2)
        raise TimeoutError(session['role'])
    try:
        if previous:
            run = list(runtime.state['runs'].values())[-1]
            task = run['tasks'][0]
        else:
            planner = runtime.start_mahoraga_planning({'projectRoot': str(project), 'brief':
            'Диагностический проект. Ровно одна задача TASK01 и ровно один разрешённый файл greeting.py. '
            'Реализовать функцию greet(name): принимает строку, удаляет пробелы по краям, возвращает Hello, <name>! '
            'Пустая строка или строка из пробелов вызывает ValueError. Не строка вызывает TypeError. '
            'Без CLI, сети и зависимостей. Независимый Test Designer должен проверить обычное имя, пробелы, '
            'пустое имя и неверный тип через Python unittest стандартной библиотеки. '
            'Не добавляй отдельные задачи документации, тестирования или интеграции. contracts=["SPEC.md"], mocks=[].',
            'artifactPaths': ['SPEC.md']})
            planner = wait(planner)
            if not planner.get('proposal'):
                raise RuntimeError(str(planner.get('planError')))
            run = runtime.approve_mahoraga_plan(planner['id'])
            task = run['tasks'][0]
            record('approved_dag', status='passed', runId=run['id'], tasks=len(run['tasks']))
            runtime.create_task_worktree(run['id'], task['id'])
            wait(runtime.launch_agent(run['id'], task['id'], 'test_designer'))
            wait(runtime.launch_agent(run['id'], task['id'], 'builder'))
        tests = runtime.test_task(run['id'], task['id'], task['allowedPaths'])
        record('independent_tests', **tests)
        if tests.get('status') != 'passed':
            raise RuntimeError('Independent tests failed')
        wait(runtime.launch_agent(run['id'], task['id'], 'reviewer'))
        integrated = runtime.integrate_task(run['id'], task['id'], confirmed=True)
        record('integration', status='passed', result=integrated)
        result = subprocess.run([sys.executable, '-c', "from greeting import greet; assert greet(' Ada ')== 'Hello, Ada!'; print('VERIFIED')"],
                                cwd=project, capture_output=True, text=True, check=True)
        record('final_smoke', status='passed', output=result.stdout.strip())
        report['status'] = 'passed'
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        record('failure', status='failed', message=str(error))
        raise
    finally:
        runtime.close()


if __name__ == '__main__':
    main()

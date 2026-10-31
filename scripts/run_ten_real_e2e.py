"""Execute ten independent GPT-6 Luna E2E cases sequentially and preserve every outcome."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from real_autonomous_e2e import (SCENARIOS, atomic_json, confirmed_builder_pairs,
                                 observed_builder_pairs, utc_now)


def _case_metrics(report: dict) -> dict:
    """Read persisted controller state so blocked runs still report real progress."""
    def stamp(value):
        try:
            return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except (TypeError, ValueError, AttributeError):
            return None

    workspace = report.get('makoraWorkspace')
    run_id = report.get('runId')
    plan = report.get('plan') or {}
    planned_count = (plan.get('validation') or {}).get('taskCount') or len(plan.get('tasks') or [])
    if not workspace:
        return {'taskCount': planned_count, 'integrations': 0, 'repairs': 0,
                'overlappingBuilderPairs': 0, 'confirmedParallelBuilderPairs': 0,
                'parallelOverlapSeconds': 0.0, 'parallelBuilderEvidence': [], 'threads': []}
    try:
        state = json.loads((Path(workspace) / 'agents' / 'state.json').read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        return {'taskCount': planned_count, 'integrations': 0, 'repairs': 0,
                'overlappingBuilderPairs': 0, 'confirmedParallelBuilderPairs': 0,
                'parallelOverlapSeconds': 0.0, 'parallelBuilderEvidence': [], 'threads': []}
    if not run_id:
        planner_id = (report.get('planner') or {}).get('sessionId')
        planner = (state.get('sessions') or {}).get(planner_id, {})
        proposal = planner.get('proposal') or {}
        tasks = proposal.get('tasks') or []
        validation = planner.get('planValidation') or {}
        return {'taskCount': planned_count or validation.get('taskCount') or len(tasks),
                'integrations': 0, 'repairs': 0,
                'overlappingBuilderPairs': 0, 'confirmedParallelBuilderPairs': 0,
                'parallelOverlapSeconds': 0.0, 'parallelBuilderEvidence': [],
                'threads': [{'role': planner.get('role'), 'taskId': planner.get('taskId'),
                             'threadId': planner.get('threadId'), 'turnId': planner.get('turnId'),
                             'model': planner.get('model'), 'status': planner.get('status'),
                             'startedAt': planner.get('executionObservedStartAt'),
                             'endedAt': planner.get('executionObservedEndAt')}]
                        if planner.get('threadId') else []}
    try:
        run = state['runs'][run_id]
    except (KeyError, TypeError):
        return {'taskCount': planned_count, 'integrations': 0, 'repairs': 0,
                'overlappingBuilderPairs': 0, 'confirmedParallelBuilderPairs': 0,
                'parallelOverlapSeconds': 0.0, 'parallelBuilderEvidence': [], 'threads': []}
    tasks = run.get('tasks') or []
    sessions = [item for item in state.get('sessions', {}).values() if item.get('runId') == run_id]
    evidence_sessions = report.get('sessions') or sessions
    confirmed_pairs = confirmed_builder_pairs(evidence_sessions, report.get('builderSnapshots') or [])
    observed_pairs = observed_builder_pairs(evidence_sessions, report.get('builderSnapshots') or [],
                                            report.get('parallelObservations') or [])
    # Do not report a pair as confirmed merely because two status timestamps
    # overlap: both distinct worktrees must also have recorded real file changes.
    overlap_seconds = round(sum(item['overlapSeconds'] for item in confirmed_pairs), 3)
    return {
        'taskCount': len(tasks),
        'integrations': sum(task.get('status') == 'integrated' for task in tasks),
        'repairs': sum(int(task.get('repairAttempts', 0) or 0) for task in tasks),
        'overlappingBuilderPairs': len(confirmed_pairs),
        'confirmedParallelBuilderPairs': len(confirmed_pairs),
        'parallelBuilderEvidence': confirmed_pairs,
        'parallelOverlapSeconds': overlap_seconds,
        'observedParallelBuilderEvidence': observed_pairs,
        'observedParallelLowerBoundSeconds': round(sum(item['observedLowerBoundSeconds'] for item in observed_pairs), 3),
        'durationSeconds': max(0, int((stamp(report.get('completedAt')) or 0) -
                                      (stamp(report.get('startedAt')) or 0))),
        'threads': [{'role': session.get('role'), 'taskId': session.get('taskId'),
                     'threadId': session.get('threadId'), 'turnId': session.get('turnId'),
                     'turnHistory': session.get('turnHistory', []),
                     'model': session.get('model'), 'status': session.get('status'),
                     'startedAt': session.get('executionObservedStartAt'),
                     'endedAt': session.get('executionObservedEndAt')}
                    for session in sessions if session.get('threadId')],
        'autopilotStatus': (run.get('mahoragaAutopilot') or {}).get('status'),
        'controllerDefects': sum(task.get('status') in ('failed', 'rebase_conflict', 'mahoraga_required') for task in tasks),
        'autopilotRejections': len((run.get('mahoragaAutopilot') or {}).get('pendingRejections') or []),
    }


def _status(report: dict, exit_code: int) -> str:
    final_run = report.get('finalRun') or {}
    final_status = final_run.get('mahoragaAutopilot', {}).get('status')
    if report.get('status') == 'pass' and final_status == 'completed' and exit_code == 0:
        return 'PASS'
    if report.get('status') == 'pass' and exit_code != 0:
        return 'FAIL'
    message = str((report.get('failure') or {}).get('message', ''))
    # Provider-level systemError means App Server failed the turn; the
    # application workflow did not get a model result to evaluate.
    if 'systemError' in message or any(
            'systemError' in json.dumps(session.get('error'), ensure_ascii=False)
            for session in report.get('sessions', []) if session.get('error')):
        return 'BLOCKED'
    if any(marker in message.lower() for marker in (
            'required gpt-6-luna is not available', 'model_unavailable',
            'required model is unavailable', 'model catalog is unavailable')):
        return 'BLOCKED'
    if any(marker in message for marker in (
            'Codex запросил действие вне разрешённой роли, turn или worktree',
            'Ожидается подтверждение человека', 'Autopilot stopped for human attention:',
            'Махорага задала вопрос человеку', 'Требуется решение по задачам')):
        return 'BLOCKED'
    if any(session.get('status') == 'unconfirmed' for session in report.get('sessions', [])
           if isinstance(session, dict)):
        return 'BLOCKED'
    task_statuses = report.get('taskStatuses') or []
    if any(item.get('status') in ('rebase_conflict', 'blocked_for_human', 'unconfirmed')
           for item in task_statuses if isinstance(item, dict)):
        return 'BLOCKED'
    if any(item.get('status') == 'mahoraga_required' for item in task_statuses if isinstance(item, dict)):
        escalated = {session.get('taskId') for session in report.get('sessions', [])
                     if isinstance(session, dict) and session.get('role') == 'mahoraga'}
        if any(item.get('id') not in escalated for item in task_statuses
               if isinstance(item, dict) and item.get('status') == 'mahoraga_required'):
            return 'FAIL'
        return 'BLOCKED'
    if report.get('status') == 'fail':
        return 'FAIL'
    return 'BLOCKED'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-binary', required=True)
    parser.add_argument('--output-root', default='C:/m')
    parser.add_argument('--run-timeout', type=int, default=7200)
    parser.add_argument('--plan-timeout', type=int, default=900)
    parser.add_argument('--scenarios', nargs='*', choices=sorted(SCENARIOS), default=sorted(SCENARIOS))
    args = parser.parse_args()
    batch = Path(args.output_root).resolve() / f'batch-{dt.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
    batch.mkdir(parents=True, exist_ok=False)
    manifest_path = batch / 'batch.json'
    manifest = {'startedAt': utc_now(), 'modelRequired': 'gpt-6-luna', 'status': 'running', 'scenarios': []}
    atomic_json(manifest_path, manifest)
    for scenario_id in args.scenarios:
        item = {'scenarioId': scenario_id, 'case': SCENARIOS[scenario_id][0], 'startedAt': utc_now(), 'status': 'running'}
        manifest['scenarios'].append(item)
        atomic_json(manifest_path, manifest)
        stdout_path, stderr_path = batch / f'{scenario_id}.stdout.log', batch / f'{scenario_id}.stderr.log'
        command = [sys.executable, str(Path(__file__).with_name('real_autonomous_e2e.py')),
                   '--scenario', scenario_id, '--codex-binary', args.codex_binary,
                   '--output-root', str(batch / scenario_id), '--run-timeout', str(args.run_timeout),
                   '--plan-timeout', str(args.plan_timeout)]
        env = os.environ.copy()
        for name in ('GITHUB_TOKEN', 'GH_TOKEN'):
            env.pop(name, None)
        env['CODEX_APP_SERVER_BINARY'] = args.codex_binary
        try:
            with stdout_path.open('w', encoding='utf-8') as stdout, stderr_path.open('w', encoding='utf-8') as stderr:
                result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                        stdout=stdout, stderr=stderr, env=env, check=False)
            item['exitCode'] = result.returncode
            item['status'] = 'completed' if result.returncode == 0 else 'blocked_or_failed'
            # Find the per-case machine report created by the child runner.
            files = sorted((batch / scenario_id).glob('makora-e2e-*/evidence.json'))
            if files:
                report = json.loads(files[-1].read_text(encoding='utf-8'))
                metrics = _case_metrics(report)
                item.update({'evidence': str(files[-1]), 'runStatus': report.get('status'),
                             'runId': report.get('runId'), **metrics,
                             'model': report.get('model'), 'completedAt': report.get('completedAt'),
                             'failure': report.get('failure')})
                item['status'] = _status(report, result.returncode)
            else:
                item.update({'status': 'BLOCKED', 'failure': 'Runner produced no evidence.json; see captured logs.'})
        except Exception as exc:
            item.update({'status': 'BLOCKED', 'failure': f'{type(exc).__name__}: {exc}'})
        item['endedAt'] = utc_now()
        atomic_json(manifest_path, manifest)
    manifest['endedAt'] = utc_now()
    manifest['status'] = 'completed'
    manifest['summary'] = {status: sum(item.get('status') == status for item in manifest['scenarios'])
                           for status in ('PASS', 'FAIL', 'BLOCKED')}
    atomic_json(manifest_path, manifest)
    print(json.dumps({'manifest': str(manifest_path), 'summary': manifest['summary']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

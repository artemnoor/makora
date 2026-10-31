"""Create a redacted, machine-readable index of preserved real E2E evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from real_autonomous_e2e import observed_builder_pairs


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _classification(report: dict, run: dict | None = None,
                    sessions: list[dict] | None = None) -> tuple[str, str]:
    failure = report.get('failure') or {}
    message = str(failure.get('message') or '')
    lower = message.lower()
    final_run = report.get('finalRun') or {}
    if (report.get('status') == 'pass' and
            (final_run.get('mahoragaAutopilot') or {}).get('status') == 'completed'):
        return 'PASS', 'autopilot_completed'
    if any(token in lower for token in (
            'махорага задала вопрос человеку', 'требуется решение по задачам',
            'autopilot stopped for human attention')):
        return 'BLOCKED', 'safe_stop_requires_human_decision'
    if any(token in lower for token in (
            'systemerror', 'вне разрешённой роли', 'out of allowed role',
            'sandbox_required', 'requires windows', 'requires authentication',
            'token_revoked', 'codex approval', 'required gpt-6-luna is not available',
            'model_unavailable', 'required model is unavailable')):
        return 'BLOCKED', 'external_codex_or_sandbox_block'
    tasks = report.get('taskStatuses') or (run or {}).get('tasks') or []
    sessions = sessions or report.get('sessions') or []
    if any(isinstance(session, dict) and session.get('status') == 'unconfirmed' for session in sessions):
        return 'BLOCKED', 'safe_stop_requires_human_or_delivery_confirmation'
    if any(isinstance(task, dict) and task.get('status') in
           ('rebase_conflict', 'blocked_for_human', 'unconfirmed') for task in tasks):
        return 'BLOCKED', 'safe_stop_requires_human_or_delivery_confirmation'
    if any(isinstance(task, dict) and task.get('status') == 'mahoraga_required' for task in tasks):
        escalated = any(isinstance(session, dict) and session.get('role') == 'mahoraga' and
                        session.get('taskId') in {task.get('id') for task in tasks
                                                  if task.get('status') == 'mahoraga_required'}
                        for session in sessions)
        if escalated:
            return 'BLOCKED', 'mahoraga_diagnosis_requires_human'
        return 'FAIL', 'mahoraga_escalation_not_processed'
    if report.get('status') == 'pass':
        return 'FAIL', 'runner_did_not_confirm_completed_autopilot'
    if not failure:
        return 'BLOCKED', 'evidence_incomplete'
    return 'FAIL', 'makora_or_plan_acceptance_failure'


def _smoke_summary(value):
    if isinstance(value, dict) and isinstance(value.get('checks'), list):
        if value.get('mode') == 'cli':
            return {'mode': 'cli', 'checks': [
                {'name': item.get('name'), 'exitCode': item.get('exitCode'),
                 'expectedExitCode': item.get('expectedExitCode'), 'passed': item.get('passed')}
                for item in value['checks'] if isinstance(item, dict)]}
        return {'mode': 'http', 'checks': [
            {'case': item.get('case'), 'status': item.get('status')}
            for item in value['checks'] if isinstance(item, dict)]}
    if isinstance(value, dict) and value.get('status') == 'covered_by_independent_project_tests':
        return {'mode': 'project_tests_only', 'status': value.get('status')}
    return None


def _builder_intervals(session: dict) -> list[tuple[float, float]]:
    intervals = []
    for turn in session.get('turnHistory') or []:
        if not isinstance(turn, dict):
            continue
        start, end = _stamp(turn.get('executionObservedStartAt')), _stamp(turn.get('executionObservedEndAt'))
        if start is not None and end is not None and end > start:
            intervals.append((start, end))
    if intervals:
        return intervals
    start, end = _stamp(session.get('executionObservedStartAt')), _stamp(session.get('executionObservedEndAt'))
    return [(start, end)] if start is not None and end is not None and end > start else []


def _confirmed_parallel_pairs(sessions: list[dict], snapshots: list[dict]) -> list[dict]:
    """Require overlapping turns, distinct worktrees, and observed writes by both builders."""
    changed: dict[str, set[str]] = {}
    worktrees: dict[str, str] = {}
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not snapshot.get('taskId'):
            continue
        task_id = str(snapshot['taskId'])
        paths = snapshot.get('changedFiles') or []
        if isinstance(paths, list) and paths:
            changed.setdefault(task_id, set()).update(str(path) for path in paths if isinstance(path, str))
        if snapshot.get('worktree'):
            worktrees[task_id] = os.path.normcase(os.path.normpath(str(snapshot['worktree'])))

    builders = [item for item in sessions if isinstance(item, dict) and item.get('role') == 'builder'
                and item.get('taskId') and item.get('threadId')]
    result = []
    for index, first in enumerate(builders):
        for second in builders[index + 1:]:
            task_a, task_b = str(first['taskId']), str(second['taskId'])
            if task_a == task_b or first['threadId'] == second['threadId']:
                continue
            tree_a = worktrees.get(task_a) or first.get('cwd')
            tree_b = worktrees.get(task_b) or second.get('cwd')
            if not tree_a or not tree_b or os.path.normcase(os.path.normpath(str(tree_a))) == \
                    os.path.normcase(os.path.normpath(str(tree_b))):
                continue
            if not changed.get(task_a) or not changed.get(task_b):
                continue
            overlaps = [min(end_a, end_b) - max(start_a, start_b)
                        for start_a, end_a in _builder_intervals(first)
                        for start_b, end_b in _builder_intervals(second)
                        if min(end_a, end_b) > max(start_a, start_b)]
            if overlaps:
                result.append({'firstTaskId': task_a, 'secondTaskId': task_b,
                               'firstThreadId': first['threadId'], 'secondThreadId': second['threadId'],
                               'overlapSeconds': round(max(overlaps), 3),
                               'firstChangedFiles': sorted(changed[task_a]),
                               'secondChangedFiles': sorted(changed[task_b])})
    return result


def _state_evidence(report: dict) -> tuple[dict, dict, list[dict]]:
    workspace = report.get('makoraWorkspace')
    if not workspace:
        return {}, {}, []
    state = _load(Path(workspace) / 'agents' / 'state.json')
    run_id = report.get('runId')
    run = (state.get('runs') or {}).get(run_id, {}) if run_id else {}
    planner_id = (report.get('planner') or {}).get('sessionId')
    planner = (state.get('sessions') or {}).get(planner_id, {}) if planner_id else {}
    if not run and planner:
        run = {}
    return state, run, list((state.get('sessions') or {}).values())


def summarize_evidence(path: Path, evidence_root: Path) -> dict:
    report = _load(path)
    state, run, state_sessions = _state_evidence(report)
    planner_id = (report.get('planner') or {}).get('sessionId')
    planner = (state.get('sessions') or {}).get(planner_id, {}) if planner_id else {}
    plan = report.get('plan') or {}
    plan_tasks = plan.get('tasks') or (planner.get('proposal') or {}).get('tasks') or []
    tasks = run.get('tasks') or []
    if not plan_tasks and tasks:
        plan_tasks = tasks
    sessions = report.get('sessions') or [item for item in state_sessions
                                          if not report.get('runId') or item.get('runId') == report.get('runId')]
    snapshots = report.get('builderSnapshots') or []
    overlap_pairs = _confirmed_parallel_pairs(sessions, snapshots)
    observed_pairs = observed_builder_pairs(sessions, snapshots, report.get('parallelObservations') or [])
    status, category = _classification(report, run, sessions)
    final_tasks = tasks or report.get('taskStatuses') or []
    integrated = [task for task in final_tasks if task.get('status') == 'integrated']
    sessions_out = []
    for item in sessions:
        if not item.get('threadId'):
            continue
        sessions_out.append({key: item.get(key) for key in (
            'role', 'taskId', 'threadId', 'turnId', 'model', 'status',
            'turnHistory', 'executionObservedStartAt', 'executionObservedEndAt', 'executionObservedDurationMs')})
    try:
        evidence_ref = path.resolve().relative_to(evidence_root.resolve()).as_posix()
    except ValueError:
        evidence_ref = path.resolve().as_posix()
    return {
        'scenarioId': report.get('scenarioId') or path.parent.parent.name,
        'caseBrief': report.get('caseBrief'),
        'runId': report.get('runId'), 'status': status, 'classification': category,
        'model': report.get('model'), 'appServerVersion': report.get('appServerVersion'),
        'startedAt': report.get('startedAt'), 'completedAt': report.get('completedAt'),
        'durationSeconds': (max(0, int(_stamp(report.get('completedAt')) - _stamp(report.get('startedAt'))))
                            if _stamp(report.get('completedAt')) is not None and
                            _stamp(report.get('startedAt')) is not None else None),
        'taskCount': len(plan_tasks),
        'planSummary': plan.get('summary') or (planner.get('proposal') or {}).get('summary'),
        'planRisks': plan.get('risks') or (planner.get('proposal') or {}).get('risks') or [],
        'planOpenQuestions': plan.get('openQuestions') or (planner.get('proposal') or {}).get('openQuestions') or [],
        'dag': [{'id': task.get('id'), 'title': task.get('title'),
                 'dependsOn': task.get('dependsOn') or []} for task in plan_tasks if isinstance(task, dict)],
        'planner': {'threadId': (report.get('planner') or {}).get('threadId') or planner.get('threadId'),
                    'turnId': (report.get('planner') or {}).get('turnId') or planner.get('turnId'),
                    'model': (report.get('planner') or {}).get('model') or planner.get('model'),
                    'status': planner.get('status') or report.get('plannerStatus')},
        'sessions': sessions_out,
        'autopilotStatus': ((report.get('finalRun') or {}).get('mahoragaAutopilot') or
                            run.get('mahoragaAutopilot') or {}).get('status'),
        'parallelBuilderPairs': overlap_pairs,
        'observedParallelBuilderPairs': observed_pairs,
        'parallelEvidence': {'sampleCount': len(report.get('parallelObservations') or []),
                             'completedTurnOverlapSeconds': round(sum(item['overlapSeconds'] for item in overlap_pairs), 3),
                             'observedLowerBoundSeconds': round(sum(item['observedLowerBoundSeconds'] for item in observed_pairs), 3),
                             'threadSets': sorted({tuple(sorted(item.get('threadIds') or []))
                                                   for item in report.get('parallelObservations') or []
                                                   if isinstance(item, dict)})},
        'builderSnapshots': [{'taskId': item.get('taskId'), 'changedFiles': item.get('changedFiles'),
                              'digest': item.get('digest')}
                             for item in snapshots if isinstance(item, dict)],
        'integratedTaskCount': len(integrated),
        'tasks': [{'id': task.get('id'), 'status': task.get('status'),
                   'repairAttempts': int(task.get('repairAttempts', 0) or 0),
                   'testStatus': (task.get('tests') or {}).get('status'),
                   'reviewVerdict': (task.get('review') or {}).get('verdict'),
                   'integratedCommit': task.get('integratedCommit') or task.get('integrationCommit')}
                  for task in final_tasks if isinstance(task, dict)],
        'integrationCommits': [task.get('integratedCommit') or task.get('integrationCommit')
                               for task in integrated if task.get('integratedCommit') or task.get('integrationCommit')],
        'repairAttempts': sum(int(task.get('repairAttempts', 0) or 0) for task in final_tasks),
        'reviewOutcomes': [{'taskId': task.get('id'), 'verdict': (task.get('review') or {}).get('verdict')}
                           for task in final_tasks if task.get('review')],
        'independentTestOutcomes': [{'taskId': task.get('id'), 'status': (task.get('tests') or {}).get('status'),
                                    'independent': (task.get('tests') or {}).get('independent')}
                                   for task in final_tasks if task.get('tests')],
        'apiOrCliSmoke': _smoke_summary(report.get('apiSmoke')),
        'finalCommit': report.get('finalCommit'),
        'finalWorkingTreeClean': report.get('finalWorkingTreeClean'),
        'failureType': (report.get('failure') or {}).get('type'),
        'failureMessage': (report.get('failure') or {}).get('message'),
        'autopilotStateAtStop': report.get('autopilotState'),
        'approvalEvidenceCount': len(report.get('pendingCodexApprovalsAtStop') or []),
        'plannerRevisionCount': len(report.get('plannerRevisions') or []),
        'failureCategory': category,
        'tokenUsage': None,
        'evidenceRef': evidence_ref,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', required=True, type=Path)
    parser.add_argument('--primary-batch', type=Path,
                        help='Batch directory whose ten scenarios form the requested primary cohort')
    parser.add_argument('--primary-evidence', type=Path, action='append', default=[],
                        help='Explicit evidence.json path for a primary scenario; repeat exactly ten times')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.primary_batch and args.primary_evidence:
        parser.error('Use either --primary-batch or --primary-evidence, not both.')
    root = args.evidence_root.resolve()
    paths = sorted(root.rglob('evidence.json'))
    known_paths = {path.resolve() for path in paths}
    for path in args.primary_evidence:
        resolved = path.resolve()
        if not resolved.is_file():
            parser.error(f'Primary evidence file does not exist: {path}')
        if resolved not in known_paths:
            paths.append(resolved)
            known_paths.add(resolved)
    reports = [summarize_evidence(path, root) for path in paths]
    primary_prefix = None
    if args.primary_batch:
        try:
            primary_prefix = args.primary_batch.resolve().relative_to(root).as_posix().rstrip('/') + '/'
        except ValueError:
            parser.error('--primary-batch must be inside --evidence-root')
    primary = [item for item in reports if primary_prefix and item['evidenceRef'].startswith(primary_prefix)]
    if args.primary_evidence:
        primary_refs = set()
        for path in args.primary_evidence:
            try:
                primary_refs.add(path.resolve().relative_to(root).as_posix())
            except ValueError:
                primary_refs.add(path.resolve().as_posix())
        primary = [item for item in reports if item['evidenceRef'] in primary_refs]
        if (len(primary) != 10 or len({item['scenarioId'] for item in primary}) != 10):
            parser.error(f'Provide exactly 10 distinct primary scenario evidence files; found {len(primary)}.')
    if args.primary_batch and (len(primary) != 10 or len({item['scenarioId'] for item in primary}) != 10):
        parser.error(f'--primary-batch must contain exactly 10 distinct scenario evidence files; found {len(primary)}.')
    payload = {
        'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        'modelRequired': 'gpt-6-luna',
        'method': 'Derived from persisted real Codex App Server evidence and Makora state; statuses are not synthesized.',
        'tokenUsageNote': 'The local Codex App Server integration did not expose per-turn token usage in the captured state.',
        'primarySummary': {status: sum(item['status'] == status for item in primary)
                           for status in ('PASS', 'FAIL', 'BLOCKED')},
        'primaryTen': primary,
        'additionalAttempts': [item for item in reports if item not in primary],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'evidenceFiles': len(reports),
                      'primaryScenarios': len(primary), 'summary': payload['primarySummary']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

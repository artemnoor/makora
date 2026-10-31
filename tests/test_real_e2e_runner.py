import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from run_ten_real_e2e import _case_metrics, _status  # noqa: E402


class RealE2ERunnerTests(unittest.TestCase):
    def test_codex_app_server_system_error_is_blocked(self):
        report = {'status': 'fail', 'failure': {'message': 'turnStatus=failed; type=systemError'}}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_required_luna_missing_is_environment_blocked_not_product_failure(self):
        report = {'status': 'fail', 'failure': {
            'message': 'Required gpt-6-luna is not available; no fallback model is permitted.'}}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_out_of_scope_codex_approval_is_blocked(self):
        report = {'status': 'fail', 'failure': {
            'message': 'Codex запросил действие вне разрешённой роли, turn или worktree; требуется проверка человека.'}}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_mahoraga_question_waiting_for_human_is_blocked(self):
        report = {'status': 'fail', 'failure': {
            'message': 'Autopilot stopped for human attention: Махорага задала вопрос человеку.'}}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_safe_rebase_conflict_is_classified_as_blocked_for_user_resolution(self):
        report = {'status': 'fail', 'taskStatuses': [{'id': 'domain', 'status': 'rebase_conflict'}]}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_unconfirmed_codex_delivery_is_blocked_not_reported_as_product_failure(self):
        report = {'status':'fail', 'sessions':[{'role':'test_designer','status':'unconfirmed'}]}
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_mahoraga_required_is_failure_until_diagnostic_session_is_started(self):
        report = {'status':'fail', 'taskStatuses':[{'id':'T1','status':'mahoraga_required'}]}
        self.assertEqual('FAIL', _status(report, 2))
        report['sessions'] = [{'role':'mahoraga','taskId':'T1','status':'completed'}]
        self.assertEqual('BLOCKED', _status(report, 2))

    def test_pass_requires_completed_autopilot_and_successful_runner(self):
        report = {'status': 'pass', 'finalRun': {'mahoragaAutopilot': {'status': 'completed'}}}
        self.assertEqual('PASS', _status(report, 0))
        self.assertEqual('FAIL', _status(report, 2))

    def test_invalid_plan_still_reports_actual_task_count_before_run_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            agents = workspace / 'agents'
            agents.mkdir()
            (agents / 'state.json').write_text(json.dumps({'sessions': {'planner-1': {
                'role': 'planner', 'threadId': 'thread-1', 'turnId': 'turn-1', 'model': 'gpt-6-luna',
                'status': 'completed', 'planValidation': {'status': 'valid', 'taskCount': 6},
                'proposal': {'tasks': [{'id': f'T{i}'} for i in range(6)]},
            }}, 'runs': {}}), encoding='utf-8')
            result = _case_metrics({'makoraWorkspace': str(workspace), 'planner': {'sessionId': 'planner-1'}})
        self.assertEqual(6, result['taskCount'])
        self.assertEqual('thread-1', result['threads'][0]['threadId'])

    def test_parallel_status_samples_without_files_are_not_confirmed_builder_work(self):
        report = {'parallelObservations': [
            {'at': '2026-10-31T11:14:20+00:00', 'threadIds': ['builder-a', 'builder-b']},
            {'at': '2026-10-31T11:14:25+00:00', 'threadIds': ['builder-a', 'builder-b']}],
            'parallelWindows': [{'from': '2026-10-31T11:14:16+00:00',
                                 'to': '2026-10-31T11:14:47+00:00'}]}
        result = _case_metrics(report)
        self.assertEqual(0, result['overlappingBuilderPairs'])
        self.assertEqual(0, result['confirmedParallelBuilderPairs'])
        self.assertEqual(0.0, result['parallelOverlapSeconds'])

    def test_parallel_metrics_require_distinct_worktrees_real_changes_and_overlapping_turns(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / 'agents').mkdir()
            (workspace / 'agents' / 'state.json').write_text(json.dumps({
                'runs': {'run-1': {'tasks': [
                    {'id': 'domain', 'status': 'integrated'}, {'id': 'store', 'status': 'integrated'}]}},
                'sessions': {},
            }), encoding='utf-8')
            report = {
                'makoraWorkspace': str(workspace), 'runId': 'run-1',
                'sessions': [
                    {'role': 'builder', 'taskId': 'domain', 'threadId': 'thread-a', 'cwd': 'C:/tree-a',
                     'executionObservedStartAt': '2026-10-31T11:14:16+00:00',
                     'executionObservedEndAt': '2026-10-31T11:14:47+00:00'},
                    {'role': 'builder', 'taskId': 'store', 'threadId': 'thread-b', 'cwd': 'C:/tree-b',
                     'executionObservedStartAt': '2026-10-31T11:14:20+00:00',
                     'executionObservedEndAt': '2026-10-31T11:14:40+00:00'},
                ],
                'builderSnapshots': [
                    {'taskId': 'domain', 'changedFiles': ['src/domain.py']},
                    {'taskId': 'store', 'changedFiles': ['src/store.py']},
                ],
            }
            result = _case_metrics(report)
        self.assertEqual(1, result['overlappingBuilderPairs'])
        self.assertEqual(1, result['confirmedParallelBuilderPairs'])
        self.assertEqual(20.0, result['parallelOverlapSeconds'])
        self.assertEqual(['domain', 'store'], result['parallelBuilderEvidence'][0]['tasks'])


if __name__ == '__main__':
    unittest.main()

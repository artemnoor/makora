import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from summarize_real_e2e import (_classification, _confirmed_parallel_pairs, _smoke_summary, main)  # noqa: E402


class MassE2ESummaryTests(unittest.TestCase):
    def test_invalid_plan_is_product_failure(self):
        report = {'status': 'fail', 'failure': {'type': 'E2EFailure', 'message': 'no independent tasks'}}
        self.assertEqual(('FAIL', 'makora_or_plan_acceptance_failure'), _classification(report))

    def test_codex_system_error_is_external_block(self):
        report = {'status': 'fail', 'failure': {'message': 'turnStatus=failed; type=systemError'}}
        self.assertEqual(('BLOCKED', 'external_codex_or_sandbox_block'), _classification(report))

    def test_missing_required_luna_is_an_environment_block(self):
        report = {'status': 'fail', 'failure': {
            'message': 'Required gpt-6-luna is not available; no fallback model is permitted.'}}
        self.assertEqual(('BLOCKED', 'external_codex_or_sandbox_block'), _classification(report))

    def test_mahoraga_question_is_a_human_decision_block(self):
        report = {'status': 'fail', 'failure': {
            'message': 'Autopilot stopped for human attention: Махорага задала вопрос человеку.'}}
        self.assertEqual(('BLOCKED', 'safe_stop_requires_human_decision'), _classification(report))

    def test_controller_permission_error_is_failure(self):
        report = {'status': 'fail', 'failure': {'message': 'PermissionError replacing state.json'}}
        self.assertEqual(('FAIL', 'makora_or_plan_acceptance_failure'), _classification(report))

    def test_safe_rebase_conflict_is_a_documented_blocker(self):
        report = {'status': 'fail', 'taskStatuses': [{'id': 'domain', 'status': 'rebase_conflict'}]}
        self.assertEqual(('BLOCKED', 'safe_stop_requires_human_or_delivery_confirmation'), _classification(report))

    def test_unconfirmed_session_is_a_safe_block_not_a_product_failure(self):
        report = {'status': 'fail', 'failure': {'message': 'delivery is unconfirmed'}}
        self.assertEqual(('BLOCKED', 'safe_stop_requires_human_or_delivery_confirmation'),
                         _classification(report, sessions=[{'status':'unconfirmed'}]))

    def test_mahoraga_required_is_fail_until_specialist_is_launched(self):
        report = {'status':'fail'}
        run = {'tasks':[{'id':'T1','status':'mahoraga_required'}]}
        self.assertEqual(('FAIL','mahoraga_escalation_not_processed'), _classification(report, run, []))
        self.assertEqual(('BLOCKED','mahoraga_diagnosis_requires_human'),
                         _classification(report, run, [{'role':'mahoraga','taskId':'T1'}]))

    def test_parallel_pair_requires_real_distinct_worktrees_and_changed_files(self):
        sessions = [
            {'role':'builder','taskId':'T1','threadId':'th1','cwd':'C:/tmp/T1','turnHistory':[
                {'executionObservedStartAt':'2026-10-31T10:00:00+00:00','executionObservedEndAt':'2026-10-31T10:00:30+00:00'}]},
            {'role':'builder','taskId':'T2','threadId':'th2','cwd':'C:/tmp/T2','turnHistory':[
                {'executionObservedStartAt':'2026-10-31T10:00:10+00:00','executionObservedEndAt':'2026-10-31T10:00:40+00:00'}]},
        ]
        snapshots = [
            {'taskId':'T1','worktree':'C:/tmp/T1','changedFiles':['src/a.py']},
            {'taskId':'T2','worktree':'C:/tmp/T2','changedFiles':['src/b.py']},
        ]
        pairs = _confirmed_parallel_pairs(sessions, snapshots)
        self.assertEqual(1, len(pairs))
        self.assertEqual(20.0, pairs[0]['overlapSeconds'])
        self.assertEqual(['src/a.py'], pairs[0]['firstChangedFiles'])
        self.assertEqual([], _confirmed_parallel_pairs(sessions, snapshots[:1]))
        same_tree = [dict(snapshots[0]), dict(snapshots[1], worktree='C:/tmp/T1')]
        self.assertEqual([], _confirmed_parallel_pairs(sessions, same_tree))

    def test_pass_requires_completed_autopilot(self):
        report = {'status': 'pass', 'finalRun': {'mahoragaAutopilot': {'status': 'completed'}}}
        self.assertEqual(('PASS', 'autopilot_completed'), _classification(report))
        report['finalRun']['mahoragaAutopilot']['status'] = 'running'
        self.assertEqual(('FAIL', 'runner_did_not_confirm_completed_autopilot'), _classification(report))

    def test_smoke_summary_omits_local_paths_and_raw_responses(self):
        value = {'mode': 'http', 'sandbox': 'C:/Users/private/project', 'checks': [
            {'case': 'list', 'status': 200, 'response': {'private': 'record'}}]}
        result = _smoke_summary(value)
        self.assertEqual({'mode': 'http', 'checks': [{'case': 'list', 'status': 200}]}, result)
        self.assertNotIn('private', str(result))

    def test_primary_evidence_can_select_latest_attempts_across_batch_directories(self):
        scenarios = ['booking-system','event-manager','expense-tracker','file-analyzer','inventory-system',
                     'mini-crm','notes-api','student-gradebook','task-manager','url-shortener']
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for scenario in scenarios:
                evidence = root / scenario / 'fresh-attempt' / 'evidence.json'
                evidence.parent.mkdir(parents=True)
                evidence.write_text(json.dumps({'scenarioId':scenario,'status':'fail',
                                                'failure':{'type':'E2EFailure','message':'review evidence'}}),
                                    encoding='utf-8')
                paths.append(str(evidence))
            output = root / 'summary.json'
            argv = ['summarize_real_e2e.py','--evidence-root',str(root),'--output',str(output)]
            for path in paths:
                argv.extend(['--primary-evidence', path])
            with patch.object(sys, 'argv', argv):
                self.assertEqual(0, main())
            report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(10, len(report['primaryTen']))
        self.assertEqual(set(scenarios), {item['scenarioId'] for item in report['primaryTen']})


if __name__ == '__main__':
    unittest.main()

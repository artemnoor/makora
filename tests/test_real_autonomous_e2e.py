import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from real_autonomous_e2e import (E2EFailure, _HTTP_PROBE, _expected_http_check_count, _next_integration_candidate, _validate_http_contract,
                                 _verify_project_entrypoint, confirmed_builder_pairs,
                                 observed_builder_pairs, redacted_approval_evidence, run_is_completed,
                                 session_snapshots, terminal_task_blocker,
                                 validate_plan, wait_for_luna_status)  # noqa: E402


def base_plan(e2e):
    return {
        'tasks': [
            {'id': 'T01', 'title': 'Data', 'goal': 'Prepare local data', 'dependsOn': [],
             'contracts': ['data exists'], 'allowedPaths': ['data.json'], 'acceptance': 'Valid JSON'},
            {'id': 'T02', 'title': 'CLI', 'goal': 'Implement command', 'dependsOn': [],
             'contracts': ['command works'], 'allowedPaths': ['cli.py'], 'acceptance': 'Runs'},
            {'id': 'T03', 'title': 'Tests', 'goal': 'Integrate and verify', 'dependsOn': ['T01', 'T02'],
             'contracts': ['integration passes'], 'allowedPaths': ['README.md'], 'acceptance': 'End-to-end'},
            {'id': 'T04', 'title': 'Final integration', 'goal': 'Final integration', 'dependsOn': ['T03'],
             'contracts': ['final project works'], 'allowedPaths': ['README.md'], 'acceptance': 'Ready'},
        ],
        'e2e': e2e,
    }


class RealAutonomousE2EPlanTests(unittest.TestCase):
    def test_harness_integrates_only_one_candidate_from_each_state_snapshot(self):
        def candidate(task_id, base='commit-a'):
            return {'id': task_id, 'status': 'review_completed', 'worktreeBase': base,
                    'review': {'verdict': 'pass', 'digest': task_id},
                    'tests': {'independent': True, 'status': 'passed', 'digest': task_id}}

        first, second = candidate('T01'), candidate('T02')
        selected = _next_integration_candidate([first, second], 'commit-a')
        self.assertIs(selected, first)
        # After the first integration advances HEAD, a fresh snapshot must be
        # used and the stale parallel branch must be left to Makora's rebase flow.
        first['status'] = 'integrated'
        self.assertIsNone(_next_integration_candidate([first, second], 'commit-b'))
        second['worktreeBase'] = 'commit-b'
        self.assertIs(_next_integration_candidate([first, second], 'commit-b'), second)

    def test_http_smoke_counts_ordered_requests_and_structured_negative_request(self):
        self.assertEqual(7, _expected_http_check_count({
            'requests': [{'name': name} for name in ('create', 'list', 'search', 'tag', 'empty', 'error')],
            'invalidRequest': {'method': 'POST', 'path': '/api/notes', 'expectedStatus': 400},
        }))
        self.assertEqual(6, _expected_http_check_count({
            'requests': [{'name': name} for name in ('create', 'list', 'search', 'tag', 'empty', 'error')],
            'invalidQuery': {'tag': ''},
        }))
        self.assertEqual(4, _expected_http_check_count({'route': '/api/items'}))

    def test_runner_waits_for_non_blocking_app_server_warmup(self):
        values = iter([
            {'warming': True, 'connected': False, 'model': None, 'modelAvailable': False},
            {'warming': False, 'connected': True, 'model': 'gpt-6-luna', 'modelAvailable': True},
        ])
        with patch('real_autonomous_e2e.time.sleep'):
            result = wait_for_luna_status('http://localhost/api/agents', 'token',
                                          fetch=lambda *args, **kwargs: next(values))
        self.assertEqual('gpt-6-luna', result['model'])

    def test_runner_does_not_fallback_when_luna_is_missing(self):
        status = {'warming': False, 'connected': True, 'model': None,
                  'modelAvailable': False, 'error': {'code': 'MODEL_UNAVAILABLE'}}
        with self.assertRaisesRegex(E2EFailure, 'no fallback model'):
            wait_for_luna_status('http://localhost/api/agents', 'token',
                                 fetch=lambda *args, **kwargs: status)

    def test_approval_evidence_redacts_command_payload_and_keeps_scope(self):
        secret = 'git status --token=do-not-log'
        result = redacted_approval_evidence([{'requestId': 'approval-1',
            'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': 'thread-1', 'turnId': 'turn-1', 'cwd': 'C:/worktree', 'command': secret}}])
        self.assertEqual(1, len(result))
        self.assertEqual('thread-1', result[0]['threadId'])
        self.assertEqual('turn-1', result[0]['turnId'])
        self.assertIn('commandDigest', result[0])
        self.assertNotIn(secret, json.dumps(result))

    def test_run_completion_requires_terminal_autopilot_after_all_integrations(self):
        run = {'tasks': [{'id': 'T1', 'status': 'integrated'}],
               'mahoragaAutopilot': {'status': 'running'}}
        self.assertFalse(run_is_completed(run))

    def test_mahoraga_required_waits_for_escalation_instead_of_stopping_runner(self):
        run = {'tasks': [{'id': 'T1', 'status': 'mahoraga_required'}],
               'mahoragaAutopilot': {'status': 'running'}}
        self.assertIsNone(terminal_task_blocker(run))
        run['tasks'][0]['status'] = 'blocked_for_human'
        self.assertEqual('T1', terminal_task_blocker(run))
        run['tasks'][0]['status'] = 'rebase_conflict'
        self.assertEqual('T1', terminal_task_blocker(run))
        run['mahoragaAutopilot']['status'] = 'completed'
        self.assertFalse(run_is_completed(run))
        run['tasks'][0]['status'] = 'integrated'
        self.assertTrue(run_is_completed(run))
        run['tasks'][0]['status'] = 'review_completed'
        self.assertFalse(run_is_completed(run))

    def test_parallel_builder_proof_requires_overlapping_turns_changes_and_distinct_worktrees(self):
        sessions = [
            {'role': 'builder', 'taskId': 'T1', 'threadId': 'thread-1', 'cwd': 'C:/repo/T1',
             'executionObservedStartAt': '2026-10-31T10:00:00+00:00',
             'executionObservedEndAt': '2026-10-31T10:00:30+00:00'},
            {'role': 'builder', 'taskId': 'T2', 'threadId': 'thread-2', 'cwd': 'C:/repo/T2',
             'executionObservedStartAt': '2026-10-31T10:00:10+00:00',
             'executionObservedEndAt': '2026-10-31T10:00:40+00:00'},
        ]
        snapshots = [{'taskId': 'T1', 'changedFiles': ['data.json']},
                     {'taskId': 'T2', 'changedFiles': ['src/api.js']}]
        pairs = confirmed_builder_pairs(sessions, snapshots)
        self.assertEqual(1, len(pairs))
        self.assertEqual(20.0, pairs[0]['overlapSeconds'])
        self.assertEqual(['thread-1', 'thread-2'], pairs[0]['threads'])
        self.assertEqual([], confirmed_builder_pairs(sessions, snapshots[:1]))

    def test_blocked_parallel_builders_keep_observed_lower_bound_separate_from_turn_completion(self):
        sessions = [
            {'role':'builder','taskId':'T1','threadId':'thread-1','cwd':'C:/tmp/T1','status':'running'},
            {'role':'builder','taskId':'T2','threadId':'thread-2','cwd':'C:/tmp/T2','status':'running'},
        ]
        snapshots = [
            {'taskId':'T1','worktree':'C:/tmp/T1','changedFiles':['src/a.py']},
            {'taskId':'T2','worktree':'C:/tmp/T2','changedFiles':['src/b.py']},
        ]
        observations = [
            {'at':'2026-10-31T10:00:10+00:00','threadIds':['thread-1','thread-2']},
            {'at':'2026-10-31T10:00:20+00:00','threadIds':['thread-1','thread-2']},
        ]
        result = observed_builder_pairs(sessions, snapshots, observations)
        self.assertEqual(1, len(result))
        self.assertEqual(10.0, result[0]['observedLowerBoundSeconds'])
        self.assertEqual(['src/a.py'], result[0]['changedFiles']['T1'])
        self.assertEqual([], confirmed_builder_pairs(sessions, snapshots))
        self.assertEqual([], observed_builder_pairs(sessions, snapshots[:1], observations))

    def test_parallel_builder_proof_uses_exact_turn_intervals_not_idle_session_span(self):
        sessions = [
            {'role':'builder','taskId':'T1','threadId':'thread-1','cwd':'C:/repo/T1',
             'executionObservedStartAt':'2026-10-31T10:00:00+00:00',
             'executionObservedEndAt':'2026-10-31T10:10:00+00:00',
             'turnHistory':[{'executionObservedStartAt':'2026-10-31T10:00:00+00:00',
                             'executionObservedEndAt':'2026-10-31T10:00:20+00:00'}]},
            {'role':'builder','taskId':'T2','threadId':'thread-2','cwd':'C:/repo/T2',
             'executionObservedStartAt':'2026-10-31T10:00:10+00:00',
             'executionObservedEndAt':'2026-10-31T10:10:00+00:00',
             'turnHistory':[{'executionObservedStartAt':'2026-10-31T10:00:30+00:00',
                             'executionObservedEndAt':'2026-10-31T10:00:40+00:00'}]},
        ]
        snapshots = [{'taskId':'T1','changedFiles':['src/a.py']},
                     {'taskId':'T2','changedFiles':['src/b.py']}]
        self.assertEqual([], confirmed_builder_pairs(sessions, snapshots))

    def test_session_evidence_keeps_prior_turns_when_followup_replaces_current_turn(self):
        first = {'id':'builder-1','role':'builder','taskId':'T01','threadId':'thread-1',
                 'operationId':'operation-1','turnId':'turn-1','status':'completed',
                 'requestedAt':'2026-10-31T10:00:00+00:00','acceptedAt':'2026-10-31T10:00:01+00:00',
                 'executionObservedStartAt':'2026-10-31T10:00:02+00:00',
                 'executionObservedEndAt':'2026-10-31T10:00:10+00:00','executionObservedDurationMs':8000,
                 'turnHistory':[]}
        second = {**first,'operationId':'operation-2','turnId':'turn-2','status':'running',
                  'requestedAt':'2026-10-31T10:01:00+00:00','acceptedAt':'2026-10-31T10:01:01+00:00',
                  'executionObservedStartAt':'2026-10-31T10:01:02+00:00','executionObservedEndAt':None,
                  'executionObservedDurationMs':None}
        result = session_snapshots([second],[first])[0]
        self.assertEqual(['turn-1','turn-2'],[turn['turnId'] for turn in result['turnHistory']])
        self.assertEqual('2026-10-31T10:00:10+00:00',result['turnHistory'][0]['executionObservedEndAt'])
        self.assertIsNone(result['turnHistory'][1]['executionObservedEndAt'])

    def test_cli_contract_accepts_success_and_invalid_input_commands(self):
        result = validate_plan(base_plan({'mode': 'cli', 'commands': [
            {'name': 'valid file', 'argv': ['python', 'cli.py', 'data.csv'], 'expectedExitCode': 0,
             'expectedContains': 'records'},
            {'name': 'missing file', 'argv': ['python', 'cli.py', 'missing.csv'], 'expectedExitCode': 2,
             'expectedContains': 'not found'},
        ]}))
        self.assertEqual('cli', result['e2eMode'])
        self.assertEqual(['T01', 'T02'], result['independentPair'])

    def test_cli_contract_requires_error_case(self):
        with self.assertRaisesRegex(E2EFailure, 'successful and an invalid-input'):
            validate_plan(base_plan({'mode': 'cli', 'commands': [
                {'argv': ['python', 'cli.py', 'data.csv'], 'expectedExitCode': 0, 'expectedContains': 'records'},
                {'argv': ['python', 'cli.py', 'other.csv'], 'expectedExitCode': 0, 'expectedContains': 'records'},
            ]}))

    def test_cli_contract_rejects_inline_code_execution(self):
        with self.assertRaisesRegex(E2EFailure, 'inline code execution'):
            validate_plan(base_plan({'mode': 'cli', 'commands': [
                {'argv': ['python', '-c', 'print(1)'], 'expectedExitCode': 0},
                {'argv': ['python', 'cli.py', 'missing.csv'], 'expectedExitCode': 2},
            ]}))

    def test_plan_validation_rejects_malformed_tasks_without_crashing(self):
        with self.assertRaisesRegex(E2EFailure, 'JSON object'):
            validate_plan({'tasks': ['not a task'] * 4})
        malformed = base_plan({'mode': 'cli', 'commands': [
            {'argv': ['python', 'cli.py', 'data.csv'], 'expectedExitCode': 0, 'expectedContains': 'records'},
            {'argv': ['python', 'cli.py', 'missing.csv'], 'expectedExitCode': 2, 'expectedContains': 'not found'},
        ]})
        malformed['tasks'][0]['id'] = []
        with self.assertRaisesRegex(E2EFailure, 'valid string ID'):
            validate_plan(malformed)

    def test_russian_infinitive_for_final_integration_is_recognized(self):
        plan = base_plan({'launch':['python','app.py'], 'portEnv':'PORT', 'route':'/items',
                          'searchParameter':'q', 'invalidQuery':{'q':'bad'},
                          'nameField':'name', 'listKey':'items'})
        plan['tasks'][3]['title'] = 'Подготовить итоговую версию'
        plan['tasks'][3]['goal'] = 'Интегрировать проверенные модули приложения.'
        result = validate_plan(plan)
        self.assertEqual('T04', result['finalIntegrationTask'])

    def test_http_contract_remains_default_for_existing_plans(self):
        self.assertEqual('http', validate_plan(base_plan({
            'launch': ['node', 'server.js'], 'portEnv': 'PORT', 'route': '/items',
            'searchParameter': 'q', 'invalidQuery': {'limit': 'bad'}, 'nameField': 'name', 'listKey': 'items',
        }))['e2eMode'])

    def test_booking_plan_requires_real_create_then_conflict_requests(self):
        listing_only = {'mode':'http','launch':['python','-m','booking'],'portEnv':'PORT',
                        'route':'/api/bookings','searchParameter':'roomId',
                        'nameField':'id','listKey':'bookings','invalidQuery':{'roomId':'missing'}}
        with self.assertRaisesRegex(E2EFailure, 'create a valid reservation'):
            validate_plan(base_plan(listing_only), scenario_id='booking-system')
        workflow = {'mode':'http','launch':['python','-m','booking'],'portEnv':'PORT','requests':[
            {'name':'createBooking','method':'POST','path':'/api/bookings',
             'body':{'roomId':'room-1','start':'2030-01-01T10:00:00Z','end':'2030-01-01T11:00:00Z'},
             'expectedStatus':201,'capture':{'bookingId':'id'}},
            {'name':'overlapBooking','method':'POST','path':'/api/bookings',
             'body':{'roomId':'room-1','start':'2030-01-01T10:30:00Z','end':'2030-01-01T11:30:00Z'},
             'expectedStatus':409,'expectedJson':{'error':'booking_conflict'}},
        ]}
        self.assertEqual('http', validate_plan(base_plan(workflow), scenario_id='booking-system')['e2eMode'])

    def test_inventory_negative_http_request_supports_method_body_and_expected_error(self):
        _validate_http_contract({
            'launch':['python','server.py'], 'portEnv':'PORT', 'route':'/api/products',
            'searchParameter':'q', 'nameField':'name', 'listKey':'products',
            'invalidQuery': {'method':'POST', 'path':'/api/products/SKU-1/stock',
                             'body':{'type':'out','quantity':11}, 'expectedStatus':409,
                             'expectedError':'insufficient_stock'},
        })

    def test_http_request_workflow_supports_create_and_redirect_without_following_external_location(self):
        plan = base_plan({'mode':'http', 'launch':['python','server.py'], 'portEnv':'PORT', 'requests':[
            {'name':'create','method':'POST','path':'/api/shorten','body':{'url':'https://example.test/demo'},
             'expectedStatus':201,'capture':{'code':'code'}},
            {'name':'redirect','method':'GET','path':'/api/{{create.code}}','expectedStatus':302,
             'expectedHeaders':{'Location':'https://example.test/demo'}},
            {'name':'invalid','method':'POST','path':'/api/shorten','body':{'url':'not-a-url'},
             'expectedStatus':400,'expectedJson':{'error':'invalid_request'}},
        ]})
        self.assertEqual('http', validate_plan(plan)['e2eMode'])

    def test_http_capture_must_use_alias_to_json_path_object(self):
        spec = {'launch':['python','server.py'], 'portEnv':'PORT', 'route':'/api/students',
                'searchParameter':'name', 'nameField':'name', 'listKey':None,
                'requests':[
                    {'name':'create','method':'POST','path':'/api/students','body':{'name':'Ada'},
                     'expectedStatus':201,'capture':['json.id']},
                    {'name':'invalid','method':'POST','path':'/api/students','body':{},
                     'expectedStatus':400,'expectedJson':{'error':'required'}},
                ]}
        with self.assertRaisesRegex(E2EFailure, 'capture must be an object mapping aliases'):
            _validate_http_contract(spec)

    def test_ordered_http_requests_support_json_path_references_and_separate_invalid_query(self):
        spec = {'launch':['python','server.py'], 'portEnv':'PORT', 'route':'/api/items',
                'searchParameter':'name', 'nameField':'name', 'listKey':None,
                'requests':[
                    {'name':'create','method':'POST','path':'/api/items','body':{'name':'Ada'},
                     'expectedStatus':201},
                    {'name':'lookup','method':'GET','path':'/api/items/{{create.json.id}}',
                     'expectedStatus':200,'expectedJson':{'item':{'name':'Ada'}}},
                ],
                'invalidQuery': {'method':'GET','path':'/api/items/missing',
                                 'expectedStatus':404,'expectedError':'error'}}
        _validate_http_contract(spec)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / '.makora-tests').mkdir()
            (project / 'server.py').write_text('''import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def respond(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.respond(201, {"id":"item-1","name":"Ada"})
    def do_GET(self):
        if self.path == "/api/items/item-1": self.respond(200, {"item":{"id":"item-1","name":"Ada"}})
        else: self.respond(404, {"error":"not found"})
    def log_message(self, *_args): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
''', encoding='utf-8')
            (project / '.makora-tests' / 'e2e-spec.json').write_text(json.dumps(spec), encoding='utf-8')
            result = subprocess.run([sys.executable, '-c', _HTTP_PROBE], cwd=project,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            payload_line = next(line for line in result.stdout.splitlines() if line.startswith('MAKORA_E2E_JSON:'))
            checks = json.loads(payload_line.split(':', 1)[1])
            self.assertEqual(['create', 'lookup', 'invalid'], [item['case'] for item in checks])
            self.assertEqual(404, checks[-1]['status'])

    def test_http_workflow_substitutes_captured_values_in_bodies_and_expected_json(self):
        spec = {'launch':['python', 'server.py'], 'portEnv':'PORT', 'route':'/api/clients',
                'searchParameter':'name', 'nameField':'name', 'listKey':'items',
                'requests':[
                    {'name':'createClient','method':'POST','path':'/api/clients',
                     'body':{'name':'Ada'},'expectedStatus':201,'capture':{'clientId':'id'}},
                    {'name':'filterClients','method':'GET','path':'/api/clients?name=Ada',
                     'expectedStatus':200,'expectedJson':{'items':[{'id':'{{createClient.clientId}}','name':'Ada'}]}},
                    {'name':'createDeal','method':'POST','path':'/api/deals',
                     'body':{'client_id':'{{createClient.json.id}}'},'expectedStatus':201,
                     'expectedJson':{'deal':{'client_id':'{{createClient.clientId}}'}}},
                ],
                'invalidQuery':{'method':'GET','path':'/missing','expectedStatus':404,'expectedError':'error'}}
        _validate_http_contract(spec)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / '.makora-tests').mkdir()
            (project / 'server.py').write_text('''import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, parse_qs
clients = []
class Handler(BaseHTTPRequestHandler):
    def respond(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        if self.path == "/api/clients":
            client = {"id": 42, **payload}
            clients.append(client)
            self.respond(201, client)
        elif self.path == "/api/deals" and payload.get("client_id") == 42:
            self.respond(201, {"deal": {"client_id": payload["client_id"]}})
        else:
            self.respond(400, {"error": "invalid client_id"})
    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/api/clients":
            query = parse_qs(parsed.query).get("name", [""])[0]
            self.respond(200, {"items": [item for item in clients if query.lower() in item["name"].lower()]})
        else:
            self.respond(404, {"error": "not found"})
    def log_message(self, *_args): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
''', encoding='utf-8')
            (project / '.makora-tests' / 'e2e-spec.json').write_text(json.dumps(spec), encoding='utf-8')
            result = subprocess.run([sys.executable, '-c', _HTTP_PROBE], cwd=project,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            payload_line = next(line for line in result.stdout.splitlines() if line.startswith('MAKORA_E2E_JSON:'))
            checks = json.loads(payload_line.split(':', 1)[1])
            self.assertEqual(['createClient','filterClients','createDeal','invalid'],
                             [item['case'] for item in checks])
            self.assertEqual(42, checks[1]['response']['items'][0]['id'])
            self.assertEqual(42, checks[2]['response']['deal']['client_id'])

    def test_http_workflow_rejects_external_origins_and_unresolved_forward_references(self):
        invalid = {'mode':'http','launch':['node','server.js'],'portEnv':'PORT','requests':[
            {'name':'create','method':'POST','path':'https://example.test','expectedStatus':201},
            {'name':'invalid','method':'GET','path':'/api/items','expectedStatus':400},
        ]}
        with self.assertRaisesRegex(E2EFailure, 'stay on the local application origin'):
            _validate_http_contract(invalid)
        invalid['requests'][0]['path'] = '/api/items'
        invalid['requests'][1]['path'] = '/api/{{later.id}}'
        with self.assertRaisesRegex(E2EFailure, 'not run yet'):
            _validate_http_contract(invalid)

    def test_http_probe_is_valid_python_source(self):
        compile(_HTTP_PROBE, '<makora-http-probe>', 'exec')

    def test_http_probe_accepts_expected_error_as_nonempty_response_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / '.makora-tests').mkdir()
            (project / 'server.py').write_text('''import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
class Handler(BaseHTTPRequestHandler):
    def respond(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        records = [{"id":"client-1","name":"Ada"}]
        query = parse_qs(urlparse(self.path).query).get("q", [""])[0]
        self.respond(200, [row for row in records if query.lower() in row["name"].lower()])
    def do_POST(self):
        self.respond(400, {"error":"Client name and email must be non-empty strings"})
    def log_message(self, *_args): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
''', encoding='utf-8')
            (project / '.makora-tests' / 'e2e-spec.json').write_text(json.dumps({
                'launch': [sys.executable, 'server.py'], 'portEnv': 'PORT', 'route': '/api/clients',
                'searchParameter': 'q', 'nameField': 'name', 'listKey': None,
                'invalidRequest': {'method': 'POST', 'path': '/api/clients',
                                   'body': {'name': '', 'email': 'invalid@example.test'},
                                   'expectedStatus': 400, 'expectedError': 'error'},
            }), encoding='utf-8')
            result = subprocess.run([sys.executable, '-c', _HTTP_PROBE], cwd=project,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr + result.stdout)
            payload_line = next(line for line in result.stdout.splitlines() if line.startswith('MAKORA_E2E_JSON:'))
            checks = json.loads(payload_line.split(':', 1)[1])
            self.assertEqual('invalid', checks[-1]['case'])
            self.assertEqual(400, checks[-1]['status'])
            self.assertIn('error', checks[-1]['response'])

    def test_list_http_contract_rejects_non_list_endpoint_without_request_flow(self):
        with self.assertRaisesRegex(E2EFailure, 'ordered e2e.requests'):
            _validate_http_contract({'launch':['python','server.py'],'portEnv':'PORT','route':'/api/shorten',
                'searchParameter':'url','nameField':'code','listKey':None,'invalidQuery':{'url':'bad'}})

    def test_cli_smoke_commands_must_share_one_entrypoint(self):
        plan = base_plan({'mode': 'cli', 'commands': [
            {'argv': ['python', 'cli.py', 'data.csv'], 'expectedExitCode': 0, 'expectedContains': 'records'},
            {'argv': ['python', 'other.py', 'bad.csv'], 'expectedExitCode': 2, 'expectedContains': 'invalid'},
        ]})
        with self.assertRaisesRegex(E2EFailure, 'same application entry point'):
            validate_plan(plan)

    def test_final_smoke_entrypoint_must_be_an_existing_project_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / 'cli.py').write_text('print("ok")\n', encoding='utf-8')
            _verify_project_entrypoint(project, ['python', 'cli.py'], 'CLI')
            with self.assertRaisesRegex(E2EFailure, 'does not exist'):
                _verify_project_entrypoint(project, ['python', 'missing.py'], 'CLI')

    def test_final_smoke_rejects_entrypoint_outside_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(E2EFailure, 'escapes the project'):
                _verify_project_entrypoint(Path(temporary), ['python', '../outside.py'], 'CLI')


if __name__ == '__main__':
    unittest.main()

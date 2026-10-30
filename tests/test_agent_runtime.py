from __future__ import annotations

import subprocess
import tempfile
import unittest
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock
from pathlib import Path

from makora_core.agents.runtime import AgentRuntime, AgentRuntimeError, CodexLocalApi, MODEL_ID


class FakeProvider:
    def __init__(self):
        self.sessions = {}
        self.next = 0
        self.pending_approvals = []
        self.resolved_approvals = []

    def status(self):
        return {"connected": True, "model": MODEL_ID, "modelAvailable": True}

    def create_thread(self, *, cwd, name, prompt, sandbox="workspaceWrite", denied_paths=None):
        self.next += 1
        thread = f"thread-{self.next}"
        operation = f"operation-{self.next}"
        turn=f"turn-{self.next}"
        self.sessions[thread] = {"operation": operation, "state": "accepted", "turn":turn, "cwd": cwd,
                                 "prompt": prompt, "sandbox": sandbox}
        return {"id": thread, "turnId": turn,
                "operation": {"id": operation, "state": "accepted"}}

    def operation(self, operation_id):
        item = next(item for item in self.sessions.values() if item["operation"] == operation_id)
        return {"id": operation_id, "state": item["state"]}

    def history(self, thread_id):
        turn=self.sessions[thread_id].get('turn')
        return {"id": thread_id, "turns": [{"id":turn,"status": "completed", "items": [{"type": "agentMessage", "text": "Done."}]}]}

    def send(self, thread_id, text):
        self.next += 1
        operation=f"followup-{self.next}"
        turn=f"new-turn-{self.next}"
        self.sessions[thread_id]['operation']=operation
        self.sessions[thread_id]['turn']=turn
        self.sessions[thread_id]['state']='accepted'
        return {"threadId": thread_id, "turnId": turn, "operation": {"id": operation, "state": "accepted"}}

    def approvals(self):
        return list(self.pending_approvals)

    def resolve_approval(self, request_id, decision):
        self.resolved_approvals.append((request_id, decision))

    def close(self):
        pass


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.workspace = self.base / "makora-state"
        self.integration = self.base / "integration"
        self.integration.mkdir()
        (self.project / "README.md").write_text("fixture\n", encoding="utf-8")
        (self.project / "private_source.py").write_text("PRIVATE SOURCE\n", encoding="utf-8")
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Makora tests")
        self.git("config", "user.email", "makora-tests@localhost")
        self.git("add", ".")
        self.git("commit", "-m", "fixture")
        self.provider = FakeProvider()
        self.runtime = AgentRuntime(self.workspace, self.integration, [self.project], self.provider)

    def tearDown(self):
        self.temp.cleanup()

    def test_concurrent_codex_api_startup_starts_only_one_bridge(self):
        integration = self.base / 'integration-startup'
        workspace = self.base / 'workspace-startup'
        integration.mkdir()
        (workspace / 'agents').mkdir(parents=True)
        (integration / 'start-api.ps1').write_text('fixture', encoding='utf-8')
        api = CodexLocalApi(integration, workspace)
        started = False
        calls_lock = threading.Lock()

        def request(path, payload=None, timeout=8):
            with calls_lock:
                return {'ready': started}

        def start_process(*args, **kwargs):
            nonlocal started
            with calls_lock:
                started = True
            return process

        api._request = request
        process = Mock()
        process.poll.return_value = None
        with patch('makora_core.agents.runtime.shutil.which', return_value='pwsh'), \
             patch('makora_core.agents.runtime.subprocess.Popen', side_effect=start_process) as popen:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(lambda _: api.ensure_started(), range(6)))
        self.assertEqual(popen.call_count, 1)
        with patch('makora_core.agents.runtime.subprocess.run'):
            api.close()

    def test_python_independent_suite_receives_conventional_source_roots(self):
        from makora_core.agents.acceptance import _test_environment
        (self.project / 'app').mkdir()
        env = _test_environment(self.project, ['python', '-m', 'unittest'])
        paths = env['PYTHONPATH'].split(os.pathsep)
        self.assertTrue(any(Path(path).samefile(self.project) for path in paths))
        self.assertTrue(any(Path(path).samefile(self.project / 'app') for path in paths))

    def test_windows_close_terminates_owned_tree_before_parent_exits(self):
        workspace = self.base / 'close-workspace'
        (workspace / 'agents').mkdir(parents=True)
        api = CodexLocalApi(self.integration, workspace)
        process = Mock(pid=12345)
        process.poll.return_value = None
        api._process = process
        with patch('makora_core.agents.runtime.os.name', 'nt'), patch('makora_core.agents.runtime.subprocess.run') as kill:
            api.close()
        kill.assert_called_once()
        self.assertEqual(['taskkill', '/PID', '12345', '/T', '/F'], kill.call_args.args[0])
        process.terminate.assert_not_called()
        process.wait.assert_called_once()

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True)
        if result.returncode:
            self.fail(result.stderr)
        return result.stdout.strip()

    def task(self, ident="T01", dependencies=None):
        return {"id": ident, "title": f"Task {ident}", "goal": "Implement a small isolated module.",
                "acceptance": "The expected file exists.", "dependsOn": dependencies or [],
                "contracts": ["example"], "mocks": ["mocks/example.json"],
                "builderPrompt": "Create result.txt with the word ready."}

    def create_run(self, tasks=None):
        return self.runtime.create_run({"projectRoot": str(self.project), "tasks": tasks or [self.task()]})

    def prepare_test_design(self, run_id, task_id="T01"):
        session = self.runtime.launch_agent(run_id, task_id, "test_designer")
        spec = Path(session['cwd'])
        (spec/'TEST_DESIGN.md').write_text('# Independent tests\nChecks public contract.\n', encoding='utf-8')
        (spec/'tests').mkdir()
        (spec/'tests'/'test_contract.py').write_text('import unittest\nclass Contract(unittest.TestCase):\n def test_smoke(self): self.assertTrue(True)\n', encoding='utf-8')
        (spec/'test-manifest.json').write_text('{"version":1,"framework":"unittest","files":["tests/test_contract.py"],"commands":[["python","-m","unittest","discover","-s",".makora-tests","-v"]]}', encoding='utf-8')
        self.provider.sessions[session["threadId"]]["state"] = "completed"
        self.runtime.get_session(session["id"])
        return session

    def test_pins_actual_model_and_records_real_thread_ids(self):
        self.create_run()
        run_id = next(iter(self.runtime.state["runs"]))
        self.prepare_test_design(run_id)
        designer_session = next(item for item in self.runtime.state['sessions'].values()
                                if item.get('role') == 'test_designer')
        designer_prompt = self.provider.sessions[designer_session['threadId']]['prompt']
        self.assertIn('входные документы находятся в корне: TASK.md, CONTRACTS.md, ACCEPTANCE.md', designer_prompt)
        self.assertIn('Позже контроллер запускает suite в sandbox-каталоге проекта', designer_prompt)
        self.assertNotIn('Не читай документы из корня проекта', designer_prompt)
        tree = self.runtime.create_task_worktree(run_id, "T01")
        session = self.runtime.launch_agent(run_id, "T01", "builder")
        self.assertEqual(MODEL_ID, session["model"])
        self.assertEqual(tree["worktree"], session["cwd"])
        self.assertEqual("codex-app-server", session["transport"])
        self.assertTrue(session["threadId"])
        self.assertTrue(session["operationId"])
        self.assertEqual("workspaceWrite", self.provider.sessions[session["threadId"]]["sandbox"])

    def test_dependencies_block_until_integration(self):
        self.create_run([self.task("T01"), self.task("T02", ["T01"])])
        run_id = next(iter(self.runtime.state["runs"]))
        with self.assertRaisesRegex(AgentRuntimeError, "Ожидает интеграции"):
            self.runtime.create_task_worktree(run_id, "T02")

    def test_unknown_dependencies_and_cycles_are_rejected(self):
        with self.assertRaises(AgentRuntimeError):
            self.create_run([self.task("T01", ["MISSING"])])
        with self.assertRaises(AgentRuntimeError):
            self.create_run([self.task("T01", ["T02"]), self.task("T02", ["T01"])])

    def test_mahoraga_decomposes_case_and_controller_validates_plan_before_run_creation(self):
        session=self.runtime.start_mahoraga_planning({'projectRoot':str(self.project),'brief':'Build a small feature.','context':'Requirements: fast and accessible.'})
        self.assertEqual('mahoraga_planner',session['role'])
        self.assertEqual('workspaceWrite',self.provider.sessions[session['threadId']]['sandbox'])
        self.assertTrue((Path(session['cwd'])/'BRIEF.md').is_file())
        planned_task=self.task('T01');planned_task['acceptance']=['Criterion A','Criterion B'];planned_task['allowedPaths']=['src/example.py']
        proposal={'summary':'One independently testable slice.','queueStrategy':'Dependency order, max two builders.',
                  'risks':['External API availability is unknown.'],'openQuestions':['Confirm data source.'],
                  'tasks':[planned_task]}
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(session['id'])
        approved=self.runtime.approve_mahoraga_plan(session['id'])
        self.assertEqual('One independently testable slice.',approved['mahoragaPlan']['summary'])
        self.assertEqual('pending',approved['tasks'][0]['status'])
        self.assertEqual('- Criterion A\n- Criterion B',approved['tasks'][0]['acceptance'])
        self.assertEqual(approved['id'],self.runtime.get_session(session['id'],refresh=False)['approvedRunId'])

    def test_mahoraga_plan_with_cycle_is_rejected_before_approval(self):
        session=self.runtime.start_mahoraga_planning({'projectRoot':str(self.project),'brief':'Build a feature.'})
        proposal={'tasks':[self.task('T01',['T02'])|{'allowedPaths':['src/one.py']},
                           self.task('T02',['T01'])|{'allowedPaths':['src/two.py']}]}
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(session['id'])
        recovered=self.runtime.get_session(session['id'],refresh=False)
        self.assertIsNone(recovered.get('proposal'))
        self.assertEqual('TASK_CYCLE',recovered['planError']['code'])
        with self.assertRaisesRegex(AgentRuntimeError,'Сначала получи'):
            self.runtime.approve_mahoraga_plan(session['id'])

    def test_mahoraga_plan_rejects_description_instead_of_mocks_path_array(self):
        session=self.runtime.start_mahoraga_planning({'projectRoot':str(self.project),'brief':'Build a feature.'})
        task=self.task('T01')
        task['mocks']='There are no fixtures yet; Builder should create them.'
        proposal={'tasks':[task]}
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(session['id'])
        recovered=self.runtime.get_session(session['id'],refresh=False)
        self.assertIsNone(recovered.get('proposal'))
        self.assertEqual('PLAN_INVALID',recovered['planError']['code'])
        self.assertIn('mocks',recovered['planError']['message'])
        with self.assertRaisesRegex(AgentRuntimeError,'Сначала получи'):
            self.runtime.approve_mahoraga_plan(session['id'])

    def test_mahoraga_plan_rejects_task_without_exact_file_scope(self):
        session=self.runtime.start_mahoraga_planning({'projectRoot':str(self.project),'brief':'Build a feature.'})
        task=self.task('T01')
        proposal={'tasks':[task]}
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(session['id'])
        recovered=self.runtime.get_session(session['id'],refresh=False)
        self.assertIsNone(recovered.get('proposal'))
        self.assertIn('allowedPaths',recovered['planError']['message'])

    def test_failed_test_design_can_be_retried_in_a_fresh_scoped_directory(self):
        run=self.create_run()
        first=self.runtime.launch_agent(run['id'],'T01','test_designer')
        self.provider.sessions[first['threadId']]['state']='completed'
        self.runtime.get_session(first['id'])
        task=next(item for item in self.runtime._run(run['id'])['tasks'] if item['id']=='T01')
        self.assertEqual('failed',task['testDesignStatus'])
        self.assertEqual(['launch_test_designer'],self.runtime._mahoraga_allowed_actions(self.runtime._run(run['id']),task))
        second=self.runtime.launch_agent(run['id'],'T01','test_designer')
        self.assertNotEqual(first['cwd'],second['cwd'])
        self.assertTrue(second['cwd'].endswith('-attempt-2'))
        self.assertIn('Предыдущая попытка',self.provider.sessions[second['threadId']]['prompt'])
        self.assertEqual(2,task['testDesignerAttempts'])
        self.assertEqual([first['id'],second['id']],task['testDesignerSessionIds'])

    def test_mahoraga_queue_actions_are_checked_by_controller(self):
        run=self.create_run()
        session=self.runtime.start_mahoraga_orchestrator(run['id'])
        proposal={'summary':'Prepare isolated worktree, then await test design.', 'actions':[
            {'action':'prepare_worktree','taskId':'T01','reason':'No dependencies.'},
            {'action':'launch_builder','taskId':'T01','reason':'Attempt before test design.'},
            {'action':'integrate','taskId':'T01','reason':'Unknown unsafe command.'}]}
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(session['id'])
        result=self.runtime.apply_mahoraga_actions(session['id'])
        self.assertEqual(['accepted','rejected','rejected'],[item['status'] for item in result['results']])
        self.assertEqual('ready',self.runtime._run(run['id'])['tasks'][0]['status'])
        self.assertEqual('ACTION_NOT_ALLOWED',result['results'][1]['code'])
        self.assertIn('launch_test_designer',result['results'][1]['details']['allowedActions'])
        self.assertEqual('Неизвестное действие или отсутствует taskId.',result['results'][2]['reason'])

    def test_autopilot_requires_approved_mahoraga_plan_and_exact_file_scopes(self):
        run=self.create_run()
        with self.assertRaises(AgentRuntimeError) as caught:
            self.runtime.set_mahoraga_autopilot(run['id'],True)
        self.assertEqual('PLAN_APPROVAL_REQUIRED',caught.exception.code)
        self.runtime._run(run['id'])['plannerSessionId']='approved-planner'
        with self.assertRaises(AgentRuntimeError) as caught:
            self.runtime.set_mahoraga_autopilot(run['id'],True)
        self.assertEqual('AUTOPILOT_SCOPE_REQUIRED',caught.exception.code)
        for unsafe in ('../outside.py','.env','src/.hidden.py','C:/outside.py'):
            with self.assertRaises(AgentRuntimeError):
                self.runtime.create_run({'projectRoot':str(self.project),'tasks':[self.task()|{'allowedPaths':[unsafe]}]})

    def test_mahoraga_autopilot_advances_completed_thread_and_stops_on_active_agent(self):
        task=self.task()|{'allowedPaths':['src/catalog.py']}
        planner=self.runtime.start_mahoraga_planning({'projectRoot':str(self.project),'brief':'Build a catalogue.'})
        proposal={'summary':'One scoped task.','tasks':[task]}
        self.provider.history=lambda thread_id:{'turns':[{'id':planner['turnId'],'status':'completed',
            'items':[{'type':'agentMessage','text':json.dumps(proposal)}]}]}
        self.runtime.refresh_session(planner['id'])
        run=self.runtime.approve_mahoraga_plan(planner['id'])
        self.runtime._ensure_autopilot_worker=lambda:None
        self.runtime.set_mahoraga_autopilot(run['id'],True)
        requested=self.runtime.advance_mahoraga_autopilot(run['id'])
        self.assertEqual('decision_requested',requested['status'])
        director=self.runtime.get_session(requested['sessionId'],refresh=False)
        response={'summary':'Prepare the task and launch its independent test designer.','actions':[
            {'action':'prepare_worktree','taskId':task['id'],'reason':'Create isolated branch.'},
            {'action':'launch_test_designer','taskId':task['id'],'reason':'Prepare independent contract tests.'}]}
        self.provider.sessions[director['threadId']]['state']='completed'
        old_history=self.provider.history
        self.provider.history=lambda thread_id: (
            {'turns':[{'id':director['turnId'],'status':'completed','items':[{'type':'agentMessage','text':json.dumps(response)}]}]}
            if thread_id==director['threadId'] else old_history(thread_id))
        applied=self.runtime.advance_mahoraga_autopilot(run['id'])
        self.assertEqual('actions_applied',applied['status'])
        self.assertEqual(['accepted','accepted'],[item['status'] for item in applied['result']['results']])
        self.assertEqual('ready',self.runtime.get_run(run['id'])['tasks'][0]['status'])
        designer=next(session for session in self.runtime.snapshot()['sessions'] if session['role']=='test_designer')
        self.provider.sessions[designer['threadId']]['state']='running'
        manager_history=self.provider.history
        self.provider.history=lambda thread_id: (
            {'turns':[{'id':designer['turnId'],'status':'inProgress','items':[]}]} if thread_id==designer['threadId']
            else manager_history(thread_id))
        current=self.runtime.advance_mahoraga_autopilot(run['id'])
        self.assertEqual('waiting_for_agents',current['status'])
        self.assertEqual(1,self.runtime.get_run(run['id'])['mahoragaAutopilot']['decisions'])

    def test_mahoraga_controller_caps_simultaneous_agents_at_four(self):
        tasks=[self.task(f'T0{i}') for i in range(1,6)]
        run=self.create_run(tasks)
        director=self.runtime.start_mahoraga_orchestrator(run['id'])
        session=self.runtime.state['sessions'][director['id']]
        session['status']='completed'
        session['proposal']={'summary':'Try too many concurrent agents.','actions':[
            {'action':'launch_test_designer','taskId':task['id'],'reason':'Check each task.'} for task in tasks]}
        result=self.runtime.apply_mahoraga_actions(director['id'])
        self.assertEqual(4,sum(item['status']=='accepted' for item in result['results']))
        self.assertEqual('AUTOPILOT_CONCURRENCY_LIMIT',result['results'][4]['code'])

    def test_test_designer_only_gets_spec_workspace(self):
        self.create_run()
        run_id = next(iter(self.runtime.state["runs"]))
        session = self.runtime.launch_agent(run_id, "T01", "test_designer")
        workdir = Path(session["cwd"])
        self.assertTrue((workdir / "TASK.md").is_file())
        self.assertFalse((workdir / "private_source.py").exists())
        self.assertNotIn("PRIVATE SOURCE", self.provider.sessions[session["threadId"]]["prompt"])

    def test_test_designer_receives_only_explicit_committed_mock_files(self):
        (self.project/'mocks').mkdir()
        (self.project/'mocks'/'spaces.json').write_text('[{"id":"s1"}]\n',encoding='utf-8')
        self.git('add','mocks/spaces.json');self.git('commit','-m','add approved fixture')
        run=self.create_run([self.task()|{'mocks':['mocks/spaces.json','mocks/missing.json']}])
        session=self.runtime.launch_agent(run['id'],'T01','test_designer')
        folder=Path(session['cwd'])
        self.assertEqual('[{"id":"s1"}]\n',(folder/'mocks'/'spaces.json').read_text(encoding='utf-8'))
        self.assertFalse((folder/'private_source.py').exists())
        self.assertIn('mocks/missing.json',(folder/'MOCKS.md').read_text(encoding='utf-8'))

    def test_reviewer_is_read_only_and_waits_for_builder_completion(self):
        self.create_run()
        run_id = next(iter(self.runtime.state["runs"]))
        self.prepare_test_design(run_id)
        self.runtime.create_task_worktree(run_id, "T01")
        builder = self.runtime.launch_agent(run_id, "T01", "builder")
        with self.assertRaises(AgentRuntimeError):
            self.runtime.launch_agent(run_id, "T01", "reviewer")
        self.provider.sessions[builder["threadId"]]["state"] = "completed"
        self.runtime.get_session(builder["id"])
        task=self.runtime._run(run_id)['tasks'][0]
        tree=Path(task['worktree']); (tree/'result.txt').write_text('ready\n',encoding='utf-8')
        from makora_core.agents.acceptance import snapshot, _suite
        _,_,_,digest=snapshot(self.runtime,run_id,'T01',['result.txt'])
        _,_,_,suite_digest=_suite(task)
        task['allowedPaths']=['result.txt']
        task['tests']={'status':'passed','independent':True,'digest':digest,'suiteDigest':suite_digest}
        task['status']='tests_passed'
        reviewer = self.runtime.launch_agent(run_id, "T01", "reviewer")
        self.assertEqual("readOnly", self.provider.sessions[reviewer["threadId"]]["sandbox"])
        self.assertIn("План тестирования, подготовленный отдельным агентом", self.provider.sessions[reviewer["threadId"]]["prompt"])
        self.assertIn("Done.", self.provider.sessions[reviewer["threadId"]]["prompt"])

    def test_user_changes_in_main_worktree_are_never_discarded(self):
        self.create_run()
        (self.project / "user.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(AgentRuntimeError, "незакоммиченные изменения"):
            self.create_run()

    def test_paths_outside_allowlist_are_denied(self):
        outside = self.base / "outside"
        outside.mkdir()
        self.git("status", "--porcelain")
        with self.assertRaises(AgentRuntimeError):
            self.runtime.create_run({"projectRoot": str(outside), "tasks": [self.task()]})

    def test_state_survives_controller_restart(self):
        run = self.create_run()
        restored = AgentRuntime(self.workspace, self.integration, [self.project], FakeProvider())
        self.assertEqual(run["id"], restored.get_run(run["id"])["id"])
        self.assertEqual(run["baseCommit"], restored.get_run(run["id"])["baseCommit"])

    def test_recovery_does_not_accept_an_unrelated_completed_turn(self):
        run = self.create_run()
        session = self.runtime.launch_agent(run["id"], "T01", "test_designer")
        self.provider.sessions[session["threadId"]]["state"] = "failed"
        self.provider.history = lambda _: {"turns": [{"id": "older-turn", "status": "completed"}]}
        self.assertEqual("failed", self.runtime.get_session(session["id"])["status"])

    def test_recovery_uses_exact_turn_when_operation_record_is_gone(self):
        run=self.create_run()
        session=self.runtime.launch_agent(run['id'],'T01','test_designer')
        spec=Path(session['cwd'])
        (spec/'TEST_DESIGN.md').write_text('independent tests',encoding='utf-8')
        (spec/'.makora-tests').mkdir()
        (spec/'.makora-tests'/'test_contract.py').write_text('import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n',encoding='utf-8')
        (spec/'test-manifest.json').write_text(json.dumps({'version':1,'framework':'unittest','files':['.makora-tests/test_contract.py'],'commands':[['python','-m','unittest','discover','-s','.makora-tests','-v']]}),encoding='utf-8')
        self.provider.operation=lambda _: (_ for _ in ()).throw(AgentRuntimeError('OPERATION_NOT_FOUND','expired',404))
        self.provider.history=lambda _: {'turns':[{'id':session['turnId'],'status':'completed','items':[{'type':'agentMessage','text':'Done.'}]}]}
        refreshed=self.runtime.get_session(session['id'])
        self.assertEqual('completed',refreshed['status'])
        self.assertEqual('completed',self.runtime._run(run['id'])['tasks'][0]['testDesignStatus'])

    def test_exact_completed_turn_overrides_stale_delivered_operation(self):
        run=self.create_run()
        session=self.prepare_test_design(run['id'])
        self.provider.sessions[session['threadId']]['state']='delivered'
        refreshed=self.runtime.get_session(session['id'])
        self.assertEqual('completed',refreshed['status'])
        self.assertEqual(session['turnId'],refreshed['turnId'])
        self.assertEqual('completed',self.runtime._run(run['id'])['tasks'][0]['testDesignStatus'])

    def test_diff_includes_staged_unstaged_and_untracked_paths(self):
        run = self.create_run()
        tree = Path(self.runtime.create_task_worktree(run["id"], "T01")["worktree"])
        (tree / "README.md").write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tree), "add", "README.md"], check=True)
        (tree / "README.md").write_text("unstaged\n", encoding="utf-8")
        (tree / "new.py").write_text("value = 1\n", encoding="utf-8")
        diff = self.runtime.run_diff(run["id"], "T01")
        self.assertIn("README.md", diff["changedFiles"])
        self.assertIn("new.py", diff["untrackedFiles"])
        self.assertIn("unstaged", diff["diff"])

    def test_run_diff_ignores_python_bytecode_but_keeps_source_changes(self):
        run = self.create_run()
        tree = Path(self.runtime.create_task_worktree(run["id"], "T01")["worktree"])
        (tree / "app").mkdir()
        (tree / "app" / "module.py").write_text("value = 1\n", encoding="utf-8")
        cache = tree / "app" / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-311.pyc").write_bytes(b"generated bytecode")

        diff = self.runtime.run_diff(run["id"], "T01")

        self.assertEqual(["app/module.py"], diff["changedFiles"])
        self.assertEqual(["app/module.py"], diff["untrackedFiles"])
        self.assertEqual(["app/__pycache__/module.cpython-311.pyc"], diff["ignoredGeneratedFiles"])
        self.assertNotIn("__pycache__", diff["diff"])

    def test_autopilot_does_not_approve_command_only_because_cwd_matches(self):
        run = self.create_run()
        task = self.runtime._run(run['id'])['tasks'][0]
        task['allowedPaths'] = ['result.txt']
        self.runtime._run(run['id'])['plannerSessionId'] = 'approved-plan'
        self.prepare_test_design(run['id'])
        self.runtime.create_task_worktree(run['id'], 'T01')
        builder = self.runtime.launch_agent(run['id'], 'T01', 'builder')
        self.runtime._ensure_autopilot_worker = lambda: None
        self.runtime.set_mahoraga_autopilot(run['id'], True)
        self.provider.pending_approvals = [
            {'requestId': 'one', 'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': builder['threadId'], 'turnId': builder['turnId'], 'cwd': builder['cwd'],
                'command': 'safe command in isolated worktree'}},
            {'requestId': 'unrelated', 'method': 'item/commandExecution/requestApproval', 'params': {
                'threadId': 'another-codex-thread', 'turnId': 'another-turn', 'cwd': builder['cwd']}},
        ]

        result = self.runtime._resolve_scoped_autopilot_approvals(run['id'])

        self.assertEqual({'accepted': 0, 'needsHuman': 1}, result)
        self.assertEqual([], self.provider.resolved_approvals)
        self.assertEqual('needs_human', self.runtime._run(run['id'])['mahoragaAutopilot']['status'])

    def test_autopilot_pauses_for_codex_approval_from_outside_worktree(self):
        run = self.create_run()
        task = self.runtime._run(run['id'])['tasks'][0]
        task['allowedPaths'] = ['result.txt']
        self.runtime._run(run['id'])['plannerSessionId'] = 'approved-plan'
        self.prepare_test_design(run['id'])
        self.runtime.create_task_worktree(run['id'], 'T01')
        builder = self.runtime.launch_agent(run['id'], 'T01', 'builder')
        self.runtime._ensure_autopilot_worker = lambda: None
        self.runtime.set_mahoraga_autopilot(run['id'], True)
        self.provider.pending_approvals = [{'requestId': 'outside', 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': builder['threadId'], 'turnId': builder['turnId'],
                       'cwd': str(self.project), 'command': 'unsafe outside worktree'}}]

        result = self.runtime._resolve_scoped_autopilot_approvals(run['id'])

        self.assertEqual({'accepted': 0, 'needsHuman': 1}, result)
        self.assertEqual([], self.provider.resolved_approvals)
        autopilot = self.runtime._run(run['id'])['mahoragaAutopilot']
        self.assertFalse(autopilot['enabled'])
        self.assertEqual('needs_human', autopilot['status'])

    def test_file_change_grant_root_alone_is_not_automatically_approved(self):
        run = self.create_run()
        task = self.runtime._run(run['id'])['tasks'][0]
        task['allowedPaths'] = ['result.txt']
        self.runtime._run(run['id'])['plannerSessionId'] = 'approved-plan'
        self.prepare_test_design(run['id'])
        self.runtime.create_task_worktree(run['id'], 'T01')
        builder = self.runtime.launch_agent(run['id'], 'T01', 'builder')
        self.runtime._ensure_autopilot_worker = lambda: None
        self.runtime.set_mahoraga_autopilot(run['id'], True)
        self.provider.pending_approvals = [{'requestId':'file', 'method':'item/fileChange/requestApproval',
            'params':{'threadId':builder['threadId'], 'turnId':builder['turnId'], 'grantRoot':builder['cwd']}}]
        self.assertEqual({'accepted':0, 'needsHuman':1}, self.runtime._resolve_scoped_autopilot_approvals(run['id']))
        self.assertEqual([], self.provider.resolved_approvals)

    def test_failed_independent_suite_can_be_regenerated_without_accepting_it(self):
        run = self.create_run()
        self.prepare_test_design(run['id'])
        task = self.runtime._run(run['id'])['tasks'][0]
        task.update(status='tests_failed', tests={'status':'failed', 'commands':[{'output':'recursive import'}]})
        self.assertIn('repair_test_design', self.runtime._mahoraga_allowed_actions(self.runtime._run(run['id']), task))
        session = self.runtime.repair_test_design(run['id'], 'T01', 'recursive import in suite')
        prompt = self.provider.sessions[session['threadId']]['prompt']
        self.assertIn('recursive import', prompt)
        self.assertEqual('failed', task['tests']['status'])
        self.assertEqual('running', task['testDesignStatus'])
        self.assertEqual([], self.runtime._mahoraga_allowed_actions(self.runtime._run(run['id']), task))
        spec = Path(session['cwd'])
        (spec/'TEST_DESIGN.md').write_text('Independent tests', encoding='utf-8')
        (spec/'tests').mkdir()
        (spec/'tests'/'test_fixed.py').write_text('def test_fixed(): pass', encoding='utf-8')
        (spec/'test-manifest.json').write_text(json.dumps({'version':1, 'framework':'unittest',
            'files':['tests/test_fixed.py'], 'commands':[['python','-m','unittest','discover','-s','.makora-tests']]}), encoding='utf-8')
        self.provider.sessions[session['threadId']]['state'] = 'completed'
        self.runtime.refresh_session(session['id'])
        self.assertEqual('review_pending', task['status'])
        self.assertIsNone(task['tests'])
        self.assertEqual(['run_tests'], self.runtime._mahoraga_allowed_actions(self.runtime._run(run['id']), task))

    def test_reviewer_unsupported_requirement_does_not_request_builder_changes(self):
        run = self.create_run()
        task = self.runtime._run(run['id'])['tasks'][0]
        task.update(status='reviewing', reviewDigest='digest', reviewSuiteDigest='suite')
        self.provider.sessions['review-thread'] = {'operation':'review-op', 'state':'completed'}
        self.runtime.state['sessions']['review-agent'] = {'id':'review-agent', 'role':'reviewer', 'taskId':'T01',
            'runId':run['id'], 'status':'running', 'threadId':'review-thread', 'operationId':'review-op', 'turnId':'review-turn'}
        response = {'verdict':'changes_requested', 'findings':[{'requirementQuote':'invented requirement', 'evidence':'missing'}]}
        self.provider.history = lambda _: {'turns':[{'id':'review-turn', 'status':'completed', 'items':[{'type':'agentMessage', 'text':json.dumps(response)}]}]}
        self.runtime.refresh_session('review-agent')
        self.assertEqual('review_unconfirmed', task['status'])

    def test_autopilot_queue_handles_null_test_and_review_artifacts_after_rebase(self):
        tasks = [self.task('T01') | {'allowedPaths': ['src/one.py']},
                 self.task('T02') | {'allowedPaths': ['src/two.py']}]
        run = self.runtime.create_run({'projectRoot': str(self.project), 'tasks': tasks})
        run_state = self.runtime._run(run['id'])
        self.runtime.create_task_worktree(run['id'], 'T01')
        run_state['tasks'][0].update(status='review_pending', tests=None, review=None)

        fingerprint = self.runtime._autopilot_queue_fingerprint(run_state)
        run_state['tasks'][0]['testDesignStatus'] = 'failed'
        run_state['tasks'][0]['testDesignerAttempts'] = 1
        first_failed_design = self.runtime._autopilot_queue_fingerprint(run_state)
        run_state['tasks'][0]['testDesignerAttempts'] = 2
        second_failed_design = self.runtime._autopilot_queue_fingerprint(run_state)
        run_state['tasks'][0]['testDesignStatus'] = None
        allowed = self.runtime._mahoraga_allowed_actions(run_state, run_state['tasks'][0])

        self.assertRegex(fingerprint, r'^[0-9a-f]{64}$')
        self.assertNotEqual(first_failed_design, second_failed_design)
        self.assertEqual(['run_tests'], allowed)

    def test_explicit_autopilot_restart_allows_reconsidering_current_queue(self):
        run = self.create_run()
        stored = self.runtime._run(run['id'])
        stored['plannerSessionId'] = 'approved-plan'
        stored['tasks'][0]['allowedPaths'] = ['result.txt']
        self.runtime._ensure_autopilot_worker = lambda: None
        fingerprint = self.runtime._autopilot_queue_fingerprint(stored)
        stored['mahoragaAutopilot'].update(status='paused', enabled=False, seenQueueFingerprints=[fingerprint, 'older'])
        self.runtime.set_mahoraga_autopilot(run['id'], True)
        self.assertEqual(['older'], stored['mahoragaAutopilot']['seenQueueFingerprints'])

    def test_autopilot_controller_rejection_is_feedback_for_one_correction(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.runtime.create_run({'projectRoot':str(self.project), 'tasks':[task]})
        run_state = self.runtime._run(run['id'])
        run_state['plannerSessionId'] = 'approved-planner'
        run_state['mahoragaAutopilot'] = {'enabled':True, 'status':'running', 'actions':0,
            'decisions':0, 'seenQueueFingerprints':[], 'correctionAttempts':1,
            'pendingRejections':[{'action':'request_fixes', 'taskId':task['id'], 'code':'ACTION_NOT_ALLOWED',
                                  'allowedActions':['refresh_task_base']}]}
        with_feedback = self.runtime._autopilot_queue_fingerprint(run_state)
        run_state['mahoragaAutopilot']['pendingRejections'] = []
        self.assertNotEqual(with_feedback, self.runtime._autopilot_queue_fingerprint(run_state))
        run_state['mahoragaAutopilot']['pendingRejections'] = [{'action':'request_fixes', 'taskId':task['id'],
            'code':'ACTION_NOT_ALLOWED', 'allowedActions':['refresh_task_base']}]
        session = self.runtime.start_mahoraga_orchestrator(run['id'])
        prompt = self.provider.sessions[session['threadId']]['prompt']
        self.assertIn('controllerFeedback', prompt)
        self.assertIn('refresh_task_base', prompt)
        self.assertIn('не повторяй их', prompt)

    def test_autopilot_recovers_unconfirmed_repeatable_test_action(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.runtime.create_run({'projectRoot':str(self.project), 'tasks':[task]})
        run_state = self.runtime._run(run['id'])
        run_state['plannerSessionId'] = 'approved-planner'
        run_state['mahoragaAutopilot'] = {'enabled':True, 'status':'running', 'actions':0,
                                          'decisions':0, 'seenQueueFingerprints':[]}
        session = self.runtime.start_mahoraga_orchestrator(run['id'])
        stored = self.runtime.state['sessions'][session['id']]
        stored.update(status='completed', proposal={'actions':[{'action':'run_tests','taskId':task['id']}],
                                                    'summary':'Run independent checks.'},
                      autoApplication='applying', autoApplicationStartedAt='old')
        with patch.object(self.runtime, 'apply_mahoraga_actions', return_value={'results':[
                {'status':'accepted','action':'run_tests','taskId':task['id']}]} ) as apply:
            result = self.runtime.advance_mahoraga_autopilot(run['id'])
        self.assertEqual('actions_applied', result['status'])
        apply.assert_called_once_with(session['id'])
        self.assertEqual('applied', self.runtime.state['sessions'][session['id']]['autoApplication'])

    def test_failed_builder_fix_delivery_preserves_review_and_retry_count(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.create_run([task])
        stored = self.runtime._run(run['id'])['tasks'][0]
        stored.update(status='changes_requested', repairAttempts=1, builderSessionId='builder-session',
                      review={'verdict':'changes_requested','findings':[{'issue':'Fix it.'}]},
                      tests={'status':'passed','digest':'prior'})
        with patch.object(self.runtime, 'send_message', side_effect=AgentRuntimeError(
                'CODEX_API_ERROR', 'thread already has an active writer', 502)):
            with self.assertRaises(AgentRuntimeError) as caught:
                self.runtime.request_builder_fixes(run['id'], task['id'])
        self.assertEqual('SESSION_BUSY', caught.exception.code)
        self.assertEqual('changes_requested', stored['status'])
        self.assertEqual(1, stored['repairAttempts'])
        self.assertEqual('changes_requested', stored['review']['verdict'])
        self.assertEqual('passed', stored['tests']['status'])

    def test_autopilot_restores_review_when_app_server_rejected_fix_delivery(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.create_run([task])
        stored_run = self.runtime._run(run['id'])
        stored = stored_run['tasks'][0]
        stored.update(status='implementing', repairAttempts=2, builderSessionId='builder-session',
                      reviewerSessionId='reviewer-session', tests=None, review=None)
        stored_run['mahoragaAutopilot'] = {'enabled':True, 'status':'running', 'pendingRejections':[
            {'action':'request_fixes','taskId':task['id'],'code':'CODEX_API_ERROR',
             'reason':'thread already has an active writer'}], 'correctionAttempts':2}
        self.runtime.state['sessions']['builder-session'] = {'id':'builder-session','role':'builder',
            'taskId':task['id'],'runId':run['id'],'status':'completed'}
        self.runtime.state['sessions']['reviewer-session'] = {'id':'reviewer-session','role':'reviewer',
            'taskId':task['id'],'runId':run['id'],'status':'completed','threadId':'review-thread',
            'result':{'turns':[{'items':[{'role':'assistant','text':json.dumps({
                'verdict':'changes_requested','findings':[{'issue':'Add a missing case.'}]})}]}]}}

        self.runtime._recover_undelivered_builder_fixes(stored_run)

        self.assertEqual('changes_requested', stored['status'])
        self.assertEqual(1, stored['repairAttempts'])
        self.assertEqual('review-thread', stored['review']['threadId'])
        self.assertTrue(stored['review']['recoveredAfterUndeliveredFix'])
        self.assertEqual([], stored_run['mahoragaAutopilot']['pendingRejections'])

    def test_autopilot_refreshes_completed_builder_when_task_status_is_stale(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.create_run([task])
        stored_run = self.runtime._run(run['id'])
        stored_run['plannerSessionId'] = 'approved-planner'
        self.runtime.create_task_worktree(run['id'], task['id'])
        stored = stored_run['tasks'][0]
        stored['testDesignStatus'] = 'completed'
        builder = self.runtime.launch_agent(run['id'], task['id'], 'builder')
        self.runtime._ensure_autopilot_worker = lambda: None
        self.runtime.set_mahoraga_autopilot(run['id'], True)

        result = self.runtime.advance_mahoraga_autopilot(run['id'])

        self.assertEqual('decision_requested', result['status'])
        self.assertEqual('review_pending', stored['status'])
        self.assertEqual('completed', self.runtime.state['sessions'][builder['id']]['status'])

    def test_autopilot_defers_builder_fix_when_app_server_reports_active_writer(self):
        task = self.task() | {'allowedPaths':['src/catalog.py']}
        run = self.create_run([task])
        state = self.runtime._run(run['id'])
        state['plannerSessionId'] = 'approved-planner'
        state['mahoragaAutopilot'] = {'enabled':True, 'status':'running', 'actions':0,
                                      'decisions':0, 'seenQueueFingerprints':[]}
        stored = state['tasks'][0]
        stored.update(status='changes_requested', builderSessionId='builder-session',
                      review={'verdict':'changes_requested','findings':[{'issue':'Fix.'}]})
        self.runtime.state['sessions']['builder-session'] = {'id':'builder-session','role':'builder',
            'taskId':task['id'],'runId':run['id'],'status':'completed'}
        director = self.runtime.start_mahoraga_orchestrator(run['id'])
        session = self.runtime.state['sessions'][director['id']]
        session.update(status='completed', proposal={'actions':[{'action':'request_fixes','taskId':task['id']}],
                                                     'summary':'Retry after writer completes.'})
        with patch.object(self.runtime, 'apply_mahoraga_actions', return_value={'results':[
                {'status':'rejected','action':'request_fixes','taskId':task['id'],'code':'SESSION_BUSY'}]}):
            result = self.runtime.advance_mahoraga_autopilot(run['id'])
        self.assertEqual('deferred_retry', result['status'])
        self.assertEqual('deferred', session['autoApplication'])
        self.assertNotIn('autopilotAppliedAt', session)

    def test_integration_rejects_missing_test_and_review_evidence(self):
        run = self.create_run()
        tree = Path(self.runtime.create_task_worktree(run['id'], 'T01')['worktree'])
        (tree/'result.py').write_text('value = 1\n',encoding='utf-8')
        self.runtime._run(run['id'])['tasks'][0]['allowedPaths']=['result.py']
        with self.assertRaisesRegex(AgentRuntimeError,'подтверждение'):
            self.runtime.integrate_task(run['id'],'T01',True)

    def test_acceptance_blocks_unapproved_files(self):
        from makora_core.agents.acceptance import snapshot
        run = self.create_run()
        tree = Path(self.runtime.create_task_worktree(run['id'], 'T01')['worktree'])
        (tree/'secret.key').write_text('not a real key',encoding='utf-8')
        with self.assertRaises(AgentRuntimeError):
            snapshot(self.runtime,run['id'],'T01',['secret.key'])

    def test_outdated_parallel_branch_is_refreshed_and_old_worktree_is_preserved(self):
        from makora_core.agents.acceptance import snapshot
        run = self.create_run()
        tree = Path(self.runtime.create_task_worktree(run['id'], 'T01')['worktree'])
        (tree/'result.py').write_text('value = 1\n',encoding='utf-8')
        task, _, _, digest = snapshot(self.runtime,run['id'],'T01',['result.py'])
        task.update(tests={'status':'passed','digest':digest},review={'verdict':'pass','digest':digest})
        (self.project/'other.py').write_text('other = 1\n',encoding='utf-8')
        self.git('add','other.py')
        self.git('commit','-m','other task')
        self.runtime._run(run['id'])['baseCommit']=self.git('rev-parse','HEAD')
        old_head=subprocess.run(['git','-C',str(tree),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
        refreshed=self.runtime.refresh_task_base(run['id'],'T01',allowed_paths=['result.py'])
        new_tree=Path(refreshed['worktree'])
        self.assertEqual(refreshed['baseCommit'], self.runtime._run_git(self.project,'rev-parse','HEAD'))
        self.assertEqual(old_head,subprocess.run(['git','-C',str(tree),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip())
        self.assertEqual('value = 1\n',(new_tree/'result.py').read_text(encoding='utf-8'))
        self.assertTrue((new_tree/'other.py').is_file())
        self.assertIsNone(task.get('tests'))
        self.assertIsNone(task.get('review'))

    def _exercise_parallel_worktrees_refresh_retest_and_integrate_sequentially(self, real_sandbox):
        """Exercise branch orchestration, optionally using the real Windows sandbox."""
        from makora_core.agents.acceptance import _suite, snapshot
        run=self.create_run([self.task('T01'),self.task('T02')])
        for ident in ('T01','T02'):
            self.prepare_test_design(run['id'],ident)
            self.runtime.create_task_worktree(run['id'],ident)
        tasks={item['id']:item for item in self.runtime._run(run['id'])['tasks']}
        roots={ident:Path(tasks[ident]['worktree']) for ident in tasks}
        (roots['T01']/'first.py').write_text('value = "first"\n',encoding='utf-8')
        (roots['T02']/'second.py').write_text('value = "second"\n',encoding='utf-8')

        def run_tests_and_approve(ident, file_name):
            task=tasks[ident]
            task['status']='review_pending'
            if real_sandbox:
                result=self.runtime.test_task(run['id'],ident,[file_name])
            else:
                # This is a controller/worktree unit test. Keep the real sandbox
                # mandatory in production and exercise it in the Windows-only
                # integration test below.
                _, _, _, digest=snapshot(self.runtime,run['id'],ident,[file_name])
                _, manifest, _, suite_digest=_suite(task)
                result={'status':'passed','independent':True,'framework':manifest['framework'],
                        'commands':[{'status':'passed','exitCode':0,'executedTests':1,'minimumTests':1}],
                        'digest':digest,'suiteDigest':suite_digest}
                task.update(status='tests_passed',tests=result,allowedPaths=[file_name])
            self.assertEqual('passed',result['status'],json.dumps(result,ensure_ascii=False))
            _,_,_,digest=snapshot(self.runtime,run['id'],ident,[file_name])
            _,_,_,suite_digest=_suite(task)
            task['review']={'verdict':'pass','digest':digest,'suiteDigest':suite_digest,'findings':[]}

        run_tests_and_approve('T01','first.py')
        first=self.runtime.integrate_task(run['id'],'T01',True)
        self.assertEqual('integrated',tasks['T01']['status'])

        with self.assertRaises(AgentRuntimeError) as stale_test:
            self.runtime.test_task(run['id'],'T02',['second.py'])
        self.assertEqual('TASK_BASE_OUTDATED',stale_test.exception.code)
        task_two=tasks['T02']
        task_two['status']='tests_passed'
        task_two['tests']={'status':'passed','independent':True}
        with self.assertRaises(AgentRuntimeError) as stale_review:
            self.runtime.launch_agent(run['id'],'T02','reviewer')
        self.assertEqual('TASK_BASE_OUTDATED',stale_review.exception.code)

        refreshed=self.runtime.refresh_task_base(run['id'],'T02',allowed_paths=['second.py'])
        roots['T02']=Path(refreshed['worktree'])
        self.assertEqual(first['commit'],refreshed['baseCommit'])
        self.assertTrue((roots['T02']/'first.py').is_file())
        self.assertEqual('value = "second"\n',(roots['T02']/'second.py').read_text(encoding='utf-8'))
        run_tests_and_approve('T02','second.py')
        second=self.runtime.integrate_task(run['id'],'T02',True)
        self.assertEqual('integrated',tasks['T02']['status'])
        self.assertEqual('value = "first"\n',(self.project/'first.py').read_text(encoding='utf-8'))
        self.assertEqual('value = "second"\n',(self.project/'second.py').read_text(encoding='utf-8'))
        self.assertNotEqual(first['commit'],second['commit'])

    def test_parallel_worktrees_refresh_retest_and_integrate_sequentially(self):
        self._exercise_parallel_worktrees_refresh_retest_and_integrate_sequentially(real_sandbox=False)

    @unittest.skipUnless(
        os.name == 'nt' and os.environ.get('CODEX_APP_SERVER_BINARY'),
        'Requires Windows and the configured Codex sandbox binary',
    )
    def test_parallel_worktrees_refresh_retest_and_integrate_sequentially_in_codex_sandbox(self):
        self._exercise_parallel_worktrees_refresh_retest_and_integrate_sequentially(real_sandbox=True)

    def test_independent_tests_remain_blocked_without_codex_sandbox(self):
        from unittest.mock import patch
        run=self.create_run()
        self.prepare_test_design(run['id'])
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'result.py').write_text('value = 1\n',encoding='utf-8')
        self.runtime._run(run['id'])['tasks'][0]['status']='review_pending'
        with patch.dict(os.environ, {'CODEX_APP_SERVER_BINARY':''}):
            with self.assertRaises(AgentRuntimeError) as caught:
                self.runtime.test_task(run['id'],'T01',['result.py'])
        self.assertEqual('SANDBOX_REQUIRED',caught.exception.code)
        self.assertNotEqual('tests_passed',self.runtime._run(run['id'])['tasks'][0]['status'])

    def test_independent_node_manifest_executes_in_actual_codex_sandbox(self):
        import os
        import shutil
        if os.name != 'nt' or not os.environ.get('CODEX_APP_SERVER_BINARY') or not shutil.which('node'):
            self.skipTest('Requires Windows, Codex sandbox, and Node.js')
        run=self.create_run()
        design=self.prepare_test_design(run['id'])
        spec=Path(design['cwd'])
        (spec/'tests'/'test_contract.py').unlink()
        (spec/'tests'/'contract.test.mjs').write_text(
            'import test from "node:test"; import assert from "node:assert/strict"; test("independent contract",()=>assert.equal(2+2,4));\n',
            encoding='utf-8')
        (spec/'test-manifest.json').write_text(json.dumps({'version':1,'framework':'node:test',
            'files':['tests/contract.test.mjs'],'commands':[['node','--test','.makora-tests/contract.test.mjs']]}),encoding='utf-8')
        valid,files,error=self.runtime._validate_test_design(spec)
        self.assertTrue(valid,error)
        task=self.runtime._run(run['id'])['tasks'][0]
        task['testDesignFiles']=files
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'result.js').write_text('export const value = 4;\n',encoding='utf-8')
        task['status']='review_pending'
        old_sandbox_root=os.environ.get('MAKORA_TEST_SANDBOX_ROOT')
        sandbox_root=Path(os.environ.get('CODEX_HOME',str(self.base)))/'tmp'/'makora-node-runner-tests'
        try:
            os.environ['MAKORA_TEST_SANDBOX_ROOT']=str(sandbox_root)
            result=self.runtime.test_task(run['id'],'T01',['result.js'])
        finally:
            if old_sandbox_root is None: os.environ.pop('MAKORA_TEST_SANDBOX_ROOT',None)
            else: os.environ['MAKORA_TEST_SANDBOX_ROOT']=old_sandbox_root
        self.assertEqual('passed',result['status'],json.dumps(result,ensure_ascii=False))
        self.assertEqual('node:test',result['framework'])
        self.assertEqual(0,result['commands'][0]['exitCode'])

    def test_parallel_conflict_uses_three_way_merge_and_never_overwrites_integrated_version(self):
        run=self.create_run()
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'README.md').write_text('agent version\n',encoding='utf-8')
        task=self.runtime._run(run['id'])['tasks'][0]
        task.update(status='tests_passed')
        (self.project/'README.md').write_text('integrated version\n',encoding='utf-8')
        self.git('add','README.md'); self.git('commit','-m','parallel integration')
        self.runtime._run(run['id'])['baseCommit']=self.git('rev-parse','HEAD')
        before=tree.joinpath('README.md').read_text(encoding='utf-8')
        result=self.runtime.refresh_task_base(run['id'],'T01',allowed_paths=['README.md'])
        self.assertEqual('conflict_resolution_required',result['status'])
        self.assertEqual(['README.md'],result['conflicts'])
        conflict_tree=Path(result['worktree'])
        self.assertIn('<<<<<<<',conflict_tree.joinpath('README.md').read_text(encoding='utf-8'))
        self.assertEqual('integrated version\n',(self.project/'README.md').read_text(encoding='utf-8'))
        self.assertEqual(before,tree.joinpath('README.md').read_text(encoding='utf-8'))
        task=self.runtime._run(run['id'])['tasks'][0]
        task.update(tests={'status':'passed'},review={'verdict':'pass'})
        (conflict_tree/'README.md').write_text('integrated version\nagent version\n',encoding='utf-8')
        subprocess.run(['git','-C',str(conflict_tree),'add','README.md'],check=True)
        resolved=self.runtime.resolve_task_conflicts(run['id'],'T01')
        self.assertEqual('resolved',resolved['status'])
        self.assertEqual('integrated version\nagent version\n',(conflict_tree/'README.md').read_text(encoding='utf-8'))
        self.assertEqual('review_pending',task['status'])
        self.assertIsNone(task.get('tests'))
        self.assertIsNone(task.get('review'))

    def test_parallel_refresh_rejects_claimed_conflict_resolution_without_three_way_review(self):
        run=self.create_run()
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'README.md').write_text('agent version\n',encoding='utf-8')
        (self.project/'README.md').write_text('integrated version\n',encoding='utf-8')
        self.git('add','README.md'); self.git('commit','-m','parallel integration')
        self.runtime._run(run['id'])['baseCommit']=self.git('rev-parse','HEAD')
        with self.assertRaises(AgentRuntimeError) as caught:
            self.runtime.refresh_task_base(run['id'],'T01',resolved_conflicts='README.md',allowed_paths=['README.md'])
        self.assertEqual('UNSAFE_CONFLICT_OVERRIDE',caught.exception.code)
        self.assertTrue(tree.exists())

    def test_independent_test_suite_requires_executable_files_and_rejects_shell(self):
        from makora_core.agents.runtime import AgentRuntime
        run=self.create_run()
        design=self.prepare_test_design(run['id'])
        task=self.runtime._run(run['id'])['tasks'][0]
        valid, files, error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertTrue(valid,error)
        self.assertEqual(['tests/test_contract.py'],files)
        design_path=Path(design['cwd'])/'TEST_DESIGN.md'
        original_design=design_path.read_text(encoding='utf-8')
        design_path.write_text('The contract does not specify an exact match rule; this suite checks only the stated behavior.\n',encoding='utf-8')
        valid,_,error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertTrue(valid,error)
        design_path.write_text('The schema uses explicit placeholders based on the requested field names.\n',encoding='utf-8')
        valid,_,error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertFalse(valid)
        self.assertIn('неподтверждённые',error)
        design_path.write_text(original_design,encoding='utf-8')
        from makora_core.agents.acceptance import _suite
        _,_,suite,suite_digest=_suite(task)
        self.assertIn('.makora-tests/context/TEST_DESIGN.md',suite)
        self.assertIn('.makora-tests/context/test-manifest.json',suite)
        self.assertEqual(64,len(suite_digest))
        manifest=Path(design['cwd'])/'test-manifest.json'
        (Path(design['cwd'])/'tests'/'test_contract.mjs').write_text('import test from "node:test"; import assert from "node:assert/strict"; test("contract",()=>assert.equal(1,1));\n',encoding='utf-8')
        manifest.write_text('{"version":1,"framework":"node:test","files":["tests/test_contract.mjs"],"commands":[["node","--test",".makora-tests/test_contract.mjs"]]}',encoding='utf-8')
        valid, files, error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertTrue(valid,error)
        self.assertEqual(['tests/test_contract.mjs'],files)
        manifest.write_text('{"version":1,"framework":"unittest","files":["tests/test_contract.py"],"commands":[["powershell","-Command","python test.py .makora-tests"]]}',encoding='utf-8')
        valid, _, error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertFalse(valid)
        self.assertIn('argv-массивом',error)
        self.assertEqual('completed',task['testDesignStatus'])

    def test_test_designer_manifest_may_list_metadata_but_runtime_keeps_only_suite_files(self):
        run=self.create_run()
        design=self.prepare_test_design(run['id'])
        spec=Path(design['cwd'])
        manifest=spec/'test-manifest.json'
        manifest.write_text(json.dumps({'version':1,'framework':'unittest','files':[
            'TEST_DESIGN.md','test-manifest.json','tests/test_contract.py'],
            'commands':[['python','-m','unittest','discover','-s','.makora-tests','-v']]}),encoding='utf-8')
        valid,files,error=self.runtime._validate_test_design(spec)
        self.assertTrue(valid,error)
        self.assertEqual(['tests/test_contract.py'],files)

    def test_runner_output_must_prove_at_least_one_test_executed(self):
        from makora_core.agents.acceptance import _executed_tests
        self.assertIsNone(_executed_tests('unittest','Ran 0 tests in 0.000s\n\nOK',{}))
        self.assertEqual(2,_executed_tests('unittest','Ran 2 tests in 0.002s\n\nOK',{}))
        self.assertEqual(6,_executed_tests('Python unittest','Ran 6 tests in 0.006s\n\nOK',{}))
        self.assertEqual(1,_executed_tests('node:test','TAP version 13\n# tests 1\n# pass 1\n# fail 0',{}))
        self.assertEqual(3,_executed_tests('cargo test','test result: ok. 3 passed; 0 failed; 0 ignored',{}))
        self.assertEqual(4,_executed_tests('custom runner','verified 4 specs',{'countPrefix':'verified'}))
        self.assertIsNone(_executed_tests('custom runner','all good',{}))

    def test_independent_suite_executes_in_actual_codex_sandbox(self):
        import os
        binary=os.environ.get('CODEX_APP_SERVER_BINARY')
        if os.name != 'nt' or not binary or not Path(binary).is_file():
            self.skipTest('Requires Windows and a configured CODEX_APP_SERVER_BINARY')
        run=self.create_run()
        design=self.runtime.launch_agent(run['id'],'T01','test_designer')
        spec=Path(design['cwd'])
        (spec/'TEST_DESIGN.md').write_text('# Independent contract\nadd returns the sum.\n',encoding='utf-8')
        (spec/'tests').mkdir()
        (spec/'tests'/'test_contract.py').write_text(
            'import sys, unittest\nsys.path.insert(0, ".")\nfrom result import add\n'
            'class Contract(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2, 3), 5)\n',encoding='utf-8')
        (spec/'test-manifest.json').write_text(json.dumps({'version':1,'framework':'unittest','files':['tests/test_contract.py'],
            'commands':[['python','-m','unittest','discover','-s','.makora-tests','-v']]}),encoding='utf-8')
        self.provider.sessions[design['threadId']]['state']='completed'
        self.runtime.get_session(design['id'])
        self.runtime.create_task_worktree(run['id'],'T01')
        task=self.runtime._run(run['id'])['tasks'][0]
        (Path(task['worktree'])/'result.py').write_text('def add(a, b):\n    return a + b\n',encoding='utf-8')
        task['status']='review_pending'
        evidence=self.runtime.test_task(run['id'],'T01',['result.py'])
        self.assertEqual('passed',evidence['status'],json.dumps(evidence,ensure_ascii=False))
        self.assertTrue(evidence['independent'])
        self.assertEqual(1,len(evidence['commands']))
        self.assertEqual(0,evidence['commands'][0]['exitCode'])

    def test_third_failed_review_cycle_routes_to_mahoraga(self):
        run=self.create_run()
        self.prepare_test_design(run['id'])
        self.runtime.create_task_worktree(run['id'],'T01')
        builder=self.runtime.launch_agent(run['id'],'T01','builder')
        task=self.runtime._run(run['id'])['tasks'][0]
        for attempt in range(1,4):
            task.update(status='changes_requested',review={'verdict':'changes_requested','findings':[{'issue':'fix'}]})
            self.provider.sessions[builder['threadId']]['state']='completed'
            self.runtime.state['sessions'][builder['id']]['status']='completed'
            result=self.runtime.request_builder_fixes(run['id'],'T01')
            self.assertEqual(attempt,result['attempt'])
            self.assertEqual('implementing',task['status'])
            self.provider.sessions[builder['threadId']]['state']='completed'
            self.runtime.refresh_session(builder['id'])
            if attempt < 3:
                task.update(status='changes_requested',review={'verdict':'changes_requested','findings':[{'issue':'still failing'}]})
        task.update(status='reviewing',repairAttempts=3,reviewDigest='code-digest',reviewSuiteDigest='suite-digest')
        self.provider.sessions['thread-final-review']={'operation':'operation-final-review','state':'completed'}
        reviewer_id='agent-final-review'
        self.runtime.state['sessions'][reviewer_id]={'id':reviewer_id,'role':'reviewer','taskId':'T01','runId':run['id'],
            'threadId':'thread-final-review','operationId':'operation-final-review','turnId':'turn-final-review','status':'running',
            'reviewDigest':'code-digest','reviewSuiteDigest':'suite-digest'}
        self.provider.history=lambda _: {'turns':[{'id':'turn-final-review','status':'completed','items':[{'type':'agentMessage','text':json.dumps({'verdict':'changes_requested','findings':[{'issue':'still failing','requirementQuote':'«The expected file exists.»','evidence':'file absent'}]})}]}]}
        self.runtime.refresh_session(reviewer_id)
        self.assertEqual('mahoraga_required',task['status'])
        specialist=self.runtime.launch_agent(run['id'],'T01','mahoraga')
        self.assertEqual('readOnly',self.provider.sessions[specialist['threadId']]['sandbox'])
        self.provider.history=FakeProvider.history.__get__(self.provider,FakeProvider)
        self.provider.sessions[specialist['threadId']]['state']='completed'
        self.runtime.refresh_session(specialist['id'])
        self.assertEqual('blocked_for_human',task['status'])

    def test_builder_followup_invalidates_acceptance_and_records_new_turn(self):
        run = self.create_run()
        self.prepare_test_design(run['id'])
        self.runtime.create_task_worktree(run['id'], 'T01')
        session = self.runtime.launch_agent(run['id'], 'T01', 'builder')
        self.provider.sessions[session['threadId']]['state']='completed'
        self.runtime.get_session(session['id'])
        task = self.runtime._run(run['id'])['tasks'][0]
        task.update(tests={'status':'passed'},review={'verdict':'pass'},reviewDigest='old')
        result=self.runtime.send_message(session['id'],'Исправь замечания')
        self.assertTrue(result['turnId'].startswith('new-turn'))
        self.assertEqual(task['status'],'implementing')
        self.assertNotIn('tests',task)
        self.assertNotIn('review',task)


if __name__ == "__main__":
    unittest.main()

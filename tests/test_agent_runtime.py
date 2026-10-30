from __future__ import annotations

import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from makora_core.agents.runtime import AgentRuntime, AgentRuntimeError, MODEL_ID


class FakeProvider:
    def __init__(self):
        self.sessions = {}
        self.next = 0

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

    def test_test_designer_only_gets_spec_workspace(self):
        self.create_run()
        run_id = next(iter(self.runtime.state["runs"]))
        session = self.runtime.launch_agent(run_id, "T01", "test_designer")
        workdir = Path(session["cwd"])
        self.assertTrue((workdir / "TASK.md").is_file())
        self.assertFalse((workdir / "private_source.py").exists())
        self.assertNotIn("PRIVATE SOURCE", self.provider.sessions[session["threadId"]]["prompt"])

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

    def test_parallel_worktrees_refresh_retest_and_integrate_sequentially(self):
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
            result=self.runtime.test_task(run['id'],ident,[file_name])
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

    def test_independent_node_manifest_executes_in_actual_codex_sandbox(self):
        import os
        import shutil
        if not os.environ.get('CODEX_APP_SERVER_BINARY') or not shutil.which('node'):
            self.skipTest('Requires Codex sandbox and Node.js')
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

    def test_parallel_same_file_is_reported_without_mutating_either_worktree(self):
        run=self.create_run()
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'README.md').write_text('agent version\n',encoding='utf-8')
        task=self.runtime._run(run['id'])['tasks'][0]
        task.update(status='tests_passed')
        (self.project/'README.md').write_text('integrated version\n',encoding='utf-8')
        self.git('add','README.md'); self.git('commit','-m','parallel integration')
        self.runtime._run(run['id'])['baseCommit']=self.git('rev-parse','HEAD')
        before=tree.joinpath('README.md').read_text(encoding='utf-8')
        with self.assertRaises(AgentRuntimeError) as caught:
            self.runtime.refresh_task_base(run['id'],'T01',allowed_paths=['README.md'])
        self.assertEqual('PARALLEL_CONFLICT',caught.exception.code)
        self.assertEqual(['README.md'],caught.exception.details['conflicts'])
        self.assertEqual(before,tree.joinpath('README.md').read_text(encoding='utf-8'))

    def test_parallel_refresh_rejects_malformed_conflict_resolution(self):
        run=self.create_run()
        tree=Path(self.runtime.create_task_worktree(run['id'],'T01')['worktree'])
        (tree/'README.md').write_text('agent version\n',encoding='utf-8')
        (self.project/'README.md').write_text('integrated version\n',encoding='utf-8')
        self.git('add','README.md'); self.git('commit','-m','parallel integration')
        self.runtime._run(run['id'])['baseCommit']=self.git('rev-parse','HEAD')
        with self.assertRaises(AgentRuntimeError) as caught:
            self.runtime.refresh_task_base(run['id'],'T01',resolved_conflicts='README.md',allowed_paths=['README.md'])
        self.assertEqual('INVALID_CONFLICT_RESOLUTION',caught.exception.code)
        self.assertTrue(tree.exists())

    def test_independent_test_suite_requires_executable_files_and_rejects_shell(self):
        from makora_core.agents.runtime import AgentRuntime
        run=self.create_run()
        design=self.prepare_test_design(run['id'])
        task=self.runtime._run(run['id'])['tasks'][0]
        valid, files, error=AgentRuntime._validate_test_design(Path(design['cwd']))
        self.assertTrue(valid,error)
        self.assertEqual(['tests/test_contract.py'],files)
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
        self.assertEqual(1,_executed_tests('node:test','TAP version 13\n# tests 1\n# pass 1\n# fail 0',{}))
        self.assertEqual(3,_executed_tests('cargo test','test result: ok. 3 passed; 0 failed; 0 ignored',{}))
        self.assertEqual(4,_executed_tests('custom runner','verified 4 specs',{'countPrefix':'verified'}))
        self.assertIsNone(_executed_tests('custom runner','all good',{}))

    def test_independent_suite_executes_in_actual_codex_sandbox(self):
        import os
        binary=os.environ.get('CODEX_APP_SERVER_BINARY')
        if not binary or not Path(binary).is_file():
            self.skipTest('CODEX_APP_SERVER_BINARY is not configured in this test process')
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
        self.provider.history=lambda _: {'turns':[{'id':'turn-final-review','status':'completed','items':[{'type':'agentMessage','text':'{"verdict":"changes_requested","findings":[{"issue":"still failing"}] }'}]}]}
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

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from makora_core.agents.runtime import AgentRuntime, AgentRuntimeError, MODEL_ID


class FakeProvider:
    def __init__(self):
        self.sessions = {}
        self.next = 0

    def status(self):
        return {"connected": True, "model": MODEL_ID, "modelAvailable": True}

    def create_thread(self, *, cwd, name, prompt, sandbox="workspaceWrite"):
        self.next += 1
        thread = f"thread-{self.next}"
        operation = f"operation-{self.next}"
        self.sessions[thread] = {"operation": operation, "state": "accepted", "cwd": cwd,
                                 "prompt": prompt, "sandbox": sandbox}
        return {"id": thread, "turnId": f"turn-{self.next}",
                "operation": {"id": operation, "state": "accepted"}}

    def operation(self, operation_id):
        item = next(item for item in self.sessions.values() if item["operation"] == operation_id)
        return {"id": operation_id, "state": item["state"]}

    def history(self, thread_id):
        return {"id": thread_id, "turns": [{"status": "completed", "items": [{"type": "agentMessage", "text": "Done."}]}]}

    def send(self, thread_id, text):
        return {"threadId": thread_id, "operation": {"id": "followup-1", "state": "accepted"}}

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


if __name__ == "__main__":
    unittest.main()

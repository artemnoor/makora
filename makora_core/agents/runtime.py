"""Safe local Codex sessions, task worktrees, and durable controller state."""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_ID = "gpt-6-luna"
API_BASE = "http://127.0.0.1:4182"
MAX_TASKS = 40


class AgentRuntimeError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodexLocalApi:
    """HTTP adapter for the vendored Codex Desktop API's documented App Server path."""

    def __init__(self, integration_dir: Path, workspace: Path):
        self.integration_dir = integration_dir
        self.workspace = workspace
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        token_file = self.workspace / "agents" / "local-api-token"
        try:
            self._token = token_file.read_text("ascii").strip()
        except OSError:
            self._token = secrets.token_urlsafe(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            try:
                descriptor = os.open(token_file, flags, 0o600)
                with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                    stream.write(self._token)
            except FileExistsError:
                self._token = token_file.read_text("ascii").strip()

    def _request(self, path: str, payload: dict | None = None, timeout: float = 8) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            API_BASE + path,
            data=data,
            headers={"Authorization": f"Bearer {self._token}", **({"Content-Type": "application/json"} if data is not None else {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
                if not isinstance(value, (dict, list)):
                    raise AgentRuntimeError("CODEX_API_INVALID", "Codex API returned an invalid response", 502)
                return value
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", "replace")
            try:
                parsed = json.loads(detail)
            except json.JSONDecodeError:
                parsed = {}
            if parsed.get("deliveryUnknown"):
                raise AgentRuntimeError("DELIVERY_UNKNOWN", "Codex не подтвердил доставку. Проверь историю перед повторной отправкой.", 409, parsed) from exc
            raise AgentRuntimeError("CODEX_API_ERROR", f"Codex API HTTP {exc.code}: {detail}", 502) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AgentRuntimeError("CODEX_UNAVAILABLE", "Не удалось подключиться к локальному Codex App Server.", 503) from exc
        except json.JSONDecodeError as exc:
            raise AgentRuntimeError("CODEX_API_INVALID", "Codex API returned non-JSON response", 502) from exc

    def ensure_started(self) -> None:
        try:
            status = self._request("/api/status")
            if status.get("ready"):
                return
        except AgentRuntimeError as exc:
            if exc.code != "CODEX_UNAVAILABLE":
                raise
        with self._lock:
            try:
                status = self._request("/api/status")
                if status.get("ready"):
                    return
            except AgentRuntimeError as exc:
                if exc.code != "CODEX_UNAVAILABLE":
                    raise
            script = self.integration_dir / "start-api.ps1"
            if not script.is_file():
                raise AgentRuntimeError("INTEGRATION_MISSING", "Vendored Codex API script is missing", 503)
            pwsh = shutil.which("pwsh")
            if not pwsh:
                raise AgentRuntimeError("POWERSHELL_MISSING", "PowerShell 7 (pwsh) is required for Codex integration", 503)
            log = self.workspace / "agents" / "codex-api.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            stream = open(log, "ab", buffering=0)
            env = os.environ.copy()
            env["CODEX_LOCAL_API_TOKEN"] = self._token
            args = [pwsh, "-NoLogo", "-NoProfile", "-File", str(script), "-AppServerOnly", "-Port", "4182", "-WorkingDirectory", str(self.integration_dir)]
            self._process = subprocess.Popen(args, cwd=self.integration_dir, env=env, stdin=subprocess.DEVNULL,
                                             stdout=stream, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                if self._request("/api/status").get("ready"):
                    return
            except AgentRuntimeError:
                pass
            if self._process and self._process.poll() is not None:
                raise AgentRuntimeError("CODEX_BRIDGE_EXITED", f"Codex API exited. See {log}", 503)
            time.sleep(0.2)
        raise AgentRuntimeError("CODEX_BRIDGE_TIMEOUT", f"Codex API did not become ready. See {log}", 503)

    def status(self) -> dict:
        self.ensure_started()
        status = self._request("/api/status")
        models = self._request("/api/models", timeout=15)
        catalog = models.get("data", [])
        luna = next((model for model in catalog if model.get("id") == MODEL_ID or model.get("model") == MODEL_ID), None)
        return {
            "connected": bool(status.get("ready")),
            "transport": "Codex App Server · persistent local threads",
            "appServerVersion": status.get("appServerVersion"),
            "model": MODEL_ID if luna else None,
            "modelAvailable": luna is not None,
            "availableModels": [m.get("id") or m.get("model") for m in catalog if isinstance(m, dict)],
            "desktopBridge": "not_used",
            "desktopVisibility": "App Server threads are persistent; Codex Desktop UI visibility is not guaranteed by this transport.",
        }

    def create_thread(self, *, cwd: Path, name: str, prompt: str, sandbox: str = "workspaceWrite") -> dict:
        self.ensure_started()
        status = self.status()
        if not status["modelAvailable"]:
            raise AgentRuntimeError("MODEL_UNAVAILABLE", f"Обязательная модель {MODEL_ID} недоступна в локальном каталоге Codex.", 409)
        sandbox_mode = {"workspaceWrite": "workspace-write", "readOnly": "read-only"}.get(sandbox)
        if sandbox_mode is None:
            raise AgentRuntimeError("INVALID_SANDBOX", "Unsupported Codex sandbox mode")
        root = str(cwd.resolve())
        if sandbox == "readOnly":
            sandbox_policy = {"type": "readOnly", "access": {
                "type": "restricted", "includePlatformDefaults": True, "readableRoots": [root]}}
        else:
            sandbox_policy = {"type": "workspaceWrite", "writableRoots": [root], "networkAccess": False,
                              "readOnlyAccess": {"type": "restricted", "includePlatformDefaults": True,
                                                 "readableRoots": [root]}}
        return self._request("/api/threads", {
            "transport": "app-server", "cwd": str(cwd), "model": MODEL_ID,
            "name": name[:100], "prompt": prompt, "sandbox": sandbox_mode,
            "approvalPolicy": "on-request", "sandboxPolicy": sandbox_policy,
        }, timeout=20)

    def send(self, thread_id: str, text: str) -> dict:
        self.ensure_started()
        return self._request(f"/api/threads/{thread_id}/messages", {"transport": "app-server", "text": text}, timeout=20)

    def operation(self, operation_id: str) -> dict:
        self.ensure_started()
        return self._request(f"/api/operations/{operation_id}")

    def history(self, thread_id: str) -> dict:
        self.ensure_started()
        return self._request(f"/api/threads/{thread_id}?tail=1", timeout=15)

    def approvals(self) -> list[dict]:
        self.ensure_started()
        value = self._request("/api/approvals")
        return value if isinstance(value, list) else []

    def resolve_approval(self, request_id: str, decision: str) -> dict:
        self.ensure_started()
        return self._request(f"/api/approvals/{request_id}", {"decision": decision})

    def close(self) -> None:
        process = self._process
        self._process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=5, check=False)


class AgentRuntime:
    def __init__(self, workspace: Path, integration_dir: Path, allowed_roots: list[Path] | None = None,
                 provider: CodexLocalApi | None = None):
        self.workspace = workspace.resolve()
        self.state_path = self.workspace / "agents" / "state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.integration_dir = integration_dir.resolve()
        self.allowed_roots = [p.resolve() for p in (allowed_roots or []) if p.exists()]
        self.worktrees_dir = self.workspace / "agents" / "worktrees"
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or CodexLocalApi(self.integration_dir, self.workspace)
        self._lock = threading.RLock()
        try:
            state = json.loads(self.state_path.read_text("utf-8"))
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("unsupported state")
        except (OSError, ValueError, json.JSONDecodeError):
            state = {"version": 1, "runs": {}, "sessions": {}, "events": []}
        state.setdefault("runs", {})
        state.setdefault("sessions", {})
        state.setdefault("events", [])
        self.state = state

    def _save(self) -> None:
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temp, self.state_path)

    def _event(self, kind: str, detail: str, run_id: str | None = None, task_id: str | None = None) -> None:
        self.state["events"].append({"id": str(uuid.uuid4()), "type": kind, "detail": detail,
                                     "runId": run_id, "taskId": task_id, "at": _now()})
        self.state["events"] = self.state["events"][-500:]

    def status(self) -> dict:
        try:
            provider = self.provider.status()
            return {**provider, "allowedRoots": [str(p) for p in self.allowed_roots], "maxParallel": 2,
                    "activeSessions": sum(x.get("status") in ("running", "accepted", "delivered") for x in self.state["sessions"].values())}
        except AgentRuntimeError as exc:
            return {"connected": False, "transport": "Codex App Server", "model": None,
                    "modelAvailable": False, "error": {"code": exc.code, "message": str(exc)},
                    "allowedRoots": [str(p) for p in self.allowed_roots], "maxParallel": 2}

    def _project_root(self, value: str) -> Path:
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AgentRuntimeError("PROJECT_NOT_FOUND", "Рабочая папка проекта не найдена.") from exc
        if not path.is_dir() or not any(path == root or root in path.parents for root in self.allowed_roots):
            raise AgentRuntimeError("PROJECT_ROOT_DENIED", "Путь не входит в разрешённые рабочие папки Макоры.", 403)
        if not (path / ".git").exists():
            raise AgentRuntimeError("GIT_REQUIRED", "Рабочая папка должна быть Git-репозиторием.")
        return path

    @staticmethod
    def _run_git(root: Path, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AgentRuntimeError("GIT_OPERATION_FAILED", result.stderr.strip() or "Git operation failed", 409)
        return result.stdout.strip()

    def create_run(self, payload: dict) -> dict:
        root = self._project_root(str(payload.get("projectRoot", "")))
        clean = self._run_git(root, "status", "--porcelain")
        if clean:
            raise AgentRuntimeError("PROJECT_DIRTY", "В основной рабочей папке есть незакоммиченные изменения. Сначала сохрани их, чтобы worktree строился от однозначной версии.", 409)
        tasks = payload.get("tasks")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
            raise AgentRuntimeError("INVALID_TASKS", f"Передай список из 1–{MAX_TASKS} задач.")
        seen: set[str] = set()
        normalized = []
        for task in tasks:
            if not isinstance(task, dict):
                raise AgentRuntimeError("INVALID_TASK", "Каждая задача должна быть объектом.")
            ident = str(task.get("id", ""))
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,39}", ident) or ident in seen:
                raise AgentRuntimeError("INVALID_TASK_ID", "ID задачи должен быть уникальным и содержать латинские буквы, цифры, _ или -.")
            seen.add(ident)
            normalized.append({"id": ident, "title": str(task.get("title", ""))[:160],
                               "goal": str(task.get("goal", ""))[:8000],
                               "acceptance": str(task.get("acceptance", ""))[:6000],
                               "dependsOn": task.get("dependsOn", []) if isinstance(task.get("dependsOn", []), list) else [],
                               "contracts": task.get("contracts", []) if isinstance(task.get("contracts", []), list) else [],
                               "mocks": task.get("mocks", []) if isinstance(task.get("mocks", []), list) else [],
                               "builderPrompt": str(task.get("builderPrompt", ""))[:16000],
                               "testPrompt": str(task.get("testPrompt", ""))[:12000],
                               "reviewerPrompt": str(task.get("reviewerPrompt", ""))[:12000],
                               "status": "pending", "worktree": None, "branch": None,
                               "builderSessionId": None, "reviewerSessionId": None, "integration": "not_integrated"})
        for task in normalized:
            if not task["title"] or not task["goal"] or not task["acceptance"]:
                raise AgentRuntimeError("TASK_FIELDS_REQUIRED", f"{task['id']}: нужны название, цель и критерии готовности.")
            if any(d not in seen or d == task["id"] for d in task["dependsOn"]):
                raise AgentRuntimeError("INVALID_DEPENDENCY", f"{task['id']}: зависимость отсутствует или указывает на саму задачу.")
        self._assert_acyclic(normalized)
        run_id = "run-" + uuid.uuid4().hex[:12]
        run = {"id": run_id, "projectRoot": str(root), "baseCommit": self._run_git(root, "rev-parse", "HEAD"),
               "createdAt": _now(), "maxParallel": 2, "tasks": normalized}
        with self._lock:
            self.state["runs"][run_id] = run
            self._event("run_created", f"План {run_id} создан для {root}", run_id)
            self._save()
        return self._public_run(run)

    @staticmethod
    def _assert_acyclic(tasks: list[dict]) -> None:
        by_id = {task["id"]: task for task in tasks}
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(ident: str) -> None:
            if ident in visiting:
                raise AgentRuntimeError("TASK_CYCLE", "Граф задач содержит цикл.")
            if ident in visited:
                return
            visiting.add(ident)
            for dependency in by_id[ident]["dependsOn"]:
                visit(dependency)
            visiting.remove(ident)
            visited.add(ident)
        for task in tasks:
            visit(task["id"])

    @staticmethod
    def _public_run(run: dict) -> dict:
        return {k: v for k, v in run.items() if k not in ("internal",)}

    def get_run(self, run_id: str) -> dict:
        run = self.state["runs"].get(run_id)
        if not run:
            raise AgentRuntimeError("RUN_NOT_FOUND", "Запуск не найден.", 404)
        return self._public_run(run)

    def _run(self, run_id: str) -> dict:
        run = self.state["runs"].get(run_id)
        if not run:
            raise AgentRuntimeError("RUN_NOT_FOUND", "Запуск не найден.", 404)
        return run

    def create_task_worktree(self, run_id: str, task_id: str) -> dict:
        with self._lock:
            run = self._run(run_id)
            task = next((item for item in run["tasks"] if item["id"] == task_id), None)
            if not task:
                raise AgentRuntimeError("TASK_NOT_FOUND", "Задача не найдена.", 404)
            if task["status"] != "pending":
                raise AgentRuntimeError("TASK_NOT_PENDING", "Задача уже запускалась; автоматически создавать повторную ветку запрещено.", 409)
            by_id = {item["id"]: item for item in run["tasks"]}
            waiting = [dep for dep in task["dependsOn"] if by_id[dep]["status"] != "integrated"]
            if waiting:
                raise AgentRuntimeError("TASK_BLOCKED", "Ожидает интеграции зависимостей: " + ", ".join(waiting), 409)
            root = Path(run["projectRoot"])
            branch = f"makora/{run_id}/{task_id}".lower()
            folder = self.worktrees_dir / run_id / task_id
            folder.parent.mkdir(parents=True, exist_ok=True)
            if folder.exists():
                raise AgentRuntimeError("WORKTREE_EXISTS", "Рабочая директория уже существует; сначала проверь и восстанови её состояние.", 409)
            self._run_git(root, "worktree", "add", "-b", branch, str(folder), run["baseCommit"])
            task.update({"status": "ready", "branch": branch, "worktree": str(folder), "startedAt": _now()})
            self._event("worktree_created", f"Создана отдельная Git-ветка {branch}", run_id, task_id)
            self._save()
            return {"taskId": task_id, "branch": branch, "worktree": str(folder), "baseCommit": run["baseCommit"], "gitStatus": self._run_git(folder, "status", "--short")}

    def launch_agent(self, run_id: str, task_id: str, role: str) -> dict:
        if role not in ("builder", "reviewer", "test_designer"):
            raise AgentRuntimeError("INVALID_ROLE", "Роль должна быть builder, reviewer или test_designer.")
        with self._lock:
            run = self._run(run_id)
            task = next((item for item in run["tasks"] if item["id"] == task_id), None)
            if not task:
                raise AgentRuntimeError("TASK_NOT_FOUND", "Задача не найдена.", 404)
            if role == "builder":
                if task["status"] != "ready" or not task["worktree"]:
                    raise AgentRuntimeError("TASK_NOT_READY", "Сначала подготовь отдельный worktree для доступной задачи.", 409)
                if task.get("testDesignStatus") != "completed":
                    raise AgentRuntimeError("TEST_DESIGN_REQUIRED", "Сначала заверши независимый Test Designer. Builder не запускается до фиксации тест-плана.", 409)
                if sum(1 for s in self.state["sessions"].values() if s.get("role") == "builder" and s.get("status") in ("accepted", "delivered", "running")) >= run["maxParallel"]:
                    raise AgentRuntimeError("PARALLEL_LIMIT", "Достигнут лимит параллельных Builder.", 409)
                cwd = Path(task["worktree"])
                prompt = self._builder_prompt(task, run)
                task["status"] = "implementing"
            elif role == "reviewer":
                if task["status"] != "review_pending" or not task.get("worktree"):
                    raise AgentRuntimeError("REVIEW_NOT_READY", "Reviewer запускается после завершения Builder и проверки фактического diff.", 409)
                cwd = Path(task["worktree"])
                prompt = self._reviewer_prompt(task, run)
                task["status"] = "reviewing"
            else:
                if task.get("testDesignerSessionId"):
                    raise AgentRuntimeError("TEST_DESIGN_EXISTS", "Сессия Test Designer уже сохранена. Не запускай её повторно без проверки истории.", 409)
                if task["status"] not in ("pending", "ready"):
                    raise AgentRuntimeError("TEST_DESIGN_NOT_READY", "Независимый Test Designer должен запускаться до Builder.", 409)
                spec_dir = self.worktrees_dir / run_id / f"{task_id}-test-spec"
                spec_dir.mkdir(parents=True, exist_ok=False)
                for file_name, content in (("TASK.md", self._task_spec(task)), ("CONTRACTS.md", "\n".join(task["contracts"])), ("ACCEPTANCE.md", task["acceptance"])):
                    (spec_dir / file_name).write_text(content, "utf-8")
                cwd = spec_dir
                prompt = (task["testPrompt"] or f"Подготовь независимые проверки для {task['id']} {task['title']}.") + "\n\nРеализацию не анализируй и не просматривай. Рабочая папка содержит только условие, контракты и критерии готовности. Создай TEST_DESIGN.md с тест-кейсами и ожидаемыми результатами; не добавляй исходный код."
                task["testDesignStatus"] = "running"
            agent_id = "agent-" + uuid.uuid4().hex[:12]
            self._event("agent_start_requested", f"Запрошен Codex {role} на {MODEL_ID}", run_id, task_id)
            self._save()
        try:
            created = self.provider.create_thread(cwd=cwd, name=f"Makora {role} {task_id}", prompt=prompt,
                                                  sandbox="readOnly" if role == "reviewer" else "workspaceWrite")
        except Exception as exc:
            with self._lock:
                uncertain = isinstance(exc, AgentRuntimeError) and exc.code == "DELIVERY_UNKNOWN"
                task["status"] = "unconfirmed" if uncertain else ("ready" if role == "builder" else ("review_pending" if role == "reviewer" else "pending"))
                task["deliveryUnknown"] = bool(uncertain)
                task["testDesignStatus"] = "failed" if role == "test_designer" else task.get("testDesignStatus")
                self._event("agent_start_failed", str(exc), run_id, task_id)
                self._save()
            raise
        thread_id = created.get("id")
        operation = created.get("operation") or {}
        if not thread_id or not operation.get("id"):
            raise AgentRuntimeError("SESSION_UNCONFIRMED", "Запрос принят без подтверждённых thread/operation ID. Не отправляй его повторно автоматически.", 502)
        session = {"id": agent_id, "role": role, "taskId": task_id, "runId": run_id,
                   "threadId": thread_id, "operationId": operation["id"], "model": MODEL_ID,
                   "cwd": str(cwd), "branch": task.get("branch"), "status": operation.get("state", "accepted"),
                   "createdAt": _now(), "lastCheckedAt": None, "result": None, "error": None,
                   "transport": "codex-app-server", "turnId": created.get("turnId")}
        with self._lock:
            self.state["sessions"][agent_id] = session
            if role == "builder": task["builderSessionId"] = agent_id
            elif role == "reviewer": task["reviewerSessionId"] = agent_id
            else: task["testDesignerSessionId"] = agent_id
            self._event("agent_created", f"{role} · thread {thread_id} · {MODEL_ID}", run_id, task_id)
            self._save()
        return dict(session)

    @staticmethod
    def _task_spec(task: dict) -> str:
        return f"# {task['id']} — {task['title']}\n\n## Цель\n{task['goal']}\n\n## Критерии готовности\n{task['acceptance']}\n"

    def _builder_prompt(self, task: dict, run: dict) -> str:
        return ((task["builderPrompt"] or f"Реализуй задачу {task['id']}: {task['goal']}") + "\n\n"
            f"Рабочий проект: {run['projectRoot']}\nЗадача работает в отдельном Git worktree: {task['worktree']}\n"
            f"Ветка: {task['branch']}\nИсходная ревизия: {run['baseCommit']}\n"
            f"Критерии готовности: {task['acceptance']}\nКонтракты: {json.dumps(task['contracts'], ensure_ascii=False)}\n"
            f"Доступные моки: {json.dumps(task['mocks'], ensure_ascii=False)}\n"
            "Не изменяй основную рабочую директорию или чужие worktree. Не интегрируй изменения и не выполняй destructive команды. "
            "После реализации сообщи изменённые файлы и точные команды проверки; не утверждай, что проверки прошли, если ты их не запускал.")

    def _reviewer_prompt(self, task: dict, run: dict) -> str:
        return ((task["reviewerPrompt"] or f"Проведи независимое code review задачи {task['id']}.") + "\n\n"
            f"Задача: {self._task_spec(task)}\nИсходная ревизия: {run['baseCommit']}\n"
            f"План тестирования, подготовленный отдельным агентом:\n{task.get('testDesignResult') or 'Результат не предоставлен.'}\n\n"
            "Проверь diff только для этой задачи, ограничения, контракты и критерии. Рабочая директория доступна только для чтения. "
            "Не изменяй код и не выполняй команды. Верни структурированный результат с полями: verdict (pass|changes_requested), "
            "findings (массив объектов severity, file, line, issue, recommendation), tests (массив {name,status,evidence}). "
            "Если тесты не запускались, явно поставь not_run и не выдумывай результаты.")

    def refresh_session(self, agent_id: str) -> dict:
        with self._lock:
            session = self.state["sessions"].get(agent_id)
            if not session:
                raise AgentRuntimeError("AGENT_NOT_FOUND", "Агент не найден.", 404)
            result = dict(session)
        try:
            operation = self.provider.operation(result["operationId"])
            state = operation.get("state", "unconfirmed")
            detail = operation.get("result") or operation.get("error")
            if state == "completed":
                detail = self.provider.history(result["threadId"])
            if state in ("unconfirmed", "failed"):
                # Operation records are in-memory in the bridge. On recovery, inspect persisted thread history
                # before deciding that the user prompt was lost; never resend automatically.
                history = self.provider.history(result["threadId"])
                turns = history.get("turns", [])
                if any(t.get("status") == "completed" for t in turns if isinstance(t, dict)):
                    state = "completed"
                    detail = history
        except AgentRuntimeError as exc:
            state = "unconfirmed"
            detail = {"code": exc.code, "message": str(exc)}
        with self._lock:
            session = self.state["sessions"][agent_id]
            session["status"] = state
            session["lastCheckedAt"] = _now()
            if state == "completed":
                session["result"] = detail
                task = self._task_for_session(session)
                if session["role"] == "builder" and task:
                    task["status"] = "review_pending"
                elif session["role"] == "reviewer" and task:
                    task["status"] = "review_completed"
                elif session["role"] == "test_designer" and task:
                    task["testDesignStatus"] = "completed"
                    task["testDesignResult"] = self._assistant_text(detail)
                self._event("agent_completed", f"{session['role']} thread {session['threadId']} завершил ответ", session.get("runId"), session.get("taskId"))
            elif state == "failed":
                session["error"] = detail
                task = self._task_for_session(session)
                if task and session["role"] == "builder": task["status"] = "failed"
                self._event("agent_failed", f"{session['role']} завершился ошибкой", session.get("runId"), session.get("taskId"))
            self._save()
            return dict(session)

    @staticmethod
    def _assistant_text(history: dict) -> str:
        """Extract visible response text without serializing unrelated thread metadata."""
        parts: list[str] = []

        def collect(value):
            if isinstance(value, dict):
                text = value.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
                for key, child in value.items():
                    if key != "text":
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        for turn in history.get("turns", []):
            for item in turn.get("items", []) if isinstance(turn, dict) else []:
                if isinstance(item, dict) and item.get("type") in {"agentMessage", "assistantMessage"}:
                    collect(item)
        return "\n\n".join(dict.fromkeys(parts))

    def _task_for_session(self, session: dict) -> dict | None:
        run = self.state["runs"].get(session.get("runId"))
        return next((task for task in run["tasks"] if task["id"] == session.get("taskId")), None) if run else None

    def run_diff(self, run_id: str, task_id: str) -> dict:
        run = self._run(run_id)
        task = next((item for item in run["tasks"] if item["id"] == task_id), None)
        if not task or not task.get("worktree"):
            raise AgentRuntimeError("WORKTREE_NOT_FOUND", "Для задачи нет worktree.", 404)
        root = Path(task["worktree"])
        return {"status": self._run_git(root, "status", "--short"),
                "diff": self._run_git(root, "diff", "--no-ext-diff", "--", "."),
                "changedFiles": self._run_git(root, "diff", "--name-only", "HEAD", "--", ".").splitlines(),
                "branch": task.get("branch"), "baseCommit": run["baseCommit"]}

    def get_session(self, agent_id: str, refresh: bool = True) -> dict:
        if refresh:
            return self.refresh_session(agent_id)
        with self._lock:
            session = self.state["sessions"].get(agent_id)
            if not session:
                raise AgentRuntimeError("AGENT_NOT_FOUND", "Агент не найден.", 404)
            return dict(session)

    def send_message(self, agent_id: str, text: str) -> dict:
        text = text.strip()
        if not text or len(text) > 12000:
            raise AgentRuntimeError("INVALID_MESSAGE", "Сообщение должно содержать от 1 до 12000 символов.")
        with self._lock:
            session = self.state["sessions"].get(agent_id)
            if not session:
                raise AgentRuntimeError("AGENT_NOT_FOUND", "Агент не найден.", 404)
            if session["status"] in ("accepted", "delivered", "running"):
                raise AgentRuntimeError("SESSION_BUSY", "В этом thread уже выполняется запрос.", 409)
            thread_id = session["threadId"]
        try:
            result = self.provider.send(thread_id, text)
        except AgentRuntimeError as exc:
            if exc.code == "DELIVERY_UNKNOWN":
                with self._lock:
                    session=self.state["sessions"][agent_id]
                    session["status"]="unconfirmed"
                    session["error"]={"code":exc.code,"message":str(exc)}
                    self._event("delivery_unconfirmed", f"Результат отправки в thread {thread_id} не подтверждён", session.get("runId"), session.get("taskId"))
                    self._save()
            raise
        operation = result.get("operation") or {}
        if not operation.get("id"):
            raise AgentRuntimeError("DELIVERY_UNKNOWN", "Ответ транспорта не подтвердил ID операции. Проверь историю thread перед повтором.", 502)
        with self._lock:
            session = self.state["sessions"][agent_id]
            session["operationId"] = operation["id"]
            session["status"] = operation.get("state", "accepted")
            session["lastMessageAt"] = _now()
            session["result"] = None
            session["error"] = None
            self._event("agent_message", f"Сообщение отправлено в thread {thread_id}", session.get("runId"), session.get("taskId"))
            self._save()
            return dict(session)

    def snapshot(self) -> dict:
        return {"runs": list(self.state["runs"].values()), "sessions": list(self.state["sessions"].values()),
                "events": list(reversed(self.state["events"][-100:]))}

    def approvals(self) -> list[dict]:
        try:
            return self.provider.approvals()
        except (AttributeError, AgentRuntimeError):
            return []

    def resolve_approval(self, request_id: str, decision: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", request_id) or decision not in ("accept", "decline"):
            raise AgentRuntimeError("INVALID_APPROVAL", "Некорректное подтверждение или решение.")
        resolver = getattr(self.provider, "resolve_approval", None)
        if not callable(resolver):
            raise AgentRuntimeError("APPROVALS_UNAVAILABLE", "Этот транспорт не поддерживает подтверждения.", 503)
        result = resolver(request_id, decision)
        with self._lock:
            self._event("approval_resolved", f"Запрос действий агента {request_id}: {decision}")
            self._save()
        return result

    def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()

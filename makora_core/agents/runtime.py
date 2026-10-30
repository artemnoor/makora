"""Safe local Codex sessions, task worktrees, and durable controller state."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
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


def _elapsed_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000))
    except (TypeError, ValueError):
        return None


class CodexLocalApi:
    """HTTP adapter for the vendored Codex Desktop API's documented App Server path."""

    def __init__(self, integration_dir: Path, workspace: Path):
        self.integration_dir = integration_dir
        self.workspace = workspace
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self._port = listener.getsockname()[1]
        self._base = f'http://127.0.0.1:{self._port}'
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
            self._base + path,
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
            if 'cannot enforce split filesystem read restrictions' in str(parsed.get('error', '')):
                raise AgentRuntimeError('SANDBOX_UNAVAILABLE', 'Windows unelevated sandbox не поддерживает изоляцию чтения. Настрой MXC, elevated sandbox или отдельную Linux-среду. Запуск без изоляции заблокирован.', 503) from exc
            if parsed.get("deliveryUnknown") or parsed.get("threadId"):
                raise AgentRuntimeError("DELIVERY_UNKNOWN", "Codex не подтвердил доставку. Проверь историю перед повторной отправкой.", 409, parsed) from exc
            raise AgentRuntimeError("CODEX_API_ERROR", f"Codex API HTTP {exc.code}: {detail}", 502) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if data is not None:
                raise AgentRuntimeError('DELIVERY_UNKNOWN', 'Соединение потеряно после отправки. Результат неизвестен; автоматический повтор запрещён.', 409) from exc
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
            args = [pwsh, "-NoLogo", "-NoProfile", "-File", str(script), "-AppServerOnly", "-Port", str(self._port), "-WorkingDirectory", str(self.integration_dir)]
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

    def create_thread(self, *, cwd: Path, name: str, prompt: str, sandbox: str = "workspaceWrite", denied_paths: list[str] | None = None) -> dict:
        self.ensure_started()
        status = self.status()
        if not status["modelAvailable"]:
            raise AgentRuntimeError("MODEL_UNAVAILABLE", f"Обязательная модель {MODEL_ID} недоступна в локальном каталоге Codex.", 409)
        sandbox_mode = {"workspaceWrite": "workspace-write", "readOnly": "read-only"}.get(sandbox)
        if sandbox_mode is None:
            raise AgentRuntimeError("INVALID_SANDBOX", "Unsupported Codex sandbox mode")
        root = str(cwd.resolve())
        filesystem = {":root": "read", str(self.workspace / 'agents' / 'local-api-token'): "deny"}
        for run_folder in (self.workspace / 'agents' / 'worktrees').glob('*'):
            for sibling in run_folder.iterdir():
                if sibling.resolve() != cwd.resolve():
                    filesystem[str(sibling.resolve())] = "deny"
        filesystem.update({str(Path(p).resolve()): "deny" for p in (denied_paths or [])})
        filesystem[root] = "read" if sandbox == "readOnly" else "write"
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
            "approvalPolicy": "on-request", "permissions": "makora",
            "config": {"permissions.makora": {"filesystem": filesystem, "network": {"enabled": False}}},
        }, timeout=100)

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
            for field in ('dependsOn','contracts','mocks'):
                values = task.get(field,[])
                if not isinstance(values,list) or not all(isinstance(value,str) for value in values):
                    raise AgentRuntimeError('INVALID_TASK_FIELD', f'{ident}: {field} должен быть списком строк.')
            normalized.append({"id": ident, "title": str(task.get("title", ""))[:160],
                               "goal": str(task.get("goal", ""))[:8000],
                               "acceptance": str(task.get("acceptance", ""))[:6000],
                               "dependsOn": task.get("dependsOn", []),
                               "contracts": task.get("contracts", []),
                               "mocks": task.get("mocks", []),
                               "builderPrompt": str(task.get("builderPrompt", ""))[:16000],
                               "testPrompt": str(task.get("testPrompt", ""))[:12000],
                               "reviewerPrompt": str(task.get("reviewerPrompt", ""))[:12000],
                               "status": "pending", "worktree": None, "branch": None,
                               "builderSessionId": None, "reviewerSessionId": None, "integration": "not_integrated",
                               "repairAttempts": 0, "testDesignDir": None, "testDesignFiles": []})
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

    def start_mahoraga_planning(self, payload: dict) -> dict:
        """Ask the chief Codex agent to turn supplied case materials into a validated task DAG."""
        root = self._project_root(str(payload.get('projectRoot', '')))
        brief = payload.get('brief')
        context = payload.get('context', '')
        if not isinstance(brief, str) or not brief.strip() or len(brief) > 30_000:
            raise AgentRuntimeError('PLAN_BRIEF_REQUIRED', 'Передай условие или описание задачи длиной до 30000 символов.')
        if not isinstance(context, str) or len(context) > 60_000:
            raise AgentRuntimeError('PLAN_CONTEXT_INVALID', 'Дополнительный контекст должен быть текстом не длиннее 60000 символов.')
        plan_id = 'plan-' + uuid.uuid4().hex[:12]
        folder = (self.worktrees_dir.parent / 'plans' / plan_id).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'BRIEF.md').write_text(brief.strip() + '\n', encoding='utf-8')
        (folder / 'PROJECT_CONTEXT.md').write_text(context.strip() + '\n', encoding='utf-8')
        prompt = (
            'Ты — Махорага, главный технический агент Макоры. Независимо декомпозируй кейс на исполняемые задачи для Builder. '
            'Изучи BRIEF.md и PROJECT_CONTEXT.md в рабочей папке. Не выдумывай подтверждённые факты; неизвестное помечай в risks/openQuestions. '
            'Сформируй максимально практичный DAG задач. Для каждой задачи обязательны id, title, goal, acceptance, dependsOn, contracts, '
            'mocks, builderPrompt, testPrompt, reviewerPrompt. Не включай тестирование только в финальную задачу: каждая задача должна иметь '
            'собственные acceptance-критерии и независимый тест-дизайн; интеграционные/E2E задачи добавь отдельно при необходимости. '
            'Ограничь план 40 задачами и не запускай Builder. Верни только JSON-объект формы '
            '{"summary":"...","tasks":[...],"risks":[...],"openQuestions":[...],"queueStrategy":"..."}. '
            'Задачи должны ссылаться только на существующие ID зависимостей, без циклов. Макора проверит этот граф и оставит запуск человеку.'
        )
        try:
            created = self.provider.create_thread(cwd=folder, name='Makora Mahoraga project planning', prompt=prompt,
                                                  sandbox='workspaceWrite', denied_paths=[root])
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        thread_id = created.get('id')
        operation = created.get('operation') or {}
        if not thread_id or not operation.get('id'):
            raise AgentRuntimeError('SESSION_UNCONFIRMED', 'Планировщик создан без подтверждённых thread/operation ID.', 502)
        agent_id = 'agent-' + uuid.uuid4().hex[:12]
        session = {'id': agent_id, 'role': 'mahoraga_planner', 'taskId': None, 'runId': None,
                   'threadId': thread_id, 'operationId': operation['id'], 'turnId': created.get('turnId'),
                   'model': MODEL_ID, 'cwd': str(folder), 'projectRoot': str(root), 'planId': plan_id,
                   'status': operation.get('state', 'accepted'), 'createdAt': _now(), 'lastCheckedAt': None,
                   'result': None, 'proposal': None, 'error': None, 'transport': 'codex-app-server'}
        with self._lock:
            self.state['sessions'][agent_id] = session
            self._event('mahoraga_planning_started', f'Махорага готовит план для {root}')
            self._save()
        return dict(session)

    def start_mahoraga_orchestrator(self, run_id: str) -> dict:
        """Ask Mahoraga to inspect the current queue and propose controller-gated actions."""
        with self._lock:
            run = self._run(run_id)
            active = next((s for s in self.state['sessions'].values()
                           if s.get('runId') == run_id and s.get('role') == 'mahoraga_orchestrator'
                           and s.get('status') in ('accepted', 'delivered', 'running', 'unconfirmed')), None)
            if active:
                raise AgentRuntimeError('ORCHESTRATOR_BUSY', 'Махорага уже анализирует очередь этого запуска.', 409)
            folder = (self.worktrees_dir.parent / 'orchestrator' / run_id / uuid.uuid4().hex[:8]).resolve()
            folder.mkdir(parents=True, exist_ok=False)
            task_view = []
            for task in run['tasks']:
                item = {k:task.get(k) for k in ('id','title','goal','acceptance','dependsOn','contracts','mocks','status','worktree','worktreeBase','testDesignStatus','tests','review','repairAttempts','allowedPaths')}
                item['controllerAllowedActions'] = self._mahoraga_allowed_actions(run,task)
                task_view.append(item)
            (folder / 'RUN_PLAN.json').write_text(json.dumps({'runId':run_id,'baseCommit':run['baseCommit'],'tasks':task_view}, ensure_ascii=False, indent=2), 'utf-8')
            prompt = (
                'Ты — Махорага, главный агент-координатор разработки Макоры. Изучи приложенный актуальный план запуска и предложи следующий безопасный набор действий. '
                'Ты не запускаешь инструменты и не меняешь файлы; контроллер исполнит только допустимые действия. '
                'Верни только JSON: {"summary":"...","actions":[{"action":"prepare_worktree|launch_test_designer|launch_builder|run_tests|launch_reviewer|request_fixes|recommend_integration|ask_human","taskId":"T01","reason":"..."}],"openQuestions":[]}. '
                'Действуй по зависимостям; одновременно допускай максимум двух Builder. Для run_tests поле allowedPaths не указывай: контроллер выведет список изменённых файлов сам. '
                'Используй taskId буквально из плана и предлагай только действия из controllerAllowedActions для конкретной задачи. '
                'Если список пуст, предложи ask_human с реальным вопросом, не повторяй уже выполненное действие. Интеграцию только рекомендуй: окончательное подтверждение всегда даёт человек. '
                '\n\nАКТУАЛЬНЫЙ ПЛАН И СТАТУСЫ ЗАДАЧ:\n' + json.dumps({'runId':run_id,'baseCommit':run['baseCommit'],'tasks':task_view},ensure_ascii=False)
            )
            self._save()
        try:
            created = self.provider.create_thread(cwd=folder, name=f'Makora Mahoraga queue {run_id}', prompt=prompt,
                                                  sandbox='readOnly', denied_paths=[run['projectRoot']])
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        thread_id = created.get('id')
        operation = created.get('operation') or {}
        if not thread_id or not operation.get('id'):
            raise AgentRuntimeError('SESSION_UNCONFIRMED', 'Координатор создан без подтверждённых thread/operation ID.', 502)
        agent_id = 'agent-' + uuid.uuid4().hex[:12]
        session = {'id':agent_id,'role':'mahoraga_orchestrator','taskId':None,'runId':run_id,'threadId':thread_id,
                   'operationId':operation['id'],'turnId':created.get('turnId'),'model':MODEL_ID,'cwd':str(folder),
                   'status':operation.get('state','accepted'),'createdAt':_now(),'lastCheckedAt':None,
                   'result':None,'proposal':None,'error':None,'transport':'codex-app-server'}
        with self._lock:
            self.state['sessions'][agent_id] = session
            self._event('mahoraga_queue_analysis_started', f'Махорага анализирует очередь запуска {run_id}', run_id)
            self._save()
        return dict(session)

    def _mahoraga_allowed_actions(self, run: dict, task: dict) -> list[str]:
        by_id = {item['id']:item for item in run['tasks']}
        if any(by_id[dependency]['status'] != 'integrated' for dependency in task['dependsOn']):
            return []
        status = task.get('status')
        has_designer = bool(task.get('testDesignerSessionId'))
        has_builder = bool(task.get('builderSessionId'))
        if status == 'pending':
            actions=[]
            if not task.get('worktree'):
                actions.append('prepare_worktree')
            if not has_designer:
                actions.append('launch_test_designer')
            return actions
        if status == 'ready':
            if task.get('testDesignStatus') == 'completed' and not has_builder:
                return ['launch_builder']
            if not has_designer:
                return ['launch_test_designer']
            return []
        if status in ('review_pending','review_completed','tests_failed','changes_requested','review_unconfirmed'):
            if task.get('tests',{}).get('status') != 'passed':
                return ['run_tests']
        if status == 'tests_passed':
            return ['launch_reviewer']
        if status == 'changes_requested':
            return ['request_fixes']
        if status == 'review_completed' and task.get('review',{}).get('verdict') == 'pass':
            return ['recommend_integration']
        if status == 'rebase_conflict':
            return ['ask_human']
        return []

    @staticmethod
    def _extract_json_object(text: str) -> dict:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != '{':
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
        raise AgentRuntimeError('AGENT_JSON_INVALID', 'Ответ агента не содержит корректный JSON-объект.', 409)

    def approve_mahoraga_plan(self, agent_id: str) -> dict:
        with self._lock:
            session = self.state['sessions'].get(agent_id)
            if not session or session.get('role') != 'mahoraga_planner':
                raise AgentRuntimeError('PLAN_SESSION_NOT_FOUND', 'Сессия планирования Махораги не найдена.', 404)
            if session.get('status') != 'completed' or not isinstance(session.get('proposal'), dict):
                raise AgentRuntimeError('PLAN_NOT_READY', 'Сначала получи и проверь завершённый план Махораги.', 409)
            if session.get('approvedRunId'):
                return self.get_run(session['approvedRunId'])
            proposal = session['proposal']
            root = session['projectRoot']
            if not isinstance(proposal.get('tasks'), list):
                raise AgentRuntimeError('PLAN_INVALID', 'В плане отсутствует список задач.', 409)
            tasks = []
            for raw in proposal['tasks']:
                if not isinstance(raw,dict):
                    raise AgentRuntimeError('PLAN_INVALID','Каждая задача должна быть JSON-объектом.',409)
                item = dict(raw)
                acceptance = item.get('acceptance')
                if isinstance(acceptance,list) and all(isinstance(line,str) for line in acceptance):
                    item['acceptance'] = '\n'.join(f'- {line}' for line in acceptance)
                if not all(isinstance(item.get(name),str) for name in ('id','title','goal','acceptance')):
                    raise AgentRuntimeError('PLAN_INVALID','У каждой задачи id, title, goal и acceptance должны быть текстом.',409)
                for name in ('dependsOn','contracts','mocks'):
                    value = item.get(name,[])
                    if not isinstance(value,list) or not all(isinstance(entry,str) for entry in value):
                        raise AgentRuntimeError('PLAN_INVALID',f'{item["id"]}: {name} должен быть списком строк.',409)
                for name in ('builderPrompt','testPrompt','reviewerPrompt'):
                    if name in item and not isinstance(item[name],str):
                        raise AgentRuntimeError('PLAN_INVALID',f'{item["id"]}: {name} должен быть текстом.',409)
                tasks.append(item)
            proposal['tasks'] = tasks
        run = self.create_run({'projectRoot':root,'tasks':tasks})
        with self._lock:
            session = self.state['sessions'][agent_id]
            run_obj = self._run(run['id'])
            run_obj['mahoragaPlan'] = {k:proposal.get(k) for k in ('summary','risks','openQuestions','queueStrategy')}
            run_obj['plannerSessionId'] = agent_id
            session['approvedRunId'] = run['id']
            self._event('mahoraga_plan_approved', 'План Махораги прошёл проверки DAG и утверждён пользователем.', run['id'])
            self._save()
            return self._public_run(run_obj)

    def apply_mahoraga_actions(self, agent_id: str) -> dict:
        """Validate every proposed action against live controller state before executing it."""
        with self._lock:
            session = self.state['sessions'].get(agent_id)
            if not session or session.get('role') != 'mahoraga_orchestrator':
                raise AgentRuntimeError('ORCHESTRATOR_SESSION_NOT_FOUND', 'Сессия координации Махораги не найдена.', 404)
            if session.get('status') != 'completed' or not isinstance(session.get('proposal'), dict):
                raise AgentRuntimeError('ORCHESTRATOR_NOT_READY', 'Сначала получи завершённые рекомендации Махораги.', 409)
            proposal = session['proposal']
            actions = proposal.get('actions')
            if not isinstance(actions, list) or len(actions) > 12:
                raise AgentRuntimeError('ORCHESTRATOR_ACTIONS_INVALID', 'Ожидался список не более чем из 12 действий.', 409)
            run_id = session['runId']
        results = []
        allowed_actions = {'prepare_worktree','launch_test_designer','launch_builder','run_tests','launch_reviewer','request_fixes','recommend_integration','ask_human'}
        for item in actions:
            if not isinstance(item, dict) or item.get('action') not in allowed_actions or not isinstance(item.get('taskId'), str):
                results.append({'status':'rejected','action':item,'reason':'Неизвестное действие или отсутствует taskId.'})
                continue
            action, task_id = item['action'], item['taskId']
            try:
                run = self._run(run_id)
                task = next((t for t in run['tasks'] if t['id'] == task_id), None)
                if not task:
                    raise AgentRuntimeError('TASK_NOT_FOUND', 'Задача не принадлежит этому запуску.', 404)
                permitted = self._mahoraga_allowed_actions(run,task)
                if action != 'ask_human' and action not in permitted:
                    raise AgentRuntimeError('ACTION_NOT_ALLOWED', 'Контроллер не разрешает это действие в текущем состоянии задачи.', 409,
                                            {'allowedActions':permitted})
                if action == 'prepare_worktree':
                    outcome = self.create_task_worktree(run_id,task_id)
                elif action == 'launch_test_designer':
                    outcome = self.launch_agent(run_id,task_id,'test_designer')
                elif action == 'launch_builder':
                    outcome = self.launch_agent(run_id,task_id,'builder')
                elif action == 'run_tests':
                    paths = self.run_diff(run_id,task_id)['changedFiles']
                    if not paths:
                        raise AgentRuntimeError('NO_CHANGES','В задаче нет изменений для тестирования.',409)
                    outcome = self.test_task(run_id,task_id,paths)
                elif action == 'launch_reviewer':
                    outcome = self.launch_agent(run_id,task_id,'reviewer')
                elif action == 'request_fixes':
                    outcome = self.request_builder_fixes(run_id,task_id)
                elif action == 'recommend_integration':
                    if task.get('status') != 'review_completed' or task.get('review',{}).get('verdict') != 'pass':
                        raise AgentRuntimeError('INTEGRATION_GATE','Рекомендация допустима только после успешного Reviewer.',409)
                    task['integrationRecommendation'] = {'recommended':True,'reason':str(item.get('reason',''))[:1000],'at':_now()}
                    self._event('mahoraga_recommended_integration','Махорага рекомендует интеграцию; ожидается подтверждение человека.',run_id,task_id)
                    self._save()
                    outcome = {'status':'human_confirmation_required'}
                else:
                    question = str(item.get('reason',''))[:1000]
                    task['humanQuestion'] = {'question':question,'at':_now(),'source':'mahoraga'}
                    self._event('mahoraga_asked_human',question or 'Махорага запросила решение человека.',run_id,task_id)
                    self._save()
                    outcome = {'status':'human_attention_required','reason':question}
                results.append({'status':'accepted','action':action,'taskId':task_id,'result':outcome})
            except AgentRuntimeError as exc:
                results.append({'status':'rejected','action':action,'taskId':task_id,'code':exc.code,'reason':str(exc),'details':exc.details})
        with self._lock:
            session = self.state['sessions'][agent_id]
            session['actionResults'] = results
            self._event('mahoraga_actions_validated', f'Контроллер разрешил {sum(r["status"]=="accepted" for r in results)} из {len(results)} рекомендаций.', run_id)
            self._save()
        return {'results':results,'summary':proposal.get('summary',''),'openQuestions':proposal.get('openQuestions',[])}

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
            task.update({"status": "ready", "branch": branch, "worktree": str(folder), "worktreeBase": run["baseCommit"], "startedAt": _now()})
            self._event("worktree_created", f"Создана отдельная Git-ветка {branch}", run_id, task_id)
            self._save()
            return {"taskId": task_id, "branch": branch, "worktree": str(folder), "baseCommit": run["baseCommit"], "gitStatus": self._run_git(folder, "status", "--short")}

    def launch_agent(self, run_id: str, task_id: str, role: str) -> dict:
        if role not in ("builder", "reviewer", "test_designer", "mahoraga"):
            raise AgentRuntimeError("INVALID_ROLE", "Роль должна быть builder, reviewer, test_designer или mahoraga.")
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
                if task["status"] not in ("tests_passed",) or not task.get("worktree") or task.get('tests',{}).get('status') != 'passed':
                    raise AgentRuntimeError("REVIEW_NOT_READY", "Reviewer запускается только после прохождения независимых тестов.", 409)
                if task.get('worktreeBase', run['baseCommit']) != run['baseCommit']:
                    raise AgentRuntimeError('TASK_BASE_OUTDATED', 'База задачи устарела. Обнови ветку и повтори независимые тесты и ревью.', 409)
                cwd = Path(task["worktree"])
                prompt = self._reviewer_prompt(task, run)
                if task.get('tests',{}).get('status') == 'passed':
                    from .acceptance import snapshot
                    _, _, files, digest = snapshot(self,run_id,task_id,task['allowedPaths'])
                    task['reviewDigest'] = digest
                    from .acceptance import _suite
                    _, _, suite_files, suite_digest = _suite(task)
                    task['reviewSuiteDigest'] = suite_digest
                    prompt += ('\nФактические изменённые файлы (null означает удаление):\n' + json.dumps(files,ensure_ascii=False) +
                               '\nНезависимый набор Test Designer (файлы и содержимое):\n' + json.dumps(suite_files,ensure_ascii=False) +
                               '\nSHA256 независимого набора: ' + suite_digest +
                               '\nРезультаты независимых тестов:\n' + json.dumps(task['tests'],ensure_ascii=False) +
                               '\nОтветь только JSON: {"verdict":"pass|changes_requested","findings":[],"tests":[]}. '
                               'Проверь сами тесты и diff, а не только текст результата. При отсутствии данных не ставь pass.')
                task["status"] = "reviewing"
            elif role == "test_designer":
                if task.get("testDesignerSessionId"):
                    raise AgentRuntimeError("TEST_DESIGN_EXISTS", "Сессия Test Designer уже сохранена. Не запускай её повторно без проверки истории.", 409)
                if task["status"] not in ("pending", "ready"):
                    raise AgentRuntimeError("TEST_DESIGN_NOT_READY", "Независимый Test Designer должен запускаться до Builder.", 409)
                spec_dir = self.worktrees_dir / run_id / f"{task_id}-test-spec"
                spec_dir.mkdir(parents=True, exist_ok=False)
                task['testDesignDir'] = str(spec_dir)
                for file_name, content in (("TASK.md", self._task_spec(task)), ("CONTRACTS.md", "\n".join(task["contracts"])), ("ACCEPTANCE.md", task["acceptance"])):
                    (spec_dir / file_name).write_text(content, "utf-8")
                available_mocks, missing_mocks = [], []
                project_root = Path(run['projectRoot']).resolve()
                for name in task.get('mocks', []):
                    relative = Path(name)
                    if (relative.is_absolute() or not relative.parts or '..' in relative.parts or
                            any(part.startswith('.') for part in relative.parts) or relative.suffix.lower() in {'.env','.pem','.key','.pfx'}):
                        missing_mocks.append(f'{name} — недопустимый или закрытый путь')
                        continue
                    source = project_root.joinpath(*relative.parts)
                    if source.is_symlink() or not source.resolve().is_relative_to(project_root) or not source.is_file():
                        missing_mocks.append(f'{name} — отсутствует в исходном commit')
                        continue
                    try:
                        blob = source.read_bytes()
                        if len(blob) > 200_000 or b'\0' in blob:
                            raise ValueError('размер/тип файла не поддерживается')
                        content = blob.decode('utf-8')
                    except (OSError, UnicodeError, ValueError):
                        missing_mocks.append(f'{name} — невозможно безопасно прочитать как текст')
                        continue
                    target = spec_dir.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content.encode('utf-8'))
                    available_mocks.append(name)
                (spec_dir / 'MOCKS.md').write_text(
                    '# Моки, доступные Test Designer\n\n' +
                    ('## Доступны\n' + '\n'.join(f'- `{name}`' for name in available_mocks) + '\n\n' if available_mocks else '') +
                    ('## Не найдены или не переданы\n' + '\n'.join(f'- {name}' for name in missing_mocks) + '\n' if missing_mocks else ''),
                    'utf-8')
                cwd = spec_dir
                prompt = (task["testPrompt"] or f"Подготовь независимые проверки для {task['id']} {task['title']}.") + "\n\nРеализацию не анализируй: рабочая папка содержит только условие, контракты и явно перечисленные моки. MOCKS.md сообщает, какие из перечисленных файлов действительно переданы; изучай их на месте и не считай отсутствующие файлы доступными. Обязательно создай TEST_DESIGN.md, test-manifest.json формата {version:1, framework:string, files:[...], commands:[[...]], minimumTests:число} и исполняемые файлы тестов внутри tests/ или .makora-tests/. В manifest.files перечисляй только файлы тестового набора; не включай TEST_DESIGN.md или test-manifest.json. Минимум один тест должен действительно исполняться, manifest.minimumTests укажи не меньше 1. Для неизвестного формата вывода runner добавь буквальный countPrefix, непосредственно после которого runner печатает количество пройденных тестов. Команда каждой проверки должна явно запускать suite из .makora-tests (например python -m unittest discover -s .makora-tests -v). В sandbox исходный проект использует корень рабочей папки; документы Test Designer доступны только по путям `.makora-tests/context/TASK.md`, `.makora-tests/context/CONTRACTS.md`, `.makora-tests/context/ACCEPTANCE.md`, `.makora-tests/context/TEST_DESIGN.md` и `.makora-tests/context/test-manifest.json`. Не читай документы из корня проекта по этим именам и не предполагай, что тестовые документы являются файлами исходного приложения. Не запускай команды через shell, не добавляй установщики зависимостей и сетевые действия. Тесты должны быть независимыми от тестов самого проекта, проверять контракт и критерии, завершаться ненулевым кодом при нарушении."
                task["testDesignStatus"] = "running"
            else:
                if task.get('status') != 'mahoraga_required':
                    raise AgentRuntimeError('MAHORAGA_NOT_READY', 'Передача Махораге доступна после трёх неудачных циклов Reviewer.', 409)
                cwd = Path(task['worktree'])
                prompt = (f"Проанализируй блокирующую задачу {task_id} после трёх безуспешных циклов исправления. "
                          f"Не меняй файлы. ТЗ: {self._task_spec(task)}\nПоследний отчёт Reviewer:\n"
                          f"{json.dumps(task.get('review',{}), ensure_ascii=False)}\n"
                          f"Результаты независимых тестов:\n{json.dumps(task.get('tests',{}),ensure_ascii=False)}\n"
                          "Верни конкретный диагноз, минимальный план исправления и вопросы человеку, если есть блокеры.")
            agent_id = "agent-" + uuid.uuid4().hex[:12]
            requested_at = _now()
            self._event("agent_start_requested", f"Запрошен Codex {role} на {MODEL_ID}", run_id, task_id)
            self._save()
        try:
            created = self.provider.create_thread(cwd=cwd, name=f"Makora {role} {task_id}", prompt=prompt,
                                                  sandbox="readOnly" if role in ("reviewer", "mahoraga") else "workspaceWrite", denied_paths=[run['projectRoot']])
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
                   "requestedAt": requested_at, "acceptedAt": _now(), "createdAt": _now(), "lastCheckedAt": None,
                   "executionObservedStartAt": None, "executionObservedEndAt": None, "executionObservedDurationMs": None,
                   "providerTurnTiming": {}, "result": None, "error": None,
                   "transport": "codex-app-server", "turnId": created.get("turnId")}
        with self._lock:
            self.state["sessions"][agent_id] = session
            if role == "builder": task["builderSessionId"] = agent_id
            elif role == "reviewer": task["reviewerSessionId"] = agent_id
            elif role == 'test_designer': task["testDesignerSessionId"] = agent_id
            else: task['mahoragaSessionId'] = agent_id
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
        turn = None
        operation_error = None
        try:
            operation = self.provider.operation(result["operationId"])
            state = operation.get("state", "unconfirmed")
            detail = operation.get("result") or operation.get("error")
        except AgentRuntimeError as exc:
            operation_error = {"code": exc.code, "message": str(exc)}
            state, detail = 'unconfirmed', operation_error
        # App Server operation records can expire or disappear after a desktop restart.
        # The exact saved turn remains authoritative when history can prove its state.
        try:
            history = self.provider.history(result["threadId"])
            turns = history.get("turns", [])
            turn = next((item for item in turns if isinstance(item, dict) and item.get('id') == result.get('turnId')), None)
            if turn:
                if turn.get('status') == 'completed':
                    state, detail = 'completed', history
                elif turn.get('status') in ('failed', 'interrupted'):
                    state, detail = 'failed', {'turnId': result.get('turnId'), 'turnStatus': turn.get('status'), 'history': history}
                elif turn.get('status') in ('inProgress', 'running', 'streaming'):
                    state, detail = 'running', history
            elif not operation_error and state == 'completed':
                state, detail = 'unconfirmed', {'message': 'Операция завершена, но связанный turn не найден в истории.', 'operationId': result['operationId'], 'turnId': result.get('turnId')}
        except AgentRuntimeError as exc:
            if not operation_error:
                operation_error = {"code": exc.code, "message": str(exc)}
                state, detail = 'unconfirmed', operation_error
        if not result.get('turnId'):
            state, detail = 'unconfirmed', {'message': 'У операции нет сохранённого turn ID; результат нельзя сопоставить с историей.'}
        with self._lock:
            session = self.state["sessions"][agent_id]
            session["status"] = state
            session["lastCheckedAt"] = _now()
            if state == 'running' and not session.get('executionObservedStartAt'):
                session['executionObservedStartAt'] = session['lastCheckedAt']
            if state in ('completed','failed') and not session.get('executionObservedEndAt'):
                session['executionObservedEndAt'] = session['lastCheckedAt']
            if turn:
                timing = {}
                for target, candidates in {
                    'providerStartedAt': ('startedAt','startTime','createdAt'),
                    'providerCompletedAt': ('completedAt','finishedAt','endTime','updatedAt'),
                }.items():
                    value = next((turn.get(name) for name in candidates if isinstance(turn.get(name), str)), None)
                    if value:
                        timing[target] = value
                session['providerTurnTiming'] = timing
            session['executionObservedDurationMs'] = _elapsed_ms(session.get('executionObservedStartAt'), session.get('executionObservedEndAt'))
            if state == "completed":
                session["result"] = detail
                task = self._task_for_session(session)
                if session["role"] == "builder" and task:
                    task["status"] = "review_pending"
                elif session["role"] == "reviewer" and task:
                    text = self._assistant_text(detail)
                    try:
                        review, _ = json.JSONDecoder().raw_decode(text[text.index('{'):])
                        if review.get('verdict') in ('pass','changes_requested') and isinstance(review.get('findings'), list):
                            task['review'] = {**review,'digest':task.get('reviewDigest'),'suiteDigest':task.get('reviewSuiteDigest'),'threadId':session['threadId']}
                            if review['verdict'] == 'pass':
                                task['status'] = 'review_completed'
                            elif task.get('repairAttempts', 0) >= 3:
                                task['status'] = 'mahoraga_required'
                            else:
                                task['status'] = 'changes_requested'
                        else:
                            task['status'] = 'review_unconfirmed'
                    except (ValueError,AttributeError):
                        task['review'] = {'verdict':'unconfirmed'}
                        task['status'] = 'review_unconfirmed'
                elif session["role"] == "test_designer" and task:
                    task["testDesignResult"] = self._assistant_text(detail)
                    valid, files, error = self._validate_test_design(Path(task.get('testDesignDir', '')))
                    task["testDesignStatus"] = "completed" if valid else "failed"
                    task['testDesignFiles'] = files
                    task['testDesignError'] = error
                elif session['role'] == 'mahoraga' and task:
                    task['mahoragaResult'] = self._assistant_text(detail)
                    task['status'] = 'blocked_for_human'
                elif session['role'] == 'mahoraga_planner':
                    try:
                        proposal = self._extract_json_object(self._assistant_text(detail))
                        tasks = proposal.get('tasks')
                        if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
                            raise AgentRuntimeError('PLAN_INVALID','План должен содержать список из 1–40 задач.',409)
                        normalized = []
                        seen = set()
                        for item in tasks:
                            if not isinstance(item,dict):
                                raise AgentRuntimeError('PLAN_INVALID','Каждая задача плана должна быть объектом.',409)
                            ident = item.get('id')
                            deps = item.get('dependsOn',[])
                            if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{1,39}',ident) or ident in seen:
                                raise AgentRuntimeError('PLAN_INVALID','ID задач должны быть уникальными и безопасными.',409)
                            if not isinstance(deps,list) or not all(isinstance(dep,str) for dep in deps):
                                raise AgentRuntimeError('PLAN_INVALID',f'{ident}: dependsOn должен быть списком ID.',409)
                            seen.add(ident)
                            normalized.append({**item,'dependsOn':deps})
                        if any(dep not in seen or dep == item['id'] for item in normalized for dep in item['dependsOn']):
                            raise AgentRuntimeError('PLAN_INVALID','План содержит отсутствующую или самозависимую задачу.',409)
                        self._assert_acyclic(normalized)
                        session['proposal'] = proposal
                        session['planValidation'] = {'status':'valid','taskCount':len(tasks),'dag':'acyclic'}
                    except AgentRuntimeError as exc:
                        session['planError'] = {'code':exc.code,'message':str(exc)}
                        self._event('mahoraga_plan_rejected',str(exc),session.get('runId'))
                elif session['role'] == 'mahoraga_orchestrator':
                    try:
                        proposal = self._extract_json_object(self._assistant_text(detail))
                        if not isinstance(proposal.get('actions'),list):
                            raise AgentRuntimeError('ORCHESTRATOR_ACTIONS_INVALID','В ответе Махораги отсутствует массив actions.',409)
                        session['proposal'] = proposal
                    except AgentRuntimeError as exc:
                        session['planError'] = {'code':exc.code,'message':str(exc)}
                self._event("agent_completed", f"{session['role']} thread {session['threadId']} завершил ответ", session.get("runId"), session.get("taskId"))
            elif state == "failed":
                session["error"] = detail
                task = self._task_for_session(session)
                if task and session["role"] == "builder": task["status"] = "failed"
                self._event("agent_failed", f"{session['role']} завершился ошибкой", session.get("runId"), session.get("taskId"))
            self._save()
            return dict(session)

    @staticmethod
    def _validate_test_design(spec_dir: Path) -> tuple[bool, list[str], str | None]:
        """Require a machine-runnable, independently authored suite before Builder can start."""
        try:
            spec_dir = spec_dir.resolve(strict=True)
            manifest_path = spec_dir / 'test-manifest.json'
            design_path = spec_dir / 'TEST_DESIGN.md'
            if (manifest_path.is_symlink() or design_path.is_symlink() or not manifest_path.is_file() or
                    not design_path.is_file() or manifest_path.stat().st_size > 200_000 or design_path.stat().st_size > 200_000):
                return False, [], 'Нужны TEST_DESIGN.md и test-manifest.json.'
            manifest = json.loads(manifest_path.read_text('utf-8'))
            if manifest.get('version') != 1 or not isinstance(manifest.get('framework'), str):
                return False, [], 'Неподдерживаемый формат test-manifest.json.'
            files = manifest.get('files')
            commands = manifest.get('commands')
            if not isinstance(files, list) or not files or not isinstance(commands, list) or not commands:
                return False, [], 'Манифест должен содержать files и commands.'
            normalized = []
            for name in files:
                if name in ('TEST_DESIGN.md', 'test-manifest.json'):
                    continue
                if not isinstance(name, str):
                    return False, [], f'Недопустимое имя файла теста: {name}'
                path = Path(name)
                if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in ('tests', '.makora-tests'):
                    return False, [], f'Недопустимый путь теста: {name}'
                target = spec_dir.joinpath(*path.parts)
                if target.is_symlink() or not target.resolve().is_relative_to(spec_dir) or not target.is_file():
                    return False, [], f'Файл теста не найден или небезопасен: {name}'
                normalized.append(path.as_posix())
            if not normalized:
                return False, [], 'В манифесте нет исполняемых файлов независимого набора.'
            for command in commands:
                if (not isinstance(command, list) or len(command) < 2 or
                    not all(isinstance(part, str) and part and '\0' not in part for part in command) or
                    '.makora-tests' not in ' '.join(command) or Path(command[0]).name.lower().removesuffix('.exe') not in
                    {'python','python3','pytest','node','npm','go','cargo','dotnet','java','mvn','gradle'}):
                    return False, [], 'Каждая команда должна быть argv-массивом и запускать независимый suite из .makora-tests.'
            return True, normalized, None
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            return False, [], f'Ошибка чтения test design: {exc}'

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
                if isinstance(item, dict) and (item.get("role") == "assistant" or item.get("type") in {"agentMessage", "assistantMessage"}):
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
        untracked = self._run_git(root, "ls-files", "--others", "--exclude-standard", "--", ".").splitlines()
        tracked = self._run_git(root, "diff", "--name-only", "HEAD", "--", ".").splitlines()
        return {"status": self._run_git(root, "status", "--short"),
                "diff": self._run_git(root, "diff", "--no-ext-diff", "HEAD", "--", "."),
                "changedFiles": list(dict.fromkeys(tracked + untracked)),
                "untrackedFiles": untracked,
                "untrackedNotice": "Содержимое новых файлов не включено автоматически: проверь их перед передачей Reviewer.",
                "branch": task.get("branch"), "baseCommit": run["baseCommit"]}

    def test_task(self, run_id, task_id, allowed_paths):
        from .acceptance import test_task
        return test_task(self, run_id, task_id, allowed_paths)

    def integrate_task(self, run_id, task_id, confirmed=False):
        from .acceptance import integrate
        return integrate(self, run_id, task_id, confirmed)

    def refresh_task_base(self, run_id: str, task_id: str, resolved_conflicts: list[str] | None = None,
                          allowed_paths: list[str] | None = None) -> dict:
        """Replay a task's approved diff onto the latest base with Git's three-way merge."""
        from .acceptance import snapshot
        with self._lock:
            run = self._run(run_id)
            task = next((item for item in run['tasks'] if item['id'] == task_id), None)
            if not task or not task.get('worktree'):
                raise AgentRuntimeError('WORKTREE_NOT_FOUND', 'Для задачи нет исходного worktree.', 404)
            if task.get('worktreeBase', run['baseCommit']) == run['baseCommit']:
                return {'status': 'current', 'baseCommit': run['baseCommit'], 'worktree': task['worktree']}
            if task['status'] in ('integrated','implementing','reviewing','unconfirmed'):
                raise AgentRuntimeError('TASK_BUSY', 'Сначала заверши активную сессию агента; состояние задачи не изменено.', 409)
            if task['status'] == 'rebase_conflict':
                raise AgentRuntimeError('CONFLICT_RESOLUTION_REQUIRED', 'Разреши конфликты в новом worktree и подтверди их через отдельную проверку.', 409,
                                        {'worktree': task['worktree'], 'conflicts': task.get('conflictPaths', [])})
            if resolved_conflicts:
                raise AgentRuntimeError('UNSAFE_CONFLICT_OVERRIDE', 'Нельзя подтвердить разрешение простым списком имён файлов. Сначала перенеси изменения через трёхсторонний Git merge, затем проверь фактически разрешённый worktree.', 409)
            if runtime_head := self._run_git(Path(run['projectRoot']), 'rev-parse', 'HEAD'):
                if runtime_head != run['baseCommit'] or self._run_git(Path(run['projectRoot']), 'status', '--porcelain'):
                    raise AgentRuntimeError('PROJECT_CHANGED', 'Основной проект должен совпадать с последним интегрированным коммитом.', 409)
            allowed = allowed_paths if allowed_paths is not None else task.get('allowedPaths', [])
            if not isinstance(allowed, list) or not all(isinstance(path, str) for path in allowed):
                raise AgentRuntimeError('INVALID_ALLOWED_PATHS', 'Файлы должны быть списком относительных путей.', 400)
            if not allowed:
                raise AgentRuntimeError('ALLOWED_PATHS_REQUIRED', 'Укажи разрешённые файлы задачи для переноса на новую базу.', 409)
            _, old_root, changed, _ = snapshot(self, run_id, task_id, allowed)
            old_base = task.get('worktreeBase', run['baseCommit'])
            root = Path(run['projectRoot'])
            suffix = uuid.uuid4().hex[:8]
            scratch = self.worktrees_dir / run_id / f"{task_id}-snapshot-{suffix}"
            folder = self.worktrees_dir / run_id / f"{task_id}-base-{run['baseCommit'][:8]}-{suffix}"
            branch = f"makora/{run_id}/{task_id}-base-{run['baseCommit'][:8]}-{suffix}".lower()
            allowed_args = sorted(changed)
            try:
                # Build a synthetic commit from only the allow-listed snapshot. This avoids
                # staging or rewriting the source Builder worktree and gives Git a true base
                # for its three-way replay onto already integrated work.
                self._run_git(root, 'worktree', 'add', '--detach', str(scratch), old_base)
                for name, content in changed.items():
                    relative = Path(*Path(name).parts)
                    if relative.is_absolute() or '..' in relative.parts or any(part.startswith('.') for part in relative.parts):
                        raise AgentRuntimeError('UNSAFE_PATH', f'Недопустимый файл при обновлении базы: {name}', 409)
                    source = old_root.joinpath(*relative.parts)
                    target = scratch.joinpath(*relative.parts)
                    if content is None:
                        target.unlink(missing_ok=True)
                    else:
                        if source.is_symlink() or not source.resolve().is_relative_to(old_root.resolve()):
                            raise AgentRuntimeError('UNSAFE_PATH', name, 409)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content.encode('utf-8'))
                self._run_git(scratch, 'add', '-A', '--', *allowed_args)
                self._run_git(scratch, '-c', 'user.name=Makora', '-c', 'user.email=makora@localhost',
                              'commit', '--allow-empty', '-m', f'Makora replay snapshot {task_id}')
                replay_commit = self._run_git(scratch, 'rev-parse', 'HEAD')

                self._run_git(root, 'worktree', 'add', '-b', branch, str(folder), run['baseCommit'])
                replay = subprocess.run(['git', '-C', str(folder), 'cherry-pick', '--no-commit', replay_commit],
                                        capture_output=True, text=True, timeout=60)
                if replay.returncode:
                    conflicts = self._run_git(folder, 'diff', '--name-only', '--diff-filter=U', '--', '.').splitlines()
                    if not conflicts:
                        raise AgentRuntimeError('REPLAY_FAILED', replay.stderr.strip() or replay.stdout.strip() or 'Git could not replay task changes.', 409)
                    task.setdefault('previousWorktrees', []).append({'worktree': str(old_root), 'branch': task.get('branch'), 'baseCommit': old_base})
                    task.update(worktree=str(folder), branch=branch, worktreeBase=run['baseCommit'], status='rebase_conflict',
                                integration='not_integrated', allowedPaths=allowed, conflictPaths=conflicts,
                                tests=None, review=None, reviewDigest=None, reviewSuiteDigest=None)
                    self._event('parallel_conflict_created', f'Git оставил {len(conflicts)} файл(ов) для ручного разрешения; интегрированная версия сохранена в базе', run_id, task_id)
                    self._save()
                    return {'status': 'conflict_resolution_required', 'baseCommit': run['baseCommit'], 'worktree': str(folder),
                            'branch': branch, 'changedFiles': sorted(changed), 'conflicts': conflicts,
                            'message': 'Разреши конфликт в новом worktree. Интегрированная база не изменена.'}
                # --no-commit keeps the replay as uncommitted changes for normal validation.
                subprocess.run(['git', '-C', str(folder), 'cherry-pick', '--quit'], capture_output=True, text=True, timeout=30)
                self._run_git(folder, 'reset', '--quiet')
            except Exception:
                if folder.exists():
                    subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(folder)], capture_output=True, timeout=30)
                raise
            finally:
                if scratch.exists():
                    subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(scratch)], capture_output=True, timeout=30)
            task.setdefault('previousWorktrees', []).append({'worktree': str(old_root), 'branch': task.get('branch'), 'baseCommit': old_base})
            task.update(worktree=str(folder), branch=branch, worktreeBase=run['baseCommit'], status='review_pending',
                        integration='not_integrated', allowedPaths=allowed, tests=None, review=None, reviewDigest=None, reviewSuiteDigest=None)
            self._event('parallel_branch_replayed', f'Изменения перенесены трехсторонним Git merge на {run["baseCommit"][:12]}; тесты и Reviewer сброшены', run_id, task_id)
            self._save()
            return {'status': 'refreshed', 'baseCommit': run['baseCommit'], 'worktree': str(folder), 'branch': branch,
                    'changedFiles': sorted(changed)}

    def resolve_task_conflicts(self, run_id: str, task_id: str) -> dict:
        """Accept only a human-resolved Git worktree after verifying all conflicts and scope."""
        with self._lock:
            run = self._run(run_id)
            task = next((item for item in run['tasks'] if item['id'] == task_id), None)
            if not task or task.get('status') != 'rebase_conflict' or not task.get('worktree'):
                raise AgentRuntimeError('NO_CONFLICT_TO_RESOLVE', 'У задачи нет ожидающего ручного Git-конфликта.', 409)
            project = Path(run['projectRoot'])
            if self._run_git(project, 'rev-parse', 'HEAD') != run['baseCommit'] or self._run_git(project, 'status', '--porcelain'):
                raise AgentRuntimeError('PROJECT_CHANGED', 'Интегрированная база изменилась. Сначала повторно обнови план.', 409)
            root = Path(task['worktree']).resolve(strict=True)
            if self._run_git(root, 'rev-parse', 'HEAD') != run['baseCommit']:
                raise AgentRuntimeError('TASK_BASE_OUTDATED', 'Worktree конфликта не основан на текущей интегрированной базе.', 409)
            unresolved = self._run_git(root, 'diff', '--name-only', '--diff-filter=U', '--', '.').splitlines()
            if unresolved:
                raise AgentRuntimeError('CONFLICTS_REMAIN', 'Git всё ещё видит неразрешённые файлы.', 409, {'conflicts': unresolved})
            allowed = set(task.get('allowedPaths', []))
            changed = self.run_diff(run_id, task_id)['changedFiles']
            outside = sorted(set(changed) - allowed)
            if outside:
                raise AgentRuntimeError('UNAPPROVED_PATH', 'Разрешение затронуло файлы вне списка задачи.', 409, {'files': outside})
            for name in task.get('conflictPaths', []):
                path = root.joinpath(*Path(name).parts)
                if path.exists() and path.is_file():
                    text = path.read_text('utf-8', errors='replace')
                    if any(line.startswith(('<<<<<<< ', '=======', '>>>>>>> ')) for line in text.splitlines()):
                        raise AgentRuntimeError('CONFLICT_MARKERS_REMAIN', f'В {name} остались маркеры конфликта.', 409)
            subprocess.run(['git', '-C', str(root), 'cherry-pick', '--quit'], capture_output=True, text=True, timeout=30)
            self._run_git(root, 'reset', '--quiet')
            task.update(status='review_pending', conflictPaths=[], tests=None, review=None, reviewDigest=None, reviewSuiteDigest=None)
            self._event('parallel_conflict_resolved', 'Проверено разрешение конфликта; независимые тесты и Reviewer требуются заново', run_id, task_id)
            self._save()
            return {'status': 'resolved', 'worktree': str(root), 'baseCommit': run['baseCommit'], 'changedFiles': changed,
                    'requiresRetest': True, 'requiresReview': True}

    def request_builder_fixes(self, run_id: str, task_id: str) -> dict:
        with self._lock:
            run = self._run(run_id)
            task = next((item for item in run['tasks'] if item['id'] == task_id), None)
            if not task or task.get('status') != 'changes_requested' or task.get('review', {}).get('verdict') != 'changes_requested':
                raise AgentRuntimeError('REVIEW_CHANGES_REQUIRED', 'Нет актуальных замечаний Reviewer.', 409)
            if task.get('repairAttempts', 0) >= 3:
                task['status'] = 'mahoraga_required'
                self._save()
                return {'status': 'mahoraga_required', 'attempts': 3}
            builder_id = task.get('builderSessionId')
            if not builder_id:
                raise AgentRuntimeError('BUILDER_SESSION_MISSING', 'Сессия Builder не найдена.', 409)
            attempt = task.get('repairAttempts', 0) + 1
            feedback = json.dumps(task['review'].get('findings', []), ensure_ascii=False, indent=2)
            message = (f"Цикл исправлений {attempt}/3. Исправь замечания независимого Reviewer:\n{feedback}\n"
                       "Меняй только разрешённые файлы задачи. После исправления сообщи список файлов. Старые тесты и review будут аннулированы.")
            task['repairAttempts'] = attempt
            self._save()
        result = self.send_message(builder_id, message)
        with self._lock:
            task['lastRepairTurnId'] = result.get('turnId')
            self._event('builder_fix_requested', f'Цикл исправления {attempt}/3 отправлен Builder', run_id, task_id)
            self._save()
        return {'status': 'fix_requested', 'attempt': attempt, 'turnId': result.get('turnId')}

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
            if session["status"] in ("accepted", "delivered", "running", "unconfirmed"):
                raise AgentRuntimeError("SESSION_BUSY", "В этом thread уже выполняется запрос.", 409)
            thread_id = session["threadId"]
            requested_at = _now()
            task = self._task_for_session(session)
            if task and session['role'] == 'builder':
                task.pop('tests', None)
                task.pop('review', None)
                task.pop('reviewDigest', None)
                task.pop('reviewSuiteDigest', None)
                task['status'] = 'implementing'
                self._save()
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
            session["turnId"] = result.get('turnId')
            session["status"] = operation.get("state", "accepted")
            session['requestedAt'] = requested_at
            session['acceptedAt'] = _now()
            session['executionObservedStartAt'] = None
            session['executionObservedEndAt'] = None
            session['executionObservedDurationMs'] = None
            session['providerTurnTiming'] = {}
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

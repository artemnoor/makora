"""Small local HTTP API for Makora's persistent external-AI iteration cycle."""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .iterations import IterationStore, MAX_ARCHIVE
from .workspace import MakoraError
from .agents import AgentRuntime, AgentRuntimeError


class MakoraHandler(SimpleHTTPRequestHandler):
    server_version = 'MakoraLocal/1.0'

    def __init__(self, *args, directory=None, **kwargs):
        self.static_dir = Path(directory).resolve() if directory else None
        super().__init__(*args, directory=str(self.static_dir) if self.static_dir else None, **kwargs)

    @property
    def store(self):
        return self.server.iteration_store

    @staticmethod
    def _local_origin(value):
        try:
            parsed=urlparse(value)
            return parsed.scheme in ('http','https') and parsed.hostname in ('localhost','127.0.0.1','::1') and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment
        except ValueError:return False

    def _local_request(self):
        try:
            host=urlparse('http://'+self.headers.get('Host','')).hostname
        except ValueError:return False
        origin=self.headers.get('Origin')
        return host in ('localhost','127.0.0.1','::1') and (not origin or (self._local_origin(origin) and urlparse(origin).netloc.lower()==self.headers.get('Host','').lower()))

    def end_headers(self):
        origin = self.headers.get('Origin', '')
        if self._local_origin(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        super().end_headers()

    def do_OPTIONS(self):
        if not self._local_request():self._error(MakoraError('ORIGIN_NOT_ALLOWED','Доступ разрешён только локальному интерфейсу.'),403);return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Base-Revision')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def _body(self, limit=MAX_ARCHIVE):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError as exc:
            raise MakoraError('INVALID_CONTENT_LENGTH', 'Некорректный Content-Length.') from exc
        if length <= 0 or length > limit:
            raise MakoraError('REQUEST_TOO_LARGE', f'Размер запроса должен быть от 1 байта до {limit // (1024*1024)} МБ.')
        return self.rfile.read(length)

    def _json(self, value, status=200):
        data = json.dumps({'ok': True, 'result': value}, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def _zip(self, data, filename):
        self.send_response(200); self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def _error(self, error, status=400):
        value = {'ok': False, 'error': {'code': getattr(error, 'code', 'INTERNAL_ERROR'), 'message': str(error)}}
        details = getattr(error, 'details', None)
        if details: value['error']['details'] = details
        data = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def _read_json(self):
        data = self._body(2 * 1024 * 1024)
        try:
            value = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MakoraError('INVALID_JSON', 'Тело запроса должно быть JSON.') from exc
        if not isinstance(value, dict):
            raise MakoraError('INVALID_JSON', 'Тело запроса должно быть JSON-объектом.')
        return value

    def _agent_auth(self):
        supplied=self.headers.get('X-Makora-Token','')
        expected=getattr(self.server,'agent_token','')
        return bool(expected and secrets.compare_digest(supplied,expected))

    def _agent_json(self, call, status=200):
        try:self._json(call(),status)
        except AgentRuntimeError as exc:self._error(exc,exc.status)
        except (OSError,ValueError,KeyError) as exc:self._error(exc,500)

    def do_GET(self):
        if not self._local_request():self._error(MakoraError('ORIGIN_NOT_ALLOWED','Доступ разрешён только локальному интерфейсу.'),403);return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == '/api/agents/token':
                origin=self.headers.get('Origin','')
                same_origin = (origin and self._local_origin(origin) and urlparse(origin).netloc.lower()==self.headers.get('Host','').lower()) or (not origin and self.headers.get('Sec-Fetch-Site','') == 'same-origin')
                if not same_origin or self.headers.get('X-Makora-Request') != 'token':
                    self._error(AgentRuntimeError('SAME_ORIGIN_REQUIRED','Token is available only to the Makora page.',403),403);return
                self._json({'token':self.server.agent_token});return
            if path == '/api/agents/status':
                self._agent_json(self.server.agent_runtime.status);return
            if path == '/api/agents/approvals':
                self._agent_json(self.server.agent_runtime.approvals);return
            if path == '/api/agents/state':
                self._agent_json(self.server.agent_runtime.snapshot);return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.get_run(match.group(1)));return
            match=re.fullmatch(r'/api/agents/sessions/([\w-]+)',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.get_session(match.group(1)));return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/diff',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.run_diff(match.group(1),match.group(2)));return
            if path == '/api/status':
                current = self.store.current_revision()
                self._json({'available': True, 'storage': 'local-filesystem', 'current_revision': current,
                            'message': 'Локальная история доступна; внешний код автоматически не запускается.'})
            elif path == '/api/history': self._json(self.store.summary())
            elif path == '/api/next-package': self._zip(self.store.next_package(), 'makora-next-iteration.zip')
            elif path == '/api/revisions/current/documents':
                self._json(self.store.current_documents(parse_qs(parsed.query).get('stage',[''])[0]))
            else:
                match = re.fullmatch(r'/api/revisions/([\w-]+)/compare/([\w-]+)',path)
                if match:
                    self._json(self.store.compare_revisions(match.group(1),match.group(2))); return
                match = re.fullmatch(r'/api/revisions/([\w-]+)/archive',path)
                if match:
                    revision=self.store._revision(match.group(1))
                    self._zip(self.store._archive(revision),revision['revision_id']+'.zip');return
                match = re.fullmatch(r'/api/iterations/([\w-]+)/package', path)
                if match:
                    item = self.store._iteration(match.group(1))
                    self._zip(self.store._archive_path(item['package']).read_bytes(), f"{item['iteration_id']}-package.zip")
                    return
                match = re.fullmatch(r'/api/iterations/([\w-]+)/returns/(\d+)',path)
                if match:
                    item=self.store._iteration(match.group(1));index=int(match.group(2))
                    history=item.get('return_history',[])
                    if index>=len(history): raise MakoraError('RETURN_NOT_FOUND','Загрузка не найдена.')
                    self._zip(self.store._archive_path(history[index]['result']).read_bytes(),f"{item['iteration_id']}-return-{index+1}.zip");return
                match = re.fullmatch(r'/api/iterations/([\w-]+)/result',path)
                if match:
                    item=self.store._iteration(match.group(1))
                    if not item.get('result'): raise MakoraError('RETURN_NOT_FOUND','Загрузка не найдена.')
                    self._zip(self.store._archive_path(item['result']).read_bytes(),f"{item['iteration_id']}-result.zip");return
                match = re.fullmatch(r'/api/iterations/([\w-]+)/diff', path)
                if match:
                    item = self.store._iteration(match.group(1))
                    query = parse_qs(parsed.query)
                    change = next((c for c in item.get('changes',[]) if c['path'] == query.get('path',[''])[0]), None)
                    if not change: raise MakoraError('CHANGE_NOT_FOUND', 'Для файла нет обнаруженного изменения.')
                    self._json(change); return
                match = re.fullmatch(r'/api/iterations/([\w-]+)', path)
                if match: self._json(self.store.iteration(match.group(1)))
                elif self.static_dir:
                    super().do_GET()
                else: self._error(MakoraError('NOT_FOUND','Маршрут не найден.'),404)
        except MakoraError as exc:
            self._error(exc, 404 if exc.code.endswith('_NOT_FOUND') else 400)
        except (OSError, ValueError) as exc:
            self._error(exc, 500)

    def do_POST(self):
        if not self._local_request():self._error(MakoraError('ORIGIN_NOT_ALLOWED','Доступ разрешён только локальному интерфейсу.'),403);return
        path = unquote(urlparse(self.path).path)
        try:
            if path.startswith('/api/agents/') and not self._agent_auth():
                self._error(AgentRuntimeError('AUTH_REQUIRED','Нужен действующий токен этой страницы Макоры.',401),401);return
            match=re.fullmatch(r'/api/agents/approvals/([\w-]+)',path)
            if match:
                value=self._read_json()
                self._agent_json(lambda:self.server.agent_runtime.resolve_approval(match.group(1),str(value.get('decision',''))));return
            if path == '/api/agents/plans':
                self._agent_json(lambda:self.server.agent_runtime.start_mahoraga_planning(self._read_json()),201);return
            match=re.fullmatch(r'/api/agents/plans/([\w-]+)/approve',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.approve_mahoraga_plan(match.group(1)),201);return
            if path == '/api/agents/runs':
                self._agent_json(lambda:self.server.agent_runtime.create_run(self._read_json()),201);return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/mahoraga',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.start_mahoraga_orchestrator(match.group(1)),201);return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/(tests|integrate)',path)
            if match:
                value=self._read_json()
                if match.group(3)=='tests':
                    self._agent_json(lambda:self.server.agent_runtime.test_task(match.group(1),match.group(2),value.get('allowedPaths',[])));return
                self._agent_json(lambda:self.server.agent_runtime.integrate_task(match.group(1),match.group(2),value.get('confirmed') is True));return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/worktree',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.create_task_worktree(match.group(1),match.group(2)),201);return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/agents/(builder|reviewer|test_designer|mahoraga)',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.launch_agent(match.group(1),match.group(2),match.group(3)),201);return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/rebase',path)
            if match:
                value=self._read_json()
                self._agent_json(lambda:self.server.agent_runtime.refresh_task_base(match.group(1),match.group(2),value.get('resolvedConflicts'),value.get('allowedPaths')));return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/resolve-conflicts',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.resolve_task_conflicts(match.group(1),match.group(2)));return
            match=re.fullmatch(r'/api/agents/runs/([\w-]+)/tasks/([\w-]+)/request-fixes',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.request_builder_fixes(match.group(1),match.group(2)));return
            match=re.fullmatch(r'/api/agents/sessions/([\w-]+)/messages',path)
            if match:
                value=self._read_json()
                self._agent_json(lambda:self.server.agent_runtime.send_message(match.group(1),str(value.get('text',''))),202);return
            match=re.fullmatch(r'/api/agents/sessions/([\w-]+)/apply-actions',path)
            if match:self._agent_json(lambda:self.server.agent_runtime.apply_mahoraga_actions(match.group(1)));return
            if path == '/api/iterations/prepare':
                result = self.store.prepare(self._body(), self.headers.get('X-Base-Revision'))
                self._json(result, 201)
                return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/result', path)
            if match:
                self._json(self.store.return_project(match.group(1), self._body())); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/sent', path)
            if match:
                self._json(self.store.mark_sent(match.group(1))); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/decisions/([\w-]+)', path)
            if match:
                value=self._read_json()
                self._json(self.store.decide(match.group(1),match.group(2),value.get('action'),value.get('note',''))); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/adaptation-package', path)
            if match:
                self._zip(self.store.adaptation_package(match.group(1)), 'makora-adaptation.zip'); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/adaptation', path)
            if match:
                self._json(self.store.import_adaptation(match.group(1),self._body())); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/documents', path)
            if match:
                value=self._read_json()
                self._json(self.store.decide_document(match.group(1),value.get('path'),value.get('action'))); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/questions', path)
            if match:
                value=self._read_json()
                self._json(self.store.answer_questions(match.group(1),value.get('answers'))); return
            match = re.fullmatch(r'/api/iterations/([\w-]+)/approve', path)
            if match:
                self._json(self.store.approve(match.group(1))); return
            match = re.fullmatch(r'/api/revisions/([\w-]+)/rollback', path)
            if match:
                self._json(self.store.rollback(match.group(1))); return
            self._error(MakoraError('NOT_FOUND','Маршрут не найден.'),404)
        except MakoraError as exc:
            self._error(exc, 409 if exc.code in ('STALE_BASE','CHANGES_UNRESOLVED','DECISION_CONFLICT','ADAPTATION_REQUIRED') else 400)
        except (OSError, ValueError) as exc:
            self._error(exc, 500)

    def log_message(self, fmt, *args):
        # Keep file names and imported payloads out of the standard request log.
        if self.path.startswith('/api'):
            print(f'{self.address_string()} - {fmt % args}')
        else:
            super().log_message(fmt, *args)


def serve(workspace, static, host='127.0.0.1', port=8765, agent_roots=None):
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    handler = lambda *args, **kwargs: MakoraHandler(*args, directory=static, **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.iteration_store = IterationStore(workspace)
    default_root=Path(__file__).parent.parent.resolve()
    roots=[Path(p).expanduser().resolve() for p in (agent_roots or [])]
    server.agent_runtime=AgentRuntime(workspace,default_root/'integrations'/'codex-desktop-local-api',roots or [default_root])
    server.agent_token=secrets.token_urlsafe(32)
    print(f'Макора API: http://{host}:{port}/api/status')
    print(f'Локальное хранилище: {workspace}')
    if static: print(f'Статика: {Path(static).resolve()}')
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        server.server_close()
        server.agent_runtime.close()


def main():
    parser=argparse.ArgumentParser(description='Локальный API Макоры для внешних итераций')
    parser.add_argument('--workspace', default=os.environ.get('MAKORA_WORKSPACE', str(Path.home()/'.makora'/'workspace')))
    parser.add_argument('--static', default=None, help='Каталог dist для раздачи сайта с того же порта')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--agent-root', action='append', default=[], help='Разрешённая Git-папка проекта для Agent Worktree (можно указать несколько раз)')
    args=parser.parse_args()
    if args.port < 1 or args.port > 65535: parser.error('Порт должен быть между 1 и 65535.')
    serve(args.workspace,args.static,args.host,args.port,args.agent_root)


if __name__ == '__main__': main()

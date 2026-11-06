"""Auth health from the same provider used by agents; local interactive recovery."""
import base64
import os
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .agents.runtime import AgentRuntimeError


class CodexAuth:
    def __init__(self, provider, sessions=None):
        self.provider = provider
        self.sessions = sessions or (lambda: [])
        self.console = None
        self.lock = threading.Lock()

    def status(self):
        try:
            self.provider.ensure_started()
            result = self.provider._request('/api/auth/status', timeout=40)
            if result.get('status') == 'signed_in':
                failure = 0
                success = 0
                for session in self.sessions():
                    try:
                        stamp = datetime.fromisoformat(session.get('executionObservedEndAt') or session.get('createdAt') or '').timestamp()
                    except (ValueError, TypeError):
                        continue
                    error = session.get('error') or {}
                    message = str(error.get('message', '')).lower() if isinstance(error, dict) else ''
                    if session.get('status') == 'failed' and any(term in message for term in ('access token', 'refresh token', 'unauthorized', 'sign in again')):
                        failure = max(failure, stamp)
                    if session.get('status') == 'completed' and session.get('result'):
                        success = max(success, stamp)
                auth_file = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')) / 'auth.json'
                try:
                    credentials_changed = auth_file.stat().st_mtime
                except OSError:
                    credentials_changed = 0
                if failure > max(success, credentials_changed):
                    return {'status': 'signed_out', 'message': 'Codex отклонил запуск агента: авторизация недействительна. Войдите заново; наличие аккаунта не подтвердило доступ к генерации.'}
            return result
        except AgentRuntimeError:
            return {'status': 'unavailable', 'message': 'Проверка входа недоступна. Проверьте подключение к Codex.'}

    def login(self):
        with self.lock:
            if self.console and self.console.poll() is None:
                return {'opened': True, 'message': 'Консоль входа уже открыта.'}
            if os.name != 'nt':
                raise AgentRuntimeError('LOGIN_CONSOLE_UNAVAILABLE', 'Выполните codex login в терминале.', 503)
            shell = shutil.which('pwsh') or shutil.which('powershell')
            binary = os.environ.get('CODEX_APP_SERVER_BINARY') or shutil.which('codex.exe') or shutil.which('codex.cmd') or shutil.which('codex')
            if not shell or not binary:
                raise AgentRuntimeError('LOGIN_CONSOLE_UNAVAILABLE', 'Не найдены PowerShell или Codex CLI. Установите Codex CLI и выполните codex login.', 503)
            quoted = "'" + str(binary).replace("'", "''") + "'"
            command = ("$Host.UI.RawUI.WindowTitle='Makora - Codex login'; "
                       "Write-Host 'Sign in to Codex. Complete login in your browser.'; "
                       f"& {quoted} login; "
                       "Write-Host 'Return to Makora and click Check login.'")
            encoded = base64.b64encode(command.encode('utf-16-le')).decode('ascii')
            self.console = subprocess.Popen([shell, '-NoProfile', '-NoExit', '-EncodedCommand', encoded],
                                            creationflags=subprocess.CREATE_NEW_CONSOLE)
            return {'opened': True, 'message': 'Открыта консоль codex login. Завершите вход в браузере, затем проверьте вход здесь.'}

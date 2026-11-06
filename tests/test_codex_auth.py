import base64
import unittest
from unittest.mock import Mock, patch

from makora_core.codex_auth import CodexAuth
from makora_core.agents.runtime import AgentRuntimeError


class CodexAuthTests(unittest.TestCase):
    def test_generation_auth_failure_overrides_account_presence(self):
        import tempfile
        from pathlib import Path
        provider = Mock()
        provider._request.return_value = {'status': 'signed_in'}
        session = {'status': 'failed', 'createdAt': '2026-11-03T20:58:00+00:00',
                   'error': {'message': 'Your access token could not be refreshed. Please sign in again.'}}
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'CODEX_HOME': folder}):
            auth = CodexAuth(provider, lambda: [session])
            self.assertEqual('signed_out', auth.status()['status'])
            credentials = Path(folder) / 'auth.json'
            credentials.write_text('{}')
            import os
            os.utime(credentials, (2000000000, 2000000000))
            self.assertEqual('signed_in', auth.status()['status'])

    def test_status_uses_agent_provider_and_keeps_disconnect_distinct(self):
        provider = Mock()
        provider._request.return_value = {'status': 'signed_out', 'message': 'Sign in'}
        auth = CodexAuth(provider)
        self.assertEqual('signed_out', auth.status()['status'])
        provider.ensure_started.assert_called_once()
        provider._request.assert_called_once_with('/api/auth/status', timeout=40)
        provider.ensure_started.side_effect = AgentRuntimeError('OFFLINE', 'Disconnected')
        self.assertEqual('unavailable', auth.status()['status'])

    def test_console_is_interactive_uses_fixed_login_and_deduplicates(self):
        auth = CodexAuth(Mock())
        process = Mock()
        process.poll.return_value = None
        with patch('makora_core.codex_auth.os.name', 'nt'), \
             patch('makora_core.codex_auth.os.environ', {}), \
             patch('makora_core.codex_auth.shutil.which', side_effect=lambda name: {'pwsh': 'pwsh.exe', 'codex.exe': "C:/Codex user's/codex.exe"}.get(name)), \
             patch('makora_core.codex_auth.subprocess.CREATE_NEW_CONSOLE', 16, create=True), \
             patch('makora_core.codex_auth.subprocess.Popen', return_value=process) as launch:
            self.assertTrue(auth.login()['opened'])
            self.assertTrue(auth.login()['opened'])
            launch.assert_called_once()
            argv = launch.call_args.args[0]
            command = base64.b64decode(argv[-1]).decode('utf-16-le')
            self.assertIn("& 'C:/Codex user''s/codex.exe' login", command)
            self.assertIn('-NoExit', argv)
            self.assertEqual(16, launch.call_args.kwargs['creationflags'])


if __name__ == '__main__':
    unittest.main()

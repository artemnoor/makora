"""Public agent errors must never serialize provider history into interface copy."""
from __future__ import annotations


def agent_error_message(error, fallback='Не удалось выполнить запрос к агенту. Проверьте состояние и попробуйте ещё раз.'):
    if isinstance(error, dict):
        if error.get('turnStatus') == 'interrupted' or error.get('code') == 'TURN_INTERRUPTED':
            return 'Запрос агента прерван. Можно повторить этап с уточнениями.'
        error = error.get('message')
    if isinstance(error, str):
        message = error.strip()
        # Provider payloads and transcripts belong in diagnostics, never in copy.
        if message and len(message) <= 1000 and not message.startswith(('{', '[')):
            return message
    return fallback


def public_agent_error(error):
    interrupted = isinstance(error, dict) and error.get('turnStatus') == 'interrupted'
    code = 'TURN_INTERRUPTED' if interrupted else 'AGENT_FAILED'
    return {'code': code, 'message': agent_error_message(error)}

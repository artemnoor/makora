import json
from io import BytesIO
from copy import deepcopy
import unittest
import threading
import urllib.request
import urllib.error
from types import SimpleNamespace

from pypdf import PdfReader
from makora_core.competitors_pdf import export_competitors
from makora_core.server import LocalHTTPServer, MakoraHandler


class CompetitorsPdfTests(unittest.TestCase):
    def record(self):
        return {'status': 'failed', 'sourceEvidence': [], 'files': {
            '02_competitors.md': '# Вывод\nУчитывать ограничения и проверить источники.',
            '02_competitors.json': json.dumps({'competitors': [{
                'id': 'one', 'name': 'Русский аналог <тест>',
                'summary': 'Помогает студентам находить мероприятия. ' * 180,
                'url': 'https://example.com', 'ideasToBorrow': ['Поиск и фильтры'],
                'comparison': [{'criterion': 'Поиск', 'theirs': 'Фильтры по дате', 'ours': 'Поиск по интересам'}],
                'sources': [{'url': 'https://example.com/' + 'long-path-' * 60,
                             'title': 'Описание продукта', 'quote': 'Поиск событий', 'checkedAt': '2026-11-08'}],
            }]}, ensure_ascii=False)}}

    def test_unicode_multipage_export_preserves_unsaved_decisions_and_status(self):
        record = self.record()
        original = deepcopy(record)
        data = export_competitors(record, decisions={'one': {'action': 'adapt', 'comment': 'Адаптировать фильтры'}},
                                  note='Приоритет: простота поиска')
        self.assertTrue(data.startswith(b'%PDF-'))
        pdf = PdfReader(BytesIO(data))
        self.assertGreater(len(pdf.pages), 1)
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        for expected in ['Русский аналог <тест>', 'Адаптировать фильтры', 'Поиск по интересам',
                         'Источники пока не подтверждены', 'Рабочая версия', 'Полный отчёт', 'Приоритет: простота поиска']:
            self.assertIn(expected, text)
        self.assertEqual(original, record)

    def test_empty_review_cannot_export_and_markdown_only_review_can(self):
        with self.assertRaisesRegex(ValueError, 'не готов'):
            export_competitors({'files': {}})
        data = export_competitors({'files': {'02_competitors.md': '# Аналоги\nКраткий разбор.'}})
        self.assertIn('Краткий разбор', PdfReader(BytesIO(data)).pages[0].extract_text())

    def test_http_export_requires_auth_and_downloads_pdf_with_current_comments(self):
        state = {'stages': {'2': self.record()}, 'competitorDecisions': {}}
        original = deepcopy(state)
        with LocalHTTPServer(('127.0.0.1', 0), MakoraHandler) as server:
            server.agent_token = 'pdf-test-token'
            server.preparation = SimpleNamespace(snapshot=lambda: deepcopy(state))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                url = f'http://127.0.0.1:{server.server_port}/api/preparation/2/pdf'
                payload = json.dumps({'decisions': {'one': {'comment': 'Мой комментарий'}}}).encode()
                request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(401, error.exception.code)
                request.add_header('X-Makora-Token', 'pdf-test-token')
                with urllib.request.urlopen(request) as response:
                    self.assertEqual('application/pdf', response.headers['Content-Type'])
                    self.assertIn('attachment;', response.headers['Content-Disposition'])
                    pdf = PdfReader(BytesIO(response.read()))
                    self.assertIn('Мой комментарий', '\n'.join(p.extract_text() for p in pdf.pages))
                self.assertEqual(original, state)
            finally:
                server.shutdown()
                worker.join()

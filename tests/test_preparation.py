import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from makora_core.preparation import Preparation
from makora_core.agents.runtime import AgentRuntimeError, AgentRuntime


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        def create_thread(**kwargs):
            self.calls.append(kwargs)
            return {'id': 'thread-exact', 'turnId': 'turn-exact', 'operation': {'id': 'operation-exact', 'state': 'accepted'}}
        self.runtime = SimpleNamespace(provider=SimpleNamespace(create_thread=create_thread), _lock=threading.RLock(),
                                       state={'sessions': {}, 'runs': {}}, allowed_roots=[], _run_git=AgentRuntime._run_git,
                                       _save=lambda: None, refresh_session=lambda _: {'status': 'completed'})
        self.pipeline = Preparation(Path(self.tmp.name), self.runtime)

    def generate_analysis(self):
        self.pipeline.start(1, {'brief': 'Реальный проект заметок: API, поиск, локальные данные.'})
        folder = Path(self.pipeline.state['stages']['1']['folder'])
        (folder / 'result.json').write_text(json.dumps({'files': {'01_case_analysis.md': '# Анализ\nТребования задания'}}), 'utf-8')
        return self.pipeline.refresh(1)

    def test_session_ids_persist_and_output_requires_explicit_approval(self):
        state = self.generate_analysis()
        self.assertEqual(state['stages']['1']['status'], 'review')
        restored = Preparation(Path(self.tmp.name), self.runtime)
        self.assertEqual(restored.state['stages']['1']['turnId'], 'turn-exact')
        with self.assertRaises(AgentRuntimeError): restored.start(2, {})
        restored.approve(1)
        restored.start(2, {})
        inputs = json.loads((Path(restored.state['stages']['2']['folder']) / 'INPUT.json').read_text('utf-8'))
        self.assertIn('01_case_analysis.md', inputs['artifacts'])

    def test_unconfirmed_is_waiting_not_raw_json_error(self):
        self.pipeline.start(1, {'brief':'Проект каталога'})
        self.runtime.refresh_session=lambda _: {'status':'unconfirmed','lastRefreshEvidence':{'turnStatus':'completed','decision':'unconfirmed'}}
        record=self.pipeline.refresh(1)['stages']['1']
        self.assertEqual('unconfirmed',record['status'])
        self.assertEqual('',record['error'])
        self.assertEqual('completed',record['sessionEvidence']['turnStatus'])
        self.assertIn('повторная отправка не требуется',record['statusMessage'])

    def test_regeneration_invalidates_downstream_approval(self):
        self.generate_analysis()
        self.pipeline.approve(1)
        self.pipeline.state['stages']['2'] = {'status': 'approved', 'files': {'02_research.md': 'old'}}
        self.pipeline.start(1, {'brief': 'Совсем другой проект склада и движения товаров.'})
        self.assertEqual(self.pipeline.state['stages']['2']['status'], 'stale')
        self.assertNotIn('02_research.md', self.pipeline.context(3))

    def test_unsafe_artifacts_and_missing_outputs_do_not_pass(self):
        for name in ('../outside.md', '.git/config', 'C:/secret.md', '/absolute.md', 'mocks\\escape.json'):
            with self.assertRaises(AgentRuntimeError): Preparation.validate({name: 'x'}, 1)
        self.assertTrue(any(c['status'] == 'failed' for c in Preparation.validate({}, 1)))

    def test_unknown_delivery_is_not_resent(self):
        def uncertain(**kwargs): raise TimeoutError('Delivery unknown')
        self.runtime.provider.create_thread = uncertain
        with self.assertRaises(TimeoutError): self.pipeline.start(1, {'brief': 'API заметок с поиском и тегами.'})
        with self.assertRaises(AgentRuntimeError): self.pipeline.start(1, {'brief': 'API заметок с поиском и тегами.'})
        self.assertEqual(self.pipeline.snapshot()['stages']['1']['status'], 'unconfirmed')

    def test_negative_fixture_is_checked_against_schema(self):
        files = {'mocks/fixtures/data.json': '[]', '04_validation_report.md': '# Проверка',
                 'mocks/space.schema.json': json.dumps({'type': 'array'}),
                 'mocks/fixtures/invalid.json': '{}',
                 'mocks/scenarios.json': json.dumps([{'fixture': 'mocks/fixtures/invalid.json', 'schema': 'mocks/space.schema.json', 'expectedValid': False}])}
        self.assertTrue(all(c['status'] == 'passed' for c in Preparation.validate(files, 4)))
        files['mocks/fixtures/invalid.json'] = '[]'
        self.assertTrue(any(c['status'] == 'failed' for c in Preparation.validate(files, 4)))

    def test_development_uses_separate_git_project_and_refuses_dirty_updates(self):
        self.pipeline.state['brief'] = 'Локальный каталог'
        self.pipeline.state['stages'] = {'1': {'status': 'approved', 'files': {'01_case_analysis.md': '# Пользовательский кейс'}},
                                         '4': {'status': 'approved', 'files': {'mocks/fixtures/data.json': '[\n]'}}}
        result = self.pipeline.development()
        project = Path(result['projectRoot'])
        self.assertEqual((project / '01_case_analysis.md').read_text('utf-8'), '# Пользовательский кейс')
        self.assertEqual((project / 'mocks/fixtures/data.json').read_bytes(), b'[\n]')
        self.assertEqual(AgentRuntime._run_git(project, 'status', '--porcelain').strip(), '')
        (project / '01_case_analysis.md').write_text('# Изменение пользователя', 'utf-8')
        self.pipeline.state['stages']['1']['files']['01_case_analysis.md'] = '# Новые требования'
        with self.assertRaises(AgentRuntimeError): self.pipeline.development()
        self.assertEqual((project / '01_case_analysis.md').read_text('utf-8'), '# Изменение пользователя')

    def test_docx_extraction_and_empty_input_rejection(self):
        import io
        import zipfile
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Текст задания</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn('Текст задания', Preparation.extract('brief.docx', data.getvalue())['text'])
        with self.assertRaises(ValueError): Preparation.extract('brief.txt', b'  ')

    def test_scenario_bundle_supports_json_pointer_and_local_schema_refs(self):
        files = {'mocks/fixtures/data.json': '{"fixtures":{"items":[{"id":"one"}],"invalid":[{}]}}',
                 '04_validation_report.md': '# Ещё не проверено',
                 'mocks/schemas/item.schema.json': '{"type":"object","required":["id"]}',
                 'mocks/schemas/list.schema.json': '{"type":"array","items":{"$ref":"item.schema.json"}}'}
        files['mocks/scenarios.json'] = json.dumps({'scenarios': [
            {'fixture': 'mocks/fixtures/data.json#/fixtures/items', 'schema': 'mocks/schemas/list.schema.json', 'expectedValid': True},
            {'fixture': 'mocks/fixtures/data.json#/fixtures/invalid', 'schema': 'mocks/schemas/list.schema.json', 'expectedValid': False}]})
        self.assertTrue(all(c['status'] == 'passed' for c in Preparation.validate(files, 4)))

    def test_rechecking_completed_artifacts_does_not_send_another_prompt(self):
        self.generate_analysis()
        self.pipeline.state['stages']['1'].update(status='failed', error='Previous validator error')
        result = self.pipeline.refresh(1, recheck=True)
        self.assertEqual(result['stages']['1']['status'], 'review')
        self.assertNotIn('error', result['stages']['1'])
        self.assertEqual(len(self.calls), 1)

    def test_stage_six_requires_integrated_approved_prototype(self):
        self.pipeline.state['stages']['4'] = {'status': 'approved', 'files': {}}
        with self.assertRaises(AgentRuntimeError): self.pipeline.development(6)
        with self.assertRaises(AgentRuntimeError): self.pipeline.approve_prototype()

    def test_tasks_cannot_pass_descriptions_as_mock_paths(self):
        task = {'id': 'T1', 'title': 'Каталог', 'goal': 'Показать каталог', 'acceptance': 'Данные возвращаются',
                'dependsOn': [], 'contracts': ['GET /items'], 'mocks': ['Описание будущей заглушки'],
                'allowedPaths': ['src/catalog.py'], 'builderPrompt': 'Реализуй', 'testPrompt': 'Проверь', 'reviewerPrompt': 'Проведи ревью'}
        files = {'03_architecture.md': '# Архитектура', '03_test_plan.md': '# План',
                 '03_tasks.json': json.dumps([task]), '03_contracts/openapi.yaml': 'openapi: 3.0.3\npaths: {}'}
        with self.assertRaisesRegex(ValueError, 'mocks должен содержать пути'):
            Preparation.validate(files, 3)
        task['mocks'] = ['mocks/fixtures/data.json']
        files['03_tasks.json'] = json.dumps([task])
        self.assertTrue(all(c['status'] == 'passed' for c in Preparation.validate(files, 3)))

    def test_two_local_servers_cannot_own_the_same_port(self):
        from makora_core.server import LocalHTTPServer, MakoraHandler
        with LocalHTTPServer(('127.0.0.1', 0), MakoraHandler) as first:
            with self.assertRaises(OSError):
                LocalHTTPServer(first.server_address, MakoraHandler)

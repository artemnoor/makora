import copy
import io
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from makora_core.project_workflow import ProjectWorkflow, ORDER
from makora_core.agents.runtime import AgentRuntimeError
from makora_core.laboratories import validate_execution, laboratory_state


def graph():
    def task(ident, paths, deps):
        return {'id': ident, 'title': ident, 'goal': 'Реализовать', 'acceptance': 'Проверить',
                'allowedPaths': paths, 'dependsOn': deps, 'contracts': ['03_contracts/openapi.yaml'],
                'mocks': ['mocks/fixtures/data.json'], 'builderPrompt': 'Реализуй', 'testPrompt': 'Проверь', 'reviewerPrompt': 'Проверь'}
    tasks = [task('BASE', ['src/shell.js'], []), task('MAIN', ['src/home.js'], ['BASE']),
             task('FEATURE', ['src/feature.js', 'labs/LAB/preview.mjs', 'labs/LAB/index.html'], ['BASE']),
             task('JOIN', ['src/connect.js'], ['MAIN', 'FEATURE'])]
    execution = {'skeletonTaskId': 'BASE', 'laboratories': [{'id': 'LAB', 'title': 'Сложная функция',
        'taskIds': ['FEATURE'], 'uiRoot': 'labs/LAB/', 'previewCommand': ['node', 'labs/LAB/preview.mjs'],
        'mockFixture': 'mocks/fixtures/data.json', 'integrationTaskId': 'JOIN'}]}
    return tasks, execution


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = SimpleNamespace(create_thread=Mock(return_value={'id': 'chat', 'turnId': 'turn', 'model': 'gpt-6-astra',
            'transport': 'desktop', 'operation': {'id': 'op', 'state': 'accepted'}}), send=Mock(), history=Mock(return_value={'turns': []}))
        self.runtime = SimpleNamespace(provider=self.provider, _lock=threading.RLock(), state={'sessions': {}, 'runs': {}},
                                       allowed_roots=[], _save=lambda: None, refresh_session=lambda _: {'status': 'completed'})
        self.pipeline = ProjectWorkflow(Path(self.temp.name), self.runtime)
        self.pipeline.upgrade_workflow()
        self.pipeline.state['brief'] = 'Создать каталог событий. Не использовать реальные персональные данные.'

    def approve_before(self, stage):
        for previous in self.pipeline.required_stages(stage):
            if previous == 6:
                self.pipeline.state['returnedProject'] = {'status': 'prepared'}
            else:
                self.pipeline.state['stages'][str(previous)] = {'status': 'approved', 'files': {}}
                if previous == 0:
                    self.pipeline.state['stages']['0']['caseConstraints'] = []

    def test_new_order_and_first_stage_blocks_analogs_until_approved(self):
        self.assertEqual([0], self.pipeline.available_stages(self.pipeline.state))
        self.assertEqual(ORDER, self.pipeline.snapshot()['stageOrder'])
        with self.assertRaises(AgentRuntimeError): self.pipeline.start(2, {})
        with self.assertRaises(AgentRuntimeError): self.pipeline.start(1, {})
        self.pipeline.start(0, {})
        self.assertIn('этап 1', self.provider.create_thread.call_args.kwargs['prompt'])
        self.assertTrue(self.provider.create_thread.call_args.kwargs['desktop'])

    def test_only_verbatim_case_constraints_are_accepted(self):
        record = {}
        self.pipeline.result_ready(0, {'constraints': []}, record)
        self.assertEqual([], record['caseConstraints'])
        quote = 'Не использовать реальные персональные данные.'
        self.pipeline.result_ready(0, {'constraints': [{'quote': quote}]}, record)
        self.assertEqual(quote, record['caseConstraints'][0]['quote'])
        with self.assertRaises(ValueError): self.pipeline.result_ready(0, {'constraints': [{'quote': 'Проект обязательно должен использовать Python.'}]}, record)

    def test_pdf_line_wraps_and_nonbreaking_spaces_preserve_source_quote(self):
        source = 'В состав задачи не входят: вакансии\u00a0и стажировки,\nрейтинги студентов и\n баллы.'
        self.pipeline.state['brief'] = 'Описание проекта.\n' + source
        record = {}
        quote = 'В состав задачи не входят: вакансии и стажировки, рейтинги студентов и баллы.'
        self.pipeline.result_ready(0, {'constraints': [{'quote': quote, 'locator': 'Страница 2'}]}, record)
        self.assertEqual(source, record['caseConstraints'][0]['quote'])
        self.assertEqual('Страница 2', record['caseConstraints'][0]['locator'])
        previous = copy.deepcopy(record)
        with self.assertRaises(ValueError):
            self.pipeline.result_ready(0, {'constraints': [{'quote': quote.replace('не входят', 'входят обязательно')}]}, record)
        self.assertEqual(previous, record)

    def test_constraint_numbers_cannot_change_during_whitespace_matching(self):
        self.pipeline.state['brief'] = 'Ограничение: не более\n 10 записей.'
        with self.assertRaises(ValueError):
            self.pipeline.result_ready(0, {'constraints': [{'quote': 'Ограничение: не более 100 записей.'}]}, {})

    def test_brainstorm_publishes_only_after_ready_and_separate_human_confirmation(self):
        self.approve_before(3)
        self.pipeline.start(3, {})
        record = self.pipeline.state['stages']['3']
        folder = Path(record['folder'])
        versions = {'versions': [{'id': 'v1', 'goal': 'Поиск событий', 'entryScreen': 'home',
            'screens': [{'id': 'home', 'title': 'Каталог', 'content': 'Карточки и поиск', 'next': []}]}]}
        files = {'02_user_idea.md': '# Идея пользователя', '02_versions_and_screens.md': '# Версия 1\nКаталог',
                 '02_versions_and_screens.json': json.dumps(versions)}
        (folder/'result.json').write_text(json.dumps({'files': files, 'userConfirmed': True}), 'utf-8')
        self.pipeline.refresh(3)
        self.assertEqual('awaiting_idea', record['status'])
        self.assertEqual({}, record['files'])
        self.provider.history.return_value = {'turns': [{'status': 'completed', 'items': [{'role': 'user', 'text': 'готово'}]},
            {'status': 'completed', 'items': [{'role': 'user', 'text': 'Да'}]}]}
        self.pipeline.refresh(3)
        self.assertEqual('review', record['status'])
        self.assertTrue(record['brainstormConfirmed'])
        self.assertEqual(files, record['files'])

    def test_package_needs_idea_and_mocks_but_not_old_analysis_or_planning(self):
        self.approve_before(6)
        self.pipeline.state['stages']['3']['files'] = {'02_user_idea.md': 'Моя идея'}
        self.pipeline.state['stages']['5']['files'] = {'mocks/fixtures/data.json': '{}'}
        with zipfile.ZipFile(io.BytesIO(self.pipeline.archive())) as archive:
            self.assertIn('02_user_idea.md', archive.namelist())
            self.assertNotIn('03_tasks.json', archive.namelist())
        self.assertEqual([0, 2, 3, 5, 6], self.pipeline.available_stages(self.pipeline.state))
        self.pipeline.state['returnedProject'] = {'status': 'prepared'}
        self.assertEqual(4, self.pipeline.available_stages(self.pipeline.state)[-1])

    def test_reordered_context_and_invalidation(self):
        self.approve_before(4)
        self.pipeline.state['stages']['5']['files'] = {'mocks/fixtures/data.json': '{}'}
        self.assertIn('mocks/fixtures/data.json', self.pipeline.context(4))
        self.assertIn(4, self.pipeline.downstream_stages(5))
        self.assertNotIn(5, self.pipeline.downstream_stages(4))

    def test_versions_require_complete_screens_and_valid_navigation(self):
        with self.assertRaises(ValueError): self.pipeline.validate_versions({'versions': []})
        with self.assertRaises(ValueError): self.pipeline.validate_versions({'versions': [{'id': 'v1', 'goal': 'Demo', 'entryScreen': 'missing',
            'screens': [{'id': 'home', 'title': 'Дом', 'content': 'Текст', 'next': ['unknown']}]}]})

    def test_mocks_cover_all_agreed_screens_and_versions(self):
        self.approve_before(5)
        versions = {'versions': [{'id': 'v1', 'goal': 'Demo', 'entryScreen': 'home',
            'screens': [{'id': 'home', 'title': 'Каталог', 'content': 'Карточки', 'next': []}]}]}
        self.pipeline.state['stages']['3']['files'] = {'02_versions_and_screens.json': json.dumps(versions)}
        files = {'mocks/fixtures/data.json': '{"items":[]}', 'mocks/item.schema.json': '{"type":"object"}',
            'mocks/scenarios.json': json.dumps({'scenarios': [{'fixture': 'mocks/fixtures/data.json', 'schema': 'mocks/item.schema.json', 'expectedValid': True}]}),
            '04_validation_report.md': '# Проверка', 'mocks/screens.json': '{"screens":[]}'}
        with self.assertRaisesRegex(ValueError, 'каждый экран'):
            self.pipeline.validate(files, 5)
        files['mocks/screens.json'] = json.dumps({'screens': [{'versionId': 'v1', 'screenId': 'home', 'fixtures': ['mocks/fixtures/data.json']}]})
        self.assertTrue(all(c['status'] == 'passed' for c in self.pipeline.validate(files, 5)))

    def test_execution_edits_preserve_mocks_and_require_new_approval(self):
        self.approve_before(4)
        self.pipeline.state['stages']['5']['files'] = {'mocks/fixtures/data.json': '{}'}
        tasks, execution = graph()
        files = {'03_architecture.md': '# Архитектура', '03_contracts/openapi.yaml': 'openapi: 3.0.3\npaths: {}',
            '03_test_plan.md': '# Проверки', '03_tasks.json': json.dumps({'tasks': tasks}), '03_execution.json': json.dumps(execution)}
        self.pipeline.state['stages']['4'] = {'status': 'approved', 'files': copy.deepcopy(files)}
        result = self.pipeline.save_execution({'tasks': tasks, 'execution': execution})
        self.assertEqual('review', result['stages']['4']['status'])
        self.assertEqual('approved', result['stages']['5']['status'])
        self.assertEqual('4', str(self.pipeline.available_stages(self.pipeline.state)[-1]))
        old = copy.deepcopy(self.pipeline.state)
        broken = copy.deepcopy(tasks)
        broken[0]['dependsOn'] = ['JOIN']
        with self.assertRaises(AgentRuntimeError): self.pipeline.save_execution({'tasks': broken, 'execution': execution})
        self.assertEqual(old, self.pipeline.state)

    def test_migration_keeps_legacy_documents_and_chats(self):
        self.pipeline.state.update(workflowVersion=2, stages={
            '1': {'status': 'approved', 'files': {'01_case_analysis.md': 'Старый анализ'}, 'threadId': 'old-analysis'},
            '3': {'status': 'approved', 'files': {'02_solution_concept.md': 'Старая идея'}, 'threadId': 'old-idea'}})
        self.pipeline.upgrade_workflow()
        self.assertEqual('Старый анализ', self.pipeline.state['stages']['1']['files']['01_case_analysis.md'])
        self.assertEqual('old-idea', self.pipeline.state['stages']['3']['threadId'])
        self.assertEqual('stale', self.pipeline.state['stages']['3']['status'])


class LaboratoryGraphTests(unittest.TestCase):
    def test_skeleton_parallel_labs_and_mock_until_connection(self):
        tasks, execution = graph()
        validate_execution(tasks, execution, {'mocks/fixtures/data.json': '{}'})
        run = {'tasks': [dict(t, status='pending') for t in tasks], 'execution': execution}
        self.assertEqual('mock', laboratory_state(run)[0]['dataSource'])
        run['tasks'][2]['status'] = 'integrated'
        self.assertEqual('mock', laboratory_state(run)[0]['dataSource'])
        run['tasks'][3]['status'] = 'integrated'
        self.assertEqual('feature', laboratory_state(run)[0]['dataSource'])

    def test_cycles_missing_mock_and_preview_in_production_scope_are_rejected(self):
        tasks, execution = graph()
        with self.assertRaises(ValueError): validate_execution(tasks, execution, {})
        tasks[0]['dependsOn'] = ['JOIN']
        with self.assertRaises(AgentRuntimeError): validate_execution(tasks, execution)
        tasks, execution = graph()
        execution['laboratories'][0]['previewCommand'] = ['node', '../escape.js']
        with self.assertRaises(ValueError): validate_execution(tasks, execution)

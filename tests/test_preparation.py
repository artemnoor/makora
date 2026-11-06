import json
import tempfile
import threading
import unittest
from unittest.mock import patch
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
        self.sends = []
        def send(thread_id, text, **kwargs):
            self.sends.append((thread_id, text, kwargs))
            return {'threadId': thread_id, 'turnId': 'turn-followup-' + str(len(self.sends)),
                    'operation': {'id': 'operation-followup-' + str(len(self.sends)), 'state': 'accepted'}}
        self.runtime = SimpleNamespace(provider=SimpleNamespace(create_thread=create_thread, send=send), _lock=threading.RLock(),
                                       state={'sessions': {}, 'runs': {}}, allowed_roots=[], _run_git=AgentRuntime._run_git,
                                       _save=lambda: None, refresh_session=lambda _: {'status': 'completed'})
        self.pipeline = Preparation(Path(self.tmp.name), self.runtime)

    def test_chat_is_readonly_deduplicated_and_uses_exact_turn(self):
        folder=self.select_folder()
        self.pipeline.state['brief']='Project notes and search'
        self.pipeline.state['stages']={'1':{'status':'approved','files':{'01_case_analysis.md':'# Notes requirements'}}}
        result=self.pipeline.send_chat({'message':'Что нужно сделать?','requestId':'chat-1'})
        self.assertEqual('running',result['status'])
        self.assertEqual('readOnly',self.calls[-1]['sandbox'])
        self.assertIn('Notes requirements',(self.calls[-1]['cwd']/'CONTEXT.json').read_text('utf-8'))
        self.pipeline.send_chat({'message':'Что нужно сделать?','requestId':'chat-1'})
        self.assertEqual(1,len(self.calls))
        with self.assertRaises(AgentRuntimeError):self.pipeline.send_chat({'message':'Второй вопрос','requestId':'chat-2'})
        self.runtime.refresh_session=lambda _: {'status':'completed','turnId':'turn-exact','result':{'turns':[
            {'id':'older-turn','items':[{'type':'agentMessage','text':'Old answer'}]},
            {'id':'turn-exact','items':[{'type':'agentMessage','text':'Создать API заметок.'}]}]}}
        result=self.pipeline.chat_snapshot()
        self.assertEqual('idle',result['status'])
        self.assertEqual('Создать API заметок.',result['messages'][-1]['text'])
        self.assertEqual(2,len(self.pipeline.chat_snapshot()['messages']))
        self.assertEqual('approved',self.pipeline.state['stages']['1']['status'])
        self.assertIn('Создать API заметок.',(folder/'reports/chat.md').read_text('utf-8'))

    def test_chat_uses_codex_tools_on_a_bounded_project_snapshot(self):
        folder = self.select_folder()
        project = folder / 'app'
        project.mkdir()
        (project / 'main.py').write_text('PROJECT_MARKER = 42', encoding='utf-8')
        (project / '.env').write_text('SECRET_MARKER', encoding='utf-8')
        self.pipeline.state['brief'] = 'Project context and actual code'
        self.pipeline.send_chat({'message': 'Где находится реализация?', 'requestId': 'test-context'})
        call = self.calls[-1]
        self.assertEqual('readOnly', call['sandbox'])
        self.assertIn('project-source/', call['prompt'])
        self.assertNotIn('не выполняй команды', call['prompt'])
        self.assertNotIn('Контекст проекта (полная версия', call['prompt'])
        snapshot = next((call['cwd'] / 'snapshots').iterdir()) / 'project-source'
        self.assertIn('PROJECT_MARKER', (snapshot / 'main.py').read_text('utf-8'))
        self.assertFalse((snapshot / '.env').exists())
        self.assertTrue((call['cwd'] / 'CONTEXT.json').is_file())

    def test_chat_followup_reuses_session_and_unconfirmed_delivery_does_not_repeat(self):
        self.pipeline.send_chat({'message':'Первый вопрос','requestId':'chat-1'})
        chat=self.pipeline.state['chat'];chat['status']='idle'
        sent=[]
        def send(agent_id,text):
            sent.append((agent_id,text))
            return {'id':agent_id,'threadId':'thread-exact','turnId':'second-turn'}
        self.runtime.send_message=send
        self.pipeline.send_chat({'message':'А какие ограничения?','requestId':'chat-2'})
        self.assertEqual(1,len(self.calls))
        self.assertEqual(1,len(sent))
        self.assertEqual('second-turn',self.pipeline.state['chat']['turnId'])
        self.runtime.refresh_session=lambda _: {'status':'completed','turnId':'turn-exact','result':{'turns':[{'id':'turn-exact','items':[{'type':'agentMessage','text':'Old answer'}]}]}}
        self.assertEqual('unconfirmed',self.pipeline.chat_snapshot()['status'])
        self.assertEqual(2,len(self.pipeline.state['chat']['messages']))
        restored=Preparation(Path(self.tmp.name),self.runtime)
        self.assertEqual('unconfirmed',restored.state['chat']['status'])
        restored.send_chat({'message':'А какие ограничения?','requestId':'chat-2'})
        self.assertEqual(1,len(sent))

    def test_chat_unknown_delivery_is_persisted_and_never_resent(self):
        attempts=[]
        def fail(**kwargs):
            attempts.append(kwargs)
            raise AgentRuntimeError('DELIVERY_UNKNOWN','Connection lost after dispatch',502)
        self.runtime.provider.create_thread=fail
        with self.assertRaises(AgentRuntimeError):self.pipeline.send_chat({'message':'Вопрос','requestId':'uncertain'})
        restored=Preparation(Path(self.tmp.name),self.runtime)
        result=restored.send_chat({'message':'Вопрос','requestId':'uncertain'})
        self.assertEqual('unconfirmed',result['status'])
        self.assertEqual(1,len(attempts))
        self.assertEqual(1,len(result['messages']))

    def test_chat_recovery_unlocks_without_resending_or_losing_history(self):
        self.pipeline.state['chat'] = {'status': 'unconfirmed', 'messages': [
            {'id': 'm1', 'role': 'assistant', 'text': 'Previous answer'},
            {'id': 'm2', 'role': 'user', 'text': 'Uncertain question', 'requestId': 'r2'}],
            'sessionId': 'old-session', 'turnId': None, 'threadId': 'old-thread'}
        result = self.pipeline.recover_chat()
        self.assertEqual('idle', result['status'])
        self.assertNotIn('sessionId', result)
        self.assertEqual(2, len(result['messages']))
        self.assertEqual('unconfirmed', result['messages'][-1]['deliveryState'])
        self.assertEqual([], self.calls)
        restored = Preparation(Path(self.tmp.name), self.runtime)
        self.assertEqual('idle', restored.chat_snapshot()['status'])
        restored.send_chat({'message': 'Continue conversation', 'requestId': 'r3'})
        self.assertEqual(1, len(self.calls))
        self.assertIn('Previous answer', self.calls[-1]['prompt'])
        self.assertEqual('readOnly', self.calls[-1]['sandbox'])

    def test_chat_missing_turn_can_only_bind_using_same_operation(self):
        self.pipeline.state['chat'] = {'status': 'unconfirmed', 'messages': [], 'sessionId': 'agent',
                                      'turnId': None, 'operationId': 'new-op', 'previousTurnId': 'old-turn'}
        self.runtime.refresh_session = lambda _: {'status': 'completed', 'operationId': 'old-op', 'turnId': 'old-turn',
            'result': {'turns': [{'id': 'old-turn', 'items': [{'type': 'agentMessage', 'text': 'Stale reply'}]}]}}
        self.assertEqual('unconfirmed', self.pipeline.chat_snapshot()['status'])
        self.assertEqual([], self.pipeline.state['chat']['messages'])
        self.runtime.refresh_session = lambda _: {'status': 'completed', 'operationId': 'new-op', 'turnId': 'new-turn',
            'result': {'turns': [{'id': 'new-turn', 'items': [{'type': 'agentMessage', 'text': 'Confirmed reply'}]}]}}
        result = self.pipeline.chat_snapshot()
        self.assertEqual('idle', result['status'])
        self.assertEqual('Confirmed reply', result['messages'][-1]['text'])

    def test_chat_recovery_does_not_detach_a_known_running_request(self):
        self.pipeline.state['chat'] = {'status': 'running', 'messages': [], 'sessionId': 'active'}
        with self.assertRaises(AgentRuntimeError):
            self.pipeline.recover_chat()
        self.assertEqual('active', self.pipeline.state['chat']['sessionId'])

    def select_folder(self):
        folder=Path(self.tmp.name)/'chosen-project'
        folder.mkdir()
        with patch.object(Preparation, '_pick_directory', return_value=str(folder)):
            result=self.pipeline.choose_directory()
        self.assertEqual(result['path'],str(folder.resolve()))
        return folder.resolve()

    def test_selected_storage_preserves_original_artifacts_reports_and_restart(self):
        folder=self.select_folder()
        original=b'\xef\xbb\xbfOriginal brief with enough detail.'
        self.pipeline.store_source('brief.txt',original)
        self.pipeline.store_source('notes.md',b'# Extra requirements',attachment=True)
        self.assertEqual(self.pipeline.state['sourceFile'],'input/original/brief.txt')
        self.assertEqual((folder/self.pipeline.state['attachments'][0]).read_bytes(),b'# Extra requirements')
        self.generate_analysis()
        self.assertEqual((folder/'input/original/brief.txt').read_bytes(),original)
        self.assertNotEqual((folder/'input/brief.txt').read_bytes(),original)
        self.assertTrue((folder/'artifacts/01_case_analysis.md').is_file())
        self.assertEqual(json.loads((folder/'reports/stage-1-checks.json').read_text('utf-8'))['status'],'review')
        self.assertTrue(Path(self.pipeline.state['stages']['1']['folder']).is_relative_to(folder))
        restored=Preparation(Path(self.tmp.name),self.runtime)
        self.assertEqual(restored.state['storageRoot'],str(folder.resolve()))
        self.assertEqual(restored.root,folder/'.makora/preparation')
        self.assertEqual(restored.project_directory(),folder/'app')
        self.assertEqual(restored.state['stages']['1']['status'],'review')

    def test_folder_cancel_and_nonempty_selection_preserve_current_project(self):
        previous=self.pipeline.snapshot()
        with patch.object(Preparation,'_pick_directory',return_value=''):
            self.assertTrue(self.pipeline.choose_directory()['cancelled'])
        folder=Path(self.tmp.name)/'existing';folder.mkdir();(folder/'keep.txt').write_text('keep')
        with patch.object(Preparation,'_pick_directory',return_value=str(folder)):
            with self.assertRaises(AgentRuntimeError):self.pipeline.choose_directory()
        self.assertEqual(previous,self.pipeline.snapshot())
        self.assertEqual((folder/'keep.txt').read_text(),'keep')

    def test_source_requires_folder_and_cannot_escape_it(self):
        with self.assertRaises(AgentRuntimeError):self.pipeline.store_source('case.txt',b'original')
        folder=self.select_folder()
        for name in ('../case.txt','C:\\case.txt','x/y.md'):
            with self.assertRaises(AgentRuntimeError):self.pipeline.store_source(name,b'original')
        self.assertFalse((folder/'case.txt').exists())

    def test_handoff_contains_prompt_original_and_approved_files_without_running_agents(self):
        folder=self.select_folder()
        original=b'# Original case'
        self.pipeline.store_source('case.md',original)
        self.pipeline.state['brief']='Create local notes'
        self.pipeline.state['stages']={'1':{'status':'approved','files':{'01_case_analysis.md':'# Analysis'}},'4':{'status':'approved','files':{'mocks/fixtures/data.json':'[]'}}}
        result=self.pipeline.handoff_package()
        self.assertIn('new_mocks/',result['prompt'])
        for required in ('полноценный работающий веб-сайт', 'страницы', 'скачиваемый ZIP-архив',
                         'исходным кодом', 'стилями', 'ресурсами', 'файлами зависимостей', 'README.md'):
            self.assertIn(required, result['prompt'])
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(self.pipeline.archive())) as archive:
            self.assertEqual(result['prompt'], archive.read('PROMPT.md').decode('utf-8'))
        self.assertIn('input/original/case.md',[f['path'] for f in result['files']])
        self.assertIn('mocks/fixtures/data.json',result['documents'])
        self.assertFalse((folder/'app').exists())
        self.assertEqual([],self.calls)
        self.assertTrue((folder/'exports/project-context.zip').exists())

    def test_development_and_archive_live_in_selected_folder(self):
        folder=self.select_folder()
        self.pipeline.state['brief']='Local catalog project'
        self.pipeline.state['stages']={'1':{'status':'approved','files':{'01_case_analysis.md':'# Requirements'}},'4':{'status':'approved','files':{'mocks/fixtures/data.json':'[]'}}}
        result=self.pipeline.development()
        self.assertEqual(Path(result['projectRoot']),folder/'app')
        self.assertTrue((folder/'exports/project-context.zip').is_file())
        self.assertTrue((folder/'artifacts/PROMPT.md').is_file())
        self.assertEqual((folder/'app/mocks/fixtures/data.json').read_text(),'[]')
        self.assertEqual(AgentRuntime._run_git(folder/'app','status','--porcelain').strip(),'')

    def test_returned_zip_is_preserved_and_survives_restart_without_running_code(self):
        from makora_core.iterations import zip_files
        folder = self.select_folder()
        self.pipeline.state['stages'] = {'4': {'status': 'approved', 'files': {'mocks/fixtures/data.json': '[]'}}}
        blob = zip_files({'site/index.html': b'<h1>Site</h1>', 'site/mocks/fixtures/data.json': b'[]'})
        result = self.pipeline.receive_project('site.zip', blob)
        self.assertEqual('received', result['status'])
        self.assertEqual(2, result['fileCount'])
        self.assertEqual('passed', result['mocksStatus'])
        self.assertEqual(blob, (folder / result['path']).read_bytes())
        restored = Preparation(Path(self.tmp.name), self.runtime)
        self.assertEqual(result, restored.snapshot()['returnedProject'])
        self.assertEqual(blob, restored.returned_project_archive())
        self.assertFalse((folder / 'app').exists())
        self.assertEqual([], self.calls)

    def test_invalid_return_does_not_replace_previous_zip(self):
        from makora_core.iterations import zip_files
        from makora_core.workspace import MakoraError
        self.pipeline.state['stages'] = {'4': {'status': 'approved', 'files': {'mocks/fixtures/data.json': '[]'}}}
        blob = zip_files({'index.html': b'Site'})
        result = self.pipeline.receive_project('site.zip', blob)
        self.assertEqual('changed', result['mocksStatus'])
        import io
        import zipfile
        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, 'w') as archive:
            archive.writestr('../escape.txt', b'bad')
        for invalid in (b'not a ZIP', unsafe.getvalue()):
            with self.assertRaises(MakoraError):
                self.pipeline.receive_project('bad.zip', invalid)
        self.assertEqual(blob, self.pipeline.returned_project_archive())

    def test_continue_imports_uploaded_site_for_stage_six_without_claiming_approval(self):
        from makora_core.iterations import zip_files
        self.pipeline.state['stages'] = {'4': {'status': 'approved', 'files': {'mocks/fixtures/data.json': '[]'}}}
        self.pipeline.receive_project('site.zip', zip_files({'index.html': b'<h1>Uploaded</h1>', 'mocks/fixtures/data.json': b'[]'}))
        result = self.pipeline.continue_returned_project()
        project = self.pipeline.project_directory()
        self.assertEqual(b'<h1>Uploaded</h1>', (project / 'index.html').read_bytes())
        self.assertNotIn('prototype', result)
        developed = self.pipeline.development(6)
        self.assertEqual(str(project), developed['projectRoot'])
        self.assertEqual(b'<h1>Uploaded</h1>', (project / 'index.html').read_bytes())
        self.assertEqual(project, Path(self.pipeline.continue_returned_project()['returnedProject']['projectRoot']))
        self.assertEqual([], self.calls)

    def test_continue_rejects_changed_mocks_and_git_metadata(self):
        from makora_core.iterations import zip_files
        self.pipeline.state['stages'] = {'4': {'status': 'approved', 'files': {'mocks/fixtures/data.json': '[]'}}}
        for files in ({'index.html': b'Site'}, {'index.html': b'Site', 'mocks/fixtures/data.json': b'[]', '.git/config': b'bad'}):
            self.pipeline.receive_project('site.zip', zip_files(files))
            with self.assertRaises(AgentRuntimeError):
                self.pipeline.continue_returned_project()
            self.assertEqual('received', self.pipeline.state['returnedProject']['status'])

    def test_returned_zip_http_requires_auth_and_downloads_original_bytes(self):
        import urllib.request
        import urllib.error
        from http.server import ThreadingHTTPServer
        from makora_core.server import MakoraHandler
        from makora_core.iterations import zip_files
        self.pipeline.state['stages'] = {'4': {'status': 'approved', 'files': {}}}
        server = ThreadingHTTPServer(('127.0.0.1', 0), MakoraHandler)
        server.preparation = self.pipeline
        server.agent_token = 'test-token'
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/api/preparation/result'
            blob = zip_files({'index.html': b'<h1>Site</h1>'})
            request = urllib.request.Request(url+'?name=site.zip', data=blob, headers={'Content-Type': 'application/zip'})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(401, error.exception.code)
            request.add_header('X-Makora-Token', 'test-token')
            with urllib.request.urlopen(request) as response:
                result = json.load(response)['result']
            self.assertEqual('site.zip', result['name'])
            with urllib.request.urlopen(url) as response:
                self.assertEqual('application/zip', response.headers['Content-Type'])
                self.assertEqual(blob, response.read())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

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

    def test_preparation_groups_survive_restart_and_stage_four_is_separate(self):
        created = []
        def create(**kwargs):
            created.append(kwargs)
            return {'id': 'desktop-' + str(len(created)), 'turnId': 'turn-' + str(len(created)),
                    'transport': 'desktop', 'operation': {'id': 'op-' + str(len(created)), 'state': 'accepted'}}
        self.runtime.provider.create_thread = create
        self.pipeline.start(1, {'brief': 'Проверка общего чата анализа, идеи и плана.'})
        first = self.pipeline.state['stages']['1']
        task = json.loads((Path(first['folder']) / 'TASK.json').read_text('utf-8'))
        self.assertEqual(['01_case_analysis.md'], task['requiredFiles'])
        self.assertTrue(Path(task['protocol']).is_file())
        self.assertLess(len(created[0]['prompt']), 600)
        self.assertFalse((Path(first['folder']) / 'INSTRUCTIONS.md').exists())
        self.pipeline.state['stages']['1'].update(status='approved', files={})
        self.pipeline.save()
        restored = Preparation(Path(self.tmp.name), self.runtime)
        restored.start(2, {})
        second = restored.state['stages']['2']
        self.assertEqual(first['threadId'], second['threadId'])
        self.assertNotEqual(first['turnId'], second['turnId'])
        restored.state['stages']['2'].update(status='approved', files={})
        restored.start(3, {})
        self.assertEqual(first['threadId'], restored.state['stages']['3']['threadId'])
        restored.state['stages']['3'].update(status='approved', files={})
        restored.start(4, {})
        self.assertNotEqual(first['threadId'], restored.state['stages']['4']['threadId'])
        self.assertEqual(2, len(created))
        self.assertEqual(2, len(self.sends))
        self.assertTrue(all(options.get('desktop') for _, _, options in self.sends))

    def test_changed_brief_starts_a_new_preparation_chat(self):
        self.pipeline.start(1, {'brief': 'Исходное условие проекта заметок.'})
        self.pipeline.state['stages']['1']['status'] = 'review'
        self.pipeline.start(1, {'brief': 'Другое условие проекта каталога.'})
        self.assertEqual(2, len(self.calls))
        self.assertEqual(0, len(self.sends))

    def test_missing_ids_recovers_only_matching_completed_turn(self):
        def missing(**kwargs):
            return {'id': 'desktop-thread', 'transport': 'desktop', 'operation': {'id': 'op'}}
        self.runtime.provider.create_thread = missing
        with self.assertRaises(AgentRuntimeError):
            self.pipeline.start(1, {'brief': 'Проект каталога с поиском'})
        record = self.pipeline.state['stages']['1']
        folder = Path(record['folder'])
        (folder / 'result.json').write_text(json.dumps({'files': {'01_case_analysis.md': '# Анализ'}}), 'utf-8')
        self.runtime.provider.history = lambda _: {'turns': [{'id': 'actual-turn', 'status': 'completed', 'items': [
            {'role': 'user', 'text': str(folder / 'TASK.json')},
            {'role': 'assistant', 'phase': 'final_answer', 'text': 'Готово'}]}]}
        matching = self.runtime.provider.history
        self.runtime.provider.history = lambda _: {'turns': [{'id': 'wrong', 'status': 'completed', 'items': [
            {'role': 'user', 'text': 'another task'}, {'role': 'assistant', 'phase': 'final_answer', 'text': 'Готово'}]}]}
        self.assertEqual('unconfirmed', self.pipeline.refresh(1)['stages']['1']['status'])
        self.runtime.provider.history = matching
        self.assertEqual('review', self.pipeline.refresh(1)['stages']['1']['status'])
        self.assertEqual('actual-turn', record['turnId'])

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

    def test_scenario_index_follows_local_file_and_checks_actual_payload(self):
        files={'mocks/fixtures/data.json':'{"cases":[{"payload":{"id":"ok"}},{"payload":{}}]}',
               '04_validation_report.md':'# Проверки', 'mocks/item.schema.json':'{"$defs":{"Item":{"type":"object","required":["id"]}}}',
               'mocks/scenarios.json':'{"scenariosFile":"mocks/scenarios/items.json"}',
               'mocks/scenarios/items.json':json.dumps({'scenarios':[
                   {'id':'valid','fixture':'mocks/fixtures/data.json#/cases/0/payload','schema':'mocks/item.schema.json#/$defs/Item','expectedValid':True},
                   {'id':'invalid','fixture':'mocks/fixtures/data.json#/cases/1/payload','schema':'mocks/item.schema.json#/$defs/Item','expectedValid':False}]})}
        self.assertTrue(all(c['status']=='passed' for c in Preparation.validate(files,4)))
        files['mocks/fixtures/data.json']='{"cases":[{"payload":{"id":"ok"}},{"payload":{"id":"also-valid"}}]}'
        self.assertTrue(any(c['status']=='failed' for c in Preparation.validate(files,4)))
        files['mocks/scenarios/items.json']='{"scenariosFile":"mocks/scenarios.json"}'
        with self.assertRaisesRegex(ValueError,'Цикл'):Preparation.validate(files,4)
        files['mocks/scenarios/items.json']='{"scenariosFile":"https://example.com/scenarios.json"}'
        with self.assertRaisesRegex(ValueError,'внутри mocks'):Preparation.validate(files,4)

    def test_failed_validation_keeps_generated_files_for_inspection(self):
        self.pipeline.start(1,{'brief':'Проверка сохранения документов'})
        record=self.pipeline.state['stages']['1']
        (Path(record['folder'])/'result.json').write_text('{"files":{"unexpected.json":"not JSON"}}','utf-8')
        result=self.pipeline.refresh(1)['stages']['1']
        self.assertEqual('failed',result['status'])
        self.assertIn('unexpected.json',result['files'])

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

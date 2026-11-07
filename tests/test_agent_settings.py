import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from makora_core.agents.runtime import AgentRuntime, AgentRuntimeError, CodexLocalApi, MODEL_ID
from makora_core.preparation import Preparation


CATALOG = [
    {'id': MODEL_ID, 'model': MODEL_ID, 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'medium'}]},
    {'id': 'other-model', 'model': 'other-model', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]},
]


class AgentSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.provider = Mock()
        self.provider.model_catalog.return_value = CATALOG
        self.provider.create_thread.return_value = {'id': 't1', 'turnId': 'turn1', 'operation': {'id': 'o1', 'state': 'accepted'}}
        self.runtime = AgentRuntime(self.base / 'workspace', self.base, [], self.provider)

    def profile(self):
        value = self.runtime.agent_profile(self.project)
        value['preparation'] = {'model': MODEL_ID, 'reasoningEffort': 'low'}
        value['project_chat'] = {'model': MODEL_ID, 'reasoningEffort': 'low'}
        value['mahoraga'] = {'model': 'other-model', 'reasoningEffort': 'high'}
        value['mahoraga_orchestrator'] = {'model': 'other-model', 'reasoningEffort': 'high'}
        value['builder'] = {'model': 'other-model', 'reasoningEffort': 'high'}
        return value

    def test_role_settings_persist_and_are_scoped_to_project(self):
        self.runtime.set_agent_profile(self.project, self.profile())
        restored = AgentRuntime(self.base / 'workspace', self.base, [], self.provider)
        self.assertEqual('other-model', restored.role_config(self.project, 'builder')['model'])
        self.assertEqual('high', restored.role_config(self.project, 'mahoraga_orchestrator')['reasoningEffort'])
        self.assertEqual('low', restored.role_config(self.project, 'project_chat')['reasoningEffort'])
        self.assertEqual(MODEL_ID, restored.role_config(self.base / 'different', 'builder')['model'])

    def test_legacy_settings_are_inherited_then_roles_can_be_edited_independently(self):
        old = {'model': 'other-model', 'reasoningEffort': 'high'}
        self.runtime.state['agentProfiles'] = {str(self.project.resolve()): {'makora': old, 'mahoraga': old}}
        for role in ('preparation', 'project_chat', 'mahoraga_planner', 'mahoraga_orchestrator', 'mahoraga'):
            self.assertEqual(old, self.runtime.role_config(self.project, role))
        new = {'model': MODEL_ID, 'reasoningEffort': 'low'}
        self.runtime.set_agent_profile(self.project, {'preparation': new, 'mahoraga_planner': new})
        self.assertEqual(new, self.runtime.role_config(self.project, 'preparation'))
        self.assertEqual(new, self.runtime.role_config(self.project, 'mahoraga_planner'))
        self.assertEqual(old, self.runtime.role_config(self.project, 'project_chat'))
        self.assertEqual(old, self.runtime.role_config(self.project, 'mahoraga_orchestrator'))

    def test_returned_project_inherits_selected_storage_profile(self):
        self.runtime.register_project_storage(self.project / 'app', self.project)
        self.runtime.set_agent_profile(self.project / 'app', self.profile())
        self.assertEqual('other-model', self.runtime.role_config(self.project / '.makora/preparation/projects/returned', 'builder')['model'])

    def test_invalid_models_and_efforts_do_not_change_saved_profile(self):
        expected = self.runtime.set_agent_profile(self.project, self.profile())
        for config in [{'model': 'missing', 'reasoningEffort': None}, {'model': MODEL_ID, 'reasoningEffort': 'high'}]:
            profile = self.profile()
            profile['reviewer'] = config
            with self.assertRaises(AgentRuntimeError):
                self.runtime.set_agent_profile(self.project, profile)
            self.assertEqual(expected, self.runtime.agent_profile(self.project))

    def test_new_threads_get_new_settings_existing_session_is_unchanged(self):
        self.runtime.set_agent_profile(self.project, self.profile())
        created = self.runtime.create_configured_thread(project=self.project, role='builder', cwd=self.project, name='build', prompt='test')
        self.assertEqual('other-model', created['model'])
        self.assertEqual('high', self.provider.create_thread.call_args.kwargs['reasoning_effort'])
        profile = self.profile()
        profile['builder'] = {'model': MODEL_ID, 'reasoningEffort': 'medium'}
        self.runtime.state['sessions']['saved'] = dict(created)
        self.runtime.set_agent_profile(self.project, profile)
        self.runtime.create_configured_thread(project=self.project, role='builder', cwd=self.project, name='new', prompt='test')
        self.assertEqual('medium', self.provider.create_thread.call_args.kwargs['reasoning_effort'])
        self.assertEqual('other-model', self.runtime.state['sessions']['saved']['model'])

    def test_adapter_passes_model_and_effort_and_persists_effort_in_thread_config(self):
        adapter = CodexLocalApi(self.base, self.base / 'workspace')
        adapter.model_catalog = lambda: CATALOG
        adapter._request = Mock(return_value={'id': 'thread'})
        adapter.create_thread(cwd=self.project, name='test', prompt='test', model='other-model', reasoning_effort='high')
        payload = adapter._request.call_args.args[1]
        self.assertEqual('never', payload['approvalPolicy'])
        self.assertTrue(payload['desktopVisible'])
        self.assertEqual('other-model', payload['model'])
        self.assertEqual('high', payload['reasoningEffort'])
        self.assertEqual('high', payload['config']['model_reasoning_effort'])
        self.assertEqual('appServer', payload['threadSource'])
        adapter.create_thread(cwd=self.project, name='chat', prompt='test', model='other-model', reasoning_effort='high', user_chat=True)
        self.assertEqual('user', adapter._request.call_args.args[1]['threadSource'])
        adapter._request.reset_mock()
        with self.assertRaises(AgentRuntimeError):
            adapter.create_thread(cwd=self.project, name='test', prompt='test', model='other-model', reasoning_effort='low')
        adapter._request.assert_not_called()

    def test_preparation_saves_settings_and_rejects_stale_project(self):
        pipeline = Preparation(self.base / 'prep-state', self.runtime)
        pipeline.state['storageRoot'] = str(self.project)
        self.runtime.register_project_storage(self.project / 'app', self.project)
        with self.assertRaises(AgentRuntimeError):
            pipeline.save_agent_settings({'projectId': 'wrong', 'roles': self.profile()})
        result = pipeline.save_agent_settings({'projectId': pipeline.state['projectId'], 'roles': self.profile()})
        self.assertEqual('high', result['roles']['builder']['reasoningEffort'])
        self.assertEqual(result['roles'], json.loads((self.project / 'reports/agent-settings.json').read_text('utf-8')))
        created = pipeline._create_agent('preparation', cwd=self.project, name='analysis', prompt='test')
        self.assertTrue(self.provider.create_thread.call_args.kwargs['desktop'])
        self.assertEqual('test', self.provider.create_thread.call_args.kwargs['prompt'])
        self.assertEqual('low', created['reasoningEffort'])
        self.assertEqual('low', self.provider.create_thread.call_args.kwargs['reasoning_effort'])

    def test_changed_makora_settings_start_new_chat_session_with_history(self):
        pipeline = Preparation(self.base / 'chat-state', self.runtime)
        pipeline.state['storageRoot'] = str(self.project)
        self.runtime.register_project_storage(self.project / 'app', self.project)
        self.runtime.set_agent_profile(pipeline.project_directory(), self.profile())
        first = pipeline.send_chat({'message': 'Первый вопрос', 'requestId': 'one'})
        self.assertTrue(self.provider.create_thread.call_args.kwargs['user_chat'])
        first_id = first['sessionId']
        pipeline.state['chat']['status'] = 'idle'
        profile = self.profile()
        profile['project_chat'] = {'model': 'other-model', 'reasoningEffort': 'high'}
        self.runtime.set_agent_profile(pipeline.project_directory(), profile)
        second = pipeline.send_chat({'message': 'Следующий вопрос', 'requestId': 'two'})
        self.assertNotEqual(first_id, second['sessionId'])
        self.assertEqual('other-model', second['model'])
        self.assertEqual('high', second['reasoningEffort'])
        self.assertIn('Первый вопрос', self.provider.create_thread.call_args.kwargs['prompt'])
        self.assertEqual(MODEL_ID, self.runtime.state['sessions'][first_id]['model'])

    def test_preparation_creates_desktop_chat_with_updated_role_settings(self):
        pipeline = Preparation(self.base / 'prep-state', self.runtime)
        pipeline.state['storageRoot'] = str(self.project)
        pipeline.start(0, {'brief': 'Сделать каталог заметок с поиском.'})
        pipeline.state['stages']['0']['status'] = 'review'
        self.runtime.set_agent_profile(pipeline.project_directory(), {
            'preparation': {'model': 'other-model', 'reasoningEffort': 'high'},
        })
        self.provider.send.return_value = {'turnId': 'turn2', 'operation': {'id': 'o2', 'state': 'accepted'}}
        result = pipeline.start(0, {'feedback': 'Объясни короче.'})
        self.assertEqual(2, self.provider.create_thread.call_count)
        self.provider.send.assert_not_called()
        self.assertTrue(self.provider.create_thread.call_args.kwargs['desktop'])
        self.assertEqual('other-model', self.provider.create_thread.call_args.kwargs['model'])
        self.assertEqual('high', self.provider.create_thread.call_args.kwargs['reasoning_effort'])
        self.assertEqual('other-model', result['stages']['0']['model'])

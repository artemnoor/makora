import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from makora_core.agents.runtime import AgentRuntime, AgentRuntimeError
from makora_core.preparation import Preparation


class ProjectLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'MAKORA_PROJECTS_DIR': str(self.base / 'library')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.runtime = AgentRuntime(self.base / 'workspace', self.base, [], Mock())
        self.pipeline = Preparation(self.base / 'workspace', self.runtime)

    def test_create_makes_folder_and_lists_project_without_overwriting_collision(self):
        first = self.pipeline.create_project({'name': 'Первый проект'})
        marker = Path(first['path']) / 'input' / 'keep.txt'
        marker.write_text('keep')
        second = self.pipeline.create_project({'name': 'Первый проект'})
        self.assertNotEqual(first['path'], second['path'])
        self.assertEqual('keep', marker.read_text())
        self.assertEqual(2, len(self.pipeline.list_projects()['projects']))
        self.assertTrue((Path(second['path']) / '.makora/preparation/state.json').is_file())

    def test_open_restores_approved_artifacts_stage_and_project_identity(self):
        first = self.pipeline.create_project({'name': 'Сохранённый'})
        self.pipeline.state['brief'] = 'Existing requirements'
        self.pipeline.state['stages'] = {'1': {'status': 'approved', 'files': {'analysis.md': '# Analysis'}}, '2': {'status': 'approved', 'files': {'idea.md': '# Idea'}}}
        self.pipeline.save()
        self.pipeline.create_project({'name': 'Другой'})
        snapshot = self.pipeline.open_project({'projectId': first['projectId'], 'stage': 3})
        self.assertEqual(first['projectId'], snapshot['projectId'])
        self.assertEqual('Existing requirements', snapshot['brief'])
        self.assertEqual(3, snapshot['lastStage'])
        self.assertEqual('# Analysis', snapshot['stages']['1']['files']['analysis.md'])
        self.assertEqual([1, 2, 3], self.pipeline.available_stages(snapshot))
        restored = Preparation(self.base / 'workspace', self.runtime)
        self.assertEqual(3, restored.state['lastStage'])

    def test_cannot_open_locked_stage_or_unknown_project(self):
        first = self.pipeline.create_project({'name': 'Один'})
        for payload in [{'projectId': first['projectId'], 'stage': 6}, {'projectId': '../outside', 'stage': 1}]:
            with self.assertRaises(AgentRuntimeError):
                self.pipeline.open_project(payload)
        self.assertEqual(1, self.pipeline.state['lastStage'])

    def test_active_agent_blocks_switch_and_create(self):
        first = self.pipeline.create_project({'name': 'Один'})
        self.runtime.state['sessions']['busy'] = {'status': 'running'}
        with self.assertRaises(AgentRuntimeError):
            self.pipeline.create_project({'name': 'Два'})
        with self.assertRaises(AgentRuntimeError):
            self.pipeline.open_project({'projectId': first['projectId'], 'stage': 1})
        self.assertFalse((self.base / 'library/Два').exists())

    def test_names_cannot_escape_library_or_use_windows_device_names(self):
        for name in ('../outside', 'D:\\outside', 'CON', 'NUL.txt', '.hidden', ''):
            with self.assertRaises(AgentRuntimeError):
                self.pipeline.create_project({'name': name})

    def test_scans_project_on_another_installation_and_handles_null_prototype(self):
        first = self.pipeline.create_project({'name': 'Переносимый'})
        self.pipeline.state.update(prototype=None, returnedProject={'status': 'prepared'})
        self.pipeline.state['stages'] = {str(n): {'status': 'approved'} for n in range(1, 5)}
        self.pipeline.save()
        other = Preparation(self.base / 'different-workspace', self.runtime)
        listing = other.list_projects()
        self.assertEqual(first['projectId'], listing['projects'][0]['id'])
        self.assertIn(6, listing['projects'][0]['availableStages'])

    def test_no_d_drive_uses_user_documents(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=self.base):
            original = Path.is_dir
            with patch.object(Path, 'is_dir', lambda path: False if str(path) in ('D:\\', 'D:/') else original(path)):
                location = self.pipeline.projects_directory()
        self.assertEqual((self.base / 'Documents' / 'Макора').resolve(), location)
        self.assertTrue(location.is_dir())

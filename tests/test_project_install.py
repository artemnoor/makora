import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('makora_controller', Path(__file__).resolve().parents[1] / 'scripts' / 'makora.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class ProjectInstallTests(unittest.TestCase):
    def test_install_preserves_project_instructions_and_custom_skills(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            (project / 'AGENTS.md').write_text('Project rules\n', 'utf-8')
            controller.install(project, 8123)
            skill = project / '.agents/skills/makora-control/SKILL.md'
            self.assertTrue(skill.exists())
            skill.write_text('customized', 'utf-8')
            controller.install(project, 8123)
            instructions = (project / 'AGENTS.md').read_text('utf-8')
            self.assertTrue(instructions.startswith('Project rules\n'))
            self.assertEqual(1, instructions.count('<!-- makora:project -->'))
            self.assertEqual('customized', skill.read_text('utf-8'))

    def test_request_rejects_non_api_paths(self):
        for path in ('https://example.com', '/api/../auth', '/api/status?token=x'):
            with self.assertRaises(ValueError):
                controller.request({'port': 8123}, path)

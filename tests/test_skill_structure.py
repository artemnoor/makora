import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_skills import check_skill


class SkillStructureTests(unittest.TestCase):
    def test_native_skill_input_contract(self):
        result = subprocess.run(['node', 'tests/test_native_skill_input.mjs'], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def test_control_skill_does_not_require_document_templates(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'project-control'
            folder.mkdir()
            file = folder / 'SKILL.md'
            file.write_text('---\nname: project-control\ndescription: >-\n  Project control: local commands.\n---\n# Commands\nUse the local controller.\n', encoding='utf-8')
            self.assertEqual([], check_skill(folder))
            file.write_text('---\nname: project-control\ndescription: Invalid: YAML\n---\n', encoding='utf-8')
            self.assertTrue(any('YAML' in error for error in check_skill(folder)))

    def test_missing_inputs_outputs_and_readiness_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'development-planning'
            folder.mkdir()
            (folder / 'references').mkdir()
            (folder / 'assets').mkdir()
            (folder / 'assets' / 'output-template.md').write_text('`test-plan.md`', encoding='utf-8')
            (folder / 'SKILL.md').write_text('---\nname: development-planning\ndescription: Plan tasks\n---\n# План\n', encoding='utf-8')
            errors = check_skill(folder)
            self.assertTrue(any('«Входы»' in error for error in errors))
            self.assertTrue(any('«Выходы»' in error for error in errors))
            self.assertTrue(any('«Критерии готовности»' in error for error in errors))
            self.assertTrue(any('tasks.yaml' in error for error in errors))

    def test_missing_link_and_wrong_name_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'sample-skill'
            folder.mkdir()
            (folder / 'references').mkdir()
            (folder / 'assets').mkdir()
            (folder / 'SKILL.md').write_text('---\nname: wrong\ndescription: Sample\n---\n[method](references/missing.md)', encoding='utf-8')
            errors = check_skill(folder)
            self.assertTrue(any('имя' in error for error in errors))
            self.assertTrue(any('ссылка' in error for error in errors))


if __name__ == '__main__':
    unittest.main()

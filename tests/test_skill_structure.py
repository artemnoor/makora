import tempfile
import unittest
from pathlib import Path

from scripts.check_skills import check_skill


class SkillStructureTests(unittest.TestCase):
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

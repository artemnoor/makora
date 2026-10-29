import importlib.util
import tempfile
import unittest
from pathlib import Path
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / 'skills' / 'requirements-analysis' / 'scripts' / 'validate_requirements.py'
spec = importlib.util.spec_from_file_location('validator', SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class RequirementTests(unittest.TestCase):
    def test_example_package_tracks_sources_and_unknowns(self):
        case = Path(__file__).parent / 'fixtures' / 'requirements-case'
        expected = case / 'expected'
        names = {'problem-statement.md', 'requirements.yaml', 'opportunities.md', 'constraints.yaml',
                 'evaluation-criteria.yaml', 'submission-checklist.md', 'resources.yaml',
                 'open-questions.md', 'risk-register.yaml'}
        self.assertEqual({p.name for p in expected.iterdir()}, names)
        requirements = yaml.safe_load((expected / 'requirements.yaml').read_text(encoding='utf-8'))
        self.assertEqual(validator.validate(requirements, case / 'input'), [])
        self.assertEqual(len(requirements['mandatory']), 2)
        self.assertEqual(len(requirements['optional']), 1)
        scores = yaml.safe_load((expected / 'evaluation-criteria.yaml').read_text(encoding='utf-8'))
        self.assertIsNone(scores['weights'])
        self.assertEqual(scores['status'], 'unknown')
        resources = yaml.safe_load((expected / 'resources.yaml').read_text(encoding='utf-8'))
        self.assertEqual(resources['resources'][0]['availability'], 'not_checked')

    def test_case_with_real_quote_and_unknown_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'brief.txt').write_text('Прототип должен показывать свободные помещения. Демо сдать до пятницы.', encoding='utf-8')
            requirement = {'id': 'REQ-001', 'title': 'Список', 'description': 'Показывать свободные помещения',
                           'source': {'document': 'brief.txt', 'locator': 'абзац 1', 'quote': 'Прототип должен показывать свободные помещения.'},
                           'verification': 'Проверить демонстрацию списка', 'status': 'confirmed'}
            document = {'mandatory': [requirement], 'optional': [], 'unspecified': []}
            self.assertEqual(validator.validate(document, root), [])
            requirement['source']['quote'] = 'Организатор начисляет 50 баллов.'
            self.assertTrue(any('цитата не найдена' in e for e in validator.validate(document, root)))
            requirement['source']['document'] = '../brief.txt'
            self.assertTrue(any('недоступен' in e for e in validator.validate(document, root)))


if __name__ == '__main__':
    unittest.main()

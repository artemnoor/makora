import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'skills' / 'development-planning' / 'scripts' / 'validate_tasks.py'
spec = importlib.util.spec_from_file_location('task_validator', SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def task(ident, dependencies=()):
    return {'id': ident, 'title': 'Реализация', 'goal': 'Реализовать функцию', 'scope': 'src/',
            'depends_on': list(dependencies), 'requirement_ids': ['REQ-001'], 'feature_ids': ['F-001'],
            'inputs': [], 'acceptance': ['Функция работает'], 'verification': ['unit'], 'deliverables': ['код']}


class TaskTests(unittest.TestCase):
    def test_valid_graph(self):
        self.assertEqual(validator.validate({'tasks': [task('T01'), task('T02', ['T01'])]}), [])

    def test_cycle_and_unknown(self):
        errors = validator.validate({'tasks': [task('T01', ['T02']), task('T02', ['T01', 'MISSING'])]})
        self.assertTrue(any('цикл' in e for e in errors))
        self.assertTrue(any('MISSING' in e for e in errors))

    def test_rejects_missing_verification_and_duplicate_id(self):
        first, second = task('T01'), task('T01')
        second['verification'] = []
        errors = validator.validate({'tasks': [first, second]})
        self.assertTrue(any('повторяется' in e for e in errors))
        self.assertTrue(any('verification' in e for e in errors))


if __name__ == '__main__':
    unittest.main()

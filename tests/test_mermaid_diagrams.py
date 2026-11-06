import unittest
from unittest.mock import patch
from makora_core.preparation import Preparation

class MermaidValidationTests(unittest.TestCase):
    def test_valid_flow_c4_er_and_invalid_diagrams(self):
        files={'flow.mmd':'flowchart TD\n A([Начало]) --> B{Вопрос?}\n B -->|Да| C([Готово])',
               'bad.mmd':'flowchart TD\n A --> -->',
               'architecture.md':'# Архитектура\n```mermaid\nC4Context\n Person(user, "Пользователь")\n System(app, "Приложение", "Система")\n Rel(user, app, "Использует")\n```\n```mermaid\nerDiagram\n USER ||--o{ ORDER : places\n```'}
        checks=Preparation.validate_diagrams(files)
        self.assertEqual(['passed','failed','passed','passed'],[x['status'] for x in checks])
        self.assertIn('bad.mmd',checks[1]['name'])
        self.assertTrue(checks[1]['detail'])

    def test_unavailable_validator_is_never_reported_as_passed(self):
        with patch('makora_core.preparation.subprocess.run',side_effect=FileNotFoundError()):
            checks=Preparation.validate_diagrams({'flow.mmd':'flowchart TD\n A --> B'})
        self.assertEqual('not_checked',checks[0]['status'])

    def test_no_diagrams_needs_no_validator(self):
        self.assertEqual([],Preparation.validate_diagrams({'readme.md':'# Простое описание'}))

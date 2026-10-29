"""Exercise hand-authored examples against contracts and cross-stage links.

These fixtures are expected examples, not output from an agent or a model.
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent / 'fixtures'
REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('plan_validator', REPO / 'skills/development-planning/scripts/validate_tasks.py')
plan_validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_validator)


def read_yaml(path):
    return yaml.safe_load(path.read_text(encoding='utf-8'))


class SkillCaseTests(unittest.TestCase):
    def test_all_expected_outputs_are_present_and_parse(self):
        outputs = {
            'product-research': {'problem-research.md', 'competitors.md', 'patterns.md', 'technical-feasibility.md', 'research-summary.md'},
            'solution-design': {'concepts.md', 'concept-decision.md', 'product-concept.md', 'mvp-scope.yaml', 'user-flow.mmd', 'task-flows.mmd', 'demo-script.md', 'success-metrics.yaml', 'hypotheses.yaml'},
            'system-design': {'c1-context.md', 'c2-containers.md', 'c3-components.md', 'data-model.md', 'openapi.yaml', 'c4-code.md', 'architecture-decisions.md', 'contract-validation.md'},
            'development-planning': {'test-plan.md', 'tasks.yaml', 'plan-validation.md'},
            'mock-environment': {'data-requirements.md', 'scenarios.yaml', 'mock-validation.md', 'fixtures/places.json', 'fixtures/empty.json', 'fixtures/invalid.json', 'mock-server/README.md'},
        }
        for skill, filenames in outputs.items():
            with self.subTest(skill=skill):
                case = ROOT / skill
                self.assertTrue(any((case / 'input').iterdir()), 'Нужны входные данные')
                self.assertEqual({p.relative_to(case / 'expected').as_posix() for p in (case / 'expected').rglob('*') if p.is_file()}, filenames)
                for name in filenames:
                    path = case / 'expected' / name
                    self.assertTrue(path.read_text(encoding='utf-8').strip(), name)
                    if path.suffix == '.yaml':
                        self.assertIsNotNone(read_yaml(path))
                    elif path.suffix == '.json':
                        json.loads(path.read_text(encoding='utf-8'))
                    elif path.suffix == '.mmd':
                        self.assertTrue(path.read_text(encoding='utf-8').lstrip().startswith('flowchart '))

    def test_requirements_to_mvp_tasks_tests_and_mock_scenarios(self):
        requirements = read_yaml(ROOT / 'requirements-case/expected/requirements.yaml')
        mandatory = {entry['id'] for entry in requirements['mandatory']}
        mvp = read_yaml(ROOT / 'solution-design/expected/mvp-scope.yaml')
        features = {feature['id']: feature for feature in mvp['features']}
        covered = {req for feature in features.values() if feature['included_in_mvp'] for req in feature['requirement_ids']}
        self.assertEqual(mandatory, covered)
        tasks = read_yaml(ROOT / 'development-planning/expected/tasks.yaml')
        self.assertEqual(plan_validator.validate(tasks), [])
        task_requirements = {req for task in tasks['tasks'] for req in task['requirement_ids']}
        self.assertEqual(mandatory, task_requirements)
        self.assertTrue(all(feature in features for task in tasks['tasks'] for feature in task['feature_ids']))
        test_plan = (ROOT / 'development-planning/expected/test-plan.md').read_text(encoding='utf-8')
        test_ids = set(re.findall(r'\bTC-\d+\b', test_plan))
        self.assertTrue(all(test in test_ids for task in tasks['tasks'] for test in task['verification']))
        scenarios = read_yaml(ROOT / 'mock-environment/expected/scenarios.yaml')['scenarios']
        self.assertTrue(all(set(scenario['tests']) <= test_ids for scenario in scenarios))
        for scenario in scenarios:
            self.assertTrue((ROOT / 'mock-environment/expected' / scenario['fixture']).is_file())
        for skill in ('development-planning', 'mock-environment'):
            context = ROOT / skill / 'input/context.md'
            for relative in re.findall(r'`([^`]+)`', context.read_text(encoding='utf-8')):
                self.assertTrue((context.parent / relative).is_file(), relative)

    def test_mock_fixtures_against_example_schema(self):
        contract = read_yaml(ROOT / 'system-design/expected/openapi.yaml')
        self.assertEqual(contract['openapi'], '3.1.1')
        place = contract['components']['schemas']['Place']
        jsonschema.Draft202012Validator.check_schema(place)
        schema = {'type': 'array', 'items': place}
        fixtures = ROOT / 'mock-environment/expected/fixtures'
        for name in ('places.json', 'empty.json'):
            self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(json.loads((fixtures / name).read_text(encoding='utf-8'))))
        invalid = json.loads((fixtures / 'invalid.json').read_text(encoding='utf-8'))
        self.assertFalse(jsonschema.Draft202012Validator(schema).is_valid(invalid))
        places = json.loads((fixtures / 'places.json').read_text(encoding='utf-8'))
        filtered = [place for place in places if place['district'] == 'Центр']
        self.assertEqual([place['id'] for place in filtered], ['p-001'])

    def test_unverified_claims_and_unrun_checks_are_labeled(self):
        research = ROOT / 'product-research/expected'
        self.assertIn('не исследовались', (research / 'competitors.md').read_text(encoding='utf-8'))
        self.assertIn('не выполнялись', (research / 'technical-feasibility.md').read_text(encoding='utf-8'))
        for relative in ('system-design/expected/contract-validation.md', 'mock-environment/expected/mock-validation.md'):
            self.assertIn('not_checked', (ROOT / relative).read_text(encoding='utf-8'))
        self.assertIn('skipped', (ROOT / 'mock-environment/expected/mock-server/README.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

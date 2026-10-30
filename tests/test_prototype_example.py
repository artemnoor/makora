import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

import jsonschema
import yaml

CASE = Path(__file__).resolve().parents[1] / 'dist' / 'prototype-example'


def read_json(path):
    return json.loads((CASE / path).read_text(encoding='utf-8'))


class PrototypeExampleTests(unittest.TestCase):
    def test_manifest_is_complete_and_prompt_preserves_mocks(self):
        manifest = read_json('manifest.json')['files']
        actual = {p.relative_to(CASE).as_posix() for p in CASE.rglob('*') if p.is_file()} - {'manifest.json'}
        self.assertEqual(set(manifest), actual)
        self.assertEqual(len(manifest), len(set(manifest)))
        prompt = (CASE / 'PROMPT.md').read_text(encoding='utf-8')
        self.assertIn('mocks/', prompt)
        self.assertIn('new_mocks/', prompt)
        self.assertIn('не изменяй и не удаляй', prompt)
        for required in ('mocks/fixtures/', 'не подменяй', 'параметр URL', 'prototype-report.json', 'passed', 'failed', 'not_run', 'не блокирует выполнение обязательных требований'):
            self.assertIn(required, prompt)

    def test_schemas_fixtures_and_contract_agree(self):
        schema = read_json('mocks/schemas/place.schema.json')
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        places = read_json('mocks/fixtures/places.json')
        self.assertEqual(len(places), 8)
        self.assertEqual(len({place['id'] for place in places}), len(places))
        self.assertTrue(all(validator.is_valid(place) for place in places))
        self.assertTrue(all(not validator.is_valid(place) for place in read_json('mocks/fixtures/invalid.json')))
        self.assertEqual(read_json('mocks/fixtures/empty.json'), [])
        contract = yaml.safe_load((CASE / '03_contracts/openapi.yaml').read_text(encoding='utf-8'))
        place_schema = contract['components']['schemas']['Place']
        self.assertEqual(place_schema['properties'], schema['properties'])
        self.assertEqual(set(place_schema['required']), set(schema['required']))
        self.assertEqual(place_schema['additionalProperties'], schema['additionalProperties'])
        error = read_json('mocks/fixtures/error.json')
        jsonschema.Draft202012Validator(contract['components']['schemas']['Error']).validate(error)
        self.assertEqual({place['id'] for place in places if place['district']=='Центральный' and place['entrance_status']=='accessible'}, {'place-001','place-003'})
        self.assertFalse([place for place in places if place['district']=='Северный' and place['entrance_status']=='accessible'])

    def test_rename_changeset_requires_the_original_path(self):
        schema=read_json('changeset.schema.json')
        validator=jsonschema.Draft202012Validator(schema)
        change={'id':'MOVE','operation':'rename','path':'src/new.js','reason':'Перенос'}
        self.assertFalse(validator.is_valid({'base_revision':'v1','changes':[change]}))
        change['source_artifact']='src/old.js'
        self.assertTrue(validator.is_valid({'base_revision':'v1','changes':[change]}))

    def test_tasks_scenarios_and_plan_are_linked(self):
        plan = (CASE / '03_test_plan.md').read_text(encoding='utf-8')
        ids = set(re.findall(r'\bTC-\d+\b', plan))
        tasks = read_json('03_tasks.json')['tasks']
        task_ids = {task['id'] for task in tasks}
        self.assertEqual(len(task_ids), len(tasks))
        self.assertTrue(all(set(task['dependsOn']) <= task_ids for task in tasks))
        self.assertTrue(all(set(task['tests']) <= ids for task in tasks))
        requirements = set(re.findall(r'\bREQ-\d+\b', (CASE / '01_case_analysis.md').read_text(encoding='utf-8')))
        self.assertEqual(requirements, {req for task in tasks for req in task['requirements']})
        for scenario in read_json('mocks/scenarios.json'):
            self.assertTrue((CASE / 'mocks' / scenario['fixture']).is_file())
            self.assertTrue(set(scenario['tests']) <= ids)
        self.assertIn('запланированы', plan)

    def test_fixture_validation_script_runs_from_case(self):
        result = subprocess.run([sys.executable, str(CASE / 'mocks/validate.py')], cwd=CASE,
                                text=True, encoding='utf-8', capture_output=True,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('негативный набор отклонён', result.stdout)
        self.assertIn('не проверялись', result.stdout)


if __name__ == '__main__':
    unittest.main()

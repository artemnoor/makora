"""Check local Agent Skills frontmatter and referenced local resources."""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / 'skills'
CONTRACTS = {
    'requirements-analysis': (('материал',), ('problem-statement.md', 'requirements.yaml', 'opportunities.md', 'constraints.yaml', 'evaluation-criteria.yaml', 'submission-checklist.md', 'resources.yaml', 'open-questions.md', 'risk-register.yaml')),
    'product-research': (('требован', 'ограничен'), ('problem-research.md', 'competitors.md', 'patterns.md', 'technical-feasibility.md', 'research-summary.md')),
    'solution-design': (('требован', 'исследован'), ('concepts.md', 'concept-decision.md', 'product-concept.md', 'mvp-scope.yaml', 'user-flow.mmd', 'task-flows.mmd', 'demo-script.md', 'success-metrics.yaml', 'hypotheses.yaml')),
    'system-design': (('требован', 'mvp'), ('c1-context.md', 'c2-containers.md', 'c3-components.md', 'data-model.md', 'openapi.yaml', 'c4-code.md', 'architecture-decisions.md', 'contract-validation.md')),
    'development-planning': (('требован', 'контракт'), ('test-plan.md', 'tasks.yaml', 'plan-validation.md')),
    'mock-environment': (('контракт', 'тест-план'), ('data-requirements.md', 'fixtures/', 'scenarios.yaml', 'mock-server/', 'mock-validation.md')),
    'prototype-handoff': (('контракт', 'мок'), ('prototype-prompt.md', 'prototype-context.zip', 'handoff-status.json', 'mock-change-questions.md', 'mock-adaptation-report.md')),
    'change-reconciliation': (('ревиз', 'возвращён'), ('project-diff.json', 'impact-map.json', 'adaptation-context.json', 'adaptation-report.json', 'changeset.schema.json')),
}


def section(body, title):
    match = re.search(r'^##\s+' + re.escape(title) + r'\s*\n(.*?)(?=^##\s+|\Z)', body, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ''


def check_skill(folder):
    errors = []
    file = folder / 'SKILL.md'
    if not file.is_file():
        return [f'{folder.name}: SKILL.md отсутствует']
    text = file.read_text(encoding='utf-8')
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not match:
        return [f'{folder.name}: отсутствует YAML frontmatter']
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [f'{folder.name}: некорректный YAML: {exc}']
    if not isinstance(metadata, dict):
        return [f'{folder.name}: frontmatter должен быть объектом']
    name, description = metadata.get('name'), metadata.get('description')
    if not isinstance(name, str) or name != folder.name or len(name) > 64 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name):
        errors.append(f'{folder.name}: некорректное имя скилла')
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        errors.append(f'{folder.name}: некорректное описание')
    for target in re.findall(r'\]\(([^)]+)\)', text[match.end():]):
        if '://' in target or target.startswith('#'):
            continue
        path = (folder / target.split('#', 1)[0]).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            errors.append(f'{folder.name}: ссылка на недоступный файл {target}')
    for required in ('references', 'assets'):
        if not (folder / required).is_dir():
            errors.append(f'{folder.name}: нет каталога {required}')
    body = text[match.end():]
    inputs = section(body, 'Входы')
    outputs = section(body, 'Выходы')
    readiness = section(body, 'Критерии готовности')
    for title, value in (('Входы', inputs), ('Выходы', outputs), ('Критерии готовности', readiness)):
        if len(value) < 20:
            errors.append(f'{folder.name}: отсутствует или пуст раздел «{title}»')
    if folder.name in CONTRACTS:
        required_inputs, required_outputs = CONTRACTS[folder.name]
        for token in required_inputs:
            if token not in inputs.lower():
                errors.append(f'{folder.name}: во входах не указано «{token}»')
        template_path = folder / 'assets' / 'output-template.md'
        template = template_path.read_text(encoding='utf-8') if template_path.is_file() else ''
        for filename in required_outputs:
            if f'`{filename}`' not in outputs:
                errors.append(f'{folder.name}: в выходах отсутствует {filename}')
            if f'`{filename}`' not in template:
                errors.append(f'{folder.name}: в шаблоне отсутствует {filename}')
    return errors


def main():
    skills = sorted(path for path in ROOT.iterdir() if path.is_dir())
    errors = [error for folder in skills for error in check_skill(folder)]
    for missing in sorted(set(CONTRACTS) - {folder.name for folder in skills}):
        errors.append(f'{missing}: обязательный скилл отсутствует')
    if not skills:
        errors.append('Скиллы не найдены')
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f'Проверены структура и наличие входов, выходов и критериев: {len(skills)}. Качество методологии и работа модели не проверялись.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

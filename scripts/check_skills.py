"""Check local Agent Skills frontmatter and referenced local resources."""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / 'skills'


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
    return errors


def main():
    skills = sorted(path for path in ROOT.iterdir() if path.is_dir())
    errors = [error for folder in skills for error in check_skill(folder)]
    if not skills:
        errors.append('Скиллы не найдены')
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    print(f'Проверена структура скиллов: {len(skills)}. Содержательное качество не проверялось.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

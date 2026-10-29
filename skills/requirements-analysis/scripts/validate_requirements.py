"""Validate YAML requirements against extracted text; never claims semantic completeness."""
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({'ok': False, 'errors': ['PyYAML недоступен; проверка не выполнялась.']}, ensure_ascii=False))
    raise SystemExit(2)


def validate(document, source_root):
    errors = []
    if not isinstance(document, dict):
        return ['Ожидается YAML-объект.']
    ids = set()
    for category in ('mandatory', 'optional', 'unspecified'):
        entries = document.get(category)
        if not isinstance(entries, list):
            errors.append(f'{category}: ожидается список.')
            continue
        for i, item in enumerate(entries):
            label = f'{category}[{i}]'
            if not isinstance(item, dict):
                errors.append(f'{label}: ожидается объект.')
                continue
            ident = item.get('id')
            if not isinstance(ident, str) or not ident.strip() or ident in ids:
                errors.append(f'{label}: идентификатор отсутствует или повторяется.')
            else:
                ids.add(ident)
            if not item.get('title') or not item.get('description') or not item.get('verification'):
                errors.append(f'{label}: нужны название, описание и способ проверки.')
            status = item.get('status')
            if status not in ('confirmed', 'inferred', 'assumption', 'unknown'):
                errors.append(f'{label}: неизвестный статус.')
            if status != 'confirmed':
                continue
            source = item.get('source')
            if not isinstance(source, dict) or not all(source.get(k) for k in ('document', 'locator', 'quote')):
                errors.append(f'{label}: подтверждённому требованию нужны документ, локатор и цитата.')
                continue
            root = Path(source_root).resolve()
            path = (root / str(source['document'])).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                errors.append(f'{label}: источник недоступен в каталоге исходных текстов.')
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                errors.append(f'{label}: не удалось прочитать текст источника в UTF-8.')
                continue
            if not isinstance(source['quote'], str) or source['quote'] not in text:
                errors.append(f'{label}: цитата не найдена в источнике.')
    return errors


def main():
    if len(sys.argv) != 3:
        print('Использование: validate_requirements.py requirements.yaml INPUT_ROOT', file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding='utf-8') as stream:
            document = yaml.safe_load(stream)
        errors = validate(document, sys.argv[2])
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        errors = [str(exc)]
    print(json.dumps({'ok': not errors, 'errors': errors, 'scope': 'синтаксис, идентификаторы и цитаты; полнота не проверялась'}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())

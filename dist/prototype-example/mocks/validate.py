"""Validate the synthetic fixture set. Does not start or test the prototype."""
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    print('Установите зависимости: python -m pip install -r mocks/requirements.txt', file=sys.stderr)
    raise SystemExit(2)

root = Path(__file__).resolve().parent


def read(path):
    return json.loads((root / path).read_text(encoding='utf-8'))


def main():
    try:
        schema = read('schemas/place.schema.json')
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        places, empty, invalid, error = (read('fixtures/' + name) for name in ('places.json', 'empty.json', 'invalid.json', 'error.json'))
        checks = {
            'валидные записи': isinstance(places, list) and len(places) == 8 and all(validator.is_valid(item) for item in places),
            'уникальные id': isinstance(places, list) and len({item.get('id') for item in places if isinstance(item, dict)}) == len(places),
            'пустой набор': empty == [],
            'негативный набор отклонён': isinstance(invalid, list) and bool(invalid) and all(not validator.is_valid(item) for item in invalid),
            'ошибка источника': isinstance(error, dict) and error.get('code') == 'SOURCE_UNAVAILABLE' and isinstance(error.get('message'), str),
            'фильтр Центральный + accessible': {item['id'] for item in places if item['district'] == 'Центральный' and item['entrance_status'] == 'accessible'} == {'place-001', 'place-003'},
            'пустой фильтр Северный + accessible': not any(item['district'] == 'Северный' and item['entrance_status'] == 'accessible' for item in places),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Ошибка проверки:', exc, file=sys.stderr)
        return 1
    for name, passed in checks.items():
        print(('OK' if passed else 'ERROR') + ' — ' + name)
    print('Интерфейс и API этой командой не проверялись.')
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Check task shape and dependencies, without claiming plan completeness."""
import json
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({'ok': False, 'errors': ['PyYAML недоступен; проверка не выполнялась.']}, ensure_ascii=False))
    raise SystemExit(2)


def validate(document):
    errors = []
    tasks = document.get('tasks') if isinstance(document, dict) else None
    if not isinstance(tasks, list) or not tasks:
        return ['Поле tasks должно содержать непустой список.']
    ids = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f'tasks[{i}]: ожидается объект.')
            continue
        ident = task.get('id')
        if not isinstance(ident, str) or not ident.strip() or ident in ids:
            errors.append(f'tasks[{i}]: отсутствует или повторяется ID.')
        else:
            ids.add(ident)
        for field in ('title', 'goal', 'scope'):
            if not task.get(field):
                errors.append(f'{ident}: отсутствует {field}.')
        for field in ('depends_on', 'requirement_ids', 'feature_ids', 'inputs', 'acceptance', 'verification', 'deliverables'):
            if not isinstance(task.get(field), list):
                errors.append(f'{ident}: {field} должен быть списком.')
            elif field in ('acceptance', 'verification', 'deliverables') and not task[field]:
                errors.append(f'{ident}: {field} не должен быть пустым.')
    graph = {}
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get('id'), str):
            continue
        deps = task.get('depends_on') if isinstance(task.get('depends_on'), list) else []
        graph[task['id']] = []
        for dep in deps:
            if not isinstance(dep, str) or dep not in ids:
                errors.append(f"{task['id']}: неизвестная зависимость {dep}.")
            else:
                graph[task['id']].append(dep)
    state = {}
    def visit(node):
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        cycle = any(visit(dep) for dep in graph.get(node, []))
        state[node] = 2
        return cycle
    if any(visit(node) for node in graph):
        errors.append('Обнаружен цикл зависимостей.')
    return errors


def main():
    if len(sys.argv) != 2:
        print('Использование: validate_tasks.py tasks.yaml', file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding='utf-8') as file:
            errors = validate(yaml.safe_load(file))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        errors = [str(exc)]
    print(json.dumps({'ok': not errors, 'errors': errors, 'scope': 'структура и граф; полнота плана не проверялась'}, ensure_ascii=False))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())

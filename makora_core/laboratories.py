"""Execution graph validation and laboratory acceptance boundaries."""
import re
from pathlib import PurePosixPath


def validate_execution(tasks, execution, artifacts=None):
    from .agents.runtime import AgentRuntime
    if not isinstance(tasks, list) or not tasks or not isinstance(execution, dict):
        raise ValueError('Нужны список задач и схема исполнения.')
    ids = [t.get('id') for t in tasks if isinstance(t, dict)]
    if len(ids) != len(tasks) or any(not isinstance(i, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{1,39}', i) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError('ID задач должны быть уникальными.')
    for task in tasks:
        if not isinstance(task.get('allowedPaths'), list) or not task['allowedPaths'] or any(not isinstance(p, str) or not p for p in task['allowedPaths']):
            raise ValueError('Каждой задаче нужны точные пути файлов allowedPaths.')
        if not isinstance(task.get('dependsOn'), list) or any(d not in ids or d == task['id'] for d in task['dependsOn']):
            raise ValueError('Неверная зависимость задачи.')
    AgentRuntime._assert_acyclic(tasks)
    AgentRuntime._assert_non_overlapping_independent_scopes(tasks)
    skeleton = execution.get('skeletonTaskId')
    if skeleton not in ids:
        raise ValueError('Выберите задачу общего каркаса skeletonTaskId.')
    by_id = {t['id']: t for t in tasks}
    def depends(task_id, ancestor):
        seen, pending = set(), list(by_id[task_id]['dependsOn'])
        while pending:
            item = pending.pop()
            if item == ancestor:
                return True
            if item not in seen:
                seen.add(item); pending.extend(by_id[item]['dependsOn'])
        return False
    if by_id[skeleton]['dependsOn'] or any(t['id'] != skeleton and not depends(t['id'], skeleton) for t in tasks):
        raise ValueError('Общий каркас запускается первым; остальные задачи должны зависеть от него.')
    labs = execution.get('laboratories', [])
    if not isinstance(labs, list):
        raise ValueError('laboratories должен быть списком, он может быть пустым.')
    used, lab_ids = set(), set()
    for lab in labs:
        if not isinstance(lab, dict) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{1,39}', str(lab.get('id', ''))) or lab['id'] in lab_ids or not lab.get('title'):
            raise ValueError('У лаборатории нужны уникальный id и название.')
        lab_ids.add(lab['id'])
        members = lab.get('taskIds')
        if not isinstance(members, list) or not members or any(not isinstance(t, str) or t not in ids or t in used or t == skeleton for t in members) or len(members) != len(set(members)):
            raise ValueError('Выберите задачи лаборатории, не занятые другой лабораторией.')
        used.update(members)
        root = lab.get('uiRoot', '')
        if root != f'labs/{lab["id"]}/':
            raise ValueError('Тестовый интерфейс лаборатории хранится только в labs/<id>/.')
        preview = lab.get('previewCommand', [])
        if not isinstance(preview, list) or len(preview) != 2 or preview[0] not in ('node', 'python', 'python3') or not isinstance(preview[1], str) or not preview[1].startswith(root):
            raise ValueError('previewCommand: [node|python, labs/<id>/preview.mjs|py].')
        if '..' in PurePosixPath(preview[1]).parts or PurePosixPath(preview[1]).suffix not in ('.mjs', '.js', '.py'):
            raise ValueError('Неверный путь скрипта мини-интерфейса.')
        paths = {p for t in tasks if t['id'] in members for p in t.get('allowedPaths', [])}
        if preview[1] not in paths or not any(not p.startswith(root) for p in paths):
            raise ValueError('У лаборатории нужны скрипт мини-интерфейса и отдельные файлы рабочей функции.')
        fallback = lab.get('mockFixture')
        if not isinstance(fallback, str) or not fallback.startswith('mocks/') or '..' in PurePosixPath(fallback).parts or (artifacts is not None and fallback not in artifacts):
            raise ValueError('Лаборатории нужна существующая мок-фикстура для основной ветки.')
        join = lab.get('integrationTaskId')
        if join not in ids or join in used or not all(depends(join, t) for t in members):
            raise ValueError('Задача подключения функции должна зависеть от всех задач лаборатории.')
        for task in tasks:
            if task['id'] not in members and any(p.startswith(root) for p in task.get('allowedPaths', [])):
                raise ValueError('Тестовый интерфейс не может менять основная ветка.')
    for task in tasks:
        for path in task.get('allowedPaths', []):
            if path.startswith('labs/') and not any(task['id'] in lab['taskIds'] and path.startswith(lab['uiRoot']) for lab in labs):
                raise ValueError('Файлы labs/ должны принадлежать конкретной лаборатории, иначе они попадут в основной проект.')
    return execution


def task_laboratory(run, task_id):
    return next((lab for lab in run.get('execution', {}).get('laboratories', []) if task_id in lab['taskIds']), None)


def laboratory_state(run):
    by_id = {t['id']: t for t in run['tasks']}
    result = []
    for lab in run.get('execution', {}).get('laboratories', []):
        ready = all(by_id[i]['status'] == 'integrated' for i in lab['taskIds'])
        connected = by_id[lab['integrationTaskId']]['status'] == 'integrated'
        result.append({**lab, 'status': 'connected' if connected else 'ready' if ready else 'developing',
                       'dataSource': 'feature' if connected else 'mock',
                       'humanAccepted': all(by_id[i].get('laboratoryAcceptance') for i in lab['taskIds'])})
    return result

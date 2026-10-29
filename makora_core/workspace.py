"""Versioned, explicit local artifact handoff for a single Makora workspace."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class MakoraError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat()


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.makora-')
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.manifest_path = self.root / 'state' / 'manifest.json'
        if not self.manifest_path.is_file():
            raise MakoraError('WORKSPACE_NOT_FOUND', 'Сначала создайте рабочую область командой init.')
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))

    @classmethod
    def create(cls, root):
        root = Path(root).resolve()
        manifest = root / 'state' / 'manifest.json'
        if manifest.exists():
            raise MakoraError('WORKSPACE_EXISTS', 'Рабочая область уже существует.')
        for folder in ('input', 'artifacts', 'state', 'project'):
            (root / folder).mkdir(parents=True, exist_ok=True)
        atomic(manifest, json.dumps({'schema_version': 1, 'artifacts': [], 'decisions': []}, ensure_ascii=False, indent=2).encode())
        return cls(root)

    def save(self):
        atomic(self.manifest_path, json.dumps(self.manifest, ensure_ascii=False, indent=2).encode('utf-8'))

    def path(self, value):
        value = Path(value)
        if value.is_absolute():
            raise MakoraError('INVALID_PATH', 'Путь должен быть относительным.')
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise MakoraError('INVALID_PATH', 'Путь выходит за пределы рабочей области.')
        return path

    def artifact(self, artifact_id):
        item = next((item for item in self.manifest['artifacts'] if item['artifact_id'] == artifact_id), None)
        if item is None:
            raise MakoraError('ARTIFACT_NOT_FOUND', f'Артефакт {artifact_id} не найден.')
        return item

    def snapshot(self, item, data):
        # IDs are user supplied; use a digest as the directory name.
        directory = checksum(item['artifact_id'].encode('utf-8'))[:24]
        path = self.root / 'state' / 'versions' / directory / str(item['version'])
        atomic(path, data)

    def register(self, artifact_id, file_path, kind, depends_on=(), sources=()):
        if any(a['artifact_id'] == artifact_id for a in self.manifest['artifacts']):
            raise MakoraError('DUPLICATE_ID', 'Идентификатор уже используется.')
        target = self.path(file_path)
        relative = target.relative_to(self.root).as_posix()
        if not relative.startswith(('input/', 'artifacts/')):
            raise MakoraError('INVALID_PATH', 'Артефакты должны находиться в input/ или artifacts/.')
        if any(a['path'] == relative for a in self.manifest['artifacts']):
            raise MakoraError('DUPLICATE_PATH', 'Файл уже зарегистрирован.')
        if not target.is_file():
            raise MakoraError('FILE_NOT_FOUND', f'Файл {file_path} не найден.')
        for dependency in depends_on:
            self.artifact(dependency)
        data = target.read_bytes()
        item = {'artifact_id': artifact_id, 'path': relative, 'type': kind, 'version': 1,
                'status': 'draft', 'sha256': checksum(data),
                'depends_on': list(depends_on), 'sources': list(sources), 'updated_at': now()}
        self.snapshot(item, data)
        self.manifest['artifacts'].append(item)
        self.save()
        return item

    def mark_dependents_stale(self, artifact_id):
        pending = [artifact_id]
        visited = set(pending)
        while pending:
            current = pending.pop()
            for item in self.manifest['artifacts']:
                if current in item['depends_on'] and item['artifact_id'] not in visited:
                    visited.add(item['artifact_id'])
                    item['status'] = 'stale'
                    pending.append(item['artifact_id'])

    def audit(self):
        changed = []
        for item in self.manifest['artifacts']:
            target = self.path(item['path'])
            actual = checksum(target.read_bytes()) if target.is_file() else None
            if actual != item['sha256']:
                item['sha256'] = actual
                item['version'] += 1
                item['status'] = 'stale' if actual is None else 'draft'
                item['updated_at'] = now()
                if actual is not None:
                    self.snapshot(item, target.read_bytes())
                changed.append(item['artifact_id'])
        for artifact_id in changed:
            self.mark_dependents_stale(artifact_id)
        if changed:
            self.save()
        return changed

    def approve(self, artifact_id, note):
        self.audit()
        item = self.artifact(artifact_id)
        if not self.path(item['path']).is_file():
            raise MakoraError('FILE_NOT_FOUND', 'Утверждаемый файл отсутствует.')
        for dependency in item['depends_on']:
            if self.artifact(dependency)['status'] != 'approved':
                raise MakoraError('DEPENDENCY_NOT_APPROVED', f'Не утверждён {dependency}.')
        item['status'] = 'approved'
        self.manifest['decisions'].append({'action': 'approved', 'artifact_id': artifact_id,
                                           'version': item['version'], 'note': note, 'time': now()})
        self.save()
        return item

    def context(self, ids):
        self.audit()
        result = []
        for artifact_id in ids:
            item = self.artifact(artifact_id)
            if item['status'] != 'approved':
                raise MakoraError('ARTIFACT_NOT_APPROVED', f'{artifact_id} не утверждён или требует перепроверки.')
            result.append({**item, 'absolute_path': str(self.path(item['path']))})
        return result

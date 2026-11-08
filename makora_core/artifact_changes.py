"""Reviewable edits to preparation artifacts, bound to an exact project snapshot."""
from __future__ import annotations

import copy
import base64
import difflib
import hashlib
import json
import uuid
from pathlib import PurePosixPath

from .agents.runtime import AgentRuntimeError
from .artifact_registry import build_registry, ID_PATTERN
from .workspace import atomic, now


class ArtifactChanges:
    def __init__(self, preparation):
        self.preparation = preparation

    def directory(self):
        path = self.preparation.root / 'changes'
        path.mkdir(exist_ok=True)
        return path

    def context(self):
        self.recover()
        files, owners = {}, {}
        for stage, record in self.preparation.state['stages'].items():
            if self.preparation.state.get('workflowVersion', 0) >= 3 and int(stage) not in (0, 2, 3, 5, 6, 4, 7):
                continue
            for name, content in record.get('files', {}).items():
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                    raise AgentRuntimeError('UNSAFE_ARTIFACT', 'Небезопасный путь артефакта.')
                if name in files:
                    raise AgentRuntimeError('AMBIGUOUS_ARTIFACT', f'Артефакт {name} есть в нескольких этапах.')
                files[name], owners[name] = content, int(stage)
        version = {'files': files, 'statuses': {key: record['status'] for key, record in self.preparation.state['stages'].items()},
                   'projectId': self.preparation.state['projectId'], 'decisions': self.preparation.state.get('competitorPreferences'), 'disk': self.disk_hashes(files)}
        digest = hashlib.sha256(json.dumps(version, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {'baseDigest': digest, 'projectId': version['projectId'], 'files': files, 'owners': owners}

    def disk_hashes(self, files):
        root = self.preparation.state.get('storageRoot')
        if not root:
            return {}
        from pathlib import Path
        hashes = {}
        for name in files:
            target = Path(root) / 'artifacts' / name
            if target.is_symlink() or not target.resolve().is_relative_to(Path(root).resolve()):
                raise AgentRuntimeError('UNSAFE_ARTIFACT', 'Небезопасный путь файла на диске.')
            if target.is_file() and target.stat().st_size > 8 * 1024 * 1024:
                raise AgentRuntimeError('ARTIFACT_LIMIT', 'Артефакт на диске превышает 8 МБ.')
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
        return hashes

    @staticmethod
    def state_hash(state):
        return hashlib.sha256(json.dumps(state,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

    def _pending(self, ident=None, remove=False):
        path = self.directory()/'pending.json'
        values = json.loads(path.read_text('utf-8')) if path.is_file() else []
        if ident is not None:
            values = [value for value in values if value != ident]
            if not remove: values.append(ident)
            atomic(path,json.dumps(values).encode())
        return values

    def recovery_status(self):
        return {'stateHash':self.state_hash(self.preparation.state), 'pending':self._pending()}

    def resolve_recovery(self, ident, payload):
        with self.preparation.lock:
            self.get(ident)
            path = self.directory()/(ident+'-transaction.json')
            if payload.get('confirm') is not True or payload.get('expectedStateHash') != self.state_hash(self.preparation.state):
                raise AgentRuntimeError('RECOVERY_CONFIRMATION_REQUIRED','Подтвердите сохранение текущих файлов на актуальной базе.',409)
            transaction = json.loads(path.read_text('utf-8'))
            if transaction['status'] != 'conflict':
                raise AgentRuntimeError('NO_RECOVERY_CONFLICT','Нет конфликта для ручного разрешения.',409)
            transaction['status']='resolved_keep_current'
            atomic(path,json.dumps(transaction,ensure_ascii=False).encode())
            self._pending(ident,remove=True)
            self.preparation.change_recovery_required = bool(self._pending())
            return {'status':'kept_current','requiresScan':True}

    def recover(self):
        from pathlib import Path
        recovered = []
        with self.preparation.lock:
            for ident in self._pending():
                self.get(ident)
                path = self.directory()/(ident+'-transaction.json')
                transaction = json.loads(path.read_text('utf-8'))
                if transaction['status'] == 'conflict':
                    raise AgentRuntimeError('CHANGE_RECOVERY_CONFLICT','Нужна проверка сохранённого журнала применения.',409)
                if transaction['status'] != 'prepared':
                    self._pending(ident,remove=True)
                    continue
                current = self.state_hash(self.preparation.state)
                after = current == transaction['afterHash']
                before = current == transaction['beforeHash']
                safe = after or before
                root = self.preparation.state.get('storageRoot')
                for name, value in transaction['diskBefore'].items():
                    target = Path(root)/'artifacts'/name
                    if target.is_symlink() or not target.resolve().is_relative_to(Path(root).resolve()):
                        safe = False
                        break
                    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
                    original = hashlib.sha256(base64.b64decode(value)).hexdigest() if value is not None else None
                    expected = transaction['diskAfter'][name]
                    if actual not in (original, expected) or (after and actual != expected):
                        safe = False
                        break
                if not safe:
                    transaction['status'] = 'conflict'
                    atomic(path,json.dumps(transaction,ensure_ascii=False).encode())
                    raise AgentRuntimeError('CHANGE_RECOVERY_CONFLICT','Незавершённое применение конфликтует с новой правкой. Сохранён журнал; нужна ручная проверка.',409)
                if before and root:
                    for name,value in transaction['diskBefore'].items():
                        target=Path(root)/'artifacts'/name
                        if value is None:
                            if target.exists(): target.unlink()
                        else:self.preparation._storage_write('artifacts/'+name,base64.b64decode(value))
                self.preparation.save()
                if after:
                    self._write(transaction['itemAfter'])
                transaction['status']='committed' if after else 'rolled_back'
                atomic(path,json.dumps(transaction,ensure_ascii=False).encode())
                self._pending(ident,remove=True)
                recovered.append(transaction['status'])
        return recovered

    def _write(self, item):
        atomic(self.directory() / (item['id'] + '.json'), json.dumps(item, ensure_ascii=False, indent=2).encode())
        index = self.directory() / 'index.json'
        rows = json.loads(index.read_text('utf-8')) if index.is_file() else []
        rows = [row for row in rows if row['id'] != item['id']]
        rows.append({key:item[key] for key in ('id','status','createdAt','request','targets','baseDigest')})
        rows.sort(key=lambda row:row['createdAt'],reverse=True)
        atomic(index,json.dumps(rows[:100],ensure_ascii=False).encode())
        return item

    def get(self, ident):
        if not isinstance(ident, str) or len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
            raise AgentRuntimeError('CHANGE_NOT_FOUND', 'Предложение не найдено.', 404)
        path = self.directory() / (ident + '.json')
        if not path.is_file():
            raise AgentRuntimeError('CHANGE_NOT_FOUND', 'Предложение не найдено.', 404)
        return json.loads(path.read_text('utf-8'))

    def list(self):
        with self.preparation.lock:
            self.recover()
            index = self.directory() / 'index.json'
            return json.loads(index.read_text('utf-8')) if index.is_file() else []

    def scan(self, payload):
        from pathlib import Path
        with self.preparation.lock:
            context = self.context()
            root = self.preparation.state.get('storageRoot')
            if not root:
                raise AgentRuntimeError('PROJECT_FOLDER_REQUIRED', 'Для чтения правок нужна папка проекта.')
            targets = payload.get('targets', list(context['files']))
            if not isinstance(targets, list) or any(path not in context['files'] for path in targets):
                raise AgentRuntimeError('CHANGE_TARGET_REQUIRED', 'Выберите зарегистрированные артефакты.')
            replacements = {}
            for path in targets:
                file = Path(root) / 'artifacts' / path
                if not file.is_file():
                    raise AgentRuntimeError('ARTIFACT_MISSING', f'Артефакт удалён: {path}. Уточните, чем его заменить.')
                text = file.read_text('utf-8-sig')
                if text != context['files'][path]:
                    replacements[path] = text
            if not replacements:
                return {'status':'unchanged','baseDigest':context['baseDigest'],'changes':[]}
            return self.propose({'request':payload.get('request','Согласовать изменения файлов на диске'),
                                 'targets':list(replacements), 'files':replacements, 'baseDigest':context['baseDigest']})

    def propose(self, payload):
        with self.preparation.lock:
            context = self.context()
            request, targets, replacements = payload.get('request'), payload.get('targets'), payload.get('files', {})
            if not isinstance(request, str) or not request.strip() or len(request) > 12000:
                raise AgentRuntimeError('CHANGE_REQUEST_REQUIRED', 'Опишите желаемое изменение.')
            if not isinstance(targets, list) or not targets or not all(isinstance(path, str) and path in context['files'] for path in targets):
                raise AgentRuntimeError('CHANGE_TARGET_REQUIRED', 'Укажите существующие артефакты из контекста.')
            if not isinstance(replacements, dict) or any(path not in targets or not isinstance(text, str) for path, text in replacements.items()):
                raise AgentRuntimeError('INVALID_CHANGE_FILES', 'Передайте новые версии выбранных артефактов.')
            if sum(len(text.encode()) for text in replacements.values()) > 8 * 1024 * 1024:
                raise AgentRuntimeError('ARTIFACT_LIMIT', 'Изменения превышают 8 МБ.')
            if payload.get('baseDigest', context['baseDigest']) != context['baseDigest']:
                raise AgentRuntimeError('STALE_CHANGE_BASE', 'Проект изменился. Повторите анализ на актуальной версии.', 409)
            if not isinstance(payload.get('validation', {}), dict):
                raise AgentRuntimeError('INVALID_CHANGE_VALIDATION', 'Метаданные проверки должны быть объектом.')
            approved = {path for path, stage in context['owners'].items() if self.preparation.state['stages'][str(stage)]['status'] == 'approved'}
            registry = build_registry({path: text.encode() for path, text in context['files'].items()}, approved)
            graph = {}
            for edge in registry['links']:
                graph.setdefault(edge['from'], []).append(edge)
            impact = {}
            from collections import deque
            queue = deque((path, True, 0) for path in targets)
            # ID co-occurrence is a possible relationship, never proof of dependency.
            queue.extend((match.group().upper(), False, 0) for path in targets for match in ID_PATTERN.finditer(context['files'][path]))
            visited = set()
            while queue and len(visited) < 5000:
                source, certain, distance = queue.popleft()
                if (source, certain) in visited:
                    continue
                visited.add((source, certain))
                for edge in graph.get(source, []):
                    target = edge['to']
                    confirmed = certain and edge.get('confidence') == 'confirmed'
                    if target in context['files'] and target not in targets:
                        old = impact.get(target)
                        if not old or confirmed:
                            impact[target] = {'path': target, 'stage': context['owners'][target],
                                              'confidence': 'confirmed' if confirmed else 'possible', 'via': source, 'evidence': edge.get('evidence')}
                    queue.append((target, confirmed, distance + 1))
            stage_rank = getattr(self.preparation, 'stage_number', lambda value: value + 1)
            earliest = min(stage_rank(context['owners'][path]) for path in targets)
            for path, stage in context['owners'].items():
                if stage_rank(stage) > earliest and path not in targets and path not in impact:
                    impact[path] = {'path': path, 'stage': stage, 'confidence': 'possible',
                                    'via': 'workflow', 'evidence': 'Более поздний этап; точная зависимость не установлена.'}
            changes = [{'path': path, 'before': context['files'][path], 'after': text,
                        'diff': ''.join(difflib.unified_diff(context['files'][path].splitlines(True), text.splitlines(True), fromfile=path, tofile=path))}
                       for path, text in replacements.items() if text != context['files'][path]]
            return self._write({'id': uuid.uuid4().hex, 'projectId': context['projectId'], 'baseDigest': context['baseDigest'],
                                'createdAt': now(), 'request': request.strip(), 'targets': targets, 'changes': changes,
                                'validation':payload.get('validation', {}), 'impact': list(impact.values()), 'truncated':bool(queue), 'status': 'proposed' if changes else 'analysis_only',
                                'limitations': ['Влияние кода приложения не анализировалось. Возможные связи требуют проверки.',
                                                'Уровень согласования хранится на уровне этапа, а не отдельного файла.']})

    def apply(self, ident, payload):
        with self.preparation.lock:
            item, context = self.get(ident), self.context()
            if item.get('truncated'):
                raise AgentRuntimeError('IMPACT_TRUNCATED', 'Граф слишком велик. Сузьте запрос перед применением.', 409)
            if item['status'] != 'proposed' or payload.get('confirm') is not True:
                raise AgentRuntimeError('CHANGE_CONFIRMATION_REQUIRED', 'Подтвердите конкретный diff перед применением.', 409)
            if context['baseDigest'] != item['baseDigest'] or context['projectId'] != item['projectId']:
                raise AgentRuntimeError('STALE_CHANGE_BASE', 'База изменилась. Пересчитайте влияние.', 409)
            self.preparation._check_project_idle()
            proposed = copy.deepcopy(self.preparation.state)
            touched = set()
            for change in item['changes']:
                stage = str(context['owners'][change['path']])
                proposed['stages'][stage]['files'][change['path']] = change['after']
                touched.add(stage)
            for stage in touched:
                record = proposed['stages'][stage]
                checks = self.preparation.validate(record['files'], int(stage))
                if hasattr(self.preparation, 'validate_evidence'):
                    metadata = {'requirementsEvidence':record.get('requirementsEvidence', []), 'coverage':record.get('requirementCoverage', [])}
                    metadata.update(item.get('validation', {}))
                    brief, artifacts = proposed['brief'], self.preparation.context(int(stage))
                    self.preparation.lock.release()
                    try:
                        extra_checks, evidence = self.preparation.validate_evidence(record['files'],int(stage),metadata,brief=brief,context=artifacts)
                    finally:
                        self.preparation.lock.acquire()
                    if self.context()['baseDigest'] != item['baseDigest']:
                        raise AgentRuntimeError('STALE_CHANGE_BASE','Проект изменился во время проверки.',409)
                    self.preparation._check_project_idle()
                    checks.extend(extra_checks)
                    record.update(evidence)
                if not all(check['status'] == 'passed' for check in checks):
                    raise AgentRuntimeError('INVALID_CHANGE_RESULT', 'Изменённые документы не прошли проверки.', 409)
                record.update(status='review', checks=checks)
                record.pop('error', None)
            review_stages = payload.get('reviewStages', sorted({entry['stage'] for entry in item['impact']}))
            suggested = {entry['stage'] for entry in item['impact']}
            if not isinstance(review_stages, list) or any(type(stage) is not int or stage not in suggested for stage in review_stages):
                raise AgentRuntimeError('INVALID_REVIEW_STAGES', 'Выберите этапы из отчёта влияния.')
            for stage in review_stages:
                if str(stage) not in touched:
                    proposed['stages'][str(stage)]['status'] = 'stale'
            required = {entry['stage'] for entry in item['impact'] if entry['confidence'] == 'confirmed'}
            if not required <= set(review_stages):
                raise AgentRuntimeError('REQUIRED_DEPENDENCY_REVIEW', 'Подтверждённые зависимости требуют повторной проверки.', 409)
            proposed.setdefault('artifactDecisions', []).append({'changeRequestId':ident, 'request':item['request'], 'targets':item['targets'], 'baseDigest':item['baseDigest']})
            for stage in touched:
                proposed['stages'][stage]['changeRequestId'] = ident
                proposed['stages'][stage]['methodologyStatus'] = 'requires_review'
            proposed['lastStage'] = min(map(int, touched))
            if proposed.get('prototype'):
                proposed['prototype']['status'] = 'stale'
            if proposed.get('returnedProject'):
                proposed['returnedProject']['status'] = 'stale'
            # Preserve the complete prior state and proposals before mutation.
            atomic(self.directory() / (ident + '-before.json'), json.dumps(self.preparation.state, ensure_ascii=False).encode())
            previous = self.preparation.state
            transaction = {'status':'prepared','beforeHash':self.state_hash(previous),'afterHash':self.state_hash(proposed),
                           'diskBefore':{},'diskAfter':{},'itemAfter':{**item,'status':'applied','appliedAt':now(),'reviewStages':review_stages}}
            if proposed.get('storageRoot'):
                from pathlib import Path
                for change in item['changes']:
                    target=Path(proposed['storageRoot'])/'artifacts'/change['path']
                    transaction['diskBefore'][change['path']]=base64.b64encode(target.read_bytes()).decode() if target.is_file() else None
                    transaction['diskAfter'][change['path']]=hashlib.sha256(change['after'].encode()).hexdigest()
            journal = self.directory()/(ident+'-transaction.json')
            atomic(journal,json.dumps(transaction,ensure_ascii=False).encode())
            self._pending(ident)
            written = []
            try:
                if proposed.get('storageRoot'):
                    for change in item['changes']:
                        from pathlib import Path
                        target = Path(proposed['storageRoot']) / 'artifacts' / change['path']
                        original = target.read_bytes() if target.is_file() else None
                        written.append((change, original))
                        self.preparation._storage_write('artifacts/' + change['path'], change['after'].encode())
                self.preparation.state = proposed
                self.preparation.save()
            except Exception:
                self.preparation.state = previous
                try:
                    for change, original in written:
                        if original is not None:
                            self.preparation._storage_write('artifacts/' + change['path'], original)
                        else:
                            target = Path(previous['storageRoot']) / 'artifacts' / change['path']
                            if target.exists() and not target.is_symlink():
                                target.unlink()
                    self.preparation.save()
                    transaction['status']='rolled_back'
                    atomic(journal,json.dumps(transaction,ensure_ascii=False).encode())
                    self._pending(ident,remove=True)
                except Exception:
                    self.preparation.change_recovery_required = True
                    # Keep the prepared journal: restart must inspect the actual durable state.
                raise
            item.update(status='applied', appliedAt=now(), reviewStages=review_stages)
            self._write(item)
            transaction['status']='committed'
            atomic(journal,json.dumps(transaction,ensure_ascii=False).encode())
            self._pending(ident,remove=True)
            return item

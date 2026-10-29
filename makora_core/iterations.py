"""Persistent, review-first external-AI project iteration workflow.\n\nArchives are treated as data. Nothing imported from a project is executed.\n"""
from __future__ import annotations

import difflib
import copy
import io
import json
import re
import stat
import threading
import uuid
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .workspace import MakoraError, atomic, checksum
from .artifact_registry import build_registry

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_TOTAL_UNPACKED = 300 * 1024 * 1024
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_FILES = 10000
MAX_RATIO = 1000
TEXT_LIMIT = 1024 * 1024
CHANGESET_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "required": ["base_revision", "changes"],
    "properties": {
        "base_revision": {"type": "string"},
        "changes": {"type": "array", "items": {
            "type": "object", "required": ["id", "operation", "path", "reason"],
            "properties": {
                "id": {"type": "string"},
                "operation": {"enum": ["add", "modify", "delete", "rename"]},
                "path": {"type": "string"}, "source_artifact": {"type": "string"},
                "proposal_path": {"type": "string"}, "reason": {"type": "string"},
                "related_ids": {"type": "array", "items": {"type": "string"}},
                "requires": {"type": "array", "items": {"type": "string"}}
            }, "additionalProperties": True,
            "allOf": [{"if":{"properties":{"operation":{"const":"rename"}}},"then":{"required":["source_artifact"]}}]
        }}
    }, "additionalProperties": True
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def revision_id(data: bytes) -> str:
    return 'rev-' + checksum(data)[:16]


def safe_name(name: str) -> str:
    name = name.replace('\\', '/')
    parts = name.split('/')
    if (not name or name.startswith('/') or re.match(r'^[A-Za-z]:', name)
            or '\x00' in name or any(part in ('', '.', '..') for part in parts)):
        raise MakoraError('UNSAFE_ARCHIVE_PATH', f'Небезопасный путь в ZIP: {name[:160]}')
    return PurePosixPath(*parts).as_posix()


def read_archive(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_ARCHIVE:
        raise MakoraError('ARCHIVE_TOO_LARGE', 'ZIP больше допустимых 100 МБ.')
    files: dict[str, bytes] = {}
    seen_paths=set()
    seen_folded=set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES:
                raise MakoraError('TOO_MANY_FILES', 'В ZIP больше 10 000 записей.')
            for info in infos:
                raw = info.filename.replace('\\', '/')
                mode = info.external_attr >> 16
                file_type=stat.S_IFMT(mode)
                if stat.S_ISLNK(mode):
                    raise MakoraError('SYMLINK_IN_ARCHIVE', f'Символьные ссылки запрещены: {raw[:160]}')
                if file_type not in (0,stat.S_IFREG,stat.S_IFDIR):
                    raise MakoraError('SPECIAL_FILE_IN_ARCHIVE', f'Специальный файл запрещён: {raw[:160]}')
                normalized=safe_name(raw.rstrip('/'))
                folded=normalized.casefold()
                if normalized in seen_paths or folded in seen_folded:
                    raise MakoraError('DUPLICATE_ARCHIVE_PATH', f'Повторяющийся путь в ZIP: {normalized}')
                seen_paths.add(normalized);seen_folded.add(folded)
                if info.is_dir() or raw.endswith('/'):
                    continue
                path = normalized
                if info.flag_bits & 1:
                    raise MakoraError('ENCRYPTED_ARCHIVE', 'Зашифрованные ZIP не поддерживаются.')
                if info.file_size > MAX_FILE_SIZE:
                    raise MakoraError('ARCHIVE_FILE_TOO_LARGE', f'Файл больше 50 МБ: {path}')
                total += info.file_size
                if total > MAX_TOTAL_UNPACKED:
                    raise MakoraError('ARCHIVE_BOMB', 'Распакованный размер ZIP больше 300 МБ.')
                if info.file_size and (not info.compress_size or info.file_size / info.compress_size > MAX_RATIO):
                    raise MakoraError('ARCHIVE_BOMB', f'Слишком высокий коэффициент сжатия: {path}')
                content = archive.read(info)  # also checks CRC
                if len(content) != info.file_size:
                    raise MakoraError('CORRUPT_ARCHIVE', f'Размер файла не совпал: {path}')
                files[path] = content
    except MakoraError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise MakoraError('INVALID_ARCHIVE', 'ZIP повреждён или не читается.') from exc
    return files


def zip_files(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(safe_name(path), content)
    return out.getvalue()


def read_project_archive(data: bytes) -> dict[str, bytes]:
    """Accept a conventional single enclosing folder without extracting it."""
    files=read_archive(data)
    if not files or any('/' not in path for path in files): return files
    roots={path.split('/',1)[0] for path in files}
    if len(roots)!=1:return files
    root=next(iter(roots))
    if root.lower() in {'src','mocks','new_mocks','proposals','input','artifacts','base','returned','accepted','makora-context'}: return files
    stripped={path.split('/',1)[1]:content for path,content in files.items()}
    anchors=('src/','mocks/','new_mocks/','proposals/','changeset.json','prototype-report.json','README.md','PROMPT.md')
    return stripped if any(path.startswith(anchors) for path in stripped) else files


def is_text(path: str, data: bytes) -> bool:
    return len(data) <= TEXT_LIMIT and b'\0' not in data and Path(path).suffix.lower() in {
        '.txt', '.md', '.json', '.yaml', '.yml', '.mmd', '.html', '.css', '.js', '.ts',
        '.tsx', '.jsx', '.py', '.xml', '.csv', '.sql', '.toml', '.ini', '.sh', '.svg', '.yaml'
    }


def stage_hints(path):
    low=path.lower(); stages=[]
    if low.startswith(('proposals/01/','01_','01/','artifacts/01/')): stages.append('01')
    if low.startswith(('proposals/02/','02_','02/','artifacts/02/')) or 'user-flow' in low or 'task-flow' in low: stages.append('02')
    if not low.startswith(('src/','app/','components/','public/','assets/')) and (low.startswith(('proposals/03/','03_','03/','artifacts/03/')) or any(x in low for x in ('openapi','architecture','tasks','test_plan'))): stages.append('03')
    if low.startswith(('proposals/04/','04_','04/','artifacts/04/','mocks/','new_mocks/')): stages.append('04')
    return stages


def file_category(path):
    low=path.lower()
    if low.startswith(('mocks/','new_mocks/')):return 'data'
    if low.startswith(('proposals/','01_','02_','03_','04_','01/','02/','03/','04/','artifacts/')) or low=='artifact-links.json':return 'artifact'
    return 'application'


def possible_stage_hints(path):
    low=path.lower();result=set(stage_hints(path))
    if low.startswith(('src/','app/','components/')) and Path(low).suffix not in ('.css','.scss','.sass','.svg','.png','.jpg','.gif','.webp'):
        result.add('03')
    return sorted(result)


def validate_document_links(path, value):
    errors=[]
    name=Path(path).name.lower()
    if name in ('openapi.yaml','openapi.yml','openapi.json'):
        if (not isinstance(value,dict) or not isinstance(value.get('openapi'),str)
                or not isinstance(value.get('info'),dict) or not isinstance(value.get('paths'),dict)
                or not all(isinstance(value['info'].get(k),str) and value['info'][k] for k in ('title','version'))):
            errors.append(f'{path}: OpenAPI должен содержать версию, info.title, info.version и paths.')
    if name in ('tasks.json','03_tasks.json'):
        tasks=value.get('tasks') if isinstance(value,dict) else None
        if not isinstance(tasks,list): return errors+[f'{path}: ожидается массив tasks.']
        graph={}
        for task in tasks:
            if not isinstance(task,dict) or not isinstance(task.get('id'),str) or not task['id']:
                errors.append(f'{path}: каждая задача должна иметь id.');continue
            ident=task['id'];deps=task.get('dependsOn',task.get('depends_on',[]))
            if ident in graph: errors.append(f'{path}: повторяется ID задачи {ident}.');continue
            if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps):
                errors.append(f'{path}: зависимости задачи {ident} должны быть массивом ID.');deps=[]
            graph[ident]=deps
        for ident,deps in graph.items():
            for dep in deps:
                if dep not in graph:errors.append(f'{path}: у {ident} отсутствует зависимость {dep}.')
        pending={ident:len({d for d in deps if d in graph}) for ident,deps in graph.items()}
        consumers={ident:[] for ident in graph}
        for ident,deps in graph.items():
            for dep in set(deps):
                if dep in consumers:consumers[dep].append(ident)
        ready=deque(ident for ident,count in pending.items() if count==0);processed=0
        while ready:
            ident=ready.popleft();processed+=1
            for child in consumers[ident]:
                pending[child]-=1
                if pending[child]==0:ready.append(child)
        if processed<len(graph): errors.append(f'{path}: обнаружен цикл зависимостей задач.')
    return errors


class IterationStore:
    """Atomic JSON index + immutable archive snapshots for a local Makora project."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.state = self.root / 'state' / 'iterations'
        self.index_path = self.state / 'index.json'
        self.state.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._save({'schema_version': 1, 'revisions': [], 'iterations': [], 'decisions': [], 'artifact_links': []})
        self.index = json.loads(self.index_path.read_text(encoding='utf-8'))
        self.index.setdefault('artifact_links',[])
        migrated=self._migrate_artifact_approvals()
        for item in self.index.get('iterations',[]):
            if item.get('status')=='approved' or item.get('analysis_version',0)>=2 or not item.get('changes'):continue
            item.setdefault('analysis_history',[]).append({'time':timestamp(),'reason':'Обновлена оценка зависимостей',
                'changes':copy.deepcopy(item['changes']),'impacted_artifacts':copy.deepcopy(item.get('impacted_artifacts',[]))})
            for change in item['changes']:
                change['category']=file_category(change['path']);change['impacted_stages']=[]
                change['possible_stages']=possible_stage_hints(change['path'])
            item['impacted_artifacts']=self._apply_graph(item['changes']);item['analysis_version']=2;migrated=True
        if migrated:self._save()

    def _migrate_artifact_approvals(self):
        changed=False
        for revision in self.index.get('revisions',[]):
            if 'approved_artifacts' in revision:continue
            try:files=read_project_archive(self._archive(revision))
            except (OSError,MakoraError):continue
            if revision.get('reason')=='initial':
                approved={a['path'] for a in build_registry(files)['artifacts'] if a['status']=='approved'}
            else:
                source_id=revision.get('parent_revision')
                if revision.get('reason','').startswith('rollback from '):source_id=revision['reason'].removeprefix('rollback from ')
                source=next((r for r in self.index['revisions'] if r['revision_id']==source_id),{})
                approved=set(source.get('approved_artifacts',[]))
                iteration=next((i for i in self.index.get('iterations',[]) if i.get('approved_revision')==revision['revision_id']),None)
                if iteration:
                    for change in iteration.get('changes',[]):
                        if change.get('decision')!='accepted':continue
                        path=change.get('path','')
                        if change.get('operation')=='delete':approved.discard(path)
                        else:
                            if change.get('old_path'):approved.discard(change['old_path'])
                            if stage_hints(path) and not path.startswith('proposals/'):approved.add(path)
                    for path,decision in iteration.get('document_decisions',{}).items():
                        if decision=='accepted':approved.add(self._proposal_target(path))
                    report=(iteration.get('adaptation') or {}).get('report') or {}
                    reviewed=report.get('reviewed_unchanged',[]) if isinstance(report,dict) else []
                    if isinstance(reviewed,list):approved.update(p for p in reviewed if isinstance(p,str))
            revision['approved_artifacts']=sorted(p for p in approved if p in files);changed=True
        return changed

    def _save(self, value=None):
        if value is not None:
            self.index = value
        atomic(self.index_path, json.dumps(self.index, ensure_ascii=False, indent=2).encode('utf-8'))

    def synchronized(method):
        def wrapped(self, *args, **kwargs):
            with self.lock:
                return method(self, *args, **kwargs)
        wrapped.__name__ = method.__name__
        wrapped.__doc__ = method.__doc__
        return wrapped

    def _archive_path(self, relative):
        path = (self.state / relative).resolve()
        if not path.is_relative_to(self.state.resolve()):
            raise MakoraError('INVALID_PATH', 'Путь снимка выходит за пределы хранилища.')
        return path

    def _put_revision(self, archive: bytes, parent=None, reason='approved'):
        rid = revision_id(archive)
        existing = next((r for r in self.index['revisions'] if r['revision_id'] == rid), None)
        if existing:
            # Revisions are content-addressed; rollback still needs a new revision event.
            rid = 'rev-' + uuid.uuid4().hex[:16]
        filename = f'revisions/{rid}.zip'
        atomic(self._archive_path(filename), archive)
        item = {'revision_id': rid, 'sha256': checksum(archive), 'archive': filename,
                'parent_revision': parent, 'created_at': timestamp(), 'reason': reason,
                'artifact_links':copy.deepcopy(self.index.get('artifact_links',[]))}
        self.index['revisions'].append(item)
        return item

    def _revision(self, rid):
        item = next((r for r in self.index['revisions'] if r['revision_id'] == rid), None)
        if not item:
            raise MakoraError('REVISION_NOT_FOUND', f'Версия {rid} не найдена.')
        return item

    def _iteration(self, iid):
        item = next((x for x in self.index['iterations'] if x['iteration_id'] == iid), None)
        if not item:
            raise MakoraError('ITERATION_NOT_FOUND', f'Итерация {iid} не найдена.')
        return item

    def _archive(self, item):
        return self._archive_path(item['archive']).read_bytes()

    def current_revision(self):
        return next((r for r in reversed(self.index['revisions']) if r.get('current')), None)

    @synchronized
    def register_links(self, links, replace=False, persist=True):
        if not isinstance(links,list): raise MakoraError('INVALID_LINKS','Связи должны быть массивом.')
        normalized=[]
        for edge in links:
            if not isinstance(edge,dict): raise MakoraError('INVALID_LINKS','Каждая связь должна быть объектом.')
            source,target=edge.get('from'),edge.get('to')
            if not all(isinstance(x,str) and x.strip() and len(x)<=300 and not any(ord(c)<32 for c in x) for x in (source,target)) or source==target:
                raise MakoraError('INVALID_LINKS','Связь должна содержать разные непустые from и to.')
            confidence=edge.get('confidence','confirmed')
            if confidence not in ('confirmed','inferred'):raise MakoraError('INVALID_LINKS','Некорректная достоверность связи.')
            normalized.append({'from':source.strip(),'to':target.strip(),'kind':str(edge.get('kind','depends_on'))[:80],
                               'confidence':confidence,'evidence':str(edge.get('evidence',''))[:500],
                               'origin':'generated' if edge.get('origin')=='generated' else 'manual'})
        combined=[] if replace else list(self.index.get('artifact_links',[]))
        known={(x['from'],x['to'],x['kind']) for x in combined}
        for edge in normalized:
            key=(edge['from'],edge['to'],edge['kind'])
            if key not in known: combined.append(edge);known.add(key)
        self.index['artifact_links']=combined
        if persist:self._save()
        return combined

    def _apply_graph(self, changes):
        graph={}
        for edge in self.index.get('artifact_links',[]): graph.setdefault(edge['from'],[]).append(edge)
        impacted={}
        for change in changes:
            seeds=[change['path']]+([change['old_path']] if change.get('old_path') else [])+[x for x in change.get('related_ids',[]) if isinstance(x,str)]
            visited={(node,True) for node in seeds};queue=deque((node,0,True) for node in seeds);related=[]
            while queue:
                node,depth,confirmed=queue.popleft()
                for edge in graph.get(node,[]):
                    target=edge['to'];certain=confirmed and edge.get('confidence','confirmed')=='confirmed'
                    if (target,certain) in visited: continue
                    visited.add((target,certain));queue.append((target,depth+1,certain))
                    relation={'artifact':target,'distance':depth+1,'via':node,'basis':'registered' if certain else 'inferred', 'evidence':edge.get('evidence','')}
                    related.append(relation)
                    if target not in impacted or certain:impacted[target]={'artifact':target,'status':'needs_review' if certain else 'suggested','basis':'registered' if certain else 'inferred'}
                    field='impacted_stages' if certain else 'possible_stages'
                    change[field]=sorted(set(change.get(field,[]))|set(stage_hints(target)))
            change['related_artifacts']=related
            change['impact_basis']='registered' if any(r['basis']=='registered' for r in related) else ('inferred' if related or change.get('possible_stages') else 'none')
        return list(impacted.values())

    @synchronized
    def prepare(self, package: bytes, base_revision: str | None = None):
        context = read_archive(package)
        current = self.current_revision()
        if not current:
            registry=build_registry(context)
            context['artifact-registry.json']=json.dumps(registry,ensure_ascii=False,indent=2).encode('utf-8')
            package=zip_files(context)
            base = self._put_revision(package, reason='initial')
            base['current'] = True
            self.index['revisions'][-1] = base
            current = base
            if 'artifact-links.json' in context:
                try: document=json.loads(context['artifact-links.json'].decode('utf-8'))
                except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise MakoraError('INVALID_LINKS','artifact-links.json повреждён.') from exc
                self.register_links(document.get('links') if isinstance(document,dict) else None,persist=False)
            self.register_links(registry['links'],persist=False)
            base['artifact_links']=copy.deepcopy(self.index['artifact_links'])
            base['approved_artifacts']=[a['path'] for a in registry['artifacts'] if a['status']=='approved']
        elif base_revision is None:
            base_revision = current['revision_id']
        if base_revision and base_revision != current['revision_id']:
            raise MakoraError('STALE_BASE', 'Нельзя подготовить пакет от устаревшей версии; сначала обновите проект.')
        if current and current['reason'] != 'initial':
            # Carry the last approved application forward, while keeping newly approved
            # Makora documents in a separate context folder to avoid silent overwrites.
            project_files = read_archive(self._archive(current))
            merged = dict(project_files)
            merged.update({f'makora-context/{path}': data for path, data in context.items()})
            if 'PROMPT.md' in context:
                merged['PROMPT.md'] = (
                    ('# Продолжи разработку существующего проекта\n\n'
                     'Не пересоздавай проект. Согласованный проект и документы находятся в корне архива. '
                     'В makora-context/ находится текущее состояние доски Макоры; её демонстрационные материалы могут быть устаревшими. '
                     'При расхождениях уточни их и опирайся на согласованные файлы в корне.\n\n').encode('utf-8')
                    + context['PROMPT.md']
                )
            package = zip_files(merged)
        iid = 'it-' + uuid.uuid4().hex[:16]
        package_files=read_archive(package)
        approved_files=read_archive(self._archive(current))
        registry=build_registry(approved_files,current.get('approved_artifacts'))
        self.index['artifact_links']=[edge for edge in self.index.get('artifact_links',[]) if edge.get('origin')!='generated']
        self.register_links(registry['links'],persist=False)
        package_files['artifact-registry.json']=json.dumps(registry,ensure_ascii=False,indent=2).encode('utf-8')
        package_files['iteration-context.json']=json.dumps({
            'iteration_id':iid,'base_revision':current['revision_id'],
            'base_checksum':current['sha256'],
            'note':'Идентификаторы исходной согласованной версии для этой передачи.'
        },ensure_ascii=False,indent=2).encode('utf-8')
        package=zip_files(package_files)
        filename = f'iterations/{iid}/package.zip'
        atomic(self._archive_path(filename), package)
        item = {'iteration_id': iid, 'base_revision': current['revision_id'],
                'base_checksum': current['sha256'], 'package': filename, 'package_sha256':checksum(package),
                'status': 'package_ready', 'created_at': timestamp(), 'changes': [],
                'questions': [], 'choices': {}, 'adaptation': None, 'checks': []}
        self.index['iterations'].append(item)
        self._save()
        return self.summary()

    @synchronized
    def mark_sent(self, iid):
        item=self._iteration(iid)
        if item['status'] != 'package_ready':
            raise MakoraError('INVALID_ITERATION_STATUS','Пакет уже отправлен или итерация завершена.')
        item['status']='waiting_external';item['sent_at']=timestamp()
        self._save()
        return self.iteration(iid)

    def _diff(self, base_data, returned_data, preserve_missing_artifacts=False):
        base, returned = read_project_archive(base_data), read_project_archive(returned_data)
        declared_deletes=set()
        declared_renames=[]
        try:
            declaration=json.loads(returned.get('changeset.json',b'{}').decode('utf-8'))
            if isinstance(declaration,dict) and isinstance(declaration.get('changes'),list):
                declared_deletes={c.get('path') for c in declaration['changes'] if isinstance(c,dict) and c.get('operation')=='delete' and isinstance(c.get('path'),str)}
                declared_deletes.update(c.get('source_artifact') for c in declaration['changes'] if isinstance(c,dict) and c.get('operation')=='rename' and isinstance(c.get('source_artifact'),str))
                declared_renames=[(c.get('source_artifact'),c.get('path')) for c in declaration['changes'] if isinstance(c,dict) and c.get('operation')=='rename' and isinstance(c.get('source_artifact'),str) and isinstance(c.get('path'),str)]
        except (UnicodeDecodeError,json.JSONDecodeError):pass
        added_hashes={(file_category(path),checksum(data)) for path,data in returned.items() if path not in base}
        output = []
        for path in sorted(set(base) | set(returned)):
            if path.startswith('makora-context/') or path in ('iteration-context.json','context-status.json','PROMPT.md','changeset.schema.json','artifact-registry.json'): continue
            before, after = base.get(path), returned.get(path)
            if before == after:
                continue
            if preserve_missing_artifacts and before is not None and after is None and path not in declared_deletes and (file_category(path),checksum(before)) not in added_hashes and file_category(path) in ('artifact','data'):
                continue
            operation = 'add' if before is None else 'delete' if after is None else 'modify'
            change_id = 'chg-' + checksum(path.encode())[:10]
            record = {'id': change_id, 'path': path, 'operation': operation,'category':file_category(path),
                      'before_sha256': checksum(before) if before is not None else None,
                      'after_sha256': checksum(after) if after is not None else None,
                      'size_before': len(before) if before is not None else None,
                      'size_after': len(after) if after is not None else None,
                      'decision': 'pending', 'reason': None, 'related_ids': [], 'requires': []}
            if path == 'changeset.json': record['decision'] = 'informational'
            if (before is None or is_text(path,before)) and (after is None or is_text(path,after)):
                a = (before or b'').decode('utf-8', errors='replace').splitlines(keepends=True)
                b = (after or b'').decode('utf-8', errors='replace').splitlines(keepends=True)
                record['diff'] = ''.join(list(difflib.unified_diff(a, b, fromfile='Было: '+path,
                                                                  tofile='Стало: '+path, n=3))[:1000])
                record['kind'] = 'text'
            else:
                record['kind'] = 'binary' if before is not None and after is not None else 'file'
            low = path.lower()
            record['impacted_stages'] = []
            record['possible_stages'] = possible_stage_hints(path)
            record['mocks_changed'] = (low.startswith('mocks/') or '/mocks/' in low) and not low.startswith('proposals/')
            output.append(record)
        additions={};deletions={}
        for change in output:
            if change['operation']=='add':additions.setdefault((change['category'],change['after_sha256']),[]).append(change)
            if change['operation']=='delete':deletions.setdefault((change['category'],change['before_sha256']),[]).append(change)
        merged=[];consumed=set()
        def merge_rename(old,new):
            consumed.update((old['id'],new['id']))
            item=dict(new);item.update({'id':'chg-'+checksum((old['path']+'\0'+new['path']).encode())[:10],
                'operation':'rename','old_path':old['path'],'before_sha256':old['before_sha256'],
                'size_before':old['size_before'],'diff':'','mocks_changed':old['mocks_changed'] or new['mocks_changed'],
                'impacted_stages':sorted(set(old['impacted_stages'])|set(new['impacted_stages'])),
                'possible_stages':sorted(set(old['possible_stages'])|set(new['possible_stages']))})
            before,after=base[old['path']],returned[new['path']]
            if is_text(old['path'],before) and is_text(new['path'],after) and before!=after:
                item['kind']='text';item['diff']=''.join(list(difflib.unified_diff(before.decode('utf-8',errors='replace').splitlines(keepends=True),after.decode('utf-8',errors='replace').splitlines(keepends=True),fromfile='Было: '+old['path'],tofile='Стало: '+new['path'],n=3))[:1000])
            merged.append(item)
        for old_path,new_path in declared_renames:
            old=next((c for c in output if c['operation']=='delete' and c['path']==old_path and c['id'] not in consumed),None)
            new=next((c for c in output if c['operation']=='add' and c['path']==new_path and c['id'] not in consumed),None)
            if old and new and old['category']==new['category']:merge_rename(old,new)
        for key,deleted in deletions.items():
            added=additions.get(key,[])
            if key[1] and len(deleted)==len(added)==1 and deleted[0]['id'] not in consumed and added[0]['id'] not in consumed:
                merge_rename(deleted[0],added[0])
        output=[c for c in output if c['id'] not in consumed]+merged
        output.sort(key=lambda c:c['path'])
        return output, base, returned

    def _parse_changeset(self, files, changes):
        raw = files.get('changeset.json')
        if raw is None:
            return {'present': False, 'valid': None, 'errors': [], 'declared_missing': [],
                    'undeclared': [c['path'] for c in changes]}
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {'present': True, 'valid': False, 'errors': ['changeset.json содержит некорректный JSON.'],
                    'declared_missing': [], 'undeclared': [c['path'] for c in changes]}
        errors = []
        if not isinstance(value, dict) or not isinstance(value.get('base_revision'), str) or not isinstance(value.get('changes'), list):
            errors.append('Ожидаются base_revision и массив changes.')
            declared = []
        else:
            declared = []
            seen = set()
            seen_paths=set()
            for entry in value['changes']:
                if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry[k] for k in ('id','operation','path','reason')):
                    errors.append('Каждое изменение должно содержать id, operation, path и reason.')
                    continue
                if entry['operation'] not in ('add','modify','delete','rename'):
                    errors.append('Недопустимая operation для '+entry['id']+'.')
                for key in ('related_ids','requires'):
                    value_list=entry.get(key,[])
                    if not isinstance(value_list,list) or any(not isinstance(part,str) for part in value_list):
                        errors.append(key+' должен быть массивом строк для '+entry['id']+'.')
                try:
                    entry['path'] = safe_name(entry['path'])
                except MakoraError as exc:
                    errors.append(str(exc)); continue
                if entry['id'] in seen: errors.append('ID changeset повторяется: ' + entry['id'])
                if entry['path'] in seen_paths: errors.append('Путь changeset заявлен несколько раз: '+entry['path'])
                seen_paths.add(entry['path'])
                seen.add(entry['id']); declared.append(entry['path'])
                matched = next((c for c in changes if c['path'] == entry['path']), None)
                if matched:
                    if matched['operation'] != entry['operation']:
                        errors.append('Заявленная операция не совпадает с фактической для '+entry['path']+'.')
                    if entry['operation']=='rename' and entry.get('source_artifact')!=matched.get('old_path'):
                        errors.append('Для rename укажите исходный путь в source_artifact: '+entry['path']+'.')
                    matched['reason'] = entry['reason']
                    matched['requires'] = [v for v in entry.get('requires',[]) if isinstance(v,str)] if isinstance(entry.get('requires',[]),list) else []
                    matched['related_ids'] = [v for v in entry.get('related_ids',[]) if isinstance(v,str)] if isinstance(entry.get('related_ids',[]),list) else []
                    matched['change_set_id'] = entry['id']
                else: errors.append('Заявленное изменение отсутствует в файлах: ' + entry['path'])
        actual = {c['path'] for c in changes if c['path'] != 'changeset.json'}
        return {'present': True, 'valid': not errors, 'errors': errors,
                'declared_missing': [p for p in declared if p not in actual],
                'undeclared': sorted(actual - set(declared)), 'base_revision': value.get('base_revision') if isinstance(value, dict) else None}

    @staticmethod
    def _prototype_report(files):
        raw=files.get('prototype-report.json')
        if raw is None:
            return {'status':'not_run','errors':['prototype-report.json отсутствует.'],'features':[],
                    'checks':[],'run_commands':[],'known_limitations':[],'contradictions':[]}
        try: report=json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError,json.JSONDecodeError):
            return {'status':'failed','errors':['prototype-report.json содержит некорректный JSON.'],'features':[],
                    'checks':[],'run_commands':[],'known_limitations':[],'contradictions':[]}
        if not isinstance(report,dict):
            return {'status':'failed','errors':['Корень prototype-report.json должен быть объектом.'],'features':[],
                    'checks':[],'run_commands':[],'known_limitations':[],'contradictions':[]}
        errors=[]
        for key in ('features','checks','run_commands','known_limitations','contradictions'):
            if not isinstance(report.get(key),list): errors.append(f'{key} должен быть массивом.')
        statuses={'passed','failed','not_run'}
        checks=report.get('checks',[])
        if isinstance(checks,list):
            for index,check in enumerate(checks):
                if not isinstance(check,dict) or not isinstance(check.get('id'),str) or not isinstance(check.get('status'),str) or check.get('status') not in statuses or not isinstance(check.get('command'),str) or not isinstance(check.get('result'),str):
                    errors.append(f'checks[{index}] должен содержать id, статус passed/failed/not_run, command и result.')
        for key in ('features','run_commands','known_limitations','contradictions'):
            value=report.get(key,[])
            if isinstance(value,list) and any(not isinstance(entry,(str,dict)) for entry in value): errors.append(f'{key} содержит неподдерживаемое значение.')
        return {'status':'failed' if errors else 'parsed','errors':errors,'features':report.get('features',[]),
                'checks':checks if isinstance(checks,list) else [],'run_commands':report.get('run_commands',[]) if isinstance(report.get('run_commands'),list) else [],
                'known_limitations':report.get('known_limitations',[]) if isinstance(report.get('known_limitations'),list) else [],
                'contradictions':report.get('contradictions',[]) if isinstance(report.get('contradictions'),list) else []}

    @synchronized
    def return_project(self, iid, archive: bytes):
        item = self._iteration(iid)
        if item.get('status')=='approved':
            raise MakoraError('ITERATION_CLOSED','Эта итерация уже согласована. Создайте следующую итерацию.')
        files = read_project_archive(archive)
        base_revision = self._revision(item['base_revision'])
        changes, base_files, returned_files = self._diff(self._archive(base_revision), archive, preserve_missing_artifacts=True)
        change_set = self._parse_changeset(returned_files, changes)
        impacted_artifacts=self._apply_graph(changes)
        prototype_report=self._prototype_report(returned_files)
        removed_paths={c.get('old_path') if c['operation']=='rename' else c['path'] for c in changes if c['operation'] in ('rename','delete')}
        missing_artifacts=[p for p in base_files if p not in returned_files and p not in removed_paths and file_category(p) in ('artifact','data') and not p.startswith('proposals/') and p not in ('artifact-registry.json','iteration-context.json')]
        stale = self.current_revision()['revision_id'] != item['base_revision']
        declared_base=change_set.get('base_revision')
        if declared_base and declared_base != item['base_revision']: stale=True
        if item.get('result'):
            fields=('result','result_sha256','returned_at','changes','changeset','prototype_report','status',
                    'questions','question_answers','adaptation','adapted_docs','document_decisions','checks')
            item.setdefault('return_history',[]).append(copy.deepcopy({key:item[key] for key in fields if key in item}))
        for key in ('question_answers','adaptation','adapted_docs','document_decisions'):
            item.pop(key,None)
        # Automatically register proposals as proposed changes; never apply/approve them.
        proposal_paths = [p for p in returned_files if p.startswith('proposals/')]
        for change in changes:
            change['proposal'] = change['path'] in proposal_paths
            if change['mocks_changed']:
                change['reason'] = change.get('reason') or 'Изменены исходные мок-данные; требуется отдельное решение.'
        item.update({'result': f"iterations/{iid}/returned-{uuid.uuid4().hex}.zip", 'result_sha256': checksum(archive),
                     'returned_at': timestamp(), 'changes': changes, 'changeset': change_set,
                     'prototype_report':prototype_report,'impacted_artifacts':impacted_artifacts,'missing_artifacts':missing_artifacts,'analysis_version':2,
                     'status': 'stale_base' if stale else ('review' if changes else 'no_changes'),
                     'stale_base': stale, 'questions': self._questions(changes, change_set),
                     'checks': [{'id':'archive_safety','status':'passed','detail':'ZIP прочитан с ограничениями; код не запускался.'},
                                {'id':'changeset','status':'passed' if change_set['valid'] else ('not_run' if not change_set['present'] else 'failed'),
                                 'detail':'changeset.json проверен структурно.' if change_set['present'] else 'changeset.json отсутствует.'},
                                {'id':'prototype_report','status':prototype_report['status'] if prototype_report['status'] in ('passed','failed','not_run') else 'passed',
                                 'detail':'Отчёт прочитан и его формат проверен.' if prototype_report['status']=='parsed' else 'Отчёт отсутствует или содержит ошибки.'},
                                {'id':'missing_artifacts','status':'not_checked' if missing_artifacts else 'passed','detail':('Отсутствующие в ZIP документы и моки сохраняются из базы: '+', '.join(missing_artifacts[:8])) if missing_artifacts else 'Базовые документы и моки присутствуют.'},
                                {'id':'external_code','status':'not_checked','detail':'Внешний код не запускался.'}]})
        atomic(self._archive_path(item['result']), archive)
        self._save()
        return self.iteration(iid)

    def _questions(self, changes, changeset):
        questions = []
        if any(c['mocks_changed'] for c in changes):
            questions.append({'id':'q-mocks-source','text':'Изменены исходные mocks/. Эти изменения намеренные? Исходные файлы нужно сохранить в истории без перезаписи.',
                              'change_ids':[c['id'] for c in changes if c['mocks_changed']], 'required':True})
        if any('new_mocks' in c['path'].split('/') for c in changes):
            questions.append({'id':'q-proposals','text':'Как использовать новые мок-данные рядом с исходными и какие сценарии сохранить?',
                              'change_ids':[c['id'] for c in changes if 'new_mocks' in c['path'].split('/')], 'required':True})
        if changeset.get('undeclared'):
            questions.append({'id':'q-unexplained','text':'Часть файловых изменений не объяснена changeset.json. Проверьте причины перед применением.',
                              'change_ids':[c['id'] for c in changes if c['path'] in changeset['undeclared']], 'required':True})
        if changeset.get('base_revision') and changeset['base_revision'] != (self.current_revision() or {}).get('revision_id'):
            questions.append({'id':'q-base','text':'Заявленная базовая версия не совпадает с актуальной. Нужна ручная адаптация результата.', 'change_ids':[], 'required':True})
        if changeset.get('valid') is False:
            questions.append({'id':'q-changeset','text':'changeset.json не прошёл структурную проверку. Сверь заявленные пути с обнаруженными файлами.', 'change_ids':[], 'required':True})
        return questions[:4]

    @synchronized
    def decide(self, iid, change_id, action, note=''):
        if action not in ('accept','revise','reject'):
            raise MakoraError('INVALID_DECISION', 'Решение должно быть accept, revise или reject.')
        item = self._iteration(iid)
        if item.get('status')=='approved': raise MakoraError('ITERATION_CLOSED','Итерация уже согласована.')
        change = next((c for c in item.get('changes',[]) if c['id'] == change_id), None)
        if change is None: raise MakoraError('CHANGE_NOT_FOUND', f'Изменение {change_id} не найдено.')
        change['decision'] = {'accept':'accepted','revise':'revision_requested','reject':'rejected'}[action]
        change['decision_note'] = note
        change['decided_at'] = timestamp()
        adaptation=item.get('adaptation') or {}
        if adaptation.get('accepted_change_ids') is not None:
            accepted={c['id'] for c in item['changes'] if c['decision']=='accepted'}
            if accepted != set(adaptation['accepted_change_ids']): adaptation['status']='stale'
        self.index['decisions'].append({'iteration_id':iid,'change_id':change_id,'action':action,'note':note,'time':change['decided_at']})
        self._save()
        return self.iteration(iid)

    @synchronized
    def answer_questions(self, iid, answers):
        item=self._iteration(iid)
        if item.get('status')=='approved': raise MakoraError('ITERATION_CLOSED','Итерация уже согласована.')
        if not isinstance(answers,dict): raise MakoraError('INVALID_ANSWERS','Ответы должны быть объектом JSON.')
        if not answers: raise MakoraError('EMPTY_ANSWER','Ответы не могут быть пустыми.')
        allowed={q['id'] for q in item.get('questions',[]) if q.get('required')}
        unknown=set(answers)-allowed
        if unknown: raise MakoraError('UNKNOWN_QUESTION','Неизвестные вопросы: '+', '.join(sorted(unknown)))
        cleaned={key:str(value).strip() for key,value in answers.items()}
        if any(not value for value in cleaned.values()): raise MakoraError('EMPTY_ANSWER','Ответы не могут быть пустыми.')
        prior=dict(item.get('question_answers',{}))
        item.setdefault('question_answers',{}).update(cleaned)
        if prior!=item['question_answers'] and item.get('adaptation'): item['adaptation']['status']='stale'
        self.index['decisions'].append({'iteration_id':iid,'question_answers':cleaned,'time':timestamp()})
        self._save()
        return self.iteration(iid)

    def _check_choice_conflicts(self, item):
        by_id = {c.get('change_set_id'): c for c in item['changes'] if c.get('change_set_id')}
        conflicts = []
        for change in item['changes']:
            if change['decision'] != 'accepted': continue
            for required in change.get('requires', []):
                target = by_id.get(required) or next((c for c in item['changes'] if c['path'] == required), None)
                if target is None or target['decision'] != 'accepted':
                    conflicts.append({'change_id':change['id'],'required':required,
                                      'message':f"Принято {change['path']}, но зависимое изменение {required} не принято."})
        targets={}
        for change in item['changes']:
            if change['decision']=='accepted' and change['path'].startswith('proposals/'):
                target=self._proposal_target(change['path'])
                if target in targets:
                    conflicts.append({'change_id':change['id'],'required':targets[target],
                        'message':f"Приняты несколько предложений для {target}: {targets[target]} и {change['path']}."})
                else:targets[target]=change['path']
        return conflicts

    @synchronized
    def adaptation_package(self, iid):
        item = self._iteration(iid)
        if item.get('status')=='approved': raise MakoraError('ITERATION_CLOSED','Итерация уже согласована.')
        conflicts = self._check_choice_conflicts(item)
        if conflicts: raise MakoraError('DECISION_CONFLICT', json.dumps(conflicts, ensure_ascii=False))
        unanswered=[q['id'] for q in item.get('questions',[]) if q.get('required') and not item.get('question_answers',{}).get(q['id'])]
        if unanswered: raise MakoraError('QUESTIONS_UNANSWERED','Ответь на существенные вопросы: '+', '.join(unanswered))
        accepted = [c for c in item['changes'] if c['decision'] == 'accepted']
        if not accepted: raise MakoraError('NOTHING_ACCEPTED', 'Сначала примите хотя бы одно изменение.')
        base = read_project_archive(self._archive(self._revision(item['base_revision'])))
        returned = read_project_archive(self._archive_path(item['result']).read_bytes())
        context = {
            'iteration_id': iid, 'base_revision': item['base_revision'],
            'accepted_changes': accepted, 'all_changes': item['changes'],
            'questions': item['questions'], 'conflicts': conflicts,
            'question_answers': item.get('question_answers',{}),
            'artifact_links':self.index.get('artifact_links',[]), 'impacted_artifacts':item.get('impacted_artifacts',[]),
            'instructions':'Обнови только перечисленные затронутые документы, сохраняя ID и связи. Не переписывай исходные требования организатора и не утверждай новые требования автоматически. Верни документы в proposals/ и файл adaptation-report.json. Код не запускай.'
        }
        affected_stages={stage for change in accepted for stage in change.get('impacted_stages',[])+change.get('possible_stages',[])}
        registered={entry['artifact'] for change in accepted for entry in change.get('related_artifacts',[]) if entry.get('basis')=='registered'}
        context['impacted_artifacts']=[entry for entry in item.get('impacted_artifacts',[]) if entry['artifact'] in registered]
        document_paths=[p for p in base if p in registered or
                        (p.startswith(('01_','02_','03_','04_','mocks/','new_mocks/')) and bool(set(stage_hints(p)) & affected_stages))]
        context['documents_to_review']=[{'path':p,'basis':'registered' if p in registered else 'stage_heuristic'} for p in document_paths]
        out = {f'base/{p}':base[p] for p in document_paths}
        out.update({f'returned/{change["path"]}':returned[change['path']] for change in accepted
                    if change['path'].startswith('proposals/') and change['path'] in returned})
        for change in accepted:
            path=change['path']
            if path in returned:
                out[f'accepted/{path}']=returned[path]
        out['adaptation-context.json'] = json.dumps(context,ensure_ascii=False,indent=2).encode()
        out['ADAPTATION_PROMPT.md'] = ('# Актуализация документации\n\n'+context['instructions']+
          '\n\n## Принятые изменения\n\n'+ '\n'.join(f"- {c['path']}: {c.get('reason') or 'причина не указана'}" for c in accepted)+
          '\n\n## Документы для проверки\n\n'+'\n'.join('- '+p for p in document_paths)).encode()
        archive = zip_files(out)
        package_path=f'iterations/{iid}/adaptation-package-{uuid.uuid4().hex}.zip'
        atomic(self._archive_path(package_path),archive)
        if (item.get('adaptation') or {}).get('package') or (item.get('adaptation') or {}).get('archive'):
            item.setdefault('adaptation_history',[]).append(copy.deepcopy({'adaptation':item['adaptation'],
                'adapted_docs':item.get('adapted_docs',{}),'document_decisions':item.get('document_decisions',{})}))
        item.pop('adapted_docs',None);item.pop('document_decisions',None)
        item['adaptation'] = {'status':'package_ready','created_at':timestamp(),'sha256':checksum(archive),'package':package_path,
                              'accepted_change_ids':[c['id'] for c in accepted]}
        item['status'] = 'adaptation_pending'
        self._save()
        return archive

    @synchronized
    def import_adaptation(self, iid, archive):
        item = self._iteration(iid)
        if item.get('status')=='approved':
            raise MakoraError('ITERATION_CLOSED','Эта итерация уже согласована.')
        if not item.get('adaptation'):
            raise MakoraError('ADAPTATION_REQUIRED','Сначала подготовь пакет актуализации.')
        if item['adaptation'].get('status') not in ('package_ready','documents_received'):
            raise MakoraError('ADAPTATION_STALE','Решения изменились. Сформируй новый пакет актуализации.')
        accepted_ids={c['id'] for c in item.get('changes',[]) if c['decision']=='accepted'}
        if accepted_ids!=set(item['adaptation'].get('accepted_change_ids',[])):
            raise MakoraError('ADAPTATION_STALE','Решения изменились. Сформируй новый пакет актуализации.')
        files = read_project_archive(archive)
        proposals = {p:v for p,v in files.items() if p.startswith('proposals/')}
        report = files.get('adaptation-report.json')
        try:
            report_value = json.loads(report.decode()) if report else None
        except (UnicodeDecodeError,json.JSONDecodeError): report_value = None
        if not proposals:
            raise MakoraError('NO_ADAPTATION_DOCS', 'В архиве нет обновлённых документов в proposals/.')
        report_errors=[]
        if not isinstance(report_value,dict): report_errors.append('Нет корректного adaptation-report.json.')
        else:
            required=('iteration_id','base_revision','updated_documents','checks','unresolved_questions','assumptions','known_limitations')
            report_errors.extend('В отчёте отсутствует '+key+'.' for key in required if key not in report_value)
            if report_value.get('iteration_id') != iid: report_errors.append('В отчёте указан другой iteration_id.')
            if report_value.get('base_revision') != item['base_revision']: report_errors.append('В отчёте указана другая базовая ревизия.')
            docs=report_value.get('updated_documents',[])
            if not isinstance(docs,list): report_errors.append('updated_documents должен быть массивом.')
            else:
                documented={doc.get('path') for doc in docs if isinstance(doc,dict) and isinstance(doc.get('path'),str)}
                expected={self._proposal_target(path) for path in proposals}
                if documented != expected: report_errors.append('Список updated_documents не совпадает с файлами proposals/.')
                if any(not isinstance(doc,dict) or not isinstance(doc.get('change_reason'),str) or not isinstance(doc.get('related_ids'),list) for doc in docs):
                    report_errors.append('У документа нужны path, change_reason и related_ids.')
            checks=report_value.get('checks',[])
            allowed={'passed','failed','not_run','not_checked'}
            if not isinstance(checks,list) or any(not isinstance(check,dict) or not isinstance(check.get('id'),str) or not isinstance(check.get('status'),str) or check.get('status') not in allowed or not isinstance(check.get('detail'),str) for check in checks):
                report_errors.append('В checks нужны id, статус и detail для каждой проверки.')
            if not isinstance(report_value.get('unresolved_questions',[]),list): report_errors.append('unresolved_questions должен быть массивом.')
            if not isinstance(report_value.get('assumptions',[]),list): report_errors.append('assumptions должен быть массивом.')
            if not isinstance(report_value.get('known_limitations',[]),list): report_errors.append('known_limitations должен быть массивом.')
            if not isinstance(report_value.get('reviewed_unchanged',[]),list) or any(not isinstance(p,str) for p in report_value.get('reviewed_unchanged',[])):
                report_errors.append('reviewed_unchanged должен быть массивом путей.')
        targets=[self._proposal_target(path) for path in proposals]
        if len(targets)!=len(set(targets)): report_errors.append('Несколько документов претендуют на один и тот же путь.')
        syntax_errors=[]
        syntax_not_run=[]
        dependency_errors=[]
        for path,content in proposals.items():
            if not content.strip(): syntax_errors.append(f'Пустой документ: {path}'); continue
            suffix=Path(path).suffix.lower()
            try:
                parsed=None
                if suffix=='.json': parsed=json.loads(content.decode('utf-8'))
                elif suffix in ('.yaml','.yml'):
                    try: import yaml
                    except ImportError:
                        syntax_not_run.append(path);continue
                    parsed=yaml.safe_load(content.decode('utf-8'))
                elif suffix in ('.md','.mmd','.txt','.js','.ts','.py','.html','.css','.csv'):
                    content.decode('utf-8')
                if parsed is not None: dependency_errors.extend(validate_document_links(self._proposal_target(path),parsed))
            except (UnicodeDecodeError,ValueError) as exc: syntax_errors.append(f'Некорректное содержимое {path}: {exc}')
            except Exception as exc:
                if suffix in ('.yaml','.yml'): syntax_errors.append(f'Некорректный YAML {path}: {exc}')
        checks = [{'id':'proposal_files','status':'passed','detail':f'Найдено документов: {len(proposals)}'},
                  {'id':'adaptation_report','status':'passed' if not report_errors else 'failed',
                   'detail':'Отчёт соответствует формату.' if not report_errors else ' '.join(report_errors)},
                  {'id':'document_syntax','status':'failed' if syntax_errors else ('not_run' if syntax_not_run else 'passed'),
                   'detail':(' '.join(syntax_errors) if syntax_errors else ('YAML-проверка недоступна: '+', '.join(syntax_not_run) if syntax_not_run else 'Проверены непустые файлы и доступный синтаксис.'))},
                  {'id':'document_links','status':'failed' if dependency_errors else ('not_run' if syntax_not_run else 'passed'),
                   'detail':' '.join(dependency_errors) if dependency_errors else ('Проверка YAML недоступна.' if syntax_not_run else 'Проверены доступные структуры OpenAPI и зависимости задач.')}]
        required_stages={stage for change in item.get('changes',[]) if change['decision']=='accepted' for stage in change.get('impacted_stages',[])}
        reviewed_unchanged=report_value.get('reviewed_unchanged',[]) if isinstance(report_value,dict) and isinstance(report_value.get('reviewed_unchanged',[]),list) else []
        base_files=read_project_archive(self._archive(self._revision(item['base_revision'])))
        unknown_reviewed=[p for p in reviewed_unchanged if not isinstance(p,str) or p not in base_files]
        if unknown_reviewed:report_errors.append('Проверенные без изменений пути отсутствуют в базе: '+', '.join(map(str,unknown_reviewed)))
        returned_stages={stage for path in proposals for stage in self._proposal_stages(path,report_value)}
        returned_stages.update(stage for path in reviewed_unchanged if isinstance(path,str) for stage in stage_hints(path))
        missing_stages=sorted(required_stages-returned_stages)
        checks.append({'id':'impacted_stages','status':'failed' if missing_stages else 'passed',
                       'detail':'Нет документов для этапов: '+', '.join(missing_stages) if missing_stages else 'Для затронутых этапов возвращены документы.'})
        linked={edge['artifact'] for change in item.get('changes',[]) if change['decision']=='accepted'
                for edge in change.get('related_artifacts',[]) if edge.get('basis')=='registered' and edge['artifact'] in base_files}
        documented={self._proposal_target(path) for path in proposals}|set(p for p in reviewed_unchanged if isinstance(p,str))
        missing_linked=sorted(linked-documented)
        checks.append({'id':'linked_artifacts','status':'failed' if missing_linked else 'passed',
                       'detail':'Не рассмотрены связанные документы: '+', '.join(missing_linked) if missing_linked else 'Связанные документы рассмотрены по зарегистрированным связям.'})
        if report_errors:
            checks[1]['status']='failed';checks[1]['detail']=' '.join(report_errors)
        reported_checks=report_value.get('checks',[]) if isinstance(report_value,dict) else []
        if not isinstance(reported_checks,list): reported_checks=[]
        reported_failures=[str(c.get('id','?')) for c in reported_checks if isinstance(c,dict) and c.get('status')=='failed']
        checks.append({'id':'reported_checks','status':'failed' if reported_failures else 'not_checked',
                       'detail':'По отчёту внешнего ИИ не прошли: '+', '.join(reported_failures) if reported_failures else 'Результаты внешних проверок самостоятельно не перепроверялись.'})
        if (item.get('adaptation') or {}).get('archive'):
            item.setdefault('adaptation_history',[]).append(copy.deepcopy({'adaptation':item['adaptation'],
                'adapted_docs':item.get('adapted_docs',{}),'document_decisions':item.get('document_decisions',{})}))
        adapted_docs={}
        for path,content in proposals.items():
            target=self._proposal_target(path);before=base_files.get(target)
            meta={'target':target,'sha256':checksum(content),'size':len(content),
                  'before_sha256':checksum(before) if before is not None else None}
            if (before is None or is_text(target,before)) and is_text(target,content):
                meta['diff']=''.join(list(difflib.unified_diff((before or b'').decode('utf-8',errors='replace').splitlines(keepends=True),
                    content.decode('utf-8',errors='replace').splitlines(keepends=True),fromfile='Было: '+target,tofile='Стало: '+target,n=3))[:1000])
            adapted_docs[path]=meta
        item['adapted_docs'] = adapted_docs
        item['document_decisions'] = {path:'pending' for path in proposals}
        old_package=(item.get('adaptation') or {}).get('package')
        accepted_snapshot=list((item.get('adaptation') or {}).get('accepted_change_ids',[]))
        item['adaptation'] = {'status':'documents_received','received_at':timestamp(),'report':report_value,'package':old_package,
                              'checks':checks,'accepted_change_ids':accepted_snapshot,'archive':f'iterations/{iid}/adaptation-{uuid.uuid4().hex}.zip'}
        atomic(self._archive_path(item['adaptation']['archive']),archive)
        item['status'] = 'documents_review'
        self._save()
        return self.iteration(iid)

    @staticmethod
    def _proposal_target(path):
        parts = path.split('/')
        if len(parts) > 2 and parts[0] == 'proposals' and parts[1] in ('01','02','03','04'):
            return '/'.join(parts[2:])
        return '/'.join(parts[1:]) if len(parts) > 1 and parts[0] == 'proposals' else ''

    @staticmethod
    def _proposal_stages(path, report=None):
        parts=path.split('/')
        stages=set(stage_hints(IterationStore._proposal_target(path)))
        if len(parts)>2 and parts[0]=='proposals' and parts[1] in ('01','02','03','04'):stages.add(parts[1])
        docs=report.get('updated_documents',[]) if isinstance(report,dict) else []
        if isinstance(docs,list):
            for doc in docs:
                if isinstance(doc,dict) and doc.get('path')==IterationStore._proposal_target(path) and doc.get('stage') in ('01','02','03','04'):
                    stages.add(doc['stage'])
        return stages

    @synchronized
    def decide_document(self, iid, path, action):
        if action not in ('accept','reject'):
            raise MakoraError('INVALID_DECISION','Документ можно принять или отклонить.')
        item=self._iteration(iid)
        if item.get('status')=='approved': raise MakoraError('ITERATION_CLOSED','Итерация уже согласована.')
        decisions=item.get('document_decisions',{})
        if path not in decisions:
            raise MakoraError('DOCUMENT_NOT_FOUND','Документ адаптации не найден.')
        decisions[path]='accepted' if action=='accept' else 'rejected'
        item['document_decisions']=decisions
        self.index['decisions'].append({'iteration_id':iid,'document':path,'action':action,'time':timestamp()})
        self._save()
        return self.iteration(iid)

    @synchronized
    def approve(self, iid):
        item = self._iteration(iid)
        if item.get('status')=='approved': raise MakoraError('ITERATION_CLOSED','Итерация уже согласована.')
        if not item.get('result'): raise MakoraError('NO_RETURNED_PROJECT','Сначала верни ZIP проекта.')
        if item.get('stale_base') or self.current_revision()['revision_id'] != item['base_revision']:
            raise MakoraError('STALE_BASE', 'Базовая версия устарела. Адаптируйте результат к текущей версии.')
        pending = [c['path'] for c in item.get('changes',[]) if c['decision'] == 'pending']
        revising = [c['path'] for c in item.get('changes',[]) if c['decision'] == 'revision_requested']
        if pending or revising:
            raise MakoraError('CHANGES_UNRESOLVED', 'Остались нерассмотренные изменения: '+', '.join((pending+revising)[:8]))
        conflicts = self._check_choice_conflicts(item)
        if conflicts: raise MakoraError('DECISION_CONFLICT', json.dumps(conflicts,ensure_ascii=False))
        unanswered=[q['id'] for q in item.get('questions',[]) if q.get('required') and not item.get('question_answers',{}).get(q['id'])]
        if unanswered: raise MakoraError('QUESTIONS_UNANSWERED','Ответь на существенные вопросы: '+', '.join(unanswered))
        if item.get('adapted_docs') and item.get('adaptation',{}).get('status') != 'documents_received':
            raise MakoraError('ADAPTATION_REQUIRED', 'Сначала импортируйте документы адаптации.')
        if (item.get('adaptation') or {}).get('status')=='stale':
            raise MakoraError('ADAPTATION_STALE','Решения изменились. Сформируй новый пакет актуализации.')
        failed_adaptation=[check['id'] for check in (item.get('adaptation') or {}).get('checks',[]) if check['status']=='failed']
        if failed_adaptation: raise MakoraError('ADAPTATION_CHECKS_FAILED','Проверки документов не пройдены: '+', '.join(failed_adaptation))
        unresolved_adaptation=((item.get('adaptation') or {}).get('report') or {}).get('unresolved_questions',[])
        if unresolved_adaptation: raise MakoraError('ADAPTATION_QUESTIONS','В отчёте остаются открытые вопросы.')
        unresolved_docs=[p for p,decision in item.get('document_decisions',{}).items() if decision=='pending']
        if unresolved_docs:
            raise MakoraError('DOCUMENTS_UNRESOLVED','Остались документы адаптации без решения: '+', '.join(unresolved_docs[:8]))
        docs_required=any(c['decision']=='accepted' and c.get('impacted_stages') for c in item.get('changes',[]))
        if docs_required and not item.get('adapted_docs'):
            raise MakoraError('ADAPTATION_REQUIRED','Принятые изменения затрагивают документы этапов 1–4. Импортируйте результат актуализации или отклоните эти изменения.')
        base_archive = self._archive(self._revision(item['base_revision']))
        base = read_project_archive(base_archive)
        previous=self._revision(item['base_revision'])
        approved_paths=set(previous.get('approved_artifacts',[a['path'] for a in build_registry(base)['artifacts'] if a['status']=='approved']))
        returned = read_project_archive(self._archive_path(item['result']).read_bytes()) if item.get('result') else {}
        altered_mocks=[c['path'] for c in item.get('changes',[]) if c['decision']=='accepted' and c.get('mocks_changed')]
        if altered_mocks:
            raise MakoraError('ORIGINAL_MOCKS_CHANGED','Исходные mocks/ должны оставаться неизменными. Отклони изменения или верни их в new_mocks/: '+', '.join(altered_mocks[:8]))
        required_stages={stage for c in item.get('changes',[]) if c['decision']=='accepted' for stage in c.get('impacted_stages',[])}
        adaptation_report=(item.get('adaptation') or {}).get('report') or {}
        accepted_stages={stage for p,d in item.get('document_decisions',{}).items() if d=='accepted' for stage in self._proposal_stages(p,adaptation_report)}
        accepted_stages.update(stage for path in adaptation_report.get('reviewed_unchanged',[]) if isinstance(path,str) for stage in stage_hints(path))
        required_linked={edge['artifact'] for c in item.get('changes',[]) if c['decision']=='accepted' for edge in c.get('related_artifacts',[]) if edge.get('basis')=='registered' and edge['artifact'] in base}
        accepted_targets={self._proposal_target(path) for path,d in item.get('document_decisions',{}).items() if d=='accepted'}|set(adaptation_report.get('reviewed_unchanged',[]))
        if required_linked-accepted_targets:
            raise MakoraError('DOCUMENTS_UNRESOLVED','Не согласованы связанные документы: '+', '.join(sorted(required_linked-accepted_targets)))
        if required_stages-accepted_stages:
            raise MakoraError('DOCUMENTS_UNRESOLVED','Для затронутых этапов нет принятых документов: '+', '.join(sorted(required_stages-accepted_stages)))
        applied = {}
        for change in item.get('changes',[]):
            if change['decision'] != 'accepted': continue
            path=change['path']
            if change['operation'] == 'delete': base.pop(path,None);approved_paths.discard(path)
            elif change['operation'] == 'rename':
                base.pop(change['old_path'],None)
                approved_paths.discard(change['old_path'])
                if path in returned:base[path]=returned[path]
            elif path in returned: base[path]=returned[path]
            if change['operation']!='delete' and stage_hints(path) and not path.startswith('proposals/'):approved_paths.add(path)
        # Adapted documents override only explicitly delivered proposal files into their target paths.
        if (item.get('adaptation') or {}).get('archive'):
            adapted=read_project_archive(self._archive_path(item['adaptation']['archive']).read_bytes())
            for path,content in adapted.items():
                if path.startswith('proposals/'):
                    target=self._proposal_target(path)
                    if target and item.get('document_decisions',{}).get(path)=='accepted':
                        if target.startswith('mocks/') and base.get(target)!=content:
                            raise MakoraError('ORIGINAL_MOCKS_CHANGED','Изменённые данные и сценарии помести в new_mocks/, сохрани исходные mocks/.')
                        base[target]=content
                        approved_paths.add(target)
        approved_paths.update(path for path in adaptation_report.get('reviewed_unchanged',[]) if isinstance(path,str) and path in base)
        if any(c['decision']=='accepted' and c['path']=='artifact-links.json' for c in item.get('changes',[])):
            try: link_document=json.loads(base['artifact-links.json'].decode('utf-8'))
            except (KeyError,UnicodeDecodeError,json.JSONDecodeError) as exc: raise MakoraError('INVALID_LINKS','Утверждённый artifact-links.json повреждён.') from exc
            self.register_links(link_document.get('links') if isinstance(link_document,dict) else None,replace=True,persist=False)
        self.index['artifact_links']=[edge for edge in self.index.get('artifact_links',[]) if edge.get('origin')!='generated']
        registry=build_registry(base,approved_paths)
        base['artifact-registry.json']=json.dumps(registry,ensure_ascii=False,indent=2).encode('utf-8')
        self.register_links(registry['links'],persist=False)
        archive=zip_files(base)
        for rev in self.index['revisions']: rev['current']=False
        revision=self._put_revision(archive,parent=item['base_revision'],reason='iteration '+iid)
        revision['approved_artifacts']=sorted(approved_paths)
        revision['current']=True; self.index['revisions'][-1]=revision
        item['approved_revision']=revision['revision_id']; item['approved_at']=timestamp(); item['status']='approved'
        self._save()
        return self.iteration(iid)

    @synchronized
    def rollback(self, rid):
        current=self.current_revision()
        selected=self._revision(rid)
        data=self._archive(selected)
        self.index['artifact_links']=copy.deepcopy(selected.get('artifact_links',[]))
        for revision in self.index['revisions']: revision['current']=False
        new=self._put_revision(data,parent=current['revision_id'] if current else None,reason='rollback from '+rid)
        new['approved_artifacts']=copy.deepcopy(selected.get('approved_artifacts',[]))
        new['current']=True; self.index['revisions'][-1]=new
        self._save()
        return {'revision':new,'source_revision':rid,'history_preserved':True}

    @synchronized
    def iteration(self, iid):
        item=self._iteration(iid)
        result={k:v for k,v in item.items() if k not in ('package','result','adaptation_archive')}
        result['conflicts']=self._check_choice_conflicts(item)
        return result

    @synchronized
    def summary(self):
        return {'current_revision':self.current_revision(), 'revisions':self.index['revisions'],
                'iterations':[self.iteration(i['iteration_id']) for i in self.index['iterations']],
                'decisions':self.index['decisions'], 'artifact_links':self.index.get('artifact_links',[])}

    @synchronized
    def next_package(self):
        current=self.current_revision()
        if not current: raise MakoraError('NO_PROJECT', 'Сначала подготовьте первый пакет проекта.')
        return self._archive(current)

    @synchronized
    def current_documents(self, stage):
        if stage not in ('01','02','03','04'): raise MakoraError('INVALID_STAGE','Укажите этап от 01 до 04.')
        current=self.current_revision()
        if not current: raise MakoraError('NO_PROJECT','Сначала подготовьте первый пакет проекта.')
        files=read_project_archive(self._archive(current));documents=[];omitted=[];total=0
        initial=next((r for r in self.index['revisions'] if r.get('reason')=='initial'),None)
        initial_files=read_project_archive(self._archive(initial)) if initial else {}
        try:demo=json.loads(initial_files.get('context-status.json',b'{}').decode('utf-8')).get('demo') is True
        except (UnicodeDecodeError,json.JSONDecodeError,AttributeError):demo=False
        for path,data in sorted(files.items()):
            if not path.startswith(('01_','02_','03_','04_','01/','02/','03/','04/','artifacts/01/','artifacts/02/','artifacts/03/','artifacts/04/','mocks/','new_mocks/')) or stage not in stage_hints(path):continue
            if Path(path).suffix.lower() not in ('.md','.mmd','.json','.yaml','.yml','.txt','.csv'):continue
            if len(data)>TEXT_LIMIT or total+len(data)>5*1024*1024 or len(documents)>=100:
                omitted.append(path);continue
            try:text=data.decode('utf-8')
            except UnicodeDecodeError:omitted.append(path);continue
            documents.append({'path':path,'content':text,'sha256':checksum(data),
                              'is_demo':bool(demo and path in initial_files and initial_files[path]==data)})
            total+=len(data)
        return {'revision_id':current['revision_id'],'reason':current['reason'],'documents':documents,'omitted':omitted}

    @synchronized
    def compare_revisions(self, old_id, new_id):
        old=self._revision(old_id);new=self._revision(new_id)
        changes,_,_=self._diff(self._archive(old),self._archive(new))
        return {'before':old_id,'after':new_id,'changes':changes}

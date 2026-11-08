"""The project-facing workflow. Legacy artifact IDs stay stable across reordering."""
import copy
import hashlib
import json
import re
from pathlib import Path

from .preparation import Preparation, STAGES
from .agents.runtime import AgentRuntimeError

ORDER = [0, 2, 3, 5, 6, 4, 7]
LABELS = {0: 'Простое объяснение', 2: 'Поиск аналогов', 3: 'Брейншторм',
          5: 'Мок-данные', 6: 'Пакет для агента', 4: 'Планирование', 7: 'Разработка агентами'}


class ProjectWorkflow(Preparation):
    def upgrade_workflow(self):
        with self.lock:
            if self.state.get('workflowVersion', 0) >= 3:
                return
            backup = self.root / 'state-before-workflow-v3.json'
            if not backup.exists():
                backup.write_text(json.dumps(self.state, ensure_ascii=False), 'utf-8')
            has_history = bool(self.state.get('stages'))
            explanation = self.state.get('stages', {}).get('0', {})
            if explanation and 'caseConstraints' not in explanation and explanation.get('status') not in ('running', 'launching', 'unconfirmed', 'stopping'):
                explanation['status'] = 'stale'
            for key in ('3', '4'):
                record = self.state.get('stages', {}).get(key, {})
                if record and record.get('status') not in ('running', 'launching', 'unconfirmed', 'stopping'):
                    record['status'] = 'stale'
            for key, record in self.state.get('stages', {}).items():
                if int(key) in ORDER:
                    record['displayNumber'] = self.stage_number(int(key))
            self.state.update(workflowVersion=3, workflowNotice=None,
                              workflowUpdate='Новый порядок этапов. Прежние документы и чаты сохранены. Начните с простого объяснения; идею, версии и план нужно согласовать по новому формату.' if has_history else '')
            self.save()

    def snapshot(self):
        result = super().snapshot()
        result.update(workflowVersion=3, stageOrder=ORDER, stageLabels=LABELS,
                      availableStages=self.available_stages(self.state))
        return result

    def stage_spec(self, stage):
        if stage not in ORDER or stage in (6, 7):
            raise AgentRuntimeError('INVALID_STAGE', 'В новом процессе нет отдельного анализа задания.', 409)
        _, skills, files = STAGES[stage]
        if stage == 3:
            skills = ['brainstorm']
            files = ['02_user_idea.md', '02_versions_and_screens.md', '02_versions_and_screens.json']
        if stage == 4:
            skills = ['system-design', 'development-planning', 'laboratory-planning']
            files = [*files, '03_execution.json']
        if stage == 5:
            files = [*files, 'mocks/screens.json']
        return LABELS[stage], skills, files

    def stage_number(self, stage):
        return ORDER.index(stage) + 1

    @staticmethod
    def stage_complete(state, stage):
        if stage == 0:
            record = state.get('stages', {}).get('0', {})
            return record.get('status') == 'approved' and 'caseConstraints' in record
        if stage == 6:
            return (state.get('returnedProject') or {}).get('status') == 'prepared' or (state.get('prototype') or {}).get('status') == 'approved'
        return Preparation.stage_complete(state, stage)

    @staticmethod
    def available_stages(state):
        available = []
        for stage in ORDER:
            available.append(stage)
            if not ProjectWorkflow.stage_complete(state, stage):
                break
        return available

    def required_stages(self, stage, continuing=False):
        previous = ORDER[:ORDER.index(stage)]
        return [s for s in previous if not (continuing and s == 2)]

    def downstream_stages(self, stage):
        return ORDER[ORDER.index(stage) + 1:]

    def context(self, before):
        artifacts = {name: text for key in self.required_stages(before)
                if key != 6 and self.stage_complete(self.state, key)
                for name, text in self.state['stages'].get(str(key), {}).get('files', {}).items()}
        constraints = self.state['stages'].get('0', {}).get('caseConstraints', [])
        if before != 0 and constraints and self.stage_complete(self.state, 0):
            artifacts['00_case_constraints.json'] = json.dumps(constraints, ensure_ascii=False)
        return artifacts

    def start(self, stage, payload):
        self.stage_spec(stage)
        payload = dict(payload)
        if stage == 3:
            payload['userIdea'] = True
        if stage == 4:
            payload['feedback'] = (str(payload.get('feedback', '')) + '\nУчитывай возвращённый проект: ' +
                json.dumps(self.state.get('returnedProject'), ensure_ascii=False) +
                '\nПожелания пользователя к лабораториям: ' + json.dumps(self.state.get('laboratoryPreferences', []), ensure_ascii=False))
        return super().start(stage, payload)

    def result_ready(self, stage, result, record):
        if stage == 0:
            constraints = result.get('constraints', [])
            if not isinstance(constraints, list):
                raise ValueError('constraints должен быть списком цитат ограничений из кейса.')
            for item in constraints:
                if not isinstance(item, dict) or not isinstance(item.get('quote'), str) or not item['quote'].strip() or item['quote'] not in self.state['brief']:
                    raise ValueError('Каждое ограничение должно быть точной цитатой исходного кейса.')
            record['caseConstraints'] = constraints
        if stage == 3:
            history = self.runtime.provider.history(record['threadId'])
            finished = record.get('brainstormReadyObserved', False)
            confirmed = False
            for turn in history.get('turns', []):
                for item in turn.get('items', []):
                    if item.get('role') != 'user':
                        continue
                    text = str(item.get('text', '')).strip().lower()
                    if 'task.json' in text:
                        continue
                    confirmed = False
                    if finished and re.search(r'^(да\b|подтверждаю\b|утверждаю\b|согласен\b|согласна\b)', text) and not re.search(r'\b(но|добавь|измени|поправь|не)\b', text):
                        confirmed = True
                    if re.search(r'\bготово\b|идеи закончились|закончил.*идеи', text):
                        finished = True
            record['brainstormReadyObserved'] = finished
            if not confirmed or result.get('userConfirmed') is not True:
                record['brainstormPhase'] = 'reviewing_versions' if finished else 'collecting_ideas'
                return False
            record['brainstormConfirmed'] = True
        return True

    def validate(self, files, stage):
        checks = Preparation.validate(files, stage)
        required = self.stage_spec(stage)[2]
        checks = [c for c in checks if c['name'] not in STAGES[stage][2] or c['name'] in required]
        checks += [{'name': name, 'status': 'passed' if isinstance(files.get(name), str) and files[name].strip() else 'failed'}
                   for name in required if name not in STAGES[stage][2]]
        if stage == 0 and re.search(r'^#+\s+.*ограничен', files.get('00_brief_explanation.md', ''), re.I | re.M):
            raise ValueError('Ограничения передаются отдельными точными цитатами в constraints, а не придумываются в пояснении.')
        if stage == 3 and files.get('02_versions_and_screens.json'):
            self.validate_versions(json.loads(files['02_versions_and_screens.json']))
        if stage == 4 and files.get('03_execution.json'):
            from .laboratories import validate_execution
            data = json.loads(files['03_tasks.json'])
            validate_execution(data.get('tasks', []) if isinstance(data, dict) else data,
                               json.loads(files['03_execution.json']), self.context(4))
        if stage == 5 and files.get('mocks/screens.json'):
            versions = json.loads(self.context(5)['02_versions_and_screens.json'])['versions']
            expected = {(v['id'], s['id']) for v in versions for s in v['screens']}
            entries = json.loads(files['mocks/screens.json']).get('screens', [])
            found = set()
            for item in entries:
                pair = (item.get('versionId'), item.get('screenId'))
                if pair in found or pair not in expected or not isinstance(item.get('fixtures'), list):
                    raise ValueError('Моки экранов должны однозначно соответствовать согласованным версиям и экранам.')
                found.add(pair)
                if not item['fixtures'] and not item.get('reason'):
                    raise ValueError('Для статического экрана без моков укажите причину.')
                if any(name not in files or not name.startswith('mocks/fixtures/') for name in item['fixtures']):
                    raise ValueError('Фикстура экрана отсутствует в пакете моков.')
            if found != expected:
                raise ValueError('Моки должны покрывать каждый экран каждой согласованной версии.')
        return checks

    @staticmethod
    def validate_versions(data):
        versions = data.get('versions', []) if isinstance(data, dict) else []
        if not versions or not isinstance(versions, list):
            raise ValueError('Укажите версии продукта с экранами.')
        ids = set()
        for version in versions:
            if not isinstance(version, dict) or not version.get('id') or version['id'] in ids or not version.get('goal'):
                raise ValueError('У версии нужны уникальный id и цель.')
            ids.add(version['id'])
            screens = version.get('screens', [])
            if not isinstance(screens, list) or not screens:
                raise ValueError('Для каждой версии укажите все экраны, включая сохраняющиеся из прошлых версий.')
            screen_ids = set()
            for screen in screens:
                if not isinstance(screen, dict) or not all(screen.get(k) for k in ('id', 'title', 'content')) or screen['id'] in screen_ids:
                    raise ValueError('Экрану нужны уникальный id, название и содержимое.')
                screen_ids.add(screen['id'])
            for screen in screens:
                if not isinstance(screen.get('next', []), list) or any(s not in screen_ids for s in screen.get('next', [])):
                    raise ValueError('Переходы экрана должны ссылаться на экраны той же версии.')
            if version.get('entryScreen') not in screen_ids:
                raise ValueError('Укажите начальный экран каждой версии.')

    def validate_evidence(self, files, stage, result, *, brief=None, context=None):
        if stage == 2:
            return super().validate_evidence(files, stage, result, brief=brief, context=context)
        return [], {}

    def approve(self, stage, payload=None):
        record = self.state['stages'].get(str(stage), {})
        if stage == 0 and 'caseConstraints' not in record:
            raise AgentRuntimeError('EXPLANATION_UPDATE_REQUIRED', 'Пересоздайте пояснение: новый формат проверяет ограничения по цитатам кейса.', 409)
        if stage == 3 and not record.get('brainstormConfirmed'):
            raise AgentRuntimeError('BRAINSTORM_CONFIRMATION_REQUIRED', 'Сначала подтвердите версии и экраны в чате Codex.', 409)
        return super().approve(stage, payload)

    def save_execution(self, payload):
        from .laboratories import validate_execution
        with self.lock:
            record = self.state['stages'].get('4', {})
            if record.get('status') not in ('review', 'approved'):
                raise AgentRuntimeError('PLAN_NOT_READY', 'Сначала создайте план.', 409)
            if any(r.get('projectRoot') == str(self.project_directory()) for r in self.runtime.state.get('runs', {}).values()):
                raise AgentRuntimeError('PLAN_ALREADY_RUNNING', 'После запуска агентов создайте новую редакцию плана через уточнение.', 409)
            tasks, execution = payload.get('tasks'), payload.get('execution')
            validate_execution(tasks, execution, self.context(4))
            files = {**record['files'], '03_tasks.json': json.dumps({'tasks': tasks}, ensure_ascii=False, indent=2),
                     '03_execution.json': json.dumps(execution, ensure_ascii=False, indent=2)}
            checks = self.validate(files, 4)
            if any(c['status'] != 'passed' for c in checks):
                raise AgentRuntimeError('PLAN_INVALID', 'В плане остались ошибки.', 409)
            self.state.setdefault('executionHistory', []).append(copy.deepcopy(record['files']))
            self.state['executionHistory'] = self.state['executionHistory'][-20:]
            record.update(files=files, checks=checks, status='review')
            for name in ('03_tasks.json', '03_execution.json'):
                if self.state.get('storageRoot'):
                    self._storage_write('artifacts/' + name, files[name].encode('utf-8'))
            self.save()
            return self.snapshot()

    def laboratory_preferences(self, payload):
        value = payload.get('laboratories', [])
        if not isinstance(value, list) or any(not isinstance(v, str) or len(v) > 2000 for v in value):
            raise ValueError('Передайте список пожеланий к лабораториям.')
        with self.lock:
            self.state['laboratoryPreferences'] = value
            self.save()
            return self.snapshot()

    def development(self, stage=7):
        if stage != 7 or 7 not in self.available_stages(self.state):
            raise AgentRuntimeError('PLAN_REQUIRED', 'Сначала утвердите план запуска агентов.', 409)
        project = super().development(stage)
        project['approvedExecution'] = json.loads(self.state['stages']['4']['files']['03_execution.json'])
        project['approvedTasks'] = json.loads(self.state['stages']['4']['files']['03_tasks.json'])
        graph_digest = hashlib.sha256(json.dumps([project['approvedTasks'], project['approvedExecution']], sort_keys=True).encode()).hexdigest()
        run_id = self.state.get('approvedDevelopmentRun')
        if not run_id or run_id not in self.runtime.state['runs'] or self.state.get('approvedDevelopmentGraphDigest') != graph_digest:
            tasks = project['approvedTasks']
            run = self.runtime.create_run({'projectRoot': project['projectRoot'],
                'tasks': tasks.get('tasks', []) if isinstance(tasks, dict) else tasks,
                'execution': project['approvedExecution']})
            self.state['approvedDevelopmentRun'] = run['id']
            self.state['approvedDevelopmentGraphDigest'] = graph_digest
            self.save()
            run_id = run['id']
        project['approvedRunId'] = run_id
        return project

    def development_context(self):
        return self.context(7)

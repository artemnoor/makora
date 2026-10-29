import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from makora_core.iterations import IterationStore, read_archive, validate_document_links
from makora_core.workspace import MakoraError


def archive(files):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items(): z.writestr(name,content)
    return out.getvalue()


class IterationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=IterationStore(self.root)
        self.base=archive({'PROMPT.md':'Build app','src/app.js':'v1',
                           'mocks/fixtures/places.json':'[]',
                           '02_user_flow.mmd':'flow v1','03_contracts/openapi.yaml':'openapi v1'})
        self.store.prepare(self.base)
        self.rev1=self.store.current_revision()['revision_id']
        self.iid=self.store.index['iterations'][0]['iteration_id']

    def returned(self, files, base_revision=None):
        payload=dict(files)
        if base_revision:
            payload['changeset.json']=json.dumps({'base_revision':base_revision,'changes':[
                {'id':'map-ui','operation':'modify','path':'src/app.js','reason':'Добавлена интерактивная карта'},
                {'id':'flow','operation':'modify','path':'02_user_flow.mmd','reason':'Добавлен шаг открытия карты'},
                {'id':'api','operation':'modify','path':'03_contracts/openapi.yaml','reason':'Добавлен эндпоинт карты','requires':['flow']}
            ]})
        return archive(payload)

    def decide_all(self, iid, value='accept'):
        for change in list(self.store.iteration(iid)['changes']):
            if change['decision']=='pending': self.store.decide(iid,change['id'],value)
        questions=self.store.iteration(iid)['questions']
        if questions:
            self.store.answer_questions(iid,{q['id']:'Проверено для тестового сценария' for q in questions if q.get('required')})

    def test_create_v1_no_changes_and_persistent_history(self):
        result=self.store.return_project(self.iid,self.base)
        self.assertEqual(result['status'],'no_changes')
        self.assertEqual(result['changes'],[])
        restored=IterationStore(self.root)
        self.assertEqual(restored.current_revision()['revision_id'],self.rev1)
        self.assertEqual(restored.iteration(self.iid)['status'],'no_changes')

    def test_diff_flow_api_mocks_report_and_changeset(self):
        result=self.store.return_project(self.iid,self.returned({
            'PROMPT.md':'Build app','src/app.js':'v2','mocks/fixtures/places.json':'[1]',
            'new_mocks/fixtures/places.json':'[2]','02_user_flow.mmd':'flow v2',
            '03_contracts/openapi.yaml':'openapi v2','prototype-report.json':'{}'},self.rev1))
        by_path={c['path']:c for c in result['changes']}
        self.assertEqual(by_path['02_user_flow.mmd']['impacted_stages'],['02'])
        self.assertEqual(by_path['03_contracts/openapi.yaml']['impacted_stages'],['03'])
        self.assertTrue(by_path['mocks/fixtures/places.json']['mocks_changed'])
        self.assertEqual(by_path['mocks/fixtures/places.json']['decision'],'pending')
        self.assertEqual(by_path['changeset.json']['decision'],'informational')
        self.assertTrue(result['changeset']['valid'])
        self.assertEqual(result['changeset']['undeclared'],['mocks/fixtures/places.json','new_mocks/fixtures/places.json','prototype-report.json'])
        self.assertTrue(any(q['id']=='q-mocks-source' for q in result['questions']))
        self.assertTrue(any(c['id']=='external_code' and c['status']=='not_checked' for c in result['checks']))

    def test_changes_without_changeset_are_accepted_for_review_and_marked_undeclared(self):
        result=self.store.return_project(self.iid,archive({'PROMPT.md':'Build app','src/app.js':'new',
            'mocks/fixtures/places.json':'[]','02_user_flow.mmd':'flow v1','03_contracts/openapi.yaml':'openapi v1'}))
        self.assertFalse(result['changeset']['present'])
        self.assertEqual(set(result['changeset']['undeclared']),{'src/app.js'})
        self.assertTrue(any(q['id']=='q-unexplained' for q in result['questions']))

    def test_declared_missing_change_is_reported(self):
        bad=archive({'src/app.js':'v2','changeset.json':json.dumps({'base_revision':self.rev1,'changes':[
            {'id':'missing','operation':'modify','path':'src/not-here.js','reason':'Not present'}]})})
        result=self.store.return_project(self.iid,bad)
        self.assertIn('src/not-here.js',result['changeset']['declared_missing'])
        self.assertFalse(result['changeset']['valid'])

    def test_malformed_external_json_is_reported_without_crashing(self):
        returned=read_archive(self.base);returned['src/app.js']=b'v2'
        returned['changeset.json']=json.dumps({'base_revision':self.rev1,'changes':[
            {'id':'C1','operation':'modify','path':'src/app.js','reason':'Example','requires':[{'unexpected':'object'}]}]})
        returned['prototype-report.json']=json.dumps({'features':[],'checks':[{'id':'T1','status':{},'command':'','result':''}],
                                                        'run_commands':[],'known_limitations':[],'contradictions':[]})
        result=self.store.return_project(self.iid,archive(returned))
        self.assertFalse(result['changeset']['valid'])
        self.assertEqual(result['prototype_report']['status'],'failed')
        change=next(c for c in result['changes'] if c['path']=='src/app.js')
        self.store.decide(self.iid,change['id'],'accept')
        self.assertEqual(self.store.iteration(self.iid)['conflicts'],[])

    def test_registered_links_trace_direct_and_indirect_impacts(self):
        self.store.register_links([
            {'from':'02_user_flow.mmd','to':'03_contracts/openapi.yaml'},
            {'from':'03_contracts/openapi.yaml','to':'mocks/fixtures/places.json'},
            {'from':'unrelated.md','to':'unrelated-test.md'}])
        files=read_archive(self.base);files['02_user_flow.mmd']=b'flow v2'
        result=self.store.return_project(self.iid,archive(files))
        change=next(c for c in result['changes'] if c['path']=='02_user_flow.mmd')
        self.assertEqual(change['impacted_stages'],['02','03','04'])
        self.assertEqual([(x['artifact'],x['distance']) for x in change['related_artifacts']],
                         [('03_contracts/openapi.yaml',1),('mocks/fixtures/places.json',2)])
        self.assertNotIn('unrelated-test.md',{x['artifact'] for x in result['impacted_artifacts']})

    def test_repeated_return_preserves_prior_archive_and_decisions(self):
        first=read_archive(self.base);first['build/a.js']=b'first'
        result=self.store.return_project(self.iid,archive(first))
        change=next(c for c in result['changes'] if c['path']=='build/a.js')
        self.store.decide(self.iid,change['id'],'reject','Первый вариант')
        old_path=self.store._iteration(self.iid)['result']
        second=read_archive(self.base);second['build/a.js']=b'second'
        current=self.store.return_project(self.iid,archive(second))
        self.assertEqual(len(current['return_history']),1)
        self.assertEqual(current['return_history'][0]['changes'][0]['decision'],'rejected')
        self.assertEqual(read_archive(self.store._archive_path(old_path).read_bytes())['build/a.js'],b'first')
        self.assertNotEqual(old_path,self.store._iteration(self.iid)['result'])
        self.assertEqual(current['changes'][0]['decision'],'pending')

    def test_changed_decisions_invalidate_adaptation_package(self):
        returned=read_archive(self.base);returned['src/app.js']=b'new'
        result=self.store.return_project(self.iid,archive(returned))
        change=result['changes'][0]
        self.store.decide(self.iid,change['id'],'accept')
        self.store.answer_questions(self.iid,{q['id']:'Проверено' for q in result['questions']})
        self.store.adaptation_package(self.iid)
        self.store.decide(self.iid,change['id'],'reject')
        with self.assertRaises(MakoraError) as cm:
            self.store.import_adaptation(self.iid,archive({'proposals/03/test.md':'# test'}))
        self.assertEqual(cm.exception.code,'ADAPTATION_STALE')

    def test_contract_and_task_dependency_validation(self):
        self.assertTrue(validate_document_links('03_contracts/openapi.yaml',{'openapi':'3.1.0'}))
        self.assertFalse(validate_document_links('03_contracts/openapi.yaml',{'openapi':'3.1.0','info':{'title':'x','version':'1'},'paths':{}}))
        cyclic={'tasks':[{'id':'A','dependsOn':['B']},{'id':'B','dependsOn':['A']}]}
        missing={'tasks':[{'id':'A','dependsOn':['missing']}]}
        self.assertTrue(any('цикл' in error for error in validate_document_links('03_tasks.json',cyclic)))
        self.assertTrue(any('отсутствует' in error for error in validate_document_links('03_tasks.json',missing)))

    def test_registered_impacts_must_be_updated_or_explicitly_reviewed(self):
        self.store.register_links([{'from':'src/app.js','to':'03_contracts/openapi.yaml'}])
        returned=read_archive(self.base);returned['src/app.js']=b'new'
        result=self.store.return_project(self.iid,archive(returned))
        self.store.decide(self.iid,result['changes'][0]['id'],'accept')
        self.store.answer_questions(self.iid,{q['id']:'Изменение проверено' for q in result['questions']})
        self.store.adaptation_package(self.iid)
        report={'iteration_id':self.iid,'base_revision':self.rev1,
                'updated_documents':[{'path':'03_architecture.md','change_reason':'Изменился код','related_ids':[]}],
                'checks':[{'id':'review','status':'not_run','detail':'Требуется проверка'}],
                'unresolved_questions':[],'assumptions':[],'known_limitations':[]}
        def adapted(): return archive({'proposals/03/03_architecture.md':'# Архитектура\n',
                                       'adaptation-report.json':json.dumps(report,ensure_ascii=False)})
        initial=self.store.import_adaptation(self.iid,adapted())
        self.assertEqual(next(c['status'] for c in initial['adaptation']['checks'] if c['id']=='linked_artifacts'),'failed')
        report['reviewed_unchanged']=['03_contracts/openapi.yaml']
        reviewed=self.store.import_adaptation(self.iid,adapted())
        self.assertEqual(next(c['status'] for c in reviewed['adaptation']['checks'] if c['id']=='linked_artifacts'),'passed')
        for path in reviewed['adapted_docs']:self.store.decide_document(self.iid,path,'accept')
        self.assertEqual(self.store.approve(self.iid)['status'],'approved')

    def test_sent_package_contains_revision_metadata_and_matches_baseline(self):
        item=self.store._iteration(self.iid)
        sent=read_archive(self.store._archive_path(item['package']).read_bytes())
        metadata=json.loads(sent['iteration-context.json'])
        self.assertEqual(metadata['base_revision'],self.rev1)
        self.assertEqual(metadata['base_checksum'],self.store.current_revision()['sha256'])
        self.assertEqual(self.store.return_project(self.iid,archive(sent))['changes'],[])

    def test_project_in_single_top_level_folder_is_compared_by_content(self):
        sent=read_archive(self.store._archive_path(self.store._iteration(self.iid)['package']).read_bytes())
        wrapped={'returned-project/'+path:data for path,data in sent.items()}
        wrapped['returned-project/src/app.js']=b'v2'
        result=self.store.return_project(self.iid,archive(wrapped))
        self.assertEqual([c['path'] for c in result['changes']],['src/app.js'])
        self.assertEqual(result['changes'][0]['operation'],'modify')

    def test_decision_conflict_prevents_adaptation(self):
        data=self.returned({'PROMPT.md':'Build app','src/app.js':'v2','02_user_flow.mmd':'flow v2',
                            '03_contracts/openapi.yaml':'openapi v2'},self.rev1)
        result=self.store.return_project(self.iid,data)
        by_path={c['path']:c for c in result['changes']}
        self.store.decide(self.iid,by_path['03_contracts/openapi.yaml']['id'],'accept')
        self.store.decide(self.iid,by_path['02_user_flow.mmd']['id'],'reject')
        with self.assertRaises(MakoraError) as cm: self.store.adaptation_package(self.iid)
        self.assertEqual(cm.exception.code,'DECISION_CONFLICT')

    def test_selective_decision_adaptation_approval_and_v2(self):
        returned=self.returned({'PROMPT.md':'Build app','src/app.js':'v2','mocks/fixtures/places.json':'[]','02_user_flow.mmd':'flow map',
                                '03_contracts/openapi.yaml':'map contract'},self.rev1)
        first=self.store.return_project(self.iid,returned)
        for change in first['changes']:
            if change['path']!='changeset.json': self.store.decide(self.iid,change['id'],'accept')
        adaptation=self.store.adaptation_package(self.iid)
        packaged=read_archive(adaptation)
        self.assertIn('base/02_user_flow.mmd',packaged)
        self.assertIn('ADAPTATION_PROMPT.md',packaged)
        adaptation_return=archive({'proposals/02/02_user_flow.mmd':'updated flow',
                                   'proposals/03/03_contracts/openapi.yaml':'openapi: 3.1.1\ninfo: {title: Demo, version: 1.0.0}\npaths: {}\n',
                                   'adaptation-report.json':json.dumps({'iteration_id':self.iid,'base_revision':self.rev1,
                                     'updated_documents':[{'path':'02_user_flow.mmd','change_reason':'Карта','related_ids':[]},
                                                          {'path':'03_contracts/openapi.yaml','change_reason':'Новая карта API','related_ids':[]}],
                                     'checks':[{'id':'docs','status':'passed','detail':'JSON/YAML parsed'}],
                                     'unresolved_questions':[],'assumptions':[],'known_limitations':[]})})
        docs=self.store.import_adaptation(self.iid,adaptation_return)
        self.assertEqual(docs['status'],'documents_review')
        self.assertFalse(any(check['status']=='failed' for check in docs['adaptation']['checks']))
        questions=self.store.iteration(self.iid)['questions']
        if questions: self.store.answer_questions(self.iid,{q['id']:'Изменения проверены' for q in questions if q.get('required')})
        with self.assertRaises(MakoraError) as cm: self.store.approve(self.iid)
        self.assertEqual(cm.exception.code,'DOCUMENTS_UNRESOLVED')
        for path in docs['adapted_docs']:
            self.store.decide_document(self.iid,path,'accept')
        approved=self.store.approve(self.iid)
        self.assertEqual(approved['status'],'approved')
        self.assertNotEqual(approved['approved_revision'],self.rev1)
        self.assertEqual(self.store.current_revision()['revision_id'],approved['approved_revision'])
        project=read_archive(self.store.next_package())
        self.assertEqual(project['src/app.js'],b'v2')
        self.assertEqual(project['02_user_flow.mmd'],b'updated flow')
        documents=self.store.current_documents('02')
        self.assertEqual(next(d['content'] for d in documents['documents'] if d['path']=='02_user_flow.mmd'),'updated flow')

    def test_second_iteration_carries_existing_project_and_current_context(self):
        first=self.store.return_project(self.iid,archive({'PROMPT.md':'Build app','src/app.js':'v1',
            'mocks/fixtures/places.json':'[]','02_user_flow.mmd':'flow v1','03_contracts/openapi.yaml':'openapi v1',
            'build/main.js':'v2'}))
        self.decide_all(self.iid)
        self.store.approve(self.iid)
        context=archive({'PROMPT.md':'Continue this app','02_solution.md':'new approved context'})
        self.store.prepare(context)
        item=self.store.index['iterations'][-1]
        package=read_archive(self.store._archive_path(item['package']).read_bytes())
        self.assertEqual(package['src/app.js'],b'v1')
        self.assertEqual(package['build/main.js'],b'v2')
        self.assertEqual(package['makora-context/02_solution.md'],b'new approved context')
        self.assertIn('Не пересоздавай проект'.encode(),package['PROMPT.md'])

    def test_outdated_return_is_held_and_cannot_approve(self):
        stale_id=self.iid
        second=self.store.prepare(self.base)['iterations'][-1]['iteration_id']
        result=self.store.return_project(second,archive({'PROMPT.md':'Build app','src/app.js':'v1',
            'mocks/fixtures/places.json':'[]','02_user_flow.mmd':'flow v1','03_contracts/openapi.yaml':'openapi v1',
            'build/main.js':'v2'}))
        self.decide_all(second)
        self.store.approve(second)
        result=self.store.return_project(stale_id,archive({'PROMPT.md':'Build app','src/other.js':'late'}))
        self.assertTrue(result['stale_base'])
        with self.assertRaises(MakoraError) as cm: self.store.approve(stale_id)
        self.assertEqual(cm.exception.code,'STALE_BASE')

    def test_rollback_creates_new_revision_without_deleting_history(self):
        result=self.store.return_project(self.iid,archive({'PROMPT.md':'Build app','src/app.js':'v1',
            'mocks/fixtures/places.json':'[]','02_user_flow.mmd':'flow v1','03_contracts/openapi.yaml':'openapi v1',
            'build/main.js':'v2'}))
        self.decide_all(self.iid); self.store.approve(self.iid)
        current=self.store.current_revision()['revision_id']
        before=len(self.store.index['revisions'])
        rollback=self.store.rollback(self.rev1)
        self.assertEqual(len(self.store.index['revisions']),before+1)
        self.assertEqual(rollback['source_revision'],self.rev1)
        self.assertEqual(rollback['revision']['parent_revision'],current)
        rolled_project=read_archive(self.store.next_package())
        self.assertEqual(rolled_project['src/app.js'],b'v1')
        self.assertNotIn('build/main.js',rolled_project)

    def test_duplicate_and_slip_paths_are_rejected(self):
        for name in ('../escape.txt','/absolute.txt','C:/outside.txt','x//y.txt'):
            with self.subTest(name=name):
                with self.assertRaises(MakoraError): read_archive(archive({name:'x'}))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('same.txt','one');z.writestr('same.txt','two')
        with self.assertRaises(MakoraError): read_archive(out.getvalue())

    def test_symbolic_link_rejected(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            info=zipfile.ZipInfo('link')
            info.create_system=3
            info.external_attr=(0o120777<<16)
            z.writestr(info,'target')
        with self.assertRaises(MakoraError) as cm: read_archive(out.getvalue())
        self.assertEqual(cm.exception.code,'SYMLINK_IN_ARCHIVE')

    def test_accessible_city_map_v1_to_v2_and_repeat_handoff(self):
        case_root=Path(__file__).resolve().parents[1]/'dist'/'prototype-example'
        manifest=json.loads((case_root/'manifest.json').read_text(encoding='utf-8'))
        initial={name:(case_root/name).read_bytes() for name in manifest['files']}
        initial['changeset.schema.json']=(case_root.parent/'changeset.schema.json').read_bytes()
        store=IterationStore(self.root/'accessible-city')
        store.prepare(archive(initial))
        v1=store.current_revision()['revision_id']
        first_id=store.index['iterations'][0]['iteration_id']
        returned=dict(initial)
        returned.update({
            'src/map.js':'export function showMap() {}',
            'new_mocks/fixtures/map_places.json':'[{"id":"place-001","lat":55.75,"lon":37.61}]',
            'proposals/02/02_user_flow.mmd':'flowchart TD\n A[Каталог]-->B[Карта]\n',
            'proposals/03/data-model.md':'# Координаты учреждений\n',
            'proposals/03/03_contracts/openapi.yaml':'openapi: 3.1.1\ninfo: {title: Accessible City, version: 1.1.0}\npaths: {}\n',
            'proposals/03/03_test_plan.md':'# Проверки карты\n',
            'proposals/04/04_mock_data.md':'# Синтетические координаты\n',
            'proposals/04/new_mocks/scenarios.json':'[{"id":"map-visible","fixture":"fixtures/map_places.json"}]'
        })
        proposal_changes=[
            ('MAP-UI','add','src/map.js','Показать учреждения на интерактивной карте',[]),
            ('MAP-FLOW','add','proposals/02/02_user_flow.mmd','Добавить переход каталога к карте',[]),
            ('MAP-DATA','add','proposals/03/data-model.md','Добавить координаты учреждения',[]),
            ('MAP-API','add','proposals/03/03_contracts/openapi.yaml','Передавать координаты через API',['MAP-FLOW']),
            ('MAP-TEST','add','proposals/03/03_test_plan.md','Проверять отображение координат',['MAP-API']),
            ('MAP-MOCK','add','new_mocks/fixtures/map_places.json','Добавить отдельный синтетический набор координат',[]),
            ('MAP-SCENARIO','add','proposals/04/new_mocks/scenarios.json','Добавить сценарий данных для карты',['MAP-MOCK'])
        ]
        returned['changeset.json']=json.dumps({'base_revision':v1,'changes':[{'id':i,'operation':op,'path':path,'reason':reason,'requires':requires} for i,op,path,reason,requires in proposal_changes]},ensure_ascii=False).encode()
        returned['prototype-report.json']=json.dumps({'features':['Интерактивная карта'],'checks':[{'id':'map-ui','status':'not_run','command':'','result':'Код не запускался в Макоре.'}], 'run_commands':['npm run dev'],'known_limitations':['Проверки заявлены внешним ИИ.'],'contradictions':[]},ensure_ascii=False).encode()
        review=store.return_project(first_id,archive(returned))
        paths={change['path']:change for change in review['changes']}
        self.assertIn('src/map.js',paths)
        self.assertIn('proposals/02/02_user_flow.mmd',paths)
        self.assertIn('new_mocks/fixtures/map_places.json',paths)
        self.assertEqual(paths['new_mocks/fixtures/map_places.json']['impacted_stages'],['04'])
        self.assertEqual(review['prototype_report']['status'],'parsed')
        self.assertEqual(review['prototype_report']['checks'][0]['status'],'not_run')
        for change in review['changes']:
            if change['decision']=='pending': store.decide(first_id,change['id'],'accept')
        if review['questions']:
            store.answer_questions(first_id,{question['id']:'Принять карту и новые синтетические данные; исходные моки оставить.' for question in review['questions']})
        adaptation=read_archive(store.adaptation_package(first_id))
        self.assertIn('accepted/src/map.js',adaptation)
        self.assertIn('base/02_user_flow.mmd',adaptation)
        doc_files={
            'proposals/02/02_user_flow.mmd':'flowchart TD\n A[Каталог]-->B[Карта]\n',
            'proposals/03/data-model.md':'# Модель координат\n',
            'proposals/03/03_contracts/openapi.yaml':'openapi: 3.1.1\ninfo: {title: Accessible City, version: 1.1.0}\npaths: {}\n',
            'proposals/03/03_test_plan.md':'# Проверка карты\n',
            'proposals/04/04_mock_data.md':'# Данные карты\n',
            'proposals/04/new_mocks/scenarios.json':'[{"id":"map-visible","fixture":"fixtures/map_places.json"}]'
        }
        report={'iteration_id':first_id,'base_revision':v1,
                'updated_documents':[{'path':store._proposal_target(path),'change_reason':'Согласована карта и координаты','related_ids':['MAP-UI']} for path in doc_files],
                'checks':[{'id':'json-yaml-parse','status':'passed','detail':'Документы синтаксически прочитаны.'},
                          {'id':'browser-map','status':'not_run','detail':'Не запускался в изоляции.'}],
                'unresolved_questions':[],'assumptions':['Координаты синтетические.'],'known_limitations':['Смысловую совместимость API не проверяли.']}
        doc_files['adaptation-report.json']=json.dumps(report,ensure_ascii=False).encode()
        docs=store.import_adaptation(first_id,archive(doc_files))
        self.assertFalse(any(check['status']=='failed' for check in docs['adaptation']['checks']))
        for path in docs['adapted_docs']:store.decide_document(first_id,path,'accept')
        approved=store.approve(first_id)
        self.assertEqual(approved['status'],'approved')
        self.assertEqual(store.current_revision()['parent_revision'],v1)
        v2=read_archive(store.next_package())
        self.assertIn('src/map.js',v2)
        self.assertIn('new_mocks/fixtures/map_places.json',v2)
        self.assertEqual(v2['mocks/fixtures/places.json'],initial['mocks/fixtures/places.json'])
        self.assertIn('Карта'.encode(),v2['02_user_flow.mmd'])
        store.prepare(store.next_package())
        next_iteration=store.index['iterations'][-1]
        next_zip=read_archive(store._archive_path(next_iteration['package']).read_bytes())
        self.assertIn('src/map.js',next_zip)
        self.assertIn('makora-context/02_user_flow.mmd',next_zip)
        self.assertIn('Не пересоздавай проект'.encode(),next_zip['PROMPT.md'])

    def test_code_is_not_executed_during_import(self):
        result=self.store.return_project(self.iid,archive({'PROMPT.md':'Build app','src/postinstall.py':'raise RuntimeError()'}))
        self.assertEqual(result['status'],'review')
        self.assertTrue(any(c['id']=='external_code' and c['status']=='not_checked' for c in result['checks']))


if __name__=='__main__': unittest.main()

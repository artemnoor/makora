"""Build a traceable registry from project artifacts without interpreting prose as fact."""
import hashlib
import json
import re
from pathlib import PurePosixPath

ID_PATTERN=re.compile(r'\b(?:REQ|FEATURE|FEAT|TASK|TEST|TC|F)-\d+\b|\bT\d{2,}\b',re.IGNORECASE)


def build_registry(files, approved_paths=None):
    artifacts=[]; mentions={}; links=[]; seen=set()
    if approved_paths is None:
        try:status=json.loads(files.get('context-status.json',b'{}').decode('utf-8'))
        except (ValueError,UnicodeDecodeError):status={}
        if not isinstance(status,dict):status={}
        approved_paths=set()
        for path in files:
            prefix=path.lower()
            if ((prefix.startswith(('01_','01/','artifacts/01/')) and status.get('analysisApproved') is True)
                or (prefix.startswith(('02_','02/','artifacts/02/')) and status.get('ideaApproved') is True)
                or (prefix.startswith(('03_','03/','artifacts/03/')) and status.get('planReady') is True)
                or (prefix.startswith(('04_','04/','artifacts/04/','mocks/','new_mocks/')) and status.get('mocksApproved') is True)):
                approved_paths.add(path)
    else:approved_paths=set(approved_paths)
    def link(source,target,kind,evidence,confidence='confirmed'):
        if confidence=='confirmed' and evidence.split('#',1)[0] not in approved_paths:confidence='inferred'
        key=(source,target,kind,confidence)
        if source==target or key in seen:return
        seen.add(key);links.append({'from':source,'to':target,'kind':kind,'confidence':confidence,'evidence':evidence,'origin':'generated'})
    for path,data in sorted(files.items()):
        if not path.startswith(('01_','02_','03_','04_','01/','02/','03/','04/','artifacts/01/','artifacts/02/','artifacts/03/','artifacts/04/','mocks/','new_mocks/')):continue
        if len(data)>1024*1024:continue
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:continue
        ids=sorted({m.group().upper() for m in ID_PATTERN.finditer(text)})
        artifacts.append({'path':path,'sha256':hashlib.sha256(data).hexdigest(),'ids':ids,
                          'status':'approved' if path in approved_paths else 'unconfirmed'})
        for ident in ids:
            mentions.setdefault(ident,[]).append(path)
            link(ident,path,'mentioned_in',path,'inferred')
        for line_no,line in enumerate(text.splitlines(),1):
            if '|' not in line:continue
            row={m.group().upper() for m in ID_PATTERN.finditer(line)}
            req=[x for x in row if x.startswith('REQ-')];feat=[x for x in row if x.startswith(('F-','FEAT-','FEATURE-'))]
            task=[x for x in row if re.fullmatch(r'T\d+|TASK-\d+',x)]
            tests=[x for x in row if x.startswith(('TC-','TEST-'))]
            for left,right in ((req,feat),(req,task),(feat,task),(task,tests),(req,tests)):
                for a in left:
                    for b in right:link(a,b,'table_reference',f'{path}:{line_no}','inferred')
        if PurePosixPath(path).suffix.lower()!='.json':continue
        try:value=json.loads(text)
        except ValueError:continue
        tasks=value.get('tasks',[]) if isinstance(value,dict) else []
        if isinstance(tasks,list):
            for task in tasks:
                if not isinstance(task,dict) or not isinstance(task.get('id'),str):continue
                ident=task['id'].upper();evidence=path+'#'+ident
                link(path,ident,'defines_task',evidence)
                for field in ('requirements','requirement_ids','features','feature_ids'):
                    for source in task.get(field,[]) if isinstance(task.get(field,[]),list) else []:
                        if isinstance(source,str):link(source.upper(),ident,field,evidence)
                for field in ('tests','test_ids'):
                    for target in task.get(field,[]) if isinstance(task.get(field,[]),list) else []:
                        if isinstance(target,str):link(ident,target.upper(),field,evidence)
                for field in ('contracts','contract_paths'):
                    for source in task.get(field,[]) if isinstance(task.get(field,[]),list) else []:
                        if isinstance(source,str) and source in files:link(source,ident,field,evidence)
                for field in ('architecture',):
                    source=task.get(field)
                    if isinstance(source,str) and source in files:link(source,ident,field,evidence)
                for field in ('testPlan','test_plan'):
                    target=task.get(field)
                    if isinstance(target,str) and target in files:link(ident,target,field,evidence)
                for target in task.get('fixtures',[]) if isinstance(task.get('fixtures',[]),list) else []:
                    if isinstance(target,str) and target in files:link(ident,target,'task_fixture',evidence)
                for source in task.get('dependsOn',task.get('depends_on',[])) if isinstance(task.get('dependsOn',task.get('depends_on',[])),list) else []:
                    if isinstance(source,str):link(source.upper(),ident,'task_dependency',evidence)
        if isinstance(value,list) and path.endswith('scenarios.json'):
            for scenario in value:
                if not isinstance(scenario,dict) or not isinstance(scenario.get('fixture'),str):continue
                relative=PurePosixPath(scenario['fixture'])
                if relative.is_absolute() or '..' in relative.parts:continue
                fixture=str(PurePosixPath(path).parent / relative)
                if fixture not in files:continue
                for test in scenario.get('tests',[]) if isinstance(scenario.get('tests',[]),list) else []:
                    if isinstance(test,str):link(test.upper(),fixture,'scenario_fixture',path)
    return {'schema_version':1,'artifacts':artifacts,'ids':[{'id':ident,'mentioned_in':paths} for ident,paths in sorted(mentions.items())],
            'links':links,'note':'Структурные связи подтверждены только для согласованных документов; остальные связи и совпадения являются предположениями.'}

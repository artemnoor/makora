"""Opt-in real App Server skill execution in an isolated temporary workspace."""
import argparse
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path


def run(model, timeout):
    binary = os.environ.get('CODEX_APP_SERVER_BINARY') or shutil.which('codex.exe') or shutil.which('codex')
    if not binary:
        raise RuntimeError('Codex binary is required')
    with tempfile.TemporaryDirectory(prefix='makora-skill-smoke-', ignore_cleanup_errors=True) as folder:
        root = Path(folder)
        skill = root/'audit-skill'
        skill.mkdir()
        marker = uuid.uuid4().hex
        (skill/'SKILL.md').write_text('---\nname: audit-skill\ndescription: Write isolated test evidence\n---\nЗапиши файл evidence.txt в рабочей папке с точным содержимым '+marker+'. Не изменяй другие файлы.\n', 'utf-8')
        process = subprocess.Popen([binary,'app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',cwd=root,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        messages=queue.Queue()
        def read():
            for line in process.stdout:
                try: messages.put(json.loads(line))
                except ValueError: pass
        threading.Thread(target=read,daemon=True).start()
        seq=0
        deadline=time.monotonic()+timeout
        def call(method,params):
            nonlocal seq
            seq+=1
            process.stdin.write(json.dumps({'id':seq,'method':method,'params':params})+'\n');process.stdin.flush()
            while time.monotonic()<deadline:
                message=messages.get(timeout=max(.1,deadline-time.monotonic()))
                if message.get('id')==seq:
                    if 'error' in message: raise RuntimeError(message['error'])
                    return message.get('result')
            raise TimeoutError(method)
        try:
            call('initialize',{'clientInfo':{'name':'makora-native-skill-smoke','version':'1'},'capabilities':{'experimentalApi':True}})
            thread=call('thread/start',{'cwd':str(root),'model':model,'ephemeral':True,'approvalPolicy':'never','sandbox':'workspace-write'})['thread']['id']
            turn=call('turn/start',{'threadId':thread,'input':[{'type':'skill','name':'audit-skill','path':str(skill/'SKILL.md')},{'type':'text','text':'Выполни подключённый навык. Работай только в текущей папке.'}],'approvalPolicy':'never'})['turn']['id']
            while time.monotonic()<deadline:
                message=messages.get(timeout=max(.1,deadline-time.monotonic()))
                if message.get('method')=='turn/completed' and message.get('params',{}).get('turn',{}).get('id')==turn:
                    break
            evidence=root/'evidence.txt'
            if not evidence.is_file() or evidence.read_text('utf-8').strip()!=marker:
                raise RuntimeError('Native skill did not produce matching evidence')
            return {'status':'passed','binding':'native-skill-input','fileWritten':True,'markerMatched':True,'model':model}
        finally:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:
                process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait()


def run_bridge(model, timeout):
    import socket
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from makora_core.agents.runtime import CodexLocalApi
    with tempfile.TemporaryDirectory(prefix='makora-bridge-smoke-', ignore_cleanup_errors=True) as folder:
        root=Path(folder); (root/'agents').mkdir(); (root/'task').mkdir(); (root/'skill').mkdir()
        marker=uuid.uuid4().hex
        skill=root/'skill/SKILL.md'
        skill.write_text('---\nname: audit-skill\ndescription: Write isolated evidence\n---\nСоздай evidence.txt в текущей рабочей папке с содержимым '+marker+'. Не трогай другие файлы.\n','utf-8')
        repository=Path(__file__).resolve().parents[1]
        integration=repository/'integrations/codex-desktop-local-api'
        api=CodexLocalApi(integration,root)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
        env={**os.environ,'PORT':str(port),'CODEX_LOCAL_API_TOKEN':api._token,
             'CODEX_APP_SERVER_BINARY':shutil.which('codex.exe') or shutil.which('codex'),'CODEX_DEFAULT_CWD':str(root/'task')}
        bridge=subprocess.Popen(['node',str(integration/'server.mjs')],env=env,cwd=root/'task',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        api._base=f'http://127.0.0.1:{port}'
        api.ensure_started=lambda:None
        deadline=time.monotonic()+timeout
        try:
            while time.monotonic()<deadline:
                try:
                    api._request('/api/models',timeout=3);break
                except Exception: time.sleep(.5)
            created=api.create_thread(cwd=root/'task',name='Native skill smoke',prompt='Выполни подключённый навык в текущей папке.',
                model=model,skills=[{'name':'audit-skill','path':str(skill)}],read_roots=[str(root/'skill')])
            while time.monotonic()<deadline:
                operation=api.operation(created['operation']['id'])
                if operation.get('done'):break
                time.sleep(1)
            evidence=root/'task/evidence.txt'
            if not evidence.is_file() or evidence.read_text('utf-8').strip()!=marker:
                raise RuntimeError('Macora bridge did not produce native skill evidence')
            return {'status':'passed','binding':'macora-bridge-native-skill','markerMatched':True,'model':model}
        finally:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(bridge.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:bridge.terminate()
            bridge.wait(timeout=10)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',default='gpt-6-luna')
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--bridge',action='store_true')
    args=parser.parse_args()
    print(json.dumps((run_bridge if args.bridge else run)(args.model,args.timeout)))

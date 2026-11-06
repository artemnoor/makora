"""Install project skills and control the same local API as the Makora UI."""
import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def request(config, path, payload=None):
    if not path.startswith('/api/') or '?' in path or '..' in path:
        raise ValueError('Use a local /api/ route without a query string')
    base = f"http://127.0.0.1:{config['port']}"
    def read(route, data=None, headers=None):
        req = urllib.request.Request(base + route, data=data, headers={'Origin': base, **(headers or {})})
        with urllib.request.urlopen(req, timeout=220) as response:
            return json.load(response)
    current = read('/api/preparation')['result']
    if Path(current['storageRoot']).resolve() != Path(config['projectRoot']).resolve():
        raise ValueError('This port belongs to another project; select a different port')
    headers = {}
    if payload is not None:
        auth = read('/api/agents/token', headers={'X-Makora-Request': 'token'})
        headers = {'X-Makora-Token': auth['result']['token'], 'Content-Type': 'application/json'}
    return read(path, json.dumps(payload).encode('utf-8') if payload is not None else None, headers)


def install(project, port):
    project.mkdir(parents=True, exist_ok=True)
    skills = project / '.agents' / 'skills'
    skills.mkdir(parents=True, exist_ok=True)
    for source in (REPO / 'skills').iterdir():
        if source.is_dir() and (source / 'SKILL.md').exists() and not (skills / source.name).exists():
            shutil.copytree(source, skills / source.name)
    config = project / '.makora' / 'control.json'
    config.parent.mkdir(exist_ok=True)
    config.write_text(json.dumps({'projectRoot': str(project), 'repository': str(REPO), 'port': port}, ensure_ascii=False, indent=2), 'utf-8')
    instructions = project / 'AGENTS.md'
    marker = '<!-- makora:project -->'
    old = instructions.read_text('utf-8') if instructions.exists() else ''
    if marker not in old:
        old += f'\n\n{marker}\nДля управления Макорой прочитай `.agents/skills/makora-control/SKILL.md`.\nКонтроллер: `{REPO / "scripts" / "makora.py"}`. Конфигурация текущего проекта: `.makora/control.json`.\nЭто один проект; используй его состояние и документы из input/, artifacts/, reports/, app/.\n'
        instructions.write_text(old, 'utf-8')
    return {'installed': True, 'project': str(project), 'skills': str(skills)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('install')
    setup.add_argument('--port', type=int, default=8000)
    commands.add_parser('launch')
    commands.add_parser('status')
    call = commands.add_parser('request')
    call.add_argument('path')
    call.add_argument('--json', type=Path, help='UTF-8 JSON file; omit for GET')
    args = parser.parse_args()
    project = args.project_root.expanduser().resolve()
    if args.command == 'install':
        if not 1 <= args.port <= 65535:
            parser.error('Invalid port')
        result = install(project, args.port)
    else:
        config = json.loads((project / '.makora' / 'control.json').read_text('utf-8'))
        if args.command == 'launch':
            try:
                result = request(config, '/api/preparation')
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                log = project / '.makora' / 'server.log'
                with log.open('ab') as stream:
                    process = subprocess.Popen([sys.executable, '-m', 'makora_core.server', '--static', str(REPO / 'dist'), '--workspace', str(project / '.makora' / 'workspace'), '--project-root', str(project), '--port', str(config['port'])], cwd=REPO, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f'Server exited; see {log}')
                    try:
                        request(config, '/api/preparation')
                        break
                    except urllib.error.HTTPError:
                        raise
                    except urllib.error.URLError:
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f'Server did not start; see {log}')
                        time.sleep(.2)
                result = {'pid': process.pid, 'url': f"http://127.0.0.1:{config['port']}", 'log': str(log)}
        else:
            payload = json.loads(args.json.read_text('utf-8-sig')) if args.command == 'request' and args.json else None
            result = request(config, args.path if args.command == 'request' else '/api/preparation', payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

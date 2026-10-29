"""Prepare skill invocations and manage artifacts; does not call an AI model."""
import argparse
import json
from pathlib import Path

from .workspace import MakoraError, Workspace


SKILLS = Path(__file__).resolve().parent.parent / 'skills'


def parser():
    result = argparse.ArgumentParser(description='Локальные артефакты Макоры')
    sub = result.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('workspace')
    listing = sub.add_parser('skills')
    register = sub.add_parser('register'); register.add_argument('workspace'); register.add_argument('id'); register.add_argument('path'); register.add_argument('type'); register.add_argument('--depends-on', action='append', default=[]); register.add_argument('--source', action='append', default=[])
    approve = sub.add_parser('approve'); approve.add_argument('workspace'); approve.add_argument('id'); approve.add_argument('--note', default='')
    audit = sub.add_parser('audit'); audit.add_argument('workspace')
    prepare = sub.add_parser('prepare'); prepare.add_argument('workspace'); prepare.add_argument('skill'); prepare.add_argument('--artifact', action='append', default=[]); prepare.add_argument('--task', required=True); prepare.add_argument('--constraint', action='append', default=[]); prepare.add_argument('--output', action='append', default=[]); prepare.add_argument('--success', action='append', default=[])
    return result


def main():
    args = parser().parse_args()
    try:
        if args.command == 'skills':
            result = [{'name': p.parent.name, 'path': str(p.resolve())} for p in sorted(SKILLS.glob('*/SKILL.md'))]
        elif args.command == 'init':
            workspace = Workspace.create(args.workspace)
            result = {'workspace': str(workspace.root), 'status': 'created'}
        else:
            workspace = Workspace(args.workspace)
            if args.command == 'register':
                result = workspace.register(args.id, args.path, args.type, args.depends_on, args.source)
            elif args.command == 'approve':
                result = workspace.approve(args.id, args.note)
            elif args.command == 'audit':
                changed = workspace.audit()
                result = {'changed': changed, 'artifacts': workspace.manifest['artifacts']}
            else:
                skill = SKILLS / args.skill / 'SKILL.md'
                if not skill.resolve().is_relative_to(SKILLS.resolve()) or not skill.is_file():
                    raise MakoraError('SKILL_NOT_FOUND', 'Скилл не найден в реестре проекта.')
                result = {'skill': args.skill, 'skill_path': str(skill.resolve()), 'task': args.task,
                          'artifacts': workspace.context(args.artifact), 'constraints': args.constraint,
                          'expected_outputs': args.output, 'success_criteria': args.success, 'execution': 'not_started',
                          'message': 'Пакет подготовлен; исполнитель модели не подключён.'}
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, indent=2))
    except (MakoraError, OSError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': {'code': getattr(exc, 'code', 'IO_ERROR'), 'message': str(exc)}}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

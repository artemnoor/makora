"""Create a disposable, clean Git repository for the opt-in REAL browser cycle."""
import argparse
import subprocess
import tempfile
from pathlib import Path


def git(root: Path, *args: str) -> str:
    result = subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def prepare(parent: Path | None = None) -> Path:
    parent = parent.resolve() if parent else Path(tempfile.gettempdir()).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='makora-real-agent-e2e-', dir=parent)).resolve()
    (root / 'README.md').write_text('# Makora real agent E2E fixture\n\nDisposable Python project for one isolated Builder task.\n', encoding='utf-8')
    git(root, 'init', '--initial-branch=main')
    git(root, 'config', 'user.name', 'Makora E2E')
    git(root, 'config', 'user.email', 'makora-e2e@localhost')
    git(root, 'add', 'README.md')
    git(root, 'commit', '-m', 'Create disposable agent E2E fixture')
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=Path, help='Parent directory for the disposable repository')
    args = parser.parse_args()
    print(prepare(args.parent))

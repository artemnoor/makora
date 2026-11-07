"""Immutable, content-addressed snapshots of the skills used by a task."""
import hashlib
import shutil
from pathlib import Path


def snapshot_skill(source, destination):
    source = Path(source).resolve()
    entries = list(source.parent.rglob('*'))
    if any(path.is_symlink() for path in entries):
        raise ValueError('Skill packages cannot contain symbolic links')
    files = sorted((path for path in entries if path.is_file()), key=lambda path:path.relative_to(source.parent).as_posix().encode())
    if len(files) > 200 or any(path.is_symlink() for path in files):
        raise ValueError('Skill package must contain at most 200 regular files')
    digest = hashlib.sha256()
    total = 0
    for path in files:
        data = path.read_bytes()
        total += len(data)
        if total > 8 * 1024 * 1024:
            raise ValueError('Skill package exceeds 8 MB')
        digest.update(path.relative_to(source.parent).as_posix().encode() + b'\0' + data + b'\0')
    version = digest.hexdigest()
    target = Path(destination) / source.parent.name / version
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source.parent, target)
    stored = hashlib.sha256()
    entries = list(target.rglob('*'))
    if any(path.is_symlink() for path in entries):
        raise ValueError('Stored skill snapshot contains symbolic links')
    for path in sorted((path for path in entries if path.is_file()), key=lambda path:path.relative_to(target).as_posix().encode()):
        stored.update(path.relative_to(target).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    if stored.hexdigest() != version:
        raise ValueError('Stored skill package does not match its manifest')
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    if (target/'SKILL.md').is_symlink() or hashlib.sha256((target/'SKILL.md').read_bytes()).hexdigest() != expected:
        raise ValueError('Stored skill snapshot does not match its manifest')
    return {'name':source.parent.name, 'path':str((target/'SKILL.md').resolve()),
            'sha256':expected, 'packageSha256':version}

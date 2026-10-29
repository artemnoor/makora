import tempfile
import unittest
from pathlib import Path

from makora_core.workspace import MakoraError, Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace.create(self.temp.name)

    def add(self, ident, name, content, dependencies=()):
        path = self.ws.root / 'artifacts' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        self.ws.register(ident, 'artifacts/' + name, 'markdown', dependencies)
        return path

    def test_versions_and_targeted_invalidation(self):
        source = self.add('A', 'brief.md', 'first')
        self.add('B', 'plan.md', 'plan', ['A'])
        self.add('C', 'other.md', 'independent')
        for ident in ('A', 'B', 'C'):
            self.ws.approve(ident, 'reviewed')
        source.write_text('updated', encoding='utf-8')
        self.assertEqual(self.ws.audit(), ['A'])
        self.assertEqual(self.ws.artifact('A')['version'], 2)
        self.assertEqual(self.ws.artifact('A')['status'], 'draft')
        self.assertEqual(self.ws.artifact('B')['status'], 'stale')
        self.assertEqual(self.ws.artifact('C')['status'], 'approved')
        with self.assertRaises(MakoraError):
            self.ws.context(['B'])
        snapshots = [p.read_text(encoding='utf-8') for p in (self.ws.root / 'state' / 'versions').rglob('*') if p.is_file()]
        self.assertIn('first', snapshots)
        self.assertIn('updated', snapshots)

    def test_no_approval_with_unapproved_or_missing_dependency(self):
        source = self.add('A', 'brief.md', 'first')
        self.add('B', 'plan.md', 'plan', ['A'])
        with self.assertRaises(MakoraError):
            self.ws.approve('B', '')
        self.ws.approve('A', '')
        self.ws.approve('B', '')
        source.unlink()
        with self.assertRaises(MakoraError):
            self.ws.context(['B'])
        self.assertEqual(self.ws.artifact('A')['status'], 'stale')

    def test_path_escape_and_duplicate_id_rejected(self):
        self.add('A', 'brief.md', 'first')
        with self.assertRaises(MakoraError):
            self.ws.register('A', 'artifacts/brief.md', 'markdown')
        with self.assertRaises(MakoraError):
            self.ws.register('B', '../outside', 'markdown')
        with self.assertRaises(MakoraError):
            self.ws.register('C', 'state/manifest.json', 'json')


if __name__ == '__main__':
    unittest.main()

import tempfile
import unittest
from pathlib import Path
from makora_core.skill_manifest import snapshot_skill

class SkillManifestTests(unittest.TestCase):
    def test_complete_package_is_frozen_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();(source/'references').mkdir()
            (source/'SKILL.md').write_text('---\nname: source\ndescription: test\n---\nUse references/check.md','utf-8')
            (source/'references/check.md').write_text('Original methodology','utf-8')
            first=snapshot_skill(source/'SKILL.md',root/'versions')
            second=snapshot_skill(source/'SKILL.md',root/'versions')
            self.assertEqual(first,second)
            frozen=Path(first['path']).parent/'references/check.md'
            frozen.write_text('Silently changed methodology','utf-8')
            with self.assertRaisesRegex(ValueError,'package'):
                snapshot_skill(source/'SKILL.md',root/'versions')

import unittest
from pathlib import Path
from unittest.mock import patch
import test_artifact_changes as fixtures
from makora_core.agents.runtime import AgentRuntimeError

class ChangeRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ArtifactChangeTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.service=fixture.service;self.preparation=fixture.preparation;self.proposal=fixture.proposal
        self.project=self.preparation.root/'project';self.project.mkdir()
        self.preparation.state['storageRoot']=str(self.project)
        def write(name,data):
            path=self.project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.write=write;self.preparation._storage_write=write
        for record in self.preparation.state['stages'].values():
            for name,text in record['files'].items():write('artifacts/'+name,text.encode())

    def test_crash_before_state_commit_rolls_back_disk(self):
        item=self.proposal();original=self.preparation.state['stages']['3']['files']['02_user_flow.mmd']
        def crash(name,data):self.write(name,data);raise SystemExit('simulated process death')
        self.preparation._storage_write=crash
        with self.assertRaises(SystemExit):self.service.apply(item['id'],{'confirm':True})
        self.preparation._storage_write=self.write
        self.assertEqual(['rolled_back'],self.service.recover())
        self.assertEqual(original,(self.project/'artifacts/02_user_flow.mmd').read_text('utf-8'))
        self.assertEqual('proposed',self.service.get(item['id'])['status'])

    def test_crash_after_state_commit_finalizes_proposal(self):
        item=self.proposal();write=self.service._write
        def crash(value):
            if value['status']=='applied':raise SystemExit('simulated metadata failure')
            return write(value)
        with patch.object(self.service,'_write',side_effect=crash):
            with self.assertRaises(SystemExit):self.service.apply(item['id'],{'confirm':True})
        self.assertEqual(['committed'],self.service.recover())
        self.assertEqual('applied',self.service.get(item['id'])['status'])
        self.assertEqual([],self.service.recovery_status()['pending'])

    def test_new_external_edit_is_preserved_on_recovery_conflict(self):
        item=self.proposal()
        def crash(name,data):self.write(name,data);raise SystemExit('process death')
        self.preparation._storage_write=crash
        with self.assertRaises(SystemExit):self.service.apply(item['id'],{'confirm':True})
        self.preparation._storage_write=self.write
        self.write('artifacts/02_user_flow.mmd',b'flowchart TD\nA-->NEW\n')
        with self.assertRaises(AgentRuntimeError):self.service.recover()
        report=self.service.recovery_status()
        result=self.service.resolve_recovery(item['id'],{'confirm':True,'expectedStateHash':report['stateHash']})
        self.assertTrue(result['requiresScan'])
        new=self.service.scan({'request':'Согласовать мою новую правку','targets':['02_user_flow.mmd']})
        self.assertIn('NEW',new['changes'][0]['after'])

import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from makora_core.artifact_changes import ArtifactChanges
from makora_core.agents.runtime import AgentRuntimeError


class ArtifactChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        state = {'projectId':'p','stages':{
            '3':{'status':'approved','files':{'02_user_flow.mmd':'flowchart TD\nA-->B\n','02_solution_concept.md':'REQ-1 registration'}},
            '4':{'status':'approved','files':{'03_tasks.json':json.dumps({'tasks':[{'id':'T01','requirements':['REQ-1']}]} )}},
            '5':{'status':'approved','files':{'mocks/fixtures/data.json':'[]'}}}}
        self.preparation = SimpleNamespace(root=root, lock=threading.RLock(), state=state,
            validate=lambda files,stage:[{'status':'passed'}], save=lambda:None, _check_project_idle=lambda:None)
        self.service=ArtifactChanges(self.preparation)

    def proposal(self):
        return self.service.propose({'request':'Убрать шаг регистрации в User flow',
            'targets':['02_user_flow.mmd'],'files':{'02_user_flow.mmd':'flowchart TD\nA-->C\n'}})

    def test_proposal_preserves_original_and_apply_requires_confirmation(self):
        proposal=self.proposal()
        self.assertIn('A-->B',self.preparation.state['stages']['3']['files']['02_user_flow.mmd'])
        self.assertIn('-A-->B',proposal['changes'][0]['diff'])
        self.assertEqual('possible',proposal['impact'][0]['confidence'])
        with self.assertRaises(AgentRuntimeError): self.service.apply(proposal['id'],{})
        result=self.service.apply(proposal['id'],{'confirm':True,'reviewStages':[4]})
        self.assertEqual('applied',result['status'])
        self.assertEqual('review',self.preparation.state['stages']['3']['status'])
        self.assertEqual('stale',self.preparation.state['stages']['4']['status'])
        self.assertEqual('approved',self.preparation.state['stages']['5']['status'])
        self.assertTrue((self.service.directory()/(proposal['id']+'-before.json')).exists())
        self.assertEqual(1,len(self.service.list()))

    def test_stale_base_invalid_result_and_unknown_paths_do_not_apply(self):
        proposal=self.proposal()
        self.preparation.state['stages']['4']['files']['03_tasks.json']='[]'
        with self.assertRaisesRegex(AgentRuntimeError,'База изменилась'): self.service.apply(proposal['id'],{'confirm':True})
        proposal=self.proposal()
        self.preparation.validate=lambda *_:[{'status':'failed'}]
        with self.assertRaises(AgentRuntimeError): self.service.apply(proposal['id'],{'confirm':True})
        self.assertEqual('approved',self.preparation.state['stages']['3']['status'])
        with self.assertRaises(AgentRuntimeError): self.service.propose({'request':'x','targets':['../secret']})
        with self.assertRaises(AgentRuntimeError): self.service.get('../secret')

    def test_request_without_replacement_is_analysis_only(self):
        item=self.service.propose({'request':'Изменить переход','targets':['02_user_flow.mmd']})
        self.assertEqual('analysis_only',item['status'])
        self.assertTrue(item['impact'])
        with self.assertRaises(AgentRuntimeError): self.service.apply(item['id'],{'confirm':True})

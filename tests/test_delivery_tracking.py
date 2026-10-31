import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('node'), 'Node.js required for bridge regression')
class DeliveryTrackingTests(unittest.TestCase):
    def test_long_running_exact_turn_and_late_delivery_recover_without_resend(self):
        source=(Path(__file__).resolve().parents[1]/'integrations/codex-desktop-local-api/server.mjs').read_text('utf-8')
        tracker=source[source.index('function operationView('):source.index('function localOrigin(')]
        harness=r'''
const assert=require('node:assert/strict');
let now=1, sequence=0, timeline={turns:[]}, polls=[];
Date.now=()=>now;
const operations=new Map(),activeThreadOperations=new Map();
const randomUUID=()=>String(++sequence),publish=()=>{};
const readThreadTimeline=async()=>timeline;
const setTimeout=fn=>{polls.push(fn);return {unref(){}}};
const tick=async()=>{const fn=polls.shift();assert.ok(fn);await fn()};
'''+tracker+r'''
(async()=>{
let op=startDeliveryTracking('thread','prompt',null,'exact');
timeline={turns:[{id:'exact',status:'inProgress',items:[]}]};now=181000;await tick();
assert.equal(operations.get(op.id).state,'delivered');assert.equal(operations.get(op.id).done,false);
assert.equal(activeThreadOperations.get('thread'),op.id);
timeline={turns:[{id:'exact',status:'completed',items:[{role:'assistant',phase:'final_answer',text:'Done'}]}]};
await tick();assert.equal(operations.get(op.id).state,'completed');assert.equal(activeThreadOperations.has('thread'),false);
op=startDeliveryTracking('late','prompt',null,'late-exact');now+=181000;
timeline={turns:[{id:'wrong',status:'completed',items:[{role:'assistant',text:'Not ours'}]}]};await tick();
assert.equal(operations.get(op.id).state,'unconfirmed');assert.equal(operations.get(op.id).done,false);
assert.equal(activeThreadOperations.get('late'),op.id);
timeline={turns:[{id:'late-exact',status:'completed',items:[{role:'assistant',text:'Done'}]}]};await tick();
assert.equal(operations.get(op.id).state,'completed');assert.equal(activeThreadOperations.has('late'),false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run(['node','-e',harness],capture_output=True,text=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stderr)

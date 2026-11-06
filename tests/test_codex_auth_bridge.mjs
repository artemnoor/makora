import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
const source=readFileSync(new URL('../integrations/codex-desktop-local-api/server.mjs',import.meta.url),'utf8');
const code=source.slice(source.indexOf('let accountCheck = null;'),source.indexOf('const appToolsContextThreadId'));
async function check(rpc){return runInNewContext(code+'\nauthStatus();',{rpc,Date,Boolean})}
assert.equal((await check(async()=>({account:null,requiresOpenaiAuth:true}))).status,'signed_out');
assert.equal((await check(async()=>({account:{type:'chatgpt'},requiresOpenaiAuth:true}))).status,'signed_in');
assert.equal((await check(async()=>({account:null,requiresOpenaiAuth:false}))).status,'signed_in');
assert.equal((await check(async()=>{throw Error('Your access token could not be refreshed. Please sign in again.')})).status,'signed_out');
assert.equal((await check(async()=>{throw Error('Connection closed')})).status,'unavailable');
const safe=await check(async()=>({account:{type:'chatgpt',email:'private@example.com',accessToken:'secret'},requiresOpenaiAuth:true}));
assert.ok(!JSON.stringify(safe).includes('secret'));
assert.ok(!JSON.stringify(safe).includes('private@example.com'));
console.log('Codex auth bridge: account, expired token, disconnect and redaction passed');
const errorCode=source.slice(source.indexOf('const turnErrors = new Map();'),source.indexOf('let accountCheck = null;'));
runInNewContext(errorCode+`
captureTurnError({method:'error',params:{turnId:'failed-turn',willRetry:false,error:{message:'unauthorized'}}});
assert.equal(turnErrors.get('failed-turn').message,'unauthorized');
captureTurnError({method:'error',params:{turnId:'retrying-turn',willRetry:true,error:{message:'temporary'}}});
assert.equal(turnErrors.has('retrying-turn'),false);
captureTurnError({method:'turn/completed',params:{turn:{id:'terminal-turn',error:{message:'failed'}}}});
assert.equal(turnErrors.get('terminal-turn').message,'failed');
`,{Map,assert});
console.log('Terminal turn errors preserved; retryable errors excluded');

const deliveryCode=source.slice(source.indexOf('function operationView('),source.indexOf('function localOrigin('));
await runInNewContext(`const callbacks=[];const history={turns:[{id:'exact-turn',status:'interrupted',items:[]}]};
const readThreadTimeline=async()=>history;
const setTimeout=(callback)=>{callbacks.push(callback);return {unref(){}}};
`+deliveryCode+`
(async()=>{
 const view=startDeliveryTracking('desktop-thread','prompt',null,'exact-turn','desktop');
 await callbacks.shift()();
 const op=operations.get(view.id);
 assert.equal(op.state,'unconfirmed');
 assert.equal(op.done,false);
 assert.equal(activeThreadOperations.get('desktop-thread'),op.id);
 history.turns[0]={id:'exact-turn',status:'completed',items:[{role:'assistant',phase:'final_answer',text:'Done'}]};
 await callbacks.shift()();
 assert.equal(op.state,'completed');
 assert.equal(activeThreadOperations.has('desktop-thread'),false);
})()
`,{assert,Date,Map,operations:new Map(),activeThreadOperations:new Map(),randomUUID:()=> 'op',publish:()=>{}});

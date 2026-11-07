import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,dirname,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {buildTurnInput} from '../integrations/codex-desktop-local-api/skill-input.mjs';
const folder=await mkdtemp(join(tmpdir(),'makora-skill-input-'));
try {
 const path=join(folder,'SKILL.md'),body='---\nname: test-skill\ndescription: test\n---\nWrite evidence.';
 await writeFile(path,body);
 const skill={name:'test-skill',path,sha256:createHash('sha256').update(body).digest('hex')};
 const input=await buildTurnInput('perform',[skill]);
 assert.equal(input[1].type,'skill');assert.equal(input[1].name,'test-skill');
 assert.equal(input[0].type,'text');assert.equal(input.length,2);
 await assert.rejects(buildTurnInput('perform',[{...skill,sha256:'wrong'}]));
 await assert.rejects(buildTurnInput('perform',[{...skill,path:'relative/SKILL.md'}]));
 await assert.rejects(buildTurnInput('perform',[skill,skill]));
 await assert.rejects(buildTurnInput('perform',{}));
 console.log('Native skill input: structured binding and changed/malformed manifests checked');
} finally {
 if(dirname(resolve(folder))!==resolve(tmpdir()))throw Error('Invalid temporary target');
 await rm(folder,{recursive:true,force:true});
}

import {readFile, realpath, readdir} from 'node:fs/promises';
import {basename, isAbsolute, dirname, join, relative} from 'node:path';
import {createHash} from 'node:crypto';

// Resolve and bind the exact skill content before any turn is dispatched.
export async function buildTurnInput(text, skills = []) {
  if (!Array.isArray(skills) || skills.length > 12) throw new Error('Invalid native skills list');
  const input = [{type:'text', text}];
  const names = new Set();
  for (const skill of skills) {
    if (!skill || typeof skill.name !== 'string' || !/^[a-z0-9-]+$/.test(skill.name)
        || typeof skill.path !== 'string' || !isAbsolute(skill.path) || basename(skill.path) !== 'SKILL.md'
        || names.has(skill.name)) throw new Error('Invalid native skill binding');
    names.add(skill.name);
    const path = await realpath(skill.path);
    const bytes = await readFile(path);
    if (bytes.length > 1024 * 1024) throw new Error('Skill is too large');
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (skill.sha256 && digest !== skill.sha256) throw new Error('Skill changed after task creation');
    if (skill.packageSha256) {
      const root=dirname(path), files=[];
      const walk=async folder=>{for(const entry of await readdir(folder,{withFileTypes:true})){
        if(entry.isSymbolicLink())throw new Error('Skill package contains symbolic links');
        const target=join(folder,entry.name);if(entry.isDirectory())await walk(target);else if(entry.isFile())files.push(target);
        if(files.length>200)throw new Error('Skill package has too many files');
      }};
      await walk(root);
      files.sort((a,b)=>Buffer.compare(Buffer.from(relative(root,a).replaceAll('\\','/')),Buffer.from(relative(root,b).replaceAll('\\','/'))));
      const hash=createHash('sha256');let size=0;
      for(const file of files){const data=await readFile(file);size+=data.length;if(size>8*1024*1024)throw new Error('Skill package is too large');
        hash.update(relative(root,file).replaceAll('\\','/'));hash.update(Buffer.from([0]));hash.update(data);hash.update(Buffer.from([0]));}
      if(hash.digest('hex')!==skill.packageSha256)throw new Error('Skill package changed after task creation');
    }
    input.push({type:'skill', name:skill.name, path});
  }
  return input;
}

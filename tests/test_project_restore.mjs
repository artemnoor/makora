import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const script = readFileSync(new URL('../dist/project-start.js', import.meta.url), 'utf8');
for (const snapshot of [
  { storageRoot: 'project', brief: '', lastStage: 1 },
  { storageRoot: 'project', brief: 'Saved task', lastStage: 3, stages: { '4': { status: 'review' } } },
]) {
  const dom = new JSDOM('<section id="first-stage"><div class="first-form"><h1>Task</h1><p>Intro</p><button data-choose-project-folder></button></div></section>', { runScripts: 'outside-only' });
  let restored = null;
  const calls = [];
  dom.window.fetch = async (path, options) => {
    calls.push({ path, options });
    return { ok: true, json: async () => ({ result: snapshot }) };
  };
  dom.window.addEventListener('makora:resume-project', event => { restored = event.detail; });
  dom.window.eval(script);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/api/preparation');
  assert.equal(calls[0].options.method, undefined);
  assert.equal(restored, snapshot.brief ? snapshot : null);
  assert.ok(dom.window.document.querySelector('[data-choose-project-folder]').hidden);
  dom.window.close();
}
console.log('Project restoration PASS: saved stage restored; empty project stays at upload; no mutation requests.');

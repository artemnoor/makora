async page => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const readRun = async () => page.evaluate(async () => {
    const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
    const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
    return state.runs.at(-1);
  });
  let run=await readRun();
  let task=run.tasks[0];
  if(task.status==='integrated'){
    assert(task.repairAttempts>=1,'Интегрирован без подтверждённого цикла исправлений');
    assert(task.tests?.status==='passed'&&task.tests.independent===true,'Интеграция не опирается на независимые тесты');
    assert(task.tests.commands.every(command=>command.executedTests>=1),'Runner не подтвердил число выполненных тестов');
    assert(task.review?.verdict==='pass'&&task.review.digest===task.tests.digest&&task.review.suiteDigest===task.tests.suiteDigest,'Reviewer не подтвердил те же хеши тестов и кода');
    return {runId:run.id,status:task.status,repairAttempts:task.repairAttempts,executedTests:task.tests.commands.map(command=>command.executedTests),codeDigest:task.tests.digest,suiteDigest:task.tests.suiteDigest,integratedCommit:task.integratedCommit,review:task.review.verdict};
  }
  assert(task.repairAttempts===1&&task.status==='review_pending','Продолжение требует настоящего завершённого цикла Reviewer → Builder');

  for(let reviewPass=0;reviewPass<4;reviewPass++){
    const tests=page.locator('[data-agent-action="tests"][data-task="T01"]');
    await tests.waitFor({state:'visible',timeout:30000});
    await page.evaluate(()=>{
      window.prompt=()=> 'src/slug.py';
      document.querySelector('[data-agent-action="tests"][data-task="T01"]').click();
    });
    await page.waitForFunction(async()=>{
      const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
      const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
      return state.runs.at(-1)?.tasks[0]?.tests?.status==='passed';
    },null,{timeout:180000});
    run=await readRun();task=run.tasks[0];
    assert(task.tests.independent===true&&task.tests.commands.every(command=>command.executedTests>=1),'Независимый набор не подтвердил реальные выполненные тесты');
    await page.locator('[data-agent-action="reviewer"][data-task="T01"]').click();
    await page.waitForFunction(async()=>{
      const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
      const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
      return ['review_completed','changes_requested','mahoraga_required'].includes(state.runs.at(-1)?.tasks[0]?.status);
    },null,{timeout:240000});
    run=await readRun();task=run.tasks[0];
    if(task.status==='review_completed'){
      await page.evaluate(()=>{window.confirm=()=>true});
      await page.locator('[data-agent-action="integrate"][data-task="T01"]').click();
      await page.waitForFunction(async()=>{
        const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
        const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
        return state.runs.at(-1)?.tasks[0]?.status==='integrated';
      },null,{timeout:60000});
      run=await readRun();task=run.tasks[0];
      return {runId:run.id,status:task.status,repairAttempts:task.repairAttempts,tests:task.tests,commit:task.integratedCommit};
    }
    if(task.status==='mahoraga_required'){
      await page.locator('[data-agent-action="mahoraga"][data-task="T01"]').click();
      await page.waitForFunction(async()=>{
        const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
        const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
        return state.runs.at(-1)?.tasks[0]?.status==='blocked_for_human';
      },null,{timeout:240000});
      run=await readRun();task=run.tasks[0];
      return {runId:run.id,status:task.status,repairAttempts:task.repairAttempts,mahoraga:!!task.mahoragaResult};
    }
    assert(task.status==='changes_requested','Reviewer не завершил повторную проверку');
    assert(reviewPass<3,'Лимит исправлений не остановил цикл после третьего follow-up');
    await page.locator('[data-agent-fixes="T01"]').click();
    await page.waitForFunction(async expected=>{
      const token=(await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json()).result.token;
      const state=(await(await fetch('/api/agents/state',{headers:{'X-Makora-Token':token}})).json()).result;
      return state.runs.at(-1)?.tasks[0]?.repairAttempts===expected&&state.runs.at(-1)?.tasks[0]?.status==='review_pending';
    },task.repairAttempts+1,{timeout:240000});
  }
  throw new Error('REAL цикл превысил заданный предел');
}

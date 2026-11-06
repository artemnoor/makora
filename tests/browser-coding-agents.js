async page => {
  await page.reload();
  await page.waitForFunction(()=>!!window.makoraCodingAgents);
  await page.evaluate(()=>window.makoraCodingAgents.render([
    {id:'test-builder',role:'builder',taskId:'TASK-1',status:'running'},
    {id:'test-reviewer',role:'reviewer',taskId:'TASK-2',status:'running'}
  ]));
  await page.waitForFunction(()=>{
    const frames=[...document.querySelectorAll('.nox-worker iframe')];
    return frames.length===2&&frames.every(f=>f.contentWindow.agentDiagnostics?.ready)&&frames[0].contentWindow.agentDiagnostics.mode==='code'&&frames[1].contentWindow.agentDiagnostics.mode==='debug';
  });
  const result=await page.evaluate(async()=>{
    const frame=document.querySelector('.nox-worker iframe');
    window.makoraCodingAgents.render([{id:'test-builder',role:'builder',taskId:'TASK-1',status:'completed'}]);
    if(document.querySelector('.nox-worker iframe')!==frame)throw Error('Polling recreated portrait');
    await new Promise(resolve=>setTimeout(resolve,80));
    if(frame.contentWindow.agentDiagnostics.mode!=='idle')throw Error('Completed agent still coding');
    window.makoraCodingAgents.hide();
    window.makoraCodingAgents.render([{id:'test-builder',role:'builder',taskId:'TASK-1',status:'running'}]);
    await new Promise(resolve=>setTimeout(resolve,80));
    if(frame.contentWindow.agentDiagnostics.mode!=='code')throw Error('Agent did not resume');
    return {realStateMapping:true,persistentPortrait:true,resume:true,ready:frame.contentWindow.agentDiagnostics.ready};
  });
  return result;
}

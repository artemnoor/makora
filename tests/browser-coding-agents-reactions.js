async page => {
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.reload();await page.waitForFunction(()=>!!window.makoraCodingAgents);
  await page.evaluate(()=>window.makoraCodingAgents.render([{id:'reacting-agent',role:'builder',taskId:'TASK-1',status:'running'}]));
  const agent=page.locator('.nox-worker');
  await page.waitForFunction(()=>document.querySelector('.nox-worker iframe')?.contentWindow.agentDiagnostics?.ready);
  const diagnostics=()=>agent.evaluate(el=>el.querySelector('iframe').contentWindow.agentDiagnostics);
  await page.mouse.move(900,300);await page.waitForTimeout(2600);
  let state=await diagnostics();assert(state.locomotion.phase>0&&state.locomotion.blend>.1,'No articulated walking');
  const phase=state.locomotion.phase;await page.waitForTimeout(150);state=await diagnostics();assert(state.locomotion.phase>phase,'Gait not advancing');
  await page.mouse.move(0,0);await page.waitForTimeout(250);state=await diagnostics();assert(state.pointer.x<0&&state.pointer.y<0,'No cursor tracking');
  const box=await agent.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+65);
  await page.waitForFunction(()=>document.querySelector('.nox-worker iframe').contentWindow.agentDiagnostics.visualMode==='wave');
  await page.mouse.click(box.x+box.width/2,box.y+65);
  await page.waitForFunction(()=>document.querySelector('.nox-worker iframe').contentWindow.agentDiagnostics.visualMode==='jump');
  await page.waitForTimeout(1200);assert((await diagnostics()).visualMode==='code','Runtime state not restored after click');
  await page.mouse.move(box.x+box.width/2,box.y+65);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+80,box.y+40,{steps:4});
  await page.waitForFunction(()=>document.querySelector('.nox-worker iframe').contentWindow.agentDiagnostics.locomotion.carried);
  await page.mouse.up();
  await page.waitForFunction(()=>!document.querySelector('.nox-worker iframe').contentWindow.agentDiagnostics.locomotion.carried);
  const clear=await agent.evaluate(el=>{
    const win=el.querySelector('iframe').contentWindow,canvas=win.document.querySelector('canvas'),ctx=canvas.getContext('2d');
    return {background:getComputedStyle(el.querySelector('span')).backgroundColor,alpha:[ctx.getImageData(0,0,1,1).data[3],ctx.getImageData(1,canvas.height-2,1,1).data[3]]};
  });
  assert(clear.alpha.every(a=>a===0)&&clear.background==='rgba(0, 0, 0, 0)','Background remains');
  return {walkCycle:true,cursorTracking:true,hover:true,click:true,dragReaction:true,runtimeRestored:true,transparent:true};
}

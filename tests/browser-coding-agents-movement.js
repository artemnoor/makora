async page => {
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.reload();await page.waitForFunction(()=>!!window.makoraCodingAgents);
  await page.evaluate(()=>window.makoraCodingAgents.render([{id:'walking-agent',role:'builder',taskId:'TASK-1',status:'running'}]));
  const agent=page.locator('.nox-worker');
  await page.mouse.move(800,50);
  const before=await agent.boundingBox();
  await page.waitForTimeout(2800);
  const walking=await agent.boundingBox();
  assert(Math.hypot(walking.x-before.x,walking.y-before.y)>5,'Agent did not walk');
  await page.mouse.move(walking.x+60,walking.y+65);await page.mouse.down();
  await page.mouse.move(walking.x+240,walking.y-80,{steps:8});await page.mouse.up();
  const dragged=await agent.boundingBox();
  assert(dragged.x>walking.x+100,'Dragging did not move agent');
  await agent.focus();const keyBefore=await agent.boundingBox();await page.keyboard.press('ArrowRight');
  assert((await agent.boundingBox()).x>=keyBefore.x+11,'Keyboard movement failed');
  await page.keyboard.press('Space');assert(await agent.getAttribute('aria-pressed')==='true','Pause failed');
  await page.setViewportSize({width:390,height:600});
  const small=await agent.boundingBox();assert(small.x>=0&&small.y>=0&&small.x+small.width<=391&&small.y+small.height<=601,'Agent escaped screen');
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.evaluate(()=>{document.activeElement.blur();window.makoraCodingAgents.render([{id:'walking-agent',role:'builder',taskId:'TASK-1',status:'running'}])});
  await page.mouse.move(380,0);const still=await agent.boundingBox();await page.waitForTimeout(400);
  const after=await agent.boundingBox();assert(Math.hypot(after.x-still.x,after.y-still.y)<1,'Reduced motion ignored');
  return {wandering:true,drag:true,keyboard:true,pause:true,viewportBounds:true,reducedMotion:true};
}

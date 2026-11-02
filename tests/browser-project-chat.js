async page=>{
 const assert=(v,m)=>{if(!v)throw Error(m)};let messages=[],status='idle',polls=0,posts=0,workflowPosts=0;
 await page.route('**/api/preparation**',route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  if(path.endsWith('/chat')){
   if(request.method()==='POST'){const body=request.postDataJSON();assert(!!body.requestId,'Нет ID сообщения');messages.push({role:'user',text:body.message});posts++;status='running';polls=0}
   else if(status==='running'&&++polls>=2){messages.push({role:'assistant',text:'Ответ Макоры №'+posts+': реализовать поиск заметок.'});status='idle'}
   return route.fulfill({json:{ok:true,result:{messages,status,model:'gpt-6-luna'}}});
  }
  if(request.method()==='POST')workflowPosts++;
  return route.fulfill({json:{ok:true,result:{brief:'Проект заметок',stages:{1:{status:'review',files:{'01_case_analysis.md':'# Заметки'},checks:[]}}}}});
 });
 await page.route('**/api/agents/approvals',r=>r.fulfill({json:{ok:true,result:[]}}));
 await page.evaluate(()=>localStorage.clear());await page.goto(new URL('/',page.url()).href);
 await page.mouse.move(10,100);await page.waitForTimeout(400);assert(await page.locator('.makora-chat-toggle').evaluate(e=>getComputedStyle(e).opacity==='0'),'Панель не скрывается без наведения');
 await page.locator('.mascot-area').hover();await page.locator('.makora-chat-toggle').click();await page.locator('.project-chat textarea').fill('Какие функции нужны?');await page.locator('.project-chat textarea').press('Enter');
 await page.locator('.chat-user').waitFor();assert(await page.locator('.project-chat [type=submit]').isDisabled(),'Отправка не заблокирована во время ответа');
 await page.locator('.chat-assistant').waitFor();await page.locator('.project-chat textarea').fill('А какие ограничения?');await page.locator('.project-chat [type=submit]').click();await page.locator('.chat-assistant').nth(1).waitFor();
 assert(posts===2&&workflowPosts===0,'Чат изменил этап или повторил сообщение');
 await page.reload();await page.locator('.mascot-area').hover();await page.locator('.makora-chat-toggle').click();await page.locator('.chat-assistant').nth(1).waitFor();assert(await page.locator('.chat-user').count()===2,'История не восстановилась');
 await page.waitForTimeout(280);const before=await page.locator('.project-chat').boundingBox(),mascot=await page.locator('.mascot-area').boundingBox();await page.mouse.move(mascot.x+mascot.width/2,mascot.y+mascot.height/2);await page.mouse.down();await page.mouse.move(mascot.x+mascot.width/2+40,mascot.y+mascot.height/2,{steps:5});await page.mouse.up();assert(Math.abs((await page.locator('.project-chat').boundingBox()).x-before.x-40)<3,'Чат не следует за Макорой');
 return {provider:'fake-http',conversation:true,history:true,anchoring:true,noWorkflowMutations:true};
}

async page=>{
 const assert=(v,m)=>{if(!v)throw Error(m)};let resolveStart,current={brief:"",stages:{}};
 await page.route('**/api/preparation**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/start')){await new Promise(r=>{resolveStart=r});current={projectId:'guide-test',brief:'Кейс',stages:{1:{status:'running',threadId:'guide-thread',files:{}}}};return route.fulfill({json:{ok:true,result:current}})}
  if(path.endsWith('/refresh'))return route.fulfill({json:{ok:true,result:{projectId:'guide-test',brief:'Кейс',stages:{1:{status:'review',files:{'01_case_analysis.md':'# Проверенный результат\nREQ-1'},checks:[]}}}}});
  return route.fulfill({json:{ok:true,result:current}});
 });
 await page.goto(new URL('/?new=1',page.url()).href);
 await page.locator('.mg-body h3').filter({hasText:'Пришлите'}).waitFor();
 await page.locator('[data-guide-show]').click();assert(await page.locator('.pixel-drop').evaluate(e=>e.classList.contains('mg-highlight')),'Нет подсветки загрузки');
 await page.locator('#first-text').fill('Приложение с поиском задач');await page.locator('.pixel-start').click();
 await page.locator('.mg-status').filter({hasText:'Отправляем'}).waitFor();assert(await page.locator('.makora-guide').evaluate(e=>e.classList.contains('mg-working')),'Нет ожидания запроса');
 for(let i=0;i<50&&!resolveStart;i++)await page.waitForTimeout(100);assert(resolveStart,"Запрос не дошёл до API");resolveStart();await page.locator('.rp-wait').waitFor();await page.locator('.mg-status').filter({hasText:'Макора работает'}).waitFor();await page.waitForFunction(()=>document.querySelector('.mascot-frame')?.contentDocument?.querySelector('[data-action=wheel]')?.classList.contains('active'));
 await page.locator('[data-guide-show]').click();assert(await page.locator('[data-real-refresh]').evaluate(e=>e.classList.contains('mg-highlight')),'Нет подсветки проверки');
 await page.locator('[data-real-refresh]').click();await page.locator('.mg-body h3').filter({hasText:'Откройте результат'}).waitFor();await page.waitForFunction(()=>!document.querySelector('.mascot-frame')?.contentDocument?.querySelector('[data-action=wheel]')?.classList.contains('active'));
 await page.locator('[data-guide-show]').click();await page.locator('[data-real-file]').click();await page.locator('.mg-body h3').filter({hasText:'Прочитайте'}).waitFor();
 await page.locator('[data-rp-back]').click();await page.locator('.mg-body h3').filter({hasText:'Утвердите'}).waitFor();
 await page.locator('[data-guide-show]').click();assert(await page.locator('[data-real-approve]').evaluate(e=>e.classList.contains('mg-highlight')),'Нет подсветки утверждения');
 await page.waitForTimeout(1800);await page.screenshot({path:'C:/m/makora-guide-review.png'});
 await page.locator('[data-guide-toggle]').click();assert(await page.locator('.mg-body').isHidden(),'Путеводитель не сворачивается');
 await page.evaluate(()=>{document.querySelector('[data-real-stage].active').dataset.realStage='6';const view=document.createElement('div');view.className='real-agent-view';view.dataset.agentSessions=JSON.stringify([{id:'ui-builder',role:'builder',task:'T02',status:'running'},{id:'ui-reviewer',role:'reviewer',task:'T01',status:'accepted'}]);document.querySelector('.board-content').append(view)});await page.locator('.agent-oval').first().waitFor();assert(await page.locator('.agent-oval').count()===2,'Нет овалов реальных сессий');assert((await page.locator('.agent-orbit').innerText()).includes('Builder'),'Нет роли агента'); return {wheelStartStop:true,agentBadges:true,provider:'fake-http',uploadHighlight:true,requestLoading:true,agentLoading:true,documentGuide:true,approvalHighlight:true,collapse:true};
}

async page => {
  // Fake HTTP responses verify the real UI protocol; no claim of model generation.
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let state={storageRoot:'C:/test-project',brief:'',stages:{}},submitted='',lastFeedback='';
  await page.route('**/api/preparation**',async route=>{
    if(new URL(route.request().url()).pathname.endsWith('/folder/select')){state.storageRoot='C:/test-project';return route.fulfill({json:{ok:true,result:{path:'C:/test-project',cancelled:false}}})}
    const request=route.request();if(request.method()==='GET')await new Promise(resolve=>setTimeout(resolve,100));const url=new URL(request.url()),match=url.pathname.match(/\/([1-4])\/(start|refresh|approve)$/);
    if(match){const stage=Number(match[1]),action=match[2],body=request.postDataJSON();
      if(action==='start'){lastFeedback=body.feedback||'';
        if(stage===1&&body.brief){state.brief=body.brief;submitted=body.brief}
        state.stages[stage]={status:'running',threadId:'test-thread-'+stage,turnId:'test-turn-'+stage,files:{}};
        for(const key of Object.keys(state.stages))if(Number(key)>stage)state.stages[key].status='stale';
      }
      if(action==='refresh')Object.assign(state.stages[stage],{status:'review',files:{[stage===1?'01_case_analysis.md':'02_solution_concept.md']:'# Тикеты\n\n## Обязательные требования\n\nREQ-1: поиск тикетов по статусу.\n\n## Открытые вопросы\n\nУточнить авторизацию.'},checks:[{name:'Документ',status:'passed'}]});
      if(action==='approve')state.stages[stage].status='approved';
    }
    await route.fulfill({json:{ok:true,result:state}});
  });
  await page.route('**/api/agents/approvals',route=>route.fulfill({json:{ok:true,result:[]}}));
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear()});await page.reload();
  await page.locator('#first-text').fill('Создать систему тикетов с поиском по статусу и обработкой неверного запроса.');
  await page.locator('.pixel-start').click();await page.locator('[data-real-stage]').first().waitFor();
  assert(submitted.includes('систему тикетов'),'Исходный текст не отправлен API');
  assert(await page.locator('.analysis-thinking').count()===1,'Нет ожидания документа');
  assert(await page.locator('[data-real-stage]').count()===6,'Нет шести этапов');
  assert(await page.locator('.board-next').isHidden(),'Осталась учебная кнопка Далее');
  await page.locator('[data-real-file]').first().waitFor();
  await page.locator('[data-real-file]').first().click();
  assert((await page.locator('[data-real-document]').innerText()).includes('REQ-1'),'Документ API не отображён');
  assert(await page.locator('.board').evaluate(e=>e.classList.contains('expanded')),'Документ не раскрыл доску');
  await page.locator('[data-analysis-close]').click();await page.locator('.analysis-file').waitFor();
  assert(await page.locator('.board').evaluate(e=>e.classList.contains('board-settled')&&!e.classList.contains('expanded')),'Доска не вернулась без анимации');
  assert(!(await page.locator('.board-content').innerText()).includes('Тихий кампус'),'Показан прежний учебный кейс');
  await page.reload();await page.locator('[data-real-file]').first().waitFor();
  await page.locator('[data-real-approve]').click();await page.waitForFunction(()=>document.querySelector('.board-bar h2')?.textContent==='Разработка идеи');await page.locator('[data-real-run]').waitFor();
  assert(state.stages[1].status==='approved','Нет явного утверждения');
  await page.locator('[data-real-run]').click();await page.locator('.analysis-thinking').waitFor();
  await page.locator('[data-real-approve]').waitFor();
  await page.locator('[data-real-stage="1"]').click();await page.locator('[data-analysis-edit]').click();
  const chatBefore=await page.locator('.analysis-chat').boundingBox(),speaker=await page.locator('.mascot-area').boundingBox();
  await page.mouse.move(speaker.x+speaker.width/2,speaker.y+speaker.height/2);await page.mouse.down();await page.mouse.move(speaker.x+speaker.width/2+40,speaker.y+speaker.height/2,{steps:5});await page.mouse.up();
  assert(Math.abs((await page.locator('.analysis-chat').boundingBox()).x-chatBefore.x-40)<3,'Чат не следует за Макорой');
  await page.locator('.analysis-chat textarea').fill('Сохранить уточнение пользователя');const resend=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/preparation/1/start');await page.locator('.analysis-chat [type=submit]').click();await resend;await page.locator('.analysis-thinking').waitFor();
  assert(lastFeedback.includes('Сохранить уточнение'),'Уточнение не передано повторной генерации');
  assert(state.stages[2].status==='stale','Повторный анализ не инвалидирует последующие этапы');
  await page.setViewportSize({width:390,height:844});
  const layout=await page.locator('.board-content').evaluate(el=>({height:el.clientHeight,width:el.clientWidth,scroll:el.scrollWidth}));
  assert(layout.height>=160,'Рабочая область доски слишком мала');
  assert(layout.scroll<=layout.width+1,'Горизонтальный скролл на узком экране');
  for(const viewport of [{width:390,height:844},{width:1280,height:720},{width:1920,height:1080}]){
    await page.setViewportSize(viewport);await page.waitForTimeout(250);
    const bounds=await page.locator('.rp-board').evaluate(board=>{
      const frame=board.getBoundingClientRect();
      return {inside:frame.left>=0&&frame.top>=0&&frame.right<=innerWidth+1&&frame.bottom<=innerHeight+1,
        children:['.board-inner','.board-content','.board-footer'].every(selector=>{
          const r=board.querySelector(selector).getBoundingClientRect();
          return r.left>=frame.left&&r.right<=frame.right+1&&r.top>=frame.top&&r.bottom<=frame.bottom+1;
        })};
    });
    assert(bounds.inside&&bounds.children,'Содержимое выходит за доску: '+JSON.stringify(viewport));
  }
  await page.setViewportSize({width:1280,height:720});
  const mascot=page.locator('.mascot-area'),before=await mascot.boundingBox();
  await page.mouse.move(before.x+before.width/2,before.y+before.height/2);await page.mouse.down();
  await page.mouse.move(before.x+before.width/2+60,before.y+before.height/2+35,{steps:8});await page.mouse.up();
  assert((await mascot.boundingBox()).x>before.x+40,'Персонаж не перетаскивается');
  await page.locator('.board-size').click();
  assert(await page.locator('.board').evaluate(e=>e.classList.contains('rp-large')),'Доска не увеличивается');
  await page.goto(new URL('/?new=1',page.url()).href);
  await page.locator('.analysis-file').waitFor();
  assert(await page.locator('.first-form').isHidden(),'Параметр URL сбросил текущий проект');
  assert(errors.length===0,errors.join('; '));
  return {provider:'fake-http',briefSubmitted:true,realArtifactsRendered:true,approval:true,invalidation:true,reload:true,errors};
}

async page => {
  // Fake HTTP responses verify the real UI protocol; no claim of model generation.
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let state={brief:'',stages:{}},submitted='',lastFeedback='';
  await page.route('**/api/preparation**',async route=>{
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
  assert(await page.locator('[data-real-stage]').count()===6,'Нет шести реальных этапов');
  assert(await page.locator('.board-next').isHidden(),'Осталась учебная кнопка Далее');
  await page.locator('[data-real-feedback]').fill('Сохранить уточнение пользователя');
  await page.locator('[data-real-refresh]').click();await page.locator('[data-real-file]').first().waitFor();
  assert((await page.locator('[data-real-feedback]').inputValue()).includes('Сохранить уточнение'),'Уточнение потерялось при обновлении статуса');
  await page.locator('[data-real-file]').first().click();
  assert((await page.locator('[data-real-document]').innerText()).includes('REQ-1'),'Документ API не отображён');
  assert(!(await page.locator('.board-content').innerText()).includes('Тихий кампус'),'Показан прежний учебный кейс');
  await page.reload();await page.locator('[data-real-file]').first().waitFor();
  await page.locator('[data-real-approve]').click();await page.waitForFunction(()=>document.querySelector('.board-bar h2')?.textContent==='Разработка идеи');await page.locator('[data-real-run]').waitFor();
  assert(state.stages[1].status==='approved','Нет явного утверждения');
  await page.locator('[data-real-run]').click();await page.locator('[data-real-refresh]').waitFor();await page.locator('[data-real-refresh]').click();
  await page.locator('[data-real-approve]').waitFor();
  await page.locator('[data-real-stage="1"]').click();await page.locator('[data-real-run]').click();await page.locator('[data-real-refresh]').waitFor();
  assert(lastFeedback.includes('Сохранить уточнение'),'Уточнение не передано повторной генерации');
  assert(state.stages[2].status==='stale','Повторный анализ не инвалидирует последующие этапы');
  assert(errors.length===0,errors.join('; '));
  return {provider:'fake-http',briefSubmitted:true,realArtifactsRendered:true,approval:true,invalidation:true,reload:true,errors};
}

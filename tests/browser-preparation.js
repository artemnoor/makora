async page => {
  // Fake HTTP responses verify the real UI protocol; no claim of model generation.
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let state={storageRoot:'C:/test-project',brief:'',stages:{}},submitted='',lastFeedback='',ideaRequests=0,chatOpens=0;
  await page.route('**/api/preparation**',async route=>{
    if(new URL(route.request().url()).pathname==='/api/preparation/3/open-codex'){
      assert(route.request().method()==='POST','Открытие чата не использует API');
      chatOpens++;
      state.stages[3].desktopOpened=true;
      return route.fulfill({json:{ok:true,result:state}});
    }
    if(new URL(route.request().url()).pathname==='/api/preparation/idea/start'){
      ideaRequests++;
      const body=route.request().postDataJSON();
      assert(body.openInCodex===true,'Не запрошено открытие чата идеи');
      state.stages[2].status='continued';
      state.competitorDecisions=body.decisions;
      state.stages[3]={status:'awaiting_idea',interactionMode:'user_idea',threadId:'01a1b6b4-a4f1-7893-8945-c4076fe43907',files:{}};
      return route.fulfill({json:{ok:true,result:state}});
    }
    if(new URL(route.request().url()).pathname.endsWith('/folder/select')){state.storageRoot='C:/test-project';return route.fulfill({json:{ok:true,result:{path:'C:/test-project',cancelled:false}}})}
    const request=route.request();if(request.method()==='GET')await new Promise(resolve=>setTimeout(resolve,100));const url=new URL(request.url()),match=url.pathname.match(/\/([0-5])\/(start|refresh|approve)$/);
    if(match){const stage=Number(match[1]),action=match[2],body=request.postDataJSON();
      if(action==='start'){lastFeedback=body.feedback||'';
        assert(body.openInCodex===true,'Доска не запросила открытие чата в Codex');
        if(stage===0&&body.brief){state.brief=body.brief;submitted=body.brief}
        state.stages[stage]={status:'running',threadId:'test-thread-'+stage,turnId:'test-turn-'+stage,files:{}};
        for(const key of Object.keys(state.stages))if(Number(key)>stage)state.stages[key].status='stale';
      }
      if(action==='refresh')Object.assign(state.stages[stage],{status:'review',files:{[stage===1?'01_case_analysis.md':'02_solution_concept.md']:'# Тикеты\n\n## Обязательные требования\n\nREQ-1: поиск тикетов по статусу.\n\n## Открытые вопросы\n\nУточнить авторизацию.'},checks:[{name:'Документ',status:'passed'}]});
      if(action==='refresh'&&stage===0)state.stages[stage].files={'00_brief_explanation.md':'## Что сделать\nСделать поиск тикетов.\n\n## Пример\nДопустим, нужен открытый тикет.'};
      if(action==='refresh'&&stage===2)state.stages[stage].files={'02_competitors.md':'# Конкуренты','02_competitors.json':JSON.stringify({competitors:[{id:'one',name:'Example',url:'https://example.com',status:'verified',comparison:[{criterion:'Поиск',ours:'Требуется',theirs:'Фильтры'}],sources:[{url:'https://example.com/features',title:'Функции',checkedAt:'2026-11-06'}]}]})};
      if(action==='approve'){state.stages[stage].status='approved';if(stage===2)state.competitorPreferences=body.note}

    }
    await route.fulfill({json:{ok:true,result:state}});
  });
  await page.route('**/api/agents/approvals',route=>route.fulfill({json:{ok:true,result:[]}}));
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear()});await page.reload();
  await page.locator('#first-text').fill('Создать систему тикетов с поиском по статусу и обработкой неверного запроса.');
  await page.locator('.pixel-start').click();await page.locator('[data-real-stage]').first().waitFor();
  assert(submitted.includes('систему тикетов'),'Исходный текст не отправлен API');
  assert((await page.locator('.stage-tile-number').allTextContents()).join(' ')==='01 02 03 04 05 06 07 08','На доске должны быть восемь этапов');
  assert(await page.locator('.stage-tile-name').count()===8,'Нет подписей этапов');
  assert(await page.locator('.board-content').isHidden(),'Содержание этапа показано до выбора');
  await page.locator('.mascot-area.mascot-ready').waitFor();
  await page.locator('[data-real-stage="0"]').click();
  await page.locator('.analysis-thinking').waitFor();
  assert(await page.locator('.board').evaluate(e=>e.classList.contains('expanded')),'Этап не открылся на весь экран');
  assert(await page.locator('#first-stage').evaluate(e=>e.classList.contains('stage-open')),'Маскот не закреплён в открытом этапе');
  await page.locator('.brief-explanation').getByRole('heading',{name:'Пример'}).waitFor();
  const navigation=page.getByRole('navigation',{name:'Переключение этапов'});
  assert(await navigation.getByRole('button').count()===8,'В полноэкранном режиме нет всех этапов');
  await navigation.getByRole('button',{name:/Разбор аналогов/}).click();
  await page.locator('.stage-locked').waitFor();
  await navigation.getByRole('button',{name:/Анализ задания/}).click();
  await page.locator('[data-real-run]').click();
  assert(await navigation.getByRole('button',{name:/Анализ задания/}).getAttribute('aria-current')==='step','Активный этап не отмечен');
  assert(await page.locator('.stage-grid').isHidden(),'Переключение вернуло к доске');
  await page.locator('[data-real-file]').first().waitFor();
  await page.locator('[data-real-file]').first().click();
  assert((await page.locator('[data-real-document]').innerText()).includes('REQ-1'),'Документ API не отображён');
  await page.locator('[data-analysis-close]').click();
  await page.locator('.analysis-file').waitFor();
  assert(await page.locator('.board').evaluate(e=>e.classList.contains('expanded')),'Возврат из документа закрыл этап');
  await page.reload();
  await page.locator('.stage-grid').waitFor();
  assert(await page.locator('.board-content').isHidden(),'Перезагрузка открыла этап вместо доски');
  await page.locator('[data-real-stage="1"]').click();
  await page.locator('[data-real-approve]').click();await page.waitForFunction(()=>document.querySelector('.board-bar h2')?.textContent==='Разбор аналогов');await page.locator('[data-real-run]').waitFor();
  assert(state.stages[1].status==='approved','Нет явного утверждения');
  await page.locator('[data-real-run]').click();await page.locator('.analysis-thinking').waitFor();
  await page.locator('[data-begin-idea]').waitFor();
  assert(await page.locator('.competitor-card').count()===1,'Нет карточки аналога');
  const sources=page.locator('.competitor-sources a');
  assert(await sources.isHidden(),'Технические детали открыты сразу');
  await page.getByText('Сравнение и источники',{exact:true}).click();
  assert(await sources.getAttribute('href')==='https://example.com/features','Нет ссылки на источник');
  await page.getByText('Сравнение и источники',{exact:true}).click();
  await page.screenshot({path:'output/browser/competitors-review.png'});
  await page.setViewportSize({width:390,height:844});
  assert(await page.locator('.board-content').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Сравнение выходит за экран телефона');
  await page.setViewportSize({width:1280,height:900});
  await page.locator('[data-competitor-choice="one"]').selectOption('adapt');
  await page.getByText('Добавить комментарий',{exact:true}).click();
  await page.locator('[data-competitor-note="one"]').fill('Адаптировать фильтры');
  // Continue even when source checks fail, without declaring those sources verified.
  state.stages[2].status='failed';
  await page.evaluate(()=>window.makoraPreparation.open(2));
  await page.locator('[data-begin-idea]').click();
  await page.getByRole('heading',{name:'Разработка идеи',exact:true}).waitFor();
  const openChat=page.getByRole('button',{name:'Открыть чат идеи в Codex ↗'});
  await openChat.waitFor();
  await Promise.all([
    page.waitForResponse(r=>new URL(r.url()).pathname==='/api/preparation/3/open-codex'),
    openChat.click(),
  ]);
  assert(chatOpens===1,'Кнопка не открыла существующий чат через API');
  assert(ideaRequests===1,'Создан повторный чат идеи');
  assert(state.stages[2].status==='continued','Переход требует успешной проверки');
  assert(state.competitorDecisions.one.comment.includes('фильтры'),'Решение по аналогу не передано');
  assert((await page.locator('.idea-handoff').innerText()).includes('Расскажите'),'Нет приглашения сформулировать идею');

  await page.locator('.stage-board-back').click();
  await page.locator('[data-real-stage="1"]').click();await page.locator('[data-analysis-edit]').click();
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
        children:['.board-inner','.board-content'].every(selector=>{
          const r=board.querySelector(selector).getBoundingClientRect();
          return r.left>=frame.left&&r.right<=frame.right+1&&r.top>=frame.top&&r.bottom<=frame.bottom+1;
        })};
    });
    assert(bounds.inside&&bounds.children,'Содержимое выходит за доску: '+JSON.stringify(viewport));
  }
  await page.locator('.stage-board-back').click();
  await page.locator('.stage-grid').waitFor();
  await page.goto(new URL('/?new=1',page.url()).href,{waitUntil:'domcontentloaded'});
  await page.locator('.stage-grid').waitFor();
  assert(await page.locator('.first-form').isHidden(),'Параметр URL сбросил текущий проект');
  assert(errors.length===0,errors.join('; '));
  return {provider:'fake-http',briefSubmitted:true,realArtifactsRendered:true,approval:true,invalidation:true,reload:true,errors};
}

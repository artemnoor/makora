async page => {
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  let state={workflowVersion:3,stageOrder:[0,2,3,5,6,4,7],projectId:'v3',storageRoot:'C:/project',brief:'',stages:{}};
  let planSaved=false;
  await page.route('**/api/preparation**',async route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    const body=route.request().method()==='POST'?route.request().postDataJSON():{};
    if(path==='/api/preparation/idea/start'){
      state.stages[2].status='continued';
      state.stages[3]={status:'awaiting_idea',interactionMode:'user_idea',threadId:'01a1b6b4-a4f1-7893-8945-c4076fe43907',files:{}};
    }
    if(path==='/api/preparation/planning/execution'){
      assert(body.execution.laboratories.length===1,'Лаборатория не сохранена');
      assert(body.tasks.find(t=>t.id==='JOIN').dependsOn.includes('FEATURE'),'Не сохранена связь подключения');
      state.stages[4].files['03_tasks.json']=JSON.stringify({tasks:body.tasks});
      state.stages[4].files['03_execution.json']=JSON.stringify(body.execution);state.stages[4].status='review';planSaved=true;
    }
    const match=path.match(/\/([0-5])\/(start|refresh|approve)$/);
    if(match){const stage=Number(match[1]),action=match[2];
      if(action==='start'){
        if(body.brief)state.brief=body.brief;
        assert(stage!==1,'Запущен старый анализ задания');
        state.stages[stage]={status:'running',files:{}};
      }
      if(action==='refresh'&&stage===0)state.stages[0]={status:'review',caseConstraints:[],files:{'00_brief_explanation.md':'## Что сделать\nКаталог событий.\n\n## Пример\nДопустим, студент ищет встречу.'}};
      if(action==='refresh'&&stage===2)state.stages[2]={status:'review',files:{'02_competitors.md':'# Аналоги','02_competitors.json':JSON.stringify({competitors:[{id:'one',name:'Пример',summary:'Каталог событий',url:'https://example.com',comparison:[],sources:[]}]})}};
      if(action==='approve')state.stages[stage].status='approved';
    }
    await route.fulfill({json:{ok:true,result:state}});
  });
  await page.route('**/api/agents/approvals',route=>route.fulfill({json:{ok:true,result:[]}}));
  await page.evaluate(()=>{localStorage.clear();sessionStorage.clear()});await page.reload();
  await page.locator('#first-text').fill('Создать каталог студенческих событий с поиском.');
  await page.locator('.pixel-start').click();await page.locator('.stage-grid').waitFor();
  assert((await page.locator('.stage-tile-name').allTextContents()).join('|')==='Простое объяснение|Поиск аналогов|Брейншторм|Мок-данные|Пакет для агента|Планирование|Разработка агентами','Неверный порядок семи этапов');
  assert((await page.locator('.stage-tile-number').allTextContents()).join(' ')==='01 02 03 04 05 06 07','Неверная нумерация');
  await page.screenshot({path:'output/browser/workflow-v3-board.png'});
  await page.locator('[data-real-stage="0"]').click();await page.locator('.brief-explanation').waitFor();
  assert(await page.locator('.case-constraints').count()===0,'Придуман блок ограничений');
  await page.locator('[data-real-approve]').click();
  await page.getByRole('heading',{name:'Поиск аналогов',exact:true}).waitFor();
  await page.locator('[data-real-run]').click();await page.locator('[data-begin-idea]').waitFor();
  await page.locator('[data-begin-idea]').click();
  await page.getByRole('heading',{name:'Брейншторм',exact:true}).waitFor();
  assert((await page.locator('.idea-handoff').innerText()).includes('готово'),'Нет объяснения, как завершить сбор идей');
  assert((await page.locator('.idea-handoff').innerText()).includes('подтвердите'),'Нет отдельного подтверждения версий');
  assert(await page.locator('[data-real-file]').count()===0,'Черновики опубликованы до согласования');
  state.stages[3]={status:'stale',interactionMode:'user_idea',files:{'02_solution_concept.md':'Old idea'}};
  await page.evaluate(snapshot=>{window.makoraPreparation.mount(snapshot);window.makoraPreparation.open(3)},state);
  await page.locator('[data-create-idea]').waitFor();
  assert(await page.locator('[data-real-file]').count()===0,'Старая идея показана как результат нового брейншторма');
  for(const stage of [0,2,3,5])state.stages[stage]={status:'approved',files:{}};
  state.stages[5].files={'mocks/fixtures/data.json':'{}'};
  state.returnedProject={status:'prepared'};
  const task=(id,deps,paths)=>({id,title:id,goal:'Реализовать',acceptance:'Проверить',dependsOn:deps,allowedPaths:paths,contracts:[],mocks:[],builderPrompt:'Реализуй',testPrompt:'Проверь',reviewerPrompt:'Проверь'});
  state.stages[4]={status:'review',files:{'03_tasks.json':JSON.stringify({tasks:[task('BASE',[],['src/shell.js']),task('FEATURE',['BASE'],['src/feature.js']),task('JOIN',['BASE'],['src/join.js'])]}),'03_execution.json':JSON.stringify({skeletonTaskId:'BASE',laboratories:[]})}};
  await page.evaluate(snapshot=>{window.makoraPreparation.mount(snapshot);window.makoraPreparation.open(4)},state);
  await page.locator('.execution-editor').waitFor();
  await page.getByText('Добавить лабораторию',{exact:true}).click();
  await page.locator('[data-lab-name]').fill('Поиск похожих событий');
  await page.locator('[data-lab-task]').selectOption('FEATURE');await page.locator('[data-lab-join]').selectOption('JOIN');
  await page.locator('[data-add-lab]').click();
  assert(await page.locator('.laboratory-card').count()===1,'Лаборатория не появилась в схеме');
  await page.locator('[data-save-plan]').click();await page.waitForTimeout(200);
  assert(planSaved,'Изменённая схема не отправлена контроллеру');
  await page.setViewportSize({width:390,height:844});
  assert(await page.locator('.board-content').evaluate(e=>e.scrollWidth<=e.clientWidth+1),'Редактор схемы выходит за ширину телефона');
  await page.screenshot({path:'output/browser/workflow-v3-planning-mobile.png'});
  await page.setViewportSize({width:1280,height:900});
  await page.locator('.stage-board-back').click();await page.waitForTimeout(700);
  await page.screenshot({path:'output/browser/workflow-v3-board.png'});
  assert(errors.length===0,errors.join('\n'));
  return {order:true,noInventedConstraints:true,brainstormHandoff:true,editableLaboratories:true,noPageErrors:true};
}

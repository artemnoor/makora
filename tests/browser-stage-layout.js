async page=>{
 const assert=(v,m)=>{if(!v)throw Error(m)},errors=[];page.on('pageerror',e=>errors.push(e.message));
 const state={projectId:'layout-all-stages',storageRoot:'C:/temporary-layout-project',lastStage:3,brief:'Проверочный проект',prototype:{status:'approved',commit:'abc123'},stages:{}};
 const documents={1:{'01_case_analysis.md':'# Требования'},3:{'02_research.md':'# Исследование','02_solution_concept.md':'# Концепция','02_user_flow.mmd':'flowchart TD\nA-->B'},4:{'03_architecture.md':'# Архитектура','03_contracts/openapi.yaml':'openapi: 3.1.0','03_tasks.json':'[{"id":"T01"}]'},5:{'04_validation_report.md':'# Проверка моков','mocks/fixtures/spaces.json':'[{"id":"space-1"}]','mocks/scenarios.json':'{"scenarios":[]}'}};
 for(let i=1;i<=5;i++)state.stages[i]={status:'approved',files:documents[i]||{},checks:[{name:'Проверка структуры',status:'passed'}]};
 let submitted,planningRequest,sessions=[],approvedStep=null;
 await page.route('**/api/preparation**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/package'))return route.fulfill({json:{ok:true,result:{prompt:'Создай приложение на mocks/fixtures/',files:[{path:'PROMPT.md'},{path:'mocks/fixtures/spaces.json'}],documents:{'PROMPT.md':'Создай приложение на mocks/fixtures/','mocks/fixtures/spaces.json':'[]'}}}});
  if(path.endsWith('/development'))return route.fulfill({json:{ok:true,result:{projectRoot:'C:/temporary-layout-project',digest:'layout-test',brief:state.brief,context:'Документы проекта',artifactPaths:[]}}});
  if(path.endsWith('/4/approve')){state.stages[4].status='approved';approvedStep=4}
  if(path.endsWith('/start'))submitted={path,body:route.request().postDataJSON()};
  return route.fulfill({json:{ok:true,result:state}});
 });
 const run={id:'layout-run',projectRoot:'C:/temporary-layout-project',baseCommit:'abc123456789',plannerSessionId:'plan-session',mahoragaAutopilot:{enabled:false,status:'manual'},tasks:[{id:'T01',title:'Первый блок',goal:'Реализовать контракт',status:'pending',dependsOn:[]}]};
 await page.route('**/api/agents/**',route=>{const path=new URL(route.request().url()).pathname;let result=[];if(path.endsWith('/plans')&&route.request().method()==='POST'){planningRequest=route.request().postDataJSON();result={id:'new-plan'}}else if(path.endsWith('/token'))result={token:'layout-token'};else if(path.endsWith('/status'))result={connected:true,modelAvailable:true,allowedRoots:['C:/temporary-layout-project']};else if(path.endsWith('/state'))result={runs:[run],sessions,events:[]};return route.fulfill({json:{ok:true,result}})});
 await page.evaluate(()=>{localStorage.clear();localStorage.setItem('makora.real-stage','2');localStorage.setItem('makora.real-development-digest','layout-test');localStorage.setItem('makora.real-agents-base','abc123');localStorage.setItem('makora.agent-real-run','layout-run')});await page.goto(new URL('/',page.url()).href);
 for(const step of [3,4,5]){
  await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.analysis-file').waitFor();
  assert(await page.locator('.board-content').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'Компактная доска прокручивается: '+step);
  await page.locator('.analysis-file').click();await page.locator('.artifact-files').waitFor();
  assert(await page.locator('.artifact-files [data-real-file]').count()===Object.keys(documents[step]).length,'Не все файлы доступны');
  const json=Object.keys(documents[step]).find(p=>p.endsWith('.json'));if(json){await page.locator(`.artifact-files [data-real-file="${json}"]`).click();assert((await page.locator('.analysis-paper').innerText()).includes(documents[step][json]),'JSON не отображён')}
  await page.locator('[data-analysis-close]').click();await page.locator('[data-analysis-edit]').click();await page.locator('.analysis-chat textarea').fill('Правка этапа '+step);await page.locator('.analysis-chat [type=submit]').click();await page.locator('.analysis-chat').waitFor({state:'detached'});
  assert(submitted.path.endsWith('/'+step+'/start')&&submitted.body.feedback==='Правка этапа '+step,'Уточнение ушло в неверный этап');
 }
 for(const step of [3,4,5]){
  state.stages[step].status='running';await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.analysis-wheel').waitFor();assert(await page.locator('.analysis-wheel').evaluate(e=>getComputedStyle(e).animationName==='analysis-resistance'),'Нет вращения на этапе '+step);state.stages[step].status='approved';await page.evaluate(n=>window.makoraPreparation.open(n),step);
 }
 await page.locator('[data-real-stage="6"]').click();await page.locator('[data-handoff-open]').waitFor();assert(await page.locator('[data-agent-autopilot]').count()===0,'Этап 5 запускает внутренних агентов');await page.locator('[data-handoff-open]').click();await page.locator('[data-handoff-reader] a[download]').first().waitFor();await page.locator('[data-handoff-back]').click();
 for(const step of [7]){
  await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.runtime-summary').waitFor();
  assert(await page.locator('.board-content').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'Компактная разработка прокручивается: '+step);
  assert(await page.locator('.runtime-detail').isHidden(),'Детали разработки не скрыты');
  await page.locator('[data-runtime-open]').click();await page.locator('.runtime-detail').waitFor();
  assert(await page.locator('.agent-board-overview .agent-board-actions .rp-primary').isVisible(),'Управление агентами потеряно');
  if(step===7)await page.screenshot({path:'output/browser/all-stages-expanded-runtime.png'});
  await page.locator('.runtime-back').click();assert(await page.locator('.runtime-summary').isVisible(),'Не вернулись к краткому виду');
 }
 for(const step of [7]){sessions=[{id:'active-builder',runId:run.id,taskId:'T01',role:'builder',status:'running',threadId:'fake-thread'}];await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.runtime-summary .analysis-wheel').waitFor();assert(await page.locator('.board-content').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'Ожидание не вмещается в доску');sessions=[];}
 await page.screenshot({path:'output/browser/all-stages-runtime.png'});
 await page.evaluate(()=>window.makoraRealAgents.selectRun('__new__'));await page.locator('[data-real-stage="7"]').click();await page.locator('.runtime-summary').waitFor();
 await page.locator('.runtime-summary button').filter({hasText:'Уточнить задание'}).click();await page.locator('.analysis-chat textarea').fill('Учесть офлайн режим');await page.locator('.analysis-chat [type=submit]').click();await page.waitForTimeout(200);assert(planningRequest?.brief?.includes('Учесть офлайн режим'),'Уточнение не передано планировщику');
 state.stages[4].status='review';await page.evaluate(()=>window.makoraPreparation.open(4));await page.locator('.analysis-file').click();await page.locator('[data-reader-approve]').waitFor();const approvalBounds=await page.locator('.artifact-approval').boundingBox();assert(approvalBounds.y>=0&&approvalBounds.y+approvalBounds.height<=page.viewportSize().height+1,'Подтверждение вне экрана');await page.screenshot({path:'output/browser/stage3-approve.png'});await page.locator('[data-reader-approve]').click();await page.locator('[data-real-stage="5"].active').waitFor();assert(approvedStep===4,'Не утверждён полный третий этап');
 assert(errors.length===0,errors.join('; '));return {provider:'fake-http',stages:[2,3,4,5,6,7],files:true,feedbackRouting:true,runtimeControls:true,noPageErrors:true};
}

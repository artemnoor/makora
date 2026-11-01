async page=>{
 const assert=(v,m)=>{if(!v)throw Error(m)},errors=[];page.on('pageerror',e=>errors.push(e.message));
 const state={projectId:'layout-all-stages',brief:'Проверочный проект',prototype:{status:'approved',commit:'abc123'},stages:{}};
 const documents={1:{'01_case_analysis.md':'# Требования'},2:{'02_research.md':'# Исследование','02_solution_concept.md':'# Концепция','02_user_flow.mmd':'flowchart TD\nA-->B'},3:{'03_architecture.md':'# Архитектура','03_contracts/openapi.yaml':'openapi: 3.1.0','03_tasks.json':'[{"id":"T01"}]'},4:{'04_validation_report.md':'# Проверка моков','mocks/fixtures/spaces.json':'[{"id":"space-1"}]','mocks/scenarios.json':'{"scenarios":[]}'}};
 for(let i=1;i<=4;i++)state.stages[i]={status:'approved',files:documents[i],checks:[{name:'Проверка структуры',status:'passed'}]};
 let submitted,planningRequest;
 await page.route('**/api/preparation**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/development'))return route.fulfill({json:{ok:true,result:{projectRoot:'C:/temporary-layout-project',digest:'layout-test',brief:state.brief,context:'Документы проекта',artifactPaths:[]}}});
  if(path.endsWith('/start'))submitted={path,body:route.request().postDataJSON()};
  return route.fulfill({json:{ok:true,result:state}});
 });
 const run={id:'layout-run',projectRoot:'C:/temporary-layout-project',baseCommit:'abc123456789',plannerSessionId:'plan-session',mahoragaAutopilot:{enabled:false,status:'manual'},tasks:[{id:'T01',title:'Первый блок',goal:'Реализовать контракт',status:'pending',dependsOn:[]}]};
 await page.route('**/api/agents/**',route=>{const path=new URL(route.request().url()).pathname;let result=[];if(path.endsWith('/plans')&&route.request().method()==='POST'){planningRequest=route.request().postDataJSON();result={id:'new-plan'}}else if(path.endsWith('/token'))result={token:'layout-token'};else if(path.endsWith('/status'))result={connected:true,modelAvailable:true,allowedRoots:['C:/temporary-layout-project']};else if(path.endsWith('/state'))result={runs:[run],sessions:[],events:[]};return route.fulfill({json:{ok:true,result}})});
 await page.evaluate(()=>{localStorage.clear();localStorage.setItem('makora.real-stage','2');localStorage.setItem('makora.real-development-digest','layout-test');localStorage.setItem('makora.real-stage6-base','abc123');localStorage.setItem('makora.agent-real-run','layout-run')});await page.goto(new URL('/',page.url()).href);
 for(const step of [2,3,4]){
  await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.analysis-file').waitFor();
  assert(await page.locator('.board-content').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'Компактная доска прокручивается: '+step);
  await page.locator('.analysis-file').click();await page.locator('.artifact-files').waitFor();
  assert(await page.locator('.artifact-files [data-real-file]').count()===Object.keys(documents[step]).length,'Не все файлы доступны');
  const json=Object.keys(documents[step]).find(p=>p.endsWith('.json'));if(json){await page.locator(`.artifact-files [data-real-file="${json}"]`).click();assert((await page.locator('.analysis-paper').innerText()).includes(documents[step][json]),'JSON не отображён')}
  await page.locator('[data-analysis-close]').click();await page.locator('[data-analysis-edit]').click();await page.locator('.analysis-chat textarea').fill('Правка этапа '+step);await page.locator('.analysis-chat [type=submit]').click();await page.locator('.analysis-chat').waitFor({state:'detached'});
  assert(submitted.path.endsWith('/'+step+'/start')&&submitted.body.feedback==='Правка этапа '+step,'Уточнение ушло в неверный этап');
 }
 for(const step of [5,6]){
  await page.locator(`[data-real-stage="${step}"]`).click();await page.locator('.runtime-summary').waitFor();
  assert(await page.locator('.board-content').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'Компактная разработка прокручивается: '+step);
  assert(await page.locator('.runtime-detail').isHidden(),'Детали разработки не скрыты');
  await page.locator('[data-runtime-open]').click();await page.locator('.runtime-detail').waitFor();
  assert(await page.locator('[data-agent-autopilot]').isVisible(),'Управление агентами потеряно');
  if(step===6)await page.screenshot({path:'C:/m/all-stages-expanded-runtime.png'});
  await page.locator('.runtime-back').click();assert(await page.locator('.runtime-summary').isVisible(),'Не вернулись к краткому виду');
 }
 await page.screenshot({path:'C:/m/all-stages-runtime.png'});
 await page.evaluate(()=>window.makoraRealAgents.selectRun('__new__'));await page.locator('[data-real-stage="5"]').click();await page.locator('.runtime-summary').waitFor();
 await page.locator('.runtime-summary button').filter({hasText:'Уточнить задание'}).click();await page.locator('.analysis-chat textarea').fill('Учесть офлайн режим');await page.locator('.analysis-chat [type=submit]').click();await page.waitForTimeout(200);assert(planningRequest?.brief?.includes('Учесть офлайн режим'),'Уточнение не передано планировщику');
 assert(errors.length===0,errors.join('; '));return {provider:'fake-http',stages:[2,3,4,5,6],files:true,feedbackRouting:true,runtimeControls:true,noPageErrors:true};
}

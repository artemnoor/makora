async page => {
  const assert = (value, message) => { if (!value) throw Error(message); };
  const state = {projectId:'one-project', storageRoot:'C:/Projects/Current', brief:'', lastStage:1, stages:{}};
  let uploaded, launches=0, opened=0;
  await page.route('**/api/preparation**', async route => {
    const request=route.request(), path=new URL(request.url()).pathname;
    if(path.endsWith('/folder/select') || path.includes('/projects/create') || path.endsWith('/chat')) throw Error('Removed workflow was called');
    if(path.endsWith('/folder/open')) { opened++; return route.fulfill({json:{ok:true,result:{opened:true}}}); }
    if(path.endsWith('/source')) { uploaded=request.postDataBuffer().toString('utf8'); return route.fulfill({json:{ok:true,result:{text:uploaded}}}); }
    if(path.endsWith('/0/start')) { launches++; state.brief=request.postDataJSON().brief; state.stages['0']={status:'review',files:{'00_brief_explanation.md':'## Пример\nКороткое объяснение.'},checks:[]}; }
    return route.fulfill({json:{ok:true,result:state}});
  });
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('[data-choose-project-folder]')?.dataset.folderSelected==='true');
  assert(await page.locator('[data-choose-project-folder]').isHidden(), 'Folder picker should be hidden');
  assert(await page.locator('.first-new-task,.project-start-tabs,.makora-chat-toggle,.project-chat').count()===0,'Removed project/chat controls are still mounted');
  const original='# Requirement\nA notes API with search and tests.\n';
  await page.locator('.pixel-drop input').setInputFiles({name:'requirements.md',mimeType:'text/markdown',buffer:Buffer.from(original)});
  await page.locator('.pixel-start').click();
  await page.locator('.stage-grid').waitFor();
  assert(uploaded===original && launches===1,'Original input was not uploaded exactly once');
  const opening=page.waitForResponse(response=>new URL(response.url()).pathname.endsWith('/folder/open'));
  await page.locator('.first-open-folder').click();
  await opening;
  assert(opened===1,'Project folder did not open');
  await page.reload();
  await page.locator('.stage-grid').waitFor();
  assert(await page.locator('.first-form').isHidden(),'Reload returned to attachment screen');
  assert(launches===1,'Reload launched the stage again');
  const roles=Object.fromEntries(['preparation','project_chat','mahoraga_planner','mahoraga_orchestrator','mahoraga','builder','test_designer','reviewer']
    .map(role=>[role,{model:'base',reasoningEffort:null}]));
  let settingsPayload;
  await page.route('**/api/preparation/agent-settings',route=>{
    if(route.request().method()==='POST'){
      settingsPayload=route.request().postDataJSON();
      Object.assign(roles,settingsPayload.roles);
    }
    return route.fulfill({json:{ok:true,result:{projectId:state.projectId,storageRoot:state.storageRoot,roles,
      models:[{model:'base'},{model:'alternate',supportedReasoningEfforts:[{reasoningEffort:'high'}]}]}}});
  });
  await page.locator('[data-open-agent-settings]').click();
  const dialog=page.getByRole('dialog',{name:'Модели и рассуждения'});
  await dialog.locator('[data-role="mahoraga_planner"] summary').click();
  const planner=dialog.locator('[data-role="mahoraga_planner"]');
  await planner.locator('[data-model]').selectOption('alternate');
  await planner.locator('[data-effort]').selectOption('high');
  await dialog.locator('[data-role="mahoraga_orchestrator"] summary').click();
  assert(await dialog.locator('[data-role="mahoraga_orchestrator"] [data-model]').inputValue()==='base','Planner changes affected the coordinator');
  await dialog.locator('[data-settings-save]').click();
  await dialog.getByText('Настройки сохранены',{exact:true}).waitFor();
  assert(Object.keys(settingsPayload.roles).join()==='mahoraga_planner','Save overwrote untouched roles');
  assert(settingsPayload.roles.mahoraga_planner.reasoningEffort==='high','Selected reasoning was not saved');
  return {singleProject:true,noSiteChat:true,originalUpload:true,reload:true,independentRoleSettings:true};
}

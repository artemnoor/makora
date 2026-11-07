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
  return {singleProject:true,noSiteChat:true,originalUpload:true,reload:true};
}

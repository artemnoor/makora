async page=>{
 const assert=(v,m)=>{if(!v)throw Error(m)};let chosen=false,cancel=true,opened=0,uploaded=null;
 let state={brief:'',stages:{}};
 await page.route('**/api/preparation**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  if(path.endsWith('/folder/select')){if(cancel){cancel=false;return route.fulfill({json:{ok:true,result:{cancelled:true}}})}chosen=true;state.storageRoot='C:/Projects/My Makora';return route.fulfill({json:{ok:true,result:{cancelled:false,path:state.storageRoot}}})}
  if(path.endsWith('/folder/open')){opened++;return route.fulfill({json:{ok:true,result:{opened:true,path:state.storageRoot}}})}
  if(path.endsWith('/source')){uploaded={name:new URL(request.url()).searchParams.get('name'),bytes:request.postDataBuffer().toString('utf8')};return route.fulfill({json:{ok:true,result:{text:uploaded.bytes}}})}
  if(path.endsWith('/1/start'))state={...state,brief:request.postDataJSON().brief,stages:{1:{status:'review',files:{'01_case_analysis.md':'# Подготовленный документ'},checks:[]}}};
  return route.fulfill({json:{ok:true,result:state}});
 });
 await page.route('**/api/agents/approvals',r=>r.fulfill({json:{ok:true,result:[]}}));
 await page.evaluate(()=>localStorage.clear());await page.goto(new URL('/?new=1',page.url()).href);
 await page.locator('#first-text').fill('Достаточно подробное условие тестового проекта');
 assert(await page.locator('.pixel-start').isDisabled(),'Можно начать без папки');
 await page.locator('[data-choose-project-folder]').click();assert(await page.locator('.pixel-start').isDisabled(),'Отмена выбора разрешила анализ');
 await page.locator('[data-choose-project-folder]').click();await page.waitForFunction(()=>!document.querySelector('.pixel-start').disabled);assert(chosen&&!await page.locator('.pixel-start').isDisabled(),'Выбор папки не разблокировал анализ');
 const original='# Исходный файл\nAPI заметок с поиском и тестами.\n';
 await page.locator('.pixel-drop input').setInputFiles({name:'requirements.md',mimeType:'text/markdown',buffer:Buffer.from(original)});
 await page.locator('.pixel-start').click();await page.locator('.analysis-file').waitFor();
 assert(uploaded?.name==='requirements.md'&&uploaded.bytes===original,'Исходный файл не отправлен без изменений');
 const opening=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/folder/open'));await page.locator('.first-open-folder').click();await opening;assert(opened===1,'Папка не открывается через API');
 await page.reload();await page.locator('.analysis-file').waitFor();assert((await page.locator('.first-open-folder').getAttribute('title')).includes('C:/Projects/My Makora'),'Папка не восстановилась');
 return {provider:'fake-http',requiresFolder:true,cancel:true,originalBytes:true,openFolder:true,reload:true};
}

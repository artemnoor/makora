async page => {
  // HTTP fixtures exercise the upload UI without changing a user's project.
  const assert=(ok,message)=>{if(!ok)throw Error(message)};
  let result=null,uploads=0,reject=false;
  const state={brief:'Test site',stages:{'4':{status:'approved',files:{'mocks/fixtures/data.json':'[]'}}}};
  await page.route('**/api/preparation**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/api/preparation/package')return route.fulfill({json:{ok:true,result:{prompt:'Create a website and return ZIP.',files:[{path:'PROMPT.md'}],documents:{'PROMPT.md':'Create a website and return ZIP.'},returnedProject:result}}});
    if(url.pathname==='/api/preparation/result/continue'){
      result={...result,status:'prepared',commit:'imported-site'};state.returnedProject=result;
      return route.fulfill({json:{ok:true,result:state}});
    }
    if(url.pathname==='/api/preparation/development')return route.fulfill({json:{ok:true,result:{projectRoot:'C:/test/imported-site',brief:'Uploaded site',context:'',digest:'site-digest'}}});
    if(url.pathname==='/api/preparation/result'){
      if(reject)return route.fulfill({status:400,json:{ok:false,error:{message:'ZIP повреждён или не читается.'}}});
      assert(route.request().headers()['content-type']==='application/zip','Upload is not ZIP');
      assert(route.request().postDataBuffer().length>0,'Empty upload');
      uploads++;
      result={status:'received',name:url.searchParams.get('name'),fileCount:2,files:['index.html','mocks/fixtures/data.json'],mocksStatus:'passed',newMocks:[]};
      return route.fulfill({json:{ok:true,result}});
    }
    return route.fulfill({json:{ok:true,result:state}});
  });
  await page.reload();
  await page.locator('[data-real-stage="1"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-result-file]'));
  await page.locator('[data-real-stage="5"]').click();
  await page.locator('[data-result-file]').waitFor({state:'attached'});
  await page.locator('[data-result-file]').setInputFiles({name:'site.txt',mimeType:'text/plain',buffer:Buffer.from('invalid')});
  await page.getByText('Выберите непустой ZIP-архив размером до 100 МБ.').waitFor();
  assert(uploads===0,'Invalid filename uploaded');
  await page.locator('[data-result-file]').setInputFiles({name:'site.zip',mimeType:'application/zip',buffer:Buffer.from('mock ZIP bytes')});
  await page.getByText('✓ ZIP проекта сохранён').waitFor();
  assert(await page.locator('[data-result-continue]').isVisible(),'No continuation button after upload');
  assert(await page.locator('[data-result-replace]').isVisible(),'No replace ZIP button');
  assert(uploads===1,'ZIP was not sent');
  await page.reload();
  await page.getByText('✓ ZIP проекта сохранён').waitFor();
  assert(await page.locator('[data-result-summary] a').getAttribute('href')==='/api/preparation/result','No download link');
  reject=true;
  await page.locator('[data-result-file]').setInputFiles({name:'bad.zip',mimeType:'application/zip',buffer:Buffer.from('bad')});
  await page.getByText('ZIP повреждён или не читается.').waitFor();
  assert(await page.getByText('✓ ZIP проекта сохранён').isVisible(),'Previous result lost after error');
  for(const width of [390,1280]){
    await page.setViewportSize({width,height:844});
    const size=await page.locator('.board-content').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
    assert(size.scroll<=size.width+1,'Upload overflows board at '+width);
  }
  await page.evaluate(()=>{window.makoraRealAgents={selectRun:()=>{},render:async ctx=>{if(ctx.project.projectRoot!=='C:/test/imported-site')throw Error('Wrong project');ctx.content.innerHTML='<p data-test-development>Uploaded site ready for agents</p>'}}});
  await page.locator('[data-result-continue]').click();
  await page.locator('[data-test-development]').waitFor();
  assert(await page.locator('[data-real-stage="6"]').isEnabled(),'Stage six locked');
  return {upload:true,reload:true,errorPreservesResult:true,responsive:true,continueToAgents:true,provider:'fake-http'};
}

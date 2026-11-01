async page => {
  // Opt-in real Luna test. Reserved port protects the user's normal workspace.
  if(new URL(page.url()).port!=='8780')throw Error('Запускай только на отдельном E2E сервере :8780');
  const get=()=>page.evaluate(async()=>{const response=await fetch('/api/preparation');const body=await response.json();if(!response.ok)throw Error(body.error.message);return body.result});
  async function wait(predicate,timeout){const until=Date.now()+timeout;while(Date.now()<until){const value=await get();if(predicate(value))return value;await page.waitForTimeout(1500)}throw Error('Истекло время наблюдения за конкретной сессией; повторная отправка не выполнялась')}
  let state=await get();
  if(!state.brief){
    await page.locator('#first-text').fill('Локальный API заметок: создание, список, поиск по тексту и тегам. JSON-хранилище. Пустые ответы и неверные запросы. Исполняемые тесты. 24 часа, команда 2 человека. Сдача Git, README и демо.');
    await page.locator('.pixel-start').click();
  }
  await page.locator('[data-real-stage]').first().waitFor({timeout:240000});
  for(let stage=1;stage<=4;stage++){
    await page.locator('[data-real-stage]').nth(stage-1).click();
    state=await get();
    if(state.stages[stage]?.status==='approved')continue;
    if(!['running','review','unconfirmed'].includes(state.stages[stage]?.status)){
      const previous=state.stages[stage]?.sessionId;
      await page.locator('[data-real-run]').click();
      await wait(s=>!!s.stages[stage]?.sessionId&&s.stages[stage].sessionId!==previous,240000);
    }
    await wait(s=>['review','approved','failed'].includes(s.stages[stage]?.status),600000);
    state=await get();
    if(state.stages[stage].status!=='review'&&state.stages[stage].status!=='approved')throw Error(JSON.stringify(state.stages[stage]));
    if(stage<4&&state.stages[stage].status==='review'){
      await page.locator('[data-analysis-edit]').click();
      await page.locator('.analysis-chat textarea').fill('Для этого временного E2E принимаем предложенные рабочие допущения. Только локальный HTTP API и JSON-хранилище; поиск регистронезависимый. Остальные неизвестные не считать требованиями организатора.');
      await page.locator('[data-chat-close]').click();
      await page.locator('[data-real-approve]').click();
      await wait(s=>s.stages[stage]?.status==='approved',30000);
    }
  }
  state=await get();
  return Object.fromEntries(Object.entries(state.stages).map(([key,value])=>[key,{status:value.status,model:value.model,threadId:value.threadId,turnId:value.turnId,files:Object.keys(value.files||{}),checks:value.checks,error:value.error}]));
}

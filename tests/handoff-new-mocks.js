async page => {
  const assert=(value,message)=>{if(!value)throw new Error(message)};
  const start = async () => {
    const sourceExists=await page.evaluate(()=>window.makoraProject.source());
    if(sourceExists) await page.locator('.board-scene').waitFor({state:'visible'});
    else { await page.locator('#first-text').fill('Учебное условие'); await page.locator('.pixel-start').click(); }
    await page.locator('.capabilities-toggle').click();
    await page.locator('[data-example-open]').click();
  };
  await page.evaluate(()=>{localStorage.clear();localStorage.setItem('makora.prototype-handoff.v1',JSON.stringify({sentinel:'original'}))});
  await page.reload();
  await start();
  await page.waitForFunction(()=>document.querySelector('#prototype-prompt')?.value.includes('new_mocks/'));
  const prompt=await page.locator('#prototype-prompt').inputValue();
  assert(prompt.includes('mocks/') && prompt.includes('new_mocks/') && prompt.includes('не изменяй'), 'В промпте отсутствуют правила сохранения моков');
  for(const term of ['mocks/fixtures/','не подменяй','ошибки источника','prototype-report.json','passed','failed','not_run','не блокирует']) assert(prompt.includes(term), 'В промпте отсутствует '+term);
  await page.locator('[data-example-download]').waitFor({state:'visible'});
  const packageDownload=page.waitForEvent('download');
  await page.locator('[data-example-download]').click();
  await packageDownload;
  await page.locator('[data-example-sent]').click();
  await page.locator('.prototype-waiting').waitFor({state:'visible'});
  const malicious=await page.evaluate(()=>Array.from(fflate.zipSync({'../new_mocks/data.json':fflate.strToU8('{}')})));
  await page.locator('.prototype-drop input').setInputFiles({name:'unsafe.zip',mimeType:'application/zip',buffer:Buffer.from(malicious)});
  await page.locator('[data-receive]').click();
  await page.waitForFunction(()=>document.querySelector('.prototype-feedback')?.textContent.includes('небезопасный путь'));
  await page.locator('.prototype-drop input').setInputFiles({name:'broken.zip',mimeType:'application/zip',buffer:Buffer.from('not a zip')});
  await page.locator('[data-receive]').click();
  await page.waitForFunction(()=>document.querySelector('.prototype-feedback')?.textContent.includes('корректный архив'));
  const zipped=await page.evaluate(()=>Array.from(fflate.zipSync({'project/mocks/data.json':fflate.strToU8('{"value":1}'),'project/new_mocks/data.json':fflate.strToU8('{"value":2}')})));
  await page.locator('.prototype-drop input').setInputFiles({name:'result.zip',mimeType:'application/zip',buffer:Buffer.from(zipped)});
  await page.locator('[data-receive]').click();
  await page.locator('#mock-reason').waitFor({state:'visible'});
  assert((await page.locator('.prototype-dialog').innerText()).includes('new_mocks/'), 'Новые моки не обнаружены в сравнении');
  for(const id of ['#mock-reason','#mock-strategy','#mock-preserve']) await page.locator(id).fill('Сохранить оригиналы и рассмотреть новое предложение отдельно.');
  await page.locator('[data-save-answers]').click();
  await page.reload();
  await start();
  await page.locator('.prototype-result').waitFor({state:'visible'});
  assert((await page.locator('.prototype-result').innerText()).includes('new_mocks/'), 'Результат с новыми моками не восстановился');
  const restored=await page.evaluate(()=>({sample:JSON.parse(localStorage.getItem('makora.prototype-example.v1')),main:JSON.parse(localStorage.getItem('makora.prototype-handoff.v1'))}));
  assert(restored.sample.status==='received' && restored.sample.inspection.originalMocksPresent && Object.keys(restored.sample.mockAnswers||{}).length>0, 'Ответы или признак исходных моков потеряны после перезагрузки');
  assert(restored.main.sentinel==='original', 'Тестовый кейс изменил состояние основного проекта');
  return {newMocksDetected:true, unsafePathRejected:true, answersRestored:true, externalCodeNotRun:true};
}

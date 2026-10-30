async page => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  assert((await page.locator('.first-disclaimer').innerText()).includes('Этап 06 находится в разработке'), 'Будущий этап не отмечен');
  await page.locator('.pixel-drop input').setInputFiles({name: 'brief.txt', mimeType: 'text/plain', buffer: Buffer.from('Учебное условие хакатона')});
  await page.locator('.pixel-start').click();
  await page.waitForTimeout(1800);
  assert(await page.locator('[data-section]').count() === 10, 'В анализе должно быть 10 разделов');
  for (let i = 0; i < 10; i++) {
    await page.locator(`[data-section="${i}"]`).click();
    assert((await page.locator('.board-document').innerText()).trim().length > 30, `Пустой раздел анализа ${i}`);
    if (i === 0) assert((await page.locator('.board-document').innerText()).includes('Учебное условие хакатона'), 'Исходное условие не сохранено');
    await page.locator('.board-content .board-back').click();
  }
  await page.locator('[data-board-stage="2"]').click();
  for (const [group, count] of [['research', 5], ['solution', 9]]) {
    await page.locator(`[data-idea-group="${group}"]`).click();
    assert(await page.locator('[data-idea-item]').count() === count, `Неверное число разделов ${group}`);
    for (let i = 0; i < count; i++) {
      await page.locator(`[data-idea-item="${i}"]`).click();
      assert((await page.locator('.board-document').innerText()).trim().length > 30, `Пустой раздел ${group} ${i}`);
      if (group === 'solution' && i === 2) await page.locator('[data-idea-approve]').click();
      await page.locator('[data-idea-back]').click();
    }
    await page.locator('[data-idea-home]').click();
  }
  assert(await page.evaluate(() => window.makoraProject.isApproved()), 'Идея не утверждена');
  await page.locator('[data-board-stage="3"]').click();
  assert(await page.locator('[data-plan-item]').count() === 9, 'В планировании должно быть 9 разделов');
  for (let i = 0; i < 9; i++) {
    await page.locator(`[data-plan-item="${i}"]`).click();
    await page.locator('.demo-context-note').first().waitFor({state:'attached'});
    assert(await page.locator('.demo-context-note').count() > 0, `Нет пояснения о демо в разделе плана ${i}`);
    const text = await page.locator('.board-content').innerText();
    assert(text.trim().length > 30, `Пустой раздел плана ${i}`);
    await page.locator('[data-plan-home]').click();
  }
  await page.locator('[data-plan-item="0"]').click();
  await page.locator('[data-plan-approval]').click();
  await page.locator('#approve-step').click();
  for (let i = 1; i <= 3; i++) {
    await page.locator('#doc-content .doc-row').nth(i).click();
    await page.locator('#approve-step').click();
  }
  await page.locator('#doc-content .doc-row').nth(4).click();
  await page.locator('[data-review="architecture"]').click();
  await page.locator('[data-review="tasks"]').click();
  await page.locator('#risk-note').fill('Данные используются только для демо');
  await page.locator('#accept-demo').click();
  await page.locator('#rules-note').fill('Порог статусов уточнить до разработки');
  await page.locator('#accept-rules').click();
  await page.locator('#approve-step').click();
  assert((await page.evaluate(() => window.makoraStage3.getContext().readiness)).ready, 'План не утверждён');
  await page.locator('[data-board-stage="4"]').click();
  assert(await page.locator('[data-mock-item]').count() === 5, 'У моков должно быть 5 разделов');
  for (let i = 0; i < 5; i++) {
    await page.locator(`[data-mock-item="${i}"]`).click();
    await page.locator('.demo-context-note').first().waitFor({state:'attached'});
    assert(await page.locator('.demo-context-note').count() > 0, `Нет пояснения о демо в моках ${i}`);
    assert((await page.locator('.plan-title').first().innerText()).length > 2, `Пустой раздел моков ${i}`);
    if (i === 1) {
      await page.locator('[data-fixture="invalid.json"]').click();
      assert((await page.locator('.fixture-preview').innerText()).includes('status'), 'Фикстура не открывается');
    }
    if (i === 4) {
      await page.locator('#run-fixture-checks').click();
      await page.locator('#mock-approve').waitFor({state:'visible'});
      await page.waitForFunction(() => !document.querySelector('#mock-approve').disabled, null, {timeout: 15000});
      assert((await page.locator('.check-list').innerText()).includes('Mock API'), 'Запросы к заглушке не проверены');
      await page.locator('#mock-approve').click();
      await page.locator('#to-development').waitFor({state:'visible'});
      await page.locator('#to-development').click();
      await page.locator('.prototype-dialog').waitFor({state:'visible'});
      await page.evaluate(() => {const original=fflate.zipSync; fflate.zipSync=(files,...args)=>{window.__prototypeFiles=files;return original(files,...args)}});
      const downloadPromise=page.waitForEvent('download');
      await page.locator('[data-download]').click();
      const archive=await downloadPromise;
      assert(archive.suggestedFilename()==='makora-prototype-context.zip', 'Не создан архив с контекстом');
      const packed=await page.evaluate(()=>Object.keys(window.__prototypeFiles));
      for(const file of ['input/brief.txt','PROMPT.md','01_case_analysis_DEMO.md','02_research.md','02_solution_concept.md','03_architecture.md','03_contracts/openapi.yaml','03_test_plan.md','03_tasks.json','mocks/fixtures/spaces.json','04_validation_report.md','changeset.schema.json','context-status.json']) assert(packed.includes(file), 'В архиве отсутствует '+file);
      assert(await page.evaluate(()=>fflate.strFromU8(window.__prototypeFiles['input/brief.txt']).includes('Учебное условие хакатона')), 'Не передан исходный файл');
      await page.locator('[data-sent]').click();
      await page.locator('.prototype-waiting').waitFor({state:'visible'});
      assert((await page.locator('.prototype-dialog').innerText()).includes('ОЖИДАЮ РЕЗУЛЬТАТ'), 'Нет состояния ожидания');
      const returnedZip=await page.evaluate(()=>{const files={...window.__prototypeFiles,'src/demo.js':fflate.strToU8('not executed')};return Array.from(fflate.zipSync(files))});
      await page.locator('.prototype-drop input').setInputFiles({name:'prototype.zip',mimeType:'application/zip',buffer:Buffer.from(returnedZip)});
      await page.locator('[data-receive]').click();
      await page.locator('.prototype-change').filter({hasText:'src/demo.js'}).waitFor({state:'visible'});
      assert((await page.locator('.prototype-agent-report').innerText()).includes('отсутствует'), 'Отсутствующий отчёт не отмечен');
      const decision=page.locator('.prototype-change').filter({hasText:'src/demo.js'});
      await decision.locator('[data-decision-note]').fill('Уточни поведение интерфейса.');
      await decision.locator('[data-decision="revise"]').click();
      await page.waitForFunction(()=>[...document.querySelectorAll('.prototype-change')].some(el=>el.textContent.includes('src/demo.js')&&el.textContent.includes('На доработку')));
      const revisionDownload=page.waitForEvent('download');
      await page.getByRole('button',{name:'Скачать запрос на доработку ↓'}).click();
      assert((await revisionDownload).suggestedFilename()==='makora-revision-request.zip','Не создан запрос на доработку');
      await decision.locator('[data-decision="accept"]').click();
      await page.waitForFunction(()=>[...document.querySelectorAll('.prototype-change')].some(el=>el.textContent.includes('src/demo.js')&&el.textContent.includes('Принято')));
      await page.locator('[data-question]').first().fill('Принять изменение для проверки сценария');
      await page.locator('[data-save-questions]').click();
      await page.waitForFunction(()=>document.querySelector('.prototype-feedback')?.textContent.includes('Ответы сохранены'));
      const adaptationDownload=page.waitForEvent('download');
      await page.locator('[data-adaptation-package]').click();
      const adaptation=await adaptationDownload;
      assert(adaptation.suggestedFilename()==='makora-adaptation.zip','Не подготовлен пакет актуализации');
      const identifiers=await page.evaluate(()=>{const s=JSON.parse(localStorage.getItem('makora.prototype-handoff.v1'));return {iterationId:s.iterationId,baseRevision:s.baseRevision}});
      const docsZip=await page.evaluate(({iterationId,baseRevision})=>Array.from(fflate.zipSync({
        'proposals/01/01_case_analysis.md':fflate.strToU8('# Суть задания\n\nАктуальная суть из согласованной версии.\n'),
        'proposals/02/02_solution_concept.md':fflate.strToU8('# Финальная идея\n\nАктуальная концепция из согласованной версии.\n'),
        'proposals/03/03_architecture.md':fflate.strToU8('# Обновлённая архитектура\n'),
        'proposals/04/04_validation_report.md':fflate.strToU8('# Валидация\n\nАктуальный отчёт о данных.\n'),
        'adaptation-report.json':fflate.strToU8(JSON.stringify({iteration_id:iterationId,base_revision:baseRevision,updated_documents:['01_case_analysis.md','02_solution_concept.md','03_architecture.md','04_validation_report.md'].map(path=>({path,change_reason:'Согласована актуальная версия',related_ids:[]})),checks:[{id:'markdown',status:'not_run',detail:'Ручная проверка ещё не выполнена.'}],unresolved_questions:[],assumptions:[],known_limitations:[]}))
      })),identifiers);
      await page.locator('[data-adaptation-file]').setInputFiles({name:'adaptation.zip',mimeType:'application/zip',buffer:Buffer.from(docsZip)});
      await page.locator('.prototype-adapted h3').waitFor({state:'visible'});
      for(const path of ['01_case_analysis.md','02_solution_concept.md','03_architecture.md','04_validation_report.md']){
        await page.locator('.prototype-adapted .prototype-change').filter({hasText:path}).locator('[data-doc-decision="accept"]').click();
        await page.waitForFunction(name=>[...document.querySelectorAll('.prototype-adapted .prototype-change')].some(el=>el.textContent.includes(name)&&el.querySelector('header span')?.textContent==='accepted'),path);
      }
      await page.locator('[data-approve-revision]').click();
      await page.waitForFunction(()=>{const s=JSON.parse(localStorage.getItem('makora.prototype-handoff.v1')||'{}');return !!s.approvedRevision});
      const history=await page.evaluate(async()=>{const response=await fetch('/api/history');return (await response.json()).result});
      assert(history.revisions.length===2 && history.iterations[0].status==='approved','Не сохранена согласованная ревизия V2');
      await page.locator('[data-history]').click();
      await page.locator('[data-compare]').first().click();
      await page.waitForFunction(()=>document.querySelector('[data-comparison]')?.textContent.includes('src/demo.js'));
      await page.waitForFunction(()=>!document.querySelector('[data-next-iteration]')?.disabled);
      await page.locator('[data-next-iteration]').click();
      await page.locator('[data-download]').waitFor({state:'visible'});
      const nextDownload=page.waitForEvent('download');await page.locator('[data-download]').click();
      assert((await nextDownload).suggestedFilename()==='makora-prototype-context.zip','Не создан пакет следующей итерации');
      await page.locator('.prototype-dialog [data-close]').click();
      await page.locator('[data-board-stage="1"]').click();
      await page.locator('[data-section="0"]').click();
      assert((await page.locator('.board-document').innerText()).includes('Актуальная суть из согласованной версии'),'Этап 1 не показывает актуальный файл');
      await page.locator('[data-board-stage="2"]').click();
      await page.locator('[data-idea-group="solution"]').click();
      await page.locator('[data-idea-item="2"]').click();
      assert((await page.locator('.board-document').innerText()).includes('Актуальная концепция из согласованной версии'),'Этап 2 не показывает актуальный файл');
      await page.locator('[data-board-stage="3"]').click();
      await page.locator('[data-plan-item="0"]').click();
      assert((await page.locator('.board-document').innerText()).includes('Обновлённая архитектура'),'Этап 3 не показывает актуальный файл');
      await page.locator('.board-version').click();
      await page.locator('[data-version-file]').filter({hasText:'03_architecture.md'}).click();
      assert((await page.locator('.board-document').innerText()).includes('Обновлённая архитектура'),'Доска не открыла документ согласованной версии');
      await page.locator('[data-board-stage="4"]').click();
      await page.locator('[data-mock-item="4"]').click();
      assert((await page.locator('.board-document').innerText()).includes('Актуальный отчёт о данных'),'Этап 4 не показывает актуальный файл');
      await page.locator('[data-current-back]').click();
    }
    if (await page.locator('[data-mock-home]').count()) await page.locator('[data-mock-home]').click();
    else assert(await page.locator('[data-mock-item]').count() === 5, 'Возврат не открыл разделы моков');
  }
  await page.locator('[data-board-stage="2"]').click();
  await page.locator('[data-idea-group="solution"]').click();
  await page.locator('[data-idea-item="2"]').click();
  await page.evaluate(()=>{const doc=conceptBlocks.find(x=>x.title==='Финальная идея');window.makoraProject.saveDocument(doc,doc.md+'\n\nИзменение для проверки зависимостей.');});
  const changed = await page.evaluate(() => ({idea: window.makoraProject.isApproved(), plan: window.makoraStage3.getContext()}));
  assert(!changed.idea && !changed.plan.readiness.ready, 'Изменение идеи не отменило готовность');
  assert(changed.plan.approval.steps.every(step => step.status === 'stale'), 'Зависимый план не помечен для перепроверки');
  await page.evaluate(()=>window.makoraProject.approve());
  assert(await page.evaluate(() => window.makoraProject.isApproved()), 'Повторное утверждение не сохранилось');
  await page.locator('[data-board-stage="3"]').click();
  assert((await page.locator('.scene-bottom p').innerText()).includes('не обновляются автоматически'), 'Нет предупреждения о прежнем плане');
  await page.locator('[data-board-stage="4"]').click();
  await page.locator('[data-mock-item="4"]').click();
  assert((await page.locator('.board-document').innerText()).includes('Актуальный отчёт о данных'),'Должен отображаться утверждённый документ моков');
  assert(await page.evaluate(() => JSON.parse(localStorage.getItem('makora.stage4.review.v1')).status === 'stale'), 'Старое утверждение моков не помечено устаревшим');
  await page.reload();
  assert(await page.evaluate(() => window.makoraProject.isApproved()), 'Утверждение идеи потерялось после обновления');
  assert(await page.evaluate(() => window.makoraProject.context().concept.find(x => x.title === 'Финальная идея').md.includes('Изменение для проверки зависимостей')), 'Изменённая идея не восстановилась');
  await page.locator('.board-scene').waitFor({state:'visible'});
  assert(await page.locator('[data-board-stage].active').count() === 1, 'После перезагрузки не восстановился активный экран');
  await page.locator('.capabilities-toggle').click();
  await page.locator('[data-prototype-open]').click();
  await page.locator('#prototype-prompt').waitFor({state:'visible'});
  const persistedHistory=await page.evaluate(async()=>{const response=await fetch('/api/history');return (await response.json()).result});
  assert(persistedHistory.iterations.some(i=>i.status==='approved') && persistedHistory.revisions.length>=2, 'История версий не восстановилась после перезагрузки');
  await page.locator('[data-open-history]').click();
  await page.locator('[data-rollback]').first().click();
  await page.waitForFunction(async()=>{const r=await fetch('/api/history');const h=(await r.json()).result;return h.revisions.length===3&&h.current_revision.reason.startsWith('rollback from ')});
  await page.locator('.prototype-dialog [data-close]').click();
  await page.locator('[data-section="0"]').click();
  assert(!(await page.locator('.board-document').innerText()).includes('Актуальная суть из согласованной версии'),'После отката остался документ другой ревизии');
  assert(errors.length === 0, 'Ошибки JavaScript: ' + errors.join('; '));
  return {analysis: 10, research: 5, solution: 9, planning: 9, mocks: 5, approvedAndInvalidated: true, errors};
}

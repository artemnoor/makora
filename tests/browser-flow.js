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
      for(const file of ['input/brief.txt','PROMPT.md','01_case_analysis_DEMO.md','02_research.md','02_solution_concept.md','03_architecture.md','03_contracts/openapi.yaml','03_test_plan.md','03_tasks.json','mocks/fixtures/spaces.json','04_validation_report.md']) assert(packed.includes(file), 'В архиве отсутствует '+file);
      assert(await page.evaluate(()=>fflate.strFromU8(window.__prototypeFiles['input/brief.txt']).includes('Учебное условие хакатона')), 'Не передан исходный файл');
      await page.locator('[data-sent]').click();
      assert((await page.locator('.prototype-dialog').innerText()).includes('ОЖИДАЮ РЕЗУЛЬТАТ'), 'Нет состояния ожидания');
      await page.locator('.prototype-drop input').setInputFiles({name:'prototype.zip',mimeType:'application/zip',buffer:Buffer.from('PK\x05\x06' + '\x00'.repeat(18))});
      await page.locator('[data-receive]').click();
      await page.locator('.prototype-result').waitFor({state:'visible'});
      await page.locator('.prototype-dialog [data-close]').click();
    }
    if (await page.locator('[data-mock-home]').count()) await page.locator('[data-mock-home]').click();
    else assert(await page.locator('[data-mock-item]').count() === 5, 'Возврат не открыл разделы моков');
  }
  await page.locator('[data-board-stage="2"]').click();
  await page.locator('[data-idea-group="solution"]').click();
  await page.locator('[data-idea-item="2"]').click();
  await page.locator('[data-idea-edit]').click();
  const original = await page.locator('#idea-editor').inputValue();
  await page.locator('#idea-editor').fill(original + '\n\nИзменение для проверки зависимостей.');
  await page.locator('[data-idea-save]').click();
  const changed = await page.evaluate(() => ({idea: window.makoraProject.isApproved(), plan: window.makoraStage3.getContext()}));
  assert(!changed.idea && !changed.plan.readiness.ready, 'Изменение идеи не отменило готовность');
  assert(changed.plan.approval.steps.every(step => step.status === 'stale'), 'Зависимый план не помечен для перепроверки');
  await page.locator('[data-idea-approve]').click();
  assert(await page.evaluate(() => window.makoraProject.isApproved()), 'Повторное утверждение не сохранилось');
  await page.locator('[data-board-stage="3"]').click();
  assert((await page.locator('.scene-bottom p').innerText()).includes('не обновляются автоматически'), 'Нет предупреждения о прежнем плане');
  await page.locator('[data-board-stage="4"]').click();
  await page.locator('[data-mock-item="4"]').click();
  assert((await page.locator('.validation-summary').innerText()).includes('Проверки не выполнялись'), 'Старые проверки моков должны требовать повторного выполнения');
  assert(await page.locator('#mock-approve').isDisabled(), 'Моки нельзя утверждать без повторной проверки');
  assert(await page.evaluate(() => JSON.parse(localStorage.getItem('makora.stage4.review.v1')).status === 'stale'), 'Старое утверждение моков не помечено устаревшим');
  await page.reload();
  assert(await page.evaluate(() => window.makoraProject.isApproved()), 'Утверждение идеи потерялось после обновления');
  assert(await page.evaluate(() => window.makoraProject.context().concept.find(x => x.title === 'Финальная идея').md.includes('Изменение для проверки зависимостей')), 'Изменённая идея не восстановилась');
  await page.locator('#first-text').fill('Новое условие после перезагрузки');
  await page.locator('.pixel-start').click();
  await page.locator('.capabilities-toggle').click();
  await page.locator('[data-prototype-open]').click();
  assert((await page.locator('.prototype-dialog').innerText()).includes('Прототип'), 'Результат не восстановился после перезагрузки');
  await page.locator('[data-result-download]').waitFor({state:'visible', timeout:15000});
  assert(errors.length === 0, 'Ошибки JavaScript: ' + errors.join('; '));
  return {analysis: 10, research: 5, solution: 9, planning: 9, mocks: 5, approvedAndInvalidated: true, errors};
}

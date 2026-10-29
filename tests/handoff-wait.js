async page => {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.locator('#first-text').fill('Учебное условие');
  await page.locator('.pixel-start').click();
  await page.locator('.capabilities-toggle').click();
  await page.locator('[data-prototype-open]').click();
  const download = page.waitForEvent('download');
  await page.locator('[data-download]').click();
  await download;
  assert((await page.locator('.prototype-feedback').innerText()).includes('черновик'), 'Не показан статус черновика');
  await page.locator('[data-sent]').click();
  assert((await page.locator('.prototype-dialog').innerText()).includes('ОЖИДАЮ РЕЗУЛЬТАТ'), 'Ожидание не началось');
  await page.reload();
  await page.locator('#first-text').fill('Учебное условие');
  await page.locator('.pixel-start').click();
  await page.locator('.capabilities-toggle').click();
  await page.locator('[data-prototype-open]').click();
  assert((await page.locator('.prototype-dialog').innerText()).includes('ОЖИДАЮ РЕЗУЛЬТАТ'), 'Ожидание не восстановилось');
  await page.locator('#prototype-link').fill('https://example.com/project');
  await page.locator('[data-receive]').click();
  await page.locator('.prototype-result').waitFor({state:'visible'});
  assert((await page.locator('.prototype-result a').getAttribute('href')) === 'https://example.com/project', 'Ссылка не сохранена');
  return {waitingRestored:true, linkAccepted:true};
}

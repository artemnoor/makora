async page => {
  let status='unavailable',launches=0;
  await page.route('**/api/agents/auth**',route=>{
    if(route.request().method()==='POST'){
      launches++;
      if(!route.request().headers()['x-makora-token'])throw Error('Missing local authorization');
      return route.fulfill({json:{ok:true,result:{opened:true,message:'Консоль входа открыта'}}});
    }
    return route.fulfill({json:{ok:true,result:{status,message:status==='signed_in'?'Вход подтверждён':'Нужно проверить вход'}}});
  });
  await page.reload();
  await page.getByText('○ Codex · нет подключения',{exact:true}).waitFor();
  if(launches)throw Error('Offline started login');
  await page.locator('.codex-auth-toggle').click();
  status='signed_out';await page.locator('[data-auth-check]').click();
  await page.getByText('Консоль входа открыта',{exact:true}).waitFor();
  if(launches!==1)throw Error('Login not opened automatically');
  await page.locator('[data-auth-check]').click();
  if(launches!==1)throw Error('Duplicate automatic login');
  status='signed_in';await page.locator('[data-auth-check]').click();
  await page.getByText('● Codex · вход выполнен',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  const box=await page.locator('.codex-auth-console').boundingBox();
  if(box.x<0||box.x+box.width>391)throw Error('Console outside viewport');
  return {offlineDoesNotLaunch:true,automaticLogin:true,noDuplicates:true,signInRecovery:true,mobile:true};
}

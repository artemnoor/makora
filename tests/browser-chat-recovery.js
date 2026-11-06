async page=>{
  let recoveries=0,sends=0;
  let chat={status:'unconfirmed',error:'Доставка последнего сообщения не подтверждена.',messages:[
    {role:'user',text:'привет'},{role:'assistant',text:'Привет! Я Макора.'},{role:'user',text:'фыв'}]};
  await page.route('**/api/agents/auth',r=>r.fulfill({json:{ok:true,result:{status:'signed_in',message:'Test auth'}}}));
  await page.route('**/api/preparation**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname;
    if(path==='/api/preparation/chat/recover'){
      recoveries++;chat={...chat,status:'idle',error:null,notice:'Ожидание снято.'};chat.messages[2].deliveryState='unconfirmed';
      return route.fulfill({json:{ok:true,result:chat}});
    }
    if(path==='/api/preparation/chat'){
      if(request.method()==='POST'){
        sends++;const body=request.postDataJSON();if(body.message!=='Новый вопрос')throw Error('Uncertain message resent');
        chat.messages.push({role:'user',text:body.message},{role:'assistant',text:'Ответ на новый вопрос'});
      }
      return route.fulfill({json:{ok:true,result:chat}});
    }
    return route.fulfill({json:{ok:true,result:{brief:'Project',stages:{'1':{status:'approved',files:{'01_case_analysis.md':'# Project'}}}}}});
  });
  await page.reload();await page.waitForFunction(()=>!!window.makoraChat);
  await page.evaluate(()=>window.makoraChat.open());
  await page.getByRole('button',{name:'Снять ожидание',exact:true}).waitFor();
  if(await page.locator('.chat-thinking-wheel').count())throw Error('Unconfirmed delivery shows thinking spinner');
  await page.getByRole('button',{name:'Снять ожидание',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.project-chat textarea').disabled);
  if(await page.locator('.chat-message').count()!==3)throw Error('History lost');
  if(sends!==0||recoveries!==1)throw Error('Recovery resent a message');
  await page.locator('.project-chat textarea').fill('Новый вопрос');await page.locator('.project-chat textarea').press('Enter');
  await page.getByText('Ответ на новый вопрос',{exact:true}).waitFor();
  return {recovered:true,historyPreserved:true,noResend:true,composerUnlocked:true,newMessage:true};
}

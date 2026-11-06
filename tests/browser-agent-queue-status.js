async page => {
  let polls=0;
  await page.route('**/api/agents/auth',route=>route.fulfill({json:{ok:true,result:{status:'signed_in',message:'Test auth'}}}));
  const project={projectRoot:'C:/wanted-site',brief:'Improve uploaded site',context:'',digest:'queue-test',artifactPaths:[]};
  const prep={brief:'Improve uploaded site',stages:{'1':{status:'approved'},'2':{status:'approved'},'3':{status:'approved'},'4':{status:'approved'}},returnedProject:{status:'prepared',commit:'test-commit'}};
  await page.route('**/api/preparation**',route=>route.fulfill({json:{ok:true,result:route.request().url().endsWith('/development')?project:prep}}));
  await page.route('**/api/agents/status',route=>route.fulfill({json:{ok:true,result:{connected:true,modelAvailable:true,allowedRoots:[project.projectRoot]}}}));
  await page.route('**/api/agents/approvals',route=>route.fulfill({json:{ok:true,result:[]}}));
  await page.route('**/api/agents/state',route=>{
    polls++;
    const current={id:'wanted-run',projectRoot:project.projectRoot,baseCommit:'0123456789abcdef',plannerSessionId:'planner',tasks:[],mahoragaAutopilot:{enabled:polls===1,status:polls===1?'running':'needs_human',lastError:polls===1?null:'Codex rejected authentication'}};
    return route.fulfill({json:{ok:true,result:{runs:[current,{id:'foreign-run',projectRoot:'C:/other-site',baseCommit:'abc',tasks:[]}],sessions:[],events:[]}}});
  });
  await page.evaluate(()=>{localStorage.setItem('makora.agent-real-run','foreign-run');localStorage.setItem('makora.real-development-digest','queue-test');localStorage.setItem('makora.real-stage6-base','test-commit')});
  await page.reload();await page.locator('[data-real-stage="6"]').click();
  await page.getByRole('button',{name:'Приостановить автокоординацию',exact:true}).waitFor();
  await page.getByText('Работа остановлена: Codex rejected authentication',{exact:true}).waitFor({timeout:15000});
  await page.getByRole('button',{name:'Новый запуск →',exact:true}).waitFor();
  if(polls<2)throw Error('Queue stopped polling with zero active sessions');
  if((await page.locator('.board-content').innerText()).includes('C:/other-site'))throw Error('Foreign project selected');
  return {projectScoped:true,idleQueuePolled:true,stopReasonVisible:true,buttonUpdated:true};
}

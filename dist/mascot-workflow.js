/* Mascot animations reflect observed workflow state; agent badges represent real sessions. */
(()=>{
 let sending=false;
 window.addEventListener('makora:activity',e=>{sending=e.detail.active;sync()});
 const labels={mahoraga_planner:'Махорага · план',mahoraga_orchestrator:'Махорага',builder:'Builder',reviewer:'Reviewer',test_designer:'Test Designer',preparation:'Подготовка'};
 const statuses={accepted:'создан',delivered:'получил задачу',running:'работает',completed:'ответ готов',failed:'ошибка',unconfirmed:'проверяем связь'};
 function sync(){
  const root=document.querySelector('#first-stage');if(!root)return;
  const stage=Number(root.querySelector('[data-real-stage].active')?.dataset.realStage||1),phase=root.querySelector('.rp-workspace')?.dataset.phase;
  const spin=stage<=4&&(sending||['running','launching'].includes(phase));
  try{const wheel=root.querySelector('.mascot-frame').contentDocument.querySelector('[data-action="wheel"]');if(wheel&&wheel.classList.contains('active')!==spin)wheel.click()}catch{}
  let host=root.querySelector('.agent-orbit');
  if(stage!==6){if(host)host.hidden=true;return}
  if(!host){host=document.createElement('section');host.className='agent-orbit';host.setAttribute('aria-label','Агенты проекта');root.append(host)}host.hidden=false;
  let sessions=[];try{sessions=JSON.parse(root.querySelector('.real-agent-view')?.dataset.agentSessions||'[]')}catch{}
  const ids=new Set(sessions.map(s=>s.id));for(const badge of host.querySelectorAll('[data-session]'))if(!ids.has(badge.dataset.session))badge.remove();
  for(const session of sessions){let badge=[...host.children].find(e=>e.dataset.session===session.id);if(!badge){badge=document.createElement('div');badge.className='agent-oval';badge.dataset.session=session.id;badge.append(document.createElement('b'),document.createElement('span'));host.append(badge)}badge.dataset.status=session.status;badge.querySelector('b').textContent='Агент · '+(labels[session.role]||session.role);badge.querySelector('span').textContent=(session.task?session.task+' · ':'')+(statuses[session.status]||session.status);badge.title='Сессия '+session.id}
 }
 setInterval(sync,500);sync();
})();

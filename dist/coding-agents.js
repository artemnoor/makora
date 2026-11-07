/* NOX portraits follow real controller sessions; rendering never launches work. */
(() => {
  let host;
  const portraits=new Map();
  const dismissalKey='makora.dismissed-coding-agents';
  let dismissed=new Set();try{dismissed=new Set(JSON.parse(sessionStorage.getItem(dismissalKey)||'[]'))}catch{}
  function rememberDismissed(){try{sessionStorage.setItem(dismissalKey,JSON.stringify([...dismissed]))}catch{}}
  function removeDeparted(item){
    if(!item.leaving)return;clearTimeout(item.departureTimer);if(selected===item)closeDetails();
    const focused=item.card.contains(document.activeElement);item.card.remove();portraits.delete(item.session.id);dismissed.add(item.session.id);rememberDismissed();
    if(focused){const next=portraits.values().next().value?.card||document.querySelector('.stage-board-back');next?.focus()}
    if(host&&!portraits.size)host.hidden=true;
  }
  function dismissAgent(item){
    if(item.leaving||item.session.status!=='completed')return;
    item.leaving=true;item.paused=true;item.target=null;walking(item);item.card.classList.add('departing');item.dismiss.disabled=true;item.dismiss.textContent='Уходит в тень…';
    if(selected===item)closeDetails();
    if(reduced.matches){removeDeparted(item);return}
    item.frame.contentWindow?.postMessage({type:'makora:nox-depart'},location.origin);
    item.departureTimer=setTimeout(()=>removeDeparted(item),3500);
  }
  window.addEventListener('message',event=>{if(event.origin!==location.origin||event.data?.type!=='makora:nox-departed')return;for(const item of portraits.values())if(event.source===item.frame.contentWindow){removeDeparted(item);break}});
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let animation=0,lastTime=0;
  let mouse={x:innerWidth/2,y:innerHeight/2},lastPointerSent=0;
  function input(item,detail){item.frame.contentWindow?.postMessage({type:'makora:nox-input',...detail},location.origin)}
  function walking(item,speed=0,direction=1){
    if(item.walkSpeed===speed&&item.walkDirection===direction)return;
    item.walkSpeed=speed;item.walkDirection=direction;input(item,{speed,direction});
  }
  function lookAtCursor(item){const rect=item.card.getBoundingClientRect();input(item,{pointer:{x:Math.max(-1,Math.min(1,(mouse.x-rect.x-rect.width/2)/220)),y:Math.max(-1,Math.min(1,(mouse.y-rect.y-rect.height/3)/220))}})}
  function place(item,x,y){
    item.x=Math.max(0,Math.min(Math.max(0,innerWidth-item.card.offsetWidth),x));
    item.y=Math.max(innerHeight/2,Math.min(Math.max(innerHeight/2,innerHeight-item.card.offsetHeight),y));
    item.card.style.transform=`translate3d(${item.x}px,${item.y}px,0)`;
  }
  function tick(now){
    animation=0;
    if(!host||host.hidden||document.hidden){lastTime=0;return}
    const dt=Math.min((now-(lastTime||now))/1000,.05);lastTime=now;
    for(const item of portraits.values()){
      if(item.leaving||item.session?.status==='completed'||reduced.matches||item.drag||item.paused||item.card.matches(':hover,:focus-within')){walking(item);continue}
      if(now<item.waitUntil){walking(item);continue}
      if(!item.target){item.target={x:Math.random()*Math.max(0,innerWidth-item.card.offsetWidth),y:innerHeight/2+Math.random()*Math.max(0,innerHeight/2-item.card.offsetHeight)}}
      const dx=item.target.x-item.x,dy=item.target.y-item.y,distance=Math.hypot(dx,dy),step=dt*32;
      if(distance<step+1){walking(item);item.target=null;item.waitUntil=now+1800+Math.random()*3200;continue}
      walking(item,32,dx<0?-1:1);
      place(item,item.x+dx/distance*step,item.y+dy/distance*step);
      if(now-(item.lastLook||0)>80){lookAtCursor(item);item.lastLook=now}
    }
    if(!reduced.matches)animation=requestAnimationFrame(tick);
  }
  function start(){if(!animation&&!reduced.matches&&!document.hidden&&host&&!host.hidden)animation=requestAnimationFrame(tick)}
  function makeMovable(item){
    const card=item.card;card.tabIndex=0;card.setAttribute('role','group');
    card.addEventListener('pointerenter',()=>{if(item.leaving)return;walking(item);lookAtCursor(item);input(item,{reaction:'wave'})});
    card.addEventListener('pointerdown',e=>{
      if(e.button!==0||item.leaving||e.target.closest('button'))return;
      item.drag={id:e.pointerId,x:e.clientX,y:e.clientY,left:item.x,top:item.y,moved:false};
      walking(item);input(item,{carried:true});
      item.target=null;card.classList.add('carried');card.setPointerCapture(e.pointerId);e.preventDefault();
    });
    card.addEventListener('pointermove',e=>{const d=item.drag;if(d?.id===e.pointerId){if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>5)d.moved=true;place(item,d.left+e.clientX-d.x,d.top+e.clientY-d.y)}});
    const release=e=>{if(item.drag?.id!==e.pointerId)return;const tapped=e.type==='pointerup'&&!item.drag.moved;item.drag=null;item.waitUntil=performance.now()+5000;input(item,{carried:false,reaction:tapped?'jump':'wave'});card.classList.remove('carried');if(tapped)showDetails(item);if(card.hasPointerCapture(e.pointerId))card.releasePointerCapture(e.pointerId)};
    for(const name of ['pointerup','pointercancel','lostpointercapture'])card.addEventListener(name,release);
    card.addEventListener('keydown',e=>{
      if(item.leaving||e.target.closest('button'))return;
      if(e.key==='Enter'){e.preventDefault();if(!e.repeat)showDetails(item);return}
      if(e.key===' '){e.preventDefault();if(!e.repeat){item.paused=!item.paused;card.setAttribute('aria-pressed',String(item.paused));walking(item)}return}
      const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];
      if(!delta)return;e.preventDefault();item.target=null;item.waitUntil=performance.now()+5000;place(item,item.x+delta[0]*(e.shiftKey?40:12),item.y+delta[1]*(e.shiftKey?40:12));
    });
    card.setAttribute('aria-pressed','false');
    place(item,30+(portraits.size%4)*130,Math.max(60,innerHeight-200-(Math.floor(portraits.size/4)%3)*170));
  }
  window.addEventListener('resize',()=>{for(const item of portraits.values()){item.target=null;place(item,item.x,item.y)}});
  window.addEventListener('pointermove',e=>{mouse={x:e.clientX,y:e.clientY};const now=performance.now();if(now-lastPointerSent<60||host?.hidden)return;lastPointerSent=now;for(const item of portraits.values())lookAtCursor(item)},{passive:true});
  document.addEventListener('pointerleave',()=>{for(const item of portraits.values())input(item,{pointer:{x:0,y:0}})});
  document.addEventListener('visibilitychange',()=>{lastTime=0;start()});
  reduced.addEventListener('change',()=>{lastTime=0;start()});
  const active=s=>['accepted','delivered','running'].includes(s.status);
  const roles={builder:'Пишет код',test_designer:'Готовит тесты',reviewer:'Проверяет код',mahoraga_planner:'Составляет план',mahoraga:'Анализирует'};
  const statuses={completed:'Ответ завершён',failed:'Ошибка',unconfirmed:'Ожидает подтверждения'};
  let details, selected;
  function showDetails(item){
    selected=item;
    if(!details){
      details=document.createElement('section');details.className='nox-details';details.setAttribute('role','dialog');details.setAttribute('aria-label','Информация об агенте');
      details.innerHTML='<header><strong>Агент NOX</strong><button type="button" aria-label="Закрыть">×</button></header><dl></dl>';
      document.body.append(details);details.querySelector('button').onclick=closeDetails;
      details.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetails()});
    }
    details.hidden=false;updateDetails();details.querySelector('button').focus();
  }
  function closeDetails(){if(details)details.hidden=true;selected?.card.focus();selected=null}
  function updateDetails(){
    if(!selected||!details||details.hidden)return;
    const s=selected.session,t=selected.task||{};
    const rows=[['Роль',roles[s.role]||s.role],['Состояние',({accepted:'Запрос принят',delivered:'Сообщение доставлено',running:'Выполняется',completed:'Завершено',failed:'Ошибка',unconfirmed:'Ожидает подтверждения'})[s.status]||s.status],['Задача',t.title||s.taskId||'Проект'],['Цель',t.goal||'Цель не указана'],['Этап задачи',selected.stage||'Нет данных'],['Модель',s.model],['Рабочая папка',s.cwd],['Ошибка',s.error?.message]];
    const list=details.querySelector('dl');list.replaceChildren();
    for(const [name,value] of rows){if(!value)continue;const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;list.append(dt,dd)}
  }
  function render(sessions,run){
    if(!host){
      host=document.createElement('aside');host.className='nox-team';host.setAttribute('aria-label','Кодинг-агенты NOX');
      document.body.append(host);
    }
    for(const session of sessions)if(active(session)&&dismissed.delete(session.id))rememberDismissed();
    const visible=sessions.filter(s=>!dismissed.has(s.id));
    host.hidden=!visible.length;
    const ids=new Set(visible.map(s=>s.id));
    for(const [id,item] of portraits)if(!ids.has(id)){if(selected===item)closeDetails();clearTimeout(item.departureTimer);item.card.remove();portraits.delete(id)}
    for(const session of visible){
      let item=portraits.get(session.id);
      if(item?.leaving&&active(session)){clearTimeout(item.departureTimer);item.card.remove();portraits.delete(session.id);item=null}
      if(!item){
        const card=document.createElement('div');card.className='nox-worker';
        const frame=document.createElement('iframe');frame.src='nox-agent.html?embed=1&v=depart-34';frame.title='NOX · '+(roles[session.role]||session.role);frame.tabIndex=-1;frame.setAttribute('aria-hidden','true');
        const label=document.createElement('span');const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='nox-dismiss';dismiss.textContent='Уйти в тень';dismiss.hidden=true;card.append(frame,label,dismiss);host.append(card);
        item={card,frame,label,dismiss,mode:'idle',x:0,y:0,waitUntil:performance.now()+2000,paused:false};makeMovable(item);dismiss.onclick=event=>{event.stopPropagation();dismissAgent(item)};portraits.set(session.id,item);
        frame.onload=()=>{frame.contentWindow.postMessage({type:'makora:nox-state',mode:item.mode},location.origin);input(item,{speed:item.walkSpeed||0,direction:item.walkDirection||1,carried:!!item.drag});lookAtCursor(item)};
      }
      if(item.leaving)continue;
      item.session=session;item.dismiss.hidden=session.status!=='completed';item.dismiss.setAttribute('aria-label','Убрать завершённого агента: '+(roles[session.role]||session.role)+' · '+(session.taskId||'проект'));item.task=run?.tasks?.find(t=>t.id===session.taskId);item.stage=item.task?.status?({pending:'В очереди',ready:'Готова к запуску',implementing:'Разработка',review_pending:'Ожидает тестов',reviewing:'Проверка',review_completed:'Проверка завершена',tests_failed:'Тесты не прошли',tests_passed:'Тесты пройдены',integrated:'Интегрирована',changes_requested:'Нужны исправления',blocked_for_human:'Ожидает решения человека'})[item.task.status]||item.task.status:null;
      const mode=active(session)?(session.role==='builder'?'code':session.role==='reviewer'?'debug':'think'):session.status==='failed'?'debug':'idle';
      item.label.textContent=(roles[session.role]||session.role)+' · '+(session.taskId||'проект')+' · '+(active(session)?'работает':statuses[session.status]||session.status);
      item.card.setAttribute('aria-label','NOX. '+item.label.textContent+'. Клик или Enter — информация об агенте. Стрелки — перемещение. Пробел — пауза прогулки.');
      item.card.dataset.status=session.status;
      place(item,item.x,item.y);
      if(item.mode!==mode){item.mode=mode;item.frame.contentWindow?.postMessage({type:'makora:nox-state',mode},location.origin)}
    }
    updateDetails();start();
  }
  function hide(){if(selected)closeDetails();if(host)host.hidden=true;cancelAnimationFrame(animation);animation=0;lastTime=0;for(const item of portraits.values()){walking(item);item.mode='sleep';item.frame.contentWindow?.postMessage({type:'makora:nox-state',mode:'sleep'},location.origin)}}
  window.makoraCodingAgents={render,hide};
})();

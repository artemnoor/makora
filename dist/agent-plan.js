// Demonstration only: no agents are started and no project analysis is performed.
window.createAgentPlan = function(root, mascot) {
  const key = 'makora.agent-plan-demo.v1';
  const workspaceKey = 'makora.workspace-view.v1';
  let savedView={};try{savedView=JSON.parse(localStorage.getItem(workspaceKey))||{};}catch(_){}
  const defaults = [
    {id:'T01', title:'Подготовка проекта', deps:'Нет', goal:'Подготовить структуру приложения и подключить исходные данные.', contract:'Структура проекта и README', mocks:'mocks/fixtures/spaces.json', tools:'Редактор, терминал, Git', ready:'Проект запускается, фикстуры доступны, базовые проверки проходят.'},
    {id:'T02', title:'Каталог пространств', deps:'T01', goal:'Загрузить каталог пространств из фикстур и подготовить данные для интерфейса.', contract:'Space · GET /spaces', mocks:'spaces.json, empty.json, invalid.json', tools:'Редактор, терминал, тестовый раннер', ready:'Корректные записи загружаются, ошибки данных обрабатываются и проверены.'},
    {id:'T03', title:'Интерфейс поиска', deps:'T01', goal:'Создать экран поиска и фильтров свободных пространств.', contract:'User flow · модель Space', mocks:'spaces.json, empty.json', tools:'Редактор, браузер, тестовый раннер', ready:'Поиск и фильтры работают на мок-данных, пустое состояние проверено.'},
    {id:'T04', title:'Интеграция и проверка', deps:'T02, T03', goal:'Соединить каталог с интерфейсом и проверить основной сценарий.', contract:'GET /spaces · тест-план', mocks:'spaces.json, stale.json, empty.json', tools:'Браузер, терминал, E2E-тесты', ready:'Основной сценарий и обработка ошибок проходят сквозную проверку.'}
  ].map(t=>({...t,builder:`Реализуй задачу ${t.id} «${t.title}». Используй указанные контракты и файлы моков, добавь тесты и опиши результат.`,reviewer:`Проверь задачу ${t.id} по контрактам и критериям готовности, запусти доступные тесты и сообщи о найденных проблемах.`}));
  let state;
  try { state=JSON.parse(localStorage.getItem(key)); } catch (_) {}
  if (!state || !Array.isArray(state.tasks) || state.tasks.length !== defaults.length) state={tasks:defaults,approved:false};
  const board=document.createElement('section');
  board.className='agent-plan-board'; board.hidden=true;
  board.setAttribute('aria-label','Демонстрационный план агентов');
  board.innerHTML=`<img class="agent-board-shadow" src="analysis-board.png" alt="" draggable="false"><img class="agent-board-art" src="analysis-board.png" alt="" draggable="false"><div class="agent-board-frame"><header class="agent-board-header"><div><small>ДЕМО · ТИХИЙ КАМПУС</small><h2>План агентов</h2></div><div><button type="button" data-agent-expand aria-label="Развернуть доску">⛶</button></div></header><div class="agent-board-content"></div><footer class="agent-board-footer"><span data-agent-status></span><button type="button" data-agent-approve>Утвердить план</button></footer></div>`;
  root.append(board);
  const content=board.querySelector('.agent-board-content'), status=board.querySelector('[data-agent-status]');
  let current=null, drag=null, moved=!!savedView.planMoved;
  const motion={x:0,y:0,targetX:0,targetY:0,velocity:0,rotation:0,frame:0,last:0};
  const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  function paint(){board.style.left=motion.x+'px';board.style.top=motion.y+'px';board.style.setProperty('--agent-tilt',motion.rotation+'deg');}
  function settle(){cancelAnimationFrame(motion.frame);motion.frame=0;motion.x=motion.targetX;motion.y=motion.targetY;motion.velocity=motion.rotation=0;paint();}
  function animate(now){
    motion.frame=0;
    if(!root.isConnected||board.hidden||board.classList.contains('agent-expanded')||reducedMotion.matches){settle();return;}
    const dt=Math.min(.06,Math.max(0,(now-motion.last)/1000));motion.last=now;
    const smooth=1-Math.exp(-dt*11);motion.x+=(motion.targetX-motion.x)*smooth;motion.y+=(motion.targetY-motion.y)*smooth;
    motion.rotation+=(clamp(motion.velocity*.006,-3,3)-motion.rotation)*(1-Math.exp(-dt*7));
    if(!drag){motion.velocity*=Math.exp(-dt*7);motion.rotation*=Math.exp(-dt*2.3);}
    paint();
    if(drag||Math.abs(motion.targetX-motion.x)>.1||Math.abs(motion.targetY-motion.y)>.1||Math.abs(motion.velocity)>.1||Math.abs(motion.rotation)>.01)motion.frame=requestAnimationFrame(animate);else settle();
  }
  function startMotion(){if(reducedMotion.matches){settle();return;}if(!motion.frame){motion.last=performance.now();motion.frame=requestAnimationFrame(animate);}}
  function save(){try{localStorage.setItem(key,JSON.stringify(state));}catch(_){}}
  function saveView(){try{localStorage.setItem(workspaceKey,JSON.stringify({...savedView,planMoved:moved,planX:motion.targetX,planY:motion.targetY,planExpanded:board.classList.contains('agent-expanded')}));}catch(_){}}
  function updateStatus(){status.textContent=state.approved?'● ПЛАН УТВЕРЖДЁН · ДЕМО':'○ ЧЕРНОВИК · ДЕМО';board.querySelector('[data-agent-approve]').textContent=state.approved?'Утверждено ✓':'Утвердить план';}
  function graph(){
    current=null;
    savedView.planTask=null;saveView();
    content.innerHTML=`<p class="agent-note">Пример плана · агенты не запускаются</p><div class="agent-tree"><div class="agent-tree-row"><button data-task="0"></button></div><div class="agent-branch" aria-hidden="true"></div><div class="agent-tree-row parallel"><button data-task="1"></button><button data-task="2"></button></div><div class="agent-merge" aria-hidden="true"></div><div class="agent-tree-row"><button data-task="3"></button></div></div><p class="agent-tree-caption">T02 и T03 могут выполняться параллельно</p>`;
    content.querySelectorAll('[data-task]').forEach(button=>{const t=state.tasks[Number(button.dataset.task)];button.innerHTML='<span></span><strong></strong><small></small>';button.querySelector('span').textContent=t.id;button.querySelector('strong').textContent=t.title;button.querySelector('small').textContent='Зависит: '+t.deps;});
    updateStatus();
  }
  const fields=[['goal','Цель'],['deps','Зависимости'],['contract','Контракт'],['mocks','Моки'],['tools','Инструменты'],['ready','Критерий готовности'],['builder','Промпт Builder'],['reviewer','Промпт Reviewer']];
  function detail(index){
    current=index; const task=state.tasks[index];
    savedView.planTask=index;saveView();
    content.innerHTML='<button class="agent-back" type="button">← К графу</button><div class="agent-detail-title"><small></small><h3></h3></div><p class="agent-note">Демонстрационная карточка · изменения сохраняются в браузере</p><div class="agent-fields"></div>';
    content.querySelector('.agent-detail-title small').textContent=task.id;content.querySelector('h3').textContent=task.title;
    const container=content.querySelector('.agent-fields');
    fields.forEach(([name,label])=>{const el=document.createElement('label');const span=document.createElement('span');span.textContent=name==='deps'?label+' · зафиксированы в демо':label;const input=document.createElement(name==='deps'?'input':'textarea');input.value=task[name]||'';input.dataset.field=name;if(name==='deps')input.readOnly=true;el.append(span,input);container.append(el);});
    content.querySelector('.agent-back').onclick=graph;
    updateStatus();
  }
  content.addEventListener('click',e=>{const b=e.target.closest('[data-task]');if(b)detail(Number(b.dataset.task));});
  content.addEventListener('input',e=>{if(current===null||!e.target.dataset.field)return;state.tasks[current][e.target.dataset.field]=e.target.value;state.approved=false;save();updateStatus();});
  board.querySelector('[data-agent-approve]').onclick=()=>{state.approved=true;save();updateStatus();};
  board.querySelector('[data-agent-expand]').onclick=()=>{board.classList.toggle('agent-expanded');position();saveView();};
  board.addEventListener('dblclick',e=>{if(e.target.closest('button,textarea,input,label'))return;board.classList.toggle('agent-expanded');position();saveView();});
  board.addEventListener('pointerdown',e=>{
    if(board.classList.contains('agent-expanded') || e.button!==0 || e.target.closest('button,textarea,input,label,.agent-board-content,.agent-board-footer'))return;
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,left:motion.targetX,top:motion.targetY,previousX:e.clientX,last:performance.now()};
    board.classList.add('agent-dragging');board.setPointerCapture(e.pointerId);e.preventDefault();
  });
  board.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;moved=true;motion.targetX=clamp(drag.left+e.clientX-drag.x,0,Math.max(0,window.innerWidth-board.offsetWidth));motion.targetY=clamp(drag.top+e.clientY-drag.y,0,Math.max(0,window.innerHeight-board.offsetHeight));const now=performance.now();motion.velocity=clamp((e.clientX-drag.previousX)/Math.max(.016,(now-drag.last)/1000),-1000,1000);drag.previousX=e.clientX;drag.last=now;startMotion();});
  function endDrag(e){if(!drag||drag.id!==e.pointerId)return;drag=null;board.classList.remove('agent-dragging');saveView();startMotion();if(board.hasPointerCapture(e.pointerId))board.releasePointerCapture(e.pointerId);}
  ['pointerup','pointercancel','lostpointercapture'].forEach(type=>board.addEventListener(type,endDrag));
  function position(){if(board.hidden||board.classList.contains('agent-expanded'))return;if(moved){motion.targetX=clamp(Number(savedView.planX)||0,0,Math.max(0,window.innerWidth-board.offsetWidth));motion.targetY=clamp(Number(savedView.planY)||0,0,Math.max(0,window.innerHeight-board.offsetHeight));settle();return;}const rect=mascot.getBoundingClientRect();const width=window.innerWidth<=760?Math.min(390,window.innerWidth-16):Math.min(510,Math.max(300,rect.left-28));board.style.width=width+'px';motion.targetX=Math.max(8,rect.left-width-18);motion.targetY=Math.max(8,Math.min(window.innerHeight-board.offsetHeight-8,rect.top+rect.height/2-board.offsetHeight/2));settle();}
  graph();
  return {position,open(){board.classList.remove('agent-expanded','agent-revealing');board.hidden=false;if(Number.isInteger(savedView.planTask)&&savedView.planTask>=0&&savedView.planTask<state.tasks.length)detail(savedView.planTask);else graph();position();if(savedView.planExpanded)board.classList.add('agent-expanded');void board.offsetWidth;board.classList.add('agent-revealing');}};
};

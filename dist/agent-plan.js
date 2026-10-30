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
  board.innerHTML=`<img class="agent-board-shadow" src="analysis-board.png" alt="" draggable="false"><img class="agent-board-art" src="analysis-board.png" alt="" draggable="false"><nav class="agent-board-tabs" aria-label="Разделы доски агентов"><button type="button" data-agent-tab="agents">01 <span>Агенты</span></button><button type="button" data-agent-tab="activity">02 <span>Этапы</span></button><button type="button" data-agent-tab="gitflow">03 <span>Gitflow</span></button></nav><div class="agent-board-frame"><header class="agent-board-header"><div><small>ДЕМО · ТИХИЙ КАМПУС</small><h2>План агентов</h2></div><div><button type="button" data-agent-expand aria-label="Развернуть доску">⛶</button></div></header><div class="agent-board-content"></div><footer class="agent-board-footer"><span data-agent-status></span><button type="button" data-agent-approve>Утвердить план</button></footer></div>`;
  root.append(board);
  const content=board.querySelector('.agent-board-content'), status=board.querySelector('[data-agent-status]');
  let current=null, drag=null, moved=!!savedView.planMoved;
  let activeTab=['agents','activity','gitflow'].includes(savedView.agentTab)?savedView.agentTab:'agents';
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
  function saveView(){try{const latest=JSON.parse(localStorage.getItem(workspaceKey))||{};savedView={...latest,...savedView,stage:latest.stage,agentTab:activeTab,planMoved:moved,planX:motion.targetX,planY:motion.targetY,planExpanded:board.classList.contains('agent-expanded')};localStorage.setItem(workspaceKey,JSON.stringify(savedView));}catch(_){}}
  function updateStatus(){status.textContent=state.approved?'● ПЛАН УТВЕРЖДЁН · ДЕМО':'○ ЧЕРНОВИК · ДЕМО';const approve=board.querySelector('[data-agent-approve]');approve.hidden=activeTab!=='agents';approve.textContent=state.approved?'Утверждено ✓':'Утвердить план';}
  function updateTabs(){board.classList.toggle('agent-git-active',activeTab==='gitflow');board.querySelectorAll('[data-agent-tab]').forEach(button=>{const selected=button.dataset.agentTab===activeTab;button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});board.querySelector('.agent-board-header h2').textContent={agents:'План агентов',activity:'Активные этапы',gitflow:'Gitflow'}[activeTab];}
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
  function activity(){
    current=null;
    content.innerHTML=`<p class="agent-note">Демо-сценарий · реальные агенты не запущены</p><div class="agent-activity-list"><button type="button" data-task="0"><span class="agent-state done">✓</span><span><strong>T01 · Подготовка проекта</strong><small>Завершён · пример</small></span></button><button type="button" data-task="1"><span class="agent-state active">●</span><span><strong>T02 · Каталог пространств</strong><small>Builder · выполняется параллельно</small></span></button><button type="button" data-task="2"><span class="agent-state active">●</span><span><strong>T03 · Интерфейс поиска</strong><small>Builder · выполняется параллельно</small></span></button><button type="button" data-task="3"><span class="agent-state waiting">○</span><span><strong>T04 · Интеграция и проверка</strong><small>Ожидает T02 и T03</small></span></button></div><p class="agent-tree-caption">Reviewer проверяет результат каждого задания</p>`;
    updateStatus();
  }
  function gitflow(){
    current=null;
    content.innerHTML=`<p class="agent-note">Схема ветвления · ветки показаны как пример и не создаются автоматически</p><div class="agent-git-diagram"><svg viewBox="0 0 740 248" role="img" aria-labelledby="gitflow-title gitflow-desc" xmlns="http://www.w3.org/2000/svg"><title id="gitflow-title">Демонстрационная схема Gitflow</title><desc id="gitflow-desc">От main начинается develop. Задачи T02 и T03 разрабатываются параллельно в отдельных feature-ветках и сливаются в develop. Из develop создаётся release для проверки и слияния в main. Hotfix ответвляется от main и возвращается в main и develop.</desc>
      <defs><marker id="git-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L6 3 L0 6" fill="none" stroke="#777" stroke-width="1"/></marker></defs>
      <g class="git-lanes"><path d="M155 23 H725"/><path d="M155 61 H725"/><path d="M155 99 H725"/><path d="M155 137 H725"/><path d="M155 175 H725"/><path d="M155 213 H725"/></g>
      <g class="git-labels"><g class="git-label-feature"><rect x="8" y="11" width="130" height="24"/><text x="17" y="28">feature / T02</text></g><g class="git-label-feature"><rect x="8" y="49" width="130" height="24"/><text x="17" y="66">feature / T03</text></g><g class="git-label-develop"><rect x="8" y="87" width="130" height="24"/><text x="17" y="104">develop</text></g><g class="git-label-release"><rect x="8" y="125" width="130" height="24"/><text x="17" y="142">release</text></g><g class="git-label-hotfix"><rect x="8" y="163" width="130" height="24"/><text x="17" y="180">hotfix</text></g><g class="git-label-main"><rect x="8" y="201" width="130" height="24"/><text x="17" y="218">main</text></g></g>
      <g class="git-flow-lines"><path d="M174 213 H650 M206 99 H650 M262 23 H404 M246 61 H353 M296 137 H405 M519 175 H557"/><path d="M174 213 C188 213 188 99 206 99 M206 99 C228 99 238 23 262 23 M206 99 C222 99 229 61 246 61 M353 61 C375 61 379 99 405 99 M404 23 C434 23 440 99 475 99 M280 99 C287 99 286 137 296 137 M405 137 C430 137 435 213 463 213 M405 137 C433 137 446 99 475 99 M463 213 C489 213 496 175 519 175 M519 175 C541 175 545 213 565 213 M519 175 C550 175 562 99 600 99"/></g>
      <g class="git-commits"><g class="git-feature"><circle cx="262" cy="23" r="8"/><circle cx="333" cy="23" r="8"/><circle cx="404" cy="23" r="8"/><circle cx="246" cy="61" r="8"/><circle cx="353" cy="61" r="8"/></g><g class="git-develop"><circle cx="206" cy="99" r="8"/><circle cx="280" cy="99" r="8"/><circle cx="405" cy="99" r="8"/><circle cx="475" cy="99" r="8"/><circle cx="600" cy="99" r="8"/></g><g class="git-release"><circle cx="296" cy="137" r="8"/><circle cx="405" cy="137" r="8"/></g><g class="git-hotfix"><circle cx="519" cy="175" r="8"/></g><g class="git-main"><circle cx="174" cy="213" r="8"/><circle cx="463" cy="213" r="8"/><circle cx="565" cy="213" r="8"/></g></g>
      <g class="git-versions"><g><rect x="151" y="230" width="46" height="16"/><text x="174" y="242" text-anchor="middle">старт</text></g><g><rect x="442" y="230" width="42" height="16"/><text x="463" y="242" text-anchor="middle">v1.0</text></g><g><rect x="544" y="230" width="42" height="16"/><text x="565" y="242" text-anchor="middle">v1.1</text></g></g>
    </svg></div>`;
    updateStatus();
  }
  function showTab(tab,restoreTask=false){activeTab=tab;updateTabs();content.scrollTop=0;if(tab==='agents'){if(restoreTask&&Number.isInteger(savedView.planTask)&&savedView.planTask>=0&&savedView.planTask<state.tasks.length)detail(savedView.planTask);else graph();}else if(tab==='activity')activity();else gitflow();saveView();}
  board.querySelector('.agent-board-tabs').addEventListener('click',e=>{const tab=e.target.closest('[data-agent-tab]');if(tab)showTab(tab.dataset.agentTab);});
  content.addEventListener('click',e=>{const b=e.target.closest('[data-task]');if(b){activeTab='agents';updateTabs();detail(Number(b.dataset.task));}});
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
  function position(){if(board.hidden||board.classList.contains('agent-expanded'))return;const rect=mascot.getBoundingClientRect();const width=window.innerWidth<=760?Math.min(390,window.innerWidth-16):Math.min(510,Math.max(300,rect.left-28));board.style.width=width+'px';if(moved){motion.targetX=clamp(Number(savedView.planX)||0,0,Math.max(0,window.innerWidth-board.offsetWidth));motion.targetY=clamp(Number(savedView.planY)||0,0,Math.max(0,window.innerHeight-board.offsetHeight));settle();return;}motion.targetX=Math.max(8,rect.left-width-18);motion.targetY=Math.max(8,Math.min(window.innerHeight-board.offsetHeight-8,rect.top+rect.height/2-board.offsetHeight/2));settle();}
  return {position,open(){board.classList.remove('agent-expanded','agent-revealing');board.hidden=false;position();if(savedView.planExpanded)board.classList.add('agent-expanded');showTab(activeTab,true);void board.offsetWidth;board.classList.add('agent-revealing');}};
};

// Demonstration only: no agents are started and no project analysis is performed.
window.createAgentPlan = function(root, mascot) {
  const key = 'makora.agent-plan-demo.v1';
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
  board.innerHTML=`<div class="agent-board-frame"><header class="agent-board-header"><div><small>ДЕМО · ТИХИЙ КАМПУС</small><h2>План агентов</h2></div><div><button type="button" data-agent-expand aria-label="Развернуть доску">⛶</button><button type="button" data-agent-close aria-label="Закрыть доску">×</button></div></header><div class="agent-board-content"></div><footer class="agent-board-footer"><span data-agent-status></span><button type="button" data-agent-approve>Утвердить план</button></footer></div>`;
  root.append(board);
  const content=board.querySelector('.agent-board-content'), status=board.querySelector('[data-agent-status]');
  let current=null;
  function save(){try{localStorage.setItem(key,JSON.stringify(state));}catch(_){}}
  function updateStatus(){status.textContent=state.approved?'● ПЛАН УТВЕРЖДЁН · ДЕМО':'○ ЧЕРНОВИК · ДЕМО';board.querySelector('[data-agent-approve]').textContent=state.approved?'Утверждено ✓':'Утвердить план';}
  function graph(){
    current=null;
    content.innerHTML=`<p class="agent-note">Пример плана · агенты не запускаются</p><div class="agent-tree"><div class="agent-tree-row"><button data-task="0"></button></div><div class="agent-branch" aria-hidden="true"></div><div class="agent-tree-row parallel"><button data-task="1"></button><button data-task="2"></button></div><div class="agent-merge" aria-hidden="true"></div><div class="agent-tree-row"><button data-task="3"></button></div></div><p class="agent-tree-caption">T02 и T03 могут выполняться параллельно</p>`;
    content.querySelectorAll('[data-task]').forEach(button=>{const t=state.tasks[Number(button.dataset.task)];button.innerHTML='<span></span><strong></strong><small></small>';button.querySelector('span').textContent=t.id;button.querySelector('strong').textContent=t.title;button.querySelector('small').textContent='Зависит: '+t.deps;});
    updateStatus();
  }
  const fields=[['goal','Цель'],['deps','Зависимости'],['contract','Контракт'],['mocks','Моки'],['tools','Инструменты'],['ready','Критерий готовности'],['builder','Промпт Builder'],['reviewer','Промпт Reviewer']];
  function detail(index){
    current=index; const task=state.tasks[index];
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
  board.querySelector('[data-agent-close]').onclick=()=>{board.hidden=true;};
  board.querySelector('[data-agent-expand]').onclick=()=>{board.classList.toggle('agent-expanded');position();};
  board.addEventListener('dblclick',e=>{if(e.target.closest('button,textarea,input,label'))return;board.classList.toggle('agent-expanded');position();});
  function position(){if(board.hidden||board.classList.contains('agent-expanded'))return;const rect=mascot.getBoundingClientRect();const width=Math.min(510,Math.max(300,rect.left-28));board.style.width=width+'px';board.style.left=Math.max(8,rect.left-width-18)+'px';board.style.top=Math.max(82,Math.min(window.innerHeight-board.offsetHeight-8,rect.top+rect.height/2-board.offsetHeight/2))+'px';}
  graph();
  return {position,open(){board.hidden=false;graph();position();}};
};

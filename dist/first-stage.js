(() => {
  const root = document.createElement('section');
  root.id = 'first-stage';
  root.setAttribute('aria-label', 'Анализ задания');
  root.innerHTML = `<div class="first-top"><a class="first-logo" href="/">✳ <span>макора</span></a><span>РАБОЧЕЕ ПРОСТРАНСТВО / 01</span><span>ЭТАП 01 / 06</span></div>
  <div class="first-intro"><div class="mascot-area" tabindex="0" role="img" aria-label="Макора. Перетащите мышью или перемещайте стрелками." title="Перетащить Макору"><iframe class="mascot-frame" src="mascot.html" title="Персонаж Макоры" tabindex="-1"></iframe></div>
  <form class="first-form"><div class="speech-label">ПЕРВЫЙ ШАГ <span>01 / 06</span></div><h1>Привет!<br>Разберём задание?</h1><p>Пришли условие хакатона — соберём всё важное в одном месте.</p>
  <label class="pixel-drop"><input type="file" accept=".pdf,.doc,.docx,.txt,.md" class="sr-only"><span class="pixel-plus" aria-hidden="true"><svg viewBox="0 0 24 24" width="28" height="28" shape-rendering="crispEdges"><path fill="currentColor" d="M2 5h8v2h12v14H2zm2 4v10h16V9z"/><path fill="currentColor" d="M11 11h2v2h2v2h-2v2h-2v-2H9v-2h2z"/></svg></span><strong class="file-label">Выбрать файл</strong><small>или перетащить сюда<br>PDF, DOCX, TXT, MD · до 20 МБ</small></label><div class="or-line"><span>ИЛИ ВСТАВЬ ТЕКСТ</span></div><label class="sr-only" for="first-text">Текст задания</label><textarea id="first-text" placeholder="Вставь условие задания сюда…"></textarea><p class="first-error" role="alert" hidden></p><button class="pixel-start" type="submit" disabled>Начать анализ <span aria-hidden="true">▶</span></button><p class="first-disclaimer">Демо: загрузка и анализ имитируются. После этапа 4 доступен учебный маршрут разработки.</p></form></div>
  <div class="board-scene" hidden><div class="board-heading"><span>01 / АНАЛИЗ ЗАДАНИЯ</span><span>01_CASE_ANALYSIS.MD</span></div><div class="board-stage"><div class="board-mascot" aria-hidden="true"></div><div class="board" aria-label="Доска рабочего пространства"><nav class="board-stages" aria-label="Этапы проекта"><button type="button" data-board-stage="1">01 <span>Анализ</span></button><button type="button" data-board-stage="2">02 <span>Идея</span></button><button type="button" data-board-stage="3">03 <span>План</span></button><button type="button" data-board-stage="4">04 <span>Мок-данные</span></button></nav><div class="board-stage-message" role="status" hidden></div><div class="board-sprite"><img class="board-shadow-art" src="analysis-board.png" alt="" draggable="false"><img class="board-art" src="analysis-board.png" alt="" draggable="false"></div><div class="board-inner"><div class="board-bar"><div><span class="board-kicker">ДЕМО-КЕЙС / ТИХИЙ КАМПУС</span><h2>Анализ задания<span>.</span></h2></div><button type="button" class="board-expand" aria-label="Развернуть доску" title="Развернуть доску">⛶</button></div><div class="board-content"></div><div class="board-footer"><span>ТЯНИ ЗА РАМКУ · ДВОЙНОЙ КЛИК — НА ВЕСЬ ЭКРАН</span><span>01 / 06</span></div></div></div></div><div class="scene-bottom"><p>Демо-анализ: показан пример, файл не анализируется.</p><button type="button" class="board-next">Далее <span>→</span></button></div></div>`;
  document.body.append(root);
  document.body.classList.add('first-stage-active');
  const underneath = document.querySelectorAll('body > header, body > main');
  underneath.forEach(el => el.inert = true);
  const form = root.querySelector('form'), input = root.querySelector('input[type=file]'), textarea = root.querySelector('textarea');
  const drop = root.querySelector('.pixel-drop'), error = root.querySelector('.first-error'), start = root.querySelector('.pixel-start');
  let selectedFile = null;
  function update() { start.disabled = !selectedFile && !textarea.value.trim(); }
  function setFile(file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) { error.textContent = 'Файл больше 20 МБ. Выбери другой файл.'; error.hidden = false; selectedFile = null; input.value = ''; update(); return; }
    error.hidden = true; selectedFile = file; root.querySelector('.file-label').textContent = file.name; update();
  }
  input.addEventListener('change', () => setFile(input.files[0]));
  textarea.addEventListener('input', update);
  ['dragenter','dragover'].forEach(type => drop.addEventListener(type, e => { e.preventDefault(); drop.classList.add('dragging'); }));
  ['dragleave','drop'].forEach(type => drop.addEventListener(type, e => { e.preventDefault(); drop.classList.remove('dragging'); }));
  drop.addEventListener('drop', e => setFile(e.dataTransfer.files[0]));
  const frame = root.querySelector('iframe');
  function animate(mode) { try { frame.contentDocument.querySelector(`[data-mode="${mode}"]`)?.click(); } catch (_) {} }
  function spinWheel(duration = 2200) {
    try {
      const wheel = frame.contentDocument.querySelector('[data-action="wheel"]');
      if (!wheel || wheel.classList.contains('active')) return;
      wheel.click();
      setTimeout(() => { if (wheel.isConnected && wheel.classList.contains('active')) wheel.click(); }, duration);
    } catch (_) {}
  }
  frame.addEventListener('load', () => animate('idle'));
  const mascotArea = root.querySelector('.mascot-area');
  const prototypeHandoff = window.createPrototypeHandoff(root, mascotArea, () => textarea.value.trim() ? null : selectedFile);
  let mascotDrag = null;
  function notifyMascot(phase, x, y) {
    try { frame.contentWindow.dispatchEvent(new frame.contentWindow.CustomEvent('makora-drag', {detail:{phase, x, y}})); } catch (_) {}
  }
  function fixMascot() {
    const rect = mascotArea.getBoundingClientRect();
    if (getComputedStyle(mascotArea).position !== 'fixed') {
      const space = document.createElement('div');
      space.className = 'mascot-space';
      space.setAttribute('aria-hidden', 'true');
      Object.assign(space.style, {width:rect.width+'px', height:rect.height+'px', marginTop:getComputedStyle(mascotArea).marginTop, flex:'none'});
      mascotArea.before(space);
    }
    Object.assign(mascotArea.style, {position:'fixed', left:rect.left+'px', top:rect.top+'px', width:rect.width+'px', height:rect.height+'px', minHeight:'0', margin:'0'});
    return rect;
  }
  function moveMascot(left, top) {
    mascotArea.style.left = Math.max(0, Math.min(left, window.innerWidth - mascotArea.offsetWidth)) + 'px';
    mascotArea.style.top = Math.max(0, Math.min(top, window.innerHeight - mascotArea.offsetHeight)) + 'px';
    prototypeHandoff.updatePosition();
  }
  mascotArea.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const rect = fixMascot();
    mascotDrag = {id:e.pointerId, x:e.clientX, y:e.clientY, left:rect.left, top:rect.top};
    mascotArea.classList.add('carried');
    mascotArea.setPointerCapture(e.pointerId);
    notifyMascot('start', e.clientX, e.clientY);
    e.preventDefault();
  });
  mascotArea.addEventListener('pointermove', e => {
    if (!mascotDrag || mascotDrag.id !== e.pointerId) return;
    moveMascot(mascotDrag.left + e.clientX - mascotDrag.x, mascotDrag.top + e.clientY - mascotDrag.y);
    notifyMascot('move', e.clientX, e.clientY);
  });
  function releaseMascot(e) {
    if (!mascotDrag || mascotDrag.id !== e.pointerId) return;
    mascotDrag = null;
    mascotArea.classList.remove('carried');
    notifyMascot('end', e.clientX, e.clientY);
    if (mascotArea.hasPointerCapture(e.pointerId)) mascotArea.releasePointerCapture(e.pointerId);
  }
  ['pointerup','pointercancel','lostpointercapture'].forEach(type => mascotArea.addEventListener(type, releaseMascot));
  mascotArea.addEventListener('keydown', e => {
    const delta = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]}[e.key];
    if (!delta) return;
    e.preventDefault();
    const rect = fixMascot(), step = e.shiftKey ? 40 : 12;
    moveMascot(rect.left + delta[0] * step, rect.top + delta[1] * step);
  });

  const board = root.querySelector('.board'), content = root.querySelector('.board-content');
  const workspace = document.querySelector('body > main .layout');
  const workspaceHome = workspace.parentElement;
  const stageDownloads = {main:document.querySelector('#download').onclick, concept:document.querySelector('#download-concept').onclick};
  const boardTitles = ['Анализ задания','Разработка идеи','Планирование разработки','Подготовка мок-данных','Разработка'];
  const stageMessage = root.querySelector('.board-stage-message');
  const workspaceViewKey='makora.workspace-view.v1';
  let savedWorkspaceView={};try{savedWorkspaceView=JSON.parse(localStorage.getItem(workspaceViewKey))||{};}catch(_){}
  let boardStage = 1, stageSwitchInProgress = false, stage3DetailOpen = false, stage4DetailOpen = false;
  const boardBar=root.querySelector('.board-bar'),expandButton=boardBar.querySelector('.board-expand');
  const boardActions=document.createElement('div');boardActions.className='board-actions';
  const versionButton=document.createElement('button');versionButton.type='button';versionButton.className='board-version';versionButton.textContent='Файлы версии';
  expandButton.replaceWith(boardActions);boardActions.append(versionButton,expandButton);
  let versionDocuments=null;
  function showVersionFiles(){
    const data=versionDocuments;if(!data)return;
    content.innerHTML=`<div class="revision-nav"><button type="button" data-version-exit>← К этапу</button><span>${esc(data.revision_id)}</span></div><div class="revision-list">${data.documents.length?data.documents.map((file,i)=>`<button type="button" data-version-file="${i}"><span>${esc(file.path)}${file.is_demo?' · демо':''}</span><span>↗</span></button>`).join(''):'<p>Для этого этапа в текущей версии нет текстовых файлов.</p>'}</div>${data.omitted.length?`<p class="revision-note">Часть файлов не показана из-за размера или формата: ${esc(data.omitted.join(', '))}</p>`:''}`;
    content.scrollTop=0;
  }
  versionButton.onclick=async()=>{
    const requestedStage=stage;
    try{
      const data=await prototypeHandoff.currentDocuments(requestedStage);
      if(stage!==requestedStage)return;
      versionDocuments=data;stageMessage.hidden=true;
      if(workspace.parentElement===content)workspaceHome.append(workspace);
      board.classList.remove('workspace-board','plan-index-board','idea-board');board.classList.add('revision-view');
      showVersionFiles();
    }catch(error){stageMessage.textContent=error.message||'Не удалось открыть файлы версии.';stageMessage.hidden=false;}
  };
  content.addEventListener('click',event=>{
    if(!board.classList.contains('revision-view'))return;
    const fileButton=event.target.closest('[data-version-file]');
    if(fileButton){const file=versionDocuments?.documents[Number(fileButton.dataset.versionFile)];if(!file)return;const body=/\.md$/i.test(file.path)?render(file.content):`<pre class="case-source">${esc(file.content)}</pre>`;content.innerHTML=`<div class="revision-nav"><button type="button" data-version-list>← Все файлы</button><span>${esc(versionDocuments.revision_id)}</span></div><div class="board-document"><div class="board-doc-number">${esc(file.path)}</div>${body}</div>`;content.scrollTop=0;return;}
    if(event.target.closest('[data-version-list]'))showVersionFiles();
    if(event.target.closest('[data-version-exit]')){board.classList.remove('revision-view');openBoardStage(boardStage);}
  });
  function syncBoardStage() {
    board.classList.remove('revision-view');
    root.querySelector('.board-kicker').textContent='ДЕМО-КЕЙС / ТИХИЙ КАМПУС';
    if (stage === 4 && boardStage !== 4) { stage4DetailOpen = false; stage3DetailOpen = false; }
    boardStage = stage;
    savedWorkspaceView={...savedWorkspaceView,stage};
    try{localStorage.setItem(workspaceViewKey,JSON.stringify(savedWorkspaceView));}catch(_){}
    const working = stage > 4 || (stage === 4 && stage4DetailOpen) || (stage === 3 && stage3DetailOpen);
    board.classList.toggle('plan-index-board', (stage === 3 && !stage3DetailOpen) || (stage === 4 && !stage4DetailOpen));
    board.classList.toggle('idea-board', stage === 2);
    root.querySelector('.board-footer span:last-child').textContent = String(stage).padStart(2,'0') + ' / 06';
    board.classList.toggle('workspace-board', working);
    const stageStatuses=window.makoraDemoWorkflow.getStageStatuses();
    root.querySelectorAll('[data-board-stage]').forEach(button => {
      const number=Number(button.dataset.boardStage),status=stageStatuses[number]||'locked',locked=status==='locked';
      const active = Number(button.dataset.boardStage) === stage;
      button.classList.toggle('active', active);
      button.classList.toggle('locked',locked);
      button.dataset.status=status;
      button.setAttribute('aria-disabled','false');
      button.title=locked?window.makoraDemoWorkflow.getGateMessage(number):`Этап ${String(number).padStart(2,'0')} · ${status==='approved'?'утверждён':'доступен'}`;
      if (active) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current');
    });
    root.querySelector('.board-bar h2').textContent = boardTitles[stage-1] || 'Рабочее пространство';
    if (stage === 2 && workspace.parentElement === content) { workspaceHome.append(workspace); showIdeaHome(); }
    if (stage === 3 && !stage3DetailOpen && workspace.parentElement === content) { workspaceHome.append(workspace); showPlanningIndex(); }
    if (stage === 4 && !stage4DetailOpen && workspace.parentElement === content) { workspaceHome.append(workspace); showMockIndex(); }
    root.querySelector('.board-heading span:first-child').textContent = String(stage).padStart(2,'0') + ' / ' + (boardTitles[stage-1] || 'РАЗРАБОТКА').toUpperCase();
    root.querySelector('.board-heading span:last-child').textContent = stage === 1 ? '01_CASE_ANALYSIS.MD' : 'РАБОЧЕЕ ПРОСТРАНСТВО';
    root.querySelector('.scene-bottom > p').textContent = stage >= 3 ? window.makoraDemo.notice : stage === 1 ? 'Демо-анализ: показан пример, файл не анализируется.' : 'Учебный кейс «Тихий кампус» · исследование и идея — демонстрационные материалы.';
    const next = root.querySelector('.board-next');
    next.hidden = stage === 2 || stage >= 4;
    next.innerHTML = (stage === 1 ? 'Далее' : 'К мок-данным') + ' <span>→</span>';
  }
  async function openBoardStage(number) {
    if (stageSwitchInProgress) return;
    if(!window.makoraDemoWorkflow.canOpenStage(number)){
      stageMessage.textContent=window.makoraDemoWorkflow.getGateMessage(number);
      stageMessage.hidden=false;
      return;
    }
    stageMessage.hidden = true;
    stageSwitchInProgress = true;
    try {
      if (number === 1) {
        workspaceHome.append(workspace);
        stage = 1;
        showIndex();
      } else {
        content.replaceChildren(workspace);
        document.querySelector('#empty').hidden = true;
        if (number < 4) document.querySelector('#stage4-files')?.remove();
        if (number === 2) {
          document.querySelector('#next-stage').click();
          document.querySelector('#download').onclick = stageDownloads.main;
          document.querySelector('#download-concept').onclick = stageDownloads.concept;
        } else if (number === 3) { stage3DetailOpen = false; document.querySelector('#next-stage-3').click(); }
        else if (number === 4) { stage4DetailOpen = false; await window.openMockStage({preview:true}); }
        content.scrollTop = 0;
      }
      window.makoraDemoWorkflow.setActiveStage(number);
      syncBoardStage();
    } finally { stageSwitchInProgress = false; }
  }
  root.querySelector('.board-stages').addEventListener('click', e => {
    const button = e.target.closest('[data-board-stage]');
    if (button) openBoardStage(Number(button.dataset.boardStage));
  });
  new MutationObserver(() => { if (root.isConnected && root.classList.contains('departing')) syncBoardStage(); }).observe(document.querySelector('.page-heading'), {childList:true,subtree:true});

  const mockItems = ['Потребности в данных','Наборы данных','Тестовые сценарии','API-заглушки','Валидация'];
  function showMockIndex() {
    stage4DetailOpen = false;
    workspaceHome.append(workspace);
    board.classList.remove('workspace-board');
    board.classList.add('plan-index-board');
    content.innerHTML = '<div class="plan-board-list">' + mockItems.map((title,i)=>`<button type="button" data-mock-item="${i}" title="${esc(title)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(title)}</strong><span>↗</span></button>`).join('') + '</div>';
    content.scrollTop = 0;
  }
  function showMockStep(index) {
    stage4DetailOpen = true;
    board.classList.add('workspace-board');
    board.classList.remove('plan-index-board');
    const back = document.createElement('button');
    back.type = 'button';
    back.className = 'board-back plan-workspace-back';
    back.dataset.mockHome = '';
    back.textContent = '← Все разделы мок-данных';
    content.replaceChildren(back, workspace);
    document.querySelectorAll('#doc-content .doc-row')[index]?.click();
    content.scrollTop = 0;
  }
  content.addEventListener('click', e => {
    if (stage !== 4) return;
    const item = e.target.closest('[data-mock-item]');
    if (item) showMockStep(Number(item.dataset.mockItem));
    else if (e.target.closest('[data-mock-home]')) showMockIndex();
  });

  const planItems = ['Диаграмма C1','Диаграмма C2','Диаграмма C3','Модель данных · ER','Контракты','План тестирования','Декомпозиция','Валидация','Диаграмма C4 · при необходимости'];
  const diagrams = [
    {title:'Модель данных · ER', note:'Логическая модель демонстрационных данных. Диаграмма при необходимости; наличие базы данных не предполагается.', nodes:[['Space','id · name · building','capacity · availableSeats','status · updatedAt · source'],['SpacesResponse','items: Space[]'],['Фикстура','JSON · 0..* Space'],['Error','code · message']], edges:[[1,0,'1 → 0..*'],[2,0,'1 → 0..*']]},
    {title:'C1 · Контекст', note:'Граница системы и внешние участники. Источник актуальной занятости не подтверждён.', nodes:[['Студент','ищет свободное место'],['Тихий кампус','сервис поиска мест'],['Источник занятости','внешний API · не подтверждён'],['Демо-данные','резервный источник']], edges:[[0,1],[1,2],[1,3]]},
    {title:'C2 · Контейнеры', note:'Предварительная структура приложения; выбранный стек и источник необходимо согласовать.', nodes:[['Веб-интерфейс','каталог · фильтры · карточка'],['API пространств','HTTP · модель Space'],['Источник занятости','данные извне · не подтверждён'],['Каталог и фикстуры','локальные CSV / JSON']], edges:[[0,1],[1,2],[1,3]]},
    {title:'C3 · Компоненты', note:'Планируемые компоненты API; границы модулей уточняются при разработке.', nodes:[['API маршруты','список · карточка'],['Сервис каталога','нормализация · фильтрация'],['Адаптер занятости','статусы · время обновления'],['Адаптер фикстур','резерв · source=demo']], edges:[[0,1],[1,2],[1,3]]},
    {title:'C4 · Код (при необходимости)', note:'Необязательная иллюстрация планируемого кода; уточняется во время разработки.', nodes:[['spaces route','GET список / карточка'],['SpaceService','фильтрация · получение'],['OccupancyAdapter','загрузка статуса'],['Space / Error','модели контракта']], edges:[[0,1],[1,2],[1,3]]}
  ];
  function diagramSvg(d) {
    const locations = [[20,50],[345,50],[670,50],[345,240]], w=210, h=90;
    const rects = locations.map(([x,y])=>({x,y,cx:x+w/2,cy:y+h/2}));
    const links=d.edges.map(([a,b,label])=>{
      const p=rects[a], q=rects[b], dx=q.cx-p.cx, dy=q.cy-p.cy;
      const from=Math.min(dx ? (w/2)/Math.abs(dx) : Infinity,dy ? (h/2)/Math.abs(dy) : Infinity);
      const to=Math.min(dx ? (w/2+5)/Math.abs(dx) : Infinity,dy ? (h/2+5)/Math.abs(dy) : Infinity);
      return `<line x1="${p.cx+dx*from}" y1="${p.cy+dy*from}" x2="${q.cx-dx*to}" y2="${q.cy-dy*to}" stroke="#bcbcbc" stroke-width="2" marker-end="url(#board-diagram-arrow)"/>${label?`<text x="${(p.cx+q.cx)/2}" y="${(p.cy+q.cy)/2-8}" text-anchor="middle" fill="#fff" font-size="12">${esc(label)}</text>`:''}`;
    }).join('');
    const nodes=d.nodes.map((lines,i)=>{const {x,y}=rects[i];return `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="#1d1d24" stroke="#a59caf" stroke-width="2"/><text x="${x+w/2}" y="${y+29}" text-anchor="middle" fill="#fff" font-size="16" font-weight="700">${esc(lines[0])}</text>${lines.slice(1).map((line,j)=>`<text x="${x+w/2}" y="${y+51+j*16}" text-anchor="middle" fill="#ddd" font-size="12">${esc(line)}</text>`).join('')}</g>`}).join('');
    return `<svg viewBox="0 0 900 380" role="img" aria-label="${esc(d.title)}"><defs><marker id="board-diagram-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8Z" fill="#bcbcbc"/></marker></defs>${links}${nodes}</svg>`;
  }
  function showPlanningIndex() {
    stage3DetailOpen = false;
    workspaceHome.append(workspace);
    board.classList.remove('workspace-board');
    board.classList.add('plan-index-board');
    content.innerHTML = '<div class="plan-board-list">'+planItems.map((title,i)=>`<button type="button" data-plan-item="${i}" title="${esc(title)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(title)}</strong><span>↗</span></button>`).join('')+'</div>';
    content.scrollTop = 0;
  }
  function showPlanningDiagram(index) {
    const d=diagrams[index];
    content.innerHTML = `<div class="plan-board-detail"><button type="button" class="board-back plan-board-back" data-plan-home>← Все разделы</button>${window.makoraDemo.markup()}<div class="plan-board-heading"><h3>${esc(d.title)}</h3><button type="button" class="plan-diagram-expand" aria-label="Открыть схему на весь экран">⛶</button></div><p>${esc(d.note)}</p><div class="diagram-shell"><div id="plan-board-diagram" class="mermaid-diagram">${diagramSvg(d)}</div></div><button type="button" class="plan-secondary" data-plan-approval>Согласовать архитектуру →</button></div>`;
    content.querySelector('.plan-diagram-expand').onclick=e=>window.makoraStage3.openDiagram(content.querySelector('#plan-board-diagram'),e.currentTarget);
    content.scrollTop = 0;
  }
  function showPlanningStep(index) {
    stage3DetailOpen = true;
    board.classList.add('workspace-board');
    board.classList.remove('plan-index-board');
    const back=document.createElement('button');
    back.type='button';back.className='board-back plan-workspace-back';back.dataset.planHome='';back.textContent='← Все разделы планирования';
    content.replaceChildren(back,workspace);
    document.querySelectorAll('#doc-content .doc-row')[index]?.click();
    content.scrollTop=0;
  }
  content.addEventListener('click', e => {
    if (stage !== 3) return;
    const item=e.target.closest('[data-plan-item]');
    if (item) {const i=Number(item.dataset.planItem);if(i<4)showPlanningDiagram([1,2,3,0][i]);else if(i===8)showPlanningDiagram(4);else showPlanningStep(i-3);}
    else if(e.target.closest('[data-plan-home]')) showPlanningIndex();
    else if(e.target.closest('[data-plan-approval]')) showPlanningStep(0);
  });

  let ideaGroup = null;
  const ideaGroups = {
    research:{title:'Исследование', file:'02_research.md', docs:researchBlocks},
    solution:{title:'Решение', file:'02_solution_concept.md', docs:conceptBlocks}
  };
  function showIdeaHome() {
    ideaGroup = null;
    content.innerHTML = `<div class="idea-groups"><button type="button" data-idea-group="research"><span class="idea-card-number">01 / 02</span><strong>Исследование</strong><span class="idea-card-caption">5 разделов</span><span class="idea-card-arrow">↗</span></button><button type="button" data-idea-group="solution"><span class="idea-card-number">02 / 02</span><strong>Решение</strong><span class="idea-card-caption">9 разделов</span><span class="idea-card-arrow">↗</span></button></div>`;
    content.scrollTop = 0;
  }
  function showIdeaGroup(group) {
    ideaGroup = group;
    const item = ideaGroups[group];
    content.innerHTML = `<div class="idea-breadcrumb"><button type="button" class="board-back" data-idea-home>← ${item.title}</button><button type="button" class="idea-export" data-idea-export title="Скачать ${item.file}">Скачать ↓</button></div><h3 class="idea-group-title">${item.title}</h3><div class="idea-sections">${item.docs.map((doc,i)=>`<button type="button" data-idea-item="${i}" title="${esc(doc.title)}"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(doc.title)}</strong><span>↗</span></button>`).join('')}</div>`;
    content.scrollTop = 0;
  }
  function showIdeaDocument(index) {
    const item = ideaGroups[ideaGroup], doc = item?.docs[index];
    if (!doc) return;
    const approval=ideaGroup==='solution'&&doc.title==='Финальная идея' ? `<div class="idea-approval"><p>${window.makoraProject.isApproved()?'Идея утверждена. Изменение исходных материалов или идеи потребует перепроверки плана.':'Идея не утверждена. План и данные ниже пока являются примером для «Тихого кампуса».'}</p><button type="button" class="plan-primary" data-idea-approve>Утвердить идею</button></div>` : '';
    content.innerHTML = `<div class="idea-breadcrumb"><button type="button" class="board-back" data-idea-back>← ${item.title}</button><button type="button" class="board-back" data-idea-home>Все части</button></div><div class="board-document"><div class="board-doc-number">${String(index+1).padStart(2,'0')} / ${String(item.docs.length).padStart(2,'0')} · ${item.file}</div>${render(doc.md)}<button type="button" class="plan-secondary" data-idea-edit="${index}">Изменить Markdown</button>${approval}</div>`;
    content.scrollTop = 0;
  }
  content.addEventListener('click', e => {
    if (stage !== 2) return;
    const group = e.target.closest('[data-idea-group]'), item = e.target.closest('[data-idea-item]');
    if (group) showIdeaGroup(group.dataset.ideaGroup);
    else if (item) showIdeaDocument(Number(item.dataset.ideaItem));
    else if (e.target.closest('[data-idea-home]')) showIdeaHome();
    else if (e.target.closest('[data-idea-back]')) showIdeaGroup(ideaGroup);
    else if (e.target.closest('[data-idea-export]')) exportMarkdown(ideaGroups[ideaGroup].file, ideaGroups[ideaGroup].docs);
    else if (e.target.closest('[data-idea-approve]')) { if(!window.makoraProject.approve()){stageMessage.textContent='Не удалось сохранить утверждение на устройстве.';stageMessage.hidden=false;} showIdeaDocument(ideaGroups.solution.docs.findIndex(x=>x.title==='Финальная идея')); }
    else if (e.target.closest('[data-idea-edit]')) {const i=Number(e.target.closest('[data-idea-edit]').dataset.ideaEdit),doc=ideaGroups[ideaGroup].docs[i];content.innerHTML=`<div class="idea-breadcrumb"><button type="button" class="board-back" data-idea-back>← ${ideaGroups[ideaGroup].title}</button></div><label class="idea-editor-label" for="idea-editor">${esc(doc.title)} · Markdown</label><textarea id="idea-editor" class="idea-editor"></textarea><button type="button" class="plan-primary" data-idea-save="${i}">Сохранить</button><p class="idea-editor-status" role="status"></p>`;content.querySelector('#idea-editor').value=doc.md;content.querySelector('#idea-editor').focus();}
    else if (e.target.closest('[data-idea-save]')) {const i=Number(e.target.closest('[data-idea-save]').dataset.ideaSave),value=content.querySelector('#idea-editor').value.trim();if(!value){content.querySelector('.idea-editor-status').textContent='Введите текст раздела.';return;}if(!window.makoraProject.saveDocument(ideaGroups[ideaGroup].docs[i],value)){content.querySelector('.idea-editor-status').textContent='Не удалось сохранить данные на устройстве.';return;}showIdeaDocument(i);}
  });
  function showIndex() {
    content.innerHTML = '<div class="board-intro">ВЫБЕРИ РАЗДЕЛ, ЧТОБЫ ОТКРЫТЬ ЕГО</div><div class="board-list">' + oneTitles.map((title,i) => `<button type="button" data-section="${i}" title="${esc(title)}"><span class="board-number">${String(i+1).padStart(2,'0')}</span><span>${title}</span><span class="board-arrow">↗</span></button>`).join('') + '</div>';
  }
  function showSection(i) {
    const source=window.makoraProject.source();
    const original=i===0&&source?`<h2>Ваше исходное условие</h2><p>${esc(source.name)}. ${source.text?'Текст сохранён на этом устройстве и передаётся в контекст задания агенту.':'Файл выбран, но извлечение текста этого формата не подключено.'}</p>${source.text?`<pre class="case-source">${esc(source.text)}</pre>`:''}<p>Ниже показан учебный пример: автоматический анализ вашего условия пока не подключён.</p>`:'';
    content.innerHTML = `<button type="button" class="board-back">← Все разделы</button><div class="board-document"><div class="board-doc-number">${String(i+1).padStart(2,'0')} / 10</div>${original}${render(one[i])}</div>`;
    content.scrollTop = 0;
  }
  content.addEventListener('click', e => { const section=e.target.closest('[data-section]'); if(section) showSection(Number(section.dataset.section)); if(stage===1 && e.target.closest('.board-back')) showIndex(); });
  // The board keeps its navigation, while approved revision files supply its content.
  let artifactRequest=0, currentFixtureFiles=[], noRevisionUntil=0;
  window.addEventListener('makora-revision-updated',()=>{noRevisionUntil=0;});
  function currentFallback(s,index,group){
    board.classList.remove('revision-view');root.querySelector('.board-kicker').textContent='ДЕМО-КЕЙС / ТИХИЙ КАМПУС';
    root.querySelector('.scene-bottom > p').textContent=(s>=3?window.makoraDemo.notice:'Демо-анализ: показан пример, файл не анализируется.')+' Этап 06 находится в разработке.';
    if(s===1)showSection(index);
    else if(s===2){ideaGroup=group;showIdeaDocument(index);}
    else if(s===3){if(index<4)showPlanningDiagram([1,2,3,0][index]);else if(index===8)showPlanningDiagram(4);else showPlanningStep(index-3);}
    else if(s===4)showMockStep(index);
  }
  function sectionFromMarkdown(text,title){
    const normalize=value=>value.toLowerCase().replace(/ё/g,'е').replace(/[^a-zа-я0-9]+/g,' ').trim().replace(/^\d+\s*/, '');
    const wanted=normalize(title),lines=text.split('\n');let start=-1,level=0;
    for(let i=0;i<lines.length;i++){const m=lines[i].match(/^(#{1,3})\s+(.+)$/);if(!m)continue;const heading=normalize(m[2]);if(heading===wanted||heading.startsWith(wanted+' ')||wanted.startsWith(heading+' ')){start=i;level=m[1].length;break;}}
    if(start<0)return {text,whole:true};
    let end=lines.length;for(let i=start+1;i<lines.length;i++){const m=lines[i].match(/^(#{1,3})\s+/);if(m&&m[1].length<=level){end=i;break;}}
    return {text:lines.slice(start,end).join('\n').trim(),whole:false};
  }
  function artifactCandidates(s,index,group,files){
    const find=pattern=>files.find(f=>pattern.test(f.path));
    if(s===1){const specific=[/problem.statement/i,/requirements/i,/desired/i,/opportunities/i,/constraints/i,/evaluation/i,/submission/i,/resources/i,/open.questions/i,/risk/i][index];return find(specific)||find(/01.*case.analysis/i);}
    if(s===2){const title=ideaGroups[group]?.docs[index]?.title||'';if(/user flow/i.test(title)){const f=find(/user[_-]?flow/i);if(f)return f;}if(/task flow/i.test(title)){const f=find(/task[_-]?flows?/i);if(f)return f;}return find(group==='research'?/02.*research/i:/02.*(solution|concept)/i);}
    if(s===3){const patterns=[/c1[-_].*(context|контекст)/i,/c2[-_].*(container|контейнер)/i,/c3[-_].*(component|компонент)/i,/(data.model|er.diagram)/i,/openapi\.(yaml|yml|json)$/i,/(test.plan|test_plan)/i,/(03_tasks|tasks)\.(json|ya?ml)$/i,/(03_validation|validation.report)/i,/c4[-_].*(code|код)/i];return find(patterns[index])||(index<4||index===8?find(/03.*architecture/i):null);}
    if(s===4){const patterns=[/(04_mock_data|data.requirements|data.needs)/i,/\/(?:fixtures)\//i,/scenarios\.json$/i,/mock.api.*readme\.md$/i,/(04_validation|mock.validation)/i];return find(patterns[index]);}
    return null;
  }
  async function showRevisionArtifact(s,index,group,request){
    if(Date.now()<noRevisionUntil)return false;
    let data;
    try{data=await prototypeHandoff.currentDocuments(s);}catch(error){
      if(localStorage.getItem('makora.current-revision.v1')){stageMessage.textContent='Не удалось загрузить текущую ревизию. Проверь локальный сервер.';stageMessage.hidden=false;content.innerHTML='<button type="button" data-current-back>← К разделам</button><p>Текущая версия недоступна.</p>';return true;}
      noRevisionUntil=Date.now()+5000;return false;
    }
    if(request!==artifactRequest||stage!==s)return true;
    if(data.reason==='initial'){noRevisionUntil=Date.now()+5000;return false;}
    try{localStorage.setItem('makora.current-revision.v1',data.revision_id);}catch{}
    const files=(data.documents||[]).filter(f=>!f.is_demo),file=artifactCandidates(s,index,group,files);
    if(!file){const omitted=artifactCandidates(s,index,group,(data.omitted||[]).map(path=>({path})));if(omitted){content.innerHTML=`<button type="button" data-current-back>← К разделам</button><p>Файл ${esc(omitted.path)} не показан из-за размера или формата.</p>`;return true;}return false;}
    if(workspace.parentElement===content)workspaceHome.append(workspace);
    board.classList.remove('workspace-board','plan-index-board','idea-board');board.classList.add('revision-view');
    root.querySelector('.board-kicker').textContent='ТЕКУЩАЯ РЕВИЗИЯ';
    root.querySelector('.scene-bottom > p').textContent='Показаны файлы согласованной версии '+data.revision_id+'.';
    const title=s===1?oneTitles[index]:s===2?ideaGroups[group].docs[index].title:s===3?planItems[index]:mockItems[index];
    const nav=`<div class="revision-nav"><button type="button" data-current-back>← К разделам</button><span>${esc(data.revision_id)}</span></div>`;
    if(s===4&&index===1){
      currentFixtureFiles=files.filter(f=>/\/(?:fixtures)\//i.test(f.path));
      content.innerHTML=nav+`<div class="board-document"><h2>${esc(title)}</h2><div class="revision-list">${currentFixtureFiles.map((f,i)=>`<button type="button" data-current-fixture="${i}">${esc(f.path)} ↗</button>`).join('')}</div><pre class="case-source" data-current-preview>${esc(currentFixtureFiles[0]?.content||'')}</pre></div>`;
    }else{
      const selected=/\.md$/i.test(file.path)?sectionFromMarkdown(file.content,title):{text:file.content,whole:false};
      const body=/\.md$/i.test(file.path)?render(selected.text):`<pre class="case-source">${esc(selected.text)}</pre>`;
      content.innerHTML=nav+`<div class="board-document"><div class="board-doc-number">${esc(file.path)} · СОГЛАСОВАННАЯ ВЕРСИЯ</div>${selected.whole?'<p>Отдельный заголовок не найден — показан документ целиком.</p>':''}${body}</div>`;
    }
    content.scrollTop=0;return true;
  }
  content.addEventListener('click',event=>{
    const back=event.target.closest('[data-current-back]');if(back){event.stopImmediatePropagation();board.classList.remove('revision-view');if(stage===1)showIndex();else if(stage===2)showIdeaGroup(ideaGroup);else if(stage===3)showPlanningIndex();else if(stage===4)showMockIndex();return;}
    const fixture=event.target.closest('[data-current-fixture]');if(fixture){event.stopImmediatePropagation();const preview=content.querySelector('[data-current-preview]');if(preview)preview.textContent=currentFixtureFiles[Number(fixture.dataset.currentFixture)]?.content||'';return;}
    const targets={1:'[data-section]',2:'[data-idea-item]',3:'[data-plan-item]',4:'[data-mock-item]'},target=event.target.closest(targets[stage]||'[data-never]');
    if(!target)return;
    event.stopImmediatePropagation();const s=stage,group=ideaGroup,index=Number(target.dataset.section??target.dataset.ideaItem??target.dataset.planItem??target.dataset.mockItem),request=++artifactRequest;
    content.innerHTML='<p class="revision-note" role="status">Открываю документ…</p>';
    showRevisionArtifact(s,index,group,request).then(shown=>{if(!shown&&request===artifactRequest&&stage===s)currentFallback(s,index,group);});
  },true);
  function updateFullscreen(expanded) {
    if (expanded) settleBoard();
    board.classList.toggle('expanded', expanded);
    const button = root.querySelector('.board-expand');
    button.textContent = expanded ? '×' : '⛶';
    button.setAttribute('aria-label', expanded ? 'Свернуть доску' : 'Развернуть доску');
    button.setAttribute('aria-pressed', String(expanded));
  }
  async function toggleBoard() {
    const expanded = !board.classList.contains('expanded');
    updateFullscreen(expanded);
    if (expanded && board.requestFullscreen) await board.requestFullscreen().catch(() => {});
    else if (!expanded && document.fullscreenElement === board) await document.exitFullscreen().catch(() => {});
  }
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) updateFullscreen(false); });
  let dragging = null;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const motion = {x:0, y:0, targetX:0, targetY:0, velocityX:0, rotation:0, last:0, frame:0};
  const limit = (n, min, max) => Math.max(min, Math.min(n, Math.max(min, max)));
  function boardTarget(left, top) {
    return {x:limit(left, 8, window.innerWidth - board.offsetWidth - 8),
      y:limit(top, 8, window.innerHeight - Math.min(board.offsetHeight, window.innerHeight - 16) - 8)};
  }
  function paintBoard() {
    board.style.left = motion.x + 'px';
    board.style.top = motion.y + 'px';
    board.style.setProperty('--board-tilt', motion.rotation.toFixed(3) + 'deg');
  }
  function settleBoard() {
    cancelAnimationFrame(motion.frame);
    motion.frame = 0;
    motion.x = motion.targetX;
    motion.y = motion.targetY;
    motion.velocityX = motion.rotation = 0;
    paintBoard();
  }
  function animateBoard(now) {
    motion.frame = 0;
    if (!root.isConnected) return;
    if (reduceMotion.matches || board.classList.contains('expanded')) { settleBoard(); return; }
    const dt = Math.min(.06, Math.max(0, (now - motion.last) / 1000));
    motion.last = now;
    const smooth = 1 - Math.exp(-dt * 11);
    motion.x += (motion.targetX - motion.x) * smooth;
    motion.y += (motion.targetY - motion.y) * smooth;
    const tilt = limit(motion.velocityX * .006, -3, 3);
    motion.rotation += (tilt - motion.rotation) * (1 - Math.exp(-dt * 7));
    if (!dragging) {
      motion.velocityX *= Math.exp(-dt * 7);
      motion.rotation *= Math.exp(-dt * 2.3);
    }
    paintBoard();
    if (dragging || Math.abs(motion.targetX - motion.x) > .1 || Math.abs(motion.targetY - motion.y) > .1 || Math.abs(motion.velocityX) > .1 || Math.abs(motion.rotation) > .01) {
      motion.frame = requestAnimationFrame(animateBoard);
    } else settleBoard();
  }
  function startBoardMotion() {
    if (reduceMotion.matches) { settleBoard(); return; }
    if (!motion.frame) { motion.last = performance.now(); motion.frame = requestAnimationFrame(animateBoard); }
  }
  function moveBoard(left, top) {
    const target = boardTarget(left, top);
    motion.targetX = target.x;
    motion.targetY = target.y;
    settleBoard();
  }
  function placeBoard(mascotRect) {
    const narrow = window.innerWidth < 900;
    const width = narrow ? Math.min(620, window.innerWidth - 24) : Math.min(620, window.innerWidth - mascotRect.right - 26);
    board.style.setProperty('--board-width', width + 'px');
    moveBoard(narrow ? (window.innerWidth - width) / 2 : mascotRect.right + 18,
      narrow ? mascotRect.bottom + 12 : mascotRect.top + mascotRect.height / 2 - width / 4);
  }
  function revealWorkspace(mascotRect,{restore=false}={}) {
    const mascot=root.querySelector('.mascot-area'),formRect=form.getBoundingClientRect();
    if(restore){
      fixMascot();
      root.classList.add('restoring');
      form.hidden=true;
    }else{
      Object.assign(form.style,{position:'fixed',left:formRect.left+'px',top:formRect.top+'px',width:formRect.width+'px'});
      Object.assign(mascot.style,{position:'fixed',left:mascotRect.left+'px',top:mascotRect.top+'px',width:mascotRect.width+'px',height:mascotRect.height+'px',minHeight:'0',maxWidth:'none',margin:'0'});
      spinWheel();
    }
    root.classList.add('departing');
    prototypeHandoff.show();
    root.querySelector('.board-scene').hidden=false;
    showIndex();
    syncBoardStage();
    placeBoard(mascotRect);
    if(restore)root.classList.add('board-visible');
    else requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.add('board-visible')));
    if(window.makoraDemoWorkflow.isDemoPrototypeReady())setTimeout(()=>window.makoraAgentPlan?.open(),restore?350:1250);
    if(!restore)setTimeout(()=>{form.hidden=true;},650);
  }
  board.addEventListener('pointerdown', e => {
    if (e.button !== 0 || board.classList.contains('expanded') || e.target.closest('button,.board-content')) return;
    dragging = {id:e.pointerId, x:e.clientX, y:e.clientY, left:motion.targetX, top:motion.targetY, previousX:e.clientX, last:performance.now()};
    board.classList.add('dragging');
    board.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  board.addEventListener('pointermove', e => {
    if (!dragging || dragging.id !== e.pointerId) return;
    const target = boardTarget(dragging.left + e.clientX - dragging.x, dragging.top + e.clientY - dragging.y);
    motion.targetX = target.x;
    motion.targetY = target.y;
    const now = performance.now();
    const dt = Math.max(.016, (now - dragging.last) / 1000);
    motion.velocityX = limit((e.clientX - dragging.previousX) / dt, -1000, 1000);
    dragging.previousX = e.clientX;
    dragging.last = now;
    startBoardMotion();
  });
  function stopDrag(e) {
    if (!dragging || dragging.id !== e.pointerId) return;
    dragging = null;
    board.classList.remove('dragging');
    startBoardMotion();
    if (board.hasPointerCapture(e.pointerId)) board.releasePointerCapture(e.pointerId);
  }
  ['pointerup','pointercancel','lostpointercapture'].forEach(type => board.addEventListener(type, stopDrag));
  window.addEventListener('resize', () => {
    if (root.isConnected && root.classList.contains('departing') && !board.classList.contains('expanded')) placeBoard(root.querySelector('.mascot-area').getBoundingClientRect());
  });
  root.querySelector('.board-expand').addEventListener('click',toggleBoard);
  board.addEventListener('dblclick',e => { if(!e.target.closest('button')) toggleBoard(); });
  document.addEventListener('keydown',e => { if(e.key==='Escape' && board.classList.contains('expanded')) toggleBoard(); });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (start.disabled || root.classList.contains('departing')) return;
    const sourceText=textarea.value.trim() || (selectedFile && /\.(txt|md)$/i.test(selectedFile.name) ? await selectedFile.text() : '');
    if(!window.makoraProject.setSource({name:textarea.value.trim()?'Вставленный текст':selectedFile?.name||'Условие',text:sourceText})){error.textContent='Не удалось сохранить условие на устройстве. Попробуй более короткий текст.';error.hidden=false;return;}
    revealWorkspace(root.querySelector('.mascot-area').getBoundingClientRect());
  });
  root.querySelector('.board-next').addEventListener('click', () => {
    const next=Math.min(boardStage+1,4);
    if(boardStage===1){const result=window.makoraDemoWorkflow.approveAnalysis();if(!result.ok){stageMessage.textContent=result.error;stageMessage.hidden=false;return;}}
    openBoardStage(next);
  });
  const previousSource=window.makoraProject.source();
  if(previousSource){
    textarea.value=previousSource.text||previousSource.name||'';
    update();
    if(!start.disabled){
      revealWorkspace(root.querySelector('.mascot-area').getBoundingClientRect(),{restore:true});
    }
    let resumeStage=Math.max(1,Math.min(4,Number(savedWorkspaceView.stage)||1));
    while(resumeStage>1&&!window.makoraDemoWorkflow.canOpenStage(resumeStage))resumeStage--;
    if(resumeStage>1)setTimeout(()=>openBoardStage(resumeStage),1900);
  }
})();

(() => {
  const root = document.createElement('section');
  root.id = 'first-stage';
  root.setAttribute('aria-label', 'Анализ задания');
  root.innerHTML = `<div class="first-top"><a class="first-logo" href="/" aria-label="Макора — главная">✳ <span>макора</span></a><div class="first-header-project"><span data-header-project>Новый проект</span><small data-header-stage>8 этапов</small></div><nav class="first-top-actions" aria-label="Действия проекта"></nav></div>
  <div class="first-intro"><div class="mascot-area" tabindex="0" role="button" aria-label="Макора. Нажмите, чтобы подпрыгнуть; перетащите мышью или перемещайте стрелками." title="Нажмите для прыжка или перетащите Макору"><span class="mascot-fallback" aria-hidden="true">✳</span><iframe class="mascot-frame" src="mascot.html?v=stage-board-2" title="Персонаж Макоры" tabindex="-1"></iframe></div>
  <form class="first-form"><div class="speech-label">ПЕРВЫЙ ШАГ <span>01 / 08</span></div><h1>Привет!<br>Объяснить задание?</h1><p>Пришли условие хакатона — соберём всё важное в одном месте.</p>
  <label class="pixel-drop"><input type="file" accept=".pdf,.docx,.txt,.md" class="sr-only"><span class="pixel-plus" aria-hidden="true"><svg viewBox="0 0 24 24" width="28" height="28" shape-rendering="crispEdges"><path fill="currentColor" d="M2 5h8v2h12v14H2zm2 4v10h16V9z"/><path fill="currentColor" d="M11 11h2v2h2v2h-2v2h-2v-2H9v-2h2z"/></svg></span><strong class="file-label">Выбрать файл</strong><small>или перетащить сюда<br>PDF, DOCX, TXT, MD · до 20 МБ</small></label><div class="or-line"><span>ИЛИ ВСТАВЬ ТЕКСТ</span></div><label class="sr-only" for="first-text">Текст задания</label><textarea id="first-text" placeholder="Вставь условие задания сюда…"></textarea><div class="first-project-folder"><button type="button" data-choose-project-folder>▱ Выбрать папку проекта</button><small data-project-folder-label>Здесь будут условие, документы и код</small></div><p class="first-error" role="alert" hidden></p><button class="pixel-start" type="submit" disabled>Начать анализ <span aria-hidden="true">▶</span></button><p class="first-disclaimer">Модели агентов настраиваются для проекта. Результаты сохраняются локально и требуют утверждения.</p></form></div>
  <div class="board-scene" hidden>
    <div class="board-stage">
      <section class="board rp-board stage-board" aria-label="Доска проекта">
        <nav class="stage-grid" aria-label="Этапы проекта"></nav>
        <div class="board-inner" hidden>
          <header class="board-bar">
            <div><span class="board-kicker"></span><h2 id="stage-title" tabindex="-1"></h2></div>
            <button type="button" class="stage-board-back">← К доске</button>
          </header>
          <nav class="stage-navigation" aria-label="Переключение этапов"></nav>
          <div class="board-content"></div>
        </div>
      </section>
    </div>
  </div>`;
  document.body.append(root);
  document.body.classList.add('first-stage-active');
  const form = root.querySelector('form'), input = root.querySelector('input[type=file]'), textarea = root.querySelector('textarea');
  const drop = root.querySelector('.pixel-drop'), error = root.querySelector('.first-error'), start = root.querySelector('.pixel-start');
  let selectedFile = null, selectedFolder = '';
  const chooseFolder=root.querySelector('[data-choose-project-folder]'),folderLabel=root.querySelector('[data-project-folder-label]');
  const folderOpen=document.createElement('button');folderOpen.className='first-open-folder';folderOpen.type='button';folderOpen.disabled=true;folderOpen.title='Сначала выберите папку проекта';folderOpen.setAttribute('aria-label','Открыть папку проекта в Проводнике');folderOpen.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 7V4h6l3 3h9v13H3z"/><path d="M3 9h18"/></svg>';
  root.querySelector('.first-top-actions').append(folderOpen);
  function applyFolder(path){if(!path)return;const projectName=root.querySelector('[data-header-project]');projectName.textContent=path.split(/[\\/]/).filter(Boolean).at(-1)||'Проект';projectName.title=path;folderOpen.disabled=false;folderOpen.title='Открыть папку проекта: '+path;error.hidden=true;selectedFolder=path;chooseFolder.dataset.folderSelected='true';chooseFolder.textContent='▱ Изменить папку проекта';folderLabel.textContent=path;folderLabel.title=path;update()}
  window.addEventListener('makora:project-folder',e=>applyFolder(e.detail.path));
  chooseFolder.onclick=async()=>{chooseFolder.disabled=true;chooseFolder.textContent='Выберите папку в открывшемся окне…';try{const result=await window.makoraPreparation.chooseFolder();if(result.cancelled)chooseFolder.textContent=selectedFolder?'▱ Изменить папку проекта':'▱ Выбрать папку проекта'}catch(e){error.textContent=e.message;error.hidden=false;chooseFolder.textContent='▱ Выбрать папку проекта'}finally{chooseFolder.disabled=false}};
  folderOpen.onclick=async()=>{try{await window.makoraPreparation.openFolder()}catch(e){folderOpen.title=e.message;error.textContent=e.message;error.hidden=false}};

  function update() { start.disabled = (!selectedFile && !textarea.value.trim()) || !selectedFolder; }

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
  const mascotArea = root.querySelector('.mascot-area');
  const syncMascot = () => {
    mascotArea.classList.toggle('mascot-ready', frame.contentDocument?.querySelector('#sprite')?.dataset.ready === 'true');
  };
  frame.addEventListener('makora-mascot-render', syncMascot);
  frame.addEventListener('load', () => { syncMascot(); animate('idle'); });
  let mascotDrag = null;
  function jumpMascot(){try{frame.contentDocument.querySelector('[data-action="jump"]')?.click()}catch{}}
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
    window.dispatchEvent(new Event('makora:mascot-move'));
  }
  mascotArea.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    if(root.classList.contains('stage-open')){jumpMascot();return}
    const rect = fixMascot();
    mascotDrag = {id:e.pointerId, x:e.clientX, y:e.clientY, left:rect.left, top:rect.top,moved:false};
    mascotArea.classList.add('carried');
    mascotArea.setPointerCapture(e.pointerId);
    notifyMascot('start', e.clientX, e.clientY);
    e.preventDefault();
  });
  mascotArea.addEventListener('pointermove', e => {
    if (!mascotDrag || mascotDrag.id !== e.pointerId) return;
    if(Math.hypot(e.clientX-mascotDrag.x,e.clientY-mascotDrag.y)>6)mascotDrag.moved=true;
    moveMascot(mascotDrag.left + e.clientX - mascotDrag.x, mascotDrag.top + e.clientY - mascotDrag.y);
    notifyMascot('move', e.clientX, e.clientY);
  });
  function releaseMascot(e) {
    if (!mascotDrag || mascotDrag.id !== e.pointerId) return;
    const clicked=e.type==='pointerup'&&!mascotDrag.moved;
    mascotDrag = null;
    mascotArea.classList.remove('carried');
    notifyMascot('end', e.clientX, e.clientY);
    if(clicked)jumpMascot();
    if (mascotArea.hasPointerCapture(e.pointerId)) mascotArea.releasePointerCapture(e.pointerId);
  }
  ['pointerup','pointercancel','lostpointercapture'].forEach(type => mascotArea.addEventListener(type, releaseMascot));
  mascotArea.addEventListener('keydown', e => {
    if(e.key==='Enter'||e.key===' '){e.preventDefault();if(!e.repeat)jumpMascot();return}
    const delta = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]}[e.key];
    if (!delta||root.classList.contains('stage-open')) return;
    e.preventDefault();
    const rect = fixMascot(), step = e.shiftKey ? 40 : 12;
    moveMascot(rect.left + delta[0] * step, rect.top + delta[1] * step);
  });

  const board = root.querySelector('.board'), content = root.querySelector('.board-content');
  let dragging = null;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const motion = {x:0, y:0, targetX:0, targetY:0, velocityX:0, rotation:0, last:0, frame:0};
  const limit = (n, min, max) => Math.max(min, Math.min(n, Math.max(min, max)));
  function boardTarget(left, top) {
    const topLimit=Number(board.dataset.topLimit)||88;
    return {x:limit(left, 8, window.innerWidth - board.offsetWidth - 8),
      y:limit(top, topLimit, window.innerHeight - board.offsetHeight - 12)};
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
  function placeBoard() {
    const compact = window.innerWidth < 900;
    const headerBottom=root.querySelector('.first-top').getBoundingClientRect().bottom;
    const width=compact?window.innerWidth-24:Math.min(920,Math.floor(window.innerWidth*.72));
    const topLimit=Math.round(headerBottom)+(compact?86:20);
    const placement=compact?'compact':'wide';
    board.style.setProperty('--board-width',width+'px');
    board.style.setProperty('--board-offset',topLimit+'px');
    board.dataset.topLimit=topLimit;
    if(mascotArea.dataset.workspacePlaced!==placement){
      mascotArea.dataset.workspacePlaced=placement;
      mascotArea.style.width=compact?'116px':'220px';
      mascotArea.style.height=compact?'72px':'186px';
      moveMascot(compact?(window.innerWidth-mascotArea.offsetWidth)/2:Math.max(16,(window.innerWidth-width-28-mascotArea.offsetWidth)/2),
        compact?headerBottom+5:window.innerHeight/2-93);
    }else{
      moveMascot(parseFloat(mascotArea.style.left),parseFloat(mascotArea.style.top));
    }
    const left=compact?12:window.innerWidth-width-28;
    moveBoard(left,compact?topLimit:Math.max(topLimit,(window.innerHeight-board.offsetHeight)/2));
  }
  function revealWorkspace(snapshot,{restore=false}={}) {
    fixMascot();
    if(restore)root.classList.add('restoring');
    root.classList.add('departing');
    root.querySelector('.board-scene').hidden=false;
    window.makoraPreparation.mount(snapshot);
    placeBoard();
    if(restore){
      root.classList.add('board-visible');
      form.hidden=true;
    }else{
      requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.add('board-visible')));
      setTimeout(()=>{form.hidden=true},650);
    }
  }
  board.addEventListener('pointerdown', e => {
    if (e.button !== 0 || board.classList.contains('expanded') || e.target.closest('button,a,.board-content')) return;
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
    if (root.isConnected && root.classList.contains('departing') && !board.classList.contains('expanded')) placeBoard();
  });
  root.addEventListener('makora:stage-close',placeBoard);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (start.disabled || root.classList.contains('departing')) return;
    start.disabled=true;
    error.hidden=true;
    try{
      let sourceText=textarea.value.trim();
      if(!sourceText&&selectedFile){
        start.textContent='Читаем файл…';
        sourceText=/\.(txt|md)$/i.test(selectedFile.name)
          ? await selectedFile.text()
          : await window.makoraPreparation.extract(selectedFile);
      }
      if(!sourceText)throw Error('Вставьте текст задания или прикрепите файл с условием.');
      start.textContent='Создаём сессию Codex…';
      const snapshot=await window.makoraPreparation.start(sourceText,selectedFile);
      revealWorkspace(snapshot);
    }catch(e){
      error.textContent=e.message;
      error.hidden=false;
      start.textContent='Начать анализ';
      update();
    }
  });
  window.addEventListener('makora:resume-project',event=>{
    const snapshot=event.detail;
    if(snapshot?.brief)revealWorkspace(snapshot,{restore:true});
  });
})();

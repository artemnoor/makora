(() => {
  const root = document.createElement('section');
  root.id = 'first-stage';
  root.setAttribute('aria-label', 'Анализ задания');
  root.innerHTML = `<div class="first-top"><a class="first-logo" href="/">✳ <span>макора</span></a><span>РАБОЧЕЕ ПРОСТРАНСТВО / 01</span><span>ЭТАП 01 / 06</span></div>
  <div class="first-intro"><div class="mascot-area"><iframe class="mascot-frame" src="mascot.html" title="Персонаж Макоры" tabindex="-1"></iframe></div>
  <form class="first-form"><div class="speech-label">ПЕРВЫЙ ШАГ <span>01 / 06</span></div><h1>Привет!<br>Разберём задание?</h1><p>Пришли условие хакатона — соберём всё важное в одном месте.</p>
  <label class="pixel-drop"><input type="file" accept=".pdf,.doc,.docx,.txt,.md" class="sr-only"><span class="pixel-plus" aria-hidden="true"><svg viewBox="0 0 24 24" width="28" height="28" shape-rendering="crispEdges"><path fill="currentColor" d="M2 5h8v2h12v14H2zm2 4v10h16V9z"/><path fill="currentColor" d="M11 11h2v2h2v2h-2v2h-2v-2H9v-2h2z"/></svg></span><strong class="file-label">Выбрать файл</strong><small>или перетащить сюда<br>PDF, DOCX, TXT, MD · до 20 МБ</small></label><div class="or-line"><span>ИЛИ ВСТАВЬ ТЕКСТ</span></div><label class="sr-only" for="first-text">Текст задания</label><textarea id="first-text" placeholder="Вставь условие задания сюда…"></textarea><p class="first-error" role="alert" hidden></p><button class="pixel-start" type="submit" disabled>Начать анализ <span aria-hidden="true">▶</span></button><p class="first-disclaimer">Демо: загрузка и анализ имитируются.</p></form></div>
  <div class="board-scene" hidden><div class="board-heading"><span>01 / АНАЛИЗ ЗАДАНИЯ</span><span>01_CASE_ANALYSIS.MD</span></div><div class="board-stage"><div class="board-mascot" aria-hidden="true"></div><div class="board" aria-label="Доска анализа задания"><div class="board-sprite"><img class="board-shadow-art" src="analysis-board.png" alt="" draggable="false"><img class="board-art" src="analysis-board.png" alt="" draggable="false"></div><div class="board-inner"><div class="board-bar"><div><span class="board-kicker">ДЕМО-КЕЙС / ТИХИЙ КАМПУС</span><h2>Анализ задания<span>.</span></h2></div><button type="button" class="board-expand" aria-label="Развернуть доску" title="Развернуть доску">⛶</button></div><div class="board-content"></div><div class="board-footer"><span>ТЯНИ ЗА РАМКУ · ДВОЙНОЙ КЛИК — НА ВЕСЬ ЭКРАН</span><span>01 / 06</span></div></div></div></div><div class="scene-bottom"><p>Демо-анализ: показан пример, файл не анализируется.</p><button type="button" class="board-next">Далее <span>→</span></button></div></div>`;
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
  const board = root.querySelector('.board'), content = root.querySelector('.board-content');
  function showIndex() {
    content.innerHTML = '<div class="board-intro">ВЫБЕРИ РАЗДЕЛ, ЧТОБЫ ОТКРЫТЬ ЕГО</div><div class="board-list">' + oneTitles.map((title,i) => `<button type="button" data-section="${i}" title="${esc(title)}"><span class="board-number">${String(i+1).padStart(2,'0')}</span><span>${title}</span><span class="board-arrow">↗</span></button>`).join('') + '</div>';
  }
  function showSection(i) {
    content.innerHTML = `<button type="button" class="board-back">← Все разделы</button><div class="board-document"><div class="board-doc-number">${String(i+1).padStart(2,'0')} / 10</div>${render(one[i])}</div>`;
    content.scrollTop = 0;
  }
  content.addEventListener('click', e => { const section=e.target.closest('[data-section]'); if(section) showSection(Number(section.dataset.section)); if(e.target.closest('.board-back')) showIndex(); });
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
  form.addEventListener('submit', e => {
    e.preventDefault();
    if (start.disabled || root.classList.contains('departing')) return;
    const mascot = root.querySelector('.mascot-area');
    const initial = mascot.getBoundingClientRect();
    const formRect = form.getBoundingClientRect();
    Object.assign(form.style, {position:'fixed', left:formRect.left+'px', top:formRect.top+'px', width:formRect.width+'px'});
    Object.assign(mascot.style, {position:'fixed', left:initial.left+'px', top:initial.top+'px', width:initial.width+'px', height:initial.height+'px', minHeight:'0', maxWidth:'none', margin:'0'});
    spinWheel();
    root.classList.add('departing');
    root.querySelector('.board-scene').hidden = false;
    showIndex();
    placeBoard(initial);
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('board-visible')));
    setTimeout(() => { form.hidden = true; }, 650);
  });
  root.querySelector('.board-next').addEventListener('click', () => { document.querySelector('#next-stage').click(); underneath.forEach(el => el.inert = false); document.body.classList.remove('first-stage-active'); root.remove(); window.scrollTo(0,0); });
})();

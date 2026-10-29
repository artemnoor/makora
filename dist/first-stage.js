(() => {
  const root = document.createElement('section');
  root.id = 'first-stage';
  root.setAttribute('aria-label', 'Анализ задания');
  root.innerHTML = `<div class="first-top"><a class="first-logo" href="/">✳ <span>макора</span></a><span>РАБОЧЕЕ ПРОСТРАНСТВО / 01</span><span>ЭТАП 01 / 06</span></div>
  <div class="first-intro"><div class="mascot-area"><iframe class="mascot-frame" src="mascot.html" title="Персонаж Макоры" tabindex="-1"></iframe><span class="mascot-label">МАКОРА <i>●</i> НА СВЯЗИ</span></div>
  <form class="first-form"><div class="speech-label">ПЕРВЫЙ ШАГ <span>01 / 06</span></div><h1>Привет!<br>Давай разберём<br>твоё задание.</h1><p>Пришли условие хакатона — соберём всё важное в одном месте.</p>
  <label class="pixel-drop"><input type="file" accept=".pdf,.doc,.docx,.txt,.md" hidden><span class="pixel-plus">＋</span><strong class="file-label">Выбрать файл</strong><small>или перетащить сюда<br>PDF, DOCX, TXT, MD · до 20 МБ</small></label><div class="or-line"><span>ИЛИ ВСТАВЬ ТЕКСТ</span></div><label class="sr-only" for="first-text">Текст задания</label><textarea id="first-text" placeholder="Вставь условие задания сюда…"></textarea><p class="first-error" role="alert" hidden></p><button class="pixel-start" type="submit" disabled>Начать анализ <span>↗</span></button><p class="first-disclaimer">Демо: загрузка и анализ имитируются.</p></form></div>
  <div class="board-scene" hidden><div class="board-heading"><span>01 / АНАЛИЗ ЗАДАНИЯ</span><span>01_CASE_ANALYSIS.MD</span></div><div class="board" aria-label="Доска анализа задания"><div class="board-sprite"></div><div class="board-inner"><div class="board-bar"><div><span class="board-kicker">ДЕМО-КЕЙС / ТИХИЙ КАМПУС</span><h2>Анализ задания<span>.</span></h2></div><button type="button" class="board-expand" aria-label="Развернуть доску" title="Развернуть доску">⛶</button></div><div class="board-content"></div><div class="board-footer"><span>ДВОЙНОЙ КЛИК ПО ДОСКЕ — НА ВЕСЬ ЭКРАН</span><span>01 / 06</span></div></div></div><div class="scene-bottom"><p>Демо-анализ: показан пример, файл не анализируется.</p><button type="button" class="board-next">Далее <span>→</span></button></div></div>`;
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
  frame.addEventListener('load', () => { animate('wave'); setTimeout(() => animate('idle'), 1800); });
  const board = root.querySelector('.board'), content = root.querySelector('.board-content');
  function showIndex() {
    content.innerHTML = '<div class="board-intro">ВЫБЕРИ РАЗДЕЛ, ЧТОБЫ ОТКРЫТЬ ЕГО</div><div class="board-list">' + oneTitles.map((title,i) => `<button type="button" data-section="${i}"><span class="board-number">${String(i+1).padStart(2,'0')}</span><span>${title}</span><span class="board-arrow">↗</span></button>`).join('') + '</div>';
  }
  function showSection(i) {
    content.innerHTML = `<button type="button" class="board-back">← Все разделы</button><div class="board-document"><div class="board-doc-number">${String(i+1).padStart(2,'0')} / 10</div>${render(one[i])}</div>`;
    content.scrollTop = 0;
  }
  content.addEventListener('click', e => { const section=e.target.closest('[data-section]'); if(section) showSection(Number(section.dataset.section)); if(e.target.closest('.board-back')) showIndex(); });
  function toggleBoard() { const expanded=board.classList.toggle('expanded'); root.querySelector('.board-expand').setAttribute('aria-label',expanded?'Свернуть доску':'Развернуть доску'); }
  root.querySelector('.board-expand').addEventListener('click',toggleBoard);
  board.addEventListener('dblclick',e => { if(!e.target.closest('button')) toggleBoard(); });
  document.addEventListener('keydown',e => { if(e.key==='Escape' && board.classList.contains('expanded')) toggleBoard(); });
  form.addEventListener('submit',e => { e.preventDefault(); if(start.disabled) return; animate('walk'); root.classList.add('departing'); setTimeout(() => { root.querySelector('.first-intro').hidden=true; root.querySelector('.board-scene').hidden=false; showIndex(); requestAnimationFrame(() => root.classList.add('board-visible')); }, 850); });
  root.querySelector('.board-next').addEventListener('click', () => { document.querySelector('#next-stage').click(); underneath.forEach(el => el.inert = false); document.body.classList.remove('first-stage-active'); root.remove(); window.scrollTo(0,0); });
})();

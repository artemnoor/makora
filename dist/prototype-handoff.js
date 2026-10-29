// Stage 5 is a manual handoff: no external AI is contacted by this page.
window.createPrototypeHandoff = function(root, mascot, getSourceFile) {
  const key = 'makora.prototype-handoff.v1';
  const prompt = 'Создай запускаемый рабочий прототип по приложенным материалам. Вся разработка строится вокруг исходной папки mocks/: обязательно сохрани её целиком, без изменений, с исходными путями. Если нужны изменения или дополнительные моки, создай отдельную папку new_mocks/ и положи их туда; исходную mocks/ не изменяй и не удаляй. Реализуй основной сценарий MVP, соблюдай контракты, обработай ошибки и пустые состояния. Учебные примеры не выдавай за требования, отметь демо-данные, добавь инструкцию запуска и результаты проверок. Верни проект ZIP-архивом.';
  let state;
  try { state = JSON.parse(localStorage.getItem(key)) || {}; } catch { state = {}; }
  let selected = null, sourceFile = null, prepared = false;
  const dock = document.createElement('div');
  dock.className = 'mascot-capabilities';
  dock.hidden = true;
  dock.innerHTML = `<button type="button" class="capabilities-toggle" aria-expanded="false">✳ Возможности</button><div class="capabilities-menu" hidden><button type="button" data-prototype-open><span>01</span><strong>Рабочий прототип</strong><span>↗</span></button></div>`;
  root.append(dock);
  const panel = document.createElement('section');
  panel.className = 'prototype-dialog';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Рабочий прототип с внешним ИИ');
  root.append(panel);
  function save() { try { localStorage.setItem(key, JSON.stringify(state)); return true; } catch { return false; } }
  function updatePosition() {
    if (dock.hidden) return;
    const rect = mascot.getBoundingClientRect();
    const width = dock.offsetWidth || 170;
    const left = Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + (rect.width - width) / 2));
    const top = Math.max(8, Math.min(window.innerHeight - 48, rect.bottom + 3));
    dock.style.left = left + 'px';
    dock.style.top = top + 'px';
    dock.classList.toggle('menu-above', top > window.innerHeight - 130);
    dock.classList.toggle('menu-align-right', left + 225 > window.innerWidth - 8);
  }
  const toggle = dock.querySelector('.capabilities-toggle'), menu = dock.querySelector('.capabilities-menu');
  toggle.onclick = () => { menu.hidden = !menu.hidden; toggle.setAttribute('aria-expanded', String(!menu.hidden)); };
  dock.querySelector('[data-prototype-open]').onclick = () => { menu.hidden = true; toggle.setAttribute('aria-expanded', 'false'); open(); };
  const dbOpen = () => new Promise((resolve, reject) => {
    const request = indexedDB.open('makora-prototype-result', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('files');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Хранилище недоступно'));
    request.onblocked = () => reject(new Error('Хранилище занято другой вкладкой'));
  });
  async function fileStore(mode, value) {
    const db = await dbOpen();
    try { return await new Promise((resolve, reject) => {
      const tx = db.transaction('files', mode === 'get' ? 'readonly' : 'readwrite');
      const store = tx.objectStore('files');
      const req = mode === 'get' ? store.get('result') : mode === 'delete' ? store.delete('result') : store.put(value, 'result');
      let result; req.onsuccess = () => { result = req.result; };
      tx.oncomplete = () => resolve(result); tx.onerror = () => reject(tx.error); tx.onabort = () => reject(tx.error || new Error('Сохранение отменено'));
    }); } finally { db.close(); }
  }
  function download(name, data, type) {
    const url = URL.createObjectURL(new Blob([data], {type}));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function contextSignature() {
    const c = window.makoraStage3.getContext();
    return JSON.stringify({project:c.project.signature, openapi:c.openapi, tasks:c.tasks, approval:c.approval});
  }
  async function inspectZip(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const paths = [], originals = []; let count = 0;
    try {
      fflate.unzipSync(bytes, {filter: entry => {
        if (++count > 50000) throw new Error('В архиве слишком много файлов.');
        const name = entry.name.replace(/\\/g, '/');
        const parts = name.split('/').filter(Boolean);
        if (name.startsWith('/') || /^[A-Za-z]:/.test(name) || parts.includes('..') || parts.includes('.') || name.includes('\0')) throw new Error('В архиве обнаружен небезопасный путь.');
        const newIndex=parts.indexOf('new_mocks'), oldIndex=parts.indexOf('mocks');
        const isDirectoryPart=index=>index >= 0 && (index < parts.length-1 || name.endsWith('/'));
        if (isDirectoryPart(newIndex) && paths.length < 100) paths.push(name);
        if (isDirectoryPart(oldIndex) && (newIndex < 0 || oldIndex < newIndex) && originals.length < 100) originals.push(name);
        return false;
      }});
    } catch (error) { throw new Error(error.message?.includes('небезопасный путь') || error.message?.includes('слишком много') ? error.message : 'Не удалось прочитать ZIP. Выбери корректный архив.'); }
    return {hasNewMocks:paths.length > 0, newMocksPaths:paths, originalMocksPresent:originals.length > 0};
  }
  async function createPackage() {
    const ctx = window.makoraStage3.getContext();
    const mock = await window.makoraMockData.getBundle();
    if (Object.keys(mock.errors).length) throw new Error('Не удалось прочитать файлы моков: ' + Object.keys(mock.errors).join(', '));
    const files = {}, add = (path, text) => { files[path] = fflate.strToU8(text); };
    const source = ctx.project.source;
    let originalNote = 'Исходное условие отсутствует.';
    sourceFile = getSourceFile();
    if (sourceFile) {
      const name = sourceFile.name.replace(/[\\/\x00-\x1f]/g, '_');
      files['input/' + name] = new Uint8Array(await sourceFile.arrayBuffer());
      originalNote = 'Оригинал приложен: input/' + name;
    } else if (source?.text) {
      add('input/condition.txt', source.text);
      originalNote = 'Исходный текст приложен: input/condition.txt';
    } else if (source) originalNote = 'Исходный файл «' + source.name + '» больше недоступен в браузере. Прикрепите его отдельно.';
    add('PROMPT.md', prompt + '\n');
    add('README.md', `# Контекст для рабочего прототипа\n\n${originalNote}\n\nМатериалы этапов 1, 3 и 4 — демонстрационный кейс «Тихий кампус»; они не генерируются из загруженного условия и не обновляются после правки идеи. Используйте их как пример, а не как анализ исходного задания.\n\nИдея: ${ctx.project.approved?'утверждена':'не утверждена'}. План: ${ctx.readiness.ready?'утверждён':'требует проверки'}. Моки: ${mock.approved?'проверены и утверждены':'не утверждены или требуют повторной проверки'}. Результаты проверок — в отчётах; демонстрационные данные не являются реальными.\n`);
    add('01_case_analysis_DEMO.md', '# Демо-анализ «Тихий кампус»\n\n' + one.join('\n\n---\n\n'));
    add('02_research.md', ctx.project.research.map(x => x.md).join('\n\n---\n\n'));
    add('02_solution_concept.md', ctx.project.concept.map(x => x.md).join('\n\n---\n\n'));
    for (const item of window.makoraStage3.exportArtifacts()) add(item.name, item.text);
    for (const [path, text] of Object.entries(mock.files)) add(path, text);
    add('context-status.json', JSON.stringify({demo:true, source:originalNote, ideaApproved:ctx.project.approved, planReady:ctx.readiness.ready, mocksApproved:mock.approved, mockChecksValid:mock.checksValid, mockCheckedAt:mock.validatedAt}, null, 2));
    return {bytes:fflate.zipSync(files), signature:contextSignature(), status:{idea:ctx.project.approved, plan:ctx.readiness.ready, mocks:mock.approved}};
  }
  function shell(body) {
    panel.innerHTML = `<div class="prototype-shell"><div class="prototype-header"><span>РАБОЧИЙ ПРОТОТИП · 05</span><button type="button" data-close aria-label="Закрыть">×</button></div>${body}<p class="prototype-feedback" role="status"></p></div>`;
    panel.querySelector('[data-close]').onclick = close;
  }
  function feedback(message) { const el = panel.querySelector('.prototype-feedback'); if(el) el.textContent = message; }
  async function showPackage() {
    shell(`<h2>Давай создадим<br>рабочую версию.</h2><p>Я соберу короткое задание и файлы. Передай их своему ИИ, а готовый прототип принеси сюда.</p><label for="prototype-prompt">ПРОМПТ ДЛЯ ИИ</label><textarea id="prototype-prompt" readonly></textarea><div class="prototype-actions"><button type="button" data-copy>Скопировать промпт</button><button type="button" data-download>Скачать файлы ↓</button></div><p class="prototype-note">В архиве: исходное условие, анализ, идея, план, контракты, задачи и мок-данные. Учебные материалы помечены как демо.</p><button class="prototype-primary" type="button" data-sent disabled>Я передал пакет ИИ <span>→</span></button>`);
    panel.querySelector('#prototype-prompt').value = prompt;
    panel.querySelector('[data-copy]').onclick = async () => { try { await navigator.clipboard.writeText(prompt); feedback('Промпт скопирован.'); } catch { const el=panel.querySelector('#prototype-prompt'); el.focus(); el.select(); feedback('Выдели текст и скопируй его.'); } };
    panel.querySelector('[data-download]').onclick = async e => {
      const button = e.currentTarget; button.disabled = true; feedback('Собираю файлы…');
      try {
        const result = await createPackage();
        download('makora-prototype-context.zip', result.bytes, 'application/zip');
        state.packageSignature = result.signature; state.packageStatus = result.status;
        if (!save()) throw new Error('Не удалось сохранить состояние на устройстве.');
        prepared = true; panel.querySelector('[data-sent]').disabled = false;
        feedback(result.status.idea && result.status.plan && result.status.mocks ? 'Файлы собраны. Передай архив и промпт своему ИИ.' : 'Файлы собраны как черновик: идея, план или моки ещё требуют согласования. Проверь README в архиве.');
      } catch (error) { feedback(error.message || 'Не удалось собрать файлы.'); }
      finally { if (button.isConnected) button.disabled = false; }
    };
    panel.querySelector('[data-sent]').onclick = () => {
      if (!prepared || state.packageSignature !== contextSignature()) { feedback('Материалы изменились. Скачай пакет заново.'); panel.querySelector('[data-sent]').disabled = true; return; }
      state.status = 'waiting'; state.sentAt = new Date().toISOString();
      if (!save()) { feedback('Не удалось сохранить состояние на устройстве.'); return; }
      showWaiting();
    };
  }
  function showWaiting() {
    shell(`<h2>Жду твою<br>рабочую версию.</h2><p>Когда закончишь с ИИ, прикрепи ZIP проекта или вставь ссылку на результат.</p><div class="prototype-waiting">◌ &nbsp; ОЖИДАЮ РЕЗУЛЬТАТ</div><label class="prototype-drop"><input class="sr-only" type="file" accept=".zip,application/zip"><strong>＋ Выбрать ZIP проекта</strong><small>или перетащить сюда · до 100 МБ</small></label><label for="prototype-link">ИЛИ ССЫЛКА НА ПРОЕКТ</label><input id="prototype-link" type="url" placeholder="https://…"><button class="prototype-primary" type="button" data-receive>Вернуть результат <span>→</span></button><button class="prototype-text-button" type="button" data-package>Посмотреть пакет ещё раз</button><p class="prototype-note">Файл сохраняется только в этом браузере. Проверка и запуск проекта здесь пока не выполняются.</p>`);
    if (state.packageSignature && state.packageSignature !== contextSignature()) feedback('Материалы изменились после передачи. Если нужно, собери и передай обновлённый пакет.');
    const input=panel.querySelector('input[type=file]'), drop=panel.querySelector('.prototype-drop');
    const select = file => { if (!file) return; if (!/\.zip$/i.test(file.name) || file.size > 100 * 1024 * 1024) { selected=null; feedback('Выбери ZIP размером до 100 МБ.'); return; } selected=file; drop.querySelector('strong').textContent=file.name; feedback(''); };
    input.onchange = () => select(input.files[0]);
    ['dragenter','dragover'].forEach(type => drop.addEventListener(type, e => {e.preventDefault();drop.classList.add('dragging')}));
    ['dragleave','drop'].forEach(type => drop.addEventListener(type, e => {e.preventDefault();drop.classList.remove('dragging')}));
    drop.addEventListener('drop', e => select(e.dataTransfer.files[0]));
    panel.querySelector('[data-package]').onclick = () => { prepared=false; showPackage(); };
    panel.querySelector('[data-receive]').onclick = async e => {
      const link=panel.querySelector('#prototype-link').value.trim();
      if (!selected && !link) { feedback('Прикрепи ZIP или вставь ссылку на проект.'); return; }
      if (link) { try { const url=new URL(link); if (!['http:','https:'].includes(url.protocol)) throw new Error(); } catch { feedback('Укажи ссылку, начинающуюся с http:// или https://.'); return; } }
      const button=e.currentTarget; button.disabled=true;
      try {
        const inspection=selected ? await inspectZip(selected) : {hasNewMocks:false,newMocksPaths:[],originalMocksPresent:null};
        if (selected) await fileStore('put', {name:selected.name, file:selected}); else { try { await fileStore('delete'); } catch (_) {} }
        state.status=inspection.hasNewMocks?'questions':'received'; state.resultName=selected?.name||''; state.resultLink=link; state.receivedAt=new Date().toISOString();
        state.inspection=inspection; state.mockAnswers=null;
        if (!save()) { state.status='waiting'; throw new Error('Не удалось сохранить состояние на устройстве.'); }
        selected=null; if(state.status==='questions')showQuestions();else showReceived();
      } catch (error) { feedback('Не удалось сохранить результат: ' + (error.message || 'хранилище недоступно')); if(button.isConnected)button.disabled=false; }
    };
  }
  function adaptationRequest() {
    const answers=state.mockAnswers||{};
    const paths=(state.inspection?.newMocksPaths||[]).join('\n');
    return `# Запрос на анализ изменений моков\n\nПроект вернулся от внешнего ИИ. В архиве найдена папка new_mocks/. Сохрани исходную папку mocks/ без изменений. До применения изменений сравни файлы, схемы, контракты, тесты и сценарии; опиши влияние и предложи план адаптации. Не запускай код из архива автоматически и не изменяй утверждённые материалы без согласования.\n\n## Найденные пути\n\n${paths}\n\n## Ответы пользователя\n\nЧто изменилось и почему: ${answers.reason||'не указано'}\n\nКак использовать старые и новые данные: ${answers.strategy||'не указано'}\n\nКакие сценарии и контракты сохранить: ${answers.preserve||'не указано'}\n\n## Статус\n\nСравнение и адаптация ещё не выполнялись. Исходные материалы и ZIP проекта нужно приложить отдельно.\n`;
  }
  function showQuestions() {
    shell(`<h2>Вижу новые<br>мок-данные.</h2><p>В ZIP найдена папка <strong>new_mocks/</strong>. Прежде чем готовить адаптацию, помоги понять изменения.</p><label for="mock-reason">ЧТО ИЗМЕНИЛОСЬ И ПОЧЕМУ?</label><textarea id="mock-reason" placeholder="Например: добавились поля карточки…"></textarea><label for="mock-strategy">КАК ИСПОЛЬЗОВАТЬ СТАРЫЕ И НОВЫЕ МОКИ?</label><textarea id="mock-strategy" placeholder="Например: сохранить старые, новые сначала проверить…"></textarea><label for="mock-preserve">ЧТО ОБЯЗАТЕЛЬНО СОХРАНИТЬ И ПРОВЕРИТЬ?</label><textarea id="mock-preserve" placeholder="Сценарии, требования или контракты…"></textarea><button class="prototype-primary" type="button" data-save-answers>Сохранить ответы <span>→</span></button><p class="prototype-note">Сейчас я проверил только имена файлов. Сравнение содержимого, адаптация и запуск ещё не выполнялись.</p>`);
    const prior=state.mockAnswers||{};
    for(const [id,value] of [['mock-reason',prior.reason],['mock-strategy',prior.strategy],['mock-preserve',prior.preserve]])panel.querySelector('#'+id).value=value||'';
    panel.querySelector('[data-save-answers]').onclick=()=>{
      const answers={reason:panel.querySelector('#mock-reason').value.trim(),strategy:panel.querySelector('#mock-strategy').value.trim(),preserve:panel.querySelector('#mock-preserve').value.trim()};
      if(Object.values(answers).some(value=>!value)){feedback('Ответь на все три вопроса, чтобы подготовить адаптацию.');return;}
      state.mockAnswers=answers;state.status='received';state.answersAt=new Date().toISOString();
      if(!save()){state.status='questions';feedback('Не удалось сохранить ответы на устройстве.');return;}showReceived();
    };
  }
  async function showReceived() {
    shell(`<h2>Прототип<br>получен.</h2><p>Результат сохранён на этом устройстве. Запуск и проверка проекта пока не выполнялись.</p><div class="prototype-result"></div>${state.inspection?.hasNewMocks?'<button class="prototype-text-button" type="button" data-adaptation>Скачать запрос на адаптацию ↓</button><button class="prototype-text-button" type="button" data-edit-answers>Изменить ответы</button>':''}<button class="prototype-primary" type="button" data-result-download hidden>Скачать сохранённый ZIP ↓</button><button class="prototype-text-button" type="button" data-replace>Заменить результат</button>`);
    const result=panel.querySelector('.prototype-result');
    if (state.resultName) { const item=document.createElement('p'); item.textContent='ZIP: '+state.resultName; result.append(item); }
    if (state.resultLink) { const link=document.createElement('a'); link.href=state.resultLink; link.textContent=state.resultLink; link.target='_blank'; link.rel='noopener noreferrer'; result.append(link); }
    if(state.inspection?.hasNewMocks){const note=document.createElement('p');note.textContent='Найдена new_mocks/. Ответы сохранены; сравнение и адаптация ещё не выполнялись.';result.append(note);panel.querySelector('[data-adaptation]').onclick=()=>download('mock-adaptation-request.md',adaptationRequest(),'text/markdown;charset=utf-8');panel.querySelector('[data-edit-answers]').onclick=()=>{state.status='questions';if(!save()){feedback('Не удалось сохранить состояние.');return}showQuestions()};}
    else if(state.resultName && state.inspection){const note=document.createElement('p');note.textContent='Папка new_mocks/ не найдена. Сохранность исходных моков не проверялась.';result.append(note);}
    else if(state.resultLink){const note=document.createElement('p');note.textContent='Ссылка не проверялась. Чтобы обнаружить new_mocks/, загрузи ZIP.';result.append(note);}
    if(state.resultName && state.inspection?.originalMocksPresent===false){const note=document.createElement('p');note.textContent='Папка mocks/ в ZIP не найдена. Уточни у автора проекта, где исходные данные.';result.append(note);}
    if (state.packageSignature && state.packageSignature!==contextSignature()) { const note=document.createElement('p');note.textContent='Материалы изменились после передачи: перед повторной работой собери пакет заново.';result.append(note); }
    if (state.resultName) {
      try {
        const stored=await fileStore('get');
        if (!panel.isConnected || panel.hidden || !panel.querySelector('[data-result-download]')) return;
        if (!stored?.file) { feedback('Сохранённый ZIP недоступен. Прикрепи его заново.'); }
        else { const b=panel.querySelector('[data-result-download]');b.hidden=false;b.onclick=()=>download(stored.name,stored.file,'application/zip'); }
      } catch { feedback('Не удалось открыть сохранённый ZIP.'); }
    }
    const replace=panel.querySelector('[data-replace]'); if(replace)replace.onclick=()=>{state.status='waiting';if(!save()){feedback('Не удалось сохранить состояние.');return}showWaiting()};
  }
  function open() { panel.hidden=false; if(state.status==='waiting')showWaiting();else if(state.status==='questions')showQuestions();else if(state.status==='received')showReceived();else showPackage(); panel.querySelector('[data-close]')?.focus(); }
  function close() { panel.hidden=true; toggle.focus(); }
  window.addEventListener('makora-open-prototype', open);
  window.addEventListener('resize', updatePosition);
  document.addEventListener('keydown', e => {if(e.key==='Escape' && !panel.hidden){e.stopImmediatePropagation();close();}}, true);
  return {show(){dock.hidden=false;updatePosition();}, updatePosition, open};
};

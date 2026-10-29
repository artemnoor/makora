// Stage 5 is a manual handoff: no external AI is contacted by this page.
window.createPrototypeHandoff = function(root, mascot, getSourceFile) {
  const key = 'makora.prototype-handoff.v1';
  const sampleKey = 'makora.prototype-example.v1';
  const prompt = 'Разработай запускаемый рабочий прототип по приложенным материалам. Сохрани исходную папку mocks/ целиком и без изменений: приложение должно использовать mocks/fixtures/ как источник данных, не дублировать их в коде и не подменять другими записями. Новые или изменённые моки помещай отдельно в new_mocks/; исходную mocks/ не изменяй и не удаляй. Реализуй основной сценарий MVP, соблюдай контракты, обработай пустые состояния и ошибки. Предусмотри воспроизводимое включение ошибки источника и опиши его в README. Противоречия и выбранные допущения зафиксируй в отчёте; продолжай работу, если они не блокируют обязательные требования. Учебные примеры не выдавай за требования, отметь демо-данные. Создай в корне changeset.json по приложенной changeset.schema.json: укажи базовую ревизию из iteration-context.json, фактические операции, пути, причину и связанные ID. Создай prototype-report.json: features, checks (id, status passed/failed/not_run, command, result), run_commands, known_limitations и contradictions. Указывай только фактически выполненные проверки; не выполненные помечай not_run. Добавь инструкцию запуска. При следующем цикле продолжай существующий проект из ZIP, не пересоздавай его. Верни проект ZIP-архивом.';
  let state, activeKey = key;
  function switchMode(sample) { activeKey=sample?sampleKey:key; try { state=JSON.parse(localStorage.getItem(activeKey))||{}; } catch { state={}; } selected=null; prepared=false; }
  let selected = null, sourceFile = null, prepared = false;
  const dock = document.createElement('div');
  dock.className = 'mascot-capabilities';
  dock.hidden = true;
  dock.innerHTML = `<button type="button" class="capabilities-toggle" aria-expanded="false">✳ Возможности</button><div class="capabilities-menu" hidden><button type="button" data-prototype-open><span>01</span><strong>Рабочий прототип</strong><span>↗</span></button><button type="button" data-example-open><span>02</span><strong>Тестовый кейс</strong><span>↗</span></button></div>`;
  root.append(dock);
  const panel = document.createElement('section');
  panel.className = 'prototype-dialog';
  panel.hidden = true;
  panel.setAttribute('aria-label', 'Рабочий прототип с внешним ИИ');
  root.append(panel);
  function save() { try { localStorage.setItem(activeKey, JSON.stringify(state)); return true; } catch { return false; } }
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
  dock.querySelector('[data-example-open]').onclick = () => { menu.hidden = true; toggle.setAttribute('aria-expanded', 'false'); openExample(); };
  const dbOpen = () => new Promise((resolve, reject) => {
    const request = indexedDB.open('makora-prototype-result', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('files');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error('Хранилище недоступно'));
    request.onblocked = () => reject(new Error('Хранилище занято другой вкладкой'));
  });
  async function fileStore(mode, value) {
    const fileKey = activeKey===sampleKey?'sample-result':'result';
    const db = await dbOpen();
    try { return await new Promise((resolve, reject) => {
      const tx = db.transaction('files', mode === 'get' ? 'readonly' : 'readwrite');
      const store = tx.objectStore('files');
      const req = mode === 'get' ? store.get(fileKey) : mode === 'delete' ? store.delete(fileKey) : store.put(value, fileKey);
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
    const localStatus=await apiStatus();
    const baseRevision=localStatus?.current_revision?.revision_id||null;
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
    add('README.md', `# Контекст для рабочего прототипа\n\n${originalNote}\n\nМатериалы этапов 1, 3 и 4 — демонстрационный кейс «Тихий кампус»; они не генерируются из загруженного условия и не обновляются после правки идеи. Используйте их как пример, а не как анализ исходного задания.\n\nБазовая ревизия и контрольная сумма записаны в iteration-context.json после сохранения пакета Макорой. При возврате укажи базовую ревизию в changeset.json. JSON Schema приложена в changeset.schema.json.\n\nИдея: ${ctx.project.approved?'утверждена':'не утверждена'}. План: ${ctx.readiness.ready?'утверждён':'требует проверки'}. Моки: ${mock.approved?'проверены и утверждены':'не утверждены или требуют повторной проверки'}. Результаты проверок — в отчётах; демонстрационные данные не являются реальными.\n`);
    add('01_case_analysis_DEMO.md', '# Демо-анализ «Тихий кампус»\n\n' + one.join('\n\n---\n\n'));
    add('02_research.md', ctx.project.research.map(x => x.md).join('\n\n---\n\n'));
    add('02_solution_concept.md', ctx.project.concept.map(x => x.md).join('\n\n---\n\n'));
    for (const item of window.makoraStage3.exportArtifacts()) add(item.name, item.text);
    for (const [path, text] of Object.entries(mock.files)) add(path, text);
    add('context-status.json', JSON.stringify({demo:true, base_revision:baseRevision, source:originalNote, ideaApproved:ctx.project.approved, planReady:ctx.readiness.ready, mocksApproved:mock.approved, mockChecksValid:mock.checksValid, mockCheckedAt:mock.validatedAt}, null, 2));
    const schemaResponse=await fetch('./changeset.schema.json',{cache:'no-store'});
    if(!schemaResponse.ok)throw new Error('Не удалось загрузить changeset.schema.json.');
    files['changeset.schema.json']=new Uint8Array(await schemaResponse.arrayBuffer());
    return {bytes:fflate.zipSync(files), signature:contextSignature(), status:{idea:ctx.project.approved, plan:ctx.readiness.ready, mocks:mock.approved}};
  }
  function shell(body) {
    panel.innerHTML = `<div class="prototype-shell"><div class="prototype-header"><span>РАБОЧИЙ ПРОТОТИП · 05</span><button type="button" data-close aria-label="Закрыть">×</button></div>${body}<p class="prototype-feedback" role="status"></p></div>`;
    panel.querySelector('[data-close]').onclick = close;
  }
  function feedback(message) { const el = panel.querySelector('.prototype-feedback'); if(el) el.textContent = message; }
  function apiBase() {
    const saved=localStorage.getItem('makora.local-api');
    return (saved || location.origin).replace(/\/$/,'');
  }
  async function api(path, options={}) {
    const saved=localStorage.getItem('makora.local-api');
    const bases=saved?[saved.replace(/\/$/,'')]:[apiBase(),...(location.port==='8765'?[]:['http://127.0.0.1:8765'])];
    let last;
    for(const base of [...new Set(bases)]){
      try{
        const response=await fetch(base+path,{...options,headers:{...(options.headers||{})}});
        const type=response.headers.get('content-type')||'';
        if(type.includes('application/zip')){if(!response.ok){const error=new Error('API: '+response.status);error.fatal=true;throw error;}return new Uint8Array(await response.arrayBuffer());}
        let value;try{value=await response.json();}catch{throw new Error('Локальный API недоступен.');}
        if(!response.ok||!value.ok){last=new Error(value.error?.message||'Операция локального API не выполнена.');if(response.status===404&&!saved)continue;last.fatal=true;throw last;}
        return value.result;
      }catch(error){last=error;if(saved||error.fatal)throw error;}
    }
    throw new Error('Локальная история недоступна. Запусти сервер Макоры; операции сравнения и согласования пока не выполнялись. '+(last?.message||''));
  }
  async function apiStatus() { try { return await api('/api/status'); } catch { return null; } }
  function esc(value) { return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  async function postZip(path, file) { return api(path,{method:'POST',headers:{'Content-Type':'application/zip'},body:file}); }
  async function openHistory() {
    try{
      const history=await api('/api/history');
      const item=[...history.iterations].reverse().find(entry=>entry.returned_at);
      if(!item){
        shell(`<h2>История<br>проекта.</h2><p>${history.iterations.length?'Сохранённые передачи:':'Пока нет сохранённых передач.'}</p>${history.iterations.map(i=>`<article class="prototype-change"><strong>${esc(i.iteration_id)}</strong><p>${esc(i.status)} · ${esc(i.created_at)}</p><button type="button" data-package-download="${esc(i.iteration_id)}">Скачать пакет</button>${i.status==='package_ready'?`<button type="button" data-mark-sent="${esc(i.iteration_id)}">Я передал пакет ИИ</button>`:`<button type="button" data-resume-wait="${esc(i.iteration_id)}">Продолжить ожидание</button>`}</article>`).join('')}<button class="prototype-text-button" type="button" data-history-back>Назад</button>`);
        panel.querySelector('[data-history-back]').onclick=()=>showPackage();
        for(const b of panel.querySelectorAll('[data-package-download]'))b.onclick=async()=>{try{const bytes=await api('/api/iterations/'+encodeURIComponent(b.dataset.packageDownload)+'/package');download(b.dataset.packageDownload+'-package.zip',bytes,'application/zip');}catch(error){feedback(error.message);}};
        for(const b of panel.querySelectorAll('[data-mark-sent]'))b.onclick=async()=>{try{await api('/api/iterations/'+encodeURIComponent(b.dataset.markSent)+'/sent',{method:'POST'});state.iterationId=b.dataset.markSent;state.apiAvailable=true;state.status='waiting';save();showWaiting();}catch(error){feedback(error.message);}};
        for(const b of panel.querySelectorAll('[data-resume-wait]'))b.onclick=()=>{state.iterationId=b.dataset.resumeWait;state.apiAvailable=true;state.status='waiting';save();showWaiting();};
        return;
      }
      state.iterationId=item.iteration_id;state.apiAvailable=true;state.status='review';save();
      await showReview();panel.querySelector('[data-history]')?.click();
    }catch(error){feedback(error.message);}
  }
  async function exampleFiles() {
    const rootUrl=new URL('./prototype-example/', location.href);
    const response=await fetch(new URL('manifest.json',rootUrl),{cache:'no-store'});
    if(!response.ok)throw new Error('Не удалось открыть тестовый кейс.');
    const manifest=await response.json();
    if(!Array.isArray(manifest.files) || !manifest.files.length)throw new Error('Список файлов кейса повреждён.');
    const items=await Promise.all(manifest.files.map(async name=>{
      if(typeof name!=='string'||name.startsWith('/')||name.includes('..')||name.includes('\\'))throw new Error('Некорректный путь в кейсе.');
      const result=await fetch(new URL(name,rootUrl),{cache:'no-store'});
      if(!result.ok)throw new Error('Не удалось прочитать '+name);
      return [name,new Uint8Array(await result.arrayBuffer())];
    }));
    return Object.fromEntries(items);
  }
  async function showExample() {
    shell(`<h2>Проверим на<br>реальном примере.</h2><p>Вымышленный кейс «Доступный город»: каталог учреждений, фильтры и карточки на мок-данных.</p><label for="prototype-prompt">ПРОМПТ ДЛЯ ИИ</label><textarea id="prototype-prompt" readonly>Загружаю промпт…</textarea><div class="prototype-actions"><button type="button" data-example-copy disabled>Скопировать промпт</button><button type="button" data-example-download disabled>Скачать кейс ↓</button></div><p class="prototype-note">В архиве: подробное ТЗ, идея, User flow и Task flow, C1–C3 и ER, OpenAPI, задачи, тесты, JSON Schema и моки. Данные вымышлены.</p><button class="prototype-primary" type="button" data-example-sent disabled>Я передал кейс ИИ <span>→</span></button>`);
    try {
      const response=await fetch('./prototype-example/PROMPT.md',{cache:'no-store'});
      if(!response.ok)throw new Error('Не удалось загрузить промпт.');
      const text=await response.text();
      if(panel.hidden||!panel.querySelector('[data-example-copy]'))return;
      panel.querySelector('#prototype-prompt').value=text;
      panel.querySelector('[data-example-copy]').disabled=false;
      panel.querySelector('[data-example-download]').disabled=false;
      panel.querySelector('[data-example-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(text);feedback('Промпт скопирован.')}catch{const el=panel.querySelector('#prototype-prompt');el.focus();el.select();feedback('Выдели текст и скопируй его.')}};
      panel.querySelector('[data-example-download]').onclick=async e=>{
        const button=e.currentTarget;button.disabled=true;feedback('Собираю тестовый кейс…');
        try{const files=await exampleFiles();if(activeKey!==sampleKey||!button.isConnected)return;download('dostupny-gorod-test-case.zip',fflate.zipSync(files),'application/zip');prepared=true;panel.querySelector('[data-example-sent]').disabled=false;feedback('Кейс готов. Прикрепи архив и промпт к своему ИИ.');}
        catch(error){feedback(error.message||'Не удалось собрать кейс.');}finally{if(button.isConnected)button.disabled=false;}
      };
      panel.querySelector('[data-example-sent]').onclick=()=>{if(!prepared)return;state.status='waiting';state.sentAt=new Date().toISOString();state.packageSignature=null;if(!save()){feedback('Не удалось сохранить состояние.');return}showWaiting();};
    } catch(error) { feedback(error.message||'Не удалось загрузить кейс.'); }
  }
  async function showPackage() {
    shell(`<h2>Давай создадим<br>рабочую версию.</h2><p>Я соберу короткое задание и файлы. Передай их своему ИИ, а готовый прототип принеси сюда.</p><label for="prototype-prompt">ПРОМПТ ДЛЯ ИИ</label><textarea id="prototype-prompt" readonly></textarea><div class="prototype-actions"><button type="button" data-copy>Скопировать промпт</button><button type="button" data-download>Скачать файлы ↓</button></div><p class="prototype-note">В архиве: исходное условие, анализ, идея, план, контракты, задачи и мок-данные. Учебные материалы помечены как демо.</p><button class="prototype-primary" type="button" data-sent disabled>Я передал пакет ИИ <span>→</span></button><button class="prototype-text-button" type="button" data-open-history>История проекта</button>`);
    panel.querySelector('[data-open-history]').onclick=openHistory;
    panel.querySelector('#prototype-prompt').value = prompt;
    panel.querySelector('[data-copy]').onclick = async () => { try { await navigator.clipboard.writeText(prompt); feedback('Промпт скопирован.'); } catch { const el=panel.querySelector('#prototype-prompt'); el.focus(); el.select(); feedback('Выдели текст и скопируй его.'); } };
    panel.querySelector('[data-download]').onclick = async e => {
      const button = e.currentTarget, mode = activeKey; button.disabled = true; feedback('Собираю файлы…');
      try {
        const result = await createPackage();
        if(activeKey!==mode||!button.isConnected)return;
        let bytes=result.bytes;
        const status=await apiStatus();
        if(status){
          const preparedIteration=await postZip('/api/iterations/prepare',bytes);
          state.iterationId=preparedIteration.iterations.at(-1)?.iteration_id;
          state.baseRevision=preparedIteration.current_revision?.revision_id;
          state.apiAvailable=true;
          bytes=await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/package');
        }else{state.apiAvailable=false;state.iterationId=null;}
        if(activeKey!==mode||!button.isConnected)return;
        download('makora-prototype-context.zip', bytes, 'application/zip');
        state.packageSignature = result.signature; state.packageStatus = result.status;
        if (!save()) throw new Error('Не удалось сохранить состояние на устройстве.');
        prepared = true; panel.querySelector('[data-sent]').disabled = false;
        feedback(!status?'Файлы собраны без истории: запусти локальный API для сравнения и согласования.':result.status.idea && result.status.plan && result.status.mocks ? 'Файлы собраны и сохранены в истории. Передай архив и промпт своему ИИ.' : 'Файлы собраны как черновик: идея, план или моки ещё требуют согласования. Проверь README в архиве.');
      } catch (error) { feedback(error.message || 'Не удалось собрать файлы.'); }
      finally { if (button.isConnected) button.disabled = false; }
    };
    panel.querySelector('[data-sent]').onclick = () => {
      if (!prepared || state.packageSignature !== contextSignature()) { feedback('Материалы изменились. Скачай пакет заново.'); panel.querySelector('[data-sent]').disabled = true; return; }
      const button=panel.querySelector('[data-sent]'); button.disabled=true;
      (async()=>{
        try {
          if(state.apiAvailable&&state.iterationId) await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/sent',{method:'POST'});
          state.status='waiting'; state.sentAt=new Date().toISOString();
          if(!save())throw new Error('Не удалось сохранить состояние на устройстве.');
          showWaiting();
          feedback(state.apiAvailable?'Пакет сохранён в локальной истории. После работы с ИИ верни ZIP сюда.':'История выключена: запусти локальный API, чтобы сравнивать версии и сохранять итерации.');
        } catch(error){feedback(error.message||'Не удалось подготовить итерацию.');}
        finally{if(button.isConnected)button.disabled=false;}
      })();
    };
  }
  function showWaiting() {
    shell(`<h2>Жду твою<br>рабочую версию.</h2><p>Когда закончишь с ИИ, прикрепи ZIP проекта. Макора сравнит его с сохранённой базовой версией.</p><div class="prototype-waiting">◌ &nbsp; ОЖИДАЮ РЕЗУЛЬТАТ</div><label class="prototype-drop"><input class="sr-only" type="file" accept=".zip,application/zip"><strong>＋ Выбрать ZIP проекта</strong><small>или перетащить сюда · до 100 МБ</small></label><label for="prototype-link">ИЛИ ССЫЛКА НА ПРОЕКТ</label><input id="prototype-link" type="url" placeholder="https://…"><button class="prototype-primary" type="button" data-receive>Вернуть результат <span>→</span></button><button class="prototype-text-button" type="button" data-package>Посмотреть пакет ещё раз</button>${activeKey===sampleKey?'':'<button class="prototype-text-button" type="button" data-open-history>История проекта</button>'}<p class="prototype-note">ZIP сравнивается с ревизией передачи. Код не запускается. Ссылки не загружаются автоматически.</p>`);
    if(panel.querySelector('[data-open-history]'))panel.querySelector('[data-open-history]').onclick=openHistory;
    if (state.packageSignature && state.packageSignature !== contextSignature()) feedback('Материалы изменились после передачи. Если нужно, собери и передай обновлённый пакет.');
    const input=panel.querySelector('input[type=file]'), drop=panel.querySelector('.prototype-drop');
    const select = file => { if (!file) return; if (!/\.zip$/i.test(file.name) || file.size > 100 * 1024 * 1024) { selected=null; feedback('Выбери ZIP размером до 100 МБ.'); return; } selected=file; drop.querySelector('strong').textContent=file.name; feedback(''); };
    input.onchange = () => select(input.files[0]);
    ['dragenter','dragover'].forEach(type => drop.addEventListener(type, e => {e.preventDefault();drop.classList.add('dragging')}));
    ['dragleave','drop'].forEach(type => drop.addEventListener(type, e => {e.preventDefault();drop.classList.remove('dragging')}));
    drop.addEventListener('drop', e => select(e.dataTransfer.files[0]));
    panel.querySelector('[data-package]').onclick = () => { prepared=false; activeKey===sampleKey?showExample():showPackage(); };
    panel.querySelector('[data-receive]').onclick = async e => {
      const link=panel.querySelector('#prototype-link').value.trim();
      if (!selected && !link) { feedback('Прикрепи ZIP или вставь ссылку на проект.'); return; }
      if (link) { try { const url=new URL(link); if (!['http:','https:'].includes(url.protocol)) throw new Error(); } catch { feedback('Укажи ссылку, начинающуюся с http:// или https://.'); return; } }
      const button=e.currentTarget, mode=activeKey; button.disabled=true;
      try {
        const inspection=selected ? await inspectZip(selected) : {hasNewMocks:false,newMocksPaths:[],originalMocksPresent:null};
        if(activeKey!==mode||!button.isConnected)return;
        let iterationResult=null;
        if(selected && activeKey!==sampleKey && state.iterationId){
          iterationResult=await postZip('/api/iterations/'+encodeURIComponent(state.iterationId)+'/result',new Uint8Array(await selected.arrayBuffer()));
        }
        if (selected) await fileStore('put', {name:selected.name, file:selected}); else { try { await fileStore('delete'); } catch (_) {} }
        if(activeKey!==mode||!button.isConnected)return;
        state.status=inspection.hasNewMocks?'questions':'received'; state.resultName=selected?.name||''; state.resultLink=link; state.receivedAt=new Date().toISOString();
        state.inspection=inspection; state.mockAnswers=null;
        if(iterationResult){state.iterationResult=iterationResult;state.status='review';}
        if (!save()) { state.status='waiting'; throw new Error('Не удалось сохранить состояние на устройстве.'); }
        selected=null; if(state.status==='questions')showQuestions();else if(state.status==='review')showReview();else showReceived();
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
        if (!panel.isConnected || panel.hidden || panel.querySelector('.prototype-result') !== result || !panel.querySelector('[data-result-download]')) return;
        if (!stored?.file) { feedback('Сохранённый ZIP недоступен. Прикрепи его заново.'); }
        else { const b=panel.querySelector('[data-result-download]');b.hidden=false;b.onclick=()=>download(stored.name,stored.file,'application/zip'); }
      } catch { feedback('Не удалось открыть сохранённый ZIP.'); }
    }
    const replace=panel.querySelector('[data-replace]'); if(replace)replace.onclick=()=>{state.status='waiting';if(!save()){feedback('Не удалось сохранить состояние.');return}showWaiting()};
  }
  function renderChange(change) {
    const status={pending:'Нужно решение',accepted:'Принято',rejected:'Отклонено',revision_requested:'На доработку'}[change.decision]||change.decision;
    const impacts=(change.impacted_stages||[]).map(x=>'Подтверждённая связь: этап '+x).join(' · ')||((change.possible_stages||[]).length?'Возможное влияние: этап '+change.possible_stages.join(', ')+' · требуется оценка':'Подтверждённых связей с документами нет');
    const diff=change.diff?`<details><summary>Было / стало</summary><pre class="prototype-diff">${esc(change.diff)}</pre></details>`:`<p class="prototype-note">Было: ${esc(change.size_before??'нет')} байт · SHA-256 ${esc(change.before_sha256||'—')}<br>Стало: ${esc(change.size_after??'нет')} байт · SHA-256 ${esc(change.after_sha256||'—')}</p>`;
    const actions=change.decision==='informational'?'':`<label class="prototype-change-note">Комментарий к решению<textarea data-decision-note placeholder="Что нужно изменить?">${esc(change.decision_note||'')}</textarea></label><div class="prototype-actions" data-decisions="${esc(change.id)}"><button type="button" data-decision="accept">Принять</button><button type="button" data-decision="revise">Доработать</button><button type="button" data-decision="reject">Отклонить</button></div>`;
    const related=(change.related_artifacts||[]).length?`<p class="prototype-note">Связи: ${(change.related_artifacts||[]).map(x=>esc(x.artifact)+(x.basis==='inferred'?' (предположение)':'')+(x.distance>1?' (косвенно)':'')).join(', ')}</p>`:'';
    const category={application:'код проекта',artifact:'документ',data:'данные'}[change.category]||'файл';
    return `<article class="prototype-change"><header><strong>${change.old_path?esc(change.old_path)+' → ':''}${esc(change.path)}</strong><span>${esc(change.operation)} · ${esc(status)}</span></header><p>${esc(change.reason||'Внешний ИИ не указал причину изменения.')}</p><small>${category} · ${esc(impacts)}${change.mocks_changed?' · изменены mocks':''}${change.proposal?' · предложение документации':''}</small>${related}${diff}${actions}</article>`;
  }
  async function showReview() {
    if(!state.iterationId||!state.apiAvailable){showReceived();return;}
    let item; try{item=await api('/api/iterations/'+encodeURIComponent(state.iterationId));}catch(error){shell(`<h2>История недоступна.</h2><p>${esc(error.message)}</p>`);return;}
    state.iterationResult=item;state.status='review';save();
    const changes=item.changes||[];
    const questions=(item.questions||[]).filter(q=>q.required);
    shell(`<h2>Сверим<br>изменения.</h2><p>База: <code>${esc(item.base_revision)}</code>${item.stale_base?'<strong> · Базовая версия устарела</strong>':''}</p><p>${changes.length?`Найдено файловых изменений: ${changes.length}. Каждое изменение ждёт твоего решения.`:'Файлы совпадают с базовой версией.'}</p><div class="prototype-result"><h3>Проверки</h3>${(item.checks||[]).map(c=>`<p><strong>${esc(c.status)}</strong> · ${esc(c.detail)}</p>`).join('')}<p>Изменения без причины: ${esc(item.changeset?.undeclared?.length??changes.length)}. Структурное сравнение не является смысловой экспертизой.</p></div>${questions.length?`<section class="prototype-questions"><h3>Нужно уточнить</h3>${questions.map(q=>`<label for="question-${esc(q.id)}">${esc(q.text)}</label><textarea id="question-${esc(q.id)}" data-question="${esc(q.id)}" placeholder="Твоё решение"></textarea>`).join('')}<button class="prototype-text-button" type="button" data-save-questions>Сохранить ответы</button></section>`:''}<div class="prototype-changes">${changes.map(renderChange).join('')}</div><button class="prototype-primary" type="button" data-adaptation-package>Подготовить пакет документации <span>↓</span></button><label class="prototype-drop"><input class="sr-only" type="file" accept=".zip,application/zip" data-adaptation-file><strong>＋ Вернуть ZIP с обновлёнными документами</strong><small>proposals/ и adaptation-report.json</small></label><div class="prototype-adapted"></div><button class="prototype-primary" type="button" data-approve-revision>Согласовать версию <span>→</span></button><button class="prototype-text-button" type="button" data-history>История версий</button><button class="prototype-text-button" type="button" data-next-iteration>Скачать проект для следующей итерации ↓</button><button class="prototype-text-button" type="button" data-replace>Заменить результат</button><p class="prototype-note">Код проекта не выполнялся. Проверки ZIP и связей — автоматические; смысловое решение остаётся за тобой.</p>`);
    const agentReport=item.prototype_report||{};
    const reportBox=document.createElement('section');reportBox.className='prototype-result prototype-agent-report';
    const reportTitle=document.createElement('h3');reportTitle.textContent='Отчёт внешнего ИИ';reportBox.append(reportTitle);
    const reportStatus=document.createElement('p');reportStatus.textContent=agentReport.status==='not_run'?'Отчёт отсутствует: реализация и проверки не подтверждены.':agentReport.status==='failed'?'Формат отчёта содержит ошибки.': 'Формат отчёта прочитан; статусы ниже заявлены внешним ИИ и отдельно не перепроверялись.';reportBox.append(reportStatus);
    for(const check of agentReport.checks||[]){const row=document.createElement('p');row.textContent=`${check.id} · ${check.status} · ${check.command||''} · ${check.result||''}`;reportBox.append(row);}
    if((agentReport.features||[]).length){const features=document.createElement('p');features.textContent='Реализованные функции по отчёту: '+agentReport.features.map(x=>typeof x==='string'?x:JSON.stringify(x)).join('; ');reportBox.append(features);}
    if((agentReport.known_limitations||[]).length){const limitations=document.createElement('p');limitations.textContent='Ограничения: '+agentReport.known_limitations.map(x=>typeof x==='string'?x:JSON.stringify(x)).join('; ');reportBox.append(limitations);}
    panel.querySelector('.prototype-result').after(reportBox);
    if(item.impacted_artifacts?.length){const impact=document.createElement('p');impact.className='prototype-note';impact.textContent='Влияние на документы: '+item.impacted_artifacts.map(x=>x.artifact+(x.basis==='inferred'?' (предположение)':' (связь подтверждена)')).join(', ');reportBox.after(impact);}
    if(item.conflicts?.length){const warning=document.createElement('p');warning.className='prototype-note';warning.textContent='Конфликт решений: '+item.conflicts.map(x=>x.message).join(' ');reportBox.after(warning);}
    for(const textarea of panel.querySelectorAll('[data-question]')) textarea.value=item.question_answers?.[textarea.dataset.question]||'';
    const saveQuestions=panel.querySelector('[data-save-questions]');if(saveQuestions)saveQuestions.onclick=async()=>{const answers={};const fields=[...panel.querySelectorAll('[data-question]')];for(const textarea of fields)if(textarea.value.trim())answers[textarea.dataset.question]=textarea.value.trim();if(Object.keys(answers).length!==fields.length){feedback('Ответь на все показанные вопросы.');return;}try{await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/questions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers})});await showReview();feedback('Ответы сохранены.');}catch(error){feedback(error.message);}};
    for(const group of panel.querySelectorAll('[data-decisions]')) for(const button of group.querySelectorAll('[data-decision]')) button.onclick=async()=>{const note=group.closest('.prototype-change')?.querySelector('[data-decision-note]')?.value.trim()||'';if(button.dataset.decision==='revise'&&!note){feedback('Напиши, что нужно доработать.');return;}try{const updated=await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/decisions/'+encodeURIComponent(group.dataset.decisions),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.decision,note})});state.iterationResult=updated;save();showReview();}catch(error){feedback(error.message);}};
    const revisionRequested=changes.filter(change=>change.decision==='revision_requested');
    if(revisionRequested.length){const revisionButton=document.createElement('button');revisionButton.type='button';revisionButton.className='prototype-text-button';revisionButton.textContent='Скачать запрос на доработку ↓';panel.querySelector('.prototype-changes').after(revisionButton);revisionButton.onclick=async()=>{try{const original=await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/result');const text='# Доработай возвращённый проект\n\nСохрани исходные mocks/. Исправь только перечисленные изменения, обнови changeset.json и отчёт проверок.\n\n'+revisionRequested.map(c=>`## ${c.path}\n\n${c.decision_note||'Требуется уточнение.'}\n\n${c.diff?'```diff\n'+c.diff+'\n```\n':''}`).join('\n');const bytes=fflate.zipSync({'REQUEST.md':fflate.strToU8(text),'returned-project.zip':original});download('makora-revision-request.zip',bytes,'application/zip');feedback('Запрос и текущий проект собраны в ZIP.');}catch(error){feedback(error.message);}};}
    panel.querySelector('[data-adaptation-package]').onclick=async()=>{try{const bytes=await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/adaptation-package',{method:'POST'});download('makora-adaptation.zip',bytes,'application/zip');feedback('Пакет готов. Передай его внешнему ИИ.');}catch(error){feedback(error.message);}};
    const adaptationInput=panel.querySelector('[data-adaptation-file]');adaptationInput.onchange=async()=>{const file=adaptationInput.files?.[0];if(!file)return;try{const adapted=await postZip('/api/iterations/'+encodeURIComponent(state.iterationId)+'/adaptation',new Uint8Array(await file.arrayBuffer()));state.iterationResult=adapted;save();showReview();}catch(error){feedback(error.message);}};
    const docs=panel.querySelector('.prototype-adapted');
    if(item.adapted_docs){docs.innerHTML='<h3>Документы на проверку</h3>'+(item.adaptation?.checks||[]).map(c=>`<p>${esc(c.status)} · ${esc(c.detail)}</p>`).join('')+Object.entries(item.adapted_docs).map(([path,meta])=>`<article class="prototype-change"><header><strong>${esc(meta.target||path)}</strong><span>${esc(item.document_decisions?.[path]||'pending')}</span></header><small>SHA-256 ${esc(meta.sha256)}</small>${meta.diff?`<details><summary>Было / стало</summary><pre class="prototype-diff">${esc(meta.diff)}</pre></details>`:''}<div class="prototype-actions" data-document="${esc(path)}"><button type="button" data-doc-decision="accept">Принять документ</button><button type="button" data-doc-decision="reject">Отклонить</button></div></article>`).join('');for(const group of docs.querySelectorAll('[data-document]'))for(const b of group.querySelectorAll('[data-doc-decision]'))b.onclick=async()=>{try{await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/documents',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:group.dataset.document,action:b.dataset.docDecision})});await showReview();}catch(error){feedback(error.message);}};}
    if(Array.isArray(item.adaptation?.report?.reviewed_unchanged)&&item.adaptation.report.reviewed_unchanged.length){const note=document.createElement('p');note.textContent='По отчёту рассмотрены без изменений: '+item.adaptation.report.reviewed_unchanged.join(', ');docs.prepend(note);}
    panel.querySelector('[data-approve-revision]').onclick=async()=>{try{const result=await api('/api/iterations/'+encodeURIComponent(state.iterationId)+'/approve',{method:'POST'});state.approvedRevision=result.approved_revision;state.status='approved';save();try{localStorage.setItem('makora.current-revision.v1',result.approved_revision);}catch{}window.dispatchEvent(new Event('makora-revision-updated'));await showReview();feedback('Создана версия '+result.approved_revision+'. Её файлы доступны на доске через «Файлы версии».');}catch(error){feedback(error.message);}};
    panel.querySelector('[data-history]').onclick=async()=>{try{
      const history=await api('/api/history');const current=history.current_revision?.revision_id;
      const revisions=history.revisions.map(r=>`<article class="prototype-change"><strong>${esc(r.revision_id)}${r.current?' · текущая':''}</strong><p>${esc(r.reason)} · ${esc(r.created_at)}</p><div class="prototype-actions"><button type="button" data-revision-download="${esc(r.revision_id)}">Скачать версию</button>${r.current?'':`<button type="button" data-compare="${esc(r.revision_id)}">Сравнить с текущей</button><button type="button" data-rollback="${esc(r.revision_id)}">Откатить новой версией</button>`}</div></article>`).join('');
      const iterations=history.iterations.map(i=>`<article class="prototype-change"><strong>${esc(i.iteration_id)}</strong><p>${esc(i.status)} · база ${esc(i.base_revision)} · ${esc(i.created_at)}</p><button type="button" data-view-iteration="${esc(i.iteration_id)}" data-iteration-status="${esc(i.status)}">Открыть итерацию</button><button type="button" data-package-download="${esc(i.iteration_id)}">Скачать переданный пакет</button>${i.returned_at?`<button type="button" data-latest-return="${esc(i.iteration_id)}">Скачать возвращённый проект</button>`:''}${(i.return_history||[]).map((r,n)=>`<button type="button" data-old-return="${esc(i.iteration_id)}:${n}">Скачать предыдущую загрузку ${n+1}</button>`).join('')}</article>`).join('');
      docs.innerHTML='<h3>История итераций</h3>'+iterations+'<h3>История версий</h3>'+revisions+'<div data-comparison></div>';
      for(const b of docs.querySelectorAll('[data-rollback]'))b.onclick=async()=>{try{const rolled=await api('/api/revisions/'+encodeURIComponent(b.dataset.rollback)+'/rollback',{method:'POST'});try{localStorage.setItem('makora.current-revision.v1',rolled.revision.revision_id);}catch{}window.dispatchEvent(new Event('makora-revision-updated'));await showReview();feedback('Создана новая ревизия '+rolled.revision.revision_id+'; история сохранена.');}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-revision-download]'))b.onclick=async()=>{try{const bytes=await api('/api/revisions/'+encodeURIComponent(b.dataset.revisionDownload)+'/archive');download(b.dataset.revisionDownload+'.zip',bytes,'application/zip');}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-package-download]'))b.onclick=async()=>{try{const bytes=await api('/api/iterations/'+encodeURIComponent(b.dataset.packageDownload)+'/package');download(b.dataset.packageDownload+'-package.zip',bytes,'application/zip');}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-compare]'))b.onclick=async()=>{try{const result=await api('/api/revisions/'+encodeURIComponent(b.dataset.compare)+'/compare/'+encodeURIComponent(current));const target=docs.querySelector('[data-comparison]');target.innerHTML='<h3>Изменения версий</h3>'+(result.changes.length?result.changes.map(renderChange).join(''):'<p>Файлы совпадают.</p>');for(const actions of target.querySelectorAll('[data-decisions],.prototype-change-note'))actions.remove();target.scrollIntoView({block:'nearest'});}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-old-return]'))b.onclick=async()=>{try{const [id,index]=b.dataset.oldReturn.split(':');const bytes=await api('/api/iterations/'+encodeURIComponent(id)+'/returns/'+index);download(id+'-return-'+(Number(index)+1)+'.zip',bytes,'application/zip');}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-latest-return]'))b.onclick=async()=>{try{const bytes=await api('/api/iterations/'+encodeURIComponent(b.dataset.latestReturn)+'/result');download(b.dataset.latestReturn+'-result.zip',bytes,'application/zip');}catch(error){feedback(error.message);}};
      for(const b of docs.querySelectorAll('[data-view-iteration]'))b.onclick=async()=>{state.iterationId=b.dataset.viewIteration;state.apiAvailable=true;state.status=['package_ready','waiting_external'].includes(b.dataset.iterationStatus)?'waiting':'review';save();if(state.status==='waiting')showWaiting();else await showReview();};
    }catch(error){feedback(error.message);}};
    panel.querySelector('[data-next-iteration]').textContent='Начать следующую итерацию →';
    panel.querySelector('[data-next-iteration]').onclick=async()=>{state.status='';state.iterationId=null;state.approvedRevision=null;prepared=false;save();await showPackage();feedback('Собери пакет: в него войдёт последняя согласованная версия проекта.');};
    if(item.stale_base){const rebase=document.createElement('button');rebase.type='button';rebase.className='prototype-text-button';rebase.textContent='Подготовить новую итерацию от текущей версии';panel.querySelector('[data-next-iteration]').after(rebase);rebase.onclick=async()=>{state.status='';state.iterationId=null;prepared=false;save();await showPackage();feedback('Скачай новый пакет и передай его ИИ вместе с прежним результатом из истории.');};}
    panel.querySelector('[data-replace]').onclick=()=>{state.status='waiting';save();showWaiting();};
    if(item.status==='approved'){
      for(const control of panel.querySelectorAll('[data-decision],[data-doc-decision],[data-adaptation-package],[data-adaptation-file],[data-approve-revision],[data-save-questions]'))control.disabled=true;
      panel.querySelector('[data-replace]').hidden=true;
    }else panel.querySelector('[data-next-iteration]').disabled=true;
  }
  function showMode() { panel.hidden=false; if(state.status==='waiting')showWaiting();else if(state.status==='questions')showQuestions();else if(state.status==='review'&&state.iterationId)showReview();else if(state.status==='received')showReceived();else if(activeKey===sampleKey)showExample();else showPackage(); panel.querySelector('[data-close]')?.focus(); }
  function open() { switchMode(false); showMode(); }
  function openExample() { switchMode(true); showMode(); }
  function close() { panel.hidden=true; toggle.focus(); }
  window.addEventListener('makora-open-prototype', open);
  window.addEventListener('resize', updatePosition);
  document.addEventListener('keydown', e => {if(e.key==='Escape' && !panel.hidden){e.stopImmediatePropagation();close();}}, true);
  return {show(){dock.hidden=false;updatePosition();}, updatePosition, open,
    currentDocuments(stage){return api('/api/revisions/current/documents?stage='+encodeURIComponent(String(stage).padStart(2,'0')));}};
};

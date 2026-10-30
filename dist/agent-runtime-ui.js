/* REAL mode for stage 6. Talks to the local Makora controller; DEMO stays intact. */
(() => {
  let authToken = null;
  let selectedRun = localStorage.getItem('makora.agent-real-run') || '';
  let lastContext = null;
  let refreshTimer = 0;
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  async function token() {
    if (authToken) return authToken;
    const response = await fetch('/api/agents/token', {credentials:'same-origin', cache:'no-store'});
    const body = await response.json();
    if (!response.ok || !body.result?.token) throw new Error(body.error?.message || 'Не удалось получить токен локального API. Открой Макору с того же адреса, на котором запущен сервер.');
    authToken = body.result.token;
    return authToken;
  }
  async function api(path, options={}) {
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-Makora-Token', await token());
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, {...options, headers, credentials:'same-origin', cache:'no-store'});
    const body = await response.json();
    if (!response.ok || body.ok === false) throw new Error(body.error?.message || body.error || `HTTP ${response.status}`);
    return body.result ?? body;
  }
  const taskStateLabel = status => ({pending:'ожидает',ready:'готова к запуску',implementing:'Builder выполняет',review_pending:'ожидает Reviewer',reviewing:'Reviewer проверяет',review_completed:'ревью завершено',failed:'ошибка'})[status] || status || 'не запущена';
  const sessionStateLabel = status => ({accepted:'запрос принят',delivered:'сообщение доставлено',running:'выполняется',completed:'ответ завершён',failed:'ошибка',unconfirmed:'результат не подтверждён'})[status] || status;
  function tasksFromPlan(workflow) {
    return workflow.getTasks().map(task => ({id:task.id,title:task.title,goal:task.goal,acceptance:task.acceptance,dependsOn:task.dependsOn,contracts:task.contracts,mocks:task.mocks,builderPrompt:task.builderPrompt,testPrompt:task.testPrompt,reviewerPrompt:task.reviewerPrompt}));
  }
  async function getState() {
    const data = await api('/api/agents/state');
    const runs = data.runs || [];
    if (!selectedRun && runs.length) selectedRun = runs[runs.length-1].id;
    const run = runs.find(item => item.id === selectedRun) || null;
    if (run && run.id !== selectedRun) selectedRun = run.id;
    return {run, sessions:data.sessions || [], events:data.events || []};
  }
  async function render(ctx) {
    lastContext = ctx;
    const {content,status,primary,workflow,announce}=ctx;
    if (primary) primary.hidden = true;
    clearTimeout(refreshTimer);
    let connection;
    try { connection = await api('/api/agents/status'); }
    catch(error) { connection = {connected:false,modelAvailable:false,error:{message:error.message},allowedRoots:[]}; }
    let state={run:null,sessions:[],events:[]};
    try { state = await getState(); } catch {}
    let approvals=[];
    try { approvals=await api('/api/agents/approvals'); } catch {}
    const run=state.run;
    const allowed=(connection.allowedRoots||[]).map(escapeHtml).join('<br>')||'не настроены';
    const isConnected=connection.connected&&connection.modelAvailable;
    const tasks=run?.tasks || [];
    const taskCards=tasks.map(task=>{
      const deps=task.dependsOn?.length?task.dependsOn.join(', '):'нет';
      const sessions=state.sessions.filter(session=>session.runId===run.id&&session.taskId===task.id);
      const builder=sessions.find(session=>session.role==='builder');
      const reviewer=sessions.find(session=>session.role==='reviewer');
      const designer=sessions.find(session=>session.role==='test_designer');
      const controls=[];
      if (task.status==='pending' && !designer) controls.push(`<button type="button" data-agent-action="test_designer" data-task="${escapeHtml(task.id)}" ${!isConnected?'disabled':''}>Test Designer</button>`);
      if (task.status==='pending') controls.push(`<button type="button" data-agent-action="worktree" data-task="${escapeHtml(task.id)}">Создать worktree</button>`);
      if (task.status==='ready') controls.push(`<button type="button" data-agent-action="builder" data-task="${escapeHtml(task.id)}" ${(!isConnected||designer?.status!=='completed')?'disabled':''}>Запустить Builder</button>${designer?.status!=='completed'?'<small class="real-gate-note">Builder откроется после завершения независимого Test Designer.</small>':''}`);
      if (task.status==='review_pending') controls.push(`<button type="button" data-agent-action="reviewer" data-task="${escapeHtml(task.id)}" ${!isConnected?'disabled':''}>Запустить Reviewer</button>`);
      return `<article class="real-task"><header><b>${escapeHtml(task.id)}</b><span>${escapeHtml(taskStateLabel(task.status))}</span></header><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.goal)}</p><small>Зависимости: ${escapeHtml(deps)} · ветка: <code>${escapeHtml(task.branch||'ещё не создана')}</code></small><div class="real-actions">${controls.join('')}</div>${task.worktree?`<details><summary>Рабочая директория и diff</summary><code>${escapeHtml(task.worktree)}</code><button type="button" data-agent-diff="${escapeHtml(task.id)}">Обновить diff</button><pre data-diff="${escapeHtml(task.id)}"></pre></details>`:''}${designer?`<p class="real-session-line">Test Designer · ${escapeHtml(designer.threadId)} · ${escapeHtml(sessionStateLabel(designer.status))}</p>`:''}${builder?`<p class="real-session-line">Builder · ${escapeHtml(builder.threadId)} · ${escapeHtml(sessionStateLabel(builder.status))}</p>${builder.result?`<details><summary>Ответ Builder</summary><pre>${escapeHtml(JSON.stringify(builder.result,null,2))}</pre></details>`:''}`:''}${reviewer?`<p class="real-session-line">Reviewer · ${escapeHtml(reviewer.threadId)} · ${escapeHtml(sessionStateLabel(reviewer.status))}</p>${reviewer.result?`<details><summary>Результат Reviewer · требует проверки тестов</summary><pre>${escapeHtml(JSON.stringify(reviewer.result,null,2))}</pre></details>`:''}`:''}</article>`;
    }).join('');
    content.innerHTML=`<section class="real-agent-view"><div class="real-status ${connection.connected?'online':'offline'}"><div><span class="real-kicker">CODEX APP SERVER</span><strong>${connection.connected?'Локальный App Server подключён':'Нет подключения к локальному App Server'}</strong><small>${escapeHtml(connection.appServerVersion||connection.error?.message||'Проверь запуск Codex Desktop и App Server.')}${connection.modelAvailable?' · Каталог содержит gpt-6-luna; доступность генерации подтверждается только ответом агента.':''}</small></div><button type="button" data-agent-refresh>Проверить</button></div><p class="real-caveat">Реальные агенты изменяют файлы в отдельных Git worktree. Интеграция и запуск кода не автоматизируются без подтверждённых тестов и изоляции. App Server thread ID виден здесь; отображение всех таких чатов в окне Codex Desktop не гарантируется.</p>${!run?`<section class="real-create-run"><h3>Подготовить настоящий запуск</h3><p>Укажи разрешённую Git-папку проекта. Макора проверит чистоту основной ветки и создаст отдельный worktree для каждой задачи.</p><label>Путь к Git-проекту<input data-project-root autocomplete="off" placeholder="C:\\Projects\\my-app"></label><details><summary>Разрешённые корни</summary><p>${allowed}</p><small>Чтобы добавить другие папки, передай серверу параметр <code>--agent-root</code>.</small></details><div class="real-plan-summary"><b>${workflow.getTasks().length} задач из утверждённой карты</b><span>Зависимости проверяются сервером · максимум 2 параллельных Builder</span></div><button type="button" data-agent-create-run ${!isConnected?'disabled':''}>Создать план запуска</button></section>`:`<header class="real-run-header"><div><span class="real-kicker">${escapeHtml(run.id)} · ${escapeHtml(run.baseCommit.slice(0,12))}</span><h3>${escapeHtml(run.projectRoot)}</h3></div><button type="button" data-agent-new-run>Новый запуск</button></header><div class="real-task-list">${taskCards}</div><section class="real-report"><h3>Решение об интеграции</h3><p>Статус: <b>не выполнялась</b>. Перед merge нужны фактические тесты в изолированной среде, результат Reviewer и подтверждение пользователя. Код из worktree автоматически не запускается.</p></section>`}<section class="real-agent-list"><h3>Агенты и события</h3>${state.sessions.filter(s=>!run||s.runId===run.id).map(s=>`<article><div><b>${escapeHtml(s.role)} · ${escapeHtml(s.taskId)}</b><span>${escapeHtml(sessionStateLabel(s.status))}</span></div><code>thread ${escapeHtml(s.threadId)}</code><small>${escapeHtml(s.model)} · ${escapeHtml(s.cwd)}</small><button type="button" data-agent-poll="${escapeHtml(s.id)}">Обновить состояние</button></article>`).join('')||'<p>Настоящие Codex-сессии ещё не создавались.</p>'}</section><details class="real-history"><summary>Журнал контроллера</summary><ol>${state.events.map(event=>`<li><time>${escapeHtml(new Date(event.at).toLocaleTimeString('ru-RU'))}</time> ${escapeHtml(event.type)} · ${escapeHtml(event.detail)}</li>`).join('')||'<li>Событий пока нет.</li>'}</ol></details></section>`;
    if(approvals.length){const section=document.createElement('section');section.className='real-approvals';section.innerHTML=`<h3>Подтверждение действий Codex</h3>${approvals.map(item=>`<article><div><b>${escapeHtml(item.method||'Запрос действия')}</b><pre>${escapeHtml(JSON.stringify(item.params||{},null,2))}</pre></div><button type="button" data-approval="${escapeHtml(item.requestId)}" data-decision="accept">Разрешить</button><button type="button" data-approval="${escapeHtml(item.requestId)}" data-decision="decline">Отклонить</button></article>`).join('')}`;content.querySelector('.real-status').after(section);section.querySelectorAll('[data-approval]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/api/agents/approvals/${button.dataset.approval}`,{method:'POST',body:JSON.stringify({decision:button.dataset.decision})});await render(ctx)}catch(error){announce(error.message);button.disabled=false}}))}
    status.textContent=connection.connected?(connection.modelAvailable?'APP SERVER ПОДКЛЮЧЁН · GPT-6 LUNA ЕСТЬ В КАТАЛОГЕ':'APP SERVER ПОДКЛЮЧЁН · GPT-6 LUNA НЕТ В КАТАЛОГЕ'):'НЕТ ПОДКЛЮЧЕНИЯ К APP SERVER';
    content.querySelector('[data-agent-refresh]')?.addEventListener('click',()=>render(ctx));
    content.querySelector('[data-agent-new-run]')?.addEventListener('click',()=>{selectedRun='';localStorage.removeItem('makora.agent-real-run');render(ctx)});
    content.querySelector('[data-agent-create-run]')?.addEventListener('click',async()=>{const button=content.querySelector('[data-agent-create-run]');button.disabled=true;try{const created=await api('/api/agents/runs',{method:'POST',body:JSON.stringify({projectRoot:content.querySelector('[data-project-root]').value.trim(),tasks:tasksFromPlan(workflow)})});selectedRun=created.id;localStorage.setItem('makora.agent-real-run',selectedRun);await render(ctx)}catch(error){announce(error.message);button.disabled=false}});
    content.querySelectorAll('[data-agent-action]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;const task=button.dataset.task,action=button.dataset.agentAction;try{if(action==='worktree')await api(`/api/agents/runs/${run.id}/tasks/${task}/worktree`,{method:'POST',body:'{}'});else await api(`/api/agents/runs/${run.id}/tasks/${task}/agents/${action}`,{method:'POST',body:'{}'});await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-poll]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/api/agents/sessions/${button.dataset.agentPoll}`);await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-diff]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const diff=await api(`/api/agents/runs/${run.id}/tasks/${button.dataset.agentDiff}/diff`);const pre=content.querySelector(`[data-diff="${button.dataset.agentDiff}"]`);pre.textContent=`${diff.status||'(чисто)'}\n\n${diff.diff||'(diff пока пуст)'}\n\nФайлы: ${(diff.changedFiles||[]).join(', ')||'нет'}`}catch(error){announce(error.message)}finally{button.disabled=false}}));
    if(run&&state.sessions.some(s=>s.runId===run.id&&['accepted','delivered','running'].includes(s.status))) refreshTimer=setTimeout(()=>render(ctx),3000);
  }
  window.makoraRealAgents={render};
})();

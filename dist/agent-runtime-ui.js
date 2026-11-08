/* REAL mode for stage 6. Talks to the local Makora controller; DEMO stays intact. */
(() => {
  let authToken = null;
  let selectedRun = localStorage.getItem('makora.agent-real-run') || '';
  let lastContext = null;
  let refreshTimer = 0;
  let renderGeneration = 0;
  const preparationPanels = new Map();
  const runtimeMotion = new Map();
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  async function token() {
    if (authToken) return authToken;
    const response = await fetch('/api/agents/token', {credentials:'same-origin', cache:'no-store', headers:{'X-Makora-Request':'token'}});
    const body = await response.json();
    if (!response.ok || !body.result?.token) throw new Error(body.error?.message || 'Не удалось получить токен локального API. Открой Макору с того же адреса, на котором запущен сервер.');
    authToken = body.result.token;
    return authToken;
  }
  async function api(path, options={}) {
    const mutation=options.method&&options.method!=='GET';
    if(mutation)window.dispatchEvent(new CustomEvent('makora:activity',{detail:{active:true,text:'Контроллер выполняет действие…'}}));
    try{
    const headers = new Headers(options.headers || {});
    if (options.method && options.method !== 'GET') headers.set('X-Makora-Token', await token());
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, {...options, headers, credentials:'same-origin', cache:'no-store'});
    const body = await response.json();
    if (!response.ok || body.ok === false) { const error=new Error(body.error?.message || body.error || `HTTP ${response.status}`);error.code=body.error?.code;error.details=body.error?.details;throw error; }
    return body.result ?? body;
    }finally{if(mutation)window.dispatchEvent(new CustomEvent('makora:activity',{detail:{active:false}}))}
  }
  const taskStateLabel = status => ({integrated:'готово · интегрировано',pending:'в очереди',ready:'готова к запуску',implementing:'Builder выполняет',review_pending:'требует независимых тестов',reviewing:'Reviewer проверяет',review_completed:'ревью завершено',changes_requested:'нужны исправления',mahoraga_required:'передать Махораге',blocked_for_human:'ожидает решения человека',tests_failed:'независимые тесты не прошли',tests_passed:'независимые тесты пройдены',rebase_conflict:'нужно разрешить Git-конфликт',failed:'ошибка'})[status] || status || 'не запущена';
  const sessionStateLabel = status => ({accepted:'запрос принят',delivered:'сообщение доставлено',running:'выполняется',completed:'ответ завершён',failed:'ошибка',unconfirmed:'результат не подтверждён'})[status] || status;
  function tasksFromPlan(workflow) {
    return workflow.getTasks().map(task => ({id:task.id,title:task.title,goal:task.goal,acceptance:task.acceptance,dependsOn:task.dependsOn,contracts:task.contracts,mocks:task.mocks,builderPrompt:task.builderPrompt,testPrompt:task.testPrompt,reviewerPrompt:task.reviewerPrompt}));
  }
  async function getState(project) {
    const data = await api('/api/agents/state');
    const normalize=value=>String(value||'').replaceAll('\\','/').replace(/\/+$/,'').toLowerCase();
    const matches=root=>!project||normalize(root)===normalize(project.projectRoot);
    const runs = (data.runs || []).filter(run=>matches(run.projectRoot));
    if(selectedRun!=='__new__'&&!runs.some(run=>run.id===selectedRun))selectedRun='';
    if (!selectedRun && runs.length) selectedRun = runs[runs.length-1].id;
    const run = selectedRun==='__new__' ? null : (runs.find(item => item.id === selectedRun) || null);
    if (run && run.id !== selectedRun) selectedRun = run.id;
    return {run, sessions:(data.sessions || []).filter(session=>matches(session.projectRoot)||runs.some(run=>run.id===session.runId)), events:data.events || []};
  }
  const projectSessions=(ctx,run,state)=>state.sessions.filter(s=>run?s.runId===run.id:s.role==='mahoraga_planner');
  const latestPlanner=state=>state.sessions.filter(s=>s.role==='mahoraga_planner').at(-1);
  function displayedTasks(run,state){
    if(run)return run.tasks||[];
    const planner=latestPlanner(state);
    return planner?.status==='completed'&&!planner.approvedRunId&&Array.isArray(planner.proposal?.tasks)?planner.proposal.tasks.map(t=>({...t,status:'pending'})):[];
  }
  function preparationLayout(ctx,run,state){
    if(!ctx.project)return;
    window.makoraCodingAgents?.render(projectSessions(ctx,run,state),run);
    const host=ctx.content,view=host.querySelector('.real-agent-view');if(!view)return;
    view.dataset.activeAgents=String(projectSessions(ctx,run,state).filter(s=>['accepted','delivered','running'].includes(s.status)).length);
    view.dataset.agentSessions=JSON.stringify(projectSessions(ctx,run,state).map(s=>({id:s.id,role:s.role,task:s.taskId,status:s.status})));
    view.classList.add('rp-runtime');
    const completed=(run?.tasks||[]).filter(t=>t.status==='integrated').length,total=run?.tasks?.length||0,index=total&&completed===total?2:run?1:0;
    const header=document.createElement('header');header.className='rp-summary';header.innerHTML=`<div class="rp-eyebrow"><span>ШАГ ${ctx.project?.approvedRunId?'07 / 07':String(ctx.preparationStage+1).padStart(2,'0')+' / 08'}</span><span>${run?`${completed} из ${total} задач готово`:'Сначала согласуем план'}</span></div><p>${ctx.preparationStage===6?'Соберём рабочую версию на ваших мок-данных. Вы проверяете план и принимаете результат.':'Продолжим разработку утверждённого прототипа. Изменения проходят тесты и независимую проверку.'}</p><ol class="rp-lifecycle">${['Согласовать план','Работа агентов','Принять результат'].map((text,i)=>`<li class="${i===index?'is-current':i<index?'is-done':''}"><b>${i<index?'✓':i+1}</b><span>${text}</span></li>`).join('')}</ol>`;view.prepend(header);
    const fold=(nodes,title)=>{const items=nodes.filter(Boolean);if(!items.length)return;const details=document.createElement('details');details.className='rp-details';const summary=document.createElement('summary');summary.textContent=title;details.append(summary);const task=items[0].closest('.real-task')?.querySelector('header b')?.textContent||'';const key=ctx.project.projectRoot+'|'+ctx.preparationStage+'|'+title+'|'+task;details.dataset.panelKnown=preparationPanels.has(key)?'1':'0';details.open=preparationPanels.get(key)||false;details.addEventListener('toggle',()=>preparationPanels.set(key,details.open));items[0].before(details);items.forEach(el=>details.append(el));return details};
    const connection=view.querySelector('.real-status');if(connection){const connected=connection.classList.contains('online');const detail=fold([connection],connected?'Подключение к ИИ · есть связь':'Подключение к ИИ · нужна проверка');if(detail&&detail.dataset.panelKnown!=='1')detail.open=!connected}
    fold([...view.querySelectorAll(':scope > .real-caveat')],'Как Макора проверяет результат');
    const create=view.querySelector('.real-create-run');
    if(create){create.querySelector('h3').textContent='Начнём с плана';const explanation=create.querySelector('p');if(explanation)explanation.textContent='Макора разобьёт проект на задачи. Проверьте план перед запуском агентов.';
      const projectLabel=create.querySelector('[data-project-root]')?.closest('label'),contextLabel=create.querySelector('[data-mahoraga-context]')?.closest('label');const advanced=fold([projectLabel,...create.querySelectorAll(':scope > details'),contextLabel],'Папка проекта и переданный контекст');if(advanced)create.append(advanced);
      const brief=create.querySelector('[data-mahoraga-brief]');if(brief){brief.closest('label').firstChild.textContent='Что нужно получить';fold([brief.closest('label')],'Задание для этого шага')}
      const summary=create.querySelector('.real-plan-summary');if(summary)summary.innerHTML='<b>✓ Условие, документы и моки уже переданы</b>';
      const plan=create.querySelector('[data-mahoraga-plan]');if(plan){plan.textContent='Составить план →';plan.classList.add('rp-primary')}
      const manual=create.querySelector('[data-agent-create-run]');if(manual)manual.hidden=true;
    }
    view.querySelectorAll('[data-mahoraga-approve]').forEach(el=>el.classList.add('rp-primary'));
    view.querySelectorAll('.real-task').forEach(card=>{card.classList.add('rp-task-card');fold([...card.querySelectorAll(':scope > .real-session-line')],'Сессии агентов')});
    fold([view.querySelector('.real-agent-list')],'Все агенты и сведения о сессиях');
    const tools=host.querySelector('[data-preparation-tools]');if(tools){const approve=tools.querySelector('button');if(approve){approve.hidden=!(total&&completed===total);if(!approve.hidden){approve.classList.add('rp-primary');view.querySelector('.real-task-list')?.after(approve)}}const exported=fold([tools],'Экспорт для внешнего ИИ');if(exported)view.append(exported)}
  }
  function compactRuntime(ctx,run,state,approvals){
    if(!ctx.project)return;const view=ctx.content.querySelector('.real-agent-view');if(!view)return;
    const detail=document.createElement('div');detail.className='runtime-detail';while(view.firstChild)detail.append(view.firstChild);view.append(detail);
    const sessions=projectSessions(ctx,run,state),active=sessions.filter(s=>['accepted','delivered','running'].includes(s.status));
    window.makoraModelStatus?.agents(active);
    const completed=(run?.tasks||[]).filter(t=>t.status==='integrated').length,total=displayedTasks(run,state).length;
    const summary=document.createElement('section');summary.className='runtime-summary';
    summary.innerHTML=`<p class="analysis-purpose">${ctx.preparationStage===6?'Соберём рабочий прототип на ваших мок-данных.':'Развиваем прототип: агенты выполняют задачи, тестируют и проверяют изменения.'}</p><button class="analysis-file" data-runtime-open><span class="analysis-file-mark">${ctx.preparationStage===6?'07':'08'}</span><span><strong>${run?'Задачи и результаты':'План разработки'}</strong><small>${run?`${completed} / ${total} задач · ${active.length} агентов работают`:active.length?'Махорага составляет план…':total?`Новый план · ${total} задач · ожидает утверждения`:'Документы и моки уже переданы'}</small></span><span>↗</span></button>${active.length?`<div class="runtime-active" role="status">${active.slice(0,3).map(s=>`<span>${escapeHtml(s.role)} · ${escapeHtml(s.taskId||'план')} · ${escapeHtml(s.model||'модель не сообщена')}</span>`).join('')}${active.length>3?`<small>ещё ${active.length-3}</small>`:''}</div>`:''}${approvals.length?'<p class="runtime-attention">Ожидается разрешение действия Codex. Откройте управление и проверьте запрос.</p>':''}<div class="analysis-actions" data-runtime-controls></div>`;
    const motionKey=ctx.preparationStage+':'+(run?.id||'planner');
    if(active.length){
      if(!runtimeMotion.has(motionKey))runtimeMotion.set(motionKey,performance.now());
      const delay=-(performance.now()-runtimeMotion.get(motionKey))/1000;
      summary.querySelector('.analysis-purpose')?.remove();
      const waiting=document.createElement('section');waiting.className='analysis-thinking';waiting.setAttribute('role','status');waiting.innerHTML=`<img src="analysis-wheel.png" class="analysis-wheel" alt="" style="animation-delay:${delay}s;${approvals.length?'animation-play-state:paused':''}"><p>${approvals.length?'Ожидается ваше разрешение':run?'Агенты работают над проектом':'Махорага составляет план'}</p><button class="rp-text-button" data-runtime-open>${approvals.length?'Проверить запрос →':'Смотреть работу →'}</button>`;
      summary.querySelector('.analysis-file').replaceWith(waiting);summary.querySelector('[data-runtime-controls]').hidden=true;
    }else runtimeMotion.delete(motionKey);
    view.prepend(summary);
    const expand=()=>{ctx.board.dataset.runtimeView='detail';ctx.content.scrollTop=0};
    summary.querySelector('[data-runtime-open]').onclick=expand;
    const controls=summary.querySelector('[data-runtime-controls]');
    if(run?.mahoragaAutopilot?.lastError){const notice=document.createElement('p');notice.className='runtime-stopped';notice.setAttribute('role','status');notice.textContent='Работа остановлена: '+run.mahoragaAutopilot.lastError;summary.insertBefore(notice,controls)}
    const button=(label,primary,callback)=>{const el=document.createElement('button');el.type='button';el.className=primary?'rp-primary':'rp-secondary';el.textContent=label;el.onclick=callback;controls.append(el)};
    const plan=detail.querySelector('[data-mahoraga-plan]'),approval=detail.querySelector('[data-mahoraga-approve]:not(:disabled)'),autopilot=detail.querySelector('[data-agent-autopilot]');
    const accept=[...detail.querySelectorAll('button')].find(b=>b.textContent.includes('Утвердить работающий прототип')&&!b.hidden);
    if(run&&['failed','needs_human','limit_reached'].includes(run.mahoragaAutopilot?.status)){
      button('Новый запуск →',true,()=>detail.querySelector('[data-agent-new-run]')?.click());
      button('Подробнее об остановке',false,expand);
    }
    else if(approvals.length)button('Проверить запрос →',true,expand);
    else if(accept)button('Принять прототип →',true,()=>{expand();accept.scrollIntoView({block:'center'})});
    else if(approval)button('Проверить план →',true,()=>{expand();ctx.content.querySelector('.agent-board-nav button[data-page=overview]')?.click();ctx.content.querySelector('.execution-tree')?.scrollIntoView({block:'start'})});
    else if(!run&&plan&&!plan.disabled&&!active.length)button('Составить план →',true,()=>plan.click());
    else if(total&&completed===total)button('Открыть результат →',true,expand);
    else if(run&&autopilot)button(autopilot.textContent,true,()=>autopilot.click());
    if(!run&&!active.length&&plan&&!plan.disabled)button('Уточнить задание',false,()=>window.makoraPreparation.openRefinementChat({step:ctx.preparationStage,title:'Что учтём в плане?',description:'Допиши пожелания к реализации. Я передам их Махораге вместе с материалами проекта.',submit:'Составить план с уточнениями →',onSubmit:async feedback=>{const brief=detail.querySelector('[data-mahoraga-brief]');if(brief)brief.value+='\n\nУточнения пользователя:\n'+feedback;ctx.board.closest('#first-stage')?.querySelector('.analysis-chat')?.remove();plan.click()}}));
    if(!controls.children.length)button('Открыть управление →',false,expand);
    const back=document.createElement('button');back.className='rp-text-button runtime-back';back.textContent='← К краткому результату';back.onclick=()=>{delete ctx.board.dataset.runtimeView;ctx.content.scrollTop=0;summary.querySelector('[data-runtime-open]')?.focus()};detail.prepend(back);
  }
  let redrawBoardTree=()=>{};
  window.addEventListener('resize',()=>requestAnimationFrame(redrawBoardTree));
  const boardPortraits=new Map();
  const boardRoles={builder:'Разработчик',test_designer:'Автор тестов',reviewer:'Ревьюер',mahoraga_planner:'Махорага · планирование',mahoraga_orchestrator:'Махорага · координация',mahoraga:'Махорага · анализ'};
  const sessionActive=s=>['accepted','delivered','running'].includes(s?.status);
  function syncBoardPortrait(frame){
    if(frame.dataset.character==='mahoraga'){
      try{const wheel=frame.contentDocument?.querySelector('[data-action="wheel"]');if(wheel&&wheel.classList.contains('active')!==(frame.dataset.active==='true'))wheel.click()}catch{}
    }else frame.contentWindow?.postMessage({type:'makora:nox-state',mode:frame.dataset.mode},location.origin);
  }
  function agentRoster(page,sessions,tasks){
    const keep=new Set(sessions.map(s=>s.id));
    for(const [id,frame] of boardPortraits)if(!keep.has(id)){frame.remove();boardPortraits.delete(id)}
    const roster=document.createElement('div');roster.className='board-agent-roster';
    for(const session of sessions){
      const task=tasks.find(t=>t.id===session.taskId);
      const card=document.createElement('article');card.className='board-agent-card';card.dataset.status=session.status;
      card.innerHTML=`<div class="board-agent-portrait"></div><div class="board-agent-copy"><h3>${escapeHtml(boardRoles[session.role]||session.role)}</h3><span class="board-agent-status" data-status="${escapeHtml(session.status)}"><i aria-hidden="true"></i>${escapeHtml(sessionStateLabel(session.status))}</span><strong>${escapeHtml(task?task.id+' · '+task.title:session.taskId||'Проект')}</strong><p>${escapeHtml(session.error?.message||task?.goal||(session.role==='mahoraga_planner'?'Составляет план задач по материалам проекта.':session.role==='mahoraga_orchestrator'?'Координирует очередь задач и проверки.':'Цель сессии не указана.'))}</p><details><summary>Сведения о сессии</summary><dl><dt>Модель</dt><dd>${escapeHtml(session.model||'Не указана')}</dd><dt>Рассуждения</dt><dd>${escapeHtml(session.reasoningEffort||'По умолчанию модели')}</dd><dt>Рабочая папка</dt><dd>${escapeHtml(session.cwd||'Не указана')}</dd><dt>Сессия</dt><dd>${escapeHtml(session.threadId||session.id)}</dd></dl></details></div>`;
      const isMahoraga=['mahoraga','mahoraga_planner','mahoraga_orchestrator'].includes(session.role);
      let frame=boardPortraits.get(session.id);
      if(!frame){frame=document.createElement('iframe');frame.dataset.character=isMahoraga?'mahoraga':'nox';frame.src=isMahoraga?'mascot.html':'nox-agent.html?embed=1&v=walk-react-3';frame.tabIndex=-1;frame.setAttribute('aria-hidden','true');boardPortraits.set(session.id,frame);frame.onload=()=>syncBoardPortrait(frame)}
      frame.title=(isMahoraga?'Махорага':'NOX')+' · '+(boardRoles[session.role]||session.role);frame.dataset.active=String(sessionActive(session));
      frame.dataset.mode=sessionActive(session)?(session.role==='builder'?'code':session.role==='reviewer'?'debug':'think'):session.status==='failed'?'debug':'idle';
      card.querySelector('.board-agent-portrait').append(frame);syncBoardPortrait(frame);
      roster.append(card);
    }
    page.append(roster);
  }
  function executionTree(page,tasks,sessions,onSelect,initialSelection){
    const section=document.createElement('section');section.className='execution-tree';section.setAttribute('aria-label','Схема запуска агентов');
    section.innerHTML='<div class="execution-tree-heading"><h3>Как идёт работа</h3><p>Нажмите на пункт, чтобы увидеть его связи. Повторное нажатие снимает выделение.</p><div class="execution-legend"><span><i class="is-running"></i>В работе</span><span><i class="is-complete"></i>Готово</span><span><i></i>Ожидает</span></div></div><div class="execution-tree-scroll"><div class="execution-tree-canvas"><svg class="execution-tree-lines" aria-hidden="true"></svg><div class="execution-tree-levels"></div></div></div>';
    const reset=document.createElement('button');reset.type='button';reset.className='execution-reset';reset.textContent='Сбросить выделение';reset.hidden=true;section.querySelector('.execution-tree-heading').append(reset);
    const announcement=document.createElement('p');announcement.className='execution-selection-note';announcement.setAttribute('role','status');section.querySelector('.execution-tree-heading').append(announcement);
    let selected=initialSelection||null;
    const levels=section.querySelector('.execution-tree-levels'),nodes=new Map(),edges=[];
    const addLevel=()=>{const row=document.createElement('div');row.className='execution-tree-level';levels.append(row);return row};
    const root=document.createElement('button');root.type='button';root.className='execution-tree-root';root.innerHTML='<span class="execution-node-icon" aria-hidden="true">✳</span><span class="execution-node-eyebrow">Начало</span><strong>Махорага составляет план</strong><span>Распределяет задачи между агентами</span>';addLevel().append(root);nodes.set('__start',root);
    const pending=new Map(tasks.map(t=>[t.id,t])),depth=new Map();let level=0;
    while(pending.size){
      const ready=[...pending.values()].filter(t=>(t.dependsOn||[]).every(id=>depth.has(id)||!tasks.some(x=>x.id===id)));
      if(!ready.length){const note=document.createElement('p');note.textContent='Не удалось построить зависимости: проверьте план задач.';levels.append(note);break}
      const row=addLevel();row.setAttribute('aria-label','Уровень '+(++level));row.dataset.caption=ready.length>1?'Уровень '+level+' · параллельных веток: '+ready.length:'Уровень '+level+' · последовательно';
      for(const task of ready){
        pending.delete(task.id);depth.set(task.id,level);
        const node=document.createElement('button');node.type='button';node.className='execution-tree-task';node.dataset.status=task.status;
        const related=sessions.filter(s=>s.taskId===task.id);
        node.innerHTML=`<span class="execution-task-top"><span class="execution-tree-task-id">${escapeHtml(task.id)}</span><span class="execution-task-badge">${escapeHtml(taskStateLabel(task.status))}</span></span><strong>${escapeHtml(task.title)}</strong><span class="execution-task-deps">${task.dependsOn?.length?'После '+escapeHtml(task.dependsOn.join(', ')):'Можно запускать независимо'}</span><span class="execution-tree-pipeline">${[['test_designer','Тест-дизайн'],['builder','Код'],['reviewer','Ревью']].map(([role,label],index)=>{const last=related.filter(s=>s.role===role).at(-1);return `<span data-status="${escapeHtml(last?.status||'pending')}"><b aria-hidden="true">${index+1}</b><span>${label}</span><em>${escapeHtml(last?sessionStateLabel(last.status):'ожидает')}</em></span>`}).join('')}</span><span class="execution-task-open">Показать связи <span aria-hidden="true">⌁</span></span>`;
        row.append(node);nodes.set(task.id,node);
        for(const id of task.dependsOn?.length?task.dependsOn:['__start'])edges.push([id,task.id]);
      }
    }
    if(tasks.length&&!pending.size){
      const finish=document.createElement('button');finish.type='button';finish.className='execution-tree-finish';finish.dataset.status=tasks.every(t=>t.status==='integrated')?'completed':'pending';
      finish.innerHTML='<span class="execution-node-icon" aria-hidden="true">✓</span><strong>Готовый результат</strong><span>Все задачи интегрированы → можно принимать работу</span>';addLevel().append(finish);nodes.set('__finish',finish);
      for(const task of tasks)if(!tasks.some(t=>(t.dependsOn||[]).includes(task.id)))edges.push([task.id,'__finish']);
    }
    if(!tasks.length){const note=document.createElement('p');note.className='agent-board-empty';note.textContent='После утверждения плана здесь появятся ветки задач и агенты для каждой из них.';levels.append(note)}
    // Keep only the edges needed to express the same dependency order.
    const uniqueEdges=edges.filter(([from,to],index)=>nodes.has(from)&&nodes.has(to)&&edges.findIndex(([a,b])=>a===from&&b===to)===index);
    const outgoing=new Map();
    for(const [from,to] of uniqueEdges){if(!outgoing.has(from))outgoing.set(from,[]);outgoing.get(from).push(to)}
    const essential=uniqueEdges.filter(([from,to])=>{
      const queue=(outgoing.get(from)||[]).filter(id=>id!==to),visited=new Set();
      while(queue.length){const id=queue.pop();if(id===to)return false;if(visited.has(id))continue;visited.add(id);queue.push(...outgoing.get(id)||[])}
      return true;
    });
    edges.splice(0,edges.length,...essential);
    if(!nodes.has(selected))selected=null;
    function highlight(){
      const related=new Set(selected?[selected]:[]);
      for(const [from,to] of edges)if(from===selected||to===selected){related.add(from);related.add(to)}
      section.classList.toggle('has-selection',!!selected);reset.hidden=!selected;
      for(const [id,node] of nodes){node.classList.toggle('is-related',related.has(id));node.classList.toggle('is-selected',id===selected);node.setAttribute('aria-pressed',String(id===selected))}
      for(const path of section.querySelectorAll('.execution-tree-lines>path')){const connected=path.dataset.from===selected||path.dataset.to===selected;path.classList.toggle('is-related',connected);path.setAttribute('marker-end',selected&&connected?'url(#flow-arrow-selected)':'url(#flow-arrow)')}
      announcement.textContent=selected?'Показаны только связи выбранного пункта.':'';
    }
    function selectNode(id){selected=selected===id?null:id;onSelect(selected);highlight()}
    for(const [id,node] of nodes)node.onclick=()=>selectNode(id);
    reset.onclick=()=>{selected=null;onSelect(null);highlight()};
    section.addEventListener('keydown',event=>{if(event.key==='Escape'){selected=null;onSelect(null);highlight()}});
    const draw=()=>{
      if(section.hidden||!section.isConnected)return;
      const canvas=section.querySelector('.execution-tree-canvas'),svg=section.querySelector('svg'),rect=canvas.getBoundingClientRect();if(!rect.width)return;
      svg.setAttribute('viewBox',`0 0 ${rect.width} ${rect.height}`);svg.replaceChildren();
      const ns='http://www.w3.org/2000/svg',defs=document.createElementNS(ns,'defs');
      for(const [id,color] of [['flow-arrow','#888888'],['flow-arrow-selected','#ffffff']]){const marker=document.createElementNS(ns,'marker');marker.id=id;marker.setAttribute('viewBox','0 0 10 10');marker.setAttribute('refX','9');marker.setAttribute('refY','5');marker.setAttribute('markerWidth','7');marker.setAttribute('markerHeight','7');marker.setAttribute('orient','auto');const tip=document.createElementNS(ns,'polygon');tip.setAttribute('points','1,1 9,5 1,9');tip.setAttribute('fill',color);marker.append(tip);defs.append(marker)}svg.append(defs);
      for(const [from,to] of edges){const a=nodes.get(from)?.getBoundingClientRect(),b=nodes.get(to)?.getBoundingClientRect();if(!a||!b)continue;const x=a.x+a.width/2-rect.x,y=a.bottom-rect.y,tx=b.x+b.width/2-rect.x,ty=b.top-rect.y;const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',`M ${x} ${y+3} C ${x} ${(y+ty)/2}, ${tx} ${(y+ty)/2}, ${tx} ${ty-6}`);const done=tasks.find(t=>t.id===from)?.status==='integrated';path.dataset.complete=String(done);path.dataset.from=from;path.dataset.to=to;svg.append(path)}
      highlight();
    };
    page.append(section);highlight();return draw;
  }
  const boardNavigation=new Map();
  function organizeBoard(ctx,run,state,approvals){
    if(!ctx.project)return;
    const detail=ctx.content.querySelector('.runtime-detail');if(!detail)return;
    const key=ctx.project.projectRoot+'|'+ctx.preparationStage;
    const saved=boardNavigation.get(key)||{page:'overview',tasks:new Set(),approvals:0};if(approvals.length>saved.approvals)saved.page='overview';saved.approvals=approvals.length;boardNavigation.set(key,saved);
    const original=[...detail.children];
    const shell=document.createElement('div');shell.className='agent-board';
    const nav=document.createElement('nav');nav.className='agent-board-nav';nav.setAttribute('aria-label','Управление разработкой');
    const pages={};
    for(const [id,title] of [['overview','Обзор'],['tasks','Задачи'],['agents','Агенты'],['settings','Настройки']]){
      const button=document.createElement('button');button.type='button';button.textContent=title;button.dataset.page=id;
      const page=document.createElement('section');page.className='agent-board-page';page.setAttribute('aria-label',title);pages[id]=page;
      button.onclick=()=>select(id);nav.append(button);shell.append(page);
    }
    let drawTree=()=>{};
    function select(id){saved.page=id;requestAnimationFrame(drawTree);for(const [name,page] of Object.entries(pages))page.hidden=name!==id;for(const button of nav.children)button.setAttribute('aria-pressed',String(button.dataset.page===id))}
    const tasks=displayedTasks(run,state),done=tasks.filter(t=>t.status==='integrated').length;
    const planner=latestPlanner(state),preview=!run&&tasks.length>0,planning=!run&&sessionActive(planner);
    const sessions=projectSessions(ctx,run,state),working=sessions.filter(s=>['accepted','delivered','running'].includes(s.status)).length;
    const overview=document.createElement('header');overview.className='agent-board-overview';
    const stopped=run?.mahoragaAutopilot?.lastError;
    const title=approvals.length?'Нужно ваше разрешение':planning?'Махорага составляет новый план':preview?'План готов — проверьте схему':stopped?'Работа приостановлена':tasks.length&&done===tasks.length?'Задачи завершены':working?'Агенты выполняют работу':run?'План готов к работе':'Подготовим план разработки';
    overview.innerHTML=`<span class="agent-board-caption">Этап ${escapeHtml(ctx.preparationStage)} · Разработка</span><h2>${title}</h2><p>${approvals.length?'Проверьте запрос ниже, чтобы продолжить.':planning?'План ещё готовится. Схема появится здесь, когда Махорага завершит ответ.':preview?escapeHtml(planner.proposal.summary||'Проверьте задачи и зависимости перед утверждением.'):stopped?escapeHtml(stopped):working?'Можно следить за задачами и открыть сведения о каждом агенте.':run?'Запустите работу или откройте задачи, чтобы проверить результат.':'Составьте план по утверждённым материалам и проверьте его перед запуском.'}</p><div class="agent-board-counts"><span>${preview?`Предложено задач: <b>${tasks.length}</b>`:`<b>${done} / ${tasks.length}</b> задач готово`}</span><span><b>${working}</b> агентов работают</span></div><div class="agent-board-actions"></div>`;
    pages.overview.append(overview);
    const offline=detail.querySelector('.real-status.offline');if(offline){const warning=document.createElement('p');warning.className='runtime-stopped';warning.setAttribute('role','status');warning.textContent='Нет связи с Codex. Откройте настройки и проверьте подключение.';pages.overview.append(warning)}
    const actions=overview.querySelector('.agent-board-actions');
    const controls=ctx.content.querySelector('.runtime-summary [data-runtime-controls]');
    for(const source of controls?.children||[]){if(preview&&source.textContent.includes('Проверить план'))continue;const button=source.cloneNode(true);button.onclick=()=>{source.click();if(source.textContent.includes('план'))select('overview')};actions.append(button)}
    if(preview){const approve=detail.querySelector('[data-mahoraga-approve]:not(:disabled)');if(approve)actions.append(approve)}
    if(run&&!working){const source=detail.querySelector('[data-agent-autopilot]');if(source&&!actions.children.length){const button=source.cloneNode(true);button.textContent=source.dataset.enabled==='true'?'Приостановить работу':'Запустить агентов';button.onclick=()=>source.click();actions.append(button)}}
    const go=document.createElement('button');go.type='button';go.className='rp-text-button';go.textContent='Посмотреть задачи →';go.onclick=()=>select('tasks');if(run&&tasks.length)actions.append(go);
    drawTree=executionTree(pages.overview,tasks,sessions,id=>{saved.treeSelection=id},saved.treeSelection);
    if(preview){
      const caption=document.createElement('p');caption.className='plan-preview-caption';caption.textContent='Предпросмотр плана · '+tasks.length+' задач. Утверждение создаст запуск именно с этими задачами.';pages.overview.querySelector('.execution-tree-heading').append(caption);
    }
    if(planning)pages.overview.querySelector('.execution-tree .agent-board-empty').textContent='Ждём новый план от Махораги…';
    const rootTitle=pages.overview.querySelector('.execution-tree-root strong');if(rootTitle)rootTitle.textContent=planning?'Махорага составляет план':preview?'Махорага подготовила план':run?'Утверждённый план':'Махорага составляет план';
    for(const node of original){
      if(node.matches('.runtime-back'))continue;
      if(node.matches('.rp-summary')){node.remove();continue}
      if(node.matches('.real-task-list')){
        pages.tasks.append(node);
        for(const card of node.querySelectorAll('.real-task')){
          const id=card.querySelector('header b')?.textContent||'';
          const fold=document.createElement('details');fold.className='agent-task';fold.open=saved.tasks.has(id);
          const summary=document.createElement('summary');const task=tasks.find(t=>t.id===id);
          summary.innerHTML=`<span>${escapeHtml(id)}</span><strong>${escapeHtml(task?.title||'Задача')}</strong><small>${escapeHtml(taskStateLabel(task?.status))}</small>`;
          fold.append(summary);card.before(fold);fold.append(card);fold.addEventListener('toggle',()=>{if(fold.open)saved.tasks.add(id);else saved.tasks.delete(id)});
        }
      }else if(node.matches('.real-create-run,.real-approvals,.real-mahoraga-plan,.real-mahoraga-director')||node.querySelector('[data-mahoraga-approve],[data-mahoraga-apply]')||node.matches('button.rp-primary'))pages.overview.append(node);
      else if(node.matches('.rp-details')&&node.querySelector('.real-agent-list')){pages.settings.append(node)}
      else pages.settings.append(node);
    }
    if(preview&&!pages.tasks.children.length){
      for(const task of tasks){const card=document.createElement('details');card.className='agent-task';
        card.innerHTML=`<summary><span>${escapeHtml(task.id)}</span><strong>${escapeHtml(task.title)}</strong><small>Предложено · до утверждения</small></summary><article class="real-task"><p>${escapeHtml(task.goal)}</p><p>Зависимости: ${escapeHtml((task.dependsOn||[]).join(', ')||'нет')}</p><strong>Критерии готовности</strong><pre>${escapeHtml(Array.isArray(task.acceptance)?task.acceptance.join('\n'):task.acceptance||'Не указаны')}</pre></article>`;pages.tasks.append(card)}
    }
    if(!pages.tasks.children.length)pages.tasks.innerHTML='<p class="agent-board-empty">Задачи появятся после утверждения плана. Начните с обзора.</p>';
    agentRoster(pages.agents,sessions,tasks);
    if(!sessions.length)pages.agents.innerHTML='<p class="agent-board-empty">Агенты ещё не запущены. Сначала составьте и утвердите план.</p>';
    const configure=document.createElement('button');configure.type='button';configure.className='rp-secondary';configure.textContent='Модели и рассуждения агентов';configure.onclick=()=>window.makoraAgentSettings?.open();pages.settings.prepend(configure);
    shell.prepend(nav);detail.append(shell);redrawBoardTree=drawTree;select(saved.page);
  }
  function showRuntimeWaiting(ctx,text){
    const overview=ctx.content.querySelector('.agent-board-overview');if(overview){overview.querySelector('h2').textContent=text;overview.setAttribute('aria-busy','true');overview.querySelectorAll('button').forEach(button=>button.disabled=true)}
    const summary=ctx.content.querySelector('.runtime-summary');if(!summary)return;
    summary.innerHTML=`<div class="analysis-thinking" role="status"><img src="analysis-wheel.png" class="analysis-wheel" alt=""><p>${escapeHtml(text)}</p></div>`;
  }
  async function render(ctx) {
    const generation=++renderGeneration;
    const isCurrent=()=>generation===renderGeneration&&ctx.board?.classList.contains('agent-real-mode');
    lastContext = ctx;
    const {content,status,primary,workflow,announce}=ctx;
    const savedScroll=content.scrollTop;
    if (primary) primary.hidden = true;
    clearTimeout(refreshTimer);
    let connection;
    try { connection = await api('/api/agents/status'); }
    catch(error) { connection = {connected:false,modelAvailable:false,error:{message:error.message},allowedRoots:[]}; }
    let state={run:null,sessions:[],events:[]};
    try {
      state = await getState(ctx.project);
      const active=state.sessions.filter(session=>(session.runId===state.run?.id||(!state.run&&session.role==='mahoraga_planner'))&&['accepted','delivered','running'].includes(session.status));
      if(active.length){await Promise.allSettled(active.map(session=>api(`/api/agents/sessions/${session.id}`)));state=await getState(ctx.project);}
    } catch {}
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
      if (task.status==='pending' && task.testDesignStatus==='completed') controls.push(`<button type="button" data-agent-action="worktree" data-task="${escapeHtml(task.id)}">Создать worktree</button>`);
      if (task.status==='ready') controls.push(`<button type="button" data-agent-action="builder" data-task="${escapeHtml(task.id)}" ${(!isConnected||designer?.status!=='completed')?'disabled':''}>Запустить Builder</button>${designer?.status!=='completed'?'<small class="real-gate-note">Builder откроется после завершения независимого Test Designer.</small>':''}`);
      if (['review_pending','review_completed','tests_failed','changes_requested','review_unconfirmed','tests_passed'].includes(task.status)) controls.push(`<button type="button" data-agent-action="tests" data-task="${escapeHtml(task.id)}">Запустить независимые тесты</button>`);
      if (task.status==='tests_passed') controls.push(`<button type="button" data-agent-action="reviewer" data-task="${escapeHtml(task.id)}" ${!isConnected?'disabled':''}>Запустить Reviewer</button>`);
      if (task.status==='changes_requested') controls.push(`<button type="button" data-agent-fixes="${escapeHtml(task.id)}">Передать замечания Builder · ${Number(task.repairAttempts||0)}/3</button>`);
      if (task.status==='mahoraga_required') controls.push(`<button type="button" data-agent-action="mahoraga" data-task="${escapeHtml(task.id)}" ${!isConnected?'disabled':''}>Передать Махораге</button>`);
      if (task.status==='rebase_conflict') controls.push(`<button type="button" data-agent-resolve-conflicts="${escapeHtml(task.id)}">Проверить разрешение Git-конфликтов</button>`);
      if (task.worktree && task.worktreeBase && task.worktreeBase!==run.baseCommit && !['integrated','implementing','reviewing','unconfirmed'].includes(task.status)) controls.push(`<button type="button" data-agent-rebase="${escapeHtml(task.id)}">Обновить базу и перепроверить</button>`);
      if (task.review?.verdict==='pass') controls.push(`<button type="button" data-agent-action="integrate" data-task="${escapeHtml(task.id)}">Подтвердить интеграцию</button>`);
      return `<article class="real-task"><header><b>${escapeHtml(task.id)}</b><span>${escapeHtml(taskStateLabel(task.status))}</span></header><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.goal)}</p><small>Зависимости: ${escapeHtml(deps)} · ветка: <code>${escapeHtml(task.branch||'ещё не создана')}</code> · база: <code>${escapeHtml((task.worktreeBase||run.baseCommit).slice(0,12))}</code></small>${task.status==='rebase_conflict'?`<p class="real-gate-note">Конфликтующие файлы: ${escapeHtml((task.conflictPaths||[]).join(', '))}. Открой новый worktree и разреши конфликт с сохранением нужных изменений обеих сторон. Интегрированная версия не перезаписывается.</p>`:''}<div class="real-actions">${controls.join('')}</div>${task.testDesignError?`<p class="real-gate-note">Test Designer: ${escapeHtml(task.testDesignError)}</p>`:''}${task.tests?`<details><summary>Независимые тесты · ${escapeHtml(task.tests.status)} · suite ${escapeHtml((task.tests.suiteDigest||'').slice(0,12))}</summary><pre>${escapeHtml(JSON.stringify(task.tests,null,2))}</pre></details>`:''}${task.mahoragaResult?`<details open><summary>Анализ Махораги</summary><pre>${escapeHtml(task.mahoragaResult)}</pre></details>`:''}${task.worktree?`<details><summary>Рабочая директория и diff</summary><code>${escapeHtml(task.worktree)}</code><button type="button" data-agent-diff="${escapeHtml(task.id)}">Обновить diff</button><pre data-diff="${escapeHtml(task.id)}"></pre></details>`:''}${designer?`<p class="real-session-line">Test Designer · ${escapeHtml(designer.threadId)} · ${escapeHtml(sessionStateLabel(designer.status))}</p>`:''}${builder?`<p class="real-session-line">Builder · ${escapeHtml(builder.threadId)} · ${escapeHtml(sessionStateLabel(builder.status))}</p>${builder.result?`<details><summary>Ответ Builder</summary><pre>${escapeHtml(JSON.stringify(builder.result,null,2))}</pre></details>`:''}`:''}${reviewer?`<p class="real-session-line">Reviewer · ${escapeHtml(reviewer.threadId)} · ${escapeHtml(sessionStateLabel(reviewer.status))}</p>${reviewer.result?`<details><summary>Результат Reviewer</summary><pre>${escapeHtml(JSON.stringify(reviewer.result,null,2))}</pre></details>`:''}`:''}</article>`;
    }).join('');
    if(!isCurrent())return;
    content.innerHTML=`<section class="real-agent-view"><div class="real-status ${connection.connected?'online':'offline'}"><div><span class="real-kicker">CODEX APP SERVER</span><strong>${connection.warming?'Подключаем локальный App Server…':connection.connected?'Локальный App Server подключён':'Нет подключения к локальному App Server'}</strong><small>${escapeHtml(connection.warming?'Ожидание запуска локального моста…':connection.appServerVersion||connection.error?.message||'Проверь запуск Codex Desktop и App Server.')}${connection.modelAvailable?' · Модели и рассуждения выбираются в настройках проекта.':''}</small></div><button type="button" data-agent-refresh>Проверить</button></div><p class="real-caveat">Тесты готовит отдельный Test Designer. Макора запускает их в sandbox-копии проекта и привязывает ревью к хешам кода и тестов. Параллельная ветка после интеграции другой задачи переносится на новую базу и проверяется повторно; конфликтующие файлы нужно разрешить вручную. До трёх циклов исправлений, затем — Махорага.</p><p class="real-caveat real-visibility">Потоки App Server сохраняются, но их отображение в Codex Desktop не гарантируется.</p>${!run?`<section class="real-create-run"><h3>Подготовить настоящий запуск</h3><p>Укажи разрешённую Git-папку проекта. Макора проверит чистоту основной ветки и создаст отдельный worktree для каждой задачи.</p><label>Путь к Git-проекту<input data-project-root autocomplete="off" placeholder="C:\\Projects\\my-app"></label><details><summary>Разрешённые корни</summary><p>${allowed}</p><small>Чтобы добавить другие папки, передай серверу параметр <code>--agent-root</code>.</small></details><div class="real-plan-summary"><b>${workflow.getTasks().length} задач из утверждённой карты</b><span>Ручной запуск сохраняется как резервный вариант. Махорага может подготовить собственную декомпозицию.</span></div><label>Условие / цель для Махораги<textarea data-mahoraga-brief rows="5" placeholder="Опиши кейс, ожидаемый результат и ограничения"></textarea></label><label>Контекст этапов 1–4<textarea data-mahoraga-context rows="5">${escapeHtml(JSON.stringify(tasksFromPlan(workflow),null,2))}</textarea></label><button type="button" data-mahoraga-plan ${!isConnected?'disabled':''}>Попросить Махорагу декомпозировать проект</button><button type="button" data-agent-create-run ${!isConnected?'disabled':''}>Создать план запуска</button></section>`:`<header class="real-run-header"><div><span class="real-kicker">${escapeHtml(run.id)} · ${escapeHtml(run.baseCommit.slice(0,12))}</span><h3>${escapeHtml(run.projectRoot)}</h3></div><button type="button" data-agent-new-run>Новый запуск</button>${run.plannerSessionId?`<button type="button" data-agent-autopilot data-enabled="${run.mahoragaAutopilot?.enabled?'true':'false'}">${run.mahoragaAutopilot?.enabled?'Приостановить автокоординацию':'Запустить автономную работу'}</button><small>Махорага: ${escapeHtml(run.mahoragaAutopilot?.status||'manual')} · ${Number(run.mahoragaAutopilot?.actions||0)}/80 действий · ${Number(run.mahoragaAutopilot?.decisions||0)}/40 решений</small><small>Одноразовые запросы Codex автоматически подтверждаются только для активного агента в его точном worktree; неизвестные действия останавливают запуск.</small>`:''}</header><div class="real-task-list">${taskCards}</div><section class="real-report"><h3>Решение об интеграции</h3><p>Для интеграции выбери разрешённые файлы задачи, выполни независимый sandbox-набор и Reviewer, затем подтверди интеграцию. Сервер повторно сверит файлы и хеши.</p></section>`}<section class="real-agent-list"><h3>Агенты и события</h3>${projectSessions(ctx,run,state).map(s=>`<article><div><b>${escapeHtml(s.role)} · ${escapeHtml(s.taskId)}</b><span>${escapeHtml(sessionStateLabel(s.status))}</span></div><code>thread ${escapeHtml(s.threadId)}</code><small>${escapeHtml(s.model)} · ${escapeHtml(s.cwd)}</small><button type="button" data-agent-poll="${escapeHtml(s.id)}">Обновить состояние</button></article>`).join('')||'<p>Настоящие Codex-сессии ещё не создавались.</p>'}</section><details class="real-history"><summary>Журнал контроллера</summary><ol>${state.events.map(event=>`<li><time>${escapeHtml(new Date(event.at).toLocaleTimeString('ru-RU'))}</time> ${escapeHtml(event.type)} · ${escapeHtml(event.detail)}</li>`).join('')||'<li>Событий пока нет.</li>'}</ol></details></section>`;
    if(ctx.project){const tools=document.createElement('section');tools.className='real-report';tools.dataset.preparationTools='';const download=document.createElement('a');download.href='/api/preparation/archive';download.textContent='Скачать утверждённые файлы и промпт для внешнего ИИ ↓';tools.append(download);if(ctx.preparationStage===6){const approve=document.createElement('button');approve.type='button';approve.textContent='Утвердить работающий прототип →';approve.addEventListener('click',ctx.approvePrototype);tools.append(approve)}content.prepend(tools)}
    if(!run&&ctx.project){for(const [selector,value] of [['[data-project-root]',ctx.project.projectRoot],['[data-mahoraga-brief]',ctx.project.brief],['[data-mahoraga-context]',ctx.project.context]]){const input=content.querySelector(selector);if(input)input.value=value}}
    if(!run){
      const planner=latestPlanner(state);
      if(planner){
        const box=document.createElement('section');box.className='real-report';
        box.innerHTML=`<h3>План Махораги · ${escapeHtml(sessionStateLabel(planner.status))}</h3>${planner.error?.message?`<p class="real-gate-note">${escapeHtml(planner.error.message)}</p>`:''}${planner.planError?`<p class="real-gate-note">${escapeHtml(planner.planError.message)}</p>`:''}${planner.proposal?`<p>${escapeHtml(planner.proposal.summary||'')}</p><p>${planner.proposal.tasks?.length||0} задач · ${escapeHtml(planner.planValidation?.dag||'DAG не подтверждён')}</p><details><summary>Проверить декомпозицию и рекомендации</summary><pre>${escapeHtml(JSON.stringify(planner.proposal,null,2))}</pre></details><button type="button" data-mahoraga-approve="${escapeHtml(planner.id)}" ${planner.approvedRunId?'disabled':''}>${planner.approvedRunId?'План уже утверждён':`Утвердить план · ${planner.proposal.tasks?.length||0} задач`}</button>`:''}<small>thread ${escapeHtml(planner.threadId)} · ${escapeHtml(planner.model)}</small>`;
        content.querySelector('.real-create-run')?.append(box);
      }
    }else{
      const directors=state.sessions.filter(session=>session.runId===run.id&&session.role==='mahoraga_orchestrator');
      const director=directors.at(-1);
      const box=document.createElement('section');box.className='real-report real-mahoraga';
      let directorMarkup=`<h3>Махорага · управление очередью</h3><p>Главный агент анализирует зависимости и предлагает следующий набор действий. Контроллер проверяет каждое предложение; интеграция всегда требует подтверждения человека.</p><button type="button" data-mahoraga-orchestrate ${!isConnected?'disabled':''}>${director&&['accepted','delivered','running'].includes(director.status)?'Махорага анализирует очередь…':'Запросить план очереди'}</button>`;
      if(director){
        directorMarkup+=`<small>Состояние: ${escapeHtml(sessionStateLabel(director.status))} · thread ${escapeHtml(director.threadId)}</small>`;
        if(director.planError)directorMarkup+=`<p class="real-gate-note">${escapeHtml(director.planError.message)}</p>`;
        if(director.proposal){directorMarkup+=`<p>${escapeHtml(director.proposal.summary||'')}</p><details><summary>Предложенные действия · ${director.proposal.actions?.length||0}</summary><pre>${escapeHtml(JSON.stringify(director.proposal,null,2))}</pre></details><button type="button" data-mahoraga-apply="${escapeHtml(director.id)}" ${director.actionResults?'disabled':''}>Проверить и выполнить допустимые действия</button>`;if(director.actionResults)directorMarkup+=`<pre>${escapeHtml(JSON.stringify(director.actionResults,null,2))}</pre>`}
      }
      box.innerHTML=directorMarkup;
      content.querySelector('.real-task-list')?.before(box);
    }
    if(run?.execution?.laboratories?.length){
      const section=document.createElement('section');section.className='runtime-laboratories';
      section.innerHTML='<h3>Лаборатории</h3><p>Основная ветка использует моки, пока функция не принята и не подключена. Мини-интерфейсы не попадают в финальную ветку.</p>'+run.execution.laboratories.map(lab=>{
        const connected=run.tasks.find(t=>t.id===lab.integrationTaskId)?.status==='integrated';
        return `<article class="laboratory-card"><h4>${escapeHtml(lab.title)}</h4><p>${connected?'Функция подключена':'В основном приложении: моки'}</p><p>Задачи: ${escapeHtml(lab.taskIds.join(', '))}</p><div class="analysis-actions"><button type="button" data-lab-preview="${escapeHtml(lab.id)}">Запустить тестовый интерфейс</button><button type="button" data-lab-accept="${escapeHtml(lab.id)}">Принять проверенные задачи</button></div><p data-lab-result="${escapeHtml(lab.id)}" role="status"></p></article>`;
      }).join('');
      content.querySelector('.real-task-list')?.before(section);
      section.querySelectorAll('[data-lab-preview],[data-lab-accept]').forEach(button=>button.onclick=async()=>{
        button.disabled=true;
        const id=button.dataset.labPreview||button.dataset.labAccept,action=button.dataset.labPreview?'preview':'accept';
        try{
          const result=await api(`/api/agents/runs/${run.id}/laboratories/${id}/${action}`,{method:'POST',body:'{}'});
          if(result.url){const link=document.createElement('a');link.href=result.url;link.target='_blank';link.rel='noopener';link.textContent='Открыть тестовый интерфейс ↗';section.querySelector(`[data-lab-result="${id}"]`).replaceChildren(link)}
          else {announce('Проверенные задачи приняты. Подключение функции выполняется отдельной задачей.');await render(ctx)}
        }catch(error){announce(error.message)}finally{button.disabled=false}
      });
    }
    content.querySelector('[data-mahoraga-plan]')?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;showRuntimeWaiting(ctx,'Отправляем задание Махораге…');try{await api('/api/agents/plans',{method:'POST',body:JSON.stringify({projectRoot:content.querySelector('[data-project-root]').value.trim(),brief:content.querySelector('[data-mahoraga-brief]').value,context:content.querySelector('[data-mahoraga-context]').value,artifactPaths:ctx.project?.artifactPaths||[],includeSource:!!ctx.project})});announce('Махорага готовит декомпозицию.');await render(ctx)}catch(error){await render(ctx);announce(error.message);button.disabled=false}});
    content.querySelectorAll('[data-mahoraga-approve]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const created=await api(`/api/agents/plans/${button.dataset.mahoragaApprove}/approve`,{method:'POST',body:'{}'});selectedRun=created.id;localStorage.setItem('makora.agent-real-run',selectedRun);if(ctx.project)boardNavigation.delete(ctx.project.projectRoot+'|'+ctx.preparationStage);announce('План проверен контроллером и утверждён.');await render(ctx)}catch(error){announce(error.message);await render(ctx)}}));
    content.querySelector('[data-mahoraga-orchestrate]')?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;try{await api(`/api/agents/runs/${run.id}/mahoraga`,{method:'POST',body:'{}'});announce('Махорага анализирует текущую очередь.');await render(ctx)}catch(error){announce(error.message);button.disabled=false}});
    content.querySelectorAll('[data-mahoraga-apply]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const result=await api(`/api/agents/sessions/${button.dataset.mahoragaApply}/apply-actions`,{method:'POST',body:'{}'});announce(`Контроллер проверил рекомендации: принято ${result.results.filter(x=>x.status==='accepted').length}, отклонено ${result.results.filter(x=>x.status==='rejected').length}.`);await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    if(approvals.length){const section=document.createElement('section');section.className='real-approvals';section.innerHTML=`<h3>Подтверждение действий Codex</h3>${approvals.map(item=>`<article><div><b>${escapeHtml(item.method||'Запрос действия')}</b><pre>${escapeHtml(JSON.stringify(item.params||{},null,2))}</pre></div><button type="button" data-approval="${escapeHtml(item.requestId)}" data-decision="accept">Разрешить</button><button type="button" data-approval="${escapeHtml(item.requestId)}" data-decision="decline">Отклонить</button></article>`).join('')}`;content.querySelector('.real-status').after(section);section.querySelectorAll('[data-approval]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/api/agents/approvals/${button.dataset.approval}`,{method:'POST',body:JSON.stringify({decision:button.dataset.decision})});await render(ctx)}catch(error){announce(error.message);button.disabled=false}}))}
    status.textContent=connection.warming?'ПОДКЛЮЧЕНИЕ К APP SERVER…':connection.connected?(connection.modelAvailable?'APP SERVER ПОДКЛЮЧЁН · КАТАЛОГ МОДЕЛЕЙ ДОСТУПЕН':'APP SERVER ПОДКЛЮЧЁН · МОДЕЛИ НЕДОСТУПНЫ'):'НЕТ ПОДКЛЮЧЕНИЯ К APP SERVER';
    content.querySelector('[data-agent-refresh]')?.addEventListener('click',()=>render(ctx));
    content.querySelector('[data-agent-new-run]')?.addEventListener('click',()=>{selectedRun='__new__';localStorage.setItem('makora.agent-real-run',selectedRun);render(ctx)});
    content.querySelector('[data-agent-autopilot]')?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;try{const enabled=button.dataset.enabled!=='true';const result=await api(`/api/agents/runs/${run.id}/autopilot`,{method:'POST',body:JSON.stringify({enabled})});announce(enabled?`Автокоординация включена · лимит ${result.decisions}/40 решений.`:'Автокоординация приостановлена.');await render(ctx)}catch(error){announce(error.message);button.disabled=false}});
    content.querySelector('[data-agent-create-run]')?.addEventListener('click',async()=>{const button=content.querySelector('[data-agent-create-run]');button.disabled=true;try{const created=await api('/api/agents/runs',{method:'POST',body:JSON.stringify({projectRoot:content.querySelector('[data-project-root]').value.trim(),tasks:tasksFromPlan(workflow)})});selectedRun=created.id;localStorage.setItem('makora.agent-real-run',selectedRun);await render(ctx)}catch(error){announce(error.message);button.disabled=false}});
    content.querySelectorAll('[data-agent-action]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;const task=button.dataset.task,action=button.dataset.agentAction;try{if(action==='tests'){const paths=prompt('Разрешённые файлы задачи через запятую');if(!paths){button.disabled=false;return}await api(`/api/agents/runs/${run.id}/tasks/${task}/tests`,{method:'POST',body:JSON.stringify({allowedPaths:paths.split(',').map(x=>x.trim()).filter(Boolean)})})}else if(action==='integrate'){if(!confirm('Интегрировать проверенные изменения в исходную ветку?')){button.disabled=false;return}await api(`/api/agents/runs/${run.id}/tasks/${task}/integrate`,{method:'POST',body:JSON.stringify({confirmed:true})})}else if(action==='worktree')await api(`/api/agents/runs/${run.id}/tasks/${task}/worktree`,{method:'POST',body:'{}'});else await api(`/api/agents/runs/${run.id}/tasks/${task}/agents/${action}`,{method:'POST',body:'{}'});await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-poll]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/api/agents/sessions/${button.dataset.agentPoll}`);await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-fixes]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const result=await api(`/api/agents/runs/${run.id}/tasks/${button.dataset.agentFixes}/request-fixes`,{method:'POST',body:'{}'});announce(`Цикл исправлений ${result.attempt}/3 передан Builder.`);await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-rebase]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;const task=run.tasks.find(item=>item.id===button.dataset.agentRebase);let paths=task.allowedPaths;if(!paths?.length){const entered=prompt(`Перечисли только файлы этой задачи, которые разрешено переносить из worktree:\n${task.worktree}`);if(!entered){button.disabled=false;return}paths=entered.split(',').map(x=>x.trim()).filter(Boolean)}try{const result=await api(`/api/agents/runs/${run.id}/tasks/${task.id}/rebase`,{method:'POST',body:JSON.stringify({allowedPaths:paths})});announce(result.status==='conflict_resolution_required'?`Git создал новую ветку с конфликтами: ${result.conflicts.join(', ')}. Интегрированный код сохранён в базе. Разреши конфликты в указанном worktree, затем подтверди проверку.`:'Изменения перенесены трёхсторонним Git merge. Тесты и Reviewer сброшены; запусти их снова.');await render(ctx)}catch(error){announce(error.message);button.disabled=false;await render(ctx)}}));
    content.querySelectorAll('[data-agent-resolve-conflicts]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const result=await api(`/api/agents/runs/${run.id}/tasks/${button.dataset.agentResolveConflicts}/resolve-conflicts`,{method:'POST',body:'{}'});announce(`Конфликт разрешён. Повторно запусти независимые тесты${result.requiresReview?' и Reviewer':''}.`);await render(ctx)}catch(error){announce(error.message);button.disabled=false}}));
    content.querySelectorAll('[data-agent-diff]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{const diff=await api(`/api/agents/runs/${run.id}/tasks/${button.dataset.agentDiff}/diff`);const pre=content.querySelector(`[data-diff="${button.dataset.agentDiff}"]`);pre.textContent=`${diff.status||'(чисто)'}\n\n${diff.diff||'(diff пока пуст)'}\n\nФайлы: ${(diff.changedFiles||[]).join(', ')||'нет'}`}catch(error){announce(error.message)}finally{button.disabled=false}}));
    preparationLayout(ctx,run,state);
    compactRuntime(ctx,run,state,approvals);
    organizeBoard(ctx,run,state,approvals);
    content.scrollTop=savedScroll;
    if(connection.warming||run?.mahoragaAutopilot?.enabled||state.sessions.some(s=>(run?s.runId===run.id:s.role==='mahoraga_planner')&&['accepted','delivered','running'].includes(s.status))) refreshTimer=setTimeout(()=>{if(isCurrent())render(ctx)},3000);
  }
  function cancel(){renderGeneration++;clearTimeout(refreshTimer);refreshTimer=0}
  window.makoraRealAgents={render,cancel,selectRun(id){selectedRun=id;localStorage.setItem('makora.agent-real-run',id)}};
})();

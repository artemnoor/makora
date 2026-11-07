/* Real artifact pipeline. No example documents are used by this controller. */
(() => {
  let state={brief:'',stages:{}}, stage=1, file=null, timer=0, busy=false, generation=0, feedbacks={}, feedbackProject=null;
  let analysisMotion={key:null,started:0};
  const names=['Анализ задания','Анализ конкурентов','Разработка идеи','Планирование','Мок-данные','Пакет для агента','Разработка агентами'];
  const purposes=['Разберём условие: что сделать, какие есть ограничения и как будут оценивать.','Найдём конкурентов и альтернативы, сравним их с вашим продуктом и выберем полезные подходы.','Исследуем проблему и выберем идею, которая отвечает требованиям задания.','Определим устройство продукта, контракты, проверки и задачи для разработки.','Подготовим данные для разработки и проверим их по схемам и сценариям.','Соберём работающий прототип из согласованных материалов и моков.','Разовьём утверждённый прототип с помощью агентов и проверяемых задач.'];
  const fileNames={'02_competitors.md':'Сравнение конкурентов','02_competitors.json':'Конкуренты и источники','01_case_analysis.md':'Разбор задания','02_research.md':'Исследование проблемы','02_solution_concept.md':'Концепция решения','02_user_flow.mmd':'Путь пользователя','02_task_flow.mmd':'Сценарий действий','03_architecture.md':'Архитектура продукта','03_test_plan.md':'План тестирования','03_tasks.json':'Задачи для агентов','04_validation_report.md':'Отчёт о готовности данных'};
  const fileTitle=path=>fileNames[path]||(/openapi/i.test(path)?'Контракты API':path.split('/').pop());
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path,body){
    const foreground=body!==undefined&&!path.endsWith('/refresh')&&!path.includes('/folder/');
    if(foreground)window.dispatchEvent(new CustomEvent('makora:activity',{detail:{active:true,text:path.endsWith('/approve')?'Сохраняем утверждение…':path.endsWith('/development')?'Подготавливаем рабочий проект…':'Отправляем задание Макоре…'}}));
    try{
    const options={credentials:'same-origin',cache:'no-store'};
    if(body!==undefined){const token=await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'},credentials:'same-origin'});const auth=await token.json();if(!token.ok)throw Error(auth.error?.message||'Нет доступа к локальному API');options.method='POST';options.headers={'Content-Type':'application/json','X-Makora-Token':auth.result.token};options.body=JSON.stringify(body)}
    const response=await fetch(path,options), data=await response.json();if(!response.ok)throw Error(data.error?.message||'Ошибка API');return data.result;
    }finally{if(foreground)window.dispatchEvent(new CustomEvent('makora:activity',{detail:{active:false}}))}
  }
  function markdown(text){let html='',end=0;for(const match of text.matchAll(/```([^\n]*)\n([\s\S]*?)```/g)){html+=render(text.slice(end,match.index));html+=match[1].trim()==='mermaid'?'<pre data-real-mermaid>'+esc(match[2])+'</pre>':'<pre class="case-source"><code>'+esc(match[2])+'</code></pre>';end=match.index+match[0].length}return html+render(text.slice(end))}
  async function diagrams(host){
    const elements=[...host.querySelectorAll('[data-real-mermaid]')];if(!elements.length)return;
    const mermaid=window.mermaid;
    if(mermaid)mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'strict',flowchart:{htmlLabels:false}});
    for(const el of elements){
      const source=el.textContent;
      try{if(!mermaid)throw Error('Библиотека Mermaid недоступна');const result=await mermaid.render('real-'+crypto.randomUUID(),source);if(el.isConnected){const figure=document.createElement('figure');figure.className='real-diagram';figure.innerHTML=result.svg;figure.setAttribute('aria-label','Диаграмма Mermaid');el.replaceWith(figure)}}
      catch(error){if(!el.isConnected)continue;const message=document.createElement('p');message.className='real-diagram-error';message.setAttribute('role','alert');message.textContent='Не удалось построить схему. Ниже показан её исходный текст.';el.before(message);el.classList.add('case-source');el.removeAttribute('data-real-mermaid')}
    }
  }

  async function extract(file,attachment=false){const token=await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json();const response=await fetch('/api/preparation/'+(attachment&&state.storageRoot?'attachment':'extract')+'?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Makora-Token':token.result.token},body:file});const result=await response.json();if(!response.ok)throw Error(result.error?.message||'Не удалось прочитать файл');return result.result.text}
  const root=()=>document.querySelector('#first-stage');
  function error(message){const host=root()?.querySelector('.board-content');if(host){let el=host.querySelector('[data-real-error]');if(!el){el=document.createElement('p');el.dataset.realError='';el.setAttribute('role','alert');host.prepend(el)}el.textContent=message;el.hidden=false}}
  async function chooseFolder(){const result=await api('/api/preparation/folder/select',{});if(!result.cancelled)window.dispatchEvent(new CustomEvent('makora:project-folder',{detail:result}));return result}
  async function openFolder(){return api('/api/preparation/folder/open',{})}
  async function uploadSource(file){const auth=await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json();const response=await fetch('/api/preparation/source?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Makora-Token':auth.result.token},body:file});const data=await response.json();if(!response.ok)throw Error(data.error?.message||'Не удалось сохранить исходный файл');return data.result}
  async function start(brief,sourceFile){if(sourceFile)await uploadSource(sourceFile);state=await api('/api/preparation/1/start',{brief});stage=1;file=null;localStorage.setItem('makora.real-stage','1');history.replaceState(null,'',location.pathname)}
  function schedule(){clearTimeout(timer);if(stage<=5&&(['running','unconfirmed','stopping'].includes(state.stages[stage]?.status)||(state.stages[stage]?.status==='failed'&&state.stages[stage]?.agentStatus==='failed'))){timer=setTimeout(async()=>{try{state=await api(`/api/preparation/${stage}/refresh`,{});paint()}catch(e){error(e.message);schedule()}},4000)}}
  function paint(){
    if(stage!==7)window.makoraCodingAgents?.hide();
    const scene=root();if(!scene||!state.brief)return;
    const board=scene.querySelector('.board'),content=scene.querySelector('.board-content');
    window.makoraRealAgents?.cancel?.();
    if(!board.classList.contains('rp-board')){board.classList.add('rp-board');requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))}
    if(!board.querySelector('.board-size')){const size=document.createElement('button');size.type='button';size.className='board-size';size.textContent='＋';size.setAttribute('aria-label','Увеличить доску');size.onclick=()=>{const large=board.classList.toggle('rp-large');size.textContent=large?'−':'＋';size.setAttribute('aria-label',large?'Уменьшить доску':'Увеличить доску');window.dispatchEvent(new Event('resize'))};board.querySelector('.board-expand').before(size)}
    board.classList.remove('idea-board','plan-index-board','revision-view');board.classList.add('workspace-board');
    board.classList.toggle('agent-real-mode',stage>=6);
    board.classList.add('rp-analysis');

    scene.querySelector('.board-kicker').textContent='ПРОЕКТ · МАКОРА';
    const headerStage=scene.querySelector('[data-header-stage]');if(headerStage)headerStage.textContent='Этап '+stage+' из 7 · '+['Анализ','Конкуренты','Идея','План','Мок-данные','Прототип','Агенты'][stage-1];
    scene.querySelector('.board-bar h2').textContent=names[stage-1];scene.querySelector('.board-heading span:first-child').textContent=String(stage).padStart(2,'0')+' / '+names[stage-1];scene.querySelector('.board-footer span:last-child').textContent=String(stage).padStart(2,'0')+' / 07';
    scene.querySelector('.scene-bottom p').textContent='Реальные артефакты проекта · результаты требуют вашего утверждения';
    scene.querySelector('.board-next').hidden=true;
    scene.querySelector('[data-workflow-notice]')?.remove();
    if(state.workflowNotice){const notice=document.createElement('p');notice.dataset.workflowNotice='';notice.textContent=state.workflowNotice;notice.setAttribute('role','status');const keep=document.createElement('button');keep.className='rp-text-button';keep.textContent='Сохранить согласования старого проекта';keep.onclick=()=>action(async()=>{state=await api('/api/preparation/workflow/preserve-legacy',{confirm:true});await open(state.lastStage)});if(state.legacyChoiceAvailable)notice.append(keep);scene.querySelector('.board-bar').after(notice)}
    const nav=scene.querySelector('.board-stages')||scene.querySelector('[data-board-stage]')?.parentElement;
    if(nav){nav.innerHTML=names.map((name,i)=>{const approved=i<5?state.stages[i+1]?.status==='approved':i===5&&(state.prototype?.status==='approved'||state.returnedProject?.status==='prepared');const unlocked=names.slice(0,Math.min(i,5)).every((_,j)=>state.stages[j+1]?.status==='approved')&&(i<6||state.prototype?.status==='approved'||state.returnedProject?.status==='prepared');return `<button type="button" data-real-stage="${i+1}" class="${stage===i+1?'active':''} ${approved?'rp-complete':''}" ${unlocked?'':'disabled'} ${stage===i+1?'aria-current="step"':''} title="${name}"><b class="rp-stage-index">${approved?'✓':String(i+1).padStart(2,'0')}</b><span>${['Анализ','Конкуренты','Идея','План','Моки','Прототип','Агенты'][i]}<small>${stage===i+1?'Вы здесь':approved?'Утверждено':unlocked?'Доступно':'Впереди'}</small></span></button>`}).join('')}
    scene.querySelectorAll('[data-real-stage]').forEach(b=>b.onclick=()=>open(Number(b.dataset.realStage)).catch(e=>error(e.message)));
    scene.querySelectorAll('.capabilities-toggle,.capabilities-menu').forEach(el=>el.hidden=true);
    const projectKey='makora.real-feedbacks.v2.'+(state.projectId||'current');if(feedbackProject!==projectKey){feedbackProject=projectKey;try{feedbacks=JSON.parse(localStorage.getItem(projectKey))||{}}catch{feedbacks={}}}
    if(stage===6){window.makoraModelStatus?.external();handoffView(content,board);return}
    if(stage===7){window.makoraModelStatus?.agents([]);development(content,board);return}
    const record=state.stages[stage],files=record?.files||{},status=record?.status||'not_started';
    if(record?.skillBindingMode==='native'&&Array.isArray(record.skillManifest))scene.querySelector('.board-kicker').textContent='ПРОЕКТ · НАТИВНЫЕ НАВЫКИ · '+record.skillManifest.map(skill=>skill.name).join(', ');
    window.makoraModelStatus?.preparation(record);
    const working=['running','launching','stopping'].includes(status);
    artifactView(scene,board,content,record,files,status,working,projectKey);
  }
  function artifactView(scene,board,content,record,files,status,working,projectKey){
    const step=stage,paths=Object.keys(files),main=paths.find(p=>/\.md$/.test(p))||paths[0];
    const expected=['01_case_analysis.md','02_competitors.md','02_solution_concept.md','03_architecture.md','04_validation_report.md'][step-1];
    const ready=['review','approved'].includes(status)&&paths.length>0;
    const motionKey=step;
    if(working&&analysisMotion.key!==motionKey)analysisMotion={key:motionKey,started:performance.now()};
    if(!working)analysisMotion.key=null;
    const wheelDelay=working?-((performance.now()-analysisMotion.started)/1000):0;
    const go=()=>open(step+1).catch(e=>error(e.message));
    content.innerHTML=`<div class="board-document rp-workspace analysis-summary" data-phase="${esc(status)}">
      ${(record?.filesystemIsolation==='windows-compatible-read'||/Win/i.test(navigator.platform))?'<p role="note">Windows: запись ограничена рабочей областью; полная изоляция чтения вне проекта не гарантируется.</p>':''}
      ${working?`<div class="analysis-thinking" role="status"><img src="analysis-wheel.png" alt="" class="analysis-wheel" style="animation-delay:${wheelDelay}s"><p>${status==='stopping'?'Останавливаем сессию…':'Составляются материалы этапа'}</p><small>${esc(expected)}${record?.lastCheckedAt?' · проверено '+esc(new Date(record.lastCheckedAt).toLocaleTimeString()):''}</small>${record?.sessionId?`<button class="rp-secondary" data-real-cancel ${status==='stopping'?'disabled':''}>Остановить</button>`:''}</div>`:`<p class="analysis-purpose">${ready?'Материалы подготовлены. ':''}${esc(purposes[step-1])}</p>
      ${main?`<button class="analysis-file" data-real-file="${esc(main)}"><span class="analysis-file-mark">${paths.length===1?'MD':'▤'}</span><span><strong>${paths.length===1?esc(fileTitle(main)):'Материалы этапа'}</strong><small>${paths.length===1?esc(main):paths.length+' файлов · документы, схемы и данные'}</small></span><span aria-hidden="true">↗</span></button>`:''}
      ${status==='unconfirmed'?`<p role="status">Ответ агента пока не подтверждён. Проверьте состояние; повторная отправка не выполняется.</p>${record?.sessionId?'<button class="rp-secondary" data-real-cancel>Остановить сессию</button>':''}`:''}

      ${record?.skillManifest?.length?`<details><summary>Навыки и проверки выполнения</summary><ul>${record.skillManifest.map(skill=>`<li>${esc(skill.name)} · версия ${esc((skill.packageSha256||skill.sha256||'').slice(0,12))}</li>`).join('')}</ul><p>${record.nativeSkillStatus==='accepted'?'API подтвердил приём навыков.':'Подключение навыков ещё не подтверждено.'} ${record.methodologyStatus==='structure_checked'?'Структурные проверки выполнены; это не доказательство полноты методики.':'Результат методических проверок ещё не получен.'}</p></details>`:''}
      ${record?.error?`<p data-real-error role="alert">${esc(typeof record.error==='string'?record.error:'Не удалось выполнить запрос агента. Проверьте состояние.')}</p>`:''}
      <div class="analysis-actions"><button class="rp-secondary" data-analysis-edit ${status==='unconfirmed'?'disabled':''} ${!record?'data-real-run':''}>${record?'Пересоздать с уточнениями':'Начать этап →'}</button>${ready?`<button class="rp-primary" ${status==='approved'?'data-real-next':'data-real-approve'}>${step===4?(status==='approved'?'К мок-данным →':'Утвердить весь план →'):'Продолжить →'}</button>`:''}${['failed','unconfirmed'].includes(status)?'<button class="rp-text-button" data-real-refresh>Проверить состояние ↻</button>':''}</div>`}
      <div data-real-approvals></div></div><article class="analysis-reader" data-real-document data-phase="${esc(status)}" hidden></article>`;
    const show=path=>{
      if(!files[path])return;file=path;content.querySelector('.analysis-summary').hidden=true;
      const doc=content.querySelector('[data-real-document]');doc.hidden=false;
      const checks=record?.checks||[],questions=record?.questions||[],limits=record?.limitations||[];
      doc.innerHTML=`<header class="analysis-reader-header"><button class="rp-text-button" data-analysis-close data-rp-back>← К результату</button><span>${String(step).padStart(2,'0')} / ${esc(names[step-1])}</span><a download="${esc(path.split('/').pop())}">Скачать файл ↓</a></header><div class="artifact-reader-layout"><aside class="artifact-files" aria-label="Файлы этапа">${paths.map(p=>`<button data-real-file="${esc(p)}" class="${p===path?'active':''}" ${p===path?'aria-current="page"':''}><strong>${esc(fileTitle(p))}</strong><small>${esc(p)}</small></button>`).join('')}${checks.length?`<details class="artifact-checks"><summary>Проверки · ${checks.filter(c=>c.status==='passed').length}/${checks.length}</summary>${checks.map(c=>`<p>${c.status==='passed'?'✓':c.status==='not_checked'?'?':'×'} ${esc(c.name)}${c.detail?`<br><small>${esc(c.detail)}</small>`:''}</p>`).join('')}<small>Проверки артефактов. Тесты приложения выполняются при разработке.</small></details>`:''}${record?.requirementCoverage?.length?`<details><summary>Покрытие требований</summary>${record.requirementCoverage.map(row=>`<p>${esc(row.requirementId)} · ${esc(row.disposition)} · ${esc(row.reason||(row.artifacts||[]).join(', '))}</p>`).join('')}</details>`:''}${questions.length?`<details><summary>Открытые вопросы · ${questions.length}</summary><ul>${questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}${limits.length?`<details><summary>Ограничения · ${limits.length}</summary><ul>${limits.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}</aside><div class="analysis-paper"><p class="analysis-filename">${esc(path)}</p>${/\.md$/i.test(path)?markdown(files[path]):/\.mmd$/i.test(path)?markdown('```mermaid\n'+files[path]+'\n```'):`<h1>${esc(fileTitle(path))}</h1><pre class="case-source"><code>${esc(files[path])}</code></pre>`}</div></div>${ready?`<footer class="artifact-approval"><div><strong>${status==='approved'?'Этап уже утверждён':step===4?'Подтверждение плана разработки':'Подтверждение результата'}</strong><p>${status==='approved'?'Материалы сохранены и доступны следующему этапу.':`Утверждение относится ко всем ${paths.length} файлам этапа. Каждый файл отдельно подтверждать не нужно.`}</p></div><div><button class="rp-secondary" data-reader-edit>Нужны правки</button><button class="rp-primary" data-reader-approve>${status==='approved'?'Перейти дальше →':step===4?'Утвердить весь план →':'Утвердить и продолжить →'}</button></div></footer>`:''}`;
      doc.querySelector('[data-reader-approve]')?.addEventListener('click',()=>action(async()=>{if(status!=='approved')state=await api(`/api/preparation/${step}/approve`,{note:step===2?competitorDecision():feedbacks[step]||'',...(step===2?{decisions:{...(state.competitorDecisions||{}),...(feedbacks.competitorDecisions||{})}}:{})});file=null;await open(step+1)}));
      doc.querySelector('[data-reader-edit]')?.addEventListener('click',()=>{if(board.classList.contains('expanded'))board.querySelector('.board-expand').click();else{file=null;paint()}root()?.querySelector('[data-analysis-edit]')?.click()});
      if(doc.dataset.downloadUrl)URL.revokeObjectURL(doc.dataset.downloadUrl);doc.dataset.downloadUrl=URL.createObjectURL(new Blob([files[path]],{type:'text/plain;charset=utf-8'}));doc.querySelector('a[download]').href=doc.dataset.downloadUrl;
      doc.querySelectorAll('[data-real-file]').forEach(b=>b.onclick=()=>show(b.dataset.realFile));
      doc.querySelector('[data-analysis-close]').onclick=()=>{if(board.classList.contains('expanded'))board.querySelector('.board-expand').click();else{file=null;paint()}};
      diagrams(doc);content.scrollTop=0;
    };
    content.querySelector('[data-real-file]')?.addEventListener('click',()=>{show(main);if(!board.classList.contains('expanded'))board.querySelector('.board-expand').click()});
    if(file&&files[file])show(file);
    content.querySelector('[data-analysis-edit]')?.addEventListener('click',()=>{
      const regenerate=feedback=>action(async()=>{window.makoraModelStatus?.preparation({status:'dispatching'});artifactView(scene,board,content,record,{},'launching',true,projectKey);try{state=await api(`/api/preparation/${step}/start`,{feedback});file=null;root()?.querySelector('.analysis-chat')?.remove();paint()}catch(e){try{state=await api('/api/preparation')}catch{}paint();throw e}});
      if(!record){regenerate(feedbacks[step]||'');return}
      openRefinementChat({key:projectKey,step,title:step===2?'Каких конкурентов искать?':'Какие правки внесём?',description:`Расскажи, что поправить: ${names[step-1].toLowerCase()}. Я обновлю материалы этапа.`,submit:step===2?'Обновить поиск →':'Пересоздать материалы →',onSubmit:regenerate});
    });
    content.querySelector('[data-real-approve]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/approve`,{note:step===2?competitorDecision():feedbacks[step]||'',...(step===2?{decisions:{...(state.competitorDecisions||{}),...(feedbacks.competitorDecisions||{})}}:{})});await open(step+1)}));
    content.querySelector('[data-real-next]')?.addEventListener('click',go);
    content.querySelector('[data-real-refresh]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/refresh`,{});paint()}));
    if(step===2&&!working)competitorView(content,record,files,projectKey);
    content.querySelector('[data-real-cancel]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/cancel`,{});paint()}));
    approvals(content);schedule();
  }
  function competitorDecision(){return feedbacks.competitorDecision||state.competitorPreferences||''}
  function competitorView(content,record,files,projectKey){
    const summary=content.querySelector('.analysis-summary');
    if(!summary)return;
    if(record?.status==='unconfirmed'||record?.status==='failed'&&!files['02_competitors.json'])return;
    const edit=summary.querySelector('[data-analysis-edit]');if(edit)edit.textContent=record?'Найти ещё или уточнить поиск':'Найти конкурентов →';
    if(!files['02_competitors.json'])return;
    let research;try{research=JSON.parse(files['02_competitors.json'])}catch{return}
    const safeUrl=value=>{try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null}catch{return null}};
    const link=(url,label)=>safeUrl(url)?`<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`:esc(label);
    const panel=document.createElement('section');panel.className='competitor-review';panel.setAttribute('aria-label','Сравнение конкурентов');
    panel.innerHTML=`<h3>Что уже существует и чему можно научиться</h3><p>Сравнение основано на источниках, перечисленных в карточках. Непроверенные возможности отмечены отдельно.</p>${esc(research.searchBrief||'')?`<p class="competitor-scope">${esc(research.searchBrief)}</p>`:''}${(research.competitors||[]).map(c=>`<article class="competitor-card"><header><h4>${link(c.url,c.name)}</h4><span>${(record.sourceEvidence||[]).some(source=>source.status==='passed'&&(c.sources||[]).some(ref=>ref.url===source.url&&(ref.quote||'')===(source.quote||'')))?'Цитата подтверждена проверкой':c.status==='verified'?'Заявлено агентом · проверка контроллера не подтверждена':'Не проверено'}</span></header><p>${esc(c.summary||'')}</p><div class="competitor-table"><table><caption>Сравнение с вашим продуктом</caption><thead><tr><th scope="col">Критерий</th><th scope="col">Ваш продукт</th><th scope="col">${esc(c.name)}</th></tr></thead><tbody>${(c.comparison||[]).map(r=>`<tr><th scope="row">${esc(r.criterion)}</th><td>${esc(r.ours)}</td><td>${esc(r.theirs)}</td></tr>`).join('')}</tbody></table></div>${c.ideasToBorrow?.length?`<p><strong>Что рассмотреть:</strong> ${esc(c.ideasToBorrow.join('; '))}</p>`:''}<label>Решение по ${esc(c.name)}<select data-competitor-choice="${esc(c.id)}"><option value="">Выберите решение</option><option value="research">Исследовать дальше</option><option value="borrow">Перенять</option><option value="adapt">Адаптировать</option><option value="avoid">Не использовать</option></select></label><label>Комментарий<textarea rows="2" data-competitor-note="${esc(c.id)}" placeholder="Какие механики и почему"></textarea></label><ul class="competitor-sources">${(c.sources||[]).map(source=>`<li>${link(source.url,source.title||source.url)} · ${esc(source.checkedAt)}</li>`).join('')}</ul></article>`).join('')}<label class="competitor-decision">Что перенять, чего избегать и чем отличаться<textarea data-competitor-decision rows="4" placeholder="Например: взять фильтры у первого продукта, упростить регистрацию; платёжные функции не нужны.">${esc(competitorDecision())}</textarea></label><p>Этот комментарий будет передан в разработку идеи и новых схем. Если ничего не подходит, укажите это.</p>`;
    const board=root().querySelector('.board');
    panel.hidden=!board.classList.contains('expanded');
    const compare=document.createElement('button');compare.type='button';compare.className='analysis-file';compare.dataset.competitorOpen='';
    compare.textContent=`Сравнить конкурентов и выбрать подходы · ${(research.competitors||[]).length}`;
    compare.onclick=()=>{if(!board.classList.contains('expanded'))board.querySelector('.board-expand').click();panel.hidden=false;panel.scrollIntoView({block:'start'})};
    summary.querySelector('.analysis-actions')?.before(compare,panel);
    panel.querySelectorAll('[data-competitor-choice]').forEach(select=>{
      const id=select.dataset.competitorChoice,note=[...panel.querySelectorAll('[data-competitor-note]')].find(el=>el.dataset.competitorNote===id);
      const saved=({...state.competitorDecisions,...feedbacks.competitorDecisions})[id];if(saved){select.value=saved.action;note.value=saved.comment||''}
      const save=()=>{feedbacks.competitorDecisions={...(state.competitorDecisions||{}),...(feedbacks.competitorDecisions||{})};feedbacks.competitorDecisions[id]={action:select.value,comment:note.value};localStorage.setItem(projectKey,JSON.stringify(feedbacks))};select.onchange=save;note.oninput=save;
    });
    if(record.comparisonChanges){const change=document.createElement('p');change.textContent=`Изменение выборки: добавлено ${record.comparisonChanges.added.length}, исключено ${record.comparisonChanges.removed.length}, обновлено ${record.comparisonChanges.updated.length}`;panel.prepend(change)}
    panel.querySelector('[data-competitor-decision]').oninput=e=>{feedbacks.competitorDecision=e.target.value;localStorage.setItem(projectKey,JSON.stringify(feedbacks))};
  }
  function openRefinementChat({key=feedbackProject,step,title,description,submit,onSubmit}){
    window.makoraChat?.close();
    const scene=root();if(!scene)return;
    if(scene.querySelector('.analysis-chat')){scene.querySelector('.analysis-chat textarea').focus();return}
    const chat=document.createElement('form');chat.className='analysis-chat';chat.setAttribute('aria-label','Уточнения Макоре');
    chat.innerHTML=`<div class="speech-label"><span class="analysis-chat-speaker"><i aria-hidden="true"></i> МАКОРА</span><button type="button" aria-label="Закрыть уточнения" data-chat-close>×</button></div><div class="analysis-chat-body"><h3>${esc(title)}</h3><p>${esc(description)}</p><textarea aria-label="Уточнения к этапу" placeholder="Что добавить или исправить?">${esc(feedbacks[step]||'')}</textarea><label class="analysis-attachment"><span aria-hidden="true">＋</span> Файл с уточнениями<input type="file" accept=".pdf,.docx,.txt,.md" hidden></label><small class="analysis-attachment-name" role="status"></small><p class="analysis-chat-error" role="alert"></p></div><button class="rp-primary" type="submit">${esc(submit)}</button>`;
    scene.append(chat);positionAnalysisChat();chat.querySelector('[data-chat-close]').onclick=()=>chat.remove();
    const input=chat.querySelector('textarea'),button=chat.querySelector('[type=submit]');input.focus();input.oninput=()=>{feedbacks[step]=input.value;localStorage.setItem(key,JSON.stringify(feedbacks))};
    let attached='',reading=false;
    async function attach(f){if(!f)return;reading=true;button.disabled=true;const label=chat.querySelector('.analysis-attachment-name');label.textContent='Читаем файл…';try{attached=await extract(f,true);label.textContent=f.name}catch(e){label.textContent=e.message}finally{reading=false;button.disabled=false}}
    chat.querySelector('input').onchange=e=>attach(e.target.files[0]);chat.ondragover=e=>e.preventDefault();chat.ondrop=e=>{e.preventDefault();attach(e.dataTransfer.files[0])};
    chat.onsubmit=async e=>{e.preventDefault();if(reading||button.disabled)return;const feedback=[input.value,attached].filter(Boolean).join('\n\n');if(!feedback.trim()){input.focus();return}feedbacks[step]=feedback;localStorage.setItem(key,JSON.stringify(feedbacks));button.disabled=true;button.textContent='Отправляем…';try{await onSubmit(feedback)}catch(e){chat.querySelector('.analysis-chat-error').textContent=e.message}finally{if(chat.isConnected){button.disabled=false;button.textContent=submit}}};
  }
  function positionAnalysisChat(){
    const chat=root()?.querySelector('.analysis-chat'),mascot=root()?.querySelector('.mascot-area');if(!chat||!mascot)return;
    const r=mascot.getBoundingClientRect(),width=Math.min(344,innerWidth-24),left=Math.max(12,Math.min(innerWidth-width-12,r.left+r.width/2-width/2));
    const top=Math.min(innerHeight-140,Math.max(88,r.bottom+14));
    Object.assign(chat.style,{left:left+'px',top:top+'px',maxHeight:Math.max(120,innerHeight-top-16)+'px'});
    chat.style.setProperty('--chat-available',Math.max(120,innerHeight-top-16)+'px');
    chat.style.setProperty('--chat-anchor',Math.max(20,Math.min(width-20,r.left+r.width/2-left))+'px');
  }
  window.addEventListener('makora:mascot-move',positionAnalysisChat);
  window.addEventListener('resize',positionAnalysisChat);
  window.addEventListener('makora:board-fullscreen',e=>{if(!e.detail.expanded&&stage===6){const content=root()?.querySelector('.board-content');const reader=content?.querySelector('[data-handoff-reader]');if(reader){reader.hidden=true;content.querySelector('.analysis-summary').hidden=false}}if(!e.detail.expanded&&stage<=5&&(file||stage===2)){file=null;paint()}});
  async function action(fn){if(busy)return;busy=true;root()?.querySelector('.board-content')?.setAttribute('aria-busy','true');try{await fn()}catch(e){error(e.message)}finally{busy=false;root()?.querySelector('.board-content')?.setAttribute('aria-busy','false')}}
  async function approvals(content){try{const list=await api('/api/agents/approvals');if(!content.isConnected)return;const host=content.querySelector('[data-real-approvals]');if(!host)return;host.innerHTML=list.map(item=>`<details><summary>Codex запрашивает разрешение</summary><pre>${esc(JSON.stringify(item.params,null,2))}</pre><button data-prep-approval="${esc(item.requestId)}" data-choice="accept">Разрешить</button><button data-prep-approval="${esc(item.requestId)}" data-choice="decline">Отклонить</button></details>`).join('');host.querySelectorAll('[data-prep-approval]').forEach(b=>b.onclick=()=>action(async()=>{await api(`/api/agents/approvals/${b.dataset.prepApproval}`,{decision:b.dataset.choice});paint()}))}catch(e){error(e.message)}}
  async function handoffView(content,board){
    const ticket=++generation;
    if(state.stages['5']?.status!=='approved'){content.innerHTML='<p>Сначала утвердите мок-данные.</p>';return}
    content.innerHTML='<div class="analysis-thinking"><img class="analysis-wheel" src="analysis-wheel.png" alt=""><p>Собираем промпт и файлы…</p></div>';
    try{
      const pack=await api('/api/preparation/package');if(ticket!==generation||stage!==6)return;
      content.innerHTML=`<section class="analysis-summary"><p class="analysis-purpose">Передайте промпт и ZIP своему ИИ-агенту для создания прототипа. Сначала попросите выполнить ENVIRONMENT_CHECK.md: чтение файла и создание небольшого скачиваемого ZIP.</p><button class="analysis-file" data-handoff-open><span class="analysis-file-mark">ZIP</span><span><strong>Промпт и контекст проекта</strong><small>PROMPT.md · ${pack.files.length} файлов</small></span><span>↗</span></button><div class="analysis-actions"><button class="rp-secondary" data-handoff-copy>Скопировать промпт</button><a class="rp-primary handoff-download" href="/api/preparation/archive" download="makora-agent-package.zip">Скачать пакет ↓</a></div><small class="handoff-state" role="status">После передачи пакета ожидаем результат внешнего агента.</small></section><article class="analysis-reader" data-handoff-reader hidden></article>`;
      const copy=async button=>{try{await navigator.clipboard.writeText(pack.prompt);button.textContent='Промпт скопирован ✓'}catch{button.textContent='Откройте PROMPT.md и скопируйте текст'}};
      const receive=document.createElement('section');receive.className='handoff-receive';
      receive.innerHTML=`<h3>Готовый сайт</h3><p>Прикрепите ZIP, который вернул ваш ИИ-агент.</p><label class="handoff-drop" data-result-drop><span>＋ Выбрать ZIP проекта</span><small>или перетащить сюда · до 100 МБ</small><input type="file" accept=".zip,application/zip" data-result-file></label><p class="handoff-upload-status" role="status" aria-live="polite"></p><div data-result-summary></div>`;
      content.querySelector('.analysis-summary').append(receive);
      const resultHost=receive.querySelector('[data-result-summary]'),uploadStatus=receive.querySelector('.handoff-upload-status'),input=receive.querySelector('[data-result-file]'),drop=receive.querySelector('[data-result-drop]');
      const packageTile=content.querySelector('[data-handoff-open]'),tiles=document.createElement('div');tiles.className='handoff-tiles';
      packageTile.before(tiles);tiles.append(packageTile);
      const uploadTile=document.createElement('button');uploadTile.type='button';uploadTile.className='analysis-file';uploadTile.dataset.handoffUpload='';
      uploadTile.innerHTML='<span class="analysis-file-mark">↑</span><span><strong>Прикрепить готовый ZIP</strong><small>Сайт от вашего ИИ-агента</small></span><span>＋</span>';
      uploadTile.onclick=()=>input.click();tiles.append(uploadTile);
      const showResult=result=>{
        if(!result)return;
        resultHost.innerHTML=`<div class="handoff-received"><strong>✓ ZIP проекта сохранён</strong><p>${esc(result.name)} · файлов: ${result.fileCount}</p><p>${result.mocksStatus==='passed'?'Исходные мок-данные сохранены.':'В исходных мок-данных есть изменения или отсутствующие файлы.'}${result.newMocks?.length?' Новых мок-файлов: '+result.newMocks.length+'.':''}</p><details><summary>Файлы проекта</summary><ul>${result.files.map(path=>`<li>${esc(path)}</li>`).join('')}</ul></details><a href="/api/preparation/result" download="makora-website.zip">Скачать сохранённый ZIP ↓</a><small>Архив проверен и сохранён. Работоспособность сайта ещё не проверялась.</small></div>`;
        const actions=document.createElement('div');actions.className='analysis-actions';
        actions.innerHTML='<button type="button" class="rp-primary" data-result-continue>Продолжить с этим сайтом →</button><button type="button" class="rp-secondary" data-result-replace>Заменить ZIP</button>';
        resultHost.prepend(actions);
        const next=actions.querySelector('[data-result-continue]');
        next.onclick=()=>action(async()=>{next.disabled=true;next.textContent='Подготавливаем сайт…';try{state=await api('/api/preparation/result/continue',{});await open(7)}finally{next.disabled=false;next.textContent='Продолжить с этим сайтом →'}});
        actions.querySelector('[data-result-replace]').onclick=()=>input.click();
        const explanation=document.createElement('p');explanation.textContent='Дальше агенты изучат загруженный сайт и составят план проверки и доработок. Запуск плана — на следующем этапе.';resultHost.prepend(explanation);
        uploadTile.querySelector('strong').textContent='Продолжить с сайтом →';uploadTile.onclick=()=>{resultHost.scrollIntoView({block:'nearest'});next.focus()};
      };
      showResult(pack.returnedProject);
      let uploading=false;
      const upload=async selected=>{
        if(!selected||uploading)return;
        if(!/\.zip$/i.test(selected.name)||!selected.size||selected.size>100*1024*1024){uploadStatus.textContent='Выберите непустой ZIP-архив размером до 100 МБ.';input.value='';receive.scrollIntoView({block:'nearest'});return}
        uploading=true;input.disabled=true;uploadTile.disabled=true;drop.setAttribute('aria-busy','true');uploadStatus.textContent='Загружаем и проверяем архив…';receive.scrollIntoView({block:'nearest'});
        try{
          const tokenResponse=await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'},credentials:'same-origin'}),auth=await tokenResponse.json();
          if(!tokenResponse.ok)throw Error(auth.error?.message||'Нет доступа к локальному API');
          const response=await fetch('/api/preparation/result?name='+encodeURIComponent(selected.name),{method:'POST',headers:{'Content-Type':'application/zip','X-Makora-Token':auth.result.token},credentials:'same-origin',body:selected}),data=await response.json();
          if(!response.ok)throw Error(data.error?.message||'Не удалось загрузить ZIP');
          state.returnedProject=data.result;showResult(data.result);uploadStatus.textContent='Готово. Нажмите «Продолжить с этим сайтом».';resultHost.scrollIntoView({block:'nearest'});
        }catch(e){uploadStatus.textContent=e.message}finally{uploading=false;input.disabled=false;uploadTile.disabled=false;input.value='';drop.removeAttribute('aria-busy')}
      };
      input.onchange=()=>upload(input.files[0]);
      for(const event of ['dragenter','dragover'])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.add('drag-over')});
      for(const event of ['dragleave','drop'])drop.addEventListener(event,e=>{e.preventDefault();drop.classList.remove('drag-over')});
      drop.addEventListener('drop',e=>upload(e.dataTransfer.files[0]));
      content.querySelector('[data-handoff-copy]').onclick=e=>copy(e.currentTarget);
      const show=(path='PROMPT.md')=>{
        const doc=content.querySelector('[data-handoff-reader]');content.querySelector('.analysis-summary').hidden=true;doc.hidden=false;
        doc.innerHTML=`<header class="analysis-reader-header"><button class="rp-text-button" data-handoff-back>← К пакету</button><span>06 / ПЕРЕДАЧА ВНЕШНЕМУ АГЕНТУ</span><a href="/api/preparation/archive" download="makora-agent-package.zip">Скачать ZIP ↓</a></header><div class="artifact-reader-layout"><aside class="artifact-files">${pack.files.map(f=>pack.documents[f.path]!==undefined?`<button data-package-file="${esc(f.path)}" class="${f.path===path?'active':''}"><strong>${esc(f.path.split('/').pop())}</strong><small>${esc(f.path)}</small></button>`:`<p>${esc(f.path)} · в архиве</p>`).join('')}</aside><div class="analysis-paper"><p class="analysis-filename">${esc(path)}</p>${/\.md$/.test(path)?markdown(pack.documents[path]):`<pre>${esc(pack.documents[path])}</pre>`}</div></div><footer class="artifact-approval"><div><strong>Готово для вашего ИИ-агента</strong><p>Прикрепите ZIP и отправьте PROMPT.md. Исходные mocks/ сохраняются, изменения — в new_mocks/.</p></div><div><button data-copy-full>Скопировать промпт</button><a class="handoff-download" href="/api/preparation/archive" download="makora-agent-package.zip">Скачать пакет ↓</a></div></footer>`;
        doc.querySelectorAll('[data-package-file]').forEach(b=>b.onclick=()=>show(b.dataset.packageFile));doc.querySelector('[data-copy-full]').onclick=e=>copy(e.currentTarget);
        doc.querySelector('[data-handoff-back]').onclick=()=>{doc.hidden=true;content.querySelector('.analysis-summary').hidden=false;if(board.classList.contains('expanded'))board.querySelector('.board-expand').click()};diagrams(doc);
      };
      content.querySelector('[data-handoff-open]').onclick=()=>{show();if(!board.classList.contains('expanded'))board.querySelector('.board-expand').click()};
      content.querySelectorAll('.handoff-download').forEach(a=>a.addEventListener('click',()=>{content.querySelector('.handoff-state').textContent='Пакет передан на скачивание. Прикрепите его внешнему агенту и отправьте промпт.'}));
    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function development(content,board){
    const ticket=++generation;
    if(state.stages['5']?.status!=='approved'){content.innerHTML='<div class="board-document"><p>Сначала выполни и утверди подготовку мок-данных.</p></div>';return}
    content.innerHTML='<div class="board-document"><p>Подготавливаем отдельный Git-проект по утверждённым файлам…</p></div>';
    try{const project=await api('/api/preparation/development',{stage});if(ticket!==generation||stage<6)return;
      if(stage===7&&state.prototype?.status!=='approved'&&state.returnedProject?.status!=='prepared'){throw Error('Сначала утверди работающий прототип на этапе 6.')}
      if(!window.makoraRealAgents){await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='agent-runtime-ui.js?v=stage-model-41';script.onload=resolve;script.onerror=reject;document.head.append(script)})}
      if(stage===7&&localStorage.getItem('makora.real-agents-base')!==(state.returnedProject?.commit||state.prototype?.commit)){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-agents-base',(state.returnedProject?.commit||state.prototype?.commit))}
      const previousDigest=localStorage.getItem('makora.real-development-digest');if(previousDigest!==project.digest){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-development-digest',project.digest)}
      project.brief+=stage===6?'\nСоздай работающий прототип на исходных mocks/fixtures/. Сохрани mocks/, изменения предлагай в new_mocks/.':'\nПродолжи разработку текущего проекта по утверждённым требованиям.';
      const ctx={board,content,project,preparationStage:stage,approvePrototype:()=>action(async()=>{state=await api('/api/preparation/prototype/approve',{});await open(7)}),status:document.createElement('span'),primary:null,workflow:{getTasks:()=>[]},announce:error};
      await window.makoraRealAgents.render(ctx);
      if(ticket!==generation)return;

    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function open(number){root()?.querySelector('.board.expanded .board-expand')?.click();root()?.querySelector('.analysis-chat')?.remove();generation++;clearTimeout(timer);root()?.querySelectorAll('.board-content button,.board-content textarea,.board-content input').forEach(el=>el.disabled=true);stage=Math.max(1,Math.min(7,number));file=null;localStorage.setItem('makora.real-stage',String(stage));state=await api('/api/preparation/projects/stage',{stage});paint()}
  async function mount(){window.makoraModelStatus?.refresh();state=await api('/api/preparation');if(!state.brief)return;stage=Number(state.lastStage)||1;paint()}
  window.makoraPreparation={start,mount,open,extract,openRefinementChat,chooseFolder,openFolder};
})();


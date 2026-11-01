/* Real artifact pipeline. No example documents are used by this controller. */
(() => {
  let state={brief:'',stages:{}}, stage=1, file=null, timer=0, busy=false, generation=0, feedbacks={}, feedbackProject=null;
  let analysisMotion={key:null,started:0};
  const names=['Анализ задания','Разработка идеи','Планирование','Мок-данные','Рабочий прототип','Разработка агентами'];
  const purposes=['Разберём условие: что сделать, какие есть ограничения и как будут оценивать.','Исследуем проблему и выберем идею, которая отвечает требованиям задания.','Определим устройство продукта, контракты, проверки и задачи для разработки.','Подготовим данные для разработки и проверим их по схемам и сценариям.','Соберём работающий прототип из согласованных материалов и моков.','Разовьём утверждённый прототип с помощью агентов и проверяемых задач.'];
  const fileNames={'01_case_analysis.md':'Разбор задания','02_research.md':'Исследование проблемы','02_solution_concept.md':'Концепция решения','02_user_flow.mmd':'Путь пользователя','02_task_flow.mmd':'Сценарий действий','03_architecture.md':'Архитектура продукта','03_test_plan.md':'План тестирования','03_tasks.json':'Задачи для агентов','04_validation_report.md':'Отчёт о готовности данных'};
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
  async function diagrams(host){const elements=[...host.querySelectorAll('[data-real-mermaid]')];if(!elements.length)return;try{const mermaid=(await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')).default;mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'strict',flowchart:{htmlLabels:false}});for(const el of elements){const svg=await mermaid.render('real-'+crypto.randomUUID(),el.textContent);if(el.isConnected)el.innerHTML=svg.svg}}catch{}}
  async function extract(file,attachment=false){const token=await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json();const response=await fetch('/api/preparation/'+(attachment&&state.storageRoot?'attachment':'extract')+'?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Makora-Token':token.result.token},body:file});const result=await response.json();if(!response.ok)throw Error(result.error?.message||'Не удалось прочитать файл');return result.result.text}
  const root=()=>document.querySelector('#first-stage');
  function error(message){const host=root()?.querySelector('.board-content');if(host){let el=host.querySelector('[data-real-error]');if(!el){el=document.createElement('p');el.dataset.realError='';el.setAttribute('role','alert');host.prepend(el)}el.textContent=message;el.hidden=false}}
  async function chooseFolder(){const result=await api('/api/preparation/folder/select',{});if(!result.cancelled)window.dispatchEvent(new CustomEvent('makora:project-folder',{detail:result}));return result}
  async function openFolder(){return api('/api/preparation/folder/open',{})}
  async function uploadSource(file){const auth=await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json();const response=await fetch('/api/preparation/source?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Makora-Token':auth.result.token},body:file});const data=await response.json();if(!response.ok)throw Error(data.error?.message||'Не удалось сохранить исходный файл');return data.result}
  async function start(brief,sourceFile){if(sourceFile)await uploadSource(sourceFile);state=await api('/api/preparation/1/start',{brief});stage=1;file=null;localStorage.setItem('makora.real-stage','1');history.replaceState(null,'',location.pathname)}
  function schedule(){clearTimeout(timer);if(stage<=4&&['running','unconfirmed'].includes(state.stages[stage]?.status)){timer=setTimeout(async()=>{try{state=await api(`/api/preparation/${stage}/refresh`,{});paint()}catch(e){error(e.message);schedule()}},4000)}}
  function paint(){
    const scene=root();if(!scene||!state.brief)return;
    const board=scene.querySelector('.board'),content=scene.querySelector('.board-content');
    window.makoraRealAgents?.cancel?.();
    if(!board.classList.contains('rp-board')){board.classList.add('rp-board');requestAnimationFrame(()=>window.dispatchEvent(new Event('resize')))}
    if(!board.querySelector('.board-size')){const size=document.createElement('button');size.type='button';size.className='board-size';size.textContent='＋';size.setAttribute('aria-label','Увеличить доску');size.onclick=()=>{const large=board.classList.toggle('rp-large');size.textContent=large?'−':'＋';size.setAttribute('aria-label',large?'Уменьшить доску':'Увеличить доску');window.dispatchEvent(new Event('resize'))};board.querySelector('.board-expand').before(size)}
    board.classList.remove('idea-board','plan-index-board','revision-view');board.classList.add('workspace-board');
    board.classList.toggle('agent-real-mode',stage>=5);
    board.classList.add('rp-analysis');

    scene.querySelector('.board-kicker').textContent='ПРОЕКТ · GPT-6 LUNA';
    scene.querySelector('.board-bar h2').textContent=names[stage-1];scene.querySelector('.board-heading span:first-child').textContent=String(stage).padStart(2,'0')+' / '+names[stage-1];scene.querySelector('.board-footer span:last-child').textContent=String(stage).padStart(2,'0')+' / 06';
    scene.querySelector('.scene-bottom p').textContent='Реальные артефакты проекта · результаты требуют вашего утверждения';
    scene.querySelector('.board-next').hidden=true;
    const nav=scene.querySelector('.board-stages')||scene.querySelector('[data-board-stage]')?.parentElement;
    if(nav){nav.innerHTML=names.map((name,i)=>{const approved=i<4?state.stages[i+1]?.status==='approved':i===4&&state.prototype?.status==='approved';const unlocked=i===0||(i<5?state.stages[i]?.status==='approved':state.prototype?.status==='approved');return `<button type="button" data-real-stage="${i+1}" class="${stage===i+1?'active':''} ${approved?'rp-complete':''}" ${unlocked?'':'disabled'} ${stage===i+1?'aria-current="step"':''} title="${name}"><b class="rp-stage-index">${approved?'✓':String(i+1).padStart(2,'0')}</b><span>${['Анализ','Идея','План','Моки','Прототип','Агенты'][i]}<small>${stage===i+1?'Вы здесь':approved?'Утверждено':unlocked?'Доступно':'Впереди'}</small></span></button>`}).join('')}
    scene.querySelectorAll('[data-real-stage]').forEach(b=>b.onclick=()=>open(Number(b.dataset.realStage)).catch(e=>error(e.message)));
    scene.querySelectorAll('.capabilities-toggle,.capabilities-menu').forEach(el=>el.hidden=true);
    const projectKey='makora.real-feedbacks.'+(state.projectId||'current');if(feedbackProject!==projectKey){feedbackProject=projectKey;try{feedbacks=JSON.parse(localStorage.getItem(projectKey))||{}}catch{feedbacks={}}}
    if(stage>=5){development(content,board);return}
    const record=state.stages[stage],files=record?.files||{},status=record?.status||'not_started';
    const working=['running','launching','unconfirmed'].includes(status);
    artifactView(scene,board,content,record,files,status,working,projectKey);
  }
  function artifactView(scene,board,content,record,files,status,working,projectKey){
    const step=stage,paths=Object.keys(files),main=paths.find(p=>/\.md$/.test(p))||paths[0];
    const expected=['01_case_analysis.md','02_solution_concept.md','03_architecture.md','04_validation_report.md'][step-1];
    const ready=['review','approved'].includes(status)&&paths.length>0;
    const motionKey=step+':'+(record?.turnId||record?.threadId||'waiting');
    if(working&&analysisMotion.key!==motionKey)analysisMotion={key:motionKey,started:performance.now()};
    if(!working)analysisMotion.key=null;
    const wheelDelay=working?-((performance.now()-analysisMotion.started)/1000):0;
    const go=()=>open(step+1).catch(e=>error(e.message));
    content.innerHTML=`<div class="board-document rp-workspace analysis-summary" data-phase="${esc(status)}">
      ${working?`<div class="analysis-thinking" role="status"><img src="analysis-wheel.png" alt="" class="analysis-wheel" style="animation-delay:${wheelDelay}s"><p>${status==='unconfirmed'?'Проверяем состояние документов…':'Составляются материалы этапа'}</p><small>${esc(expected)}</small></div>`:`<p class="analysis-purpose">${ready?'Материалы подготовлены. ':''}${esc(purposes[step-1])}</p>
      ${main?`<button class="analysis-file" data-real-file="${esc(main)}"><span class="analysis-file-mark">${paths.length===1?'MD':'▤'}</span><span><strong>${paths.length===1?esc(fileTitle(main)):'Материалы этапа'}</strong><small>${paths.length===1?esc(main):paths.length+' файлов · документы, схемы и данные'}</small></span><span aria-hidden="true">↗</span></button>`:''}
      ${record?.error?`<p data-real-error role="alert">${esc(typeof record.error==='string'?record.error:JSON.stringify(record.error))}</p>`:''}
      <div class="analysis-actions"><button class="rp-secondary" data-analysis-edit ${!record?'data-real-run':''}>${record?'Пересоздать с уточнениями':'Начать этап →'}</button>${ready?`<button class="rp-primary" ${status==='approved'?'data-real-next':'data-real-approve'}>Продолжить →</button>`:''}${['failed','unconfirmed'].includes(status)?'<button class="rp-text-button" data-real-refresh>Проверить состояние ↻</button>':''}</div>`}
      <div data-real-approvals></div></div><article class="analysis-reader" data-real-document data-phase="${esc(status)}" hidden></article>`;
    const show=path=>{
      if(!files[path])return;file=path;content.querySelector('.analysis-summary').hidden=true;
      const doc=content.querySelector('[data-real-document]');doc.hidden=false;
      const checks=record?.checks||[],questions=record?.questions||[],limits=record?.limitations||[];
      doc.innerHTML=`<header class="analysis-reader-header"><button class="rp-text-button" data-analysis-close data-rp-back>← К результату</button><span>${String(step).padStart(2,'0')} / ${esc(names[step-1])}</span><a download="${esc(path.split('/').pop())}">Скачать файл ↓</a></header><div class="artifact-reader-layout"><aside class="artifact-files" aria-label="Файлы этапа">${paths.map(p=>`<button data-real-file="${esc(p)}" class="${p===path?'active':''}" ${p===path?'aria-current="page"':''}><strong>${esc(fileTitle(p))}</strong><small>${esc(p)}</small></button>`).join('')}${checks.length?`<details class="artifact-checks"><summary>Проверки · ${checks.filter(c=>c.status==='passed').length}/${checks.length}</summary>${checks.map(c=>`<p>${c.status==='passed'?'✓':'×'} ${esc(c.name)}</p>`).join('')}<small>Проверки артефактов. Тесты приложения выполняются при разработке.</small></details>`:''}${questions.length?`<details><summary>Открытые вопросы · ${questions.length}</summary><ul>${questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}${limits.length?`<details><summary>Ограничения · ${limits.length}</summary><ul>${limits.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}</aside><div class="analysis-paper"><p class="analysis-filename">${esc(path)}</p>${/\.md$/i.test(path)?markdown(files[path]):/\.mmd$/i.test(path)?markdown('```mermaid\n'+files[path]+'\n```'):`<h1>${esc(fileTitle(path))}</h1><pre class="case-source"><code>${esc(files[path])}</code></pre>`}</div></div>`;
      if(doc.dataset.downloadUrl)URL.revokeObjectURL(doc.dataset.downloadUrl);doc.dataset.downloadUrl=URL.createObjectURL(new Blob([files[path]],{type:'text/plain;charset=utf-8'}));doc.querySelector('a[download]').href=doc.dataset.downloadUrl;
      doc.querySelectorAll('[data-real-file]').forEach(b=>b.onclick=()=>show(b.dataset.realFile));
      doc.querySelector('[data-analysis-close]').onclick=()=>{if(board.classList.contains('expanded'))board.querySelector('.board-expand').click();else{file=null;paint()}};
      diagrams(doc);content.scrollTop=0;
    };
    content.querySelector('[data-real-file]')?.addEventListener('click',()=>{show(main);if(!board.classList.contains('expanded'))board.querySelector('.board-expand').click()});
    if(file&&files[file])show(file);
    content.querySelector('[data-analysis-edit]')?.addEventListener('click',()=>{
      const regenerate=feedback=>action(async()=>{state=await api(`/api/preparation/${step}/start`,{feedback});file=null;root()?.querySelector('.analysis-chat')?.remove();paint()});
      if(!record){regenerate(feedbacks[step]||'');return}
      openRefinementChat({key:projectKey,step,title:'Какие правки внесём?',description:`Расскажи, что поправить: ${names[step-1].toLowerCase()}. Я обновлю материалы этапа.`,submit:'Пересоздать материалы →',onSubmit:regenerate});
    });
    content.querySelector('[data-real-approve]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/approve`,{note:feedbacks[step]||''});await open(step+1)}));
    content.querySelector('[data-real-next]')?.addEventListener('click',go);
    content.querySelector('[data-real-refresh]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/refresh`,{});paint()}));
    approvals(content);schedule();
  }
  function openRefinementChat({key=feedbackProject,step,title,description,submit,onSubmit}){
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
  window.addEventListener('makora:board-fullscreen',e=>{if(!e.detail.expanded&&stage<=4&&file){file=null;paint()}});
  async function action(fn){if(busy)return;busy=true;root()?.querySelector('.board-content')?.setAttribute('aria-busy','true');try{await fn()}catch(e){error(e.message)}finally{busy=false;root()?.querySelector('.board-content')?.setAttribute('aria-busy','false')}}
  async function approvals(content){try{const list=await api('/api/agents/approvals');if(!content.isConnected)return;const host=content.querySelector('[data-real-approvals]');if(!host)return;host.innerHTML=list.map(item=>`<details><summary>Codex запрашивает разрешение</summary><pre>${esc(JSON.stringify(item.params,null,2))}</pre><button data-prep-approval="${esc(item.requestId)}" data-choice="accept">Разрешить</button><button data-prep-approval="${esc(item.requestId)}" data-choice="decline">Отклонить</button></details>`).join('');host.querySelectorAll('[data-prep-approval]').forEach(b=>b.onclick=()=>action(async()=>{await api(`/api/agents/approvals/${b.dataset.prepApproval}`,{decision:b.dataset.choice});paint()}))}catch(e){error(e.message)}}
  async function development(content,board){
    const ticket=++generation;
    if(state.stages['4']?.status!=='approved'){content.innerHTML='<div class="board-document"><p>Сначала выполни и утверди подготовку мок-данных.</p></div>';return}
    content.innerHTML='<div class="board-document"><p>Подготавливаем отдельный Git-проект по утверждённым файлам…</p></div>';
    try{const project=await api('/api/preparation/development',{stage});if(ticket!==generation||stage<5)return;
      if(stage===6&&state.prototype?.status!=='approved'){throw Error('Сначала утверди работающий прототип на этапе 5.')}
      if(!window.makoraRealAgents){await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='agent-runtime-ui.js?v=compact-10';script.onload=resolve;script.onerror=reject;document.head.append(script)})}
      if(stage===6&&localStorage.getItem('makora.real-stage6-base')!==state.prototype.commit){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-stage6-base',state.prototype.commit)}
      const previousDigest=localStorage.getItem('makora.real-development-digest');if(previousDigest!==project.digest){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-development-digest',project.digest)}
      project.brief+=stage===5?'\nСоздай работающий прототип на исходных mocks/fixtures/. Сохрани mocks/, изменения предлагай в new_mocks/.':'\nПродолжи разработку текущего проекта по утверждённым требованиям.';
      const ctx={board,content,project,preparationStage:stage,approvePrototype:()=>action(async()=>{state=await api('/api/preparation/prototype/approve',{});await open(6)}),status:document.createElement('span'),primary:null,workflow:{getTasks:()=>[]},announce:error};
      await window.makoraRealAgents.render(ctx);
      if(ticket!==generation)return;

    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function open(number){root()?.querySelector('.analysis-chat')?.remove();generation++;clearTimeout(timer);root()?.querySelectorAll('.board-content button,.board-content textarea,.board-content input').forEach(el=>el.disabled=true);stage=Math.max(1,Math.min(6,number));file=null;localStorage.setItem('makora.real-stage',String(stage));state=await api('/api/preparation');paint()}
  async function mount(){state=await api('/api/preparation');if(!state.brief)return;stage=Number(localStorage.getItem('makora.real-stage'))||1;paint()}
  window.makoraPreparation={start,mount,open,extract,openRefinementChat,chooseFolder,openFolder};
})();

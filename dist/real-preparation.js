/* Real artifact pipeline. No example documents are used by this controller. */
(() => {
  let state={brief:'',stages:{}}, stage=1, file=null, timer=0, busy=false, generation=0, feedbacks={}, feedbackProject=null;
  const names=['Анализ задания','Разработка идеи','Планирование','Мок-данные','Рабочий прототип','Разработка агентами'];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function api(path,body){
    const options={credentials:'same-origin',cache:'no-store'};
    if(body!==undefined){const token=await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'},credentials:'same-origin'});const auth=await token.json();if(!token.ok)throw Error(auth.error?.message||'Нет доступа к локальному API');options.method='POST';options.headers={'Content-Type':'application/json','X-Makora-Token':auth.result.token};options.body=JSON.stringify(body)}
    const response=await fetch(path,options), data=await response.json();if(!response.ok)throw Error(data.error?.message||'Ошибка API');return data.result;
  }
  function markdown(text){let html='',end=0;for(const match of text.matchAll(/```([^\n]*)\n([\s\S]*?)```/g)){html+=render(text.slice(end,match.index));html+=match[1].trim()==='mermaid'?'<pre data-real-mermaid>'+esc(match[2])+'</pre>':'<pre class="case-source"><code>'+esc(match[2])+'</code></pre>';end=match.index+match[0].length}return html+render(text.slice(end))}
  async function diagrams(host){const elements=[...host.querySelectorAll('[data-real-mermaid]')];if(!elements.length)return;try{const mermaid=(await import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')).default;mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'strict',flowchart:{htmlLabels:false}});for(const el of elements){const svg=await mermaid.render('real-'+crypto.randomUUID(),el.textContent);if(el.isConnected)el.innerHTML=svg.svg}}catch{}}
  async function extract(file){const token=await(await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'}})).json();const response=await fetch('/api/preparation/extract?name='+encodeURIComponent(file.name),{method:'POST',headers:{'X-Makora-Token':token.result.token},body:file});const result=await response.json();if(!response.ok)throw Error(result.error?.message||'Не удалось прочитать файл');return result.result.text}
  const root=()=>document.querySelector('#first-stage');
  function error(message){const host=root()?.querySelector('.board-content');if(host){let el=host.querySelector('[data-real-error]');if(!el){el=document.createElement('p');el.dataset.realError='';el.setAttribute('role','alert');host.prepend(el)}el.textContent=message}}
  async function start(brief){state=await api('/api/preparation/1/start',{brief});stage=1;file=null}
  function schedule(){clearTimeout(timer);if(stage<=4&&['running','unconfirmed'].includes(state.stages[stage]?.status)){timer=setTimeout(async()=>{try{state=await api(`/api/preparation/${stage}/refresh`,{});paint()}catch(e){error(e.message);schedule()}},4000)}}
  function paint(){
    const scene=root();if(!scene||!state.brief)return;
    const board=scene.querySelector('.board'),content=scene.querySelector('.board-content');
    window.makoraRealAgents?.cancel?.();
    board.classList.remove('idea-board','plan-index-board','revision-view');board.classList.add('workspace-board');
    board.classList.toggle('agent-real-mode',stage>=5);
    scene.querySelector('.board-kicker').textContent='ПРОЕКТ · GPT-6 LUNA';
    scene.querySelector('.board-bar h2').textContent=names[stage-1];scene.querySelector('.board-heading span:first-child').textContent=String(stage).padStart(2,'0')+' / '+names[stage-1];scene.querySelector('.board-footer span:last-child').textContent=String(stage).padStart(2,'0')+' / 06';
    scene.querySelector('.scene-bottom p').textContent='Реальные артефакты проекта · результаты требуют вашего утверждения';
    scene.querySelector('.board-next').hidden=true;
    const nav=scene.querySelector('.board-stages')||scene.querySelector('[data-board-stage]')?.parentElement;
    if(nav){nav.innerHTML=names.map((name,i)=>`<button type="button" data-real-stage="${i+1}" class="${stage===i+1?'active':''}" ${i===0||(i<5?state.stages[i]?.status==='approved':state.prototype?.status==='approved')?'':'disabled'} title="${name}">${String(i+1).padStart(2,'0')}<span>${['Анализ','Идея','План','Моки','Прототип','Агенты'][i]}</span></button>`).join('')}
    scene.querySelectorAll('[data-real-stage]').forEach(b=>b.onclick=()=>open(Number(b.dataset.realStage)).catch(e=>error(e.message)));
    scene.querySelectorAll('.capabilities-toggle,.capabilities-menu').forEach(el=>el.hidden=true);
    if(stage>=5){development(content,board);return}
    const projectKey='makora.real-feedbacks.'+(state.projectId||'current');if(feedbackProject!==projectKey){feedbackProject=projectKey;try{feedbacks=JSON.parse(localStorage.getItem(projectKey))||{}}catch{feedbacks={}}}
    const record=state.stages[stage],files=record?.files||{},status=record?.status||'not_started';
    const labels={running:'Codex выполняет этап',launching:'Запрос отправляется',unconfirmed:'Доставка или завершение не подтверждены',review:'Готово к проверке',approved:'Утверждено',failed:'Ошибка',stale:'Требует обновления',not_started:'Ещё не выполнялся'};
    content.innerHTML=`<div class="board-document">${stage===1?`<details><summary>Исходное условие проекта</summary><textarea data-real-brief>${esc(state.brief)}</textarea><button type="button" data-real-new-brief ${['running','launching','unconfirmed'].includes(status)?'disabled':''}>Изменить условие и повторить анализ</button></details>`:''}<p>${esc(labels[status]||status)}</p>${record?.threadId?`<details><summary>Сессия GPT-6 Luna</summary><p>Thread: ${esc(record.threadId)}<br>Turn: ${esc(record.turnId)}</p></details>`:''}<p data-real-error role="alert">${esc(record?.error?JSON.stringify(record.error):'')}</p>${Object.keys(files).map(path=>`<button type="button" class="doc-row" data-real-file="${esc(path)}">${esc(path)} ↗</button>`).join('')}<div data-real-document></div>${(record?.checks||[]).map(c=>`<p>${c.status==='passed'?'✓':'×'} ${esc(c.name)}</p>`).join('')}${record?.questions?.length?`<h3>Вопросы</h3><ul>${record.questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul>`:''}${record?.limitations?.length?`<h3>Ограничения</h3><ul>${record.limitations.map(q=>`<li>${esc(q)}</li>`).join('')}</ul>`:''}<p>Исполняемые тесты приложения выполняются во время разработки. Проверки этого этапа касаются только артефактов.</p><label>Уточнения и изменения<textarea data-real-feedback placeholder="Ответы на вопросы или что необходимо изменить"></textarea></label><button type="button" data-real-run ${['running','launching','unconfirmed'].includes(status)?'disabled':''}>${record?'Пересоздать с уточнениями':'Выполнить этап'}</button>${status==='review'?'<button type="button" data-real-approve>Утвердить результат</button>':''}${['running','unconfirmed','failed'].includes(status)?'<button type="button" data-real-refresh>Проверить состояние</button>':''}<div data-real-approvals></div></div>`;
    const display=path=>{file=path;const target=content.querySelector('[data-real-document]');target.innerHTML=`<h3>${esc(path)}</h3>`+(/\.md$/i.test(path)&&typeof render==='function'?markdown(files[path]):`<pre class="case-source">${esc(files[path])}</pre>`);diagrams(target)};
    content.querySelectorAll('[data-real-file]').forEach(b=>b.onclick=()=>display(b.dataset.realFile));if(file&&files[file])display(file);
    content.querySelector('[data-real-new-brief]')?.addEventListener('click',()=>action(async()=>{const brief=content.querySelector('[data-real-brief]').value;state=await api('/api/preparation/1/start',{brief});window.makoraProject.setSource({name:'Условие проекта',text:brief});file=null;paint()}));
    const feedback=content.querySelector('[data-real-feedback]');feedback.value=feedbacks[stage]||'';feedback.oninput=()=>{feedbacks[stage]=feedback.value;localStorage.setItem(projectKey,JSON.stringify(feedbacks))};
    content.querySelector('[data-real-run]').onclick=()=>action(async()=>{state=await api(`/api/preparation/${stage}/start`,{feedback:feedbacks[stage]||''});file=null;paint()});
    content.querySelector('[data-real-approve]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${stage}/approve`,{note:feedbacks[stage]||''});await open(stage+1)}));
    content.querySelector('[data-real-refresh]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${stage}/refresh`,{});paint()}));
    approvals(content);schedule();
  }
  async function action(fn){if(busy)return;busy=true;try{await fn()}catch(e){error(e.message)}finally{busy=false}}
  async function approvals(content){try{const list=await api('/api/agents/approvals');if(!content.isConnected)return;const host=content.querySelector('[data-real-approvals]');if(!host)return;host.innerHTML=list.map(item=>`<details><summary>Codex запрашивает разрешение</summary><pre>${esc(JSON.stringify(item.params,null,2))}</pre><button data-prep-approval="${esc(item.requestId)}" data-choice="accept">Разрешить</button><button data-prep-approval="${esc(item.requestId)}" data-choice="decline">Отклонить</button></details>`).join('');host.querySelectorAll('[data-prep-approval]').forEach(b=>b.onclick=()=>action(async()=>{await api(`/api/agents/approvals/${b.dataset.prepApproval}`,{decision:b.dataset.choice});paint()}))}catch(e){error(e.message)}}
  async function development(content,board){
    const ticket=++generation;
    if(state.stages['4']?.status!=='approved'){content.innerHTML='<div class="board-document"><p>Сначала выполни и утверди подготовку мок-данных.</p></div>';return}
    content.innerHTML='<div class="board-document"><p>Подготавливаем отдельный Git-проект по утверждённым файлам…</p></div>';
    try{const project=await api('/api/preparation/development',{stage});if(ticket!==generation||stage<5)return;
      if(stage===6&&state.prototype?.status!=='approved'){throw Error('Сначала утверди работающий прототип на этапе 5.')}
      if(!window.makoraRealAgents){await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='agent-runtime-ui.js?v=real-preparation';script.onload=resolve;script.onerror=reject;document.head.append(script)})}
      if(stage===6&&localStorage.getItem('makora.real-stage6-base')!==state.prototype.commit){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-stage6-base',state.prototype.commit)}
      const previousDigest=localStorage.getItem('makora.real-development-digest');if(previousDigest!==project.digest){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-development-digest',project.digest)}
      project.brief+=stage===5?'\nСоздай работающий прототип на исходных mocks/fixtures/. Сохрани mocks/, изменения предлагай в new_mocks/.':'\nПродолжи разработку текущего проекта по утверждённым требованиям.';
      const ctx={board,content,project,preparationStage:stage,approvePrototype:()=>action(async()=>{state=await api('/api/preparation/prototype/approve',{});await open(6)}),status:document.createElement('span'),primary:null,workflow:{getTasks:()=>[]},announce:error};
      await window.makoraRealAgents.render(ctx);
      if(ticket!==generation)return;

    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function open(number){generation++;clearTimeout(timer);root()?.querySelectorAll('.board-content button,.board-content textarea,.board-content input').forEach(el=>el.disabled=true);stage=Math.max(1,Math.min(6,number));file=null;localStorage.setItem('makora.real-stage',String(stage));state=await api('/api/preparation');paint()}
  async function mount(){state=await api('/api/preparation');if(!state.brief)return;stage=Number(localStorage.getItem('makora.real-stage'))||1;paint()}
  window.makoraPreparation={start,mount,open,extract};
})();

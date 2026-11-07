/* Real artifact pipeline. No example documents are used by this controller. */
(() => {
  let state={brief:'',stages:{}}, stage=null, file=null, timer=0, busy=false, generation=0, feedbacks={}, feedbackProject=null;
  let analysisMotion={key:null,started:0};
  const names=['Простое объяснение','Анализ задания','Разбор аналогов','Разработка идеи','Планирование','Мок-данные','Пакет для агента','Разработка агентами'];
  const purposes=['Коротко объясним, что нужно сделать и показать, на понятном примере.','Разберём условие: что сделать, какие есть ограничения и как будут оценивать.','Найдём похожие продукты и покажем, какие идеи подойдут для нашего проекта.','Исследуем проблему и выберем идею, которая отвечает требованиям задания.','Определим устройство продукта, контракты, проверки и задачи для разработки.','Подготовим данные для разработки и проверим их по схемам и сценариям.','Соберём работающий прототип из согласованных материалов и моков.','Разовьём утверждённый прототип с помощью агентов и проверяемых задач.'];
  const fileNames={'00_brief_explanation.md':'Простое объяснение','02_competitors.md':'Сравнение конкурентов','02_competitors.json':'Конкуренты и источники','01_case_analysis.md':'Разбор задания','02_research.md':'Исследование проблемы','02_solution_concept.md':'Концепция решения','02_user_flow.mmd':'Путь пользователя','02_task_flow.mmd':'Сценарий действий','03_architecture.md':'Архитектура продукта','03_test_plan.md':'План тестирования','03_tasks.json':'Задачи для агентов','04_validation_report.md':'Отчёт о готовности данных'};
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
  function inline(x){return esc(x).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/\*(.+?)\*/g,'<em>$1</em>').replace(/`([^`]+)`/g,'<code>$1</code>')}
  function renderMarkdownBlocks(md){return md.replace(/^(#{1,3}[ \t]+[^\n]+)$/gm,'\n\n$1\n\n').trim().split(/\n\s*\n/).map(b=>{if(/^#{1,3} /m.test(b))return b.split('\n').map(l=>{let m=l.match(/^(#{1,3}) (.*)/);return m?`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`:inline(l)}).join('');if(/^>/.test(b))return `<blockquote>${b.replace(/^> ?/gm,'').split('\n').map(inline).join('<br>')}</blockquote>`;if(/^\|/.test(b)){let rows=b.split('\n').filter(l=>!/^\|\s*:?-+/.test(l)).map(l=>l.split('|').slice(1,-1));return `<div class="md-table-wrap"><table><thead><tr>${rows[0].map(c=>`<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(r=>`<tr>${r.map(c=>`<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}if(/^[-*] /m.test(b))return `<ul>${b.split('\n').filter(l=>/^[-*] /.test(l)).map(l=>`<li>${inline(l.slice(2))}</li>`).join('')}</ul>`;if(/^\d+\. /m.test(b))return `<ol>${b.split('\n').filter(l=>/^\d+\. /.test(l)).map(l=>`<li>${inline(l.replace(/^\d+\. /,''))}</li>`).join('')}</ol>`;return `<p>${b.split('\n').map(inline).join('<br>')}</p>`}).join('')}
  function markdown(text){let html='',end=0;for(const match of text.matchAll(/```([^\n]*)\n([\s\S]*?)```/g)){html+=renderMarkdownBlocks(text.slice(end,match.index));html+=match[1].trim()==='mermaid'?'<pre data-real-mermaid>'+esc(match[2])+'</pre>':'<pre class="case-source"><code>'+esc(match[2])+'</code></pre>';end=match.index+match[0].length}return html+renderMarkdownBlocks(text.slice(end))}
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
  async function start(brief,sourceFile){
    if(sourceFile)await uploadSource(sourceFile);
    return api('/api/preparation/0/start',{brief,openInCodex:true});
  }
  const stageStatusNames={complete:'Готово',continued:'Продолжили',running:'В работе',available:'Доступно',locked:'Закрыто',idea:'Ждёт вашу идею'};
  const pendingStatuses=['running','unconfirmed','stopping'];
  function schedule(){
    clearTimeout(timer);
    const pending=Object.keys(state.stages).find(key=>{
      const record=state.stages[key];
      return (pendingStatuses.includes(record.status)||record.status==='awaiting_idea')||(record.status==='failed'&&record.agentStatus==='failed');
    });
    if(pending===undefined)return;
    timer=setTimeout(async()=>{
      const currentGeneration=generation;
      try{
        const snapshot=await api(`/api/preparation/${pending}/refresh`,{});
        if(currentGeneration===generation){
          state=snapshot;
          if(stage===Number(pending)||stage===null)paint();
        }
      }catch(e){
        if(stage===Number(pending))error(e.message);
      }
      schedule();
    },4000);
  }
  function isUnlocked(number){
    const checkedThrough=Math.min(number-1,5);
    for(let previous=1;previous<=checkedThrough;previous++){
      if(state.stages[previous]?.status!=='approved'&&!(previous===2&&state.stages[previous]?.status==='continued'))return false;
    }
    return number<7||state.prototype?.status==='approved'||state.returnedProject?.status==='prepared';
  }
  function stageStatus(index){
    const record=state.stages[index];
    const complete=index===0?['review','approved'].includes(record?.status):index<=5
      ?record?.status==='approved':index===6&&(state.prototype?.status==='approved'||state.returnedProject?.status==='prepared');
    if(index===2&&record?.status==='continued')return 'continued';
    if(complete)return 'complete';
    if(record?.status==='awaiting_idea')return 'idea';
    if(pendingStatuses.includes(record?.status))return 'running';
    return isUnlocked(index)?'available':'locked';
  }
  function paintStageNavigation(){
    const navigation=root().querySelector('.stage-navigation');
    for(const button of navigation.querySelectorAll('button')){
      const index=Number(button.dataset.stageJump),status=stageStatus(index);
      button.dataset.status=status;
      button.querySelector('.stage-nav-status').textContent=stageStatusNames[status];
      if(index===stage)button.setAttribute('aria-current','step');
      else button.removeAttribute('aria-current');
    }
  }
  function paintGrid(){
    const grid=root().querySelector('.stage-grid');
    const focused=grid.contains(document.activeElement)?document.activeElement.dataset.realStage:null;
    grid.innerHTML=names.map((name,index)=>{
      const status=stageStatus(index);
      return `<button type="button" data-real-stage="${index}" data-status="${status}">
        <span class="stage-tile-number">${String(index+1).padStart(2,'0')}</span>
        <span class="stage-tile-copy"><span class="stage-tile-name">${name}</span><span class="stage-tile-status">${stageStatusNames[status]}</span></span>
        <span class="stage-tile-mark" aria-hidden="true">${status==='complete'?'✓':'↗'}</span>
      </button>`;
    }).join('');
    grid.querySelectorAll('button').forEach(button=>button.onclick=()=>open(Number(button.dataset.realStage)));
    if(focused!==null)grid.querySelector(`[data-real-stage="${focused}"]`)?.focus();
  }
  function paint(){
    const scene=root();if(!scene||!state.brief)return;
    const board=scene.querySelector('.board'),content=scene.querySelector('.board-content');
    window.makoraRealAgents?.cancel?.();
    if(stage!==7)window.makoraCodingAgents?.hide();
    if(stage===null){paintGrid();return}
    paintStageNavigation();
    board.dataset.stage=stage;
    board.classList.toggle('agent-real-mode',stage>=6);
    scene.querySelector('.board-kicker').textContent=`ЭТАП ${String(stage+1).padStart(2,'0')} / 08`;
    scene.querySelector('.board-bar h2').textContent=names[stage];
    scene.querySelector('[data-stage-model]')?.remove();
    scene.querySelector('[data-workflow-notice]')?.remove();
    if(state.workflowNotice){
      const notice=document.createElement('p');
      notice.dataset.workflowNotice='';
      notice.textContent=state.workflowNotice;
      notice.setAttribute('role','status');
      if(state.legacyChoiceAvailable){
        const keep=document.createElement('button');
        keep.className='rp-text-button';
        keep.textContent='Сохранить согласования старого проекта';
        keep.onclick=()=>action(async()=>{
          state=await api('/api/preparation/workflow/preserve-legacy',{confirm:true});
          await open(state.lastStage);
        });
        notice.append(keep);
      }
      scene.querySelector('.board-bar').after(notice);
    }
    content.scrollTop=0;
    if(!isUnlocked(stage)){
      const next=names.findIndex((_,index)=>index>0&&state.stages[index]?.status!=='approved');
      const required=next>0&&next<=5?next:6;
      content.innerHTML=`<div class="stage-locked"><p>Сначала завершите этап ${String(required+1).padStart(2,'0')} «${names[required]}».</p><button type="button" class="rp-secondary" data-open-required>Открыть этап ${String(required+1).padStart(2,'0')} →</button></div>`;
      content.querySelector('[data-open-required]').onclick=()=>open(required);
      return;
    }
    const projectKey='makora.real-feedbacks.v2.'+(state.projectId||'current');if(feedbackProject!==projectKey){feedbackProject=projectKey;try{feedbacks=JSON.parse(localStorage.getItem(projectKey))||{}}catch{feedbacks={}}}
    if(stage===6){window.makoraModelStatus?.external();handoffView(content,board);return}
    if(stage===7){window.makoraModelStatus?.agents([]);development(content,board);return}
    const record=state.stages[stage],files=record?.files||{},status=record?.status||'not_started';
    window.makoraModelStatus?.preparation(record);
    if(stage===3&&(!record||(record.interactionMode==='user_idea'&&['launching','running','awaiting_idea','unconfirmed'].includes(status)))){
      ideaView(content,record);
      schedule();
      return;
    }

    const working=['running','launching','stopping'].includes(status);
    artifactView(scene,board,content,record,files,status,working,projectKey);
  }
  function artifactView(scene,board,content,record,files,status,working,projectKey){
    const step=stage,paths=Object.keys(files),main=paths.find(p=>/\.md$/.test(p))||paths[0];
    const expected=['00_brief_explanation.md','01_case_analysis.md','02_competitors.md','02_solution_concept.md','03_architecture.md','04_validation_report.md'][step];
    const ready=['review','approved'].includes(status)&&paths.length>0;
    const competitors=step===2?readCompetitors(files['02_competitors.json']):[];
    const hasComparison=competitors.length>0;
    const approve=()=>action(async()=>{
      if(status!=='approved'){
        const payload=step===2?competitorApproval(competitors):{note:feedbacks[step]||''};
        if(!payload)return;
        state=await api(`/api/preparation/${step}/approve`,payload);
      }
      file=null;
      if(step===2)await beginIdea();else await open(step+1);
    });
    const threadId=record?.threadId;
    const chatLink=threadId&&/^[0-9a-f-]{36}$/i.test(threadId)
      ? `<a class="rp-thread-link" href="codex://threads/${threadId}">Чат в Codex ↗</a>`
      : '';
    const motionKey=step;
    if(working&&analysisMotion.key!==motionKey)analysisMotion={key:motionKey,started:performance.now()};
    if(!working)analysisMotion.key=null;
    const wheelDelay=working?-((performance.now()-analysisMotion.started)/1000):0;
    const go=()=>step===2?action(beginIdea):open(step+1);
    content.innerHTML=`<div class="board-document rp-workspace analysis-summary" data-phase="${esc(status)}">
      ${step!==0&&step!==2&&(record?.filesystemIsolation==='windows-compatible-read'||/Win/i.test(navigator.platform))?'<p role="note">Windows: запись ограничена рабочей областью; полная изоляция чтения вне проекта не гарантируется.</p>':''}
      ${working?`<div class="analysis-thinking" role="status"><img src="analysis-wheel.png" alt="" class="analysis-wheel" style="animation-delay:${wheelDelay}s"><p>${status==='stopping'?'Останавливаем сессию…':step===2?'Ищем аналоги и проверяем источники…':'Составляются материалы этапа'}</p><small>${esc(expected)}${record?.lastCheckedAt?' · проверено '+esc(new Date(record.lastCheckedAt).toLocaleTimeString()):''}</small>${record?.sessionId||chatLink?`<div class="analysis-actions">${record?.sessionId?`<button class="rp-secondary" data-real-cancel ${status==='stopping'?'disabled':''}>Остановить</button>`:''}${chatLink}</div>`:''}</div>`:`${!hasComparison&&(step!==0||!ready)?`<p class="analysis-purpose">${ready?'Материалы подготовлены. ':''}${esc(purposes[step])}</p>`:''}
      ${main&&step!==0?`<button class="analysis-file" data-real-file="${esc(main)}"><span class="analysis-file-mark">${paths.length===1?'MD':'▤'}</span><span><strong>${paths.length===1?esc(fileTitle(main)):'Материалы этапа'}</strong><small>${paths.length===1?esc(main):paths.length+' файлов · документы, схемы и данные'}</small></span><span aria-hidden="true">↗</span></button>`:''}
      ${step===0&&ready&&main?`<section class="brief-explanation">${markdown(files[main].replace(/^#[ \t]+Простое объяснение[^\S\n]*\n+/i,''))}</section>`:''}
      ${status==='unconfirmed'?`<p role="status">Ответ агента пока не подтверждён. Проверьте состояние; повторная отправка не выполняется.</p>${record?.sessionId?'<button class="rp-secondary" data-real-cancel>Остановить сессию</button>':''}`:''}

      ${record?.skillManifest?.length?`<details><summary>Навыки и проверки выполнения</summary><ul>${record.skillManifest.map(skill=>`<li>${esc(skill.name)} · версия ${esc((skill.packageSha256||skill.sha256||'').slice(0,12))}</li>`).join('')}</ul><p>${record.nativeSkillStatus==='accepted'?'API подтвердил приём навыков.':'Подключение навыков ещё не подтверждено.'} ${record.methodologyStatus==='structure_checked'?'Структурные проверки выполнены; это не доказательство полноты методики.':'Результат методических проверок ещё не получен.'}</p></details>`:''}
      ${record?.error&&hasComparison?`<details class="competitor-checks"><summary>Что не прошло проверку</summary><p>${esc(record.error)}</p></details>`:record?.error?`<p data-real-error role="alert">${esc(typeof record.error==='string'?record.error:'Не удалось выполнить запрос агента. Проверьте состояние.')}</p>`:''}
      <div class="analysis-actions"><button class="rp-secondary" data-analysis-edit ${status==='unconfirmed'?'disabled':''} ${!record?'data-real-run':''}>${record?'Пересоздать с уточнениями':step===0?'Объяснить задание →':'Начать анализ →'}</button>${ready?`<button class="rp-primary" ${step===0||status==='approved'?'data-real-next':'data-real-approve'}>${step===4?(status==='approved'?'К мок-данным →':'Утвердить весь план →'):step===0?'К анализу задания →':step===2?'Перейти к идее →':'Продолжить →'}</button>`:''}${['failed','unconfirmed'].includes(status)?'<button class="rp-text-button" data-real-refresh>Проверить состояние ↻</button>':''}${chatLink}</div>`}
      <div data-real-approvals></div></div><article class="analysis-reader" data-real-document data-phase="${esc(status)}" hidden></article>`;
    const show=path=>{
      if(!files[path])return;file=path;content.querySelector('.analysis-summary').hidden=true;
      const doc=content.querySelector('[data-real-document]');doc.hidden=false;
      const checks=record?.checks||[],questions=record?.questions||[],limits=record?.limitations||[];
      doc.innerHTML=`<header class="analysis-reader-header"><button class="rp-text-button" data-analysis-close data-rp-back>← К результату</button><span>${String(step+1).padStart(2,'0')} / ${esc(names[step])}</span><a download="${esc(path.split('/').pop())}">Скачать файл ↓</a></header><div class="artifact-reader-layout"><aside class="artifact-files" aria-label="Файлы этапа">${paths.map(p=>`<button data-real-file="${esc(p)}" class="${p===path?'active':''}" ${p===path?'aria-current="page"':''}><strong>${esc(fileTitle(p))}</strong><small>${esc(p)}</small></button>`).join('')}${checks.length?`<details class="artifact-checks"><summary>Проверки · ${checks.filter(c=>c.status==='passed').length}/${checks.length}</summary>${checks.map(c=>`<p>${c.status==='passed'?'✓':c.status==='not_checked'?'?':'×'} ${esc(c.name)}${c.detail?`<br><small>${esc(c.detail)}</small>`:''}</p>`).join('')}<small>Проверки артефактов. Тесты приложения выполняются при разработке.</small></details>`:''}${record?.requirementCoverage?.length?`<details><summary>Покрытие требований</summary>${record.requirementCoverage.map(row=>`<p>${esc(row.requirementId)} · ${esc(row.disposition)} · ${esc(row.reason||(row.artifacts||[]).join(', '))}</p>`).join('')}</details>`:''}${questions.length?`<details><summary>Открытые вопросы · ${questions.length}</summary><ul>${questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}${limits.length?`<details><summary>Ограничения · ${limits.length}</summary><ul>${limits.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></details>`:''}</aside><div class="analysis-paper"><p class="analysis-filename">${esc(path)}</p>${/\.md$/i.test(path)?markdown(files[path]):/\.mmd$/i.test(path)?markdown('```mermaid\n'+files[path]+'\n```'):`<h1>${esc(fileTitle(path))}</h1><pre class="case-source"><code>${esc(files[path])}</code></pre>`}</div></div>${ready?`<footer class="artifact-approval"><div><strong>${status==='approved'?'Этап уже утверждён':step===4?'Подтверждение плана разработки':'Подтверждение результата'}</strong><p>${status==='approved'?'Материалы сохранены и доступны следующему этапу.':`Утверждение относится ко всем ${paths.length} файлам этапа. Каждый файл отдельно подтверждать не нужно.`}</p></div><div><button class="rp-secondary" data-reader-edit>Нужны правки</button><button class="rp-primary" data-reader-approve>${status==='approved'?'Перейти дальше →':step===4?'Утвердить весь план →':'Утвердить и продолжить →'}</button></div></footer>`:''}`;
      if(step===2&&!ready){
        const footer=document.createElement('footer');
        footer.className='artifact-approval';
        footer.innerHTML='<div><strong>Готовы обсудить свою идею?</strong><p>Можно продолжить с текущим разбором аналогов.</p></div><button type="button" data-reader-idea>Перейти к этапу 04 →</button>';
        footer.querySelector('button').onclick=()=>action(beginIdea);
        doc.append(footer);
      }
      doc.querySelector('[data-reader-approve]')?.addEventListener('click',step===2?()=>action(beginIdea):approve);
      if(step===2&&doc.querySelector('[data-reader-approve]'))doc.querySelector('[data-reader-approve]').textContent='Перейти к этапу 04 →';
      doc.querySelector('[data-reader-edit]')?.addEventListener('click',()=>{file=null;paint();root()?.querySelector('[data-analysis-edit]')?.click()});
      if(doc.dataset.downloadUrl)URL.revokeObjectURL(doc.dataset.downloadUrl);doc.dataset.downloadUrl=URL.createObjectURL(new Blob([files[path]],{type:'text/plain;charset=utf-8'}));doc.querySelector('a[download]').href=doc.dataset.downloadUrl;
      doc.querySelectorAll('[data-real-file]').forEach(b=>b.onclick=()=>show(b.dataset.realFile));
      doc.querySelector('[data-analysis-close]').onclick=()=>{file=null;paint();};
      diagrams(doc);content.scrollTop=0;
    };
    content.querySelector('[data-real-file]')?.addEventListener('click',()=>{show(main)});
    if(file&&files[file])show(file);
    content.querySelector('[data-analysis-edit]')?.addEventListener('click',()=>{
      const regenerate=feedback=>action(async()=>{window.makoraModelStatus?.preparation({status:'dispatching'});artifactView(scene,board,content,record,{},'launching',true,projectKey);try{state=await api(`/api/preparation/${step}/start`,{feedback,openInCodex:true});file=null;root()?.querySelector('.analysis-chat')?.remove();paint()}catch(e){try{state=await api('/api/preparation')}catch{}paint();throw e}});
      if(!record){regenerate(feedbacks[step]||'');return}
      openRefinementChat({key:projectKey,step,title:step===2?'Какие аналоги искать?':'Какие правки внесём?',description:step===2?'Укажи, какие продукты добавить или что проверить в найденных аналогах.':`Расскажи, что поправить: ${names[step].toLowerCase()}. Я обновлю материалы этапа.`,submit:step===2?'Обновить поиск →':'Пересоздать материалы →',onSubmit:regenerate});
    });
    content.querySelector('[data-real-approve]')?.addEventListener('click',approve);
    content.querySelector('[data-real-next]')?.addEventListener('click',go);
    content.querySelector('[data-real-refresh]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/refresh`,{});paint()}));
    if(step===2&&!working)competitorView(content,record,competitors,projectKey);
    content.querySelector('[data-real-cancel]')?.addEventListener('click',()=>action(async()=>{state=await api(`/api/preparation/${step}/cancel`,{});paint()}));
    approvals(content);schedule();
  }
  const competitorActions={borrow:'Взять идею',adapt:'Переделать под нас',avoid:'Пропустить',research:'Изучить ещё'};
  async function beginIdea(){
    const decisions={...state.competitorDecisions,...feedbacks.competitorDecisions};
    state=await api('/api/preparation/idea/start',{openInCodex:true,decisions,note:feedbacks.competitorDecision||''});
    file=null;
    await open(3);
  }
  function ideaView(content,record){
    const threadId=record?.threadId;
    const linked=threadId&&/^[0-9a-f-]{36}$/i.test(threadId);
    content.innerHTML=`<section class="idea-handoff">
      <span class="idea-handoff-mark" aria-hidden="true">✳</span>
      <h3>${record?'Расскажите свою идею в Codex':'Сформулируем вашу идею'}</h3>
      <p>${record?'В отдельный чат отправлено задание выслушать вашу задумку и помочь её уточнить. Перейдите туда и напишите, что хотите создать.':'Создадим чат, где ИИ сначала выслушает вашу задумку и поможет оформить её.'}</p>
      <ol><li>Расскажите, для кого продукт и какую задачу он решает.</li><li>Опишите, что хотите показать в демоверсии.</li><li>Обсудите детали и попросите ИИ оформить согласованную идею.</li></ol>
      <div class="analysis-actions">${linked?`<a class="rp-primary idea-codex-link" href="codex://threads/${threadId}">Открыть чат идеи в Codex ↗</a>`:record?'<p role="status">Ожидаем подтверждение чата…</p>':'<button class="rp-primary" data-create-idea>Создать чат в Codex →</button>'}
      ${record?'<button class="rp-secondary" data-check-idea>Проверить готовность документов</button>':''}</div>
      ${record?'<small role="status">Документы появятся здесь после оформления идеи в Codex.</small>':''}
    </section>`;
    content.querySelector('[data-create-idea]')?.addEventListener('click',()=>action(beginIdea));
    content.querySelector('[data-check-idea]')?.addEventListener('click',()=>action(async()=>{
      state=await api('/api/preparation/3/refresh',{});paint();
    }));
  }
  function readCompetitors(text){
    if(!text)return [];
    try{
      const {competitors}=JSON.parse(text);
      return Array.isArray(competitors)?competitors:[];
    }catch{return []}
  }
  function competitorApproval(competitors){
    const saved={...state.competitorDecisions,...feedbacks.competitorDecisions};
    const missing=competitors.find(({id})=>!Object.hasOwn(competitorActions,saved[id]?.action));
    if(missing){
      if(file){file=null;paint()}
      const choice=[...root().querySelectorAll('[data-competitor-choice]')].find(select=>select.dataset.competitorChoice===missing.id);
      choice?.reportValidity();
      return null;
    }
    const decisions=Object.fromEntries(competitors.map(({id})=>[id,saved[id]]));
    const note=feedbacks.competitorDecision?.trim()||competitors.map(({id,name})=>{
      const {action,comment}=decisions[id];
      return `${name} — ${competitorActions[action]}${comment?.trim()?'. '+comment.trim():''}`;
    }).join('\n');
    return {note,decisions};
  }
  function competitorLink(value,label){
    try{
      const url=new URL(value);
      if(['https:','http:'].includes(url.protocol)&&!url.username&&!url.password){
        return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;
      }
    }catch{}
    return esc(label);
  }
  function competitorView(content,record,competitors,projectKey){
    const summary=content.querySelector('.analysis-summary'),edit=summary.querySelector('[data-analysis-edit]');
    if(edit)edit.textContent=record?'Уточнить поиск':'Найти аналоги →';
    if(!competitors.length||record?.status==='unconfirmed')return;
    const editable=record.status==='review';
    const decisions=editable?{...state.competitorDecisions,...feedbacks.competitorDecisions}:state.competitorDecisions||{};
    const panel=document.createElement('section');
    panel.className='competitor-review';
    panel.setAttribute('aria-labelledby','competitor-heading');
    panel.innerHTML=`
      <header class="competitor-intro">
        <h3 id="competitor-heading">Что нашли</h3>
        ${editable?'<p>Выбери, что делать с каждым аналогом. Решения попадут в следующий этап.</p>':''}
        ${record.status==='failed'?'<p role="status">Часть материалов ещё не прошла проверку. Можно посмотреть найденное и уточнить поиск.</p>':''}
      </header>
      ${competitors.map((item,index)=>{
        const {id,name,summary:description,ideasToBorrow=[],comparison=[],sources=[]}=item;
        const confirmed=sources.filter(ref=>(record.sourceEvidence||[]).some(source=>source.status==='passed'&&source.url===ref.url&&(source.quote||'')===(ref.quote||''))).length;
        const sourceStatus=confirmed===0?'Источники пока не подтверждены':confirmed===sources.length?'Источники подтверждены':`Подтверждено источников ${confirmed} из ${sources.length}`;
        const decision=decisions[id];
        return `<article class="competitor-card" aria-labelledby="analog-title-${index}">
          <header><span class="competitor-index" aria-hidden="true">${String(index+1).padStart(2,'0')}</span><h4 id="analog-title-${index}">${esc(name)}</h4></header>
          ${description?`<p>${esc(description)}</p>`:''}
          ${ideasToBorrow.length?`<div class="competitor-idea"><strong>Что можно взять</strong><ul>${ideasToBorrow.map(idea=>`<li>${esc(idea)}</li>`).join('')}</ul></div>`:''}
          ${editable?`<label class="competitor-choice" for="analog-choice-${index}">Наше решение
            <select id="analog-choice-${index}" aria-describedby="analog-title-${index}" data-competitor-choice="${esc(id)}" required>
              <option value="">Выбери вариант</option>
              ${Object.entries(competitorActions).map(([value,label])=>`<option value="${value}" ${decision?.action===value?'selected':''}>${label}</option>`).join('')}
            </select>
          </label>`:decision?`<p><strong>Наше решение</strong> · ${esc(competitorActions[decision.action])}</p>`:''}
          <details>
            <summary>Сравнение и источники</summary>
            <dl class="competitor-comparison">${comparison.map(row=>`<div><dt>${esc(row.criterion)}</dt><dd><b>У аналога</b> ${esc(row.theirs)}</dd><dd><b>У нас</b> ${esc(row.ours)}</dd></div>`).join('')}</dl>
            <p class="competitor-source-status">${sourceStatus}</p>
            <ul class="competitor-sources">${sources.map(source=>`<li>${competitorLink(source.url,source.title||source.url)}</li>`).join('')}</ul>
            <p>${competitorLink(item.url,'Открыть сайт аналога')}</p>
          </details>
          ${editable?`<details class="competitor-comment">
            <summary>${decision?.comment?'Комментарий':'Добавить комментарий'}</summary>
            <label class="sr-only" for="analog-note-${index}">Комментарий к аналогу ${esc(name)}</label>
            <textarea id="analog-note-${index}" rows="2" data-competitor-note="${esc(id)}">${esc(decision?.comment||'')}</textarea>
          </details>`:decision?.comment?`<p>${esc(decision.comment)}</p>`:''}
        </article>`;
      }).join('')}
      ${editable?`<details class="competitor-comment"><summary>Общее пожелание к идее</summary><label class="sr-only" for="analog-note-all">Общее пожелание к идее</label><textarea id="analog-note-all" data-competitor-decision rows="2">${esc(feedbacks.competitorDecision||'')}</textarea></details>`:''}
    `;
    const next=document.createElement('section');
    next.className='competitor-next';
    next.innerHTML='<div><strong>Дальше · ваша идея</strong><p>Можете уточнить разбор аналогов или сразу обсудить свою идею с ИИ в Codex.</p></div><div class="analysis-actions"><button type="button" class="rp-primary" data-begin-idea>Перейти к этапу 04 →</button></div>';
    next.querySelector('[data-begin-idea]').onclick=()=>action(beginIdea);
    const actions=next.querySelector('.analysis-actions');
    if(edit){
      edit.textContent='Исправить или уточнить разбор';
      actions.append(edit);
    }
    summary.querySelector('[data-real-approve]')?.remove();
    summary.querySelector('[data-real-next]')?.remove();
    panel.prepend(next);
    summary.prepend(panel);
    if(record.status==='failed'){
      const intro=panel.querySelector('.competitor-intro');
      const checks=summary.querySelector('.competitor-checks');
      if(checks)intro.append(checks);

    }
    const report=summary.querySelector('[data-real-file]');
    if(report){
      report.classList.add('competitor-report');
      report.innerHTML='<span>Открыть полный отчёт</span><span aria-hidden="true">↗</span>';
      summary.append(report);
    }
    const save=()=>localStorage.setItem(projectKey,JSON.stringify(feedbacks));
    panel.querySelectorAll('[data-competitor-choice]').forEach(select=>{
      const note=select.closest('.competitor-card').querySelector('[data-competitor-note]');
      const change=()=>{
        (feedbacks.competitorDecisions||={})[select.dataset.competitorChoice]={action:select.value,comment:note.value};
        save();
      };
      select.onchange=change;
      note.oninput=change;
    });
    const note=panel.querySelector('[data-competitor-decision]');
    if(note)note.oninput=()=>{feedbacks.competitorDecision=note.value;save()};
  }
  function openRefinementChat({key=feedbackProject,step,title,description,submit,onSubmit}){
    window.makoraChat?.close();
    const scene=root();if(!scene)return;
    if(scene.querySelector('.analysis-chat')){scene.querySelector('.analysis-chat textarea').focus();return}
    const chat=document.createElement('form');chat.className='analysis-chat';chat.setAttribute('aria-label','Уточнения Макоре');
    chat.innerHTML=`<div class="speech-label"><span class="analysis-chat-speaker"><i aria-hidden="true"></i> МАКОРА</span><button type="button" aria-label="Закрыть уточнения" data-chat-close>×</button></div><div class="analysis-chat-body"><h3>${esc(title)}</h3><p>${esc(description)}</p><textarea aria-label="Уточнения к этапу" placeholder="Что добавить или исправить?">${esc(feedbacks[step]||'')}</textarea><label class="analysis-attachment"><span aria-hidden="true">＋</span> Файл с уточнениями<input type="file" accept=".pdf,.docx,.txt,.md" hidden></label><small class="analysis-attachment-name" role="status"></small><p class="analysis-chat-error" role="alert"></p></div><button class="rp-primary" type="submit">${esc(submit)}</button>`;
    scene.querySelector('.stage-board').append(chat);chat.querySelector('[data-chat-close]').onclick=()=>chat.remove();
    const input=chat.querySelector('textarea'),button=chat.querySelector('[type=submit]');input.focus();input.oninput=()=>{feedbacks[step]=input.value;localStorage.setItem(key,JSON.stringify(feedbacks))};
    let attached='',reading=false;
    async function attach(f){if(!f)return;reading=true;button.disabled=true;const label=chat.querySelector('.analysis-attachment-name');label.textContent='Читаем файл…';try{attached=await extract(f,true);label.textContent=f.name}catch(e){label.textContent=e.message}finally{reading=false;button.disabled=false}}
    chat.querySelector('input').onchange=e=>attach(e.target.files[0]);chat.ondragover=e=>e.preventDefault();chat.ondrop=e=>{e.preventDefault();attach(e.dataTransfer.files[0])};
    chat.onsubmit=async e=>{e.preventDefault();if(reading||button.disabled)return;const feedback=[input.value,attached].filter(Boolean).join('\n\n');if(!feedback.trim()){input.focus();return}feedbacks[step]=feedback;localStorage.setItem(key,JSON.stringify(feedbacks));button.disabled=true;button.textContent='Отправляем…';try{await onSubmit(feedback)}catch(e){chat.querySelector('.analysis-chat-error').textContent=e.message}finally{if(chat.isConnected){button.disabled=false;button.textContent=submit}}};
  }
  async function action(fn){if(busy)return;busy=true;root()?.querySelector('.board-content')?.setAttribute('aria-busy','true');try{await fn()}catch(e){error(e.message)}finally{busy=false;schedule();root()?.querySelector('.board-content')?.setAttribute('aria-busy','false')}}
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
        doc.querySelector('[data-handoff-back]').onclick=()=>{doc.hidden=true;content.querySelector('.analysis-summary').hidden=false};diagrams(doc);
      };
      content.querySelector('[data-handoff-open]').onclick=()=>{show()};
      content.querySelectorAll('.handoff-download').forEach(a=>a.addEventListener('click',()=>{content.querySelector('.handoff-state').textContent='Пакет передан на скачивание. Прикрепите его внешнему агенту и отправьте промпт.'}));
    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function development(content,board){
    const ticket=++generation;
    if(state.stages['5']?.status!=='approved'){content.innerHTML='<div class="board-document"><p>Сначала выполни и утверди подготовку мок-данных.</p></div>';return}
    content.innerHTML='<div class="board-document"><p>Подготавливаем отдельный Git-проект по утверждённым файлам…</p></div>';
    try{const project=await api('/api/preparation/development',{stage});if(ticket!==generation||stage<6)return;
      if(stage===7&&state.prototype?.status!=='approved'&&state.returnedProject?.status!=='prepared'){throw Error('Сначала утвердите работающий прототип на этапе 7.')}
      if(!window.makoraRealAgents){await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='agent-runtime-ui.js?v=stage-model-41';script.onload=resolve;script.onerror=reject;document.head.append(script)})}
      if(stage===7&&localStorage.getItem('makora.real-agents-base')!==(state.returnedProject?.commit||state.prototype?.commit)){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-agents-base',(state.returnedProject?.commit||state.prototype?.commit))}
      const previousDigest=localStorage.getItem('makora.real-development-digest');if(previousDigest!==project.digest){window.makoraRealAgents.selectRun?.('__new__');localStorage.setItem('makora.real-development-digest',project.digest)}
      project.brief+=stage===6?'\nСоздай работающий прототип на исходных mocks/fixtures/. Сохрани mocks/, изменения предлагай в new_mocks/.':'\nПродолжи разработку текущего проекта по утверждённым требованиям.';
      const ctx={board,content,project,preparationStage:stage,approvePrototype:()=>action(async()=>{state=await api('/api/preparation/prototype/approve',{});await open(7)}),status:document.createElement('span'),primary:null,workflow:{getTasks:()=>[]},announce:error};
      await window.makoraRealAgents.render(ctx);
      if(ticket!==generation)return;

    }catch(e){if(ticket===generation)error(e.message)}
  }
  async function open(number){
    if(!Number.isInteger(number)||!names[number])return;
    const scene=root(),board=scene.querySelector('.stage-board');
    const keepFocus=scene.querySelector('.stage-navigation').contains(document.activeElement);
    const ticket=++generation;
    clearTimeout(timer);
    window.makoraRealAgents?.cancel?.();
    scene.querySelector('.analysis-chat')?.remove();
    scene.querySelector('[data-stage-model]')?.remove();
    scene.querySelector('[data-workflow-notice]')?.remove();
    stage=number;
    file=null;
    delete board.dataset.runtimeView;
    scene.classList.add('stage-open');
    board.dataset.stage=number;
    board.classList.add('expanded','rp-analysis','workspace-board');
    board.setAttribute('aria-labelledby','stage-title');
    board.querySelector('.board-inner').hidden=false;
    board.querySelector('.stage-grid').hidden=true;
    scene.querySelector('.first-top').inert=true;
    const title=board.querySelector('#stage-title');
    title.textContent=names[number];
    board.querySelector('.board-kicker').textContent=`ЭТАП ${String(number+1).padStart(2,'0')} / 08`;
    paintStageNavigation();
    if(!keepFocus)title.focus();
    if(isUnlocked(number)){
      board.querySelector('.board-content').innerHTML='<p role="status">Открываем этап…</p>';
      try{
        const snapshot=await api('/api/preparation/projects/stage',{stage:number});
        if(ticket===generation){state=snapshot;paint()}
      }catch(e){
        if(ticket===generation){paint();error(e.message)}
      }
    }else{
      paint();
    }
    schedule();
  }
  function closeStage(){
    if(stage===null)return;
    const previous=stage,scene=root(),board=scene.querySelector('.stage-board');
    generation++;
    stage=null;
    file=null;
    scene.querySelector('.analysis-chat')?.remove();
    scene.classList.remove('stage-open');
    board.classList.remove('expanded','rp-analysis','workspace-board','agent-real-mode');
    board.removeAttribute('aria-labelledby');
    board.querySelector('.board-inner').hidden=true;
    board.querySelector('.stage-grid').hidden=false;
    scene.querySelector('.first-top').inert=false;
    scene.dispatchEvent(new Event('makora:stage-close'));
    paint();
    board.querySelector(`[data-real-stage="${previous}"]`)?.focus();
    schedule();
  }
  function mount(snapshot){
    state=snapshot;
    stage=null;
    window.makoraModelStatus?.refresh();
    root().querySelector('.stage-board-back').onclick=closeStage;
    const navigation=root().querySelector('.stage-navigation');
    navigation.innerHTML=names.map((name,index)=>`<button type="button" data-stage-jump="${index}" title="${name}">
      <span class="stage-nav-number">${String(index+1).padStart(2,'0')}</span>
      <span class="stage-nav-copy"><span>${name}</span><small class="stage-nav-status"></small></span>
    </button>`).join('');
    navigation.onclick=event=>{
      const button=event.target.closest('[data-stage-jump]');
      if(button&&Number(button.dataset.stageJump)!==stage)open(Number(button.dataset.stageJump));
    };
    paint();
    schedule();
  }
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!event.defaultPrevented&&!root()?.querySelector('.analysis-chat'))closeStage();
  });
  window.makoraPreparation={start,mount,open,extract,openRefinementChat,chooseFolder,openFolder};
})();

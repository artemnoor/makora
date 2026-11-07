/* Project-scoped role settings; persisted by the controller, never by the browser. */
(()=>{
  const groups=[
    ['Макора',[
      ['preparation','Подготовка проекта','Выполняет этапы доски, от объяснения задания до мок-данных.'],
      ['project_chat','Чат проекта','Отвечает на вопросы по материалам проекта.'],
    ]],
    ['Махорага',[
      ['mahoraga_planner','Планировщик','Разбивает разработку на задачи.'],
      ['mahoraga_orchestrator','Координатор','Решает, какую задачу или агента запустить дальше.'],
      ['mahoraga','Разбор сложных задач','Ищет причину проблемы, когда обычные попытки исправления исчерпаны.'],
    ]],
    ['Разработка',[
      ['builder','Разработчик','Пишет и исправляет код.'],
      ['test_designer','Автор тестов','Готовит независимые проверки.'],
      ['reviewer','Ревьюер','Проверяет код и результаты.'],
    ]],
  ];
  const effortNames={none:'Без рассуждений',minimal:'Минимальный',low:'Низкий',medium:'Средний',high:'Высокий',xhigh:'Очень высокий',max:'Максимальный',ultra:'Ультра'};
  let dialog,loaded,request=0,saving=false,returnFocus;
  const changes=new Map();
  async function api(body){
    const headers={};
    if(body){const token=await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'},credentials:'same-origin'});const auth=await token.json();if(!token.ok)throw Error(auth.error?.message||'Нет доступа к настройкам');headers['X-Makora-Token']=auth.result.token;headers['Content-Type']='application/json'}
    const response=await fetch('/api/preparation/agent-settings',{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,credentials:'same-origin',cache:'no-store'});
    const data=await response.json();if(!response.ok)throw Error(data.error?.message||'Не удалось загрузить настройки');return data.result;
  }
  function option(select,value,label){const item=document.createElement('option');item.value=value;item.textContent=label;select.append(item)}
  function refreshEfforts(row,config){
    const model=row.querySelector('[data-model]').value,select=row.querySelector('[data-effort]');select.replaceChildren();option(select,'','По умолчанию модели');
    const details=loaded.models.find(m=>(m.model||m.id)===model);
    for(const item of details?.supportedReasoningEfforts||[])option(select,item.reasoningEffort,effortNames[item.reasoningEffort]||item.reasoningEffort);
    if(details?.defaultReasoningEffort)select.options[0].textContent='По умолчанию · '+(effortNames[details.defaultReasoningEffort]||details.defaultReasoningEffort);
    const current=config?.reasoningEffort||'';
    if(current&&![...select.options].some(o=>o.value===current))option(select,current,current+' · недоступен');
    select.value=current;select.disabled=!loaded.models.length||select.options.length===1;
  }
  function status(text,error=false){
    const el=dialog.querySelector('[data-settings-status]');
    el.textContent=text;el.setAttribute('role',error?'alert':'status');
  }
  function updateActions(){
    dialog.querySelector('[data-settings-save]').disabled=saving||!loaded?.storageRoot||!loaded.models.length||!changes.size;
    dialog.querySelector('[data-settings-reset]').hidden=!changes.size;
    dialog.querySelector('[data-settings-reset]').disabled=saving;
  }
  function build(){
    const list=dialog.querySelector('[data-settings-roles]');
    const expanded=list.querySelector('details[open]')?.dataset.role||'preparation';
    list.replaceChildren();
    for(const [group,roles] of groups){
      const section=document.createElement('section'),heading=document.createElement('h3');
      heading.textContent=group;section.append(heading);
      for(const [role,title,description] of roles){
        const row=document.createElement('details');row.dataset.role=role;row.name='agent-roles';row.open=role===expanded;
        const summary=document.createElement('summary'),name=document.createElement('strong'),current=document.createElement('span');
        name.textContent=title;current.className='agent-settings-current';summary.append(name,current);
        const fields=document.createElement('fieldset'),note=document.createElement('p');
        fields.setAttribute('aria-label',title);note.textContent=description;fields.append(note);
        for(const [key,label] of [['model','Модель'],['effort','Уровень рассуждений']]){
          const field=document.createElement('label'),select=document.createElement('select');
          field.textContent=label;select.dataset[key]='';field.append(select);fields.append(field);
        }
        row.append(summary,fields);
        const model=row.querySelector('[data-model]'),effort=row.querySelector('[data-effort]');
        const saved=loaded.roles[role],config=changes.get(role)||saved;
        for(const item of loaded.models)option(model,item.model||item.id,item.displayName||item.model||item.id);
        if(![...model.options].some(o=>o.value===config.model))option(model,config.model,config.model+' · недоступна');
        model.value=config.model;model.disabled=!loaded.models.length;refreshEfforts(row,config);
        function showConfig(){
          current.textContent=[model.selectedOptions[0]?.textContent,effort.selectedOptions[0]?.textContent].filter(Boolean).join(' · ');
          row.classList.toggle('settings-changed',changes.has(role));
        }
        function edit(){
          const next={model:model.value,reasoningEffort:effort.value||null};
          if(next.model===saved.model&&next.reasoningEffort===(saved.reasoningEffort||null))changes.delete(role);
          else changes.set(role,next);
          showConfig();updateActions();
          status(changes.size?`Изменено ролей · ${changes.size}`:'Настройки сохранены');
        }
        model.onchange=()=>{refreshEfforts(row);edit()};
        effort.onchange=edit;
        showConfig();section.append(row);
      }
      list.append(section);
    }
    updateActions();
  }
  async function load(){
    const generation=++request;
    loaded=null;
    dialog.querySelector('[data-settings-roles]').replaceChildren();
    updateActions();
    status('Загружаем доступные модели…');
    try{
      const data=await api();
      if(generation!==request)return;
      loaded=data;
      if(!loaded.storageRoot){status('Сначала выберите папку проекта.');return}
      build();
      status(loaded.models.length?'':'Каталог моделей Codex пока недоступен.');
    }catch(error){if(generation===request)status(error.message,true)}
  }
  function open(){
    if(dialog?.open)return;
    returnFocus=document.activeElement;
    if(!dialog){
      dialog=document.createElement('dialog');dialog.className='agent-settings-dialog';dialog.setAttribute('aria-labelledby','agent-settings-title');
      dialog.innerHTML=`
        <div class="agent-settings-shell">
          <form method="dialog" class="agent-settings-heading">
            <div><h2 id="agent-settings-title">Модели и рассуждения</h2><p>Выберите роль. Настройки действуют для её следующих запусков в этом проекте.</p></div>
            <button type="submit" aria-label="Закрыть настройки">×</button>
          </form>
          <div data-settings-roles></div>
          <div class="agent-settings-footer">
            <p data-settings-status role="status" aria-live="polite"></p>
            <div>
              <button type="button" data-settings-reset hidden>Отменить изменения</button>
              <button type="button" data-settings-save disabled>Сохранить</button>
            </div>
          </div>
        </div>`;
      document.body.append(dialog);
      dialog.addEventListener('close',()=>returnFocus?.focus());
      dialog.querySelector('[data-settings-reset]').onclick=()=>{changes.clear();build();status('Изменения отменены')};
      dialog.querySelector('[data-settings-save]').onclick=async()=>{
        if(saving||!loaded||!changes.size)return;
        const project=loaded,roles=Object.fromEntries(changes);
        saving=true;
        dialog.querySelectorAll('fieldset').forEach(row=>row.disabled=true);
        updateActions();
        try{
          const saved=await api({projectId:project.projectId,roles});
          if(loaded!==project)return;
          loaded.roles=saved.roles;changes.clear();build();status('Настройки сохранены');
          window.dispatchEvent(new CustomEvent('makora:agent-settings-saved',{detail:{roles:saved.roles}}));
        }catch(error){if(loaded===project)status(error.message,true)}
        finally{
          saving=false;
          dialog.querySelectorAll('fieldset').forEach(row=>row.disabled=false);
          updateActions();
        }
      };
    }
    dialog.showModal();
    if(!changes.size&&!saving)load();
  }
  function mount(){
    const root=document.querySelector('#first-stage');if(!root)return;
    const folder=root.querySelector('.first-project-folder');if(folder&&!root.querySelector('[data-onboarding-agent-settings]')){const button=document.createElement('button');button.type='button';button.dataset.onboardingAgentSettings='';button.className='onboarding-agent-settings';button.textContent='Модели и рассуждения агентов →';button.onclick=open;folder.after(button)}
    const top=root.querySelector('.first-top-actions')||root.querySelector('.first-top');if(top&&!top.querySelector('[data-open-agent-settings]')){const button=document.createElement('button');button.type='button';button.dataset.openAgentSettings='';button.className='open-agent-settings';button.textContent='Модели';button.setAttribute('aria-label','Модели и рассуждения');button.onclick=open;top.insertBefore(button,top.querySelector('.codex-auth')||top.querySelector('.first-open-folder'))}
    const disclaimer=root.querySelector('.first-disclaimer');if(disclaimer)disclaimer.textContent='Модели агентов настраиваются для проекта. Результаты сохраняются локально и требуют утверждения.';
  }
  window.addEventListener('makora:project-folder',()=>{loaded=null;changes.clear();if(dialog?.open)load()});
  window.makoraAgentSettings={open};mount();
})();

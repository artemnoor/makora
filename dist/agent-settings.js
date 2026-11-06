/* Project-scoped role settings; persisted by the controller, never by the browser. */
(()=>{
  const roles=[['makora','Макора · этот проект','Анализ, документы и общение с Макорой в контексте этого проекта'],['mahoraga','Махорага','Планирование, координация и разбор проблем'],['builder','Разработчики','Написание и исправление кода'],['test_designer','Авторы тестов','Подготовка независимых тестов'],['reviewer','Ревьюеры','Проверка кода и результатов']];
  const effortNames={none:'Без рассуждений',minimal:'Минимальный',low:'Низкий',medium:'Средний',high:'Высокий',xhigh:'Очень высокий',max:'Максимальный',ultra:'Ультра'};
  let dialog,loaded,request=0,dirty=false,saving=false,returnFocus;
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
    select.value=current;select.disabled=select.options.length===1;
  }
  function status(text,error=false){const el=dialog.querySelector('[data-settings-status]');el.textContent=text;el.setAttribute('role',error?'alert':'status')}
  function build(){
    const list=dialog.querySelector('[data-settings-roles]');list.replaceChildren();
    for(const [role,title,description] of roles){
      const row=document.createElement('fieldset');row.dataset.role=role;
      const legend=document.createElement('legend');legend.textContent=title;const note=document.createElement('p');note.textContent=description;row.append(legend,note);
      for(const [key,label] of [['model','Модель'],['effort','Уровень рассуждений']]){const field=document.createElement('label');field.textContent=label;const select=document.createElement('select');select.dataset[key]='';field.append(select);row.append(field)}
      const model=row.querySelector('[data-model]'),config=loaded.roles[role];
      for(const item of loaded.models)option(model,item.model||item.id,item.displayName||item.model||item.id);
      if(![...model.options].some(o=>o.value===config.model))option(model,config.model,config.model+' · недоступна');
      model.value=config.model;refreshEfforts(row,config);
      model.onchange=()=>{refreshEfforts(row);dirty=true;status('Есть несохранённые изменения')};
      row.querySelector('[data-effort]').onchange=()=>{dirty=true;status('Есть несохранённые изменения')};list.append(row);
    }
    dialog.querySelector('[data-settings-save]').disabled=!loaded.storageRoot||!loaded.models.length;
    status(!loaded.storageRoot?'Выберите папку проекта перед сохранением настроек.':'Изменения применятся к следующим запускам. Работающие агенты продолжат со своими настройками.');dirty=false;
  }
  async function load(){const generation=++request;if(!document.querySelector('#first-stage')?.classList.contains('departing')&&document.querySelector('[data-choose-project-folder]')?.dataset.folderSelected!=='true'){loaded=null;dialog.querySelector('[data-settings-roles]').replaceChildren();dialog.querySelector('[data-settings-save]').disabled=true;status('Сначала выберите папку нового проекта, затем настройте его модели и рассуждения.');return}status('Загружаем модели из Codex…');dialog.querySelector('[data-settings-save]').disabled=true;try{const data=await api();if(generation!==request)return;loaded=data;build()}catch(error){if(generation===request)status(error.message,true)}}
  function open(){
    returnFocus=document.activeElement;
    if(!dialog){
      dialog=document.createElement('dialog');dialog.className='agent-settings-dialog';dialog.setAttribute('aria-labelledby','agent-settings-title');
      dialog.innerHTML='<form method="dialog"><div class="agent-settings-heading"><div><h2 id="agent-settings-title">Модели и рассуждения</h2><p>Отдельные настройки для каждой роли в этом проекте</p></div><button type="submit" aria-label="Закрыть настройки">×</button></div></form><div data-settings-roles></div><div class="agent-settings-footer"><p data-settings-status role="status" aria-live="polite"></p><button type="button" data-settings-save disabled>Сохранить настройки</button></div>';
      document.body.append(dialog);dialog.addEventListener('close',()=>{returnFocus?.focus()});
      dialog.querySelector('[data-settings-save]').onclick=async()=>{
        if(saving||!loaded)return;saving=true;const button=dialog.querySelector('[data-settings-save]');button.disabled=true;
        const profile={};for(const row of dialog.querySelectorAll('[data-role]'))profile[row.dataset.role]={model:row.querySelector('[data-model]').value,reasoningEffort:row.querySelector('[data-effort]').value||null};
        try{await api({projectId:loaded.projectId,roles:profile});loaded.roles=profile;dirty=false;status('Сохранено. Новые запуски будут использовать выбранные модели и уровни рассуждений.');window.dispatchEvent(new CustomEvent('makora:agent-settings-saved',{detail:{roles:profile}}))}catch(error){status(error.message,true)}finally{saving=false;button.disabled=false}
      };
    }
    if(!dialog.open)dialog.showModal();if(!saving)load();
  }
  function mount(){
    const root=document.querySelector('#first-stage');if(!root)return;
    const folder=root.querySelector('.first-project-folder');if(folder&&!root.querySelector('[data-onboarding-agent-settings]')){const button=document.createElement('button');button.type='button';button.dataset.onboardingAgentSettings='';button.className='onboarding-agent-settings';button.textContent='Модели и рассуждения агентов →';button.onclick=open;folder.after(button)}
    const top=root.querySelector('.first-top-actions')||root.querySelector('.first-top');if(top&&!top.querySelector('[data-open-agent-settings]')){const button=document.createElement('button');button.type='button';button.dataset.openAgentSettings='';button.className='open-agent-settings';button.textContent='Настройки';button.onclick=open;top.insertBefore(button,top.querySelector('.codex-auth')||top.querySelector('.first-open-folder'))}
    const disclaimer=root.querySelector('.first-disclaimer');if(disclaimer)disclaimer.textContent='Модели агентов настраиваются для проекта. Результаты сохраняются локально и требуют утверждения.';
  }
  window.addEventListener('makora:project-folder',()=>{loaded=null;dirty=false;if(dialog?.open)load()});
  window.makoraAgentSettings={open};mount();
})();

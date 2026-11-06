/* Observed session models stay distinct from settings for future runs. */
(()=>{
  const effortNames={none:'без рассуждений',minimal:'минимальный',low:'низкий',medium:'средний',high:'высокий',xhigh:'очень высокий',max:'максимальный',ultra:'ультра'};
  let configured=null,current=null,request=0;
  const format=(model,effort)=>model?model+' · рассуждения: '+(effort===undefined?'не указан':effortNames[effort]||effort||'по умолчанию модели'):'Модель не сообщена';
  function show(text){
    const bar=document.querySelector('#first-stage .board-bar');if(!bar)return;
    let badge=bar.querySelector('[data-stage-model]');if(!badge){badge=document.createElement('p');badge.dataset.stageModel='';badge.className='stage-model';badge.setAttribute('role','status');bar.querySelector('div')?.append(badge)}badge.textContent=text;
  }
  function render(){
    if(!current)return;
    if(current.type==='preparation'){
      const record=current.record||{},status=record.status;
      if(status==='dispatching'||status==='launching'){const next=record.model?record:configured?.makora;show(next?.model?'Отправляем запрос · выбрана для запуска: '+format(next.model,next.reasoningEffort):'Отправляем запрос · параметры уточняются');return}
      if(record.model){const label=status==='running'||status==='launching'?'Работает':status==='unconfirmed'?'Проверяется сессия':['review','approved'].includes(status)?'Материалы созданы':'Последняя сессия';show(label+' · Макора: '+format(record.model,record.reasoningEffort));return}
      if(status==='running'||status==='launching'||status==='unconfirmed'){show('Сессия запущена · модель не сообщена');return}
      show(configured?.makora?'Следующий запуск · Макора: '+format(configured.makora.model,configured.makora.reasoningEffort):'Этап ещё не запущен');return;
    }
    if(current.type==='external'){show('Внешний агент · модель задаётся во внешнем сервисе');return}
    const active=current.sessions||[];
    if(active.length){const labels={builder:'Разработчик',test_designer:'Тесты',reviewer:'Ревьюер',mahoraga:'Махорага',mahoraga_planner:'Махорага',mahoraga_orchestrator:'Махорага'};show('Сейчас работают: '+active.map(s=>(labels[s.role]||s.role)+': '+format(s.model,s.reasoningEffort)).join(' | '));return}
    show('Сейчас агенты не работают');
  }
  async function refresh(){const id=++request;configured=null;render();try{const response=await fetch('/api/preparation/agent-settings',{credentials:'same-origin',cache:'no-store'});if(!response.ok)return;const data=await response.json();if(id===request){configured=data.result?.roles||null;render();window.dispatchEvent(new CustomEvent('makora:model-config',{detail:configured}))}}catch{}}
  window.makoraModelStatus={preparation(record){current={type:'preparation',record};render()},external(){current={type:'external'};render()},agents(sessions){current={type:'agents',sessions};render()},format,config:()=>configured,refresh};
  window.addEventListener('makora:project-folder',refresh);
  window.addEventListener('makora:agent-settings-saved',event=>{if(event.detail?.roles){request++;configured=event.detail.roles;render();window.dispatchEvent(new CustomEvent('makora:model-config',{detail:configured}))}else refresh()});
})();

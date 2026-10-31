/* Contextual guide: observes real UI state and never triggers workflow actions. */
(()=>{
 const host=document.createElement('aside');host.className='makora-guide';host.setAttribute('aria-label','Путеводитель Макоры');
 host.innerHTML='<div class="mg-head"><span>✳ ПУТЕВОДИТЕЛЬ</span><button type="button" data-guide-toggle aria-expanded="true" aria-label="Свернуть путеводитель">−</button></div><div class="mg-body"><p class="mg-status" role="status" aria-live="polite"></p><div class="mg-motion" aria-hidden="true"><i></i><i></i><i></i><i></i></div><p class="mg-clock"></p><h3></h3><p class="mg-comment"></p><div class="mg-controls"><button type="button" data-guide-show>Показать куда нажать ↗</button></div><details class="mg-explain"><summary>Почему так?</summary><p class="mg-note"></p></details></div>';
 let activity=null,activityAt=0,phaseKey='',phaseAt=Date.now(),signature='',target=null,highlight=null,seen=new Set(),collapsed=false;
 const visible=e=>e&&e.getClientRects().length>0&&!e.closest('[hidden]');
 const find=s=>[...document.querySelectorAll(s)].find(visible);
 const select=s=>{target=s;};
 function clear(){highlight?.classList.remove('mg-highlight');highlight=null}
 function show(){clear();const el=find(target);if(!el)return;el.scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});highlight=el;el.classList.add('mg-highlight');if(!el.matches(':disabled'))el.focus({preventScroll:true})}
 host.querySelector('[data-guide-show]').onclick=show;
 host.querySelector('[data-guide-toggle]').onclick=()=>{collapsed=!collapsed;host.classList.toggle('mg-collapsed',collapsed);const b=host.querySelector('[data-guide-toggle]');b.textContent=collapsed?'＋':'−';b.setAttribute('aria-expanded',String(!collapsed));if(collapsed)clear()};
 window.addEventListener('makora:activity',e=>{activity=e.detail.active?e.detail.text:null;if(activity)activityAt=Date.now();update()});
 document.addEventListener('click',e=>{const file=e.target.closest('[data-real-file]');if(file)seen.add(file.dataset.realFile);setTimeout(update,70)});
 document.addEventListener('input',()=>setTimeout(update,0));document.addEventListener('change',()=>setTimeout(update,0));
 function update(){
  const root=document.querySelector('#first-stage');if(!root)return;if(!host.isConnected)root.append(host);
  const phase=find('.rp-workspace')?.dataset.phase||'',current=find('[data-real-stage].active')?.dataset.realStage||'input',key=current+':'+phase;
  if(key!==phaseKey){phaseKey=key;phaseAt=Date.now();seen.clear()}
  let status='Ваш ход',title='',comment='',note='',selector='',working=false;
  const error=find('[data-real-error],.first-error');
  if(activity){working=true;status=activity;title='Запрос выполняется';comment='Дождитесь ответа сервера. Повторно нажимать кнопку не нужно.'}
  else if(error?.textContent.trim()){status='Нужна проверка';title='Возникла ошибка';comment=error.textContent;selector=find('[data-real-refresh]')?'[data-real-refresh]':'.pixel-start';note='Проверьте сообщение. Не отправляйте то же задание повторно, если доставка не подтверждена.'}
  else if(find('[data-prep-approval]')){status='Ожидается разрешение';title='Проверьте запрос Codex';comment='Макора ждёт решения по конкретному действию. Прочитайте параметры запроса перед разрешением.';selector='[data-prep-approval]'} else if(!root.classList.contains('departing')){
   const ready=!root.querySelector('.pixel-start').disabled;
   title=ready?'02 · Начните анализ':'01 · Пришлите условие';comment=ready?'Проверьте имя выбранного файла или вставленный текст. Затем нажмите «Начать анализ».':'Нажмите «Выбрать файл» или вставьте текст задания в поле ниже.';selector=ready?'.pixel-start':'.pixel-drop';note='PDF, DOCX, TXT или MD. После загрузки анализ запускается отдельной кнопкой.';
  }else if(['running','launching'].includes(phase)){working=true;status='Макора работает';title='Готовим результат этапа';comment='Сессия запущена. Макора пишет документы, затем система проверит файлы. Состояние обновляется автоматически.';selector='[data-real-refresh]';note='Индикатор показывает ожидание ответа, а не процент готовности.'}
  else if(phase==='unconfirmed'){status='Результат не подтверждён';title='Проверьте текущую сессию';comment='Нет подтверждения доставки или завершения. Новый запрос автоматически не отправляется.';selector='[data-real-refresh]';note='Нажмите «Проверить состояние». Не запускайте ещё один анализ.'}
  else if(phase==='review'){
   const files=[...root.querySelectorAll('[data-real-file]')],unread=files.find(e=>!seen.has(e.dataset.realFile));
   if(find('[data-real-document]')){title='03 · Прочитайте результат';comment='Сверьте документ с вашим заданием. Для остальных файлов нажмите «Все результаты этапа».';selector='[data-rp-back]'}
   else if(unread){title='03 · Откройте результат';comment='Макора закончила. Нажмите карточку документа, прочитайте его и проверьте требования.';selector='[data-real-file="'+CSS.escape(unread.dataset.realFile)+'"]'}
   else{title='04 · Утвердите или уточните';comment='Всё подходит — нажмите «Утвердить и продолжить». Если нужны правки, раскройте «Уточнения и изменения» и пересоздайте результат.';selector='[data-real-approve]'}
   status='Готово · ожидает вашего решения';note='Утверждение открывает следующий этап. Просмотр документа ничего не утверждает.';
  }else if(phase==='approved'){status='Этап утверждён';title='Продолжите маршрут';comment='Результат сохранён и будет использован следующим этапом.';selector='[data-real-next]'}
  else if(phase==='failed'||phase==='stale'){status=phase==='failed'?'Этап завершился с ошибкой':'Материалы устарели';title='Уточните и повторите этап';comment='Раскройте замечания и уточнения. После исправления запустите этап снова.';selector='.rp-feedback summary'}
  else if(Number(current)>=5&&Number(find('.real-agent-view')?.dataset.activeAgents)>0){working=true;status='Агенты выполняют задачи';title='Разработка идёт';comment='Контроллер сообщил об активных сессиях. Их результаты, тесты и ревью появятся на доске.';selector='.real-agent-list';note='Завершение ответа агента ещё не означает, что задача прошла тесты и интегрирована.'} else if(Number(current)>=5){
   const choices=[['[data-mahoraga-plan]','Составьте план','Нажмите «Составить план». Макора подготовит задачи по утверждённым документам.'],['[data-mahoraga-approve]','Проверьте план','Изучите задачи и зависимости перед запуском разработки.']];
   const choice=choices.find(x=>find(x[0]));title=choice?.[1]||'Следите за задачами';comment=choice?.[2]||'Статусы задач, результаты тестов и ревью показаны на доске. Подтверждайте интеграцию после проверки результата.';selector=choice?.[0]||'.board-content';status='Разработка · смотрите статусы задач';
  }else{title='02 · Запустите этот этап';comment='Предыдущие материалы уже переданы Макоре. Нажмите «Начать этап».';selector='[data-real-run]'}
  select(selector);const next=JSON.stringify([status,title,comment,note,selector,working]);
  if(signature!==next){signature=next;clear();host.querySelector('.mg-status').textContent=status;host.querySelector('h3').textContent=title;host.querySelector('.mg-comment').textContent=comment;host.querySelector('.mg-note').textContent=note;host.querySelector('.mg-explain').hidden=!note;host.querySelector('[data-guide-show]').hidden=!selector;host.classList.toggle('mg-working',working);host.querySelector('.mg-motion').hidden=!working;root.querySelector('.board')?.setAttribute('aria-busy',String(working));}
  if(!collapsed&&selector&&(!highlight||!highlight.isConnected)){highlight=find(selector);highlight?.classList.add('mg-highlight')} const seconds=Math.floor((Date.now()-(activity?activityAt:phaseAt))/1000);
  host.querySelector('.mg-clock').textContent=working?'Время наблюдения: '+Math.floor(seconds/60)+' мин '+seconds%60+' с'+(seconds>90?' · Ответ пока не получен':''):'';
 }
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){clear()}});
 setInterval(update,1000);update();
})();

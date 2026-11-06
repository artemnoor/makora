(()=>{
 const root=document.querySelector('#first-stage');if(!root)return;
 root.querySelector('.first-new-task')?.remove();
 const intro=root.querySelector('.first-form h1+p');if(intro)intro.textContent='Загрузите условие задания для текущего проекта Codex.';
 const choose=root.querySelector('[data-choose-project-folder]');if(choose){choose.hidden=true;choose.disabled=true}
 fetch('/api/preparation',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('Не удалось загрузить проект');return r.json()}).then(({result})=>{
  if(!result.storageRoot)throw Error('Папка проекта не настроена. Запустите установку из Codex.');
  window.dispatchEvent(new CustomEvent('makora:project-folder',{detail:{path:result.storageRoot}}));
  if(choose){choose.hidden=true;choose.disabled=true}
  if(result.brief)window.dispatchEvent(new CustomEvent('makora:resume-project',{detail:result}));
 }).catch(error=>{const el=root.querySelector('.first-error');if(el){el.textContent=error.message;el.hidden=false}});
})();

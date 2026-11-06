/* Mascot animations reflect observed workflow state; agent badges represent real sessions. */
(()=>{
 let sending=false;
 window.addEventListener('makora:activity',e=>{sending=e.detail.active;sync()});
 const labels={mahoraga_planner:'Махорага · план',mahoraga_orchestrator:'Махорага',builder:'Builder',reviewer:'Reviewer',test_designer:'Test Designer',preparation:'Подготовка'};
 const statuses={accepted:'создан',delivered:'получил задачу',running:'работает',completed:'ответ готов',failed:'ошибка',unconfirmed:'проверяем связь'};
 function sync(){
  const root=document.querySelector('#first-stage');if(!root)return;
  const stage=Number(root.querySelector('[data-real-stage].active')?.dataset.realStage||1),phase=root.querySelector('.rp-workspace')?.dataset.phase;
  const spin=stage<=4&&(sending||['running','launching'].includes(phase));
  try{const wheel=root.querySelector('.mascot-frame').contentDocument.querySelector('[data-action="wheel"]');if(wheel&&wheel.classList.contains('active')!==spin)wheel.click()}catch{}

 }
 setInterval(sync,500);sync();
})();

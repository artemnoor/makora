(() => {
  const host=document.createElement('aside');host.className='codex-auth';host.setAttribute('aria-label','Вход в Codex');
  host.innerHTML='<button type="button" class="codex-auth-toggle" aria-expanded="false">Codex · проверяем вход…</button><section hidden class="codex-auth-console"><header><strong>Консоль входа · Codex</strong><button type="button" data-auth-close aria-label="Закрыть консоль входа">×</button></header><pre role="status" aria-live="polite">Проверяем авторизацию…</pre><p>Завершите вход в открывшейся консоли и браузере. Затем проверьте вход.</p><div><button type="button" data-auth-login>Открыть консоль входа</button><button type="button" data-auth-check>Проверить вход</button></div></section>';
  const folder=document.querySelector('#first-stage .first-open-folder');
  if(folder)folder.before(host);else document.body.append(host);
  const toggle=host.querySelector('.codex-auth-toggle'),panel=host.querySelector('section'),log=host.querySelector('pre'),login=host.querySelector('[data-auth-login]'),check=host.querySelector('[data-auth-check]');
  let checking=false,launching=false,automaticAttempt=false;
  function setLabel(text){
    const [name,...rest]=text.split(' · ');toggle.replaceChildren(document.createTextNode(name));
    const state=document.createElement('span');state.className='codex-auth-status';state.textContent=rest.length?' · '+rest.join(' · '):'';toggle.append(state);toggle.setAttribute('aria-label',text);
  }
  setLabel(toggle.textContent);

  function expand(open){panel.hidden=!open;toggle.setAttribute('aria-expanded',String(open))}
  toggle.onclick=()=>expand(panel.hidden);host.querySelector('[data-auth-close]').onclick=()=>{expand(false);toggle.focus()};
  host.addEventListener('keydown',e=>{if(e.key==='Escape'){expand(false);toggle.focus()}});
  async function openLogin(){
    if(launching)return;launching=true;login.disabled=true;expand(true);
    try{
      const tokenResponse=await fetch('/api/agents/token',{headers:{'X-Makora-Request':'token'},credentials:'same-origin'}),auth=await tokenResponse.json();
      if(!tokenResponse.ok)throw Error(auth.error?.message||'Нет доступа к локальному серверу.');
      const response=await fetch('/api/agents/auth/login',{method:'POST',credentials:'same-origin',headers:{'X-Makora-Token':auth.result.token}}),data=await response.json();
      if(!response.ok)throw Error(data.error?.message||'Не удалось открыть консоль.');log.textContent=data.result.message;
    }catch(error){log.textContent=error.message}finally{launching=false;login.disabled=false}
  }
  async function verify(){
    if(checking)return;checking=true;check.disabled=true;
    try{
      const response=await fetch('/api/agents/auth',{cache:'no-store',credentials:'same-origin'}),data=await response.json();
      if(!response.ok)throw Error(data.error?.message||'Не удалось проверить вход.');
      const state=data.result;host.dataset.status=state.status;log.textContent=state.message;
      host.querySelector('p').textContent=state.status==='signed_in'?'Авторизация работает. Можно вернуться к плану Махораги.':state.status==='signed_out'?'Завершите вход в консоли и браузере. Затем нажмите «Проверить вход».':'Нет связи с Codex. Повторите проверку после восстановления подключения.';
      setLabel(state.status==='signed_in'?'● Codex · вход выполнен':state.status==='signed_out'?'● Codex · нужен вход':'○ Codex · нет подключения');
      if(state.status==='signed_out'){
        expand(true);
        if(!automaticAttempt){automaticAttempt=true;await openLogin()}
      }
    }catch(error){host.dataset.status='unavailable';setLabel('○ Codex · проверка недоступна');log.textContent=error.message}
    finally{checking=false;check.disabled=false}
  }
  login.onclick=openLogin;check.onclick=verify;
  window.addEventListener('focus',verify);
  setInterval(()=>{if(!document.hidden)verify()},45000);
  verify();
})();

const MODELS={success:'spaces.json',empty:'empty.json',stale:'stale.json',invalid:'invalid.json'};
self.addEventListener('install',event=>event.waitUntil(self.skipWaiting()));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('fetch',event=>{
 const u=new URL(event.request.url);if(u.origin!==self.location.origin||!u.pathname.startsWith('/mock-api/'))return;
 event.respondWith((async()=>{
  const json=(v,status=200)=>new Response(JSON.stringify(v,null,2),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Mock-Source':'synthetic'}});
  if(event.request.method!=='GET')return json({code:'METHOD_NOT_ALLOWED',message:'Разрешён только GET'},405);
  const scenario=u.searchParams.get('scenario')||'success';
  if(scenario==='server_error')return json({code:'SOURCE_UNAVAILABLE',message:'Демонстрационная ошибка источника'},503);
  if(!Object.hasOwn(MODELS,scenario))return json({code:'BAD_REQUEST',message:'Неизвестный сценарий'},400);
  const parts=u.pathname.split('/').filter(Boolean);if(parts[1]!=='spaces'||parts.length>3)return json({code:'NOT_FOUND',message:'Маршрут не найден'},404);
  const response=await fetch('/mocks/fixtures/'+MODELS[scenario],{cache:'no-store'});if(!response.ok)return json({code:'FIXTURE_UNAVAILABLE',message:'Файл фикстуры недоступен'},503);
  const items=await response.json();if(parts.length===3){const item=items.find(x=>x.id===decodeURIComponent(parts[2]));return item?json(item):json({code:'NOT_FOUND',message:'Пространство не найдено'},404)}
  const building=u.searchParams.get('building'),available=u.searchParams.get('available');if(available!==null&&!['true','false'].includes(available))return json({code:'BAD_REQUEST',message:'available должен быть true или false'},400);
  return json({items:items.filter(x=>(!building||x.building===building)&&(available!=='true'||['available','limited'].includes(x.status)))});
 })().catch(()=>new Response(JSON.stringify({code:'FIXTURE_UNAVAILABLE',message:'Ошибка чтения фикстуры'}),{status:503,headers:{'Content-Type':'application/json'}})));
});

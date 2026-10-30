/* Demo workflow state and agent simulator. No external agents, Git branches or commands run here. */
(() => {
  const STORAGE_KEY = 'makora.demo-workflow.v1';
  const LEGACY_PLAN_KEY = 'makora.agent-plan-demo.v1';
  const LEGACY_VIEW_KEY = 'makora.workspace-view.v1';
  const clone = value => JSON.parse(JSON.stringify(value));
  const defaults = [
    {id:'T01',title:'Подготовка проекта',goal:'Подготовить структуру приложения и подключить исходные данные.',result:'Запускаемый каркас с адаптером данных и заглушками интерфейса.',inputArtifacts:['03_architecture.md','03_contracts/openapi.yaml','mocks/fixtures/spaces.json'],dependsOn:[],contracts:['Space','GET /spaces'],mocks:['mocks/fixtures/spaces.json'],acceptance:'Проект запускается, адаптер читает фикстуру, заглушки имеют документированные контракты.',testUi:false,branch:'feature/T01-project-setup',outputs:['src/app-shell','src/data/space-source'],demoFailFirstReview:false},
    {id:'T02',title:'Каталог пространств',goal:'Загрузить каталог пространств из фикстур и подготовить данные для интерфейса.',result:'Модуль каталога с фильтрацией и обработкой пустого ответа.',inputArtifacts:['T01 · адаптер данных','03_contracts/openapi.yaml'],dependsOn:['T01'],contracts:['Space','GET /spaces'],mocks:['spaces.json','empty.json','invalid.json'],acceptance:'Корректные записи загружаются, пустое состояние и ошибки данных обработаны.',testUi:true,branch:'feature/T02-space-catalog',outputs:['src/catalog/space-catalog'],demoFailFirstReview:true},
    {id:'T03',title:'Интерфейс поиска',goal:'Создать экран поиска и фильтров свободных пространств.',result:'Поиск по корпусу и доступности на основе контракта Space.',inputArtifacts:['T01 · каркас','T02 · контракт каталога'],dependsOn:['T01'],contracts:['Space','GET /spaces'],mocks:['spaces.json','empty.json'],acceptance:'Поиск и фильтры работают на мок-данных, пустое состояние понятно пользователю.',testUi:true,branch:'feature/T03-space-search',outputs:['src/search/space-search'],demoFailFirstReview:false},
    {id:'T04',title:'Интеграция и сквозная проверка',goal:'Соединить каталог с интерфейсом и проверить основной пользовательский сценарий.',result:'Интегрированный сценарий поиска с результатами и обработкой отказа источника.',inputArtifacts:['T02 · каталог','T03 · интерфейс','mocks/scenarios.json'],dependsOn:['T02','T03'],contracts:['GET /spaces','Error'],mocks:['spaces.json','stale.json','empty.json','error.json'],acceptance:'Основной сценарий, устаревшие данные и ошибка источника проверены вместе.',testUi:false,branch:'feature/T04-integration',outputs:['src/app/search-flow'],demoFailFirstReview:false}
  ].map(task => ({...task,builderPrompt:`Реализуй ${task.id} «${task.title}» в демонстрационном проекте. Цель: ${task.goal} Результат: ${task.result} Используй только входные артефакты и контракты задачи. Источник данных — перечисленные фикстуры; не дублируй и не подменяй их. Добавь собственные тесты, сохрани обратную совместимость и перечисли изменённые файлы.`,testPrompt:`Независимо подготовь тесты для ${task.id} «${task.title}». Используй цель, контракты (${task.contracts.join(', ')}) и критерий: ${task.acceptance}. Реализацию Builder не показывай и не предполагай. Зафиксируй входы, ожидаемые ответы, негативные и граничные случаи.`,reviewerPrompt:`Проведи независимое ревью ${task.id} «${task.title}» после реализации Builder. Сначала выполни независимые тесты, затем проверь контракты, критерии готовности, обработку ошибок и интеграционные риски. Не интегрируй задачу при любом блокирующем замечании.`}));

  function freshState() {
    return {version:1,activeStage:1,analysis:{confirmedSignature:''},demoPrototype:{status:'locked',signature:'',approvedAt:''},agent:{step:'skeleton',skeletonApproved:false,skeletonChecks:null,decompositionApproved:false,mapApproved:false,legacyPlanApproval:false,tasks:clone(defaults),simulation:{started:false,mode:'normal',runs:0,tasks:{},events:[],activeTask:null,escalation:null}},history:[],migratedAt:''};
  }
  function readJson(key) { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } }
  let state = readJson(STORAGE_KEY);
  if (!state || state.version !== 1 || !state.agent || !Array.isArray(state.agent.tasks)) {
    state = freshState();
    const old = readJson(LEGACY_PLAN_KEY), oldView = readJson(LEGACY_VIEW_KEY);
    if (old && Array.isArray(old.tasks)) {
      state.agent.tasks = old.tasks.map((task,index) => ({...clone(defaults[index] || defaults[0]),...task,
        dependsOn:Array.isArray(task.dependsOn)?task.dependsOn:(String(task.deps||'').match(/T\d+/g)||[]),
        inputArtifacts:task.inputArtifacts||defaults[index]?.inputArtifacts||[],
        result:task.result||task.ready||'Результат задачи требует уточнения.',
        acceptance:task.acceptance||task.ready||'Критерий готовности требует уточнения.',
        contracts:task.contracts||String(task.contract||'').split(/[·,]/).map(x=>x.trim()).filter(Boolean),
        mocks:Array.isArray(task.mocks)?task.mocks:String(task.mocks||'').split(/[,;]/).map(x=>x.trim()).filter(Boolean),
        builderPrompt:task.builderPrompt||task.builder||'',testPrompt:task.testPrompt||'',reviewerPrompt:task.reviewerPrompt||task.reviewer||'',
        branch:task.branch||`feature/${task.id||'task'}`,
        outputs:task.outputs||[],testUi:!!task.testUi}));
      state.agent.legacyPlanApproval = !!old.approved;
      state.history.push({type:'migration',at:new Date().toISOString(),detail:'Сохранены прежние карточки задач. Предыдущее утверждение плана требует повторной проверки в новом маршруте.'});
    }
    const project = window.makoraProject?.source?.();
    if (project && Number(oldView?.stage) > 1) {
      state.analysis.confirmedSignature = signature(project);
      state.history.push({type:'migration',at:new Date().toISOString(),detail:'Восстановлено ранее сохранённое прохождение анализа задания.'});
    }
    state.migratedAt = new Date().toISOString();
  }
  if (!Array.isArray(state.history)) state.history=[];
  if (!state.agent.simulation || !Array.isArray(state.agent.simulation.events)) state.agent.simulation={started:false,mode:'normal',runs:0,tasks:{},events:[],activeTask:null,escalation:null};
  if (!Array.isArray(state.agent.tasks) || !state.agent.tasks.length) state.agent.tasks=clone(defaults);

  function save() { try { localStorage.setItem(STORAGE_KEY,JSON.stringify(state)); } catch {} }
  function signature(value) { return JSON.stringify(value ?? null); }
  function record(type,detail,taskId='') {
    const event={id:`EV-${Date.now()}-${Math.random().toString(36).slice(2,7)}`,type,taskId,detail,at:new Date().toISOString()};
    state.agent.simulation.events.push(event); state.history.push(event); save();
    window.dispatchEvent(new CustomEvent('makora-demo-workflow-change',{detail:{type,event,state:api.getState()}}));
    return event;
  }
  function currentSource() { return window.makoraProject?.source?.() || null; }
  function sourceSignature() { return signature(currentSource()); }
  function stage4Approval() { return readJson('makora.stage4.review.v1') || {}; }
  function stage4Signature() {
    let plan=null;
    try { const c=window.makoraStage3?.getContext?.(); plan=c?{project:c.project.signature,readiness:c.readiness,approval:c.approval}:null; } catch {}
    const review=stage4Approval();
    return signature({source:sourceSignature(),plan,stage4:{status:review.status,context:review.context,data:review.data}});
  }
  function isStage4Approved() {
    try { return !!window.makoraMockData?.getBundle && !!readJson('makora.stage4.review.v1') && readJson('makora.stage4.review.v1').status==='approved'; } catch { return false; }
  }
  function stage3Ready() {
    try { return !!window.makoraStage3?.getContext?.().readiness?.ready; } catch { return false; }
  }
  function stage2Approved() { try { return !!window.makoraProject?.isApproved?.(); } catch { return false; } }
  function analysisApproved() { return !!currentSource() && state.analysis.confirmedSignature===sourceSignature(); }
  function demoPrototypeCurrent() { return state.demoPrototype.status==='approved' && isStage4Approved() && state.demoPrototype.signature===stage4Signature(); }
  function refreshInvalidation() {
    if (state.demoPrototype.status==='approved' && !demoPrototypeCurrent()) {
      state.demoPrototype.status='stale'; state.agent.step='skeleton';
      state.agent.skeletonApproved=false; state.agent.decompositionApproved=false; state.agent.mapApproved=false;
      const sim=state.agent.simulation;
      if (sim.started) { sim.stale=true; sim.started=false; sim.tasks={}; sim.activeTask=null; }
      state.activeStage=Math.min(Number(state.activeStage)||1,4);
      state.history.push({type:'invalidation',at:new Date().toISOString(),detail:'Этап 4 изменился после согласования демо-прототипа. Этап 6 требует перепроверки.'}); save();
    }
  }
  function graphErrors(tasks=state.agent.tasks) {
    const errors=[], ids=new Set(tasks.map(t=>t.id));
    let openapi='';try{openapi=String(window.makoraStage3?.getContext?.().openapi||'')}catch{}
    const knownContracts=new Set();
    if(/^\s{4}Space:/m.test(openapi))knownContracts.add('Space');
    if(/^\s{4}Error:/m.test(openapi))knownContracts.add('Error');
    if(/\/spaces:\s*\n\s+get:/m.test(openapi))knownContracts.add('GET /spaces');
    if(/\/spaces\/\{id\}:\s*\n\s+get:/m.test(openapi))knownContracts.add('GET /spaces/{id}');
    if (ids.size!==tasks.length) errors.push('ID задач должны быть уникальными.');
    for (const task of tasks) {
      if (!/^T\d{2,}$/.test(task.id||'')) errors.push(`${task.id||'Задача'}: используйте ID вида T05.`);
      if (!String(task.title||'').trim()) errors.push(`${task.id}: укажите название.`);
      if (!String(task.goal||'').trim() || !String(task.result||'').trim()) errors.push(`${task.id}: заполните цель и результат.`);
      if (!String(task.acceptance||'').trim()) errors.push(`${task.id}: укажите критерий готовности.`);
      if (!Array.isArray(task.contracts)||!task.contracts.length||task.contracts.some(x=>!String(x).trim())) errors.push(`${task.id}: свяжите задачу хотя бы с одним контрактом.`);
      for(const contract of task.contracts||[])if(!knownContracts.has(contract))errors.push(`${task.id}: контракт «${contract}» отсутствует в утверждаемом OpenAPI.`);
      const uniqueDeps=new Set(task.dependsOn||[]);
      if (uniqueDeps.size!==(task.dependsOn||[]).length) errors.push(`${task.id}: повторяется зависимость.`);
      for (const dep of task.dependsOn||[]) {
        if (dep===task.id) errors.push(`${task.id}: задача не может зависеть от самой себя.`);
        else if (!ids.has(dep)) errors.push(`${task.id}: зависимость ${dep} не существует.`);
      }
    }
    const outputs=new Map();
    for(const t of tasks) for(const path of t.outputs||[]) { if(outputs.has(path))errors.push(`Конфликт результата ${path}: он назначен ${outputs.get(path)} и ${t.id}.`); else outputs.set(path,t.id); }
    const visiting=new Set(),visited=new Set();
    function visit(id,path=[]) { if(visiting.has(id)){errors.push('Цикл зависимостей: '+[...path,id].join(' → ')+'.');return;}if(visited.has(id))return;visiting.add(id);const task=tasks.find(t=>t.id===id);for(const dep of task?.dependsOn||[])if(ids.has(dep))visit(dep,[...path,id]);visiting.delete(id);visited.add(id); }
    for(const id of ids)visit(id);
    return [...new Set(errors)];
  }
  function simTask(id) { return state.agent.simulation.tasks[id] || {status:'blocked',testsPrepared:false,codeReady:false,fixReady:false,reviewAttempts:0,reviewPassed:false,integrated:false}; }
  function effectiveStatus(id) {
    const sim=state.agent.simulation;
    const task=state.agent.tasks.find(t=>t.id===id);
    const progress=sim.tasks[id];
    if(progress&&progress.status!=='blocked')return progress.status;
    return task&&(task.dependsOn||[]).every(dep=>sim.tasks[dep]?.status==='integrated')?'ready':'blocked';
  }
  function initializeSimulation(mode='normal') {
    const tasks={};
    for(const task of state.agent.tasks)tasks[task.id]={status:(task.dependsOn||[]).length?'blocked':'ready',testsPrepared:false,codeReady:false,fixReady:false,reviewAttempts:0,reviewPassed:false,integrated:false};
    state.agent.simulation={started:true,mode,runs:(state.agent.simulation.runs||0)+1,tasks,events:[],activeTask:null,escalation:null,stale:false};
    record('simulation_started',mode==='escalation'?'Запущен отдельный сценарий эскалации после трёх неудачных ревью.':'Запущена управляемая демонстрация. Реальные агенты и Git-ветки не создавались.');
  }
  function taskAction(id,action) {
    const task=state.agent.tasks.find(t=>t.id===id); if(!task)return {ok:false,error:'Задача не найдена.'};
    const sim=state.agent.simulation, progress=simTask(id);
    if(!sim.started || sim.stale)return {ok:false,error:'Сначала запустите актуальную демонстрацию.'};
    if(action==='prepare-tests'){
      if(effectiveStatus(id)!=='ready')return {ok:false,error:'Задача заблокирована: сначала интегрируйте её зависимости.'};
      progress.status='testing_preparation';progress.testsPrepared=false;progress.codeReady=false;progress.fixReady=false;sim.tasks[id]=progress;sim.activeTask=id;
      record('test_design_started',`Test Designer получил задачу, контракт и критерии ${id}; реализацию Builder он не видит.`,id);return {ok:true};
    }
    if(action==='complete-tests'){
      if(progress.status!=='testing_preparation')return {ok:false,error:'Независимые тесты сейчас не готовятся.'};
      progress.testsPrepared=true;progress.status='ready';sim.tasks[id]=progress;
      record('test_design_completed',`Независимый набор проверок для ${id} зафиксирован до передачи задачи Builder.`,id);return {ok:true};
    }
    if(action==='start-builder'){
      if(progress.status!=='ready'||!progress.testsPrepared)return {ok:false,error:'Сначала подготовьте независимые тесты.'};
      progress.status='implementing';progress.codeReady=false;sim.tasks[id]=progress;sim.activeTask=id;
      record('builder_started',`Builder начал ${id}. Закрытые тесты Test Designer не передаются Builder.`,id);return {ok:true};
    }
    if(action==='complete-builder'){
      if(progress.status!=='implementing')return {ok:false,error:'Builder не выполняет эту задачу.'};
      progress.status='reviewing';progress.codeReady=true;sim.tasks[id]=progress;
      record('builder_completed',`Демонстрационный результат ${id} готов к независимому ревью. Код не запускался.`,id);return {ok:true};
    }
    if(action==='review'){
      if(!progress.testsPrepared||!progress.codeReady||!['reviewing','fixing'].includes(progress.status)||progress.status==='fixing'&&!progress.fixReady)return {ok:false,error:'Для ревью нужны независимые тесты и готовая реализация.'};
      progress.reviewAttempts++;progress.fixReady=false;
      const intentional=(sim.mode==='escalation') || (task.demoFailFirstReview&&progress.reviewAttempts===1);
      if(intentional){
        progress.reviewPassed=false;
        if(progress.reviewAttempts>=3){progress.status='failed';progress.issue='Проверка не прошла три раза. Автоматическая интеграция запрещена.';sim.escalation={taskId:id,options:['Пересмотреть контракт','Изменить декомпозицию','Передать другому Builder','Запросить решение пользователя'],selected:''};}
        else{progress.status='fixing';progress.issue=task.demoFailFirstReview?'Граничный случай пустого ответа не обработан.':'Демонстрационная проверка повторно обнаружила контрактное расхождение.';}
        sim.tasks[id]=progress;
        record('review_failed',`Ревью ${id}, попытка ${progress.reviewAttempts}/3: ${progress.issue}`,id);if(progress.reviewAttempts>=3)record('escalated',`${id} передана Макоре после трёх неудачных попыток. Интеграция остаётся закрытой.`,id);return {ok:true,passed:false,attempt:progress.reviewAttempts};
      }
      progress.status='passed';progress.reviewPassed=true;progress.issue='';sim.tasks[id]=progress;
      record('review_passed',`Независимые тесты, контракт и критерии ${id} пройдены. Задача готова к ручной интеграции.`,id);return {ok:true,passed:true,attempt:progress.reviewAttempts};
    }
    if(action==='complete-fix'){
      if(progress.status!=='fixing'||progress.reviewAttempts>=3)return {ok:false,error:'Для этой задачи исправление недоступно.'};
      progress.fixReady=true;progress.codeReady=true;sim.tasks[id]=progress;
      record('fix_completed',`Builder демонстрационно исправил замечание ${id}; Reviewer должен повторить проверку.`,id);return {ok:true};
    }
    if(action==='integrate'){
      if(progress.status!=='passed'||!progress.reviewPassed||!(task.dependsOn||[]).every(dep=>sim.tasks[dep]?.status==='integrated'))return {ok:false,error:'Интеграция запрещена: нужен успешный Reviewer и интегрированные зависимости.'};
      progress.status='integrated';progress.integrated=true;sim.tasks[id]=progress;
      record('task_integrated',`${id}: условная ветка ${task.branch} принята. Зависимости: ${(task.dependsOn||[]).join(', ')||'нет'}. Реальный Git merge не выполнялся.`,id);
      for(const next of state.agent.tasks)if(next.dependsOn.includes(id)&&effectiveStatus(next.id)==='blocked')record('task_unblocked',`${next.id} теперь может стартовать после интеграции ${id}.`,next.id);
      return {ok:true};
    }
    if(action==='escalate'){
      if(progress.status!=='failed'||progress.reviewAttempts<3)return {ok:false,error:'Эскалация доступна после трёх неудачных попыток.'};
      sim.escalation={taskId:id,options:['Пересмотреть контракт','Изменить декомпозицию','Передать другому Builder','Запросить решение пользователя'],selected:''};
      record('escalated',`${id} передана Макоре после трёх неудачных попыток. Интеграция остаётся закрытой.`,id);return {ok:true};
    }
    if(action==='resolve-escalation'){
      if(sim.escalation?.taskId!==id||!sim.escalation.options.includes(arguments[2]))return {ok:false,error:'Выберите один из предложенных вариантов эскалации.'};
      sim.escalation.selected=arguments[2];record('escalation_decision',`Пользователь выбрал: ${arguments[2]}. Требуется отдельное решение до продолжения.`,id);return {ok:true};
    }
    return {ok:false,error:'Неизвестное действие.'};
  }

  const api = {
    key:STORAGE_KEY,
    getState(){refreshInvalidation();return clone(state);},
    getTasks(){return clone(state.agent.tasks);},
    getTask(id){return clone(state.agent.tasks.find(t=>t.id===id)||null);},
    getTaskStatus(id){return effectiveStatus(id);},
    getReadyTasks(){return state.agent.tasks.filter(t=>effectiveStatus(t.id)==='ready').map(t=>t.id);},
    selectSimulationTask(id){if(state.agent.tasks.some(t=>t.id===id)){state.agent.simulation.activeTask=id;save();return true;}return false;},
    validateGraph(){return graphErrors();},
    contractOptions(){const options=[];let openapi='';try{openapi=String(window.makoraStage3?.getContext?.().openapi||'')}catch{}if(/^\s{4}Space:/m.test(openapi))options.push('Space');if(/^\s{4}Error:/m.test(openapi))options.push('Error');if(/\/spaces:\s*\n\s+get:/m.test(openapi))options.push('GET /spaces');if(/\/spaces\/\{id\}:\s*\n\s+get:/m.test(openapi))options.push('GET /spaces/{id}');return options;},
    addTask(){const n=Math.max(4,...state.agent.tasks.map(t=>Number(String(t.id).replace(/\D/g,''))||0))+1;const id=`T${String(n).padStart(2,'0')}`;state.agent.tasks.push({...clone(defaults[1]),id,title:'Новая задача',goal:'Опишите цель задачи.',result:'Опишите ожидаемый результат.',dependsOn:[],inputArtifacts:[],branch:`feature/${id.toLowerCase()}-task`,outputs:[`src/${id.toLowerCase()}`],demoFailFirstReview:false});invalidatePlan('Добавлена '+id);return id;},
    updateTask(id,patch){const task=state.agent.tasks.find(t=>t.id===id);if(!task)return {ok:false,error:'Задача не найдена.'};Object.assign(task,clone(patch));if(!Array.isArray(task.dependsOn))task.dependsOn=[];invalidatePlan(`Изменена ${id}`);return {ok:true};},
    approveAnalysis(){const source=currentSource();if(!source)return {ok:false,error:'Сначала загрузите или вставьте условие задания.'};state.analysis.confirmedSignature=sourceSignature();state.activeStage=2;record('stage_01_approved','Пользователь подтвердил просмотр демонстрационного анализа.');return {ok:true};},
    getStageStatuses(){refreshInvalidation();const source=!!currentSource(),review=stage4Approval(),hasStage4Work=!!review.status&&review.status!=='draft';const statuses={1:source?(analysisApproved()?'approved':'needs_review'):'available',2:!analysisApproved()?'locked':stage2Approved()?'approved':'available',3:!stage2Approved()?'locked':stage3Ready()?'approved':'available',4:!stage2Approved()?'locked':isStage4Approved()?'approved':stage3Ready()?'available':hasStage4Work?'needs_review':'locked',5:!isStage4Approved()?'locked':demoPrototypeCurrent()?'approved':'available',6:!demoPrototypeCurrent()?'locked':state.agent.step==='simulation'?'in_progress':'available'};return statuses;},
    canOpenStage(n){const s=this.getStageStatuses();return Number(n)===1||s[Number(n)]==='approved'||s[Number(n)]==='available'||s[Number(n)]==='in_progress'||s[Number(n)]==='needs_review';},
    getGateMessage(n){const msgs={2:'Сначала просмотрите анализ задания и нажмите «Далее».',3:'Сначала утвердите идею на этапе 2.',4:'Сначала завершите и утвердите планирование на этапе 3.',5:'Сначала выполните реальные проверки и утвердите мок-данные на этапе 4.',6:'Сначала утвердите демо-мок-прототип на этапе 5.'};return msgs[n]||'Этот шаг пока недоступен.';},
    setActiveStage(n){state.activeStage=Number(n);save();},
    async getStage4DemoBundle(){try{return await window.makoraMockData.getBundle();}catch{return null;}},
    async approveDemoPrototype(){const bundle=await this.getStage4DemoBundle();if(!bundle?.approved)return {ok:false,error:'Мок-данные этапа 4 должны пройти проверки и быть утверждены.'};state.demoPrototype={status:'approved',signature:stage4Signature(),approvedAt:new Date().toISOString()};state.activeStage=6;state.agent.step='skeleton';record('stage_05_demo_approved','Утверждён учебный мок-прототип. Это подготовленный пример, он не меняет реальные ревизии.');return {ok:true};},
    isDemoPrototypeReady(){refreshInvalidation();return demoPrototypeCurrent();},
    getStep(){return state.agent.step;},
    openStep(step){const order=['skeleton','decomposition','map','simulation'];const target=order.indexOf(step),current=order.indexOf(state.agent.step);if(target<0)return {ok:false,error:'Неизвестный шаг.'};if(target>current)return {ok:false,error:'Сначала завершите предыдущий шаг и подтвердите его.'};state.agent.step=step;save();return {ok:true};},
    recordSkeletonChecks(results){state.agent.skeletonChecks={results:clone(results),checkedAt:new Date().toISOString(),sourceSignature:stage4Signature()};save();record('skeleton_checked',`Проверено файлов/контрактов: ${results.length}; ошибок: ${results.filter(x=>!x.ok).length}.`);return clone(state.agent.skeletonChecks);},
    approveSkeleton(){if(!demoPrototypeCurrent())return {ok:false,error:'Демо-мок-прототип устарел. Вернитесь к этапу 4.'};if(!state.agent.skeletonChecks?.results?.length||state.agent.skeletonChecks.results.some(x=>!x.ok)||state.agent.skeletonChecks.sourceSignature!==stage4Signature())return {ok:false,error:'Сначала выполните и пройдите проверки скелета на текущих мок-данных.'};state.agent.skeletonApproved=true;state.agent.step='decomposition';state.activeStage=6;record('skeleton_approved','Пользователь подтвердил демонстрационный скелет проекта.');return {ok:true};},
    approveDecomposition(){const errors=graphErrors();if(errors.length)return {ok:false,error:errors.join(' ')};if(!state.agent.skeletonApproved)return {ok:false,error:'Сначала подтвердите подготовку скелета.'};state.agent.decompositionApproved=true;state.agent.mapApproved=false;state.agent.step='map';state.agent.simulation={started:false,mode:'normal',runs:0,tasks:{},events:state.agent.simulation.events||[],activeTask:null,escalation:null};record('decomposition_approved','Пользователь утвердил проверенный граф задач.');return {ok:true};},
    approveMap(){const errors=graphErrors();if(errors.length)return {ok:false,error:errors.join(' ')};if(!state.agent.decompositionApproved)return {ok:false,error:'Сначала утвердите декомпозицию.'};state.agent.mapApproved=true;state.agent.step='simulation';state.activeStage=6;record('agent_map_approved','Пользователь утвердил карту запуска и предполагаемые Git-ветки.');return {ok:true};},
    startSimulation(mode='normal'){if(!demoPrototypeCurrent()||!state.agent.mapApproved||graphErrors().length)return {ok:false,error:'Перед запуском нужны актуальный прототип, корректная декомпозиция и утверждённая карта.'};initializeSimulation(mode==='escalation'?'escalation':'normal');return {ok:true};},
    taskAction(id,action,choice){if(action==='resolve-escalation'){const progress=simTask(id),sim=state.agent.simulation;if(sim.escalation?.taskId!==id||!sim.escalation.options.includes(choice))return {ok:false,error:'Выберите один из предложенных вариантов эскалации.'};sim.escalation.selected=choice;record('escalation_decision',`Пользователь выбрал: ${choice}. Требуется отдельное решение до продолжения.`,id);return {ok:true};}return taskAction(id,action);},
    resetSimulation(){const old=state.agent.simulation;state.history.push({type:'simulation_reset',at:new Date().toISOString(),detail:'Пользователь сбросил только симуляцию. Скелет, задачи, промпты, согласования и история сохранены.'});state.agent.simulation={started:false,mode:'normal',runs:old.runs||0,tasks:{},events:old.events||[],activeTask:null,escalation:null};save();window.dispatchEvent(new CustomEvent('makora-demo-workflow-change',{detail:{type:'simulation_reset',state:this.getState()}}));return {ok:true};},
    logViewEvent(type,detail){return record(type,detail);},
    exportHistory(){return clone(state.history);},
    optionsForEscalation(id){return state.agent.simulation.escalation?.taskId===id?clone(state.agent.simulation.escalation.options):[];}
  };
  function invalidatePlan(reason){
    if(state.agent.decompositionApproved||state.agent.mapApproved||state.agent.simulation.started){state.agent.decompositionApproved=false;state.agent.mapApproved=false;state.agent.step=state.agent.skeletonApproved?'decomposition':'skeleton';const sim=state.agent.simulation;if(sim.started){sim.started=false;sim.stale=true;sim.tasks={};sim.activeTask=null;}state.history.push({type:'plan_invalidated',at:new Date().toISOString(),detail:`${reason}. Утверждённые зависимости и симуляция требуют повторной проверки.`});}
    save();window.dispatchEvent(new CustomEvent('makora-demo-workflow-change',{detail:{type:'task_changed',state:api.getState()}}));
  }
  save();
  window.makoraDemoWorkflow=api;
})();

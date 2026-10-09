/* Project autonomy controls over the existing qualified Project autonomy API.
 * Presentation/control surface only: P10/P6, policy, approvals, recovery and
 * Completion Judge remain authoritative.
 */
(()=>{
  if(window.__vishnuProjectAutonomyUI?.installed)return;
  const modes=new Map(),pending=new Map(),lastAdvance=new Map(),observers=new WeakMap();
  const esc=value=>typeof prEsc==='function'?prEsc(value):String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const definitions={
    shadow:{title:'Shadow',description:'Vishnu can plan and evaluate this Project, but Project Work execution is disabled.'},
    assisted:{title:'Assisted',description:'Vishnu can execute owner-triggered qualified work and stops wherever an authority requires you.'},
    active:{title:'Active',description:'Vishnu may advance ready qualified WorkOrders while every policy, approval, evidence, recovery and completion gate remains enforced.'},
  };
  const stopCopy=reason=>{
    const value=String(reason||'').toLowerCase();
    if(!value)return '';
    if(value==='no_work_plan')return 'No canonical WorkPlan is available yet.';
    if(value==='no_ready_work')return 'No WorkOrder is currently ready to advance.';
    if(value==='emergency_stop')return 'Emergency Stop is active.';
    if(value==='step_budget_reached')return 'The bounded automatic step limit was reached.';
    if(value.startsWith('completion_state:'))return `Completion proof is ${value.split(':')[1].replaceAll('_',' ')}; dependent work remains stopped.`;
    if(value.startsWith('task_state:waiting_approval'))return 'Approval is required before Vishnu can continue.';
    if(value.startsWith('task_state:recovery_required')||value.startsWith('task_state:uncertain')||value.startsWith('task_state:recovering'))return 'Recovery or remote-state reconciliation is required before Vishnu can continue.';
    if(value.startsWith('task_state:verifying'))return 'Verification is still in progress.';
    if(value.startsWith('task_state:blocked')||value.startsWith('task_state:failed'))return 'The next WorkOrder is blocked and needs attention.';
    if(value.startsWith('plan_state:'))return `The WorkPlan is ${value.split(':')[1].replaceAll('_',' ')} and cannot auto-advance.`;
    if(value.startsWith('governed_stop:'))return 'The existing governed runtime stopped automatic progress because a policy, approval, capability, session, budget or safety requirement was not satisfied.';
    return value.replaceAll('_',' ').replaceAll(':',' · ');
  };

  function injectStyles(){
    if(document.getElementById('projectAutonomyStyles'))return;
    const style=document.createElement('style');style.id='projectAutonomyStyles';style.textContent=`
      .pa-mode-card{display:grid;gap:12px;padding:14px 15px;border:1px solid rgba(126,164,220,.16);border-radius:16px;background:linear-gradient(145deg,rgba(10,19,32,.78),rgba(7,14,24,.7));box-shadow:0 12px 32px rgba(0,0,0,.12)}
      .pa-mode-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.pa-mode-head h3{margin:0;font-size:.88rem}.pa-mode-head p{margin:4px 0 0;color:#8799b0;font-size:.72rem;line-height:1.45}.pa-mode-authority{font-size:.64rem;color:#6f829a;white-space:nowrap}
      .pa-mode-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.pa-mode-option{display:grid;gap:4px;text-align:left;min-height:76px;padding:10px 11px;border:1px solid rgba(128,165,220,.13);border-radius:13px;background:rgba(16,28,45,.55);color:#dfe9f7;cursor:pointer}.pa-mode-option b{font-size:.77rem}.pa-mode-option small{color:#8193aa;font-size:.64rem;line-height:1.35}.pa-mode-option[aria-pressed=true]{border-color:rgba(92,184,255,.5);background:rgba(30,67,102,.55);box-shadow:0 0 0 1px rgba(92,184,255,.1) inset}.pa-mode-option:disabled{cursor:default;opacity:.7}
      .pa-mode-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.pa-mode-state{display:flex;gap:7px;align-items:center;color:#94a5b9;font-size:.7rem}.pa-mode-dot{width:7px;height:7px;border-radius:50%;background:#7e8fa6}.pa-mode-dot.active{background:#61baff;box-shadow:0 0 10px rgba(97,186,255,.45)}.pa-mode-dot.shadow{background:#a0a8b7}.pa-mode-dot.assisted{background:#70d4ae}.pa-mode-stop{padding:9px 11px;border-left:2px solid rgba(255,193,100,.65);background:rgba(72,50,17,.2);color:#d9bb8b;font-size:.7rem;line-height:1.4}.pa-mode-loading{color:#8092a8;font-size:.72rem}
      @media(max-width:760px){.pa-mode-card{padding:12px;border-radius:14px}.pa-mode-head{display:grid}.pa-mode-authority{white-space:normal}.pa-mode-options{grid-template-columns:1fr}.pa-mode-option{min-height:0}.pa-mode-footer .project-btn{width:100%;min-height:44px}.pa-mode-footer{display:grid}.pa-mode-state{order:2}}
    `;document.head.append(style);
  }

  async function loadMode(projectId,{force=false}={}){
    if(!force&&modes.has(projectId))return modes.get(projectId);
    if(pending.has(projectId))return pending.get(projectId);
    const request=api(`/projects/${encodeURIComponent(projectId)}/work/autonomy`).then(data=>{modes.set(projectId,data);return data}).finally(()=>pending.delete(projectId));
    pending.set(projectId,request);return request;
  }
  const currentPlanId=projectId=>String(window.__vishnuCanonicalProjectWork?.snapshotCache?.get(projectId)?.p10_plan?.id||'');

  function cardMarkup(project,settings){
    const mode=String(settings?.mode||'assisted').toLowerCase(),definition=definitions[mode]||definitions.assisted,advance=lastAdvance.get(project.id),planId=currentPlanId(project.id);
    return `<div class="pa-mode-head"><div><h3>Project autonomy · ${esc(definition.title)}</h3><p>${esc(definition.description)}</p></div><span class="pa-mode-authority">Execution authority · existing P10/P6 runtime</span></div>
      <div class="pa-mode-options" role="group" aria-label="Project autonomy mode">${Object.entries(definitions).map(([key,item])=>`<button type="button" class="pa-mode-option" data-pa-mode="${key}" aria-pressed="${mode===key?'true':'false'}"><b>${esc(item.title)}</b><small>${esc(item.description)}</small></button>`).join('')}</div>
      ${advance?.stop_reason?`<div class="pa-mode-stop" role="status"><b>Vishnu stopped safely.</b> ${esc(stopCopy(advance.stop_reason))}</div>`:''}
      <div class="pa-mode-footer"><span class="pa-mode-state"><i class="pa-mode-dot ${esc(mode)}"></i>${esc(settings?.semantics?.automatic_execution?'Automatic advancement enabled':'Automatic advancement disabled')} · approvals and recovery remain authoritative</span>${mode==='active'&&planId?'<button type="button" class="project-btn primary" data-pa-advance>Continue now</button>':''}</div>`;
  }

  function wire(card,host,project,settings){
    card.querySelectorAll('[data-pa-mode]').forEach(button=>button.addEventListener('click',async()=>{
      const next=button.dataset.paMode;if(next===settings.mode)return;
      card.querySelectorAll('button').forEach(item=>item.disabled=true);
      try{
        const updated=await api(`/projects/${encodeURIComponent(project.id)}/work/autonomy`,{method:'PUT',body:JSON.stringify({mode:next})});
        modes.set(project.id,updated);lastAdvance.delete(project.id);showToast(`Project autonomy set to ${definitions[next]?.title||next}.`);renderCard(card,host,project,updated);
      }catch(error){showToast(error.message||'Project autonomy mode could not be changed.');card.querySelectorAll('button').forEach(item=>item.disabled=false)}
    }));
    card.querySelector('[data-pa-advance]')?.addEventListener('click',async event=>{
      const planId=currentPlanId(project.id);if(!planId)return;
      const button=event.currentTarget;button.disabled=true;button.textContent='Continuing…';
      try{
        const result=await api(`/projects/${encodeURIComponent(project.id)}/work/${encodeURIComponent(planId)}/advance`,{method:'POST',body:JSON.stringify({max_steps:10})});
        lastAdvance.set(project.id,result);showToast((result.executed_task_ids||[]).length?`Vishnu advanced ${result.executed_task_ids.length} WorkOrder${result.executed_task_ids.length===1?'':'s'}.`:'Vishnu stopped safely without dispatching new work.');
        if(typeof window.refreshCanonicalProjectWork==='function')await window.refreshCanonicalProjectWork(project.id);
        const refreshed=await loadMode(project.id,{force:true});renderCard(card,host,project,refreshed);
        if(window.projectCurrent?.id===project.id&&(window.projectTab==='plan'||window.projectTab==='live')&&typeof window.renderProjectTab==='function')window.renderProjectTab();
      }catch(error){showToast(error.message||'Vishnu could not continue this Project.');button.disabled=false;button.textContent='Continue now'}
    });
  }

  function renderCard(card,host,project,settings){
    if(!card.isConnected)return;
    card.dataset.autonomyLoaded='true';card.dataset.autonomyProject=String(project.id);card.dataset.autonomyMode=String(settings?.mode||'assisted');
    card.innerHTML=cardMarkup(project,settings);wire(card,host,project,settings);
  }
  function decorate(host,project){
    if(!host?.isConnected||!project?.id)return;
    const page=host.querySelector('.cw-page'),head=page?.querySelector('.cw-head');if(!page||!head)return;
    let card=page.querySelector('[data-project-autonomy-controls]');
    if(!card){card=document.createElement('section');card.className='pa-mode-card';card.dataset.projectAutonomyControls='true';card.innerHTML='<span class="pa-mode-loading">Loading Project autonomy policy…</span>';head.insertAdjacentElement('afterend',card)}
    const cached=modes.get(project.id);
    if(cached){
      if(card.dataset.autonomyLoaded==='true'&&card.dataset.autonomyProject===String(project.id)&&card.dataset.autonomyMode===String(cached.mode||'assisted'))return;
      renderCard(card,host,project,cached);return;
    }
    loadMode(project.id).then(settings=>{if(window.projectCurrent?.id===project.id&&card.isConnected)renderCard(card,host,project,settings)}).catch(error=>{if(card.isConnected){card.dataset.autonomyLoaded='error';card.innerHTML=`<div class="pa-mode-stop">Project autonomy policy could not be loaded. ${esc(error.message||'')}</div>`}});
  }
  function withinCard(target){const node=target?.nodeType===1?target:target?.parentElement;return Boolean(node?.closest?.('[data-project-autonomy-controls]'))}
  function watch(host,project){
    let record=observers.get(host);if(record){record.project=project;decorate(host,project);return}
    record={project,observer:null};const observer=new MutationObserver(mutations=>{if(mutations.length&&mutations.every(item=>withinCard(item.target)))return;queueMicrotask(()=>{if(!host.isConnected){observer.disconnect();return}decorate(host,record.project)})});record.observer=observer;observers.set(host,record);observer.observe(host,{childList:true,subtree:true});queueMicrotask(()=>decorate(host,project));
  }
  function wrap(name){const base=window[name];if(typeof base!=='function')return;window[name]=function(host,project,...rest){const value=base.call(this,host,project,...rest);watch(host,project);return value}}
  function install(){injectStyles();wrap('renderProjectPlan');wrap('renderProjectLive');window.__vishnuProjectAutonomyUI={installed:true,authority:'presentation_control_only',modeCache:modes,lastAdvance}}
  if(typeof window.renderProjectPlan==='function'&&typeof window.renderProjectLive==='function')install();else window.addEventListener('DOMContentLoaded',()=>setTimeout(install,0),{once:true});
})();

/* Global read-only awareness of canonical Project Work.
 * Source of truth: existing owner-scoped /projects and /projects/{id}/work GET APIs.
 * This adapter never executes, approves, pauses, resumes, cancels, or mutates work.
 */
(()=>{
  if(window.__vishnuGlobalWorkAwareness)return;
  window.__vishnuGlobalWorkAwareness={authority:'presentation_only',source:'canonical_project_work'};

  const MAX_PROJECTS=24;
  const REFRESH_MS=30000;
  const ACTIVE=new Set(['RUNNING','VERIFYING','RECOVERING','RETRYING']);
  const BLOCKED=new Set(['BLOCKED','UNCERTAIN','RECOVERY_REQUIRED','FAILED']);
  const DONE=new Set(['COMPLETED','CANCELLED']);
  let current={projects:[],workOrders:[],counts:{},state:'idle',updatedAt:null};
  let refreshTimer=0;

  const esc=value=>{const node=document.createElement('span');node.textContent=String(value??'');return node.innerHTML};
  const label=value=>String(value||'').replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
  const apiGet=async path=>{
    const response=await fetch('/iphone/api'+path,{credentials:'same-origin'});
    if(!response.ok)throw new Error('Global Work read failed ('+response.status+')');
    return response.json();
  };
  const taskTitle=task=>String(task?.title||task?.objective||task?.description||task?.id||'WorkOrder');
  const workerLabel=task=>String(task?.worker_type||task?.capability||task?.required_capability||task?.required_capabilities?.[0]||'worker');

  function summarize(projects,snapshots){
    const workOrders=[];
    const counts={active:0,verifying:0,approval:0,blocked:0,ready:0,completed:0,plannedProjects:0,activeProjects:0};
    snapshots.forEach(({project,snapshot})=>{
      if(!snapshot||snapshot.state!=='planned'||!snapshot.p10_plan)return;
      counts.plannedProjects+=1;
      const tasks=Array.isArray(snapshot.p10_plan.tasks)?snapshot.p10_plan.tasks:[];
      const completedIds=new Set(tasks.filter(task=>String(task.status||'').toUpperCase()==='COMPLETED').map(task=>String(task.id)));
      let projectAttention=false;
      tasks.forEach(task=>{
        const status=String(task.status||'UNKNOWN').toUpperCase();
        const dependencies=(task.dependencies||[]).map(String);
        const ready=status==='WAITING'&&dependencies.every(id=>completedIds.has(id));
        if(ACTIVE.has(status)){counts.active+=1;if(status==='VERIFYING')counts.verifying+=1;projectAttention=true}
        if(status==='WAITING_APPROVAL'){counts.approval+=1;projectAttention=true}
        if(BLOCKED.has(status)){counts.blocked+=1;projectAttention=true}
        if(ready)counts.ready+=1;
        if(status==='COMPLETED')counts.completed+=1;
        workOrders.push({
          id:String(task.id||''),
          projectId:String(project.id),
          projectName:String(project.name||'Project'),
          planId:String(snapshot.p10_plan.id||''),
          title:taskTitle(task),
          worker:workerLabel(task),
          status,
          ready,
          dependencies,
          updatedAt:task.updated_at||snapshot.live_work?.updated_at||project.updated_at||null,
        });
      });
      if(projectAttention||String(snapshot.live_work?.state||'').toUpperCase()==='RUNNING')counts.activeProjects+=1;
    });
    let state='idle';
    if(counts.blocked)state='blocked';
    else if(counts.approval)state='approval';
    else if(counts.verifying)state='verifying';
    else if(counts.active)state='working';
    else if(counts.ready)state='ready';
    return {projects,workOrders,counts,state,updatedAt:new Date().toISOString()};
  }

  async function load(){
    try{
      const data=await apiGet('/projects?status=all');
      const projects=(Array.isArray(data.projects)?data.projects:[]).filter(project=>project&&project.status!=='archived').slice(0,MAX_PROJECTS);
      const results=await Promise.allSettled(projects.map(async project=>({project,snapshot:await apiGet('/projects/'+encodeURIComponent(project.id)+'/work')})));
      current=summarize(projects,results.filter(result=>result.status==='fulfilled').map(result=>result.value));
      window.__vishnuGlobalWorkAwareness.snapshot=current;
      renderAll();
    }catch(error){
      window.__vishnuGlobalWorkAwareness.lastError=String(error?.message||error);
    }
  }

  function attentionOrders(){
    return current.workOrders.filter(order=>ACTIVE.has(order.status)||order.status==='WAITING_APPROVAL'||BLOCKED.has(order.status)||order.ready);
  }
  function statusClass(order){
    if(BLOCKED.has(order.status))return 'blocked';
    if(order.status==='WAITING_APPROVAL')return 'approval';
    if(order.status==='VERIFYING')return 'verifying';
    if(ACTIVE.has(order.status))return 'working';
    if(order.ready)return 'ready';
    if(DONE.has(order.status))return 'done';
    return 'queued';
  }
  function openLive(order){
    if(typeof openProject==='function')openProject(order.projectId,'live');
    else if(typeof openModule==='function')openModule('projects');
  }

  function ensureStyles(){
    if(document.getElementById('globalWorkAwarenessStyles'))return;
    const style=document.createElement('style');style.id='globalWorkAwarenessStyles';style.textContent=`
      .gwa-panel{width:min(920px,96%);margin:4px auto 12px;border:1px solid rgba(124,164,224,.18);border-radius:20px;background:linear-gradient(150deg,rgba(11,20,34,.82),rgba(8,14,24,.72));padding:14px 16px;box-shadow:0 16px 48px rgba(0,0,0,.18)}
      .gwa-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.gwa-head strong{display:block;font-size:.92rem}.gwa-head small{display:block;color:#7f8ba0;margin-top:4px;line-height:1.4}.gwa-state{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;border:1px solid rgba(127,174,236,.2);border-radius:999px;padding:5px 8px;color:#9fd4ff;white-space:nowrap}.gwa-state.blocked{color:#ff9fb2}.gwa-state.approval{color:#d3c3ff}.gwa-state.verifying{color:#8fe5c4}
      .gwa-metrics{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}.gwa-metric{border:1px solid rgba(129,164,218,.12);border-radius:999px;padding:5px 8px;color:#8c98ad;font-size:.69rem}.gwa-list{display:grid;gap:7px;margin-top:10px}.gwa-row{width:100%;border:1px solid rgba(129,164,218,.11);border-radius:13px;background:rgba(7,13,23,.62);color:#dbe5f5;padding:9px 11px;text-align:left;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;cursor:pointer}.gwa-row:hover{border-color:rgba(105,184,255,.28)}.gwa-row strong{font-size:.79rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gwa-row span{color:#8390a5;font-size:.68rem}.gwa-row em{font-style:normal;font-size:.66rem;color:#9fd4ff}.gwa-row em.blocked{color:#ff9fb2}.gwa-row em.approval{color:#d3c3ff}.gwa-row em.verifying{color:#8fe5c4}
      .gwa-today{margin:0 0 18px}.gwa-today .today-section-head{margin-bottom:8px}.gwa-today-count{color:#8c98ad;font-size:.76rem}.gwa-today-list{display:grid;gap:8px}.gwa-today-row{border:1px solid rgba(129,164,218,.12);border-radius:14px;background:rgba(7,13,23,.58);padding:11px 12px;color:inherit;text-align:left;cursor:pointer;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px}.gwa-dot{width:8px;height:8px;border-radius:50%;background:#69b8ff;box-shadow:0 0 12px rgba(105,184,255,.5)}.gwa-dot.blocked{background:#ff718d}.gwa-dot.approval{background:#9b84ff}.gwa-dot.verifying{background:#8fe5c4}.gwa-today-row strong{font-size:.82rem;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gwa-today-row small{display:block;color:#7f8ba0;margin-top:3px}.gwa-today-row em{font-style:normal;color:#93a2b8;font-size:.68rem;white-space:nowrap}
      @media(max-width:760px){.gwa-panel{width:100%;border-radius:16px;padding:12px}.gwa-row{grid-template-columns:minmax(0,1fr)}.gwa-row em{justify-self:start}.gwa-today-row{grid-template-columns:auto minmax(0,1fr)}.gwa-today-row em{grid-column:2}.gwa-head{align-items:center}}
    `;document.head.append(style);
  }

  function stateCopy(){
    const c=current.counts;
    if(current.state==='blocked')return ['Needs Attention',`${c.blocked} WorkOrder${c.blocked===1?' is':'s are'} blocked or require recovery.`];
    if(current.state==='approval')return ['Needs Approval',`${c.approval} WorkOrder${c.approval===1?' is':'s are'} waiting for your approval.`];
    if(current.state==='verifying')return ['Verifying',`${c.verifying} WorkOrder${c.verifying===1?' is':'s are'} being verified.`];
    if(current.state==='working')return ['Working',`${c.active} WorkOrder${c.active===1?' is':'s are'} active across ${Math.max(1,c.activeProjects)} project${c.activeProjects===1?'':'s'}.`];
    if(current.state==='ready')return ['Ready',`${c.ready} WorkOrder${c.ready===1?' is':'s are'} ready to continue.`];
    return null;
  }

  function renderLivingState(){
    if(typeof stateName==='undefined'||!['idle','active','background'].includes(stateName))return;
    const copy=stateCopy();if(!copy)return;
    const heading=document.getElementById('stateLabel'),detail=document.getElementById('status');
    if(heading)heading.textContent=copy[0];if(detail)detail.textContent=copy[1];
    document.body.dataset.globalWorkState=current.state;
  }

  function renderHome(){
    const anchor=document.getElementById('homeProjectsSection');if(!anchor)return;
    let panel=document.getElementById('globalWorkPulse');
    const orders=attentionOrders();
    if(!current.counts.plannedProjects&&!orders.length){panel?.remove();return}
    if(!panel){panel=document.createElement('section');panel.id='globalWorkPulse';panel.className='gwa-panel';panel.setAttribute('aria-live','polite');anchor.parentNode.insertBefore(panel,anchor)}
    const c=current.counts,copy=stateCopy()||['Project Work',`${c.plannedProjects} planned project${c.plannedProjects===1?'':'s'}.`];
    panel.innerHTML=`<div class="gwa-head"><div><strong>${esc(copy[0]==='Working'?'Vishnu is working':copy[0])}</strong><small>${esc(copy[1])} Canonical Work state only.</small></div><span class="gwa-state ${esc(current.state)}">${esc(label(current.state))}</span></div><div class="gwa-metrics"><span class="gwa-metric">${c.active} active</span><span class="gwa-metric">${c.approval} approval</span><span class="gwa-metric">${c.blocked} blocked</span><span class="gwa-metric">${c.ready} ready</span></div>${orders.length?`<div class="gwa-list">${orders.slice(0,3).map(order=>`<button type="button" class="gwa-row" data-gwa-project="${esc(order.projectId)}" data-gwa-order="${esc(order.id)}"><span><strong>${esc(order.title)}</strong><span>${esc(order.projectName)} · ${esc(order.worker)}</span></span><em class="${statusClass(order)}">${esc(order.ready?'Ready':label(order.status))}</em></button>`).join('')}</div>`:''}`;
    panel.querySelectorAll('[data-gwa-order]').forEach(button=>button.onclick=()=>{const order=orders.find(item=>item.id===button.dataset.gwaOrder&&item.projectId===button.dataset.gwaProject);if(order)openLive(order)});
  }

  function renderToday(){
    const tasksSection=document.getElementById('todayTasksSection');if(!tasksSection)return;
    let section=document.getElementById('globalWorkTodaySection');
    const orders=attentionOrders();
    const filter=typeof todayScreenFilter!=='undefined'?todayScreenFilter:'all';
    if(!orders.length){section?.remove();return}
    if(!section){section=document.createElement('section');section.id='globalWorkTodaySection';section.className='today-section gwa-today';tasksSection.parentNode.insertBefore(section,tasksSection)}
    section.classList.toggle('hidden',filter==='meetings');
    section.innerHTML=`<div class="today-section-head"><h2>Vishnu work</h2><span class="gwa-today-count">${orders.length} current WorkOrder${orders.length===1?'':'s'}</span></div><div class="gwa-today-list">${orders.slice(0,filter==='all'?5:20).map(order=>`<button type="button" class="gwa-today-row" data-gwa-today-project="${esc(order.projectId)}" data-gwa-today-order="${esc(order.id)}"><i class="gwa-dot ${statusClass(order)}" aria-hidden="true"></i><span><strong>${esc(order.title)}</strong><small>${esc(order.projectName)} · ${esc(order.worker)}</small></span><em>${esc(order.ready?'Ready':label(order.status))}</em></button>`).join('')}</div>`;
    section.querySelectorAll('[data-gwa-today-order]').forEach(button=>button.onclick=()=>{const order=orders.find(item=>item.id===button.dataset.gwaTodayOrder&&item.projectId===button.dataset.gwaTodayProject);if(order)openLive(order)});
  }

  function renderAll(){ensureStyles();renderHome();renderToday();renderLivingState()}
  function schedule(){clearTimeout(refreshTimer);refreshTimer=setTimeout(async()=>{await load();schedule()},REFRESH_MS)}
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load()});
  document.addEventListener('click',event=>{if(event.target.closest?.('.today-tab,[data-today-summary],[data-today-see],#sidebarToday,#vToday'))setTimeout(renderToday,0)});
  window.addEventListener('focus',load);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{load();schedule()},{once:true});else{load();schedule()}
})();

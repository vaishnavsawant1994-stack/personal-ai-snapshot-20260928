/* Global read-only awareness of canonical Project Work and owner attention.
 * Sources of truth: owner-scoped GET /iphone/api/work/summary and /iphone/api/work/attention.
 * This adapter never executes, approves, pauses, resumes, cancels, retries, recovers, or mutates work.
 */
(()=>{
  if(window.__vishnuGlobalWorkAwareness)return;
  window.__vishnuGlobalWorkAwareness={authority:'presentation_only',source:'canonical_project_work'};

  const REFRESH_MS=30000;
  const ACTIVE=new Set(['RUNNING','VERIFYING','RECOVERING','RETRYING']);
  const BLOCKED=new Set(['BLOCKED','UNCERTAIN','RECOVERY_REQUIRED','FAILED']);
  const DONE=new Set(['COMPLETED','CANCELLED']);
  let current={authority:'read_only_projection',projects:[],work_orders:[],counts:{},living:{state:'idle',detail:''}};
  let attention={authority:'read_only_projection',counts:{total:0,approval:0,recovery:0,review:0,blocked:0,urgent:0},items:[]};
  let refreshTimer=0,overlayApplied=false,deepLinkApplied=false;

  const esc=value=>{const node=document.createElement('span');node.textContent=String(value??'');return node.innerHTML};
  const label=value=>String(value||'').replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
  const apiGet=async path=>{
    const response=await fetch('/iphone/api'+path,{credentials:'same-origin'});
    if(!response.ok)throw new Error('Global Work read failed ('+response.status+')');
    return response.json();
  };

  async function load(){
    try{
      const [summary,attentionSnapshot]=await Promise.all([apiGet('/work/summary'),apiGet('/work/attention')]);
      if(summary?.authority!=='read_only_projection')throw new Error('Unexpected Global Work authority');
      if(attentionSnapshot?.authority!=='read_only_projection')throw new Error('Unexpected Work attention authority');
      current=summary;attention=attentionSnapshot;
      window.__vishnuGlobalWorkAwareness.snapshot=current;
      window.__vishnuGlobalWorkAwareness.attention=attention;
      renderAll();
      applyInboundDeepLink();
    }catch(error){
      window.__vishnuGlobalWorkAwareness.lastError=String(error?.message||error);
    }
  }

  function normalizeOrder(order){
    return {
      id:String(order?.task_id||order?.work_order_id||''),
      workOrderId:String(order?.work_order_id||''),
      projectId:String(order?.project_id||''),
      projectName:String(order?.project_name||'Project'),
      planId:String(order?.plan_id||''),
      title:String(order?.title||order?.objective||order?.task_id||'WorkOrder'),
      worker:String(order?.worker_type||'worker'),
      status:String(order?.status||'UNKNOWN').toUpperCase(),
      ready:Boolean(order?.ready),
    };
  }
  function attentionOrders(){
    return (Array.isArray(current.work_orders)?current.work_orders:[]).map(normalizeOrder).filter(order=>ACTIVE.has(order.status)||order.status==='WAITING_APPROVAL'||BLOCKED.has(order.status)||order.ready);
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
  function canonicalAttentionCount(){return Math.max(0,Number(attention?.counts?.total||0))}

  function ensureStyles(){
    if(document.getElementById('globalWorkAwarenessStyles'))return;
    const style=document.createElement('style');style.id='globalWorkAwarenessStyles';style.textContent=`
      .gwa-panel{width:min(920px,96%);margin:4px auto 12px;border:1px solid rgba(124,164,224,.18);border-radius:20px;background:linear-gradient(150deg,rgba(11,20,34,.82),rgba(8,14,24,.72));padding:14px 16px;box-shadow:0 16px 48px rgba(0,0,0,.18)}
      .gwa-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.gwa-head strong{display:block;font-size:.92rem}.gwa-head small{display:block;color:#7f8ba0;margin-top:4px;line-height:1.4}.gwa-state{font-size:.68rem;letter-spacing:.08em;text-transform:uppercase;border:1px solid rgba(127,174,236,.2);border-radius:999px;padding:5px 8px;color:#9fd4ff;white-space:nowrap}.gwa-state.attention{color:#ff9fb2}.gwa-state.approval{color:#d3c3ff}.gwa-state.verifying{color:#8fe5c4}
      .gwa-metrics{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}.gwa-metric{border:1px solid rgba(129,164,218,.12);border-radius:999px;padding:5px 8px;color:#8c98ad;font-size:.69rem}.gwa-metric.attention{color:#ffb0c0;border-color:rgba(255,113,141,.22)}.gwa-list{display:grid;gap:7px;margin-top:10px}.gwa-row{width:100%;border:1px solid rgba(129,164,218,.11);border-radius:13px;background:rgba(7,13,23,.62);color:#dbe5f5;padding:9px 11px;text-align:left;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 12px;cursor:pointer}.gwa-row:hover{border-color:rgba(105,184,255,.28)}.gwa-row strong{font-size:.79rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gwa-row span{color:#8390a5;font-size:.68rem}.gwa-row em{font-style:normal;font-size:.66rem;color:#9fd4ff}.gwa-row em.blocked{color:#ff9fb2}.gwa-row em.approval{color:#d3c3ff}.gwa-row em.verifying{color:#8fe5c4}
      .gwa-today{margin:0 0 18px}.gwa-today .today-section-head{margin-bottom:8px}.gwa-today-count{color:#8c98ad;font-size:.76rem}.gwa-today-list{display:grid;gap:8px}.gwa-today-row{border:1px solid rgba(129,164,218,.12);border-radius:14px;background:rgba(7,13,23,.58);padding:11px 12px;color:inherit;text-align:left;cursor:pointer;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px}.gwa-dot{width:8px;height:8px;border-radius:50%;background:#69b8ff;box-shadow:0 0 12px rgba(105,184,255,.5)}.gwa-dot.blocked{background:#ff718d}.gwa-dot.approval{background:#9b84ff}.gwa-dot.verifying{background:#8fe5c4}.gwa-today-row strong{font-size:.82rem;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gwa-today-row small{display:block;color:#7f8ba0;margin-top:3px}.gwa-today-row em{font-style:normal;color:#93a2b8;font-size:.68rem;white-space:nowrap}
      .gwa-nav-count{margin-left:auto;min-width:20px;height:20px;padding:0 6px;border-radius:999px;display:inline-flex;align-items:center;justify-content:center;background:rgba(255,113,141,.18);border:1px solid rgba(255,113,141,.3);color:#ffb7c5;font-size:.65rem;font-weight:650;font-variant-numeric:tabular-nums}.gwa-nav-count[hidden]{display:none!important}.gwa-deep-target{outline:2px solid rgba(105,184,255,.65)!important;outline-offset:3px!important}
      @media(max-width:760px){.gwa-panel{width:100%;border-radius:16px;padding:12px}.gwa-row{grid-template-columns:minmax(0,1fr)}.gwa-row em{justify-self:start}.gwa-today-row{grid-template-columns:auto minmax(0,1fr)}.gwa-today-row em{grid-column:2}.gwa-head{align-items:center}}
    `;document.head.append(style);
  }

  function stateCopy(){
    const total=canonicalAttentionCount(),urgent=Number(attention?.counts?.urgent||0);
    if(total&&urgent)return ['Needs Attention',`${total} owner attention item${total===1?'':'s'} require review.`];
    const state=String(current.living?.state||'idle');
    const detail=String(current.living?.detail||'');
    if(state==='approval')return ['Needs Approval',detail];
    if(state==='attention')return ['Needs Attention',detail];
    if(state==='verifying')return ['Verifying',detail];
    if(state==='background')return ['Working',detail];
    if(state==='ready')return ['Ready',detail];
    return null;
  }

  function renderLivingState(){
    if(typeof stateName==='undefined'||!['idle','active','background'].includes(stateName)){overlayApplied=false;return}
    const copy=stateCopy();
    if(!copy){
      if(overlayApplied&&typeof setState==='function')setState(stateName);
      overlayApplied=false;
      delete document.body.dataset.globalWorkState;
      return;
    }
    const heading=document.getElementById('stateLabel'),detail=document.getElementById('status');
    if(heading)heading.textContent=copy[0];if(detail)detail.textContent=copy[1];
    document.body.dataset.globalWorkState=canonicalAttentionCount()?'needs_attention':String(current.living?.state||'idle');
    overlayApplied=true;
  }

  function renderAttentionBadges(){
    const total=canonicalAttentionCount();
    document.body.dataset.workAttentionCount=String(total);
    const inbox=document.getElementById('sidebarInboxCount');
    if(inbox){inbox.textContent=String(total);inbox.classList.toggle('hidden',!total);inbox.setAttribute('aria-label',`${total} item${total===1?'':'s'} needing attention`)}
    const targets=[
      document.querySelector('[data-app-module="projects"]'),
      document.querySelector('[data-app-module="approvals"]'),
      document.querySelector('[data-owner-page="approvals"]'),
      document.querySelector('[data-app-module="notifications"]'),
      document.querySelector('[data-settings-section="notifications"]'),
    ].filter(Boolean);
    const unique=[...new Set(targets)];
    unique.forEach((target,index)=>{
      let badge=target.querySelector(':scope > .gwa-nav-count');
      if(!badge){badge=document.createElement('span');badge.className='gwa-nav-count';badge.dataset.gwaBadge=String(index);target.append(badge)}
      badge.textContent=String(total);badge.hidden=!total;badge.setAttribute('aria-label',`${total} owner attention item${total===1?'':'s'}`);
    });
  }

  function renderHome(){
    const anchor=document.getElementById('homeProjectsSection');if(!anchor)return;
    let panel=document.getElementById('globalWorkPulse');
    const orders=attentionOrders(),c=current.counts||{},a=attention.counts||{};
    if(!Number(current.projects_with_work||0)&&!orders.length&&!canonicalAttentionCount()){panel?.remove();return}
    if(!panel){panel=document.createElement('section');panel.id='globalWorkPulse';panel.className='gwa-panel';panel.setAttribute('aria-live','polite');anchor.parentNode.insertBefore(panel,anchor)}
    const copy=stateCopy()||['Project Work',`${Number(current.projects_with_work||0)} planned project${Number(current.projects_with_work||0)===1?'':'s'}.`];
    const state=canonicalAttentionCount()?'attention':String(current.living?.state||'idle');
    panel.innerHTML=`<div class="gwa-head"><div><strong>${esc(copy[0]==='Working'?'Vishnu is working':copy[0])}</strong><small>${esc(copy[1])} Canonical Work state only.</small></div><span class="gwa-state ${esc(state)}">${esc(label(state))}</span></div><div class="gwa-metrics"><span class="gwa-metric attention">${Number(a.total||0)} need attention</span><span class="gwa-metric">${Number(c.active||0)} active</span><span class="gwa-metric">${Number(a.approval||0)} approval</span><span class="gwa-metric">${Number(a.recovery||0)} recovery</span><span class="gwa-metric">${Number(a.review||0)} review</span><span class="gwa-metric">${Number(a.blocked||0)} blocked</span><span class="gwa-metric">${Number(c.ready||0)} ready</span></div>${orders.length?`<div class="gwa-list">${orders.slice(0,3).map(order=>`<button type="button" class="gwa-row" data-gwa-project="${esc(order.projectId)}" data-gwa-order="${esc(order.id)}"><span><strong>${esc(order.title)}</strong><span>${esc(order.projectName)} · ${esc(order.worker)}</span></span><em class="${statusClass(order)}">${esc(order.ready?'Ready':label(order.status))}</em></button>`).join('')}</div>`:''}`;
    panel.querySelectorAll('[data-gwa-order]').forEach(button=>button.onclick=()=>{const order=orders.find(item=>item.id===button.dataset.gwaOrder&&item.projectId===button.dataset.gwaProject);if(order)openLive(order)});
  }

  function renderToday(){
    const tasksSection=document.getElementById('todayTasksSection');if(!tasksSection)return;
    let section=document.getElementById('globalWorkTodaySection');
    const orders=attentionOrders();
    const filter=typeof todayScreenFilter!=='undefined'?todayScreenFilter:'all';
    if(!orders.length&&!canonicalAttentionCount()){section?.remove();return}
    if(!section){section=document.createElement('section');section.id='globalWorkTodaySection';section.className='today-section gwa-today';tasksSection.parentNode.insertBefore(section,tasksSection)}
    section.classList.toggle('hidden',filter==='meetings');
    section.innerHTML=`<div class="today-section-head"><h2>Vishnu work</h2><span class="gwa-today-count">${canonicalAttentionCount()} attention · ${orders.length} current WorkOrder${orders.length===1?'':'s'}</span></div><div class="gwa-today-list">${orders.slice(0,filter==='all'?5:20).map(order=>`<button type="button" class="gwa-today-row" data-gwa-today-project="${esc(order.projectId)}" data-gwa-today-order="${esc(order.id)}"><i class="gwa-dot ${statusClass(order)}" aria-hidden="true"></i><span><strong>${esc(order.title)}</strong><small>${esc(order.projectName)} · ${esc(order.worker)}</small></span><em>${esc(order.ready?'Ready':label(order.status))}</em></button>`).join('')}</div>`;
    section.querySelectorAll('[data-gwa-today-order]').forEach(button=>button.onclick=()=>{const order=orders.find(item=>item.id===button.dataset.gwaTodayOrder&&item.projectId===button.dataset.gwaTodayProject);if(order)openLive(order)});
  }

  function highlightDeepTarget(workOrderId){
    if(!workOrderId)return;
    const escaped=globalThis.CSS?.escape?CSS.escape(workOrderId):workOrderId.replace(/[^a-zA-Z0-9_-]/g,'');
    setTimeout(()=>{
      const target=document.querySelector(`[data-work-order-id="${escaped}"],[data-work-order="${escaped}"],[data-workorder-id="${escaped}"]`);
      if(!target)return;target.classList.add('gwa-deep-target');target.scrollIntoView({block:'center',behavior:'smooth'});setTimeout(()=>target.classList.remove('gwa-deep-target'),2400);
    },120);
  }

  async function applyInboundDeepLink(){
    if(deepLinkApplied)return;
    const params=new URL(location.href).searchParams,project=params.get('project'),section=params.get('section'),workOrder=params.get('work_order'),approval=params.get('approval');
    if(!project&&!approval)return;
    deepLinkApplied=true;
    try{
      if(project){
        if(typeof openModule==='function')openModule('projects');
        if(typeof openProject==='function')await openProject(project,['overview','chat','plan','files','approvals','discussions','activity','live','status','structure'].includes(section)?section:'live');
        highlightDeepTarget(workOrder);
        return;
      }
      if(section==='approvals'&&approval&&typeof openProjectApprovalReview==='function'){
        await openProjectApprovalReview();
        const escaped=globalThis.CSS?.escape?CSS.escape(approval):approval.replace(/[^a-zA-Z0-9_-]/g,'');
        setTimeout(()=>document.querySelector(`[data-approval-open="${escaped}"]`)?.click(),0);
      }
    }catch(error){window.__vishnuGlobalWorkAwareness.deepLinkError=String(error?.message||error)}
  }

  window.__vishnuGlobalWorkAwareness.openAttention=async item=>{
    if(!item||typeof item!=='object')return false;
    const raw=String(item.deep_link||'');if(!raw.startsWith('/iphone/'))return false;
    const url=new URL(raw,location.origin);history.replaceState(null,'',url.pathname+url.search);deepLinkApplied=false;await applyInboundDeepLink();return true;
  };

  function renderAll(){ensureStyles();renderHome();renderToday();renderAttentionBadges();renderLivingState()}
  function schedule(){clearTimeout(refreshTimer);refreshTimer=setTimeout(async()=>{await load();schedule()},REFRESH_MS)}
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load()});
  document.addEventListener('click',event=>{if(event.target.closest?.('.today-tab,[data-today-summary],[data-today-see],#sidebarToday,#vToday'))setTimeout(renderToday,0)});
  window.addEventListener('focus',load);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{load();schedule()},{once:true});else{load();schedule()}
})();

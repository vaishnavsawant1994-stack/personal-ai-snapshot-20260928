/* Unified owner Attention Center over canonical Work attention.
 * Read-only projection: all decisions/actions stay with their existing authorities.
 */
(()=>{
  if(window.__vishnuWorkAttentionCenter?.installed)return;
  const esc=value=>{const node=document.createElement('span');node.textContent=String(value??'');return node.innerHTML};
  const label=value=>String(value||'').replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
  const FILTERS={
    all:{label:'All',kinds:null},
    approvals:{label:'Approvals',kinds:new Set(['approval_required','owner_decision_required','reauthentication_required'])},
    recovery:{label:'Recovery',kinds:new Set(['recovery_required','uncertain_effect'])},
    blocked:{label:'Blocked',kinds:new Set(['blocked','capability_unavailable'])},
    verification:{label:'Verification',kinds:new Set(['verification_failed','retest_required'])},
    review:{label:'Review',kinds:new Set(['review_failed','replan_required'])},
    claims:{label:'Claims',kinds:new Set(['claim_unsupported'])},
  };
  let shell=null,currentFilter='all',snapshot={authority:'read_only_projection',items:[],counts:{}},requestSeq=0,lastFocus=null;

  function injectStyles(){
    if(document.getElementById('workAttentionCenterStyles'))return;
    const style=document.createElement('style');style.id='workAttentionCenterStyles';style.textContent=`
      .wac-shell{position:fixed;inset:0;z-index:1850;display:grid;place-items:center;padding:clamp(14px,3vw,34px);background:rgba(2,7,13,.66);backdrop-filter:blur(8px)}
      .wac-panel{width:min(1040px,96vw);max-height:min(860px,92dvh);display:flex;flex-direction:column;overflow:hidden;border:1px solid rgba(131,165,218,.2);border-radius:22px;background:rgba(6,13,23,.98);box-shadow:0 36px 110px rgba(0,0,0,.52)}
      .wac-head{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding:20px 22px 14px;border-bottom:1px solid rgba(131,165,218,.12)}.wac-head h2{margin:0;font-size:1.24rem}.wac-head p{margin:5px 0 0;color:#8b9cb1;font-size:.76rem;line-height:1.45}.wac-close{width:38px;height:38px;border-radius:12px;border:1px solid rgba(130,164,216,.15);background:rgba(18,30,48,.7);color:#e8f1fd;font-size:1.2rem}
      .wac-toolbar{display:flex;gap:7px;flex-wrap:wrap;padding:12px 22px;border-bottom:1px solid rgba(131,165,218,.1)}.wac-filter{border:1px solid rgba(130,164,216,.14);background:rgba(16,28,45,.55);color:#9daec1;border-radius:999px;padding:7px 10px;font-size:.69rem}.wac-filter[aria-pressed=true]{color:#eaf4ff;border-color:rgba(91,181,255,.45);background:rgba(29,66,101,.55)}.wac-filter b{margin-left:5px;color:#7dc8ff;font-weight:600}
      .wac-scroll{overflow:auto;padding:15px 22px 30px}.wac-list{display:grid;gap:10px}.wac-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px 14px;padding:14px;border:1px solid rgba(130,164,216,.13);border-radius:16px;background:rgba(10,19,32,.66)}.wac-card-head{min-width:0}.wac-card h3{margin:0;font-size:.86rem}.wac-project{margin-top:4px;color:#8294aa;font-size:.68rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.wac-severity{align-self:start;border:1px solid rgba(130,164,216,.16);border-radius:999px;padding:5px 8px;font-size:.63rem;color:#a5b5c8}.wac-severity.critical,.wac-severity.urgent{color:#ff9caf;border-color:rgba(255,113,141,.28)}.wac-severity.attention{color:#ffd07b}.wac-reason{grid-column:1/-1;margin:0;color:#b1bfd0;font-size:.74rem;line-height:1.5}.wac-meta{grid-column:1/-1;display:flex;gap:7px;flex-wrap:wrap}.wac-meta span{font-size:.63rem;color:#7f90a6;border:1px solid rgba(130,164,216,.1);border-radius:999px;padding:4px 7px}.wac-action{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:2px;padding-top:10px;border-top:1px solid rgba(130,164,216,.09)}.wac-action small{color:#75879f;font-size:.64rem;line-height:1.4}.wac-action button{border:1px solid rgba(89,180,255,.28);background:rgba(30,69,106,.52);color:#dff2ff;border-radius:11px;padding:8px 10px;font-size:.69rem;white-space:nowrap}.wac-empty,.wac-loading,.wac-error{text-align:center;padding:44px 20px;color:#8798ad}.wac-error{color:#ffc0cc}.wac-open-button{border:1px solid rgba(105,184,255,.25);background:rgba(24,54,83,.5);color:#a8d9ff;border-radius:999px;padding:6px 9px;font-size:.67rem;cursor:pointer}
      body.wac-open{overflow:hidden}
      @media(max-width:760px){.wac-shell{display:block;padding:0;background:#06101b;backdrop-filter:none}.wac-panel{width:100%;height:100dvh;max-height:none;border:0;border-radius:0;box-shadow:none}.wac-head{padding:16px 15px 12px}.wac-toolbar{padding:10px 14px;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}.wac-scroll{padding:12px 14px 28px}.wac-card{grid-template-columns:minmax(0,1fr)}.wac-severity{justify-self:start}.wac-action{display:grid}.wac-action button{min-height:42px;width:100%}}
    `;document.head.append(style);
  }
  const countsByFilter=()=>{const items=snapshot.items||[];return Object.fromEntries(Object.entries(FILTERS).map(([key,filter])=>[key,filter.kinds?items.filter(item=>filter.kinds.has(String(item.kind||''))).length:items.length]))};
  function filtered(){const f=FILTERS[currentFilter]||FILTERS.all;return f.kinds?(snapshot.items||[]).filter(item=>f.kinds.has(String(item.kind||''))):snapshot.items||[]}
  function timeLabel(value){if(!value)return 'Time unavailable';const when=typeof value==='number'?new Date(value*1000):new Date(value);if(Number.isNaN(when.getTime()))return String(value);const delta=Date.now()-when.getTime(),mins=Math.max(0,Math.floor(delta/60000));if(mins<1)return 'Just now';if(mins<60)return `${mins}m ago`;const hours=Math.floor(mins/60);if(hours<24)return `${hours}h ago`;return `${Math.floor(hours/24)}d ago`}
  function actionLabel(item){const map={review_approval:'Review approval',reconcile_recovery:'Review recovery',inspect_evidence:'Inspect evidence',inspect_plan:'Inspect plan',inspect_work:'Inspect WorkOrder'};return map[item.action_type]||'Open safe next action'}
  function ensureShell(){
    if(shell?.isConnected)return shell;
    shell=document.createElement('div');shell.className='wac-shell';shell.hidden=true;shell.innerHTML='<section class="wac-panel" role="dialog" aria-modal="true" aria-labelledby="wacTitle"><header class="wac-head"><div><h2 id="wacTitle">Attention Center</h2><p>One owner queue for approvals, recovery, blockers, verification, review and claims. Decision authorities remain unchanged.</p></div><button type="button" class="wac-close" aria-label="Close Attention Center">×</button></header><div class="wac-toolbar" role="group" aria-label="Attention filters"></div><div class="wac-scroll"><div class="wac-loading">Loading canonical owner attention…</div></div></section>';
    document.body.append(shell);shell.querySelector('.wac-close').addEventListener('click',close);shell.addEventListener('click',event=>{if(event.target===shell)close()});return shell;
  }
  function render(){
    const root=ensureShell(),counts=countsByFilter();root.querySelector('.wac-toolbar').innerHTML=Object.entries(FILTERS).map(([key,f])=>`<button type="button" class="wac-filter" data-wac-filter="${key}" aria-pressed="${currentFilter===key?'true':'false'}">${esc(f.label)} <b>${counts[key]}</b></button>`).join('');
    root.querySelectorAll('[data-wac-filter]').forEach(button=>button.addEventListener('click',()=>{currentFilter=button.dataset.wacFilter;render()}));
    const items=filtered(),host=root.querySelector('.wac-scroll');
    if(!items.length){host.innerHTML='<div class="wac-empty">No attention items in this filter.</div>';return}
    host.innerHTML=`<div class="wac-list">${items.map(item=>`<article class="wac-card" data-attention-id="${esc(item.id)}"><div class="wac-card-head"><h3>${esc(item.title||label(item.kind))}</h3><div class="wac-project">${esc(item.project_name||'Project')} · ${esc(item.work_order_title||item.summary||'Work')}</div></div><span class="wac-severity ${esc(String(item.severity||'info').toLowerCase())}">${esc(label(item.severity||'info'))}</span><p class="wac-reason">${esc(item.reason||item.summary||'This governed work needs owner attention.')}</p><div class="wac-meta"><span>Authority · ${esc(label(item.authority||'unknown'))}</span><span>${esc(timeLabel(item.updated_at||item.created_at))}</span>${item.expected_effect?`<span>Effect · ${esc(item.expected_effect)}</span>`:''}${item.requires_reauthentication?'<span>Fresh authentication required</span>':''}</div><div class="wac-action"><small>Safe next action follows the existing ${esc(label(item.authority||'governed'))} authority. This screen never approves, retries or reconciles work itself.</small><button type="button" data-wac-action="${esc(item.id)}">${esc(actionLabel(item))} →</button></div></article>`).join('')}</div>`;
    host.querySelectorAll('[data-wac-action]').forEach(button=>button.addEventListener('click',()=>{const item=(snapshot.items||[]).find(row=>String(row.id)===button.dataset.wacAction);if(!item)return;close();if(item.deep_link){location.assign(item.deep_link);return}if(item.project_id&&typeof openProject==='function'){openProject(item.project_id,'live');return}location.assign('/iphone/')}));
  }
  async function load(){const seq=++requestSeq;const response=await fetch('/iphone/api/work/attention?limit=200',{credentials:'same-origin'});if(!response.ok)throw new Error(`Attention Center read failed (${response.status})`);const data=await response.json();if(seq!==requestSeq)return;if(data?.authority!=='read_only_projection')throw new Error('Unexpected Attention Center authority');snapshot=data;window.__vishnuWorkAttentionCenter.snapshot=data;render()}
  async function open(filter='all'){currentFilter=FILTERS[filter]?filter:'all';lastFocus=document.activeElement;const root=ensureShell();root.hidden=false;document.body.classList.add('wac-open');root.querySelector('.wac-scroll').innerHTML='<div class="wac-loading">Loading canonical owner attention…</div>';root.querySelector('.wac-close').focus();try{await load()}catch(error){root.querySelector('.wac-scroll').innerHTML=`<div class="wac-error">${esc(error.message||'Attention Center could not be loaded.')}</div>`}}
  function close(){if(!shell)return;shell.hidden=true;document.body.classList.remove('wac-open');lastFocus?.focus?.()}
  function injectEntryPoints(){
    const pulse=document.getElementById('globalWorkPulse');if(pulse&&!pulse.querySelector('[data-open-work-attention]')){const head=pulse.querySelector('.gwa-head');if(head){const button=document.createElement('button');button.type='button';button.className='wac-open-button';button.dataset.openWorkAttention='all';button.textContent='Attention Center';head.append(button)}}
    const today=document.getElementById('globalWorkTodaySection');if(today&&!today.querySelector('[data-open-work-attention]')){const head=today.querySelector('.today-section-head');if(head){const button=document.createElement('button');button.type='button';button.className='wac-open-button';button.dataset.openWorkAttention='all';button.textContent='Open Attention';head.append(button)}}
  }
  document.addEventListener('click',event=>{const trigger=event.target.closest?.('[data-open-work-attention]');if(trigger){event.preventDefault();open(trigger.dataset.openWorkAttention||'all')}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&shell&&!shell.hidden){event.preventDefault();close()}});
  const observer=new MutationObserver(()=>queueMicrotask(injectEntryPoints));observer.observe(document.body,{childList:true,subtree:true});
  injectStyles();queueMicrotask(injectEntryPoints);window.__vishnuWorkAttentionCenter={installed:true,authority:'read_only_projection',open,close,get snapshot(){return snapshot}};
})();

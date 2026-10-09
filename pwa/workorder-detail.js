/* Full WorkOrder inspection drawer/full-screen surface.
 * Read-only presentation over the authoritative aggregate API.
 */
(()=>{
  if(window.__vishnuWorkOrderDetail?.installed)return;
  const esc=value=>typeof prEsc==='function'?prEsc(value):String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const label=value=>String(value??'—').replaceAll('_',' ').replace(/\b\w/g,ch=>ch.toUpperCase());
  let shell=null,lastFocus=null,requestSeq=0;

  function injectStyles(){
    if(document.getElementById('workOrderDetailStyles'))return;
    const style=document.createElement('style');style.id='workOrderDetailStyles';style.textContent=`
      .wo-detail-shell{position:fixed;inset:0;z-index:1800;display:grid;grid-template-columns:1fr minmax(520px,680px);background:rgba(2,7,13,.52);backdrop-filter:blur(4px)}
      .wo-detail-backdrop{grid-column:1;background:transparent;border:0}.wo-detail-panel{grid-column:2;display:flex;flex-direction:column;min-width:0;height:100dvh;background:rgba(6,13,23,.98);border-left:1px solid rgba(130,164,216,.18);box-shadow:-28px 0 80px rgba(0,0,0,.42);overflow:hidden}
      .wo-detail-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:20px 22px 14px;border-bottom:1px solid rgba(130,164,216,.12)}.wo-detail-head h2{margin:0;font-size:1.22rem}.wo-detail-head p{margin:5px 0 0;color:#8fa0b5;font-size:.76rem;line-height:1.45}.wo-detail-close{width:38px;height:38px;border-radius:12px;border:1px solid rgba(130,164,216,.15);background:rgba(18,30,48,.7);color:#e8f1fd;font-size:1.2rem}
      .wo-detail-scroll{overflow:auto;padding:16px 22px 34px;display:grid;gap:13px}.wo-detail-status{display:flex;gap:7px;flex-wrap:wrap}.wo-detail-pill{display:inline-flex;align-items:center;min-height:27px;padding:4px 8px;border-radius:999px;border:1px solid rgba(130,164,216,.17);background:rgba(13,24,40,.72);font-size:.67rem;color:#afbdd0}.wo-detail-pill.completed{color:#78d8ae}.wo-detail-pill.verifying,.wo-detail-pill.reviewing,.wo-detail-pill.running{color:#7dc8ff}.wo-detail-pill.blocked,.wo-detail-pill.failed,.wo-detail-pill.recovery-required,.wo-detail-pill.uncertain{color:#ff99ad}.wo-detail-pill.waiting-approval{color:#ffd17c}
      .wo-detail-section{padding:14px;border:1px solid rgba(130,164,216,.13);border-radius:15px;background:rgba(10,19,32,.66)}.wo-detail-section h3{margin:0 0 10px;font-size:.8rem;color:#dce8f7}.wo-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.wo-detail-field{min-width:0;padding:9px 10px;border-radius:11px;background:rgba(20,34,54,.48)}.wo-detail-field b{display:block;margin-bottom:4px;color:#71859f;font-size:.61rem;text-transform:uppercase;letter-spacing:.06em}.wo-detail-field span,.wo-detail-field p,.wo-detail-field li{font-size:.72rem;line-height:1.45;color:#c6d2e2;overflow-wrap:anywhere}.wo-detail-field p{margin:0}.wo-detail-field ul{margin:0;padding-left:16px}.wo-detail-wide{grid-column:1/-1}
      .wo-detail-list{display:grid;gap:7px}.wo-detail-item{padding:9px 10px;border-radius:11px;background:rgba(19,32,51,.48);border:1px solid rgba(130,164,216,.08)}.wo-detail-item b{display:block;font-size:.71rem}.wo-detail-item p{margin:4px 0 0;color:#99aabd;font-size:.69rem;line-height:1.45}.wo-detail-item small{display:block;margin-top:4px;color:#70829a;font-size:.62rem}.wo-detail-json{white-space:pre-wrap;font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:#9fb0c5;overflow-wrap:anywhere}
      .wo-detail-next{display:grid;gap:5px;padding:12px;border-left:2px solid rgba(86,181,255,.72);background:rgba(23,55,83,.32);border-radius:4px 12px 12px 4px}.wo-detail-next b{font-size:.76rem}.wo-detail-next span{font-size:.7rem;color:#9db0c5;line-height:1.45}.wo-detail-loading,.wo-detail-error{padding:30px;text-align:center;color:#93a4b8}.wo-detail-error{color:#ffc1cd}
      body.wo-detail-open{overflow:hidden}
      @media(max-width:760px){.wo-detail-shell{grid-template-columns:1fr;background:#06101b;backdrop-filter:none}.wo-detail-backdrop{display:none}.wo-detail-panel{grid-column:1;border-left:0;width:100%;height:100dvh;box-shadow:none}.wo-detail-head{padding:16px 15px 12px}.wo-detail-scroll{padding:12px 14px 30px}.wo-detail-grid{grid-template-columns:1fr}.wo-detail-wide{grid-column:auto}.wo-detail-section{padding:12px;border-radius:13px}}
    `;document.head.append(style);
  }
  const statusClass=value=>String(value||'').toLowerCase().replaceAll('_','-');
  const text=value=>value===null||value===undefined||value===''?'—':String(value);
  const listMarkup=items=>items?.length?`<ul>${items.map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:'<span>None</span>';
  const jsonMarkup=value=>`<div class="wo-detail-json">${esc(JSON.stringify(value??{},null,2))}</div>`;

  function evidenceMarkup(items){
    if(!items?.length)return '<p>No evidence recorded.</p>';
    return `<div class="wo-detail-list">${items.map(item=>`<article class="wo-detail-item"><b>${esc(item.subject||item.kind||'Evidence')} · ${esc(label(item.verification_state||'recorded'))}</b><p>${esc(item.observation||item.summary||'')}</p><small>${esc(label(item.provenance||item.source_type||'unknown'))}${item.tool_name?` · ${esc(item.tool_name)}`:''}</small></article>`).join('')}</div>`;
  }
  function claimsMarkup(items){
    if(!items?.length)return '<p>No completion claims recorded.</p>';
    return `<div class="wo-detail-list">${items.map(item=>`<article class="wo-detail-item"><b>${esc(label(item.state))} · ${esc(item.id)}</b><p>${esc(item.text||'')}</p><small>Claim Gate · ${item.gate?.passed?'passed':'not passed'}${item.gate?.reasons?.length?` · ${esc(item.gate.reasons.join(' · '))}`:''}</small></article>`).join('')}</div>`;
  }
  function receiptsMarkup(items){
    if(!items?.length)return '<p>No execution receipts recorded.</p>';
    return `<div class="wo-detail-list">${items.map(item=>`<article class="wo-detail-item"><b>${esc(item.tool||'Tool')} · ${esc(item.operation||'operation')}</b><p>${esc(item.destination||'')}</p><small>${item.verified?'Verified receipt':'Unverified receipt'}${item.remote_id?` · remote ${esc(item.remote_id)}`:''}</small></article>`).join('')}</div>`;
  }
  function attentionMarkup(items){
    if(!items?.length)return '<p>No owner attention item is currently bound to this WorkOrder.</p>';
    return `<div class="wo-detail-list">${items.map(item=>`<article class="wo-detail-item"><b>${esc(item.title||label(item.kind))} · ${esc(label(item.severity))}</b><p>${esc(item.reason||item.summary||'')}</p><small>Authority · ${esc(label(item.authority))}</small></article>`).join('')}</div>`;
  }

  function bodyMarkup(d){
    const approval=d.approval_requirement||{},budget=d.budget||{},completion=d.completion_judge||{},next=d.safe_next_action||{};
    return `<div class="wo-detail-status"><span class="wo-detail-pill ${statusClass(d.execution_status)}">Execution · ${esc(label(d.execution_status))}</span><span class="wo-detail-pill ${statusClass(d.canonical_status)}">Canonical · ${esc(label(d.canonical_status))}</span><span class="wo-detail-pill ${completion.passed?'completed':statusClass(completion.state)}">Completion Judge · ${completion.passed?'Passed':esc(label(completion.state))}</span><span class="wo-detail-pill">Plan v${esc(d.plan_version)}</span></div>
      <section class="wo-detail-section"><h3>WorkOrder</h3><div class="wo-detail-grid"><div class="wo-detail-field"><b>Objective</b><p>${esc(text(d.objective))}</p></div><div class="wo-detail-field"><b>Milestone</b><p>${esc(text(d.milestone?.title))}</p></div><div class="wo-detail-field"><b>Worker</b><span>${esc(text(d.worker))}</span></div><div class="wo-detail-field"><b>Requested tool</b><span>${esc(text(d.requested_tool))}</span></div><div class="wo-detail-field"><b>Dependencies</b>${listMarkup(d.dependencies)}</div><div class="wo-detail-field"><b>Required capabilities</b>${listMarkup(d.required_capabilities)}</div><div class="wo-detail-field wo-detail-wide"><b>Resource scope</b>${jsonMarkup(d.resource_scope)}</div></div></section>
      <section class="wo-detail-section"><h3>Output & proof contract</h3><div class="wo-detail-grid"><div class="wo-detail-field"><b>Expected output</b><p>${esc(text(d.expected_output))}</p></div><div class="wo-detail-field"><b>Success criteria</b>${listMarkup(d.success_criteria)}</div><div class="wo-detail-field"><b>Evidence contract</b>${jsonMarkup(d.evidence_contract)}</div><div class="wo-detail-field"><b>Verification strategy</b>${jsonMarkup(d.verification_strategy)}</div><div class="wo-detail-field"><b>Falsifier</b><p>${esc(text(d.falsifier))}</p></div><div class="wo-detail-field"><b>Retest strategy</b>${jsonMarkup(d.retest_strategy)}</div></div></section>
      <section class="wo-detail-section"><h3>Authority, approval & budget</h3><div class="wo-detail-grid"><div class="wo-detail-field"><b>Approval requirement</b>${jsonMarkup(approval)}</div><div class="wo-detail-field"><b>Reauthentication</b><span>${d.reauthentication?.required?'Required':'Not required by this WorkOrder projection'}</span></div><div class="wo-detail-field"><b>Time budget</b><span>${esc(text(budget.time_budget_seconds))}</span></div><div class="wo-detail-field"><b>Cost budget</b><span>${esc(text(budget.cost_budget))}</span></div><div class="wo-detail-field wo-detail-wide"><b>Current execution</b>${jsonMarkup(d.current_execution)}</div></div></section>
      <section class="wo-detail-section"><h3>Evidence & receipts</h3><div class="wo-detail-field wo-detail-wide"><b>Evidence · ${esc(d.evidence_count??0)}</b>${evidenceMarkup(d.evidence)}</div><div style="height:8px"></div><div class="wo-detail-field wo-detail-wide"><b>Receipts · ${esc(d.receipts?.length||0)}</b>${receiptsMarkup(d.receipts)}</div></section>
      <section class="wo-detail-section"><h3>Claims & review</h3><div class="wo-detail-field wo-detail-wide"><b>Claims · ${esc(d.claims?.length||0)}${d.domain_claim_type?` · ${esc(label(d.domain_claim_type))}`:''}</b>${claimsMarkup(d.claims)}</div><div style="height:8px"></div><div class="wo-detail-grid"><div class="wo-detail-field"><b>Reviewer decision</b>${jsonMarkup(d.reviewer_decision)}</div><div class="wo-detail-field"><b>Completion Judge</b>${jsonMarkup(d.completion_judge)}</div></div></section>
      <section class="wo-detail-section"><h3>Attention & recovery</h3><div class="wo-detail-field wo-detail-wide"><b>Attention</b>${attentionMarkup(d.attention)}</div><div style="height:8px"></div><div class="wo-detail-grid"><div class="wo-detail-field"><b>Recovery state</b><span>${esc(label(d.recovery?.state||'none'))}</span></div><div class="wo-detail-field"><b>Recovery ID</b><span>${esc(text(d.recovery?.recovery_id))}</span></div></div></section>
      <section class="wo-detail-section"><h3>Plan history</h3><div class="wo-detail-grid"><div class="wo-detail-field"><b>Versions</b><span>${esc(d.replan_history?.versions?.length||0)}</span></div><div class="wo-detail-field"><b>Plan deltas</b><span>${esc(d.replan_history?.deltas?.length||0)}</span></div><div class="wo-detail-field wo-detail-wide"><b>Replan history</b>${jsonMarkup(d.replan_history)}</div></div></section>
      <div class="wo-detail-next"><b>Safe next action · ${esc(next.label||'Inspect WorkOrder')}</b><span>${esc(next.reason||'Use the authoritative Work surfaces for any action.')} · Authority: ${esc(label(next.authority||'canonical work runtime'))}</span></div>`;
  }

  function ensureShell(){
    if(shell?.isConnected)return shell;
    shell=document.createElement('div');shell.className='wo-detail-shell';shell.hidden=true;shell.innerHTML='<button class="wo-detail-backdrop" aria-label="Close WorkOrder detail"></button><aside class="wo-detail-panel" role="dialog" aria-modal="true" aria-labelledby="woDetailTitle"><header class="wo-detail-head"><div><h2 id="woDetailTitle">WorkOrder detail</h2><p id="woDetailSub">Canonical governed work inspection</p></div><button type="button" class="wo-detail-close" aria-label="Close">×</button></header><div class="wo-detail-scroll"><div class="wo-detail-loading">Loading WorkOrder authority state…</div></div></aside>';
    document.body.append(shell);shell.querySelector('.wo-detail-backdrop').addEventListener('click',close);shell.querySelector('.wo-detail-close').addEventListener('click',close);return shell;
  }
  function close(){if(!shell)return;shell.hidden=true;document.body.classList.remove('wo-detail-open');lastFocus?.focus?.();}
  async function open(taskId){
    const project=window.projectCurrent,planId=String(window.__vishnuCanonicalProjectWork?.snapshotCache?.get(project?.id)?.p10_plan?.id||'');if(!project?.id||!planId||!taskId)return;
    const current=++requestSeq,last=ensureShell();lastFocus=document.activeElement;last.hidden=false;document.body.classList.add('wo-detail-open');last.querySelector('#woDetailTitle').textContent='WorkOrder detail';last.querySelector('#woDetailSub').textContent=`${project.name||'Project'} · ${taskId}`;last.querySelector('.wo-detail-scroll').innerHTML='<div class="wo-detail-loading">Loading WorkOrder authority state…</div>';last.querySelector('.wo-detail-close').focus();
    try{const data=await api(`/projects/${encodeURIComponent(project.id)}/work/${encodeURIComponent(planId)}/orders/${encodeURIComponent(taskId)}`);if(current!==requestSeq||last.hidden)return;last.querySelector('#woDetailTitle').textContent=data.title||'WorkOrder detail';last.querySelector('#woDetailSub').textContent=`${project.name||'Project'} · ${data.work_order_id||taskId}`;last.querySelector('.wo-detail-scroll').innerHTML=bodyMarkup(data)}catch(error){if(current!==requestSeq)return;last.querySelector('.wo-detail-scroll').innerHTML=`<div class="wo-detail-error">${esc(error.message||'WorkOrder detail could not be loaded.')}</div>`}
  }
  document.addEventListener('click',event=>{const button=event.target.closest?.('[data-cw-select],[data-cw-live-select]');if(!button)return;const taskId=button.dataset.cwSelect||button.dataset.cwLiveSelect;if(taskId)queueMicrotask(()=>open(taskId))});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&shell&&!shell.hidden){event.preventDefault();close()}});
  injectStyles();window.__vishnuWorkOrderDetail={installed:true,authority:'read_only_projection',open,close};
})();

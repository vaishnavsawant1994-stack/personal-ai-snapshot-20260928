(()=>{
  'use strict';
  if(window.__vishnuAgentWorkforceEntry)return;
  window.__vishnuAgentWorkforceEntry=true;

  const target='/iphone/agents.html';
  const icon=`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17v-2.4c0-1.4 1.1-2.6 2.6-2.6h4.8c1.5 0 2.6 1.2 2.6 2.6V17"/><circle cx="12" cy="7.5" r="3"/><path d="M4.5 18.5h15M5 9.5l-2 1.5M19 9.5l2 1.5"/></svg>`;

  const navigate=event=>{
    event?.preventDefault?.();
    window.location.assign(target);
  };

  function makeEntry(reference){
    const tag=reference?.tagName?.toLowerCase()==='a'?'a':'button';
    const entry=document.createElement(tag);
    entry.dataset.vishnuAgentsEntry='true';
    entry.className=reference?.className||'';
    entry.setAttribute('aria-label','Agents');
    if(tag==='a')entry.href=target;
    else entry.type='button';
    entry.innerHTML=`${icon}<span>Agents</span>`;
    entry.addEventListener('click',navigate);
    return entry;
  }

  function textOf(node){return String(node?.textContent||'').replace(/\s+/g,' ').trim().toLowerCase()}

  function injectTopNav(){
    const nav=document.querySelector('.nav');
    if(!nav||nav.querySelector('[data-vishnu-agents-entry]'))return;
    const children=[...nav.querySelectorAll(':scope > button,:scope > a')];
    const project=children.find(node=>textOf(node).includes('project'));
    const reference=project||children.at(-1);
    const entry=makeEntry(reference);
    if(project)project.insertAdjacentElement('afterend',entry);else nav.append(entry);
  }

  function injectSideNavigation(){
    const containers=[...document.querySelectorAll('aside,nav,.sidebar,.side-panel,.drawer,.menu-panel')];
    for(const container of containers){
      if(container.classList.contains('nav'))continue;
      if(container.querySelector('[data-vishnu-agents-entry]'))continue;
      const candidates=[...container.querySelectorAll('a,button')].filter(node=>!node.closest('[data-vishnu-agents-entry]'));
      const project=candidates.find(node=>/^projects?\b/.test(textOf(node))||textOf(node)==='project');
      if(!project)continue;
      project.insertAdjacentElement('afterend',makeEntry(project));
    }
  }

  function inject(){
    if(location.pathname==='/iphone/agents.html')return;
    injectTopNav();
    injectSideNavigation();
  }

  let scheduled=false;
  const schedule=()=>{
    if(scheduled)return;
    scheduled=true;
    requestAnimationFrame(()=>{scheduled=false;inject()});
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});
  else schedule();
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
})();

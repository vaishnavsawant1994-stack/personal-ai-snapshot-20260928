/* Owner Controls: responsive, owner-only overview backed by Vishnu's existing APIs. */
(() => {
  const sections = [
    ['overview', 'Overview', 'shield'], ['providers', 'AI Providers', 'brain'],
    ['services', 'Connected Services', 'link'], ['permissions', 'Permissions', 'lock'],
    ['security', 'Security', 'shield'], ['backups', 'Data & Backups', 'database'],
    ['audit', 'Audit Log', 'activity'],
  ];
  const appNav = [
    ['home','Home','home'], ['today','Today','today'], ['conversations','Conversations','chat'],
    ['memory','Memory','brain'], ['knowledge','Knowledge','file'], ['activities','Activities','activity'],
    ['tools','Tools','settings'], ['workflows','Workflows','workflow'],
  ];
  const state = { section:'overview', data:{}, errors:{}, query:'', category:'all', range:'30', auditPage:1, permissionSaving:false };
  const paths = {
    home:'<path d="m3 10 9-7 9 7v10H3zM9 20v-7h6v7"/>', today:'<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M7 2v5M17 2v5M3 10h18"/>',
    chat:'<path d="M4 5h16v12H9l-5 3z"/>', brain:'<path d="M12 4c-3-3-8 0-7 4-3 2-1 6 2 6-2 4 3 7 5 4M12 4c3-3 8 0 7 4 3 2 1 6-2 6 2 4-3 7-5 4M12 3v18"/>',
    file:'<path d="M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7"/>', activity:'<path d="M3 12h4l2-7 4 14 2-7h6"/>',
    settings:'<circle cx="12" cy="12" r="3"/><path d="M19 13.5a7 7 0 0 0 0-3l2-1.2-2-3.5-2.3 1a7 7 0 0 0-2.6-1.5L14 3h-4l-.4 2.3A7 7 0 0 0 7 6.8l-2.3-1-2 3.5 2 1.2a7 7 0 0 0 0 3l-2 1.2 2 3.5 2.3-1a7 7 0 0 0 2.6 1.5L10 21h4l.4-2.3a7 7 0 0 0 2.6-1.5l2.3 1 2-3.5z"/>',
    workflow:'<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/><path d="M10 6h8a3 3 0 0 1 3 3v5M14 18H6a3 3 0 0 1-3-3v-5"/>',
    shield:'<path d="M12 3 4 6v5c0 5 3 8 8 10 5-2 8-5 8-10V6z"/><path d="m9 12 2 2 4-4"/>',
    lock:'<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 1 1 8 0v3"/>',
    link:'<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
    database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 2 4 3 8 3s8-1 8-3V5M4 12v7c0 2 4 3 8 3s8-1 8-3v-7"/>',
    check:'<path d="m5 12 4 4L19 6"/>', warning:'<path d="m12 3 10 18H2L12 3z"/><path d="M12 9v5m0 3h.01"/>',
    plus:'<path d="M12 5v14M5 12h14"/>', chevron:'<path d="m9 18 6-6-6-6"/>', search:'<circle cx="10.8" cy="10.8" r="6.2"/><path d="m16 16 4.1 4.1"/>',
    cloud:'<path d="M6 18h12a4 4 0 0 0 .2-8A6.5 6.5 0 0 0 6 9a4.5 4.5 0 0 0 0 9z"/>',
    bell:'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  };
  const esc = value => window.escapeHtml(String(value ?? ''));
  const icon = (name, cls='') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.activity}</g></svg>`;
  const call = (path, options) => window.api(path, options);
  const title = key => sections.find(item => item[0]===key)?.[1] || 'Owner Controls';
  const time = value => { if (!value) return 'Unavailable'; const d=new Date(value); return Number.isNaN(d.getTime())?'Unavailable':new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(d); };
  const since = value => { if (!value) return 'No recorded sync'; const seconds=Math.max(0,(Date.now()-new Date(value).getTime())/1000); if (!Number.isFinite(seconds)) return 'Unavailable'; if(seconds<60)return 'Just now'; if(seconds<3600)return `${Math.floor(seconds/60)} min ago`; if(seconds<86400)return `${Math.floor(seconds/3600)} hr ago`; return `${Math.floor(seconds/86400)} days ago`; };
  const button = (text, action, cls='oc-button') => `<button type="button" class="${cls}" data-oc-action="${action}">${text}</button>`;
  const status = (label, tone='neutral') => `<span class="oc-status ${tone}"><i aria-hidden="true"></i>${esc(label)}</span>`;
  const safeArray = (obj,key) => Array.isArray(obj?.[key]) ? obj[key] : [];
  const skeleton = (className='') => `<span class="oc-skeleton ${className}" aria-hidden="true"></span>`;
  async function loadAuditFeed() {
    const activities=[];
    let cursor=null,pages=0;
    do {
      const query=new URLSearchParams({limit:'200'});
      if(cursor)query.set('cursor',cursor);
      const page=await call(`/activities?${query.toString()}`);
      activities.push(...safeArray(page,'activities'));
      cursor=page.next_cursor||null;
      pages++;
    } while(cursor&&pages<5);
    return {activities,has_more:Boolean(cursor),pages};
  }
  function loadingPage() {
    const section=state.section;
    const heroSkeleton=`<section class="oc-hero oc-skeleton-hero" aria-label="Loading Owner Controls"><div>${skeleton('oc-skel-title')}${skeleton('oc-skel-copy')}${skeleton('oc-skel-copy short')}${skeleton('oc-skel-pills')}</div><div class="oc-sphere-wrap"><span class="settings-orb oc-sphere-slot" aria-hidden="true"></span></div><div class="oc-skeleton-status">${skeleton()}${skeleton()}${skeleton()}${skeleton()}</div></section>`;
    const panelRows=count=>`<section class="oc-panel oc-skeleton-panel">${skeleton('oc-skel-title')}${Array.from({length:count},()=>skeleton('oc-skel-row')).join('')}</section>`;
    if(section==='overview')return `${heroSkeleton}${skeleton('oc-skel-section') }<div class="oc-control-grid">${Array.from({length:6},()=>panelRows(2)).join('')}</div>${skeleton('oc-skel-section')}<div class="oc-quick-grid">${Array.from({length:4},()=>panelRows(1)).join('')}</div>`;
    if(section==='providers')return `${heroSkeleton}${skeleton('oc-skel-section')}${Array.from({length:5},()=>panelRows(1)).join('')}${panelRows(4)}${panelRows(5)}`;
    if(section==='services')return `${heroSkeleton}${skeleton('oc-skel-section')}${skeleton('oc-skel-toolbar')}${Array.from({length:6},()=>panelRows(1)).join('')}`;
    if(section==='permissions')return `${heroSkeleton}${skeleton('oc-skel-section')}${Array.from({length:8},()=>panelRows(1)).join('')}${panelRows(4)}${panelRows(3)}`;
    if(section==='security')return `${heroSkeleton}${panelRows(4)}${panelRows(5)}${panelRows(4)}${panelRows(4)}`;
    if(section==='backups')return `${heroSkeleton}<div class="oc-metric-grid">${Array.from({length:4},()=>panelRows(1)).join('')}</div><div class="oc-two-col">${panelRows(4)}${panelRows(4)}${panelRows(4)}${panelRows(4)}</div>${panelRows(5)}`;
    return `${heroSkeleton}${skeleton('oc-skel-toolbar')}${panelRows(10)}`;
  }
  function safeAuditDetails(value) {
    if(Array.isArray(value))return value.map(safeAuditDetails);
    if(!value||typeof value!=='object')return value;
    return Object.fromEntries(Object.entries(value).map(([key,item])=>[
      key,/password|token|secret|credential|api.?key|private.?key|recovery.?code/i.test(key)?'[REDACTED]':safeAuditDetails(item),
    ]));
  }

  async function loadData() {
    const reqs = {
      system:()=>call('/system/status'), health:()=>fetch('/health',{credentials:'same-origin'}).then(async response=>{if(!response.ok)throw new Error('Health endpoint unavailable');return response.json()}), devices:()=>call('/devices'), security:()=>call('/access/security'),
      connectors:()=>call('/connectors'), activities:loadAuditFeed, approvals:()=>call('/approvals-center?limit=100'), profile:()=>call('/profile/metadata'),
      backups:()=>call('/owner/backups'), ownerPermissions:()=>call('/owner/permissions'),
    };
    const entries=await Promise.all(Object.entries(reqs).map(async([key,fn])=>{try{return [key,await fn(),null]}catch(error){return [key,null,error]}}));
    state.data=Object.fromEntries(entries.map(([key,value])=>[key,value]));
    state.errors=Object.fromEntries(entries.filter(([,value,error])=>error).map(([key,,error])=>[key,error]));
  }
  function providerRows() {
    const model=state.data.system?.model||{}, providers=safeArray(model,'providers');
    return providers.filter(item=>item.configured).map(item=>({
      id:item.id,
      name:item.display_name||item.name||(item.id==='self_hosted'?'Self-hosted model':String(item.id||'AI provider')),
      model:item.model||'Model not specified', health:item.health?.state||item.state||'configured',
      primary:item.id===model.primary_provider, private:item.private===true, ownerManaged:item.user_managed===true||item.owner_managed===true,
    }));
  }
  function connectors() { return Array.isArray(state.data.connectors) ? state.data.connectors : safeArray(state.data.connectors,'connectors'); }
  function connected(item) { return ['healthy','connected','active'].includes(String(item.state||'').toLowerCase()) || item.healthy===true; }
  function activeDevices() { return safeArray(state.data.devices,'devices').filter(item=>!item.revoked).map(item=>({...item,current:item.current===true||item.id===state.data.devices?.current_device_id,last_seen:item.last_seen||item.last_seen_at})); }
  function pendingApprovals() { return safeArray(state.data.approvals,'approvals'); }
  function auditRows() { return safeArray(state.data.activities,'activities').map(item=>({...item,kind:item.kind||item.category||'activity',label:item.label||item.category||item.kind||'Activity',details:safeAuditDetails(item.details||item.payload||{})})); }

  function shell() {
    const profile=state.data.profile||{}, name=profile.display_name||profile.full_name||'Owner';
    const initials=String(name).trim().split(/\s+/).slice(0,2).map(part=>part[0]?.toUpperCase()||'').join('')||'O';
    const navRows=appNav.map(([id,label,ico])=>`<button class="oc-nav-row" type="button" data-oc-module="${id}">${icon(ico)}<span>${label}</span></button>`).join('');
    const setRows=[['Profile','profile'],['Appearance','appearance'],['Notifications','notifications'],['Chat preferences','chat'],['Privacy & data','data'],['Language & region','personal']].map(([label,key])=>`<button class="oc-nav-sub" type="button" data-oc-settings="${key}">${label}</button>`).join('');
    return `<div class="oc-shell">
      <aside class="oc-sidebar" aria-label="Primary navigation">
        <div class="oc-brand">${icon('brain','oc-brand-icon')}<span><strong>Personal AI</strong><small>Vishnu</small></span></div>
        <nav class="oc-main-nav">${navRows}</nav>
        <div class="oc-sidebar-divider"></div><div class="oc-side-caption">Settings</div>
        <button class="oc-nav-row" type="button" data-oc-settings-home>${icon('settings')}<span>Settings</span></button>
        <div class="oc-settings-nav">${setRows}</div>
        <button class="oc-nav-row selected" type="button" aria-current="page">${icon('shield')}<span>Owner Controls</span></button>
        <div class="oc-sidebar-spacer"></div><button class="oc-nav-row oc-muted-nav" type="button" data-oc-help>${icon('activity')}<span>Help &amp; support</span></button>
        <div class="oc-owner-card"><span class="oc-avatar">${esc(initials)}</span><span><strong>${esc(name)}</strong><small>Owner</small></span><button type="button" aria-label="Open owner menu" data-oc-account>•••</button></div>
      </aside>
      <main class="oc-main">
        <header class="oc-topbar"><button class="oc-hamburger" type="button" aria-label="Open navigation" data-oc-menu>☰</button><div class="oc-mobile-brand">${icon('brain')}<span><strong>Personal AI</strong><small>Vishnu</small></span></div><label class="oc-search">${icon('search')}<input id="ocGlobalSearch" type="search" placeholder="Search anything…" aria-label="Search Owner Controls"></label><button class="oc-mobile-search" type="button" aria-label="Search conversations" data-oc-search>${icon('search')}</button><div class="oc-top-actions"><button type="button" aria-label="New chat" data-oc-new>${icon('plus')}</button><button type="button" aria-label="Start voice chat" data-oc-voice>${icon('activity')}</button><button type="button" aria-label="Open notifications" data-oc-notifications>${icon('bell')}</button><button type="button" aria-label="Owner account" data-oc-account>${icon('brain')}</button></div></header>
        <div class="oc-content"><div class="oc-breadcrumb">Settings <span>›</span> Owner Controls <span>›</span> <b>${esc(title(state.section))}</b></div>
          <header class="oc-page-heading">${icon('shield')}<div><h1>${esc(title(state.section))}</h1><p>${esc(pageSubtitle(state.section))}</p></div></header>
          <nav class="oc-tabs" aria-label="Owner Controls sections">${sections.map(([key,label])=>`<button type="button" data-oc-section="${key}" class="${state.section===key?'active':''}" aria-current="${state.section===key?'page':'false'}">${esc(label)}</button>`).join('')}</nav>
          <div class="oc-page-body" id="ocPageBody" aria-busy="${state.loading?'true':'false'}">${state.loading?loadingPage():renderPage()}</div>
        </div>
      </main>
    </div>`;
  }
  function pageSubtitle(key) { return ({overview:'Manage how Vishnu works for you, what it can access, and keep your data safe.',providers:'Manage the AI models and providers used by Vishnu.',services:'Connect and manage the external services Vishnu can use for you.',permissions:'Control what Vishnu can do, access, and when to ask for your approval.',security:'Keep Vishnu and your data secure with advanced protection and control.',backups:'Keep your data safe, backed up and under your control.',audit:'Track important activity, changes and access across your account.'})[key]; }
  function hero(heading,copy,checks,asideTitle,asideRows) {
    return `<section class="oc-hero"><div class="oc-hero-copy"><h2>${esc(heading)}</h2><p>${esc(copy)}</p><div class="oc-trust">${checks.map(text=>`<span>${icon('check')} ${esc(text)}</span>`).join('')}</div></div><div class="oc-sphere-wrap"><span class="settings-orb oc-sphere-slot" aria-hidden="true"></span></div><aside class="oc-hero-status"><h3>${esc(asideTitle)}</h3>${asideRows.map(([text,tone='good'])=>`<div>${icon(tone==='good'?'check':tone==='warn'?'warning':'activity')}<span>${esc(text)}</span>${icon('chevron')}</div>`).join('')}</aside></section>`;
  }
  function sectionHeading(heading,copy,action='') { return `<div class="oc-section-heading"><div><h2>${esc(heading)}</h2><p>${esc(copy)}</p></div>${action}</div>`; }
  function card(key,titleText,description,summary,ico,tone='blue') {
    return `<button class="oc-control-card" type="button" data-oc-section="${key}"><span class="oc-card-icon ${tone}">${icon(ico)}</span><strong>${esc(titleText)}</strong><p>${esc(description)}</p><div class="oc-card-foot">${status(summary.label,summary.tone)}<span aria-hidden="true">›</span></div></button>`;
  }
  function overview() {
    const providers=providerRows(), services=connectors(), connectedCount=services.filter(connected).length, approvalCount=pendingApprovals().length;
    const current=activeDevices().length;
    const health=state.data.health||{},backupData=state.data.backups||{},backupRows=safeArray(backupData,'backups');
    const backupState=state.errors.backups?'Backup status unavailable':backupData.available===false?'Encrypted backup service unavailable':backupRows.length?'Stored backups need integrity verification':'No backup yet';
    const systemLabel=state.errors.health?'Vishnu health unavailable':health.ok===true?'Vishnu is active':`Vishnu health: ${health.status||'Unavailable'}`;
    const systemTone=state.errors.health?'warn':health.ok===true?'good':'neutral';
    return `${hero('You’re in control','Configure Vishnu’s capabilities, connected services, permissions, security and data settings — all in one place.',['Personal use only','You are the owner','Your data stays private'],'System status',[[systemLabel,systemTone],[`${providers.length} configured AI provider${providers.length===1?'':'s'}`,providers.length?'good':'neutral'],[`${approvalCount} pending approval${approvalCount===1?'':'s'}`,approvalCount?'warn':'good'],[`${current} trusted device${current===1?'':'s'}`,current?'good':'neutral'],[backupState,state.errors.backups?'warn':backupRows.length?'warn':'neutral']])}
      ${sectionHeading('Owner Controls','Configure and manage every aspect of Vishnu.')}
      <div class="oc-control-grid">
        ${card('providers','AI Providers','Manage AI models and providers used by Vishnu.',{label:providers.length?`${providers.length} configured`:'Not configured',tone:providers.length?'good':'neutral'},'brain','purple')}
        ${card('services','Connected Services','Connect and manage accounts and external services.',{label:services.length?`${connectedCount} connected`:'Unavailable',tone:connectedCount?'good':'neutral'},'link','blue')}
        ${card('permissions','Permissions','Control what Vishnu can do, access and when to ask.',{label:`${approvalCount} pending approval${approvalCount===1?'':'s'}`,tone:approvalCount?'warn':'good'},'shield','green')}
        ${card('security','Security','Manage authentication, trusted devices and recovery.',{label:state.data.security?(state.data.security.password_configured||state.data.security.passkeys?.length?'Owner sign-in configured':'Needs setup'):'Unavailable',tone:state.data.security?'good':'neutral'},'lock','red')}
        ${card('backups','Data & Backups','Review the backup and export capabilities available here.',{label:backupState,tone:state.errors.backups?'warn':backupRows.length?'warn':'neutral'},'database','blue')}
        ${card('audit','Audit Log','View recent owner and system activity.',{label:auditRows().length?`${auditRows().length} recent events`:'No activity yet',tone:auditRows().length?'good':'neutral'},'activity','amber')}
      </div>
      ${sectionHeading('Quick actions','Common tasks to keep Vishnu running smoothly.')}
      <div class="oc-quick-grid">${quick('providers','Add AI provider','Connect a new model','brain')}${quick('services','Connect a service','Link an external account','link')}${quick('permissions','Review permissions','Check owner approval rules','shield')}${quick('backup-create','Run backup now','Create a manual encrypted backup','cloud')}</div>
      ${errorRows()}`;
  }
  function quick(section,label,sub,ico) { return `<button type="button" class="oc-quick" data-oc-quick="${section}"><span class="oc-card-icon blue">${icon(ico)}</span><span><strong>${esc(label)}</strong><small>${esc(sub)}</small></span>${icon('chevron')}</button>`; }
  function errorRows() { const failed=Object.entries(state.errors); return failed.length?`<div class="oc-inline-warning" role="status">Some status sources are unavailable: ${failed.map(([key])=>esc(key)).join(', ')}. Other Owner Controls sections remain available.</div>`:''; }
  function providersPage() {
    const rows=providerRows(), model=state.data.system?.model||{};
    return `${hero('Choose and configure AI providers','Select the AI models Vishnu can use and control their use.',['Provider credentials stay on the server'],'Provider status',[[`${rows.length} configured provider${rows.length===1?'':'s'}`,rows.length?'good':'neutral'],[model.primary_provider?`Default: ${model.primary_provider}`:'Default provider unavailable',model.primary_provider?'good':'neutral'],[state.errors.system?'System status unavailable':'Model status from Vishnu runtime',state.errors.system?'warn':'good']])}
      ${sectionHeading('Your AI providers','Connect an AI provider securely and manage the models available to Vishnu.',button('+ Add provider','provider-add','oc-button primary'))}
      <div class="oc-list">${rows.length?rows.map(item=>`<article class="oc-provider-row"><span class="oc-card-icon purple">${icon('brain')}</span><div><strong>${esc(item.name)}</strong><small>${esc(item.model)} · ${esc(item.private?'Private':item.ownerManaged?'Owner configured':'Server configured')}</small><small>${esc(String(item.health).replaceAll('_',' '))}</small></div>${item.primary?status('Default','good'):`<button type="button" class="oc-text-button" data-oc-provider-default="${esc(item.id)}">Set as default</button>`}${item.ownerManaged?`<button type="button" class="oc-text-button" data-oc-provider-model="${esc(item.id)}">Change model</button>`:''}${item.ownerManaged&&!item.primary?`<button type="button" class="oc-text-button danger" data-oc-provider-disconnect="${esc(item.id)}">Disconnect</button>`:''}<button type="button" class="oc-row-chev" data-oc-action="models" aria-label="Open ${esc(item.name)} model settings">›</button></article>`).join(''):`<div class="oc-empty"><strong>${state.errors.system?'Provider status could not be loaded.':'No configured providers are reported by the runtime.'}</strong><p>${state.errors.system?'Retry after checking the server connection.':'Add a provider to load models from its live account.'}</p>${button('+ Add provider','provider-add','oc-button')}</div>`}</div>
      <div class="oc-note">Credentials are tested against the provider’s live model endpoint and stored in Vishnu’s encrypted server vault. Keys are never returned to this page.</div>`;
  }
  function servicesPage() {
    const rows=connectors();
    return `${hero('Connect your tools','Link accounts so Vishnu can help across your apps. You stay in control of access and actions.',['Owner-controlled connections','Permissions remain explicit'],'Connection status',[[`${rows.filter(connected).length} connected`,rows.some(connected)?'good':'neutral'],[`${rows.length} available connector records`,'neutral'],['Credentials are never shown here','good']])}
      ${sectionHeading('Connected services','Service state and granted scopes are read from the connector registry.',button('Open integrations','tools','oc-button primary'))}
      <div class="oc-toolbar"><label class="oc-search">${icon('search')}<input id="ocServiceSearch" type="search" placeholder="Search services…" aria-label="Search services"></label><select id="ocServiceFilter" aria-label="Filter service status"><option value="all">All services</option><option value="connected">Connected</option><option value="other">Not connected</option></select></div>
      <div class="oc-list" id="ocServiceList">${renderServiceRows(rows)}</div>
      <div class="oc-note">Connecting a service uses the existing OAuth flow and provider scope review. This page does not invent account identifiers or claim a sync time the connector has not recorded.</div>`;
  }
  function renderServiceRows(rows,query='',filter='all') {
    const values=rows.filter(item=>`${item.name} ${item.id} ${item.provider}`.toLowerCase().includes(query.toLowerCase())).filter(item=>filter==='all'||(filter==='connected'?connected(item):!connected(item)));
    return values.length?values.map(item=>`<article class="oc-service-row"><span class="oc-card-icon blue">${icon('link')}</span><div class="oc-service-copy"><strong>${esc(item.name||item.id)}</strong><small>${esc(item.provider||item.id)} · ${esc(item.id)}</small><small>${safeArray(item,'granted_scopes').length?`${item.granted_scopes.length} granted scopes`:'No granted scopes reported'}</small></div><div>${status(connected(item)?'Connected':String(item.state||'Not connected').replaceAll('_',' '),connected(item)?'good':item.state==='degraded'?'warn':'neutral')}<small class="oc-last-sync">${item.last_success_at?`Last success ${esc(since(item.last_success_at))}`:'Sync history unavailable'}</small></div>${connected(item)?button('Manage','tools','oc-text-button'):button('Connect','tools','oc-button')}<button type="button" class="oc-row-chev" data-oc-action="tools" aria-label="Open ${esc(item.name||item.id)} details">›</button></article>`).join(''):`<div class="oc-empty"><strong>No services match this filter.</strong><p>Try another search or open integrations to review available connectors.</p>${button('Open integrations','tools','oc-button')}</div>`;
  }
  function permissionsPage() {
    const approvals=pendingApprovals(), services=connectors(), operations=services.flatMap(item=>safeArray(item,'operations').map(op=>({...op,service:item.name||item.id}))),paused=Boolean(state.data.system?.emergency_stop),policy=state.data.ownerPermissions||{},rules=policy.rules||{};
    const groups=[
      ['read','Read & understand','Read and analyze files, emails, calendar, knowledge and project data.','file'],
      ['create','Create','Create tasks, meetings, notes, documents, projects and workflows.','plus'],
      ['edit','Edit / organize','Update and organize tasks, files, project plans and calendar items.','settings'],
      ['delete','Delete','Delete files, tasks, notes or other data.','warning'],
      ['external_communication','External communication','Send emails, messages or share files outside Vishnu.','link'],
      ['execute_actions','Execute actions','Run workflows, code, deployments and integrations.','activity'],
      ['financial_actions','Financial actions','Purchases, subscriptions, invoices, payments or anything involving money.','database'],
      ['account_security_changes','Account & security changes','Change credentials, providers, permissions or security settings.','shield'],
    ];
    const mode=policy.mode||'balanced',modeLabel=({safe:'Safe',balanced:'Balanced (Recommended)',custom:'Custom'})[mode]||'Unavailable';
    const options=value=>`<option value="allow" ${value==='allow'?'selected':''}>Allow automatically</option><option value="ask" ${value==='ask'?'selected':''}>Ask every time</option><option value="never" ${value==='never'?'selected':''}>Never allow</option>`;
    return `${hero('You’re in control','Choose what Vishnu can access, what it can do, and when it should ask for your approval.',['Personal use only','You are the owner','Your data stays private'],'Permission mode',[[modeLabel,mode==='safe'?'warn':'good'],[paused?'Autonomous actions are paused':'Autonomous actions are available',paused?'warn':'good'],[`${approvals.length} pending approval${approvals.length===1?'':'s'}`,approvals.length?'warn':'good']])}
      ${state.errors.ownerPermissions?`<div class="oc-inline-warning" role="alert">Permission rules could not be loaded. ${button('Retry','permissions-refresh','oc-text-button')}</div>`:''}
      <div class="oc-two-col"><section class="oc-panel oc-core-permissions"><div class="oc-panel-title"><span class="oc-card-icon green">${icon('shield')}</span><div><h3>Core permissions</h3><p>Set what Vishnu can do across your data, tools and connected services.</p></div><button type="button" class="oc-text-button" data-oc-action="permissions-reset">Reset to defaults</button></div>
        <div class="oc-permission-mode"><label for="ocPermissionMode">Permission mode</label><select id="ocPermissionMode" aria-label="Permission mode"><option value="safe" ${mode==='safe'?'selected':''}>Safe</option><option value="balanced" ${mode==='balanced'?'selected':''}>Balanced (Recommended)</option><option value="custom" ${mode==='custom'?'selected':''}>Custom</option></select><small>Balanced permits routine reversible work and asks before sensitive or external actions.</small></div>
        <div class="oc-permission-rows">${groups.map(([key,label,description,ico])=>`<div class="oc-permission-row"><span class="oc-card-icon blue">${icon(ico)}</span><div><strong>${esc(label)}</strong><small>${esc(description)}</small></div><label class="oc-sr-only" for="oc-permission-${key}">${esc(label)} rule</label><select id="oc-permission-${key}" data-owner-permission="${key}" aria-label="${esc(label)} permission">${options(rules[key])}</select></div>`).join('')}</div>
        <div class="oc-inline-status" id="ocPermissionSaveStatus" role="status" aria-live="polite">${state.permissionSaving?'Saving permission rules…':'Changes are saved to this owner’s persistent policy.'}</div></section>
        <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon red">${icon('lock')}</span><div><h3>Sensitive action protection</h3><p>High-risk actions retain their explicit approval boundary.</p></div></div><ul class="oc-protected-list"><li>${icon('check')} Deleting data</li><li>${icon('check')} External communications</li><li>${icon('check')} Financial actions</li><li>${icon('check')} Account and security changes</li><li>${icon('check')} Connecting services</li><li>${icon('check')} External deployments</li></ul><div class="oc-inline-warning">Global rules cannot bypass hard safety restrictions.</div></section></div>
      <div class="oc-two-col"><section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon amber">${icon('activity')}</span><div><h3>Approval requests</h3><p>Requests are managed by Vishnu’s canonical approval service.</p></div></div>${approvals.length?`<div class="oc-list">${approvals.map(item=>`<article class="oc-approval-row"><div><strong>${esc(item.title||item.action||item.operation||'Approval request')}</strong><small>${esc(item.description||item.reason||'Details are not available.')}</small></div>${status(String(item.status||'Pending'),'warn')}<span>${esc(time(item.created_at||item.requested_at))}</span></article>`).join('')}</div>`:'<div class="oc-empty compact">No pending approvals.</div>'}${button('Open approvals','approvals','oc-button')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon amber">${icon('link')}</span><div><h3>Connected service safeguards</h3><p>Connector manifests define available operations, required scopes and additional restrictions.</p></div></div>${operations.length?`<div class="oc-list">${operations.slice(0,12).map(item=>`<article class="oc-approval-row"><div><strong>${esc(item.name)}</strong><small>${esc(item.service)} · ${esc(item.risk||'risk unavailable')}</small></div>${status(item.prohibited?'Prohibited':item.approval&&item.approval!=='none'?'Approval required':'Scope controlled',item.prohibited?'bad':item.approval&&item.approval!=='none'?'warn':'neutral')}</article>`).join('')}</div>`:'<div class="oc-empty compact">No connector operation metadata is available.</div>'}${button('Review connected services','services','oc-button')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon red">${icon('warning')}</span><div><h3>Quick controls</h3><p>Pause or resume autonomous tool execution. Interactive chats remain available.</p></div></div><div class="oc-setting-row"><div><strong>${paused?'Pause all autonomous actions':'Autonomous actions'}</strong><small>${paused?'The persistent emergency stop currently blocks tool execution.':'Stops tool actions and cancels currently running execution.'}</small></div>${status(paused?'Paused':'Available',paused?'warn':'good')}${button(paused?'Resume actions':'Pause actions',paused?'emergency-resume':'emergency-stop',paused?'oc-button':'oc-button danger')}</div></section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('activity')}</span><div><h3>Recent permission activity</h3><p>Recent owner and system actions recorded in the audit feed.</p></div></div>${auditRows().slice(0,4).map(item=>`<div class="oc-setting-row"><div><strong>${esc(item.action||item.label||'Recorded activity')}</strong><small>${esc(time(item.created_at))}</small></div>${status(String(item.status||'Recorded'),'neutral')}</div>`).join('')||'<div class="oc-empty compact">No recent permission activity.</div>'}${button('View audit log','audit','oc-button')}</section></div>
      <div class="oc-note">Owner permission rules are enforced by Vishnu’s tool authorization layer. Hard safety restrictions and connector-specific approval requirements remain in force.</div>`;
  }
  function securityPage() {
    const sec=state.data.security||{}, devices=activeDevices(), passkeys=safeArray(sec,'passkeys');
    return `${hero('Your system is protected','Review owner sign-in methods and trusted device state reported by the existing security services.',['Personal owner account',sec.password_configured?'Owner password configured':'Password state reported',`${passkeys.length} registered passkey${passkeys.length===1?'':'s'}`],'Security status',[[sec.google_configured?'Google owner sign-in configured':'Google owner sign-in not configured',sec.google_configured?'good':'neutral'],[`${devices.length} trusted device${devices.length===1?'':'s'}`,devices.length?'good':'neutral'],[sec.recovery_codes_remaining!==undefined?`${sec.recovery_codes_remaining} recovery codes remaining`:'Recovery status unavailable',sec.recovery_codes_remaining?'good':'neutral'],['Encryption state not reported by this page','neutral']])}
      <div class="oc-two-col"><section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon purple">${icon('lock')}</span><div><h3>Account security</h3><p>Manage the sign-in controls supported by this Vishnu installation.</p></div></div>
        ${settingRow('Owner password',sec.password_configured?'Configured':'Not configured', 'security',sec.password_configured?'good':'warn')}
        ${settingRow('Passkeys',`${passkeys.length} registered`, 'security',passkeys.length?'good':'neutral')}
        ${settingRow('Recovery codes',sec.recovery_codes_remaining!==undefined?`${sec.recovery_codes_remaining} remaining`:'Unavailable','security','neutral')}
        ${button('Open security settings','security-settings','oc-button')}
      </section><section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('settings')}</span><div><h3>Trusted devices</h3><p>Devices currently recognized by the server.</p></div></div>${devices.length?devices.map(item=>`<div class="oc-device-row"><span class="oc-device-dot"></span><div><strong>${esc(item.name||item.label||item.id)}</strong><small>${esc(item.platform||item.device_type||'Device')} · ${item.last_seen?esc(since(item.last_seen)):'activity time unavailable'}</small></div>${status(item.current?'Current':'Trusted',item.current?'good':'neutral')}</div>`).join(''):'<div class="oc-empty compact">No trusted devices are available.</div>'}${button('Manage devices','devices','oc-button')}</section></div>
      <div class="oc-two-col oc-security-lower"><section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('database')}</span><div><h3>Encryption &amp; data protection</h3><p>Security indicators are shown only when the runtime reports them.</p></div></div>${settingRow('Data encryption','Encryption state not reported','settings-data','neutral')}${settingRow('Encryption keys','Key-management details unavailable','settings-data','neutral')}${settingRow('Data residency','Storage region not reported','settings-data','neutral')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon purple">${icon('devices')}</span><div><h3>Session &amp; access control</h3><p>Manage trusted owner devices using the existing device service.</p></div></div>${settingRow('Trusted devices',`${devices.length} active device${devices.length===1?'':'s'}`,'devices',devices.length?'good':'neutral')}${settingRow('Session timeout','Policy not reported','security-settings','neutral')}${button('Manage devices','devices','oc-button')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon amber">${icon('bell')}</span><div><h3>Security notifications</h3><p>Open the existing owner notification preferences.</p></div></div><p class="oc-muted-copy">Security-specific alert delivery is not exposed as a separate event category by this installation.</p>${button('Open notification settings','settings-notifications','oc-button')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon red">${icon('shield')}</span><div><h3>Advanced security</h3><p>Sensitive operations continue to use the existing approval authority.</p></div></div><div class="oc-setting-row"><div><strong>Sensitive action approvals</strong><small>Controlled by Owner Controls approvals and connector manifests</small></div>${status('Active policy source','neutral')}</div>${button('Review permissions','permissions','oc-button')}</section></div>
      <div class="oc-note">This app exposes owner password, passkeys, recovery codes, and trusted devices. It does not report 2FA, session timeout, location restrictions, or encryption state, so those controls are not represented as enabled.</div>`;
  }
  function settingRow(label,value,action,tone) { return `<div class="oc-setting-row"><div><strong>${esc(label)}</strong><small>${esc(value)}</small></div>${status(value,tone)}<button type="button" class="oc-text-button" data-oc-action="${action}">Manage</button></div>`; }
  function backupsPage() {
    const backupData=state.data.backups||{},rows=safeArray(backupData,'backups'),unavailable=Boolean(state.errors.backups)||backupData.available===false,canCreate=backupData.can_create===true,bytes=Number(backupData.total_size_bytes)||0,latest=rows[0];
    const size=bytes?`${(bytes/1024/1024/1024).toFixed(2)} GB`:'0 GB';
    const backupHealth=unavailable?'Unavailable':latest?'Stored · verification required':'No backup yet';
    return `${hero('Your data stays owner-controlled','Review available export and encrypted backup capabilities without showing unverified backup health.',['Owner-only export','Sensitive credentials excluded'],'Data status',[[unavailable?'Backup service unavailable':`${rows.length} backup${rows.length===1?'':'s'} stored`,unavailable?'warn':rows.length?'neutral':'warn'],[latest?'Stored backups require integrity verification':'No backup has been created','neutral'],['Automatic schedule is not configured','neutral']])}
      ${state.errors.backups?`<div class="oc-inline-warning" role="alert">Unable to load backup records. ${button('Retry','backup-refresh','oc-text-button')}</div>`:''}
      <div class="oc-metric-grid"><article><span class="oc-card-icon blue">${icon('database')}</span><strong>${esc(unavailable?'Unavailable':size)}</strong><small>Stored backup size</small></article><article><span class="oc-card-icon green">${icon('check')}</span><strong>${esc(unavailable?'Unavailable':latest?since(latest.created_at):'No backup yet')}</strong><small>Last backup</small></article><article><span class="oc-card-icon blue">${icon('activity')}</span><strong>Not scheduled</strong><small>Next backup</small></article><article><span class="oc-card-icon amber">${icon('cloud')}</span><strong>${esc(backupHealth)}</strong><small>Backup status</small></article></div>
      <div class="oc-two-col"><section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('database')}</span><div><h3>Backup settings</h3><p>Encrypted manual backups are available. Automatic scheduling and retention are not configured by this application.</p></div></div>${unavailable||!canCreate?`<button type="button" class="oc-button primary" disabled>${unavailable?'Backup unavailable':'Backup requires owner device access'}</button>`:button('Run backup now','backup-create','oc-button primary')}<div class="oc-setting-row"><div><strong>Automatic backups</strong><small>Scheduler not configured</small></div>${status('Unavailable','neutral')}</div><div class="oc-setting-row"><div><strong>Retention</strong><small>No automatic cleanup policy is configured</small></div>${status('Unavailable','neutral')}</div></section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('cloud')}</span><div><h3>Cloud storage & location</h3><p>Backup artifacts are stored in this installation’s configured local backup directory.</p></div></div><div class="oc-setting-row"><div><strong>Storage provider</strong><small>Local application storage</small></div>${status('Configured','neutral')}</div><div class="oc-setting-row"><div><strong>Storage location</strong><small>Region is not reported</small></div>${status('Unavailable','neutral')}</div><div class="oc-setting-row"><div><strong>Usage</strong><small>${esc(size)} across listed backup artifacts</small></div>${status(unavailable?'Unavailable':'Reported','neutral')}</div></section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon green">${icon('check')}</span><div><h3>Restore data</h3><p>Restore from a previous verified backup.</p></div></div><p class="oc-muted-copy">The engine supports verified recovery, but the running app has no maintenance gate to coordinate database replacement safely. Restore is unavailable in this live interface.</p><button type="button" class="oc-button" disabled aria-describedby="ocRestoreUnavailable">Restore data</button><small id="ocRestoreUnavailable" class="oc-muted-copy">Use the documented offline recovery process until coordinated restore jobs are available.</small></section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('cloud')}</span><div><h3>Export your data</h3><p>Download a copy of your available owner data.</p></div></div><p class="oc-muted-copy">Exports include available conversations, preferences, memories and Knowledge. Provider credentials and recovery secrets are not included.</p>${button('Create JSON export','export','oc-button primary')}</section>
      <section class="oc-panel"><div class="oc-panel-title"><span class="oc-card-icon red">${icon('warning')}</span><div><h3>Delete data</h3><p>Review supported deletion controls without affecting external service data.</p></div></div><p class="oc-muted-copy">The existing Privacy & data screen provides supported conversation and account deletion flows. A separate all-data-and-backups deletion workflow is not available here.</p>${button('Open Privacy & data','settings-data','oc-button')}</section></div>
      <section class="oc-panel oc-backup-history"><div class="oc-panel-title"><span class="oc-card-icon blue">${icon('activity')}</span><div><h3>Backup history</h3><p>Each entry is a real encrypted backup artifact from this installation.</p></div></div>${rows.length?rows.map(item=>`<article class="oc-backup-row"><div><strong>${esc(time(item.created_at))}</strong><small>${esc(((Number(item.size_bytes)||0)/1024/1024).toFixed(2))} MB · ${esc(item.encrypted?'Encrypted':'Encryption status unavailable')}</small></div>${status(item.status==='verified'?'Verified':'Stored · unverified',item.status==='verified'?'good':'warn')}<button type="button" class="oc-text-button" data-oc-backup-verify="${esc(item.id)}">Verify</button><button type="button" class="oc-text-button" data-oc-backup-download="${esc(item.id)}">Download</button></article>`).join(''):'<div class="oc-empty compact">No backup created yet.</div>'}</section>
      <div class="oc-note">This installation does not expose a durable scheduler, remote storage, region selection, restore-job coordination, or retention controls. Restore is not offered while the live application databases are open; this avoids replacing active data files unsafely.</div>`;
  }
  function auditPage() {
    const all=auditRows();
    const rows=all.filter(item=>{
      const detail=safeAuditDetails(item.details||{}), text=`${item.action||''} ${item.label||''} ${item.kind||''} ${item.service||''} ${JSON.stringify(detail)}`.toLowerCase();
      const categoryOk=state.category==='all'||String(item.kind||item.label||'').toLowerCase().includes(state.category);
      const queryOk=!state.query||text.includes(state.query.toLowerCase());
      const age=Date.now()-new Date(item.created_at||0).getTime(), rangeOk=state.range==='all'||!Number.isFinite(age)||age<=Number(state.range)*86400000;
      return categoryOk&&queryOk&&rangeOk;
    });
    const pageSize=10,pageCount=Math.max(1,Math.ceil(rows.length/pageSize));state.auditPage=Math.max(1,Math.min(state.auditPage,pageCount));
    const visibleRows=rows.slice((state.auditPage-1)*pageSize,state.auditPage*pageSize);state.visibleAudit=rows;
    const counts={all:all.length,security:all.filter(item=>/security|auth|session/i.test(`${item.kind} ${item.action}`)).length,config:all.filter(item=>/config|model|permission|connector/i.test(`${item.kind} ${item.action}`)).length,data:all.filter(item=>/data|backup|export|memory|knowledge/i.test(`${item.kind} ${item.action}`)).length};
    return `${hero('Complete activity history','View important owner actions and system events recorded by Vishnu. Sensitive values are redacted by the audit service.',['Owner and system activity','Sensitive values redacted'],'Activity summary',[[`${counts.all} events in recent feed`,counts.all?'good':'neutral'],[`${counts.security} security and sign-in events`,'neutral'],[`${counts.config} configuration events`,'neutral'],[`${counts.data} data events`,'neutral']])}
      <div class="oc-toolbar oc-audit-toolbar"><select id="ocAuditCategory" aria-label="Filter category"><option value="all">All categories</option>${[...new Set(all.map(item=>String(item.kind||item.label||'other').toLowerCase()))].map(value=>`<option value="${esc(value)}" ${state.category===value?'selected':''}>${esc(value.replaceAll('-',' '))}</option>`).join('')}</select><select id="ocAuditRange" aria-label="Date range"><option value="7" ${state.range==='7'?'selected':''}>Last 7 days</option><option value="30" ${state.range==='30'?'selected':''}>Last 30 days</option><option value="90" ${state.range==='90'?'selected':''}>Last 90 days</option><option value="all" ${state.range==='all'?'selected':''}>All time</option></select><label class="oc-search">${icon('search')}<input id="ocAuditSearch" type="search" value="${esc(state.query)}" placeholder="Search action, service or details…" aria-label="Search audit events"></label>${button('Export log','audit-export','oc-button primary')}</div>
      <section class="oc-panel oc-audit-list"><div class="oc-table-head"><span>Time</span><span>Action</span><span>Category</span><span>Service</span><span>Result</span><span>IP / Device</span><span>Actions</span></div>${visibleRows.length?visibleRows.map(item=>{const detail=safeAuditDetails(item.details||{}),action=item.action||item.label||item.kind||'Activity',description=detail.summary||detail.description||detail.target||'',device=[detail.ip_address,typeof detail.device==='string'?detail.device:'',detail.browser,detail.operating_system].filter(value=>typeof value==='string'&&value).join(' · ')||'Not recorded';return `<article class="oc-audit-row"><time>${esc(time(item.created_at))}</time><div><strong>${esc(String(action).replace(/[._-]+/g,' '))}</strong><small>${esc(description||'Details were not provided.')}</small></div><span class="oc-category">${esc(item.label||item.kind||'Activity')}</span><span>${esc(detail.service||detail.resource||'Vishnu')}</span>${status(item.status||'Recorded',/error|blocked|denied/i.test(item.status||'')?'bad':/pending|approval|warning/i.test(item.status||'')?'warn':'good')}<small class="oc-audit-device">${esc(device)}</small><button type="button" class="oc-detail-button" data-oc-audit-detail="${esc(item.id||'')}">Details</button></article>`}).join(''):`<div class="oc-empty"><strong>${rows.length?'No matching activity.':'No activity yet.'}</strong><p>${rows.length?'Change the filters to view other events.':'Important actions will appear when the audit service records them.'}</p></div>`}</section><div class="oc-pagination"><span>Showing ${rows.length?`${(state.auditPage-1)*pageSize+1}–${Math.min(state.auditPage*pageSize,rows.length)} of ${rows.length} recent events`:'0 events'}</span><div><button type="button" data-audit-page="prev" aria-label="Previous page" ${state.auditPage<=1?'disabled':''}>‹</button><span>${state.auditPage} / ${pageCount}</span><button type="button" data-audit-page="next" aria-label="Next page" ${state.auditPage>=pageCount?'disabled':''}>›</button></div></div><div class="oc-note">${state.data.activities?.has_more?'Showing the first 1,000 records available from the canonical audit projection.':'Showing persisted events from Vishnu’s canonical, redacted audit projection.'} “Export log” downloads the events currently returned and filtered here.</div>`;
  }
  function renderPage() {
    const output=({overview,providers:providersPage,services:servicesPage,permissions:permissionsPage,security:securityPage,backups:backupsPage,audit:auditPage})[state.section]();
    return output;
  }
  function render() {
    const host=document.getElementById('moduleBody'); if(!host)return;
    // Reattach the shared sphere to its home anchor before replacing its old
    // Owner Controls page. Otherwise a section-to-section render would detach
    // the sole sphere node and the existing identity could not be restored.
    if(typeof window.restoreIdentitySphere==='function')window.restoreIdentitySphere();
    host.innerHTML=shell();
    const target=document.querySelector('#moduleBody .oc-sphere-slot');
    if(target&&typeof window.attachIdentitySphere==='function'){window.attachIdentitySphere();document.querySelector('#moduleBody .core-stage.identity-core-stage')?.classList.add('oc-sphere-slot')}
    bind();
  }
  function go(section,{push=true}={}) {
    if(!sections.some(item=>item[0]===section))return;
    state.section=section; state.query=''; state.category='all';
    if(push)history.pushState({ownerControls:section},'',`#owner-controls/${section}`);
    document.body.classList.add('owner-controls-mode');
    document.getElementById('moduleTitle').textContent='Owner Controls';
    document.getElementById('moduleText').textContent=pageSubtitle(section);
    document.getElementById('moduleMetric').textContent='';
    render();
  }
  function bind() {
    document.querySelectorAll('[data-oc-section]').forEach(el=>el.addEventListener('click',()=>go(el.dataset.ocSection)));
    document.querySelectorAll('[data-oc-quick]').forEach(el=>el.addEventListener('click',()=>{
      const action=el.dataset.ocQuick;
      if(action==='backup-create')handleAction('backup-create');
      else if(action==='providers')handleAction('models');
      else if(action==='services')handleAction('tools');
      else go(action);
    }));
    document.querySelectorAll('[data-oc-module]').forEach(el=>el.addEventListener('click',()=>window.openModule(el.dataset.ocModule)));
    document.querySelectorAll('[data-oc-settings]').forEach(el=>el.addEventListener('click',()=>window.openModule('settings').then(()=>window.renderSettings(el.dataset.ocSettings))));
    document.querySelector('[data-oc-settings-home]')?.addEventListener('click',()=>window.openModule('settings'));
    document.querySelector('[data-oc-menu]')?.addEventListener('click',()=>document.getElementById('historyButton')?.click());
    document.querySelector('[data-oc-search]')?.addEventListener('click',()=>{document.getElementById('historyButton')?.click();setTimeout(()=>document.getElementById('sidebarSearchToggle')?.click(),80)});
    document.querySelector('[data-oc-new]')?.addEventListener('click',()=>document.getElementById('vNewChat')?.click());
    document.querySelector('[data-oc-voice]')?.addEventListener('click',()=>document.getElementById('micButton')?.click());
    document.querySelector('[data-oc-notifications]')?.addEventListener('click',()=>document.getElementById('sidebarInbox')?.click());
    document.querySelectorAll('[data-oc-account]').forEach(el=>el.addEventListener('click',()=>window.openModule('settings').then(()=>window.renderSettings('profile'))));
    document.querySelector('[data-oc-help]')?.addEventListener('click',()=>window.showToast('Help & support is not configured in this installation.'));
    document.querySelectorAll('[data-oc-action]:not([data-oc-action="audit-export"])').forEach(el=>el.addEventListener('click',()=>handleAction(el.dataset.ocAction)));
    document.querySelectorAll('[data-oc-backup-verify]').forEach(el=>el.addEventListener('click',()=>verifyBackup(el.dataset.ocBackupVerify)));
    document.querySelectorAll('[data-oc-backup-download]').forEach(el=>el.addEventListener('click',()=>downloadBackup(el.dataset.ocBackupDownload)));
    document.querySelectorAll('[data-oc-provider-default]').forEach(el=>el.addEventListener('click',()=>setDefaultProvider(el.dataset.ocProviderDefault,el)));
    document.querySelectorAll('[data-oc-provider-disconnect]').forEach(el=>el.addEventListener('click',()=>disconnectProvider(el.dataset.ocProviderDisconnect)));
    document.querySelectorAll('[data-oc-provider-model]').forEach(el=>el.addEventListener('click',()=>changeProviderModel(el.dataset.ocProviderModel)));
    document.querySelectorAll('[data-oc-action="provider-add"]').forEach(el=>el.addEventListener('click',openProviderDialog));
    const svcSearch=document.getElementById('ocServiceSearch'),svcFilter=document.getElementById('ocServiceFilter');
    const refreshServices=()=>{const host=document.getElementById('ocServiceList');if(host)host.innerHTML=renderServiceRows(connectors(),svcSearch?.value||'',svcFilter?.value||'all');document.querySelectorAll('[data-oc-action="tools"]').forEach(el=>el.onclick=()=>handleAction('tools'))};
    svcSearch?.addEventListener('input',refreshServices);svcFilter?.addEventListener('change',refreshServices);
    bindAuditControls();
    document.querySelectorAll('[data-owner-permission]').forEach(el=>el.addEventListener('change',()=>saveOwnerPermissions('custom')));
    document.getElementById('ocPermissionMode')?.addEventListener('change',event=>saveOwnerPermissions(event.target.value));
    document.getElementById('ocGlobalSearch')?.addEventListener('keydown',event=>{if(event.key==='Enter'){const q=event.target.value.trim().toLowerCase();const match=sections.find(([key,label])=>`${key} ${label} ${pageSubtitle(key)}`.toLowerCase().includes(q));if(match)go(match[0]);else window.showToast('No matching Owner Controls section.')}});
  }
  async function setDefaultProvider(providerId, buttonEl) {
    if(buttonEl)buttonEl.disabled=true;
    try{
      await call('/owner/ai-provider/default',{method:'PATCH',body:JSON.stringify({provider_id:providerId})});
      await loadData();render();window.showToast('Default AI provider updated.');
    }catch(error){if(buttonEl)buttonEl.disabled=false;window.showToast(error.message||'The provider could not be selected. Check its server configuration.');}
  }
  function openProviderDialog() {
    const root=document.querySelector('.oc-shell');if(!root)return;
    root.querySelector('.oc-provider-dialog')?.remove();
    const dialog=document.createElement('dialog');dialog.className='oc-detail-dialog oc-provider-dialog';dialog.setAttribute('aria-labelledby','ocProviderDialogTitle');
    dialog.innerHTML=`<header><div><small>Owner Controls · AI Providers</small><h2 id="ocProviderDialogTitle">Connect an AI provider</h2></div><button type="button" aria-label="Close provider setup">×</button></header><form class="oc-provider-form"><label>Provider<select name="provider"><option value="openai">OpenAI</option><option value="openrouter">OpenRouter</option><option value="gemini">Google Gemini</option></select></label><label>API key<input name="apiKey" type="password" autocomplete="new-password" required minlength="16" maxlength="4096" spellcheck="false"></label><p class="oc-provider-help">The key is sent only to Vishnu’s authenticated server, tested, then stored in the encrypted vault. It is never saved in browser storage or shown again.</p><button class="oc-button" type="button" data-provider-test>Test connection and load models</button><label>Available model<select name="model" disabled required><option value="">Test the connection first</option></select></label><p class="oc-provider-error" role="alert" aria-live="polite"></p><footer><button class="oc-button" type="button" data-provider-cancel>Cancel</button><button class="oc-button primary" type="submit" disabled>Save provider</button></footer></form>`;
    root.append(dialog);const form=dialog.querySelector('form'),key=form.elements.apiKey,provider=form.elements.provider,model=form.elements.model,test=dialog.querySelector('[data-provider-test]'),save=form.querySelector('[type="submit"]'),error=dialog.querySelector('.oc-provider-error');let verifiedKey='';
    const clear=()=>{key.value='';verifiedKey='';};
    const close=()=>{clear();dialog.close();};
    dialog.querySelector('header button').addEventListener('click',close);dialog.querySelector('[data-provider-cancel]').addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close()});dialog.addEventListener('close',()=>dialog.remove());dialog.addEventListener('click',event=>{if(event.target===dialog)close()});
    key.addEventListener('input',()=>{verifiedKey='';model.disabled=true;model.innerHTML='<option value="">Test the connection first</option>';save.disabled=true;});provider.addEventListener('change',()=>{verifiedKey='';model.disabled=true;model.innerHTML='<option value="">Test the connection first</option>';save.disabled=true;});
    test.addEventListener('click',async()=>{error.textContent='';if(!key.value){error.textContent='Enter the provider API key first.';key.focus();return;}test.disabled=true;test.textContent='Testing…';try{const data=await call('/owner/ai-providers/test',{method:'POST',body:JSON.stringify({provider_id:provider.value,api_key:key.value})});model.innerHTML=data.models.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join('');model.disabled=false;verifiedKey=key.value;save.disabled=false;}catch(err){error.textContent=err.message||'The connection could not be verified.';verifiedKey='';}finally{test.disabled=false;test.textContent='Test connection and load models';}});
    form.addEventListener('submit',async event=>{event.preventDefault();error.textContent='';if(!verifiedKey||key.value!==verifiedKey){error.textContent='Test this credential again before saving.';save.disabled=true;return;}save.disabled=true;const result=await call('/owner/ai-providers',{method:'POST',body:JSON.stringify({provider_id:provider.value,api_key:key.value,model:model.value})});clear();dialog.close();if(result?.model_status){state.data.system={...(state.data.system||{}),model:result.model_status};delete state.errors.system;}else{await loadData();}render();window.showToast('Provider connected and encrypted configuration saved.');catch(err){error.textContent=err.message||'Provider setup failed.';save.disabled=false;}});
    dialog.showModal();key.focus();
  }
  async function disconnectProvider(providerId) {
    if(!await window.requestConfirmation?.('Disconnect this owner-configured provider? Requests will stop using it. Its default model must be changed first.'))return;
    try{await call(`/owner/ai-providers/${encodeURIComponent(providerId)}`,{method:'DELETE'});await loadData();render();window.showToast('Provider disconnected.');}catch(error){window.showToast(error.message||'Provider could not be disconnected.');}
  }
  async function changeProviderModel(providerId) {
    const root=document.querySelector('.oc-shell');if(!root)return;
    root.querySelector('.oc-provider-dialog')?.remove();
    const dialog=document.createElement('dialog');dialog.className='oc-detail-dialog oc-provider-dialog';dialog.setAttribute('aria-labelledby','ocProviderModelTitle');
    dialog.innerHTML=`<header><div><small>Owner Controls · AI Providers</small><h2 id="ocProviderModelTitle">Choose a model</h2></div><button type="button" aria-label="Close model selector">×</button></header><form class="oc-provider-form"><label>Available model<select name="model" disabled><option>Loading available models…</option></select></label><p class="oc-provider-error" role="alert" aria-live="polite"></p><footer><button class="oc-button" type="button" data-provider-cancel>Cancel</button><button class="oc-button primary" type="submit" disabled>Save model</button></footer></form>`;
    root.append(dialog);const form=dialog.querySelector('form'),select=form.elements.model,save=form.querySelector('[type="submit"]'),error=dialog.querySelector('.oc-provider-error');
    const close=()=>dialog.close();dialog.querySelector('header button').addEventListener('click',close);dialog.querySelector('[data-provider-cancel]').addEventListener('click',close);dialog.addEventListener('cancel',event=>{event.preventDefault();close()});dialog.addEventListener('close',()=>dialog.remove());dialog.addEventListener('click',event=>{if(event.target===dialog)close()});dialog.showModal();
    try{const data=await call(`/owner/ai-providers/${encodeURIComponent(providerId)}/models`);select.innerHTML=data.models.map(id=>`<option value="${esc(id)}">${esc(id)}</option>`).join('');select.disabled=false;save.disabled=!data.models.length;}catch(err){error.textContent=err.message||'Available models could not be loaded.';}
    form.addEventListener('submit',async event=>{event.preventDefault();save.disabled=true;try{await call(`/owner/ai-providers/${encodeURIComponent(providerId)}/model`,{method:'PATCH',body:JSON.stringify({model:select.value})});dialog.close();await loadData();render();window.showToast('Provider model updated.');}catch(err){error.textContent=err.message||'Model could not be saved.';save.disabled=false;}});
  }
  async function saveOwnerPermissions(mode) {
    if(state.permissionSaving)return;
    const previous=JSON.parse(JSON.stringify(state.data.ownerPermissions||{}));
    const rules={...(previous.rules||{})};
    document.querySelectorAll('[data-owner-permission]').forEach(el=>{rules[el.dataset.ownerPermission]=el.value});
    if(Object.keys(rules).length!==8){window.showToast('Permission rules are unavailable. Reload this page and try again.');return}
    state.permissionSaving=true;
    const statusEl=document.getElementById('ocPermissionSaveStatus');if(statusEl)statusEl.textContent='Saving permission rules…';
    document.querySelectorAll('[data-owner-permission],#ocPermissionMode').forEach(el=>el.disabled=true);
    try{
      const result=await call('/owner/permissions',{method:'PATCH',body:JSON.stringify({mode,rules})});
      state.data.ownerPermissions={mode:result.mode,rules:result.rules};
      state.errors.ownerPermissions=null;
      window.showToast('Owner permission rules saved.');
    }catch(error){
      state.data.ownerPermissions=previous;
      window.showToast(error.message||'Permission rules could not be saved.');
    }finally{state.permissionSaving=false;render()}
  }
  function bindAuditControls() {
    const refresh=focusId=>{const body=document.getElementById('ocPageBody');if(!body)return;body.innerHTML=auditPage();bindAuditControls();if(focusId){const input=document.getElementById(focusId);input?.focus({preventScroll:true});if(focusId==='ocAuditSearch')input?.setSelectionRange(input.value.length,input.value.length)}};
    document.getElementById('ocAuditSearch')?.addEventListener('input',event=>{state.query=event.target.value;state.auditPage=1;refresh('ocAuditSearch')});
    document.getElementById('ocAuditCategory')?.addEventListener('change',event=>{state.category=event.target.value;state.auditPage=1;refresh('ocAuditCategory')});
    document.getElementById('ocAuditRange')?.addEventListener('change',event=>{state.range=event.target.value;state.auditPage=1;refresh('ocAuditRange')});
    document.querySelectorAll('[data-audit-page]').forEach(button=>button.addEventListener('click',()=>{state.auditPage+=button.dataset.auditPage==='next'?1:-1;refresh()}));
    document.querySelectorAll('[data-oc-audit-detail]').forEach(el=>el.addEventListener('click',()=>showAuditDetail(el.dataset.ocAuditDetail)));
    document.querySelector('[data-oc-action="audit-export"]')?.addEventListener('click',()=>handleAction('audit-export'));
  }
  async function handleAction(action) {
    if(action==='models')return window.openModule('settings').then(()=>window.renderSettings('models'));
    if(action==='tools')return window.openModule('tools');
    if(action==='backup-refresh'||action==='permissions-refresh'){await loadData();render();return}
    if(action==='backup-create'){
      const buttonEl=document.querySelector('[data-oc-action="backup-create"]');if(buttonEl)buttonEl.disabled=true;
      try{const result=await call('/owner/backups',{method:'POST',body:'{}'});await loadData();render();window.showToast(result.backup?.status==='verified'?'Encrypted backup created and verified.':'Backup created; verify its integrity before relying on it.')}catch(error){if(buttonEl)buttonEl.disabled=false;window.showToast(error.message||'Backup creation failed.')}return;
    }
    if(action==='emergency-stop'){
      if(!await window.requestConfirmation?.('Pause Vishnu tool actions and cancel currently running tool execution? Chat remains available.'))return;
      try{await call('/system/emergency-stop',{method:'POST',body:JSON.stringify({enabled:true})});await loadData();render();window.showToast('Emergency stop is active. Tool actions are blocked.')}catch(error){window.showToast(error.message||'Emergency stop could not be activated.')}return;
    }
    if(action==='emergency-resume'){
      if(!await window.requestConfirmation?.('Resume Vishnu autonomous tool actions? High-risk actions will still require owner approval.'))return;
      try{await call('/system/emergency-stop',{method:'POST',body:JSON.stringify({enabled:false})});await loadData();render();window.showToast('Autonomous tool actions resumed.')}catch(error){window.showToast(error.message||'Autonomous actions could not be resumed.')}return;
    }
    if(action==='permissions-reset'){
      if(!await window.requestConfirmation?.('Restore the default owner permission rules?'))return;
      const rules={read:'allow',create:'allow',edit:'allow',delete:'ask',external_communication:'ask',execute_actions:'ask',financial_actions:'ask',account_security_changes:'ask'};
      try{const result=await call('/owner/permissions',{method:'PATCH',body:JSON.stringify({mode:'balanced',rules})});state.data.ownerPermissions={mode:result.mode,rules:result.rules};render();window.showToast('Default permission rules restored.')}catch(error){window.showToast(error.message||'Permission defaults could not be restored.')}return;
    }
    if(action==='approvals')return window.openModule('settings').then(()=>window.renderSettings('approvals'));
    if(action==='security'||action==='security-settings')return window.openModule('settings').then(()=>window.renderSettings('security'));
    if(action==='settings-data')return window.openModule('settings').then(()=>window.renderSettings('data'));
    if(action==='settings-notifications')return window.openModule('settings').then(()=>window.renderSettings('notifications'));
    if(action==='devices')return window.openModule('devices');
    if(action==='export'){
      try{const value=await call('/privacy/export');const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`vishnu-data-export-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);window.showToast('Data export created.')}catch(error){window.showToast(error.message||'Data export failed.')}return;
    }
    if(action==='audit-export'){
      const rows=Array.isArray(state.visibleAudit)?state.visibleAudit:auditRows();
      const csv=[['time','action','category','status','details'],...rows.map(item=>[item.created_at||'',item.action||item.label||'',item.kind||item.label||'',item.status||'',JSON.stringify(safeAuditDetails(item.details||{}))])].map(row=>row.map(value=>`"${String(value).replaceAll('"','""')}"`).join(',')).join('\r\n');
      const blob=new Blob([csv],{type:'text/csv'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`vishnu-audit-export-${new Date().toISOString().slice(0,10)}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
  }
  async function verifyBackup(id) {
    try{const result=await call(`/owner/backups/${encodeURIComponent(id)}/verify`,{method:'POST',body:'{}'});await loadData();render();window.showToast(result.ok?'Backup integrity verified.':'Backup verification failed.')}catch(error){window.showToast(error.message||'Backup could not be verified.')}
  }
  async function downloadBackup(id) {
    try{const response=await fetch(`/iphone/api/owner/backups/${encodeURIComponent(id)}/download`,{credentials:'same-origin'});if(!response.ok)throw new Error('Backup download failed.');const blob=await response.blob(),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=id;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}catch(error){window.showToast(error.message||'Backup download failed.')}
  }
  async function showAuditDetail(id) {
    const item=auditRows().find(value=>String(value.id||'')===String(id));if(!item)return;
    let event=item;
    try{const result=await call(`/activities/${encodeURIComponent(id)}`);if(result.activity)event=result.activity}catch(error){window.showToast(error.message||'Full event details are unavailable. Showing the recorded summary.')}
    const d=safeAuditDetails(event.details||{}), root=document.querySelector('.oc-shell');if(!root)return;
    root.querySelector('.oc-detail-dialog')?.remove();
    const dialog=document.createElement('dialog');dialog.className='oc-detail-dialog';
    dialog.setAttribute('aria-labelledby','ocAuditDetailTitle');
    const facts=[['Time',time(event.created_at)],['Category',event.label||event.kind||'Activity'],['Service',d.service||d.resource||'Not recorded'],['Result',event.status||'Recorded'],['Actor',d.actor||d.actor_type||'You / Vishnu / System'],['Project',d.project_name||d.project||'Not recorded'],['Device',typeof d.device==='string'?d.device:'Not recorded'],['IP address',d.ip_address||'Not recorded'],['Event ID',event.id||id]];
    dialog.innerHTML=`<header><div><small>Audit event</small><h2 id="ocAuditDetailTitle">${esc(event.action||event.label||event.kind||'Activity')}</h2></div><button type="button" aria-label="Close details">×</button></header><div class="oc-detail-grid">${facts.map(([label,value])=>`<span>${esc(label)}</span><strong>${esc(value)}</strong>`).join('')}</div><pre>${esc(JSON.stringify(d,null,2))}</pre>`;
    root.append(dialog);dialog.showModal();dialog.querySelector('button').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>dialog.remove());dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});
  }
  async function loadOwnerControlsPage() {
    document.body.classList.add('owner-controls-mode');
    const fromHash=location.hash.match(/^#owner-controls\/(overview|providers|services|permissions|security|backups|audit)$/)?.[1];
    state.section=fromHash||state.section||'overview';
    document.getElementById('moduleTitle').textContent='Owner Controls';
    document.getElementById('moduleText').textContent=pageSubtitle(state.section);
    document.getElementById('moduleMetric').textContent='';
    state.loading=true;
    render();
    await loadData();
    state.loading=false;
    document.getElementById('modulePanel')?.classList.add('open');
    document.getElementById('voicePanel')?.classList.add('hidden');document.getElementById('features')?.classList.add('hidden');
    render();
  }
  window.loadOwnerPage=loadOwnerControlsPage;
  window.loadOwnerControlsPage=loadOwnerControlsPage;
  window.addEventListener('popstate',()=>{
    if(location.hash.startsWith('#owner-controls/')){const section=location.hash.split('/')[1];if(sections.some(item=>item[0]===section)){state.section=section;if(document.body.classList.contains('owner-controls-mode'))render()}}
    else if(document.body.classList.contains('owner-controls-mode'))window.openModule('home');
  });
})();

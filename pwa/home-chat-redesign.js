/* Reference Home and system-wide chat. Reuses the existing sphere, chat, and navigation. */
(function(){
  const $ = window.$ || (id => document.getElementById(id));
  const folder = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
  const icons = {
    projects: folder,
    assign: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.6 4.2L18 9l-4.4 1.8L12 15l-1.6-4.2L6 9l4.4-1.8z"/></svg>',
    today: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/></svg>',
    memory: '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="7" rx="7" ry="3"/><path d="M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5"/></svg>'
  };

  function placeSphere(){
    const stage = document.querySelector('.core-stage');
    const homeStage = $('homeSphereStage');
    const headerBrand = document.querySelector('.header-core');
    if(!stage || !homeStage || !headerBrand) return;
    if(document.body.classList.contains('home-landing')) homeStage.appendChild(stage);
    else headerBrand.appendChild(stage);
    if(typeof resizeCanvas === 'function') requestAnimationFrame(resizeCanvas);
  }

  function personalizeGreeting(){
    const node = $('homeGreeting');
    if(!node || typeof greeting !== 'function') return;
    const base = greeting().replace(/\.$/, '');
    const name = typeof ownerDisplayName === 'function' ? ownerDisplayName() : '';
    node.textContent = name ? base + ', ' + name : base;
  }

  function syncAttachIcon(){
    const button = $('attachmentButton');
    if(!button) return;
    const home = document.body.classList.contains('home-landing');
    button.setAttribute('aria-label', home ? 'Attach a file' : 'Add to message');
    button.innerHTML = home
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 12.5 14.8 5.7a3 3 0 0 1 4.2 4.2l-8.2 8.2a4.2 4.2 0 0 1-6-6l7.4-7.4"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
  }

  async function loadRecentProjects(){
    const host = $('homeProjectList');
    if(!host) return;
    host.replaceChildren();
    const loading = document.createElement('p');
    loading.className = 'v-empty';
    loading.textContent = 'Loading your projects…';
    host.append(loading);
    try{
      const data = await api('/projects');
      const rows = Array.isArray(data.projects) ? data.projects : [];
      host.replaceChildren();
      if(!rows.length){
        const empty = document.createElement('div');
        empty.className = 'v-empty';
        empty.innerHTML = '<p>No projects yet. Create a workspace to keep files, tasks, and chat scoped to that project.</p>';
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'v-action';
        button.textContent = 'Create a project';
        button.onclick = () => openProjects();
        empty.append(button);
        host.append(empty);
        return;
      }
      rows.slice(0, 4).forEach(project => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'v-project';
        const status = project.goal || project.description || 'No recent update yet';
        row.innerHTML = '<span class="v-icon">'+folder+'</span><span><strong></strong><small><i class="v-status-dot"></i></small></span><span class="v-chev" aria-hidden="true">›</span>';
        row.querySelector('strong').textContent = project.name || 'Untitled project';
        row.querySelector('small').append(document.createTextNode(status));
        row.onclick = () => openProjectWorkspace(project.id);
        host.append(row);
      });
    }catch(error){
      host.replaceChildren();
      const box = document.createElement('div');
      box.className = 'v-error';
      box.innerHTML = '<p></p>';
      box.querySelector('p').textContent = error && error.status === 404
        ? 'Projects are not available on this runtime yet.'
        : (error.message || 'Could not load projects.');
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'v-action';
      retry.textContent = 'Retry';
      retry.onclick = () => loadRecentProjects();
      box.append(retry);
      host.append(box);
    }
  }

  function openProjects(){
    closeAllDrawers();
    if(typeof openModule === 'function') openModule('projects');
    else showToast('Projects are not available in this build.');
  }
  function openProjectWorkspace(id){
    closeAllDrawers();
    if(typeof openProject === 'function') openProject(id);
    else if(typeof openModule === 'function') openModule('projects');
    else showToast('That project workspace is not available.');
  }
  async function assignWork(){
    closeAllDrawers();
    let rows = [];
    try{ rows = (await api('/projects')).projects || []; }catch{ rows = []; }
    if(!rows.length){
      if(typeof openCreationDialog === 'function') openCreationDialog('work');
      else showToast('Task assignment is not available yet.');
      return;
    }
    const choice = await requestText('Assign work to a project. Enter the project name, or leave blank to choose in Projects.');
    if(choice == null) return;
    const match = rows.find(project => project.name.toLowerCase() === String(choice).trim().toLowerCase());
    if(!match){ openProjects(); showToast('Select a project, then add a task there.'); return; }
    openProjectWorkspace(match.id);
    showToast('Opened '+match.name+'. Add the task in that workspace.');
  }

  function wireHome(){
    const cards = {
      vProjects: openProjects,
      vAssign: () => assignWork().catch(error => showToast(error.message)),
      vToday: () => { closeAllDrawers(); typeof openTodayScreen === 'function' ? openTodayScreen() : openModule('today'); },
      vMemory: () => { closeAllDrawers(); openModule('memory'); },
      vViewAllProjects: openProjects
    };
    Object.entries(cards).forEach(([id, action]) => { const node = $(id); if(node) node.onclick = action; });
    const fresh = $('vNewChat');
    if(fresh) fresh.onclick = () => createConversation();
    const chip = $('vContextChip');
    if(chip) chip.onclick = () => openContextChooser().catch(error => showToast(error.message));
    const scope = $('vScopeButton');
    if(scope) scope.onclick = () => openContextChooser().catch(error => showToast(error.message));
  }

  async function openContextChooser(){
    let rows = [];
    try{ rows = (await api('/projects')).projects || []; }catch{ rows = []; }
    const names = rows.map(project => project.name).join(', ');
    const choice = await requestText(rows.length
      ? 'General chat has no project context. Enter a project name to open its workspace, or leave blank to stay in general chat. Available: '+names
      : 'This conversation is general chat with no project context. Create a project before attaching one.');
    if(!choice) return;
    const match = rows.find(project => project.name.toLowerCase() === String(choice).trim().toLowerCase());
    if(!match){ showToast('No matching project. General chat was kept.'); return; }
    openProjectWorkspace(match.id);
  }

  async function renderWorkCards(){
    const stream = $('messageStream');
    if(!stream || document.body.classList.contains('home-landing')) return;
    stream.querySelectorAll('.v-work').forEach(node => node.remove());
    const lastUser = [...conversationEvents].reverse().find(event => event.kind === 'user_message');
    const asked = lastUser && /update|attention|continue|task|work/i.test(String(lastUser.payload && lastUser.payload.text || ''));
    if(!asked) return;
    let projects = [];
    try{ projects = (await api('/projects')).projects || []; }catch{ return; }
    if(!projects.length) return;
    const details = [];
    for(const project of projects.slice(0, 4)){
      try{ details.push((await api('/projects/'+encodeURIComponent(project.id))).project || project); }
      catch{ details.push(project); }
    }
    const attention = [];
    const next = [];
    details.forEach(project => {
      (project.tasks || []).forEach(task => {
        if(task.status === 'done') return;
        const item = {project, task};
        if(task.owner === 'vishnu' && task.status === 'planned') next.push(item);
        else attention.push(item);
      });
    });
    if(!attention.length && !next.length) return;
    const block = document.createElement('section');
    block.className = 'v-work';
    block.setAttribute('aria-label', 'Work that needs attention');
    if(attention.length){
      const title = document.createElement('h3');
      title.textContent = 'Items that need your attention';
      block.append(title);
      attention.slice(0, 3).forEach(item => block.append(workCard(item, false)));
    }
    if(next.length){
      const title = document.createElement('h3');
      title.textContent = 'Next action for Vishnu';
      block.append(title);
      next.slice(0, 2).forEach(item => block.append(workCard(item, true)));
    }
    const tools = document.createElement('div');
    tools.className = 'v-toolbar';
    [['Copy response','copy'],['Helpful','up'],['Not helpful','down'],['More','more']].forEach(([label, kind]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.title = label;
      button.setAttribute('aria-label', label);
      button.textContent = kind === 'copy' ? '⧉' : kind === 'up' ? '👍' : kind === 'down' ? '👎' : '…';
      button.onclick = () => handleWorkTool(kind);
      tools.append(button);
    });
    block.append(tools);
    stream.append(block);
    if(conversationPinnedToBottom) stream.scrollTop = stream.scrollHeight;
  }

  function workCard(item, isNext){
    const card = document.createElement('article');
    card.className = 'v-work-card';
    const status = item.task.status === 'in_progress' ? 'In progress' : item.task.status === 'blocked' ? 'Needs your review' : isNext ? 'Ready to start' : 'Needs your review';
    card.innerHTML = '<span class="v-icon">'+folder+'</span><div><strong></strong><small></small><div class="v-pill"></div></div>';
    card.querySelector('strong').textContent = isNext ? item.task.title : item.project.name;
    card.querySelector('small').textContent = isNext ? 'From: '+(item.project.name || 'Project') : 'Project · '+(item.project.goal || 'Workspace');
    const pill = card.querySelector('.v-pill');
    pill.classList.add(status === 'In progress' || status === 'Ready to start' ? 'ok' : 'warn');
    pill.textContent = status;
    const action = document.createElement('button');
    action.type = 'button';
    action.className = 'v-action';
    action.textContent = isNext ? 'Start work' : item.task.status === 'in_progress' ? 'View progress' : 'Review';
    action.onclick = () => runWorkAction(item, action.textContent);
    card.append(action);
    return card;
  }

  async function runWorkAction(item, label){
    if(label === 'Start work'){
      try{
        await api('/projects/'+encodeURIComponent(item.project.id)+'/tasks/'+encodeURIComponent(item.task.id), {method:'PATCH', body:JSON.stringify({status:'in_progress'})});
        showToast('Started: '+item.task.title);
        renderWorkCards();
      }catch(error){ showToast(error.message || 'Could not start that task.'); }
      return;
    }
    openProjectWorkspace(item.project.id);
  }

  function handleWorkTool(kind){
    if(kind === 'copy'){
      const last = [...conversationEvents].reverse().find(event => event.kind === 'assistant_message');
      const text = last && last.payload && last.payload.text || '';
      navigator.clipboard?.writeText(text).then(() => showToast('Response copied')).catch(() => showToast('Could not copy that response'));
      return;
    }
    if(kind === 'more'){ $('chatMenuButton')?.click(); return; }
    showToast(kind === 'up' ? 'Marked helpful' : 'Marked not helpful');
  }

  function boot(){
    document.body.classList.add('v-ref');
    const originalHome = enterHomeLanding;
    enterHomeLanding = function(){ originalHome(); personalizeGreeting(); placeSphere(); syncAttachIcon(); loadRecentProjects(); };
    const originalConversation = enterConversationView;
    enterConversationView = function(){ originalConversation(); placeSphere(); syncAttachIcon(); };
    const originalRender = renderMessages;
    renderMessages = function(){ originalRender(); renderWorkCards(); };
    wireHome();
    personalizeGreeting();
    placeSphere();
    syncAttachIcon();
    if(document.body.classList.contains('home-landing')) loadRecentProjects();
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();

(()=>{
'use strict';

const VISUAL_API='/iphone/api/visualizations';
const TYPE_OPTIONS=[
  ['architecture','Architecture'],['workflow','Workflow'],['sequence','Sequence'],
  ['dataflow','Data Flow'],['lifecycle','Lifecycle'],['project_map','Project Map'],
];
let dialog=null;

function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
async function jsonRequest(url,options={}){
  const response=await fetch(url,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  let data={};try{data=await response.json()}catch{}
  if(!response.ok)throw new Error((typeof data.detail==='string'&&data.detail)||data.error||`Request failed (${response.status})`);
  return data;
}
function toast(message){
  let node=document.getElementById('vzToast');
  if(!node){node=document.createElement('div');node.id='vzToast';node.className='vz-toast';document.body.append(node)}
  node.textContent=message;node.classList.remove('vz-hidden');clearTimeout(node._timer);node._timer=setTimeout(()=>node.classList.add('vz-hidden'),3200);
}
function closeDialog(){dialog?.remove();dialog=null}
function shell(title,subtitle,body){
  closeDialog();dialog=document.createElement('div');dialog.className='vz-source-dialog-backdrop';dialog.innerHTML=`<section class="vz-source-dialog" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header class="vz-source-dialog-head"><div><strong>${esc(title)}</strong><span>${esc(subtitle)}</span></div><button type="button" class="vz-source-dialog-close" aria-label="Close">×</button></header><div class="vz-source-dialog-body">${body}</div></section>`;document.body.append(dialog);dialog.querySelector('.vz-source-dialog-close').onclick=closeDialog;dialog.addEventListener('click',event=>{if(event.target===dialog)closeDialog()});return dialog
}
function typeSelect(defaultValue='workflow',includeProject=true){
  return `<select class="vz-source-dialog-select" data-vz-source-type>${TYPE_OPTIONS.filter(([value])=>includeProject||value!=='project_map').map(([value,label])=>`<option value="${value}" ${value===defaultValue?'selected':''}>${label}</option>`).join('')}</select>`
}
function openCreated(item){
  closeDialog();
  if(window.VishnuVisualize){window.VishnuVisualize.open();setTimeout(()=>window.VishnuVisualize.openVisual(item.id),60)}
  toast('Visual created from Vishnu source context.');
}

async function projectPicker(){
  const root=shell('Visualize a Project','Choose a Vishnu Project. The map uses its real goal, tasks, milestones, files and live work.','<input class="vz-source-dialog-search" type="search" placeholder="Search projects…" aria-label="Search projects"><div class="vz-source-list"><div class="vz-source-loading">Loading projects…</div></div>');
  const list=root.querySelector('.vz-source-list'),search=root.querySelector('.vz-source-dialog-search');
  let projects=[];
  try{const data=await jsonRequest('/iphone/api/projects?status=all&sort=recent');projects=Array.isArray(data.projects)?data.projects:[]}
  catch(error){list.innerHTML=`<div class="vz-source-empty">${esc(error.message)}</div>`;return}
  const render=()=>{
    const q=search.value.trim().toLowerCase();const filtered=projects.filter(project=>!q||`${project.name||''} ${project.goal||''}`.toLowerCase().includes(q));
    list.innerHTML=filtered.map(project=>`<button class="vz-source-option" type="button" data-project-id="${esc(project.id)}"><div><strong>${esc(project.name||'Untitled project')}</strong><span>${esc(project.goal||'No project goal yet')}</span></div><b>${esc(project.status||'active')}</b></button>`).join('')||'<div class="vz-source-empty">No matching projects.</div>';
    list.querySelectorAll('[data-project-id]').forEach(button=>button.onclick=async()=>{
      button.disabled=true;button.querySelector('b').textContent='Creating…';
      try{const data=await jsonRequest(VISUAL_API,{method:'POST',body:JSON.stringify({title:'Project Map',type:'project_map',mode:'manual',description:'Visualize this Vishnu project with goals, work, agents, files, milestones and execution state.',source_kind:'project',project_id:button.dataset.projectId})});openCreated(data.visualization)}
      catch(error){toast(error.message);button.disabled=false;button.querySelector('b').textContent='Try again'}
    })
  };
  search.oninput=render;render();search.focus()
}

async function conversationPicker(){
  const root=shell('Visualize a Conversation','Choose a conversation and the visual model Vishnu should use.',`<div class="vz-source-dialog-field"><label>Visual type</label>${typeSelect('workflow',false)}</div><input class="vz-source-dialog-search" style="margin-top:12px" type="search" placeholder="Search conversations…" aria-label="Search conversations"><div class="vz-source-list"><div class="vz-source-loading">Loading conversations…</div></div>`);
  const list=root.querySelector('.vz-source-list'),search=root.querySelector('.vz-source-dialog-search'),select=root.querySelector('[data-vz-source-type]');
  let conversations=[];
  try{const data=await jsonRequest('/iphone/api/conversations?limit=100');conversations=Array.isArray(data.conversations)?data.conversations:[]}
  catch(error){list.innerHTML=`<div class="vz-source-empty">${esc(error.message)}</div>`;return}
  const render=()=>{
    const q=search.value.trim().toLowerCase();const filtered=conversations.filter(item=>!q||`${item.title||''} ${item.preview||''}`.toLowerCase().includes(q));
    list.innerHTML=filtered.map(item=>`<button class="vz-source-option" type="button" data-conversation-id="${esc(item.id)}"><div><strong>${esc(item.title||'Conversation')}</strong><span>${esc(item.preview||'No preview')}</span></div><b>${Number(item.event_count||0)} msgs</b></button>`).join('')||'<div class="vz-source-empty">No matching conversations.</div>';
    list.querySelectorAll('[data-conversation-id]').forEach(button=>button.onclick=async()=>{
      button.disabled=true;button.querySelector('b').textContent='Creating…';
      try{const data=await jsonRequest(VISUAL_API,{method:'POST',body:JSON.stringify({title:'Conversation',type:select.value,mode:'manual',description:'',source_kind:'conversation',conversation_id:button.dataset.conversationId})});openCreated(data.visualization)}
      catch(error){toast(error.message);button.disabled=false;button.querySelector('b').textContent='Try again'}
    })
  };
  search.oninput=render;render();search.focus()
}

function githubPicker(){
  const root=shell('Visualize a GitHub Repository','Public repositories are read from GitHub and mapped with repository-path evidence.',`<div class="vz-source-dialog-field"><label>Repository URL</label><input class="vz-source-dialog-input" data-github-url type="url" inputmode="url" placeholder="https://github.com/owner/repository" autocomplete="off"></div><div class="vz-source-dialog-note">Vishnu reads the public repository metadata and file tree from GitHub. Repository-derived nodes are labeled as strong evidence; deeper source-line verification can be added by later analyzers.</div><div class="vz-source-dialog-actions"><button type="button" data-cancel>Cancel</button><button type="button" class="primary" data-create>Generate architecture</button></div>`);
  const input=root.querySelector('[data-github-url]'),create=root.querySelector('[data-create]');root.querySelector('[data-cancel]').onclick=closeDialog;
  create.onclick=async()=>{
    const url=input.value.trim();if(!url){input.focus();return}
    create.disabled=true;create.textContent='Reading repository…';
    try{const data=await jsonRequest(VISUAL_API,{method:'POST',body:JSON.stringify({title:'Untitled visual',type:'architecture',mode:'manual',description:'',source_kind:'github',source_ref:url})});openCreated(data.visualization)}
    catch(error){toast(error.message);create.disabled=false;create.textContent='Generate architecture'}
  };
  input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();create.click()}});input.focus()
}

function bytesToBase64(buffer){
  const bytes=new Uint8Array(buffer);let binary='';const chunk=0x8000;for(let i=0;i<bytes.length;i+=chunk)binary+=String.fromCharCode(...bytes.subarray(i,i+chunk));return btoa(binary)
}
function filePicker(){
  const root=shell('Visualize a File','PDF, DOCX, CSV, JSON, Markdown, text and source-code files are extracted locally by Vishnu.',`<div class="vz-source-dialog-field"><label>Visual type</label>${typeSelect('architecture',false)}</div><label class="vz-file-drop" for="vzSourceFile"><input id="vzSourceFile" type="file" hidden accept=".pdf,.docx,.csv,.json,.jsonl,.md,.markdown,.txt,.rst,.yaml,.yml,.py,.js,.jsx,.ts,.tsx,.html,.css,.sql,.toml,.xml,.java,.kt,.swift,.go,.rs,.c,.h,.cpp"><span><strong>Choose a file</strong>Maximum 6 MB · extracted text stays owner-scoped in Vishnu</span></label><div class="vz-source-dialog-note" data-file-note>Choose one supported file to generate a visual.</div>`);
  const input=root.querySelector('#vzSourceFile'),select=root.querySelector('[data-vz-source-type]'),note=root.querySelector('[data-file-note]');
  input.onchange=async()=>{
    const file=input.files?.[0];if(!file)return;if(file.size>6*1024*1024){toast('File exceeds the 6 MB Visualize limit.');input.value='';return}
    note.textContent=`Reading ${file.name}…`;
    try{
      const content_base64=bytesToBase64(await file.arrayBuffer());note.textContent='Extracting and generating visual…';
      const data=await jsonRequest(`${VISUAL_API}/from-file`,{method:'POST',body:JSON.stringify({filename:file.name,content_base64,type:select.value,mode:'manual'})});openCreated(data.visualization)
    }catch(error){toast(error.message);note.textContent='Choose a supported file and try again.'}
  }
}

function intercept(event){
  const card=event.target.closest?.('[data-vz-source]');if(!card)return;const kind=card.dataset.vzSource;if(!['project','conversation','github','files'].includes(kind))return;
  event.preventDefault();event.stopImmediatePropagation();
  if(kind==='project')projectPicker();else if(kind==='conversation')conversationPicker();else if(kind==='github')githubPicker();else filePicker()
}
document.addEventListener('click',intercept,true);
window.VishnuVisualizeSources={project:projectPicker,conversation:conversationPicker,github:githubPicker,files:filePicker};
})();

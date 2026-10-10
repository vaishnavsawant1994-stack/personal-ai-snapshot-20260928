import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const base=process.env.PWA_PREVIEW_URL||'http://127.0.0.1:4173';
const screenshotDir=process.env.AGENT_WORKFORCE_SCREENSHOT_DIR||'';
if(screenshotDir)fs.mkdirSync(screenshotDir,{recursive:true});

const mk=(id,name,role,description,instances,active,version='1.0',system_owned=true,caps=[])=>({
  id,slug:id.replace('agent-',''),name,role,description,system_owned,
  preferred_version:{id:`ver-${id}`,template_id:id,version,state:'preferred',capabilities:caps,tools:role==='coding'?['github','git','terminal','files']:[],memory_policy:'project_only'},
  version_count:role==='coding'?4:1,instance_count:instances,active_instance_count:active,
});
const templates=[
  mk('agent-vishnu','Vishnu','project_manager','Main AI orchestrator',5,5,'2.1',true,['orchestration','planning','management']),
  mk('agent-project-manager','Project Manager','project_manager','Project planning and team coordination',8,7,'1.3',true,['planning','coordination','reporting']),
  mk('agent-coding','Coding Agent','coding','Software development and repository work',32,27,'1.2',true,['development','git','testing','code_review']),
  mk('agent-research','Research Agent','research','Web research and information gathering',18,14,'2.1',true,['web_research','analysis','sources']),
  mk('agent-browser','Browser Agent','browser','Web browsing and automation',11,8,'1.4',true,['browsing','data_extraction','automation']),
  mk('agent-data','Data Agent','data','Data analysis and processing',9,7,'1.1',true,['analysis','sql','visualization']),
  mk('agent-qa','QA Agent','qa','Testing and quality assurance',12,9,'1.3',true,['testing','validation']),
  mk('agent-security','Security Agent','security','Security review and vulnerability analysis',8,5,'1.3',true,['security','audit']),
  mk('agent-design','Design Agent','design','UI/UX design and visual systems',6,5,'1.0',true,['ui_ux','design']),
  mk('agent-reviewer','Reviewer Agent','reviewer','Code and content review',12,9,'2.0',true,['review','verification']),
  mk('agent-custom','Custom Agent','custom','Owner-created specialist agents',8,7,'1.0',false,['custom']),
];
const projects=[
  {id:'project-a',name:'Vishnu',goal:'Ship Vishnu',status:'active'},
  {id:'project-b',name:'The Perspective',goal:'Ship publication',status:'active'},
  {id:'project-c',name:'Website Redesign',goal:'Refresh web experience',status:'active'},
  {id:'project-d',name:'Aerospace Research',goal:'Research program',status:'active'},
];
const coding=templates.find(x=>x.id==='agent-coding');
const detail={...coding,
  versions:[
    {...coding.preferred_version,id:'ver-coding-12',version:'1.2',state:'preferred',created_at:'2026-09-14T10:00:00Z',instructions:'Preferred coding agent.'},
    {...coding.preferred_version,id:'ver-coding-13rc',version:'1.3-rc',state:'experimental',created_at:'2026-10-10T10:00:00Z',instructions:'Candidate improvements.'},
    {...coding.preferred_version,id:'ver-coding-11',version:'1.1',state:'stable',created_at:'2026-08-22T10:00:00Z',instructions:'Previous stable version.'},
    {...coding.preferred_version,id:'ver-coding-10',version:'1.0',state:'archived',created_at:'2026-07-14T10:00:00Z',instructions:'Legacy version.'},
  ],
  instances:[
    {id:'coding-01',version_id:'ver-coding-12',project_id:'project-a',state:'working',current_work_order_id:'work-api',model_provider:'anthropic',model_id:'claude'},
    {id:'coding-02',version_id:'ver-coding-12',project_id:'project-b',state:'working',current_work_order_id:'work-tests',model_provider:'openai',model_id:'gpt'},
    {id:'coding-03',version_id:'ver-coding-12',project_id:'project-c',state:'working',current_work_order_id:'work-ui',model_provider:'anthropic',model_id:'claude'},
    {id:'coding-04',version_id:'ver-coding-12',project_id:'project-a',state:'working',current_work_order_id:'work-review',model_provider:'openai',model_id:'gpt'},
    {id:'coding-05',version_id:'ver-coding-12',project_id:'project-d',state:'idle',current_work_order_id:null,model_provider:null,model_id:null},
    {id:'coding-06',version_id:'ver-coding-12',project_id:'project-a',state:'working',current_work_order_id:'work-fix',model_provider:'anthropic',model_id:'claude'},
  ],
  observations:[{id:'obs-1',kind:'verification_success',summary:'Regression suite passed.',score:1,project_id:'project-a',created_at:'2026-10-10T10:00:00Z'}],conversations:[],
};

async function mockApi(page){
  await page.route('**/iphone/api/projects*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({projects})}));
  await page.route('**/iphone/api/agents**',async r=>{
    const req=r.request(),path=new URL(req.url()).pathname,method=req.method();let body;
    if(path==='/iphone/api/agents/summary')body={total_agents:templates.length,total_instances:129,active_instances:96,working_now:76,idle:33,projects_using_agents:4,running_tasks:37,success_rate:94.7};
    else if(path==='/iphone/api/agents'&&method==='GET')body={agents:templates};
    else if(path==='/iphone/api/agents/agent-coding'&&method==='GET')body=detail;
    else if(path==='/iphone/api/agents/agent-coding/conversations'&&method==='GET')body={conversations:[]};
    else if(path==='/iphone/api/agents/agent-coding/conversations'&&method==='POST')body={conversation:{id:'chat-1',template_id:'agent-coding',version_id:'ver-coding-12',instance_id:'coding-01',project_id:'project-a',title:'Coding Agent · Vishnu',state:'active',created_at:'2026-10-10T10:00:00Z',updated_at:'2026-10-10T10:00:00Z'}};
    else if(path==='/iphone/api/agents/conversations/chat-1'&&method==='GET')body={id:'chat-1',template_id:'agent-coding',version_id:'ver-coding-12',instance_id:'coding-01',project_id:'project-a',title:'Coding Agent · Vishnu',state:'active',messages:[]};
    else if(path==='/iphone/api/agents/conversations/chat-1/messages'&&method==='POST')body={conversation:{id:'chat-1',project_id:'project-a'},user_message:{role:'user',content:'Check the failing tests',created_at:'2026-10-10T10:01:00Z'},assistant_message:{role:'assistant',content:'I can inspect the Project-scoped test context. Tool execution remains governed by Vishnu.',provider:'test',model_id:'test-model',created_at:'2026-10-10T10:01:01Z'},usage:{total_tokens:10},model_output_authority:false,tool_execution_authority:false,completion_authority:false};
    else if(path==='/iphone/api/agents/agent-coding/work-requests'&&method==='POST')body={project_id:'project-a',template_id:'agent-coding',conversation_id:'chat-1',message:'Canonical Project Work created for this request.',work:{created:true,plan_id:'plan-1'},team:[],unmapped_work_orders:[],execution_authority:false,tool_authority:false,completion_authority:false};
    else if(path.startsWith('/iphone/api/agents/')&&method==='GET'&&!path.includes('/conversations')){const id=path.split('/').at(-1),item=templates.find(x=>x.id===id);if(item)body={...item,versions:[item.preferred_version],instances:[],observations:[],conversations:[]};}
    if(body===undefined)return r.fulfill({status:404,contentType:'application/json',body:JSON.stringify({detail:`No mock for ${method} ${path}`})});
    return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
}
const near=(v,t,tol,label)=>assert.ok(Math.abs(v-t)<=tol,`${label}: ${v} not within ${tol} of ${t}`);
async function box(page,s){const b=await page.locator(s).boundingBox();assert.ok(b,`missing ${s}`);return b}
async function noOverflow(page,label){const d=await page.evaluate(()=>({s:document.documentElement.scrollWidth,c:document.documentElement.clientWidth}));assert.ok(d.s<=d.c+2,`${label}: ${d.s}>${d.c}`)}

const browser=await chromium.launch({headless:true});
try{
  const desktop=await browser.newPage({viewport:{width:1536,height:1024}});await mockApi(desktop);await desktop.goto(`${base}/iphone/agents.html`,{waitUntil:'networkidle'});
  await desktop.getByRole('heading',{name:'Agents'}).waitFor();
  const codingCard=desktop.locator('.aw-agent-card[data-agent-id="agent-coding"]');await codingCard.waitFor();
  assert.equal(await desktop.locator('[data-kpi="total_agents"]').first().textContent(),String(templates.length));assert.equal(await desktop.locator('[data-kpi="success_rate"]').textContent(),'94.7%');
  const sidebar=await box(desktop,'.aw-sidebar'),topbar=await box(desktop,'.aw-topbar');near(sidebar.width,196,2,'sidebar width');near(topbar.height,50,2,'topbar height');
  const cards=desktop.locator('.aw-agent-card');assert.ok(await cards.count()>=8,'dense agent grid expected');
  const c0=await cards.nth(0).boundingBox(),c1=await cards.nth(1).boundingBox(),c3=await cards.nth(3).boundingBox(),c4=await cards.nth(4).boundingBox();near(c0.y,c1.y,2,'row alignment');near(c0.y,c3.y,2,'four-column alignment');assert.ok(c4.y>c0.y+80,'fifth card should wrap');assert.ok(c1.x-c0.x>250,'reference card proportions expected');
  const detailBox=await box(desktop,'#agentDetail');assert.ok(detailBox.y>c4.y,'detail must sit below catalog');
  await desktop.locator('[data-detail-action="chat"]').click();await desktop.getByRole('button',{name:'＋ New Chat'}).click();await desktop.locator('#agentChatInput').fill('Check the failing tests');await desktop.locator('#agentChatForm button[type="submit"]').click();await desktop.getByText('Tool execution remains governed by Vishnu.').waitFor();
  await desktop.locator('#agentChatInput').fill('Implement the verified fix as canonical Project Work');await desktop.locator('[data-create-work]').click();await desktop.getByText('Canonical Project Work created for this request.').waitFor();
  assert.ok(await desktop.locator('.aw-side-stack').isVisible());assert.ok(await desktop.locator('.aw-dashboard-lower').isVisible());
  await desktop.locator('[data-detail-tab="versions"]').click();await desktop.getByText('Version history, performance and deployment.').waitFor();await noOverflow(desktop,'desktop');
  if(screenshotDir)await desktop.screenshot({path:`${screenshotDir}/agents-desktop.png`,fullPage:true});

  const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});await mockApi(mobile);await mobile.goto(`${base}/iphone/agents.html`,{waitUntil:'networkidle'});await mobile.getByRole('heading',{name:'Agents'}).waitFor();
  await mobile.locator('#menuButton').click();assert.equal(await mobile.evaluate(()=>document.body.classList.contains('sidebar-open')),true);await mobile.keyboard.press('Escape');
  assert.equal(await mobile.locator('.aw-agent-list').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),1);
  const mobileCoding=mobile.locator('.aw-agent-card[data-agent-id="agent-coding"]');await mobileCoding.click();await mobile.locator('[data-detail-tab="instances"]').click();await mobile.getByText('Runtime instances').waitFor();await noOverflow(mobile,'mobile');
  if(screenshotDir)await mobile.screenshot({path:`${screenshotDir}/agents-mobile.png`,fullPage:true});
} finally {await browser.close()}
console.log('Agent Workforce reference-parity browser qualification passed');

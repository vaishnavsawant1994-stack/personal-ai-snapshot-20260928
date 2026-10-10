import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const base = process.env.PWA_PREVIEW_URL || 'http://127.0.0.1:4173';
const screenshotDir = process.env.AGENT_WORKFORCE_SCREENSHOT_DIR || '';
if (screenshotDir) fs.mkdirSync(screenshotDir, { recursive: true });

const templates = [
  {
    id:'agent-coding',slug:'coding',name:'Coding Agent',role:'coding',description:'Software development and repository work',system_owned:true,
    preferred_version:{id:'ver-coding-1',template_id:'agent-coding',version:'1.0',state:'preferred',capabilities:['development','git','testing','code_review'],tools:['github','files'],memory_policy:'project_only'},
    version_count:1,instance_count:2,active_instance_count:1,
  },
  {
    id:'agent-research',slug:'research',name:'Research Agent',role:'research',description:'Research and source analysis',system_owned:true,
    preferred_version:{id:'ver-research-1',template_id:'agent-research',version:'1.0',state:'preferred',capabilities:['web_research','analysis','sources'],tools:[],memory_policy:'project_only'},
    version_count:1,instance_count:1,active_instance_count:0,
  },
  {
    id:'agent-custom',slug:'frontend-specialist',name:'Frontend Specialist',role:'design',description:'Custom UI implementation specialist',system_owned:false,
    preferred_version:{id:'ver-custom-1',template_id:'agent-custom',version:'1.0',state:'candidate',capabilities:['ui_ux','react'],tools:[],memory_policy:'project_only'},
    version_count:1,instance_count:0,active_instance_count:0,
  },
];

const projects = [
  {id:'project-a',name:'Vishnu',goal:'Ship Vishnu',description:'Primary Project',status:'active'},
  {id:'project-b',name:'The Perspective',goal:'Ship publication',description:'Publication Project',status:'active'},
];

const detail = {
  ...templates[0],
  versions:[templates[0].preferred_version],
  instances:[
    {id:'worker-1',template_id:'agent-coding',version_id:'ver-coding-1',project_id:'project-a',state:'working',current_work_order_id:'work-1',model_provider:null,model_id:null},
    {id:'worker-2',template_id:'agent-coding',version_id:'ver-coding-1',project_id:'project-b',state:'idle',current_work_order_id:null,model_provider:null,model_id:null},
  ],
  observations:[{id:'obs-1',kind:'verification_success',summary:'Regression suite passed.',score:1,project_id:'project-a',created_at:'2026-10-10T10:00:00Z'}],
  conversations:[],
};

async function mockApi(page){
  await page.route('**/iphone/api/projects*', route => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({projects})}));
  await page.route('**/iphone/api/agents**', async route => {
    const req=route.request();
    const url=new URL(req.url());
    const path=url.pathname;
    let body={};
    if(path==='/iphone/api/agents/summary') body={total_agents:3,total_instances:3,active_instances:1,working_now:1,idle:2,projects_using_agents:2,running_tasks:1,success_rate:100};
    else if(path==='/iphone/api/agents' && req.method()==='GET') body={agents:templates};
    else if(path==='/iphone/api/agents/agent-coding' && req.method()==='GET') body=detail;
    else if(path==='/iphone/api/agents/agent-research' && req.method()==='GET') body={...templates[1],versions:[templates[1].preferred_version],instances:[],observations:[],conversations:[]};
    else if(path==='/iphone/api/agents/agent-custom' && req.method()==='GET') body={...templates[2],versions:[templates[2].preferred_version],instances:[],observations:[],conversations:[]};
    else if(path==='/iphone/api/agents/agent-coding/conversations' && req.method()==='GET') body={conversations:[]};
    else if(path==='/iphone/api/agents/agent-coding/conversations' && req.method()==='POST') body={conversation:{id:'chat-1',template_id:'agent-coding',version_id:'ver-coding-1',instance_id:'worker-1',project_id:'project-a',title:'Coding Agent · Vishnu',state:'active',created_at:'2026-10-10T10:00:00Z',updated_at:'2026-10-10T10:00:00Z'}};
    else if(path==='/iphone/api/agents/conversations/chat-1' && req.method()==='GET') body={id:'chat-1',template_id:'agent-coding',version_id:'ver-coding-1',instance_id:'worker-1',project_id:'project-a',title:'Coding Agent · Vishnu',state:'active',messages:[]};
    else if(path==='/iphone/api/agents/conversations/chat-1/messages' && req.method()==='POST') body={conversation:{id:'chat-1',project_id:'project-a'},user_message:{role:'user',content:'Check the failing tests',created_at:'2026-10-10T10:01:00Z'},assistant_message:{role:'assistant',content:'I can inspect the Project-scoped test context. Tool execution remains governed by Vishnu.',provider:'test',model_id:'test-model',created_at:'2026-10-10T10:01:01Z'},usage:{total_tokens:10},model_output_authority:false,tool_execution_authority:false,completion_authority:false};
    else return route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({detail:`No mock for ${req.method()} ${path}`})});
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  });
}

async function assertNoHorizontalOverflow(page,label){
  const dims=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth}));
  assert.ok(dims.scrollWidth<=dims.clientWidth+2,`${label} has horizontal overflow: ${dims.scrollWidth} > ${dims.clientWidth}`);
}

const browser=await chromium.launch({headless:true});
try{
  const desktop=await browser.newPage({viewport:{width:1440,height:900}});
  await mockApi(desktop);
  await desktop.goto(`${base}/iphone/agents.html`,{waitUntil:'networkidle'});
  await desktop.getByRole('heading',{name:'Agents'}).waitFor();
  await desktop.getByText('Coding Agent',{exact:true}).first().waitFor();
  assert.equal(await desktop.locator('[data-kpi="total_agents"]').textContent(),'3');
  assert.equal(await desktop.locator('[data-kpi="success_rate"]').textContent(),'100%');
  await desktop.getByRole('button',{name:'Chat',exact:true}).click();
  await desktop.getByRole('button',{name:'＋ New'}).click();
  await desktop.locator('#agentChatInput').fill('Check the failing tests');
  await desktop.locator('#agentChatForm button[type="submit"]').click();
  await desktop.getByText('Tool execution remains governed by Vishnu.').waitFor();
  await desktop.getByRole('button',{name:'Versions'}).click();
  await desktop.getByText('Historical versions remain attributable to their work.').waitFor();
  await assertNoHorizontalOverflow(desktop,'desktop workforce');
  if(screenshotDir)await desktop.screenshot({path:`${screenshotDir}/agents-desktop.png`,fullPage:true});

  const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
  await mockApi(mobile);
  await mobile.goto(`${base}/iphone/agents.html`,{waitUntil:'networkidle'});
  await mobile.getByRole('heading',{name:'Agents'}).waitFor();
  await mobile.locator('#menuButton').click();
  assert.equal(await mobile.evaluate(()=>document.body.classList.contains('sidebar-open')),true);
  await mobile.keyboard.press('Escape');
  await mobile.getByText('Coding Agent',{exact:true}).first().click();
  await mobile.getByRole('button',{name:'Instances'}).click();
  await mobile.getByText('Runtime instances').waitFor();
  await assertNoHorizontalOverflow(mobile,'mobile workforce');
  if(screenshotDir)await mobile.screenshot({path:`${screenshotDir}/agents-mobile.png`,fullPage:true});
} finally {
  await browser.close();
}
console.log('Agent Workforce browser qualification passed');

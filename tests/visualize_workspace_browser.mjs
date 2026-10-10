import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';

const baseURL = process.env.VISUALIZE_BASE_URL || 'http://127.0.0.1:4173/iphone/';
const outputDir = process.env.VISUALIZE_SCREENSHOT_DIR || 'artifacts/visualize';
await mkdir(outputDir, { recursive: true });

const graph = {
  type: 'architecture',
  title: 'Personal AI Architecture',
  nodes: [
    {id:'user',label:'User',category:'external',description:'Owner of the Vishnu system.',status:'active',evidence_level:'user_supplied',evidence:[],metadata:{}},
    {id:'mobile',label:'Mobile App',category:'frontend',description:'Primary mobile Vishnu surface.',status:'active',evidence_level:'strong',evidence:[{path:'pwa/index.html',line_start:1,line_end:40}],metadata:{}},
    {id:'web',label:'Web App',category:'frontend',description:'Responsive browser surface.',status:'active',evidence_level:'strong',evidence:[{path:'pwa/index.html',line_start:1,line_end:40}],metadata:{}},
    {id:'gateway',label:'API Gateway',category:'backend',description:'Authenticated request entry point.',status:'active',evidence_level:'strong',evidence:[{path:'server/cloud_app.py',line_start:1,line_end:120}],metadata:{}},
    {id:'auth',label:'Authentication Service',category:'security',description:'Trusted-device and owner authorization.',status:'active',evidence_level:'verified',evidence:[{path:'security/owner_access.py',line_start:1,line_end:140}],metadata:{confidence:.96}},
    {id:'agent',label:'Agent Runtime',category:'agent',description:'Plans and executes governed Vishnu work.',status:'active',evidence_level:'verified',evidence:[{path:'agent/effect_runtime.py',line_start:1,line_end:180}],metadata:{confidence:.94}},
    {id:'memory',label:'Memory Engine',category:'database',description:'Stores and retrieves durable context for user, projects and agents.',status:'active',evidence_level:'verified',evidence:[{path:'memory/engine.py',line_start:28,line_end:164},{path:'memory/store.py',line_start:41,line_end:119},{path:'tests/test_memory.py',line_start:12,line_end:88}],metadata:{confidence:.92}},
    {id:'tools',label:'Tool Runner',category:'tool',description:'Executes governed tools with policy checks.',status:'active',evidence_level:'strong',evidence:[{path:'tools/registry.py',line_start:1,line_end:180}],metadata:{confidence:.88}},
    {id:'knowledge',label:'Knowledge',category:'database',description:'Indexed owner knowledge and evidence.',status:'active',evidence_level:'strong',evidence:[{path:'knowledge/store.py',line_start:1,line_end:160}],metadata:{confidence:.86}},
    {id:'database',label:'Database',category:'database',description:'Durable application state.',status:'active',evidence_level:'strong',evidence:[{path:'core/data.py',line_start:1,line_end:100}],metadata:{confidence:.84}},
    {id:'external',label:'External APIs',category:'external',description:'Connected external services.',status:'active',evidence_level:'inferred',evidence:[],metadata:{}},
    {id:'storage',label:'File Storage',category:'cloud',description:'Project files and generated artifacts.',status:'active',evidence_level:'strong',evidence:[{path:'knowledge/store.py',line_start:1,line_end:160}],metadata:{confidence:.81}},
  ],
  edges: [
    {id:'e1',source:'user',target:'mobile',kind:'uses'},{id:'e2',source:'user',target:'web',kind:'uses'},
    {id:'e3',source:'mobile',target:'gateway',kind:'request'},{id:'e4',source:'web',target:'gateway',kind:'request'},
    {id:'e5',source:'gateway',target:'auth',kind:'authorize'},{id:'e6',source:'gateway',target:'agent',kind:'execute'},
    {id:'e7',source:'agent',target:'memory',kind:'context'},{id:'e8',source:'agent',target:'tools',kind:'tool_call'},
    {id:'e9',source:'memory',target:'knowledge',kind:'retrieve'},{id:'e10',source:'memory',target:'database',kind:'persist'},
    {id:'e11',source:'tools',target:'external',kind:'call'},{id:'e12',source:'tools',target:'storage',kind:'artifact'},
    {id:'e13',source:'storage',target:'memory',kind:'source'},{id:'e14',source:'auth',target:'agent',kind:'allow'},
  ],
  views: [], metadata: {},
};

function svgFor(g) {
  const positions = {
    user:[410,20],mobile:[250,110],web:[570,110],gateway:[410,200],auth:[160,300],agent:[410,300],memory:[660,300],tools:[410,405],knowledge:[650,420],database:[790,390],external:[170,500],storage:[600,520],
  };
  const widths = {user:120,mobile:150,web:150,gateway:180,auth:160,agent:170,memory:180,tools:150,knowledge:130,database:120,external:150,storage:150};
  const lines = g.edges.map(edge => {
    const a=positions[edge.source],b=positions[edge.target]; if(!a||!b)return '';
    const aw=widths[edge.source]||140,bw=widths[edge.target]||140;
    return `<path data-edge-id="${edge.id}" d="M${a[0]+aw/2} ${a[1]+28} L${b[0]+bw/2} ${b[1]+28}" fill="none" stroke="#536987" stroke-width="2" marker-end="url(#arrow)"/>`;
  }).join('');
  const colors={frontend:'#21a9ff',backend:'#2bdcaa',security:'#ef4f92',agent:'#f09a3d',database:'#7656ff',tool:'#158be5',external:'#21b9d7',cloud:'#37d18b'};
  const nodes=g.nodes.map(node=>{const p=positions[node.id]||[50,50],w=widths[node.id]||140,c=colors[node.category]||'#3aa4ff';return `<g class="vv-node" data-node-id="${node.id}" tabindex="0" transform="translate(${p[0]} ${p[1]})"><rect width="${w}" height="56" rx="8" fill="#071626" stroke="${c}" stroke-width="2"/><text x="${w/2}" y="33" text-anchor="middle" fill="#f4f8ff" font-size="14" font-family="-apple-system,Inter,sans-serif">${node.label}</text></g>`;}).join('');
  return `<svg class="vishnu-visual-svg" viewBox="80 0 900 620" role="img" aria-label="${g.title}"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8z" fill="#536987"/></marker></defs>${lines}${nodes}</svg>`;
}

const visual = {id:'visual-1',title:'Personal AI Architecture',type:'architecture',mode:'live',source_kind:'project',source_ref:'project-1',project_id:'project-1',conversation_id:null,node_count:graph.nodes.length,edge_count:graph.edges.length,graph,svg:svgFor(graph),created_at:'2026-10-10T14:00:00Z',updated_at:'2026-10-10T15:00:00Z'};
const visual2 = {...visual,id:'visual-2',title:'Agent Execution Flow',type:'workflow',mode:'manual',source_kind:'description',node_count:8,edge_count:9};
const visual3 = {...visual,id:'visual-3',title:'Knowledge Map',type:'project_map',mode:'manual',source_kind:'files',node_count:11,edge_count:14};
const visual4 = {...visual,id:'visual-4',title:'Memory System',type:'architecture',mode:'manual',source_kind:'description',node_count:9,edge_count:11};
const visuals=[visual,visual2,visual3,visual4];

async function routeAPI(page) {
  await page.route('**/iphone/api/**', async route => {
    const req=route.request(); const url=new URL(req.url()); const path=url.pathname; const method=req.method();
    const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/iphone/api/visualizations'&&method==='GET') return json({visualizations:visuals});
    if(path==='/iphone/api/visualizations/compare'&&method==='POST') return json({summary:{added:3,removed:1,changed:2},added_nodes:['storage'],removed_nodes:[],changed_nodes:['agent']});
    if(path==='/iphone/api/visualizations/visual-1'&&method==='GET') return json({visualization:visual});
    if(path==='/iphone/api/visualizations/visual-2'&&method==='GET') return json({visualization:visual2});
    if(path==='/iphone/api/visualizations/visual-3'&&method==='GET') return json({visualization:visual3});
    if(path==='/iphone/api/visualizations/visual-4'&&method==='GET') return json({visualization:visual4});
    if(path.endsWith('/reach')&&method==='POST') {const input=JSON.parse(req.postData()||'{}');return json({origin:input.origin,direction:input.direction,node_ids:input.direction==='upstream'?['memory','agent','gateway']:['memory','knowledge','database','storage'],edge_ids:['e7','e9','e10'],max_hops:2});}
    if(path.endsWith('/path')&&method==='POST') return json({found:true,node_ids:['memory','knowledge','database'],edge_ids:['e9','e10'],hops:2});
    if(path.endsWith('/revisions')&&method==='GET') return json({revisions:[{revision:3,reason:'repository refresh',created_at:'2026-10-10T15:00:00Z'},{revision:2,reason:'owner edit',created_at:'2026-10-10T14:30:00Z'},{revision:1,reason:'created',created_at:'2026-10-10T14:00:00Z'}]});
    if(path.endsWith('/refresh')&&method==='POST') return json({visualization:visual});
    if(path.endsWith('/artifact')&&method==='GET') return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><title>Vishnu Visualize artifact</title>'});
    if(path==='/iphone/api/projects'&&method==='GET') return json({projects:[{id:'project-1',name:'Personal AI',status:'active'},{id:'project-2',name:'Visual Architecture Agent',status:'active'}]});
    if(path==='/iphone/api/conversations'&&method==='GET') return json({conversations:[{id:'c1',title:'Vishnu architecture planning',preview:'Plan the system architecture'},{id:'c2',title:'Agent workflow',preview:'Map agent execution'}]});
    if(path==='/iphone/api/status') return json({model:{state:'ready'},conversations:[],conversation:null,memory_count:3,active_qualification:false});
    if(path==='/iphone/api/system/status') return json({model:{state:'ready',providers:[]},integrations:[],emergency_stop:false});
    if(path==='/iphone/api/preferences') return json({});
    if(path==='/iphone/api/profile') return json({profile:{display_name:'Vishnu',email:'owner@example.test',email_verified:true}});
    if(method==='GET') return json({items:[],projects:[],conversations:[],documents:[],activities:[],runs:[],tools:[],connectors:[],settings:{}});
    return json({ok:true});
  });
}

async function bootPage(browser,{width,height,isMobile=false}) {
  const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:isMobile?2:1,isMobile,hasTouch:isMobile,serviceWorkers:'block'});
  const page=await context.newPage();
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  await routeAPI(page);
  await page.goto(baseURL,{waitUntil:'domcontentloaded'});
  await page.waitForTimeout(350);
  assert.ok(await page.locator('.sidebar-main-nav').count(), 'Canonical Vishnu shell must expose .sidebar-main-nav for Visualize navigation integration');
  await page.addStyleTag({path:'pwa/visualize-workspace.css'});
  await page.addScriptTag({path:'pwa/visualize-workspace.js'});
  await page.waitForFunction(()=>Boolean(window.__VISHNU_VISUALIZE__));
  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.openWorkspace());
  await page.waitForSelector('#visualizeWorkspace:not(.vz-hidden)');
  await page.waitForFunction(()=>document.querySelectorAll('.vz-recent-card').length>=4);
  return {context,page,errors};
}

const browser=await chromium.launch({headless:true});
try {
  const desktop=await bootPage(browser,{width:1440,height:900});
  const page=desktop.page;
  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.openNav());
  await page.waitForSelector('#vzNavDrawer.open');
  await page.locator('#vzNavDrawer').screenshot({path:`${outputDir}/visualize-navigation-desktop.png`});
  await page.locator('#vzNavBackdrop').click({position:{x:600,y:300}}).catch(()=>page.evaluate(()=>document.querySelector('#vzNavBackdrop')?.click()));
  await page.screenshot({path:`${outputDir}/visualize-home-desktop.png`,fullPage:false});
  assert.equal(await page.locator('.vz-source-card').count(),5,'Desktop home must expose all five creation sources');
  const gridColumns=await page.locator('.vz-create-grid').evaluate(node=>getComputedStyle(node).gridTemplateColumns.split(' ').length);
  assert.equal(gridColumns,6,'Desktop create board uses a six-track 3+2 composition');

  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.openGallery());
  await page.waitForSelector('.vz-gallery-page');
  assert.equal(await page.locator('.vz-gallery-card').count(),9,'Gallery shows the nine approved templates');
  await page.getByRole('button',{name:'Workflows'}).click();
  assert.equal(await page.locator('.vz-gallery-card').count(),2,'Gallery category filters are functional');
  await page.getByRole('button',{name:'All'}).click();
  await page.screenshot({path:`${outputDir}/visualize-gallery-desktop.png`,fullPage:false});

  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.openViewer('visual-1'));
  await page.waitForSelector('#vzViewer');
  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.selectNode('memory'));
  await page.waitForSelector('.vz-node-selected');
  assert.equal(await page.locator('[data-vz-layer]').count(),6,'Viewer exposes six layer controls');
  assert.equal(await page.locator('[data-vz-view]').count(),8,'Viewer exposes eight reference views');
  const services=page.locator('[data-vz-layer="services"]'); await services.uncheck();
  assert.equal(await services.isChecked(),false,'Layer toggles are interactive'); await services.check();
  await page.screenshot({path:`${outputDir}/visualize-viewer-desktop.png`,fullPage:false});

  await page.evaluate(()=>window.__VISHNU_VISUALIZE__.openContextual());
  await page.waitForSelector('#vzContextPanel');
  assert.equal(await page.locator('[data-vz-context-tab]').count(),4,'Contextual Ask panel exposes Chat, Sources, Paths and Evidence');
  await page.getByRole('button',{name:'Sources'}).click();
  assert.ok(await page.locator('.vz-source-ref').count()>=3,'Sources tab renders authored node evidence');
  await page.getByRole('button',{name:'Paths'}).click();
  await page.getByRole('button',{name:'Show upstream'}).click();
  await page.waitForSelector('.vz-reach-result');
  await page.getByRole('button',{name:'Chat'}).click();
  await page.screenshot({path:`${outputDir}/visualize-contextual-ask-desktop.png`,fullPage:false});
  assert.deepEqual(desktop.errors,[],'Desktop Visualize emitted no page errors');
  await desktop.context.close();

  const mobile=await bootPage(browser,{width:390,height:844,isMobile:true});
  const mp=mobile.page;
  const overflow=await mp.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  assert.ok(overflow<=1,`Mobile home must not create page-level horizontal overflow (${overflow}px)`);
  assert.equal(await mp.locator('.vz-source-card').count(),5,'Mobile home preserves all five creation sources');
  await mp.screenshot({path:`${outputDir}/visualize-home-mobile.png`,fullPage:false});

  await mp.evaluate(()=>window.__VISHNU_VISUALIZE__.openViewer('visual-1'));
  await mp.waitForSelector('#vzViewer');
  await mp.evaluate(()=>window.__VISHNU_VISUALIZE__.selectNode('memory'));
  await mp.waitForSelector('#vzMobileNodeCard:not(.vz-hidden)');
  await mp.screenshot({path:`${outputDir}/visualize-viewer-mobile.png`,fullPage:false});
  await mp.evaluate(()=>window.__VISHNU_VISUALIZE__.openMobileDetails());
  await mp.waitForSelector('.vz-mobile-details');
  assert.equal(await mp.locator('[data-vz-mobile-tab]').count(),4,'Mobile node details exposes Details, Sources, Relations and Actions');
  await mp.screenshot({path:`${outputDir}/visualize-node-details-mobile.png`,fullPage:false});
  const mobileOverflow=await mp.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  assert.ok(mobileOverflow<=1,`Mobile viewer/details must not create page-level horizontal overflow (${mobileOverflow}px)`);
  assert.deepEqual(mobile.errors,[],'Mobile Visualize emitted no page errors');
  await mobile.context.close();

  console.log('Visualize authoritative eight-screen browser qualification passed');
} finally {
  await browser.close();
}

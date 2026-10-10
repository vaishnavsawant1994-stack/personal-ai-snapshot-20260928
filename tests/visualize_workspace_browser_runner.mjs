import { readFile, writeFile, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const sourceUrl=new URL('./visualize_workspace_browser.mjs',import.meta.url);
const generatedUrl=new URL('./.visualize_workspace_browser.generated.mjs',import.meta.url);
let source=await readFile(sourceUrl,'utf8');

const injectBefore=`  await page.addStyleTag({path:'pwa/visualize-workspace.css'});\n  await page.addScriptTag({path:'pwa/visualize-workspace.js'});`;
const injectAfter=`  await page.addStyleTag({path:'pwa/visualize-workspace.css'});\n  await page.addStyleTag({path:'pwa/visualize-sources.css'});\n  await page.addScriptTag({path:'pwa/visualize-workspace.js'});\n  await page.addScriptTag({path:'pwa/visualize-sources.js'});`;
if(!source.includes(injectBefore))throw new Error('Visualize bundle injection contract changed; update runner explicitly.');
source=source.replace(injectBefore,injectAfter);

const closeBefore=`  await page.locator('#vzNavBackdrop').click({position:{x:600,y:300}}).catch(()=>page.evaluate(()=>document.querySelector('#vzNavBackdrop')?.click()));`;
const closeAfter=`  await page.evaluate(()=>document.querySelector('#vzNavBackdrop')?.click());`;
if(!source.includes(closeBefore))throw new Error('Visualize navigation close contract changed; update runner explicitly.');
source=source.replace(closeBefore,closeAfter);

const galleryBefore=`  await page.getByRole('button',{name:'Workflows'}).click();\n  assert.equal(await page.locator('.vz-gallery-card').count(),2,'Gallery category filters are functional');\n  await page.getByRole('button',{name:'All'}).click();`;
const galleryAfter=`  await page.locator('[data-vz-gallery-tab="Workflows"]').click();\n  assert.equal(await page.locator('.vz-gallery-card').count(),2,'Gallery category filters are functional');\n  await page.locator('[data-vz-gallery-tab="All"]').click();`;
if(!source.includes(galleryBefore))throw new Error('Visualize Gallery selector contract changed; update runner explicitly.');
source=source.replace(galleryBefore,galleryAfter);

const pathBefore=`  await page.getByRole('button',{name:'Sources'}).click();\n  assert.ok(await page.locator('.vz-source-ref').count()>=3,'Sources tab renders authored node evidence');\n  await page.getByRole('button',{name:'Paths'}).click();\n  await page.getByRole('button',{name:'Show upstream'}).click();\n  await page.waitForSelector('.vz-reach-result');\n  await page.getByRole('button',{name:'Chat'}).click();`;
const pathAfter=`  await page.locator('#vzContextPanel [data-vz-context-tab="sources"]').click();\n  assert.ok(await page.locator('#vzContextPanel .vz-source-ref').count()>=3,'Sources tab renders authored node evidence');\n  await page.locator('#vzContextPanel [data-vz-context-tab="paths"]').click();\n  await page.locator('#vzContextPanel [data-vz-context-reach="upstream"]').click();\n  await page.waitForSelector('#vzContextPanel .vz-reach-result');\n  await page.waitForSelector('#vzContextPanel [data-vz-path-form]');\n  await page.locator('#vzContextPanel [data-vz-path-target]').selectOption('database');\n  await page.locator('#vzContextPanel [data-vz-path-form] button[type="submit"]').click();\n  await page.waitForSelector('#vzContextPanel .vz-path-result');\n  assert.match(await page.locator('#vzContextPanel .vz-path-result').innerText(),/Memory Engine.*Knowledge.*Database/s,'Paths tab renders the authored path returned by the API');\n  await page.locator('#vzContextPanel [data-vz-context-tab="chat"]').click();`;
if(!source.includes(pathBefore))throw new Error('Visualize contextual assertion contract changed; update runner explicitly.');
source=source.replace(pathBefore,pathAfter);

await writeFile(generatedUrl,source,'utf8');
try{await import(generatedUrl.href+'?run='+Date.now());}
finally{await unlink(fileURLToPath(generatedUrl)).catch(()=>{});}

import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const root = new URL('../', import.meta.url);
const read = path => readFile(new URL(path, root));
const serverState = { projects: [], conversations: [], turns: [], nextId: 1 };
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const send = (status, body, type = 'application/json') => { res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' }); res.end(type === 'application/json' ? JSON.stringify(body) : body); };
  if (req.method === 'GET' && url.pathname === '/iphone/') return send(200, await read('pwa/index.html'), 'text/html; charset=utf-8');
  if (req.method === 'GET' && url.pathname === '/iphone/projects-workspace.js') return send(200, await read('pwa/projects-workspace.js'), 'application/javascript');
  if (req.method === 'GET' && url.pathname === '/iphone/projects-workspace.css') return send(200, await read('pwa/projects-workspace.css'), 'text/css');
  if (req.method === 'GET' && url.pathname === '/iphone/v1-runtime.js') return send(200, await read('pwa/v1-runtime.js'), 'application/javascript');
  if (req.method === 'GET' && url.pathname === '/iphone/manifest.webmanifest') return send(200, '{}', 'application/manifest+json');
  if (req.method === 'GET' && url.pathname === '/iphone/sw.js') return send(200, await read('pwa/sw.js'), 'application/javascript');
  if (url.pathname.startsWith('/iphone/api/')) {
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : {};
    const path = url.pathname.slice('/iphone/api'.length);
    if (path === '/status') return send(200, { model: { state: 'ready' }, conversations: [], conversation: null, memory_count: 0, active_qualification: false });
    if (path === '/preferences') return send(200, { continuous_voice: true, voice_rate: 1, quiet_hours: true });
    if (path === '/everyday/active') return send(200, { items: [] });
    if (path === '/conversations') return send(200, { conversations: serverState.conversations });
    if (path === '/projects' && req.method === 'GET') return send(200, { projects: serverState.projects });
    if (path === '/projects' && req.method === 'POST') {
      const project = { id: `project-${serverState.nextId++}`, ...body, status: 'active', conversation_id: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), task_count: 0, done_count: 0, milestone_count: 0, tasks: [], milestones: [], files: [], threads: [], activity: [] };
      serverState.projects.unshift(project); project.activity.push({ id: 'event-create', actor: 'owner', action: 'created project', target_type: 'project', detail: project.name, created_at: project.created_at });
      return send(201, { project });
    }
    const projectPath = path.match(/^\/projects\/([^/]+)(.*)$/);
    if (projectPath) {
      const project = serverState.projects.find(item => item.id === decodeURIComponent(projectPath[1]));
      if (!project) return send(404, { detail: 'Project not found' });
      const tail = projectPath[2];
      const result = () => { project.task_count = project.tasks.length; project.done_count = project.tasks.filter(item => item.status === 'done').length; project.milestone_count = project.milestones.length; project.updated_at = new Date().toISOString(); return { project }; };
      if (!tail && req.method === 'GET') return send(200, result());
      if (tail === '/tasks' && req.method === 'POST') { project.tasks.push({ id: `task-${serverState.nextId++}`, project_id: project.id, status: 'planned', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...body }); project.activity.push({ id: `event-${serverState.nextId++}`, actor: 'owner', action: 'created task', target_type: 'task', detail: body.title, created_at: new Date().toISOString() }); return send(201, result()); }
      const taskPath = tail.match(/^\/tasks\/([^/]+)$/);
      if (taskPath && req.method === 'PATCH') { const task = project.tasks.find(item => item.id === decodeURIComponent(taskPath[1])); if (!task) return send(404, { detail: 'Task not found' }); Object.assign(task, body); task.updated_at = new Date().toISOString(); return send(200, result()); }
      if (tail === '/milestones' && req.method === 'POST') { project.milestones.push({ id: `milestone-${serverState.nextId++}`, status: 'planned', ...body }); return send(201, result()); }
      if (tail === '/conversation' && req.method === 'POST') { project.conversation_id ||= `conversation-${serverState.nextId++}`; return send(201, { conversation_id: project.conversation_id, project }); }
      if (tail === '/activity' && req.method === 'POST') { project.activity.push({ id: `event-${serverState.nextId++}`, actor: 'owner', action: 'asked Vishnu', target_type: 'conversation', detail: body.content, created_at: new Date().toISOString() }); return send(201, result()); }
      if (tail === '/discussions' && req.method === 'POST') { project.threads.push({ id: `thread-${serverState.nextId++}`, title: body.title, status: 'open', updated_at: new Date().toISOString(), replies: [{ author: 'owner', content: body.content }] }); return send(201, result()); }
      if (tail === '/files/upload' && req.method === 'POST') { const file = { id: `file-${serverState.nextId++}`, title: body.filename, kind: 'upload', created_at: new Date().toISOString(), content: Buffer.from(body.content_base64, 'base64') }; project.files.push(file); return send(201, result()); }
      const downloadPath = tail.match(/^\/files\/([^/]+)\/download$/);
      if (downloadPath && req.method === 'GET') { const file = project.files.find(item => item.id === decodeURIComponent(downloadPath[1])); return file ? send(200, file.content, 'text/markdown') : send(404, { detail: 'File not found' }); }
    }
    if (path.startsWith('/conversations/') && req.method === 'GET') {
      const id = decodeURIComponent(path.split('/')[2]); const conversation = serverState.conversations.find(item => item.conversation.id === id);
      return send(200, conversation || { conversation: { id }, events: [] });
    }
    if (path === '/voice/turn' && req.method === 'POST') { serverState.turns.push(body); const answer = `Vishnu plan for: ${body.transcript.slice(body.transcript.lastIndexOf('Owner request:') + 14).trim()}`; const id = body.conversation_id; let conversation = serverState.conversations.find(item => item.conversation.id === id); if (!conversation) { conversation = { conversation: { id, title: 'Project conversation' }, events: [] }; serverState.conversations.push(conversation); } conversation.events.push({ kind: 'user_message', payload: { text: body.transcript } }, { kind: 'assistant_message', payload: { text: answer } }); return send(200, { status: 'completed', conversation_id: id, reply: answer }); }
    if (path === '/approvals-center/pending' || path === '/workflows') return send(200, { approvals: [], workflows: [], runs: [] });
    return send(200, {});
  }
  return send(404, 'not found', 'text/plain');
});

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const address = server.address();
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of [{ width: 390, height: 844, isMobile: true }, { width: 1440, height: 1000, isMobile: false }]) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: viewport.isMobile ? 2 : 1, isMobile: viewport.isMobile, hasTouch: viewport.isMobile, serviceWorkers: 'block' });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${address.port}/iphone/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.body.classList.contains('home-landing'));
    await page.locator('#historyButton').click();
    await page.locator('[data-app-module="projects"]').click();
    await page.getByRole('heading', { name: 'Your project work starts here' }).waitFor();
    await page.getByRole('button', { name: 'Create your first project' }).click();
    const dialog = page.locator('dialog.project-dialog');
    await dialog.locator('input[name="name"]').fill(`Responsive workspace ${viewport.width}`);
    await dialog.locator('textarea[name="goal"]').fill('Ship the project workspace and verify owner-controlled data.');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await page.getByRole('heading', { name: `Responsive workspace ${viewport.width}` }).waitFor();
    await page.getByRole('button', { name: 'Add task' }).click();
    const taskDialog = page.locator('dialog.project-dialog');
    await taskDialog.locator('input[name="title"]').fill('Verify the responsive workspace');
    await taskDialog.getByRole('button', { name: 'Save' }).click();
    await page.getByRole('button', { name: 'Work plan' }).click();
    await page.getByText('Verify the responsive workspace').waitFor();
    await page.getByRole('button', { name: 'Ask Vishnu' }).first().click();
    await page.locator('#projectChatForm textarea').fill('Please make a safe implementation plan.');
    await page.locator('#projectChatForm button[type="submit"]').click();
    await page.getByText(/Vishnu plan for:/).waitFor();
    assert.equal(serverState.turns.at(-1).conversation_id, serverState.projects[0].conversation_id, 'Project chat must use its linked canonical conversation');
    await page.getByRole('button', { name: 'Files & sources' }).click();
    await page.locator('[data-project-action="upload-file"]').click();
    await page.locator('#projectFileInput').setInputFiles({ name: 'project-notes.md', mimeType: 'text/markdown', buffer: Buffer.from('Responsive acceptance criteria') });
    await page.getByText('project-notes.md').waitFor();
    await page.getByRole('button', { name: 'Activity' }).click();
    await page.getByText('asked Vishnu').waitFor();
    const overflow = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth, module: document.querySelector('#moduleBody').scrollWidth }));
    assert.ok(overflow.body <= overflow.viewport + 1, `Workspace must not cause page-width overflow: ${JSON.stringify(overflow)}`);
    assert.deepEqual(errors, [], `No browser exceptions at ${viewport.width}px: ${errors.join(' | ')}`);
    await page.close();
  }
  console.log('Projects workspace browser smoke passed at 390px and 1440px: create, task, project chat, file upload, activity, and no horizontal page overflow.');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}

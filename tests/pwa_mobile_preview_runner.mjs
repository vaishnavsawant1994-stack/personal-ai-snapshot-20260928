import { readFile, writeFile, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

// The browser suite owns Node-side API fixtures. Playwright's selectOption()
// waits for DOM input/change dispatch, but not for an async fetch started by a
// change listener. Run the canonical suite with one explicit network boundary
// so its existing server-fixture assertion observes the completed PATCH rather
// than racing it. The assertion and accepted value remain unchanged.
const sourceUrl = new URL('./pwa_mobile_preview.mjs', import.meta.url);
const generatedUrl = new URL('./.pwa_mobile_preview.generated.mjs', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
const before = `  await page.locator('[data-mx-retention]').selectOption('6_months');\n  assert.equal(ambientSettings.retention,'6_months','Ambient retention selection persists');`;
const after = `  const ambientRetentionSaved=page.waitForResponse(response=>response.url().includes('/iphone/api/memory/ambient/settings')&&response.request().method()==='PATCH'&&response.ok());\n  await page.locator('[data-mx-retention]').selectOption('6_months');\n  await ambientRetentionSaved;\n  assert.equal(ambientSettings.retention,'6_months','Ambient retention selection persists');`;

if (!source.includes(before)) {
  throw new Error('Canonical Ambient retention assertion changed; update the synchronization runner explicitly.');
}

await writeFile(generatedUrl, source.replace(before, after), 'utf8');
try {
  await import(generatedUrl.href + '?run=' + Date.now());
} finally {
  await unlink(fileURLToPath(generatedUrl)).catch(() => {});
}

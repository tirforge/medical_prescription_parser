import { test, expect } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

test('health is env-only, no key input in website', async ({ page, request }) => {
  // API key via env, not input box
  const html = fs.readFileSync('rx-prescription-app.html', 'utf8');
  expect(html.toLowerCase()).not.toContain('google_api_key');
  expect(html.toLowerCase()).not.toContain('type="password"');

  // file:// check for file picker
  const filePath = path.resolve('rx-prescription-app.html');
  await page.goto('file://' + filePath);
  await expect(page.getByRole('tab', { name: 'Prescription' })).toBeVisible({ timeout: 5000 });
  // no password input in website
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  // photo upload + capture + paste from clipboard present
  await expect(page.locator('#filePick')).toHaveCount(1);
  await expect(page.locator('#camPick')).toHaveCount(1);
  await expect(page.locator('#camBtn')).toBeVisible();
  await expect(page.locator('#pasteBtn')).toBeVisible();
  await expect(page.locator('#camPick')).toHaveAttribute('capture', 'environment');
});

test('api health + verify + parse (env key)', async ({ request }) => {
  const h = await request.get('http://127.0.0.1:8000/health');
  expect(h.ok()).toBeTruthy();
  const hj = await h.json();
  expect(hj.ok).toBeTruthy();
  expect(typeof hj.vision_ready).toBe('boolean');

  const v = await request.get('http://127.0.0.1:8000/verify?name=Dolo%20650');
  expect(v.ok()).toBeTruthy();
  const vj = await v.json();
  expect(vj.check.match).toContain('Dolo');

  const sample = 'accuracy_test/rx_00006.png';
  const buf = fs.readFileSync(sample);
  const r = await request.post('http://127.0.0.1:8000/parse', {
    multipart: { files: { name: 'rx_00006.png', mimeType: 'image/png', buffer: buf } }
  });
  // 503 if key not set is ok, but with env key should be 200
  if (r.status() === 503) {
    console.log('parse 503 (no key) — env not set in CI, skipping strict check');
    return;
  }
  expect(r.ok()).toBeTruthy();
  const j = await r.json();
  expect(j.result.patient_name).toBeTruthy();
});

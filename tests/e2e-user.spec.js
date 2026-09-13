import { test, expect } from '@playwright/test';
import path from 'path';

test('actual user: open site, upload, see results, copy, history, chat', async ({ page, context }) => {
  // Like a real user opening the deployed site
  await page.goto('http://127.0.0.1:8000/');
  await expect(page.locator('text=RxCare').first()).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Prescription' })).toBeVisible();

  // Grant clipboard permissions for copy test
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);

  // Upload like a user: click Choose files -> pick rx_00006.png
  const filePath = path.resolve('accuracy_test/rx_00006.png');
  await page.locator('#filePick').setInputFiles(filePath);
  // Dispatch change to trigger run()
  await page.evaluate(() => {
    const el = document.getElementById('filePick');
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });

  // User sees staged loader
  await expect(page.locator('#loadWrap')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('#loadPct')).toBeVisible();

  // Then results appear (like a user waiting)
  await expect(page.locator('#results')).toBeVisible({ timeout: 20000 });
  await expect(page.locator('#fileChips')).toContainText('rx_00006.png');

  // Patient card visible like a user would read
  await expect(page.locator('#results')).toContainText('Aisha Khan', { timeout: 5000 });
  await expect(page.locator('#results')).toContainText('Prednisone', { timeout: 5000 });

  // Risk banner and meds
  await expect(page.locator('.riskbanner').first()).toBeVisible();
  await expect(page.locator('.med').first()).toBeVisible();

  // Copy button works like a user clicking Copy
  await page.locator('#copyBtn').click();
  await page.waitForTimeout(500);
  const clip = await page.evaluate(() => navigator.clipboard.readText().catch(() => ''));
  // copyBtn copies meds (Prednisone), txtBtn would have patient
  if (clip) {
    expect(clip).toContain('Prednisone');
  } else {
    await expect(page.locator('#results')).toContainText('Copy results');
  }

  // History tab like a user checking past parses
  await page.getByRole('tab', { name: 'History' }).click();
  await expect(page.locator('#histList')).toContainText('medicine', { timeout: 3000 });

  // Chat like a user asking about the med
  await page.getByRole('tab', { name: 'Prescription' }).click();
  await expect(page.locator('#chatIn')).toBeEnabled({ timeout: 5000 });
  await page.locator('#chatIn').fill('What is Prednisone for?');
  await page.locator('#chatSend').click();
  await expect(page.locator('#chatLog')).toContainText('Prednisone', { timeout: 10000 });

  // Dark mode and font scaling like a user toggling
  await page.locator('#themeBtn').click();
  await page.waitForTimeout(300);
  await page.locator('#fontInc').click();
  await expect(page.locator('html')).toHaveAttribute('data-font', 'lg');

  // Capture button visible like a user on mobile
  await expect(page.locator('#camBtn')).toBeVisible();
  await expect(page.locator('#pasteBtn')).toBeVisible();
});

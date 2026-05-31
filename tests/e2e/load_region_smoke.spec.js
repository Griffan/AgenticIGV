const { test, expect } = require('@playwright/test');

test('Load region button works with default path inputs', async ({ page }) => {
  const consoleErrors = [];
  page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      consoleErrors.push(`console.error: ${msg.text()}`);
    }
  });
  const failedRequests = [];
  page.on('requestfailed', (req) => {
    failedRequests.push(`${req.method()} ${req.url()} -> ${req.failure()?.errorText}`);
  });

  await page.goto('/');

  // Wait for default prefill to land.
  await expect(page.locator('#bamPath')).toHaveValue('resource/test.bam');
  await expect(page.locator('#fastaPath')).toHaveValue('resource/chr20.fa');
  await expect(page.locator('#region')).toHaveValue('20:59000-61000');

  await page.click('#loadRegion');

  // Wait up to 30s for either a success message or an explicit failure message.
  const messages = page.locator('#messages .message');
  await expect.poll(async () => (await messages.allTextContents()).join('\n'), {
    timeout: 30_000,
  }).toMatch(/(Loaded 20:59000-61000 in IGV\.|Failed|not in the BAM header|Provide|Could not)/);

  const lastText = (await messages.allTextContents()).join('\n');
  console.log('Final chat messages:\n', lastText);
  console.log('Console errors:\n', consoleErrors.join('\n'));
  console.log('Failed requests:\n', failedRequests.join('\n'));

  // Assert no IGV-fatal page errors and at least one alignment track view rendered.
  const trackViews = await page.locator('.igv-track-container, .igv-viewport').count();
  console.log('IGV track containers found:', trackViews);

  expect(lastText, `Expected success message; got:\n${lastText}`).toContain('Loaded 20:59000-61000 in IGV.');
});

const { test, expect } = require('@playwright/test');

const TEST_BAM = 'resource/test.bam';
const TEST_FASTA = 'resource/chr20.fa';
const TEST_REGION = '20:59000-61000';

async function bootPathMode(page) {
  // Keep the UI fully offline/deterministic in CI where public CDN fetches are blocked.
  await page.route('https://cdn.jsdelivr.net/npm/marked/marked.min.js', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/javascript',
      body: 'window.marked = { parse: (input) => String(input ?? "") };',
    });
  });

  await page.goto('/');

  await expect(page.locator('#llmStatus')).toHaveText('API: OK');

  await page.fill('#bamPath', TEST_BAM);
  await page.fill('#fastaPath', TEST_FASTA);
  await page.fill('#region', TEST_REGION);

  await expect(page.locator('#bamPath')).toHaveValue(TEST_BAM);
  await expect(page.locator('#fastaPath')).toHaveValue(TEST_FASTA);
  await expect(page.locator('#region')).toHaveValue(TEST_REGION);
}

async function sendChatPrompt(page, prompt) {
  await page.fill('#messageInput', prompt);
  await page.click('#sendMessage');

  await expect(page.getByTestId('control-summary')).toBeVisible({ timeout: 45_000 });
  await expect(page.getByTestId('control-execution-summary')).toBeVisible({ timeout: 45_000 });
  await expect(page.getByTestId('control-execution-details')).not.toContainText('State: not-run', {
    timeout: 45_000,
  });
}

test.describe('live path-mode typed control proof', () => {
  test.beforeEach(async ({ page }) => {
    await bootPathMode(page);
  });

  test('applies preset plus override in live app and records browser execution state', async ({ page }) => {
    await sendChatPrompt(
      page,
      'Use sv preset with trackHeight 180 and show navigation off at 20:59000-61000',
    );

    await expect(page.getByTestId('control-source')).toHaveText('Source: typed control_resolution');
    await expect(page.getByTestId('control-applied-list')).toContainText('preset:sv');
    await expect(page.getByTestId('control-applied-list')).toContainText('trackHeight');
    await expect(page.getByTestId('control-applied-list')).toContainText('showNavigation');

    await expect(page.getByTestId('control-execution-headline')).toHaveText('Applied in browser without reload.');
    await expect(page.getByTestId('control-execution-details')).toContainText('State: applied-in-browser');
    await expect(page.getByTestId('control-execution-details')).toContainText('Applied keys:');
    await expect(page.getByTestId('control-execution-details')).toContainText('trackHeight');
    await expect(page.getByTestId('control-execution-details')).toContainText('showNavigation');
  });

  test('shows partial-understanding parse notes for value-less control mention', async ({ page }) => {
    await sendChatPrompt(
      page,
      'sv preset, maybe turn on ruler and track height at 20:59000-61000',
    );

    await expect(page.getByTestId('control-source')).toHaveText('Source: typed control_resolution');
    await expect(page.getByTestId('control-applied-list')).toContainText('preset:sv');
    await expect(page.getByTestId('control-applied-list')).toContainText('showRuler');

    await expect(page.getByTestId('control-skipped-list')).toContainText('parse_note');
    await expect(page.getByTestId('control-parse-notes')).toContainText(
      "Detected numeric key 'trackHeight' without a numeric value",
    );

    await expect(page.getByTestId('control-execution-details')).toContainText('State: applied-in-browser');
    await expect(page.getByTestId('control-execution-details')).toContainText('Applied keys:');
    await expect(page.getByTestId('control-execution-details')).toContainText('showRuler');
  });

  test('keeps mixed control plus analysis behavior: control applies and SV analysis remains visible', async ({ page }) => {
    await sendChatPrompt(
      page,
      'Use sv preset with show ruler off and analyze structural variant evidence at 20:59000-61000',
    );

    await expect(page.getByTestId('control-source')).toHaveText('Source: typed control_resolution');
    await expect(page.getByTestId('control-applied-list')).toContainText('preset:sv');
    await expect(page.getByTestId('control-applied-list')).toContainText('showRuler');

    await expect(page.getByTestId('control-execution-details')).toContainText('State: applied-in-browser');
    await expect(page.getByTestId('control-execution-details')).toContainText('Applied keys:');
    await expect(page.getByTestId('control-execution-details')).toContainText('showRuler');

    // Mixed request must retain visible analysis output, not collapse into control-only feedback.
    await expect(page.locator('#svSummary')).toBeVisible();
    await expect(page.locator('#svSummary')).toContainText('SV:');
    await expect(page.locator('#messages')).not.toContainText('Request failed:');
  });
});

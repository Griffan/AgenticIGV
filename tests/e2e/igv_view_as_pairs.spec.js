/**
 * Tests for viewAsPairs IGV control.
 *
 * The stub deliberately exposes all methods the real IGV.js trackView and track
 * objects expose (updateViews, repaintViews, clearCachedFeatures, featureSource.setViewAsPairs)
 * and records every call so we can assert exactly which refresh path was taken.
 *
 * Each test asserts:
 *  1. track.viewAsPairs is set to the correct boolean
 *  2. featureSource.setViewAsPairs() was called
 *  3. A display-refresh method was called (updateViews preferred over repaintViews)
 *  4. The execution status shown in the UI is "applied-in-browser" (no reload needed)
 */
const { test, expect } = require('@playwright/test');

function buildIgvStub() {
  // Returned as a string to be evaluated in addInitScript — must be self-contained.
  return `
    window.__PW_CALLS__ = [];
    window.__PW_IGV_LAST_BROWSER__ = null;

    const track = {
      type: 'alignment',
      config: {},
      viewAsPairs: false,
      showSoftClips: true,
      showReadNames: false,
      featureSource: {
        setViewAsPairs(v) {
          window.__PW_CALLS__.push({ method: 'featureSource.setViewAsPairs', value: v });
        },
        setShowSoftClips(v) {
          window.__PW_CALLS__.push({ method: 'featureSource.setShowSoftClips', value: v });
        },
      },
      // Real IGV Track base class exposes clearCachedFeatures()
      clearCachedFeatures() {
        window.__PW_CALLS__.push({ method: 'track.clearCachedFeatures' });
      },
      getFeatures() { return Promise.resolve([]); },
    };

    const trackView = {
      track,
      viewports: [{ rulerSweeper: { container: { style: {} } } }],
      setTrackHeight(v) { track.config.trackHeight = Number(v); },
      // Real IGV TrackView exposes both updateViews and repaintViews
      updateViews() {
        window.__PW_CALLS__.push({ method: 'tv.updateViews' });
      },
      repaintViews() {
        window.__PW_CALLS__.push({ method: 'tv.repaintViews' });
      },
      clearCachedFeatures() {
        window.__PW_CALLS__.push({ method: 'tv.clearCachedFeatures' });
      },
    };

    const browser = {
      config: {},
      navbar: { container: { style: {} } },
      showCenterGuide: true,
      trackViews: [trackView],
      referenceFrameList: [{ chrName: '20', start: 58999, bpPerPixel: 1 }],
      on() {},
      async search(region) {
        window.__PW_CALLS__.push({ method: 'browser.search', region });
      },
      repaint() {},
      destroy() {},
      currentLoci() { return ['20:59000-61000']; },
    };

    window.__PW_IGV_LAST_BROWSER__ = browser;
    window.__PW_IGV_STUB__ = { createBrowser: async () => browser };
  `;
}

function chatPayload(viewAsPairs) {
  return JSON.stringify({
    response: 'Showing reads as pairs.',
    region: '20:59000-61000',
    coverage: [],
    reads: [],
    variant_assessment: {},
    metrics: {},
    sv_present: null,
    sv_type: null,
    sv_confidence: null,
    sv_evidence: [],
    control_resolution: {
      preset: null,
      preset_source: 'none',
      preset_path: null,
      base_igv: {},
      resolved_igv: { viewAsPairs },
      applied: [
        { key: 'viewAsPairs', action: 'applied', reason: 'Direct override', value: viewAsPairs },
      ],
      skipped: [],
      failed: [],
      parse_notes: [],
    },
    igv_params: { viewAsPairs },
    igv_feedback: `viewAsPairs set to ${viewAsPairs}`,
    preset: null,
    bam_tracks: [{ sample_name: 'sample_1', bam_path: 'resource/test.bam' }],
    per_track_results: {},
  });
}

test.describe('viewAsPairs control', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/static/igv.min.js', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: 'window.igv = window.__PW_IGV_STUB__;',
      });
    });
    await page.addInitScript(buildIgvStub());
    await page.route('**/api/health', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' });
    });
    await page.route('**/static/marked.min.js', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: 'window.marked = { parse: (s) => String(s ?? "") };',
      });
    });
  });

  test('sets track.viewAsPairs=true, calls featureSource.setViewAsPairs, and refreshes display', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: chatPayload(true) });
    });

    await page.goto('/');
    await page.fill('#messageInput', 'show reads as pairs at 20:59000-61000');
    await page.click('#sendMessage');

    // Wait for execution status to settle
    await expect(page.getByTestId('control-execution-summary')).toBeVisible({ timeout: 15_000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="control-execution-details"]');
        const text = el?.textContent || '';
        return (
          text.includes('State: applied-in-browser') ||
          text.includes('State: reloaded') ||
          text.includes('State: browser-error')
        );
      },
      { timeout: 15_000 },
    );

    const state = await page.evaluate(() => {
      const browser = window.__PW_IGV_LAST_BROWSER__;
      const track = browser?.trackViews?.[0]?.track;
      const calls = window.__PW_CALLS__ || [];
      return {
        trackViewAsPairs: track?.viewAsPairs,
        trackConfigViewAsPairs: track?.config?.viewAsPairs,
        calls,
      };
    });

    // 1. track.viewAsPairs must be true
    expect(state.trackViewAsPairs).toBe(true);
    expect(state.trackConfigViewAsPairs).toBe(true);

    // 2. featureSource.setViewAsPairs(true) must have been called
    const fsCall = state.calls.find(c => c.method === 'featureSource.setViewAsPairs');
    expect(fsCall).toBeTruthy();
    expect(fsCall.value).toBe(true);

    // 3. A display-refresh method must have been called (updateViews preferred)
    const updateViewsCalled = state.calls.some(c => c.method === 'tv.updateViews');
    const repaintViewsCalled = state.calls.some(c => c.method === 'tv.repaintViews');
    expect(updateViewsCalled || repaintViewsCalled).toBe(true);

    // 4. Execution status should be applied-in-browser — no search() reload needed
    await expect(page.getByTestId('control-execution-details')).toContainText('State: applied-in-browser');

    console.log('Call sequence:', JSON.stringify(state.calls, null, 2));
  });

  test('sets track.viewAsPairs=false and refreshes display', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: chatPayload(false) });
    });

    await page.goto('/');
    await page.fill('#messageInput', 'turn off view as pairs at 20:59000-61000');
    await page.click('#sendMessage');

    await expect(page.getByTestId('control-execution-summary')).toBeVisible({ timeout: 15_000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="control-execution-details"]');
        const text = el?.textContent || '';
        return text.includes('State: applied-in-browser') || text.includes('State: reloaded') || text.includes('State: browser-error');
      },
      { timeout: 15_000 },
    );

    const state = await page.evaluate(() => ({
      trackViewAsPairs: window.__PW_IGV_LAST_BROWSER__?.trackViews?.[0]?.track?.viewAsPairs,
      calls: window.__PW_CALLS__ || [],
    }));

    expect(state.trackViewAsPairs).toBe(false);
    const fsCall = state.calls.find(c => c.method === 'featureSource.setViewAsPairs');
    expect(fsCall).toBeTruthy();
    expect(fsCall.value).toBe(false);
    const refreshed = state.calls.some(c => c.method === 'tv.updateViews' || c.method === 'tv.repaintViews');
    expect(refreshed).toBe(true);
  });

  test('updateViews() is preferred over repaintViews() when available', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: chatPayload(true) });
    });

    await page.goto('/');
    await page.fill('#messageInput', 'view as pairs at 20:59000-61000');
    await page.click('#sendMessage');

    await expect(page.getByTestId('control-execution-summary')).toBeVisible({ timeout: 15_000 });
    await page.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="control-execution-details"]');
        const text = el?.textContent || '';
        return text.includes('State: applied-in-browser') || text.includes('State: reloaded') || text.includes('State: browser-error');
      },
      { timeout: 15_000 },
    );

    const calls = await page.evaluate(() => window.__PW_CALLS__ || []);

    // updateViews() causes a genuine re-fetch; repaintViews() only redraws from cache.
    // If the stub exposes both, updateViews() must be chosen.
    const updateViewsCalled = calls.some(c => c.method === 'tv.updateViews');
    expect(updateViewsCalled).toBe(true);
    // browser.search() must NOT be called — it's a no-op for the same region and
    // delays the UX unnecessarily.
    const searchCalled = calls.some(c => c.method === 'browser.search');
    expect(searchCalled).toBe(false);

    console.log('Call sequence:', JSON.stringify(calls, null, 2));
  });
});

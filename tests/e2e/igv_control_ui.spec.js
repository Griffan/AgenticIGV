const { test, expect } = require('@playwright/test');

test.describe('typed control feedback', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/static/igv.min.js', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: 'window.igv = window.__PW_IGV_STUB__;',
      });
    });

    await page.addInitScript(() => {
      window.__PW_FAIL_SEARCH__ = false;
      window.__PW_IGV_LAST_BROWSER__ = null;

      window.__PW_IGV_STUB__ = {
        createBrowser: async () => {
          const navContainer = { style: {} };
          const track = {
            type: 'alignment',
            config: {},
            featureSource: { setViewAsPairs() {}, setShowSoftClips() {} },
            viewAsPairs: false,
            showSoftClips: true,
            showReadNames: false,
          };

          const browser = {
            config: {},
            navbar: { container: navContainer },
            showCenterGuide: true,
            trackViews: [{
              track,
              setTrackHeight(value) {
                track.config.trackHeight = Number(value);
              },
              repaintViews() {},
              viewports: [{ cachedFeatures: { setViewAsPairs() {} }, rulerSweeper: { container: { style: {} } } }],
            }],
            referenceFrameList: [{ chrName: '20', start: 58999, bpPerPixel: 1 }],
            on() {},
            async search() {
              if (window.__PW_FAIL_SEARCH__) {
                throw new Error('forced search failure');
              }
            },
            repaint() {},
            destroy() {},
            currentLoci() { return ['20:59000-61000']; },
          };

          window.__PW_IGV_LAST_BROWSER__ = browser;
          return browser;
        },
      };
    });

    await page.route('**/api/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok' }),
      });
    });
  });

  test('applies typed control payloads with execution diagnostics and keeps mixed analysis output', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          response: 'typed response with analysis details',
          region: '20:59000-61000',
          coverage: [],
          reads: [],
          variant_assessment: {},
          metrics: {},
          sv_present: true,
          sv_type: 'DEL',
          sv_confidence: 0.82,
          sv_evidence: [],
          control_resolution: {
            preset: 'sv',
            preset_source: 'resource',
            preset_path: 'resource/igv_presets/sv.json',
            base_igv: { trackHeight: 120 },
            resolved_igv: {
              trackHeight: 180,
              showNavigation: false,
              showRuler: false,
              showCenterGuide: false,
            },
            applied: [
              { key: 'preset:sv', action: 'applied', reason: 'Loaded preset asset', value: 'resource/igv_presets/sv.json' },
              { key: 'trackHeight', action: 'applied', reason: 'Applied direct override', value: 180 },
            ],
            skipped: [],
            failed: [],
            parse_notes: [],
          },
          igv_params: {
            trackHeight: 180,
            showNavigation: false,
            showRuler: false,
            showCenterGuide: false,
          },
          igv_feedback: 'Preset applied',
          preset: 'sv',
          bam_tracks: [{ sample_name: 'sample_1', bam_path: 'resource/test.bam' }],
          per_track_results: {},
        }),
      });
    });

    await page.goto('/');
    await page.fill('#messageInput', 'apply typed controls and analyze');
    await page.click('#sendMessage');

    await expect(page.getByTestId('control-summary')).toBeVisible();
    await expect(page.getByTestId('control-source')).toHaveText('Source: typed control_resolution');
    await expect(page.getByTestId('control-applied-list')).toContainText('trackHeight');

    await expect(page.getByTestId('control-execution-summary')).toBeVisible();
    await expect(page.getByTestId('control-execution-headline')).toHaveText('Applied in browser without reload.');
    await expect(page.getByTestId('control-execution-details')).toContainText('State: applied-in-browser');
    await expect(page.getByTestId('control-execution-details')).toContainText('Reload needed: no');

    await expect(page.locator('#messages')).toContainText('typed response with analysis details');
    await expect(page.locator('#svSummary')).toContainText('SV: present');

    const browserState = await page.evaluate(() => {
      const browser = window.__PW_IGV_LAST_BROWSER__;
      const firstTrack = browser?.trackViews?.[0]?.track;
      const firstViewport = browser?.trackViews?.[0]?.viewports?.[0];
      return {
        showNavigation: browser?.config?.showNavigation,
        showRuler: browser?.config?.showRuler,
        showCenterGuide: browser?.config?.showCenterGuide,
        navDisplay: browser?.navbar?.container?.style?.display,
        rulerDisplay: firstViewport?.rulerSweeper?.container?.style?.display,
        trackHeight: firstTrack?.config?.trackHeight,
      };
    });

    expect(browserState.trackHeight).toBe(180);
    expect(browserState.showNavigation).toBe(false);
    expect(browserState.showRuler).toBe(false);
    expect(browserState.showCenterGuide).toBe(false);
    expect(browserState.navDisplay).toBe('none');
    expect(browserState.rulerDisplay).toBe('none');
  });

  test('applies typed control payloads requiring reload and keeps unsupported keys inspectable', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          response: 'reload needed response',
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
            resolved_igv: {
              showSoftClips: false,
              unsupportedThing: true,
            },
            applied: [
              { key: 'showSoftClips', action: 'applied', reason: 'Applied override', value: false },
            ],
            skipped: [
              { key: 'unsupportedThing', action: 'skipped', reason: 'Unsupported key in frontend', value: true },
            ],
            failed: [],
            parse_notes: ['Unsupported key preserved for inspection.'],
          },
          igv_params: {
            showSoftClips: false,
            unsupportedThing: true,
          },
          igv_feedback: 'Applied what was possible',
          preset: null,
          bam_tracks: [{ sample_name: 'sample_1', bam_path: 'resource/test.bam' }],
          per_track_results: {},
        }),
      });
    });

    await page.goto('/');
    await page.fill('#messageInput', 'reload controls');
    await page.click('#sendMessage');

    await expect(page.getByTestId('control-skipped-list')).toContainText('unsupportedThing');
    await expect(page.getByTestId('control-parse-notes')).toContainText('Unsupported key preserved for inspection.');

    await expect(page.getByTestId('control-execution-headline')).toHaveText('Applied in browser after reload.');
    await expect(page.getByTestId('control-execution-details')).toContainText('State: reloaded');
    await expect(page.getByTestId('control-execution-details')).toContainText('Reload needed: yes');
    await expect(page.getByTestId('control-execution-details')).toContainText('Ignored unsupported keys: unsupportedThing');
  });

  test('surfaces browser execution failures without hiding backend control rows', async ({ page }) => {
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          response: 'backend control succeeded but browser fails',
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
            resolved_igv: { showSoftClips: false },
            applied: [
              { key: 'showSoftClips', action: 'applied', reason: 'Applied direct override', value: false },
            ],
            skipped: [],
            failed: [
              { key: 'preset:nope', action: 'failed', reason: 'Preset not found' },
            ],
            parse_notes: [],
          },
          igv_params: { showSoftClips: false },
          igv_feedback: 'Control resolution succeeded',
          preset: null,
          bam_tracks: [{ sample_name: 'sample_1', bam_path: 'resource/test.bam' }],
          per_track_results: {},
        }),
      });
    });

    await page.goto('/');
    await page.evaluate(() => {
      window.__PW_FAIL_SEARCH__ = true;
    });

    await page.fill('#messageInput', 'force browser failure path');
    await page.click('#sendMessage');

    await expect(page.getByTestId('control-applied-list')).toContainText('showSoftClips');
    await expect(page.getByTestId('control-failed-list')).toContainText('preset:nope');

    await expect(page.getByTestId('control-execution-details')).toContainText('State: browser-error');
    await expect(page.getByTestId('control-execution-details')).toContainText('forced search failure');
    await expect(page.locator('#messages')).toContainText('Control execution warning: forced search failure');
  });
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdir } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const url = process.env.CHATGPT_WEB_URL;
const cdp = process.env.CHATGPT_TEST_CDP;
const output = process.env.CHATGPT_TEST_ARTIFACTS || '/tmp/chatgpt-web-acceptance';

test('live workstation controls and display remain within the viewport', { skip: !url || !cdp, timeout: 180000 }, async () => {
  await mkdir(output, { recursive: true });
  const browser = await chromium.connectOverCDP(cdp);
  try {
    for (const [width, height] of [[1440, 1000], [1024, 768], [800, 600], [390, 844], [844, 390]]) {
      const context = await browser.newContext({ viewport: { width, height } });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.goto(url);
      await page.locator('#videoCanvas').waitFor();
      const play = page.locator('#playButton');
      if (await play.isVisible()) await play.click();
      await page.waitForFunction(() => document.querySelector('#videoCanvas')?.width >= 1024, { timeout: 30000 });
      for (const panel of [null, 'clipboard', 'files', 'tools']) {
        if (panel) await page.locator(`#${panel}`).click();
        await page.waitForTimeout(200);
        const layout = await page.evaluate(() => {
          const box = (el) => {
            const r = el.getBoundingClientRect();
            return { id: el.id, x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height };
          };
          return {
            width: innerWidth, height: innerHeight,
            controls: [...document.querySelectorAll('#workstation header button, .panel:not([hidden]) button, .panel:not([hidden]) a, .panel:not([hidden]) textarea')].filter((el) => !el.hidden).map(box),
            desktop: box(document.querySelector('#desktop')),
            canvas: box(document.querySelector('#videoCanvas')),
          };
        });
        for (const rect of [...layout.controls, layout.desktop, layout.canvas]) {
          assert.ok(rect.width > 0 && rect.height > 0, `${width}x${height}: ${rect.id} collapsed`);
          assert.ok(rect.x >= -1 && rect.y >= -1 && rect.right <= width + 1 && rect.bottom <= height + 1, `${width}x${height}: clipped ${JSON.stringify(rect)}`);
        }
        for (const rect of layout.controls) assert.ok(rect.bottom <= layout.desktop.y + 1, `${rect.id} overlaps desktop`);
        assert.ok(layout.canvas.y >= layout.desktop.y - 1 && layout.canvas.bottom <= layout.desktop.bottom + 1, 'stream exceeds desktop slot');
        await page.screenshot({ path: `${output}/${width}x${height}-${panel || 'desktop'}.png` });
      }
      assert.deepEqual(errors, [], 'browser JavaScript errors');
      await context.close();
    }
  } finally { await browser.close(); }
});

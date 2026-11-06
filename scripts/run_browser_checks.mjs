import { chromium } from 'playwright';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import vm from 'node:vm';

await mkdir('output/browser', { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.MAKORA_BROWSER_CHANNEL ? { channel: process.env.MAKORA_BROWSER_CHANNEL } : {}) });
try {
  for (const name of ['browser-preparation', 'browser-stage-layout', 'browser-single-project']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    try {
      await page.goto(process.env.MAKORA_TEST_URL || 'http://127.0.0.1:8000/');
      const journey = vm.runInThisContext('(' + await readFile(`tests/${name}.js`, 'utf8') + ')');
      console.log(name, await journey(page));
    } catch (error) {
      await page.screenshot({ path: `output/browser/${name}-failure.png`, fullPage: true });
      await writeFile(`output/browser/${name}-failure.html`, await page.content());
      throw error;
    } finally { await context.close(); }
  }
} finally { await browser.close(); }

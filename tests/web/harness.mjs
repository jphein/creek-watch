// Shared test harness: serve ../../web statically on a free port and launch Chrome.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const WEB = path.join(REPO, 'web');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.webmanifest': 'application/manifest+json', '.jpg': 'image/jpeg' };

export function serveWeb() {
  const srv = http.createServer((req, res) => {
    const u = new URL(req.url, 'http://x');
    let f = path.normalize(path.join(WEB, decodeURIComponent(u.pathname)));
    if (!f.startsWith(WEB)) { res.writeHead(403).end(); return; }
    if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
    if (!fs.existsSync(f)) { res.writeHead(404, { 'content-type': 'application/json' }).end('{"detail":"Not Found"}'); return; }
    res.writeHead(200, { 'content-type': TYPES[path.extname(f)] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve({ base: `http://127.0.0.1:${srv.address().port}/`, close: () => srv.close() })));
}

export const mock = (name) => fs.readFileSync(path.join(WEB, 'mock', `${name}.json`), 'utf8');

// Browser: CHROME_PATH, else stable Google Chrome when installed, else Playwright's bundled Chromium
// (npx playwright-core install chromium). The bundled headless shell DENIES notifications even when the
// context grants them, so the push suites only run green in real Chrome (2026-10-04 triage).
const STABLE_CHROME = ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/opt/google/chrome/chrome'].find((x) => fs.existsSync(x));
export const BROWSER = process.env.CHROME_PATH || STABLE_CHROME || 'playwright-bundled';
export const launch = () => chromium.launch(BROWSER === 'playwright-bundled' ? {} : { executablePath: BROWSER });

// Precondition for push suites: notifications must really be granted in this browser, or every push check
// fails for a reason that has nothing to do with the app. Fail loudly instead (exit 2).
export async function requireNotifications(page) {
  const perm = await page.evaluate(() => (typeof Notification === 'undefined' ? 'unsupported' : Notification.permission));
  if (perm !== 'granted') {
    console.error(`SKIP-FAIL: Notification.permission is "${perm}" in ${BROWSER}; push suites need real Chrome (set CHROME_PATH=/usr/bin/google-chrome).`);
    process.exit(2);
  }
}

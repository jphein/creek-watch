# web/ browser tests

Headless-Chrome tests for the static PWA in `web/`. Each test serves `web/` itself on a free port.

```sh
cd tests/web && npm install
CHROME_PATH=/usr/bin/google-chrome npm test        # xss + service-worker push handler
BASE=http://127.0.0.1:8099/ DB=../../data/creekwatch.db npm run test:live   # needs a LOCAL backend with push configured
```

- `xss.test.mjs`: hostile values in every alert field (title, summary, url `javascript:`/`data:`/`http:`, …) on the Alerts page, deep link, creek banners and map popup; fails on any dialog, injected node or unsafe link.
- `push-sw.test.mjs`: pushes delivered via CDP; checks the official-channel notice, same-tag escalation replacement, same-origin click targets, literal HTML titles, malformed payloads.
- `push-live.test.mjs`: subscribe → update → unsubscribe against a running backend (201 → 200 → 204). Local backends only.

Without `CHROME_PATH`, stable Google Chrome is used when installed (`/usr/bin/google-chrome`), else Playwright's bundled Chromium (`npx playwright-core install chromium`). The bundled headless shell **denies notifications** even when the test grants them, so `push-sw` and `push-subscribe` stop with exit 2 and a `SKIP-FAIL: Notification.permission is "denied"` line there instead of failing every push check.

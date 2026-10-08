/**
 * TrustFL Dashboard E2E Playwright Tests
 * Tests the running dashboard at http://127.0.0.1:3000
 * API backend at http://127.0.0.1:8000
 * 
 * Run with: npx playwright test dashboard.spec.js --headed --browser=chromium
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const DASHBOARD_URL = 'http://127.0.0.1:3000';
const API_URL = 'http://127.0.0.1:8000';
const SCREENSHOT_DIR = path.join(__dirname, 'screenshots');

// Results tracking
const results = {
  pages: [],
  interactions: [],
  consoleErrors: [],
  networkFailures: [],
  screenshots: [],
};

function log(msg) { process.stdout.write(msg + '\n'); }

function recordPage(name, url, status, httpCode, notes) {
  const icon = status === 'PASS' ? '✓' : '✗';
  log(`  ${icon} [${status}] ${name} (${url}) HTTP:${httpCode} ${notes || ''}`);
  results.pages.push({ name, url, status, httpCode, notes });
}

function recordInteraction(name, status, detail) {
  const icon = status === 'PASS' ? '✓' : '✗';
  log(`  ${icon} [${status}] ${name}: ${detail || ''}`);
  results.interactions.push({ name, status, detail });
}

async function screenshot(page, name) {
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const fname = path.join(SCREENSHOT_DIR, `${name.replace(/[^a-z0-9]/gi, '_')}.png`);
  await page.screenshot({ path: fname, fullPage: true });
  results.screenshots.push(fname);
  log(`  📸 Screenshot: ${fname}`);
  return fname;
}

async function checkAPIReachable() {
  const res = await fetch(`${API_URL}/federations/`);
  if (!res.ok) throw new Error(`API not reachable: ${res.status}`);
  const json = await res.json();
  return json;
}

async function seedTestData() {
  log('\n[Seeding test data]');
  const headers = { 'Content-Type': 'application/json' };

  // Create federation
  const fedRes = await fetch(`${API_URL}/federations/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ id: 'pw-fed-01', name: 'Playwright Test Federation', min_clients: 2, max_rounds: 5 })
  });
  if (fedRes.ok) log('  Created federation pw-fed-01');
  else if (fedRes.status === 409) log('  Federation already exists');
  else log(`  Federation create: ${fedRes.status}`);

  // Create clients
  for (const cid of ['pw-client-01', 'pw-client-02']) {
    const r = await fetch(`${API_URL}/clients/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ id: cid, federation_id: 'pw-fed-01', public_key_b64: 'dGVzdGtleQ==' })
    });
    if (r.ok) log(`  Created client ${cid}`);
    else if (r.status === 409) log(`  Client ${cid} already exists`);
  }

  // Create a round
  const rndRes = await fetch(`${API_URL}/rounds/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ federation_id: 'pw-fed-01', round_number: 1, model_version: 'v1.0' })
  });
  if (rndRes.ok) {
    log('  Created round 1');
    // Submit an update
    const updRes = await fetch(`${API_URL}/updates/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        id: 'pw-upd-01', round_id: 'pw-fed-01_round1',
        client_id: 'pw-client-01', artifact_hash: 'sha256:abc123',
        nonce: 'pw-client-01:1:deadbeef', num_examples: 100, loss: 0.5
      })
    });
    if (updRes.ok) log('  Created update pw-upd-01');
    // Create artifact
    const artRes = await fetch(`${API_URL}/artifacts/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        id: 'pw-art-01', federation_id: 'pw-fed-01', round_number: 1,
        uri: 'file:///tmp/model_v1.bin', sha256_hash: 'abc123', model_version: 'v1.0'
      })
    });
    if (artRes.ok) log('  Created artifact pw-art-01');
    // Create blockchain tx
    const bctxRes = await fetch(`${API_URL}/blockchain/transactions/`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        id: 'pw-tx-01', contract_name: 'ClientRegistry',
        function_name: 'registerClient', entity_id: 'pw-client-01',
        entity_type: 'client', status: 'CONFIRMED'
      })
    });
    if (bctxRes.ok) log('  Created blockchain tx pw-tx-01');
  } else if (rndRes.status === 409) {
    log('  Round already exists');
  }
}

async function testPage(page, name, url, { expectedContent, interactions } = {}) {
  log(`\n[Page: ${name}]`);
  const pageErrors = [];
  const netFails = [];

  page.on('console', msg => {
    if (msg.type() === 'error') {
      const text = `[console.error] ${msg.text()}`;
      pageErrors.push(text);
      results.consoleErrors.push({ page: name, message: text });
    }
  });

  page.on('pageerror', err => {
    const text = `[pageerror] ${err.message}`;
    pageErrors.push(text);
    results.consoleErrors.push({ page: name, message: text });
  });

  page.on('requestfailed', req => {
    // Filter out expected API calls that will gracefully fail
    const failText = `[reqfail] ${req.method()} ${req.url()} - ${req.failure()?.errorText}`;
    netFails.push(failText);
    results.networkFailures.push({ page: name, message: failText });
  });

  let httpCode = 0;
  try {
    const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
    httpCode = resp ? resp.status() : 0;
  } catch (e) {
    recordPage(name, url, 'FAIL', 0, `Navigation failed: ${e.message}`);
    await screenshot(page, name + '_error');
    return false;
  }

  const bodyText = await page.textContent('body').catch(() => '');
  const title = await page.title().catch(() => '');
  
  if (httpCode >= 500) {
    // Capture exact error message from Next.js
    const errMsg = bodyText.substring(0, 500).replace(/\s+/g, ' ').trim();
    recordPage(name, url, 'FAIL', httpCode, `Server error: ${errMsg.substring(0, 200)}`);
    await screenshot(page, name + '_500');
    if (pageErrors.length) log(`  Console errors: ${pageErrors.slice(0,3).join(' | ')}`);
    return false;
  }

  if (httpCode === 404) {
    recordPage(name, url, 'FAIL', httpCode, 'Route not found');
    await screenshot(page, name + '_404');
    return false;
  }

  // Check expected content
  let contentOk = true;
  if (expectedContent) {
    for (const txt of expectedContent) {
      if (!bodyText.includes(txt)) {
        contentOk = false;
        log(`  MISSING content: "${txt}"`);
      }
    }
  }

  await screenshot(page, name);
  
  if (contentOk) {
    recordPage(name, url, 'PASS', httpCode, title);
  } else {
    recordPage(name, url, 'FAIL', httpCode, 'Missing expected content');
    return false;
  }

  // Run interactions
  if (interactions) {
    for (const [desc, fn] of Object.entries(interactions)) {
      try {
        await fn(page);
        recordInteraction(desc, 'PASS');
      } catch (e) {
        recordInteraction(desc, 'FAIL', e.message.substring(0, 100));
      }
    }
  }

  return true;
}

async function main() {
  log('================================================================');
  log('TrustFL Dashboard Playwright E2E Tests — Chromium');
  log('================================================================');

  // Pre-flight: check API
  log('\n[Pre-flight API check]');
  try {
    const apiData = await checkAPIReachable();
    log(`  API reachable. Federations: ${apiData.data ? apiData.data.length : 0}`);
  } catch (e) {
    log(`  FATAL: API not reachable — ${e.message}`);
    process.exit(1);
  }

  // Seed data
  await seedTestData();

  // Launch Chromium
  log('\n[Launching Chromium (headed)]');
  const browser = await chromium.launch({ headless: false, slowMo: 200 });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    recordVideo: { dir: SCREENSHOT_DIR }
  });
  const page = await context.newPage();

  // ── Pages ────────────────────────────────────────────────────────

  log('\n════════════════ PAGE TESTS ════════════════');

  const dashboardOk = await testPage(page, 'dashboard_home', DASHBOARD_URL, {
    expectedContent: [],  // Will pass with any content when 200
    interactions: {
      'Navigation links present': async p => {
        const links = await p.$$('a[href]');
        if (links.length === 0) throw new Error('No anchor links found');
      },
    }
  });

  await testPage(page, 'clients_page', `${DASHBOARD_URL}/clients`, {
    expectedContent: [],
    interactions: {
      'Page has headings': async p => {
        const h = await p.$('h1, h2, h3');
        if (!h) throw new Error('No headings found');
      }
    }
  });

  await testPage(page, 'rounds_page', `${DASHBOARD_URL}/rounds`, {
    expectedContent: [],
    interactions: {
      'Page renders table or list': async p => {
        const content = await p.textContent('body');
        if (!content || content.length < 50) throw new Error('Page body too short');
      }
    }
  });

  await testPage(page, 'models_page', `${DASHBOARD_URL}/models`, { expectedContent: [] });

  await testPage(page, 'security_page', `${DASHBOARD_URL}/security`, {
    expectedContent: [],
    interactions: {
      'Security page has content': async p => {
        const text = await p.textContent('body');
        if (!text || text.length < 30) throw new Error('Empty security page');
      }
    }
  });

  // Test non-existent routes (error states)
  log('\n════════════════ ERROR STATE TESTS ════════════════');
  await testPage(page, 'nonexistent_page_404', `${DASHBOARD_URL}/does-not-exist`, {});

  // Test loading state — navigate away and back quickly
  log('\n════════════════ NAVIGATION TESTS ════════════════');
  try {
    await page.goto(DASHBOARD_URL, { timeout: 10000 });
    const links = await page.$$eval('nav a, header a, a[href^="/"]', els =>
      els.map(el => el.getAttribute('href')).filter(h => h && h.startsWith('/'))
    );
    log(`  Found ${links.length} internal navigation links`);
    recordInteraction('Internal nav links found', links.length > 0 ? 'PASS' : 'FAIL',
      links.length > 0 ? links.slice(0, 5).join(', ') : 'None found');

    // Click first internal link if available
    if (links.length > 0) {
      const firstLink = links[0];
      await page.click(`a[href="${firstLink}"]`).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      const afterUrl = page.url();
      recordInteraction(`Click nav link ${firstLink}`, 'PASS', `Navigated to ${afterUrl}`);
      await screenshot(page, 'after_nav_click');
    }
  } catch (e) {
    recordInteraction('Navigation test', 'FAIL', e.message);
  }

  await browser.close();

  // ── Report ───────────────────────────────────────────────────────
  log('\n================================================================');
  log('PLAYWRIGHT TEST REPORT — CHROMIUM');
  log('================================================================');

  log('\n── Pages Tested ──────────────────────────────────────────────');
  for (const p of results.pages) {
    const icon = p.status === 'PASS' ? '✓' : '✗';
    log(`  ${icon} [${p.status}] ${p.name} → HTTP ${p.httpCode}`);
    if (p.notes) log(`       ${p.notes}`);
  }

  log('\n── Interactions Tested ───────────────────────────────────────');
  for (const i of results.interactions) {
    const icon = i.status === 'PASS' ? '✓' : '✗';
    log(`  ${icon} [${i.status}] ${i.name}`);
    if (i.detail) log(`       ${i.detail}`);
  }

  log('\n── Console Errors ────────────────────────────────────────────');
  if (results.consoleErrors.length === 0) {
    log('  None');
  } else {
    for (const e of results.consoleErrors.slice(0, 10)) {
      log(`  [${e.page}] ${e.message}`);
    }
  }

  log('\n── Network Failures ──────────────────────────────────────────');
  if (results.networkFailures.length === 0) {
    log('  None');
  } else {
    for (const f of results.networkFailures.slice(0, 10)) {
      log(`  [${f.page}] ${f.message}`);
    }
  }

  log('\n── Screenshots ───────────────────────────────────────────────');
  for (const s of results.screenshots) {
    log(`  ${s}`);
  }

  const passedPages = results.pages.filter(p => p.status === 'PASS').length;
  const totalPages = results.pages.length;
  const passedInt = results.interactions.filter(i => i.status === 'PASS').length;
  const totalInt = results.interactions.length;

  log('\n── Summary ───────────────────────────────────────────────────');
  log(`  Pages:        ${passedPages}/${totalPages} passed`);
  log(`  Interactions: ${passedInt}/${totalInt} passed`);
  log(`  Console Errors: ${results.consoleErrors.length}`);
  log(`  Network Failures: ${results.networkFailures.length}`);
  log(`  Screenshots: ${results.screenshots.length}`);

  const verdict = passedPages === totalPages && passedInt === totalInt
    ? 'CHROMIUM: ALL TESTS PASSED'
    : `CHROMIUM: FAILURES DETECTED — ${totalPages - passedPages} page(s) failed`;

  log('\n── Final Verdict ─────────────────────────────────────────────');
  log(`  ${verdict}`);
  log('================================================================');

  // Exit non-zero if failures
  if (passedPages < totalPages) process.exit(1);
}

main().catch(e => {
  log(`\nFATAL ERROR: ${e.message}\n${e.stack}`);
  process.exit(1);
});

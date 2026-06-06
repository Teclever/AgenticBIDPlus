#!/usr/bin/env node
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, '..', 'screenshots');
const MOCKUPS = path.join(__dirname, '..', 'mockups');
const BASE = 'http://localhost:5173';

fs.mkdirSync(OUT, { recursive: true });

async function shot(page, name, opts = {}) {
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: opts.fullPage ?? true, ...opts });
  console.log(`  ✓ ${name}.png`);
}

async function login(page) {
  await page.goto(`${BASE}/login`);
  await page.fill('#email', 'user@teclever.com');
  await page.fill('#password', 'password');
  await page.click('button[type="submit"]');
  await page.waitForURL(`${BASE}/`);
}

async function capturePrototype(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  console.log('\n── Login (reference) ──');
  await page.goto(`${BASE}/login`);
  await shot(page, '01-login-empty-fields', { fullPage: false });

  await page.fill('#email', 'user@teclever.com');
  await shot(page, '02-login-filled-fields', { fullPage: false });
  await shot(page, '03-login-page-full');

  await login(page);

  console.log('\n── Dashboard (reference) ──');
  await page.goto(`${BASE}/`);
  await page.waitForTimeout(500);
  await shot(page, '04-dashboard-full');
  await shot(page, '05-dashboard-gem-card', {
    fullPage: false,
    clip: { x: 32, y: 180, width: 440, height: 540 },
  });

  console.log('\n── Header chrome ──');
  await shot(page, '06-header-navigation', {
    fullPage: false,
    clip: { x: 0, y: 0, width: 1440, height: 64 },
  });

  console.log('\n── Portal bid lists (reference) ──');
  const listPages = [
    ['07-portal-gem-all-bids', '/portal/gem'],
    ['08-portal-gem-filter-new-bids', '/portal/gem?filter=new'],
    ['09-portal-gem-filter-score5', '/portal/gem?filter=score5'],
    ['10-portal-gem-filter-high-priority', '/portal/gem?filter=highpriority'],
    ['11-portal-hal-all-bids', '/portal/hal'],
    ['12-portal-isro-all-bids', '/portal/isro'],
  ];
  for (const [name, route] of listPages) {
    await page.goto(`${BASE}${route}`);
    await page.waitForTimeout(400);
    await shot(page, name);
  }

  await page.goto(`${BASE}/portal/gem?filter=score4plus`);
  await page.waitForTimeout(300);
  await page.getByRole('button', { name: 'Filters' }).click();
  await page.waitForTimeout(300);
  await shot(page, '13-portal-gem-filters-panel-expanded');

  await page.goto(`${BASE}/portal/gem?filter=new`);
  await page.waitForTimeout(400);
  await shot(page, '14-portal-gem-active-filter-chips', { fullPage: false });

  console.log('\n── Bid detail (reference) ──');
  const bids = [
    ['15-bid-detail-score5-with-summary', 'GEM-2026-001'],
    ['16-bid-detail-score4-new', 'HAL-2026-042'],
    ['17-bid-detail-score3-moderate', 'GEM-2026-134'],
    ['18-bid-detail-score2-rejected', 'HAL-2026-055'],
    ['19-bid-detail-score5-isro', 'ISRO-2026-024'],
  ];
  for (const [name, id] of bids) {
    await page.goto(`${BASE}/bid/${id}`);
    await page.waitForTimeout(500);
    await shot(page, name);
  }

  await page.goto(`${BASE}/bid/GEM-2026-001`);
  await page.waitForTimeout(400);
  await page.getByRole('button', { name: 'Accept' }).click();
  await page.waitForTimeout(300);
  await shot(page, '20-bid-detail-accept-confirmation-modal', { fullPage: false });

  await page.getByRole('button', { name: 'Cancel' }).click();
  await page.getByRole('button', { name: 'Reject' }).click();
  await page.waitForTimeout(300);
  await shot(page, '21-bid-detail-reject-confirmation-modal', { fullPage: false });

  await page.goto(`${BASE}/bid/GEM-2026-001`);
  await page.waitForTimeout(400);
  await shot(page, '22-bid-detail-ai-evaluation-section', {
    fullPage: false,
    clip: { x: 100, y: 380, width: 800, height: 280 },
  });
  await shot(page, '23-bid-detail-ai-summary-section', {
    fullPage: false,
    clip: { x: 100, y: 600, width: 800, height: 500 },
  });
  await shot(page, '24-bid-detail-sidebar-chat-and-documents-to-remove', {
    fullPage: false,
    clip: { x: 960, y: 180, width: 440, height: 720 },
  });

  console.log('\n── Activity log (reference) ──');
  await page.goto(`${BASE}/activity`);
  await page.waitForTimeout(400);
  await shot(page, '25-activity-log-desktop');

  console.log('\n── Mobile layouts ──');
  await ctx.close();
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
  });
  const mpage = await mobile.newPage();
  await mpage.goto(`${BASE}/login`);
  await mpage.fill('#email', 'u@teclever.com');
  await mpage.fill('#password', 'x');
  await mpage.click('button[type="submit"]');
  await mpage.waitForURL(`${BASE}/`);

  await mpage.goto(`${BASE}/`);
  await mpage.waitForTimeout(400);
  await shot(mpage, '26-dashboard-mobile');

  await mpage.goto(`${BASE}/portal/gem`);
  await mpage.waitForTimeout(400);
  await shot(mpage, '27-portal-gem-mobile-cards');

  await mpage.goto(`${BASE}/bid/GEM-2026-001`);
  await mpage.waitForTimeout(400);
  await shot(mpage, '28-bid-detail-mobile');

  await mpage.goto(`${BASE}/activity`);
  await mpage.waitForTimeout(400);
  await shot(mpage, '29-activity-log-mobile');

  await mobile.close();
}

async function captureMockups(browser) {
  console.log('\n── Target-state mockups ──');
  const mockupFiles = fs
    .readdirSync(MOCKUPS)
    .filter((f) => f.endsWith('.html'))
    .sort();

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  for (const file of mockupFiles) {
    const name = file.replace('.html', '');
    const filePath = path.join(MOCKUPS, file);
    await page.goto(`file://${filePath}`);
    await page.waitForTimeout(300);
    const isModal = name.includes('dialog') || name.includes('modal') || name.includes('dispute');
    await shot(page, name, { fullPage: !isModal });
  }

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  const mpage = await mobile.newPage();
  await mpage.goto(`file://${path.join(MOCKUPS, 'target-notification-panel.html')}`);
  await mpage.waitForTimeout(300);
  await shot(mpage, '36-target-notification-panel-mobile', { fullPage: false });

  await ctx.close();
  await mobile.close();
}

async function main() {
  const res = await fetch(BASE);
  if (!res.ok) throw new Error(`Dev server not reachable at ${BASE}`);

  const browser = await chromium.launch();
  try {
    await capturePrototype(browser);
    await captureMockups(browser);
    console.log(`\nDone — ${fs.readdirSync(OUT).filter(f => f.endsWith('.png')).length} screenshots in ${OUT}`);
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

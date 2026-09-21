// Real-browser regression for the arbitrary-precision coordinate bug.
//
// Drives the actual nginx-served page (no direct solve() call): fills the
// six >2^53 points through the real inputs, selects area 2 / outlier cap 0,
// clicks "执行审计", and then verifies
//   * the business request that left the browser still carries 6 pairwise
//     distinct exact coordinates (the old parseFloat/Number chain collapsed
//     them to 4);
//   * the page renders area 2, 6 retained points, 0 outliers and no
//     frontend-produced "duplicate coordinates" error;
//   * every exact integer in the raw backend response (coordinates, area,
//     basis, origin, (m,n) coords) survives the frontend's own lossless
//     parser and appears verbatim in the DOM.
//
// Run: node browser_audit.mjs <WEB_URL>
// Exits 0 on success, 1 on any failed assertion.

import { chromium } from 'playwright';
import { parseLosslessJson } from '../src/intmath.js';

const webUrl = process.argv[2];
if (!webUrl) {
  console.error('usage: node browser_audit.mjs <WEB_URL>');
  process.exit(2);
}

const B = 9007199254740992n;
const POINTS = Array.from({ length: 6 }, (_, i) => ({
  id: `p${i}`,
  x: (B + BigInt(i % 3)).toString(10),
  y: (2n * BigInt(Math.floor(i / 3))).toString(10)
}));

let failures = 0;
function check(cond, msg) {
  if (cond) {
    console.log(`  ok  ${msg}`);
  } else {
    console.error(`FAIL  ${msg}`);
    failures += 1;
  }
}

const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage']
});
try {
  const page = await browser.newPage();

  const requestBodies = [];
  let rawResponse = null;
  page.on('request', (req) => {
    if (req.url().includes('/api/audit')) requestBodies.push(req.postData() ?? '');
  });
  page.on('response', async (res) => {
    if (res.url().includes('/api/audit')) {
      try {
        rawResponse = await res.text();
      } catch (e) {
        rawResponse = `<<response read failed: ${e}>>`;
      }
    }
  });

  await page.goto(webUrl, { waitUntil: 'networkidle' });

  // Reduce the 13 sample rows to the six required by the scenario using the
  // real delete buttons.
  for (let n = 13; n > 6; n -= 1) {
    await page.locator('.point-table tbody tr').first().locator('button').click();
  }
  check(await page.locator('.point-table tbody tr').count() === 6, 'editor shows 6 rows');

  const rows = page.locator('.point-table tbody tr');
  for (let i = 0; i < 6; i += 1) {
    const inputs = rows.nth(i).locator('input');
    await inputs.nth(0).fill(POINTS[i].id);
    await inputs.nth(1).fill(POINTS[i].x);
    await inputs.nth(2).fill(POINTS[i].y);
  }
  await page.locator('.params input').fill('2');
  await page.locator('.params select').selectOption('0');
  check(await page.locator('button.btn-primary').isEnabled(),
        'audit button enabled: string-level validation accepts the six points');

  await page.locator('button.btn-primary', { hasText: '执行审计' }).click();

  await page.waitForSelector('.verdict-ok', { timeout: 15000 });

  // --- the request that actually left the browser -------------------------
  check(requestBodies.length === 1, `exactly one audit request was sent (got ${requestBodies.length})`);
  const sent = parseLosslessJson(requestBodies[0], { strictIntegers: true });
  const sentPairs = sent.points.map((p) => `${p.x}|${p.y}`);
  check(new Set(sentPairs).size === 6, 'request still contains 6 distinct exact coordinates');
  check(JSON.stringify(sentPairs) === JSON.stringify(POINTS.map((p) => `${p.x}|${p.y}`)),
        'request coordinates match the six entered points digit-for-digit');
  check(sent.min_cell_area === '2' && sent.max_outliers === '0',
        'request carries min_cell_area=2 and max_outliers=0 exactly');

  // --- the exact raw response parsed by the frontend's own parser ---------
  check(typeof rawResponse === 'string' && rawResponse.startsWith('{'), 'backend response was captured');
  const data = parseLosslessJson(rawResponse, { strictIntegers: true });
  check(data.feasible === true, 'parsed response is feasible');
  const r = data.result;
  check(r.area === '2', `parsed exact area is 2 (got ${r.area})`);
  check(r.outlier_count === '0', `parsed exact outlier count is 0 (got ${r.outlier_count})`);
  check(r.retained_count === '6', `parsed exact retained count is 6 (got ${r.retained_count})`);
  check(r.retained.length === 6, 'parsed response lists all six retained points');
  check(r.outliers.length === 0, 'parsed response lists no outliers');
  check(new Set(r.retained.map((p) => `${p.x}|${p.y}`)).size === 6,
        'parsed retained coordinates are six distinct exact values');
  check(r.retained[0].x === '9007199254740992' && r.retained[1].x === '9007199254740993',
        'adjacent >2^53 integers stay distinct after parsing');
  check(r.basis.b1[0] === '1' && r.basis.b1[1] === '0'
        && r.basis.b2[0] === '0' && r.basis.b2[1] === '2',
        `parsed basis b1=[1,0], b2=[0,2] (got ${JSON.stringify(r.basis)})`);
  check(r.origin[0] === '0' && r.origin[1] === '0',
        `parsed canonical origin is [0,0] (got ${JSON.stringify(r.origin)})`);
  check(data.input.points.length === 6, 'parsed echo keeps all six input points');
  check(new Set(data.input.points.map((p) => `${p.x}|${p.y}`)).size === 6,
        'parsed echo keeps six distinct exact coordinates');

  // --- what the page actually displays ------------------------------------
  const verdict = await page.locator('.verdict-ok').innerText();
  check(/面积（基矩阵行列式绝对值）=\s*2/.test(verdict), 'verdict shows area 2');
  check(/保留\s*6\s*个点/.test(verdict), 'verdict shows 6 retained points');
  check(/离群点\s*0\s*个/.test(verdict), 'verdict shows 0 outliers');

  check(await page.locator('.inline-error').count() === 0, 'no frontend error banner is shown');
  const bodyText = await page.locator('body').innerText();
  check(!/重复|duplicate/i.test(bodyText), 'page contains no duplicate-coordinate error');
  check(await page.locator('.stale-banner').count() === 0, 'result is not marked stale');

  // The retained table must display the exact decimal coordinates, the
  // exact (m,n) lattice coordinates, and six retained rows / zero outlier
  // rows.
  const tableRows = page.locator('.coord-table tbody tr');
  check(await tableRows.count() === 6, 'retained table shows exactly six rows');
  for (const p of r.retained) {
    const row = tableRows.filter({ hasText: p.id });
    const text = await row.innerText();
    check(text.includes(`(${p.x}, ${p.y})`),
          `${p.id} pixel coords rendered exactly (${p.x}, ${p.y})`);
    check(text.includes(`(${p.coord[0]},${p.coord[1]})`)
          || text.includes(`(${p.coord[0]}, ${p.coord[1]})`),
          `${p.id} lattice coords rendered exactly (${p.coord[0]}, ${p.coord[1]})`);
  }

  // Basis / origin / HNF panels echo the parsed exact integers verbatim.
  const matrixText = await page.locator('.meta-grid').innerText();
  for (const token of [r.basis.b1[0], r.basis.b1[1], r.basis.b2[0], r.basis.b2[1],
                       r.origin[0], r.origin[1], r.hnf.h, r.hnf.r, r.hnf.q]) {
    check(matrixText.includes(token), `exact result value ${token} present in basis/origin panel`);
  }

  // The SVG presentation drew all six retained spots from the exact data;
  // drawing offsets may be floats but the business data stays intact.
  check(await page.locator('circle.retained-dot').count() === 6, 'SVG draws six retained spots');
  check(await page.locator('circle.outlier-ring').count() === 0, 'SVG draws zero outlier rings');
  check(await page.locator('line.grid-line').count() > 0, 'SVG lattice grid was drawn');
} catch (e) {
  console.error(`FAIL  browser scenario aborted: ${e && e.stack || e}`);
  failures += 1;
} finally {
  await browser.close();
}

if (failures) {
  console.error(`BROWSER REGRESSION FAILED: ${failures} check(s) failed`);
  process.exit(1);
}
console.log('BROWSER REGRESSION PASSED: big-integer page submission is lossless');

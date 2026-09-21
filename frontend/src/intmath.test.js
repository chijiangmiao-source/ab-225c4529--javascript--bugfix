import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  canonicalIntText,
  coordKey,
  floorDiv,
  ceilDiv,
  intTextToBigInt,
  isIntegerText,
  parseLosslessJson,
  projectDouble,
  stringifyExactJson
} from './intmath.js';

test('integer text validation and canonicalization', () => {
  assert.equal(isIntegerText('  12  '), true);
  assert.equal(isIntegerText('-0'), true);
  assert.equal(isIntegerText('+7'), true);
  assert.equal(isIntegerText('1.0'), false);
  assert.equal(isIntegerText(''), false);
  assert.equal(canonicalIntText('007'), '7');
  assert.equal(canonicalIntText('+1'), '1');
  assert.equal(canonicalIntText('-000'), '0');
  assert.equal(canonicalIntText(' -009 '), '-9');
  assert.throws(() => canonicalIntText('x'));
});

test('coordinates beyond 2^53-1 keep distinct exact keys', () => {
  const B = 9007199254740992n;
  const keys = [];
  for (let i = 0; i < 3; i++) {
    keys.push(coordKey(String(B + BigInt(i)), '0'));
    keys.push(coordKey(String(B + BigInt(i)), '2'));
  }
  assert.equal(new Set(keys).size, 6);
  // The old float-based keying collapsed exactly these pairs:
  const rounded = keys.map((k) => {
    const [x, y] = k.split('|');
    return `${+(x)}|${+(y)}`;
  });
  assert.equal(new Set(rounded).size, 4);
  assert.equal(intTextToBigInt(String(B + 2n)), B + 2n);
});

test('parseLosslessJson preserves arbitrary-precision integers verbatim', () => {
  // Hand-written wire text: a real backend response is JSON numbers, possibly
  // far beyond 2^53 (area up to ~10^36).
  const text = '{"feasible":true,"result":{"area":81129638414606681695789005144064},'
    + '"points":[{"id":"p0","x":9007199254740992,"y":0},'
    + '{"id":"p1","x":9007199254740993,"y":0}],'
    + '"nested":{"basis":{"b1":[9007199254740994,2],"b2":[0,2]}}}';
  const parsed = parseLosslessJson(text, { strictIntegers: true });
  assert.equal(parsed.result.area, '81129638414606681695789005144064');
  assert.equal(parsed.points[0].x, '9007199254740992');
  assert.equal(parsed.points[1].x, '9007199254740993');
  assert.notEqual(parsed.points[0].x, parsed.points[1].x);
  assert.equal(parsed.nested.basis.b1[0], '9007199254740994');
  assert.equal(parsed.feasible, true);
  assert.equal(parsed.points[0].id, 'p0');
});

test('strict parser rejects fractional/exponent number tokens', () => {
  assert.throws(() => parseLosslessJson('{"a":1.5}', { strictIntegers: true }));
  assert.throws(() => parseLosslessJson('{"a":1e3}', { strictIntegers: true }));
  // But such tokens quoted in strings are left untouched.
  assert.deepEqual(parseLosslessJson('{"s":"1.5 and 1e3"}', { strictIntegers: true }), {
    s: '1.5 and 1e3'
  });
});

test('stringifyExactJson emits BigInts as bare precise JSON literals', () => {
  const B = 9007199254740992n;
  const body = stringifyExactJson({
    points: [
      { id: 'p0', x: B, y: 0n },
      { id: 'p1', x: B + 1n, y: 0n },
      { id: 'p2', x: B + 2n, y: 2n }
    ],
    min_cell_area: 2n,
    max_outliers: 0n
  });
  const reparsed = parseLosslessJson(body, { strictIntegers: true });
  assert.equal(reparsed.points[0].x, '9007199254740992');
  assert.equal(reparsed.points[1].x, '9007199254740993');
  assert.equal(new Set(reparsed.points.map((p) => `${p.x}|${p.y}`)).size, 3);
  // JavaScript numbers are refused so no float can silently enter a request.
  assert.throws(() => stringifyExactJson({ x: 2 }));
  assert.throws(() => stringifyExactJson({ x: undefined }));
});

test('exact floor/ceil division', () => {
  assert.equal(floorDiv(7n, 3n), 2n);
  assert.equal(floorDiv(-7n, 3n), -3n);
  assert.equal(ceilDiv(7n, 3n), 3n);
  assert.equal(ceilDiv(-7n, 3n), -2n);
  assert.equal(floorDiv(6n, 3n), 2n);
});

test('projectDouble only converts, stays finite for small offsets', () => {
  assert.equal(projectDouble(3n), 3);
  assert.equal(projectDouble(-2n), -2);
});

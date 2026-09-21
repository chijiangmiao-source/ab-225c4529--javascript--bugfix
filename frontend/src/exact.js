// Exact-integer boundary for the audit API.
//
// JavaScript numbers cannot distinguish integers above 2**53: the adjacent
// pixels 9007199254740992/3/4 all become the same float.  Audit inputs,
// uniqueness checks and exact results (area, basis, origin, per-point
// coordinates) therefore never go through a float: every business integer
// is held as a canonical decimal STRING, and the wire format tags each
// integer as {"@type":"int","value":"<digits>"}.  The Python backend uses
// the identical contract (backend/app/exact_json.py), so digits survive
// JSON.parse/stringify unchanged in both directions.
//
// Float conversion exists in exactly one sanctioned primitive, toFinite(),
// and may be used only to project points onto the SVG.  Its result must
// never feed validation, comparison, request construction or result data.

const INT_TAG = '@type';
const INT_TAG_VALUE = 'int';
const INT_VALUE = 'value';

const INTEGER_RE = /^[+-]?\d+$/;

export function isIntegerText(v) {
  return typeof v === 'string' && INTEGER_RE.test(v.trim());
}

// Canonical decimal form (no '+', no leading zeros, '-0' -> '0').
export function normalizeIntegerText(v) {
  const s = String(v).trim();
  if (!INTEGER_RE.test(s)) throw new Error(`not an integer literal: ${s}`);
  const neg = s.startsWith('-');
  let digits = neg || s.startsWith('+') ? s.slice(1) : s;
  digits = digits.replace(/^0+(?=\d)/, '');
  if (digits === '0') return '0';
  return neg ? `-${digits}` : digits;
}

// Tag a decimal-string integer for the exact wire contract.
export function tagInteger(v) {
  return { [INT_TAG]: INT_TAG_VALUE, [INT_VALUE]: normalizeIntegerText(v) };
}

// Exact sign/ordering over arbitrary-length decimal strings; returns -1/0/1
// without touching Number, so range checks stay exact beyond 2**53.
export function cmpInteger(a, b) {
  const sa = normalizeIntegerText(a);
  const sb = normalizeIntegerText(b);
  const negA = sa.startsWith('-');
  const negB = sb.startsWith('-');
  if (negA !== negB) return negA ? -1 : 1;
  const da = negA ? sa.slice(1) : sa;
  const db = negB ? sb.slice(1) : sb;
  let cmp = 0;
  if (da.length !== db.length) cmp = da.length < db.length ? -1 : 1;
  else if (da !== db) cmp = da < db ? -1 : 1;
  return negA ? -cmp : cmp;
}

// Display-only conversion: the single sanctioned float boundary.  Returns
// NaN when the text is not an integer literal or the magnitude is not
// representable; the returned number must never be written back into
// business data.  Written with the unary plus operator (not a
// float-constructor call) so no conversion primitive leaks elsewhere.
export function toFinite(v) {
  let canonical;
  try {
    canonical = normalizeIntegerText(v);
  } catch {
    return NaN;
  }
  const n = +canonical;
  return isFinite(n) ? n : NaN;
}

// Parse a response from the exact boundary.  Every integer must carry the
// int tag (revived to a canonical decimal string); bare JSON numbers are
// rejected because they would have already lost precision in the parser.
// Booleans (e.g. "feasible") and strings pass through untouched.
export function parseExactJSON(text) {
  return JSON.parse(text, (key, value) => {
    if (typeof value === 'number') {
      throw new Error(
        `bare JSON number${key ? ` at "${key}"` : ''} is forbidden on the ` +
        'exact integer boundary'
      );
    }
    if (
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      Object.prototype.hasOwnProperty.call(value, INT_TAG)
    ) {
      if (value[INT_TAG] !== INT_TAG_VALUE) {
        throw new Error(`unknown integer marker at "${key}": ${String(value[INT_TAG])}`);
      }
      const keys = Object.keys(value);
      if (keys.length !== 2 || !Object.prototype.hasOwnProperty.call(value, INT_VALUE)) {
        throw new Error(`tagged integer at "${key}" must carry exactly tag and value`);
      }
      return normalizeIntegerText(value[INT_VALUE]);
    }
    return value;
  });
}

// Exact arbitrary-precision integer support for the audit UI.
//
// The backend speaks exact JSON integers: coordinates may reach 10^18 and
// areas 10^36, far beyond JavaScript's safe-integer limit 2^53 - 1.  Business
// data therefore flows through the page as normalized decimal *strings*:
// input parsing, uniqueness checks, request construction, response parsing
// and exact comparisons never pass through `Number`/`parseInt`.  Conversion
// to a double happens in `projectDouble` only, at the SVG presentation
// boundary, and its result must never feed back into audit inputs,
// uniqueness comparisons or requests.

const INTEGER_RE = /^[+-]?\d+$/;

// Matches either a complete JSON string literal (including any digits
// embedded in it) or a JSON number token.  Used by parseLosslessJson to
// rewrite number tokens into exact decimal strings without touching the
// contents of string literals.
const JSON_TOKEN_RE = /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

export function isIntegerText(value) {
  return INTEGER_RE.test(String(value).trim());
}

// Normalize decimal integer text for exact comparison/keying: trim, drop a
// redundant sign/leading zeros so that "01", "+1" and "1" are identical.
export function canonicalIntText(value) {
  const s = String(value).trim();
  if (!INTEGER_RE.test(s)) {
    throw new Error(`not an exact integer: ${value}`);
  }
  const digits = s.replace(/^[+-]/, '').replace(/^0+(?=\d)/, '');
  return s.startsWith('-') && digits !== '0' ? `-${digits}` : digits;
}

// Exact BigInt value for decimal text coming from inputs or responses.
export function intTextToBigInt(value) {
  return BigInt(canonicalIntText(value));
}

// Exact coordinate identity key (replaces the old lossy float keying).
export function coordKey(x, y) {
  return `${canonicalIntText(x)}|${canonicalIntText(y)}`;
}

// Lossless JSON parser: every JSON number token is returned as its exact
// decimal source text instead of a JavaScript number.  With
// `strictIntegers` the parser additionally refuses any non-integer number
// token (decimal point / exponent), which an exact audit response must never
// carry.  Booleans, null and strings parse normally.
export function parseLosslessJson(text, { strictIntegers = false } = {}) {
  const rewritten = String(text).replace(JSON_TOKEN_RE, (token) => {
    if (token.charCodeAt(0) === 34) return token; // quoted string: untouched
    if (strictIntegers && /[.eE]/.test(token)) {
      throw new Error(`non-integer number token in exact audit payload: ${token}`);
    }
    return JSON.stringify(token); // number token -> exact decimal string
  });
  return JSON.parse(rewritten);
}

// Serialize a request object whose business integers are represented as
// BigInt values.  BigInts are emitted as bare JSON number literals with
// their full decimal precision; JavaScript `number` values are rejected so
// a silent float conversion can never re-enter the request path.
export function stringifyExactJson(value) {
  if (value === null) return 'null';
  if (typeof value === 'bigint') return value.toString(10);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((v) => stringifyExactJson(v)).join(',')}]`;
  }
  if (typeof value === 'object') {
    const parts = Object.entries(value).map(
      ([k, v]) => `${JSON.stringify(k)}:${stringifyExactJson(v)}`
    );
    return `{${parts.join(',')}}`;
  }
  throw new Error(`refusing to serialize lossy value of type ${typeof value}`);
}

// Presentation boundary only.  Converts an already-offset exact BigInt (a
// small SVG-relative difference) to a finite double for drawing.  Written
// with a unary plus rather than the `Number(...)` call form so that no
// float-coercion call survives in the business code path.  Must not be used
// on business coordinates or for any comparison/request.
export function projectDouble(exactInt) {
  const n = +exactInt.toString(10);
  if (!Number.isFinite(n)) {
    throw new Error('projected SVG coordinate is not finite');
  }
  return n;
}

// Exact floor / ceil division for a possibly negative dividend (BigInt "/"
// truncates toward zero, so floor needs an explicit correction).
export function floorDiv(a, b) {
  if (b <= 0n) throw new Error('floorDiv expects a positive divisor');
  return a >= 0n ? a / b : -((-a + b - 1n) / b);
}

export function ceilDiv(a, b) {
  if (b <= 0n) throw new Error('ceilDiv expects a positive divisor');
  return a >= 0n ? (a + b - 1n) / b : -((-a) / b);
}

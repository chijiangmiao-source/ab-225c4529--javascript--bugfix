// Typed access to the real backend audit API.
//
// The backend performs exact arbitrary-precision integer arithmetic
// (coordinates up to ~10^18, areas up to ~10^36), which exceeds JavaScript's
// safe-integer range.  Therefore:
//   * outgoing business integers are BigInt values serialized verbatim by
//     stringifyExactJson (no float formatting anywhere);
//   * incoming responses are parsed with parseLosslessJson, so every JSON
//     number (coordinates, basis, origin, area, counts, ...) is preserved as
//     its exact decimal text rather than rounded to a double.

import { parseLosslessJson, stringifyExactJson } from './intmath.js';

export async function fetchHealth() {
  const res = await fetch('/health');
  if (!res.ok) throw new Error(`health check failed: HTTP ${res.status}`);
  return parseLosslessJson(await res.text());
}

// `payload.points[].x/y`, `min_cell_area` and `max_outliers` must be BigInt.
export async function postAudit(payload) {
  const res = await fetch('/api/audit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: stringifyExactJson({
      points: payload.points.map((p) => ({ id: p.id, x: p.x, y: p.y })),
      min_cell_area: payload.minCellArea,
      max_outliers: payload.maxOutliers
    })
  });
  const rawText = await res.text();
  let data = null;
  try {
    // Success bodies must be integer-only and are parsed strictly so a
    // fractional token is an error rather than a silent rounding.  Error
    // bodies are parsed non-strictly: they are human-readable messages
    // (pydantic may echo the offending value), not business integers.
    data = parseLosslessJson(rawText, { strictIntegers: res.ok });
  } catch {
    if (res.ok) throw new Error('审计响应包含非整数数值，已拒绝显示以保证精确性');
    /* non-JSON or otherwise unparseable error body */
  }
  if (!res.ok) {
    const detail =
      data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data));
    throw new Error(detail || `审计请求失败：HTTP ${res.status}`);
  }
  return data;
}

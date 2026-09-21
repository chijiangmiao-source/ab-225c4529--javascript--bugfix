// Typed access to the real backend audit API.
//
// Every business integer (coordinates, parameters, area, basis, origin,
// per-point lattice coordinates) crosses HTTP as a tagged exact-integer
// string (see ./exact.js); it never passes through a JavaScript Number.
// The backend performs arbitrary-precision integer arithmetic and answers
// on the same exact contract, so values above 2**53 round-trip verbatim.

import { parseExactJSON, tagInteger } from './exact.js';

export async function fetchHealth() {
  const res = await fetch('/health');
  if (!res.ok) throw new Error(`health check failed: HTTP ${res.status}`);
  return res.json();
}

export async function postAudit({ points, minCellArea, maxOutliers }) {
  // points[].x/y and the parameters are canonical decimal strings here.
  // Tagging happens at this last step; nothing is coerced to a float.
  const body = {
    points: points.map((p) => ({
      id: p.id,
      x: tagInteger(p.x),
      y: tagInteger(p.y)
    })),
    min_cell_area: tagInteger(minCellArea),
    max_outliers: tagInteger(maxOutliers)
  };
  const res = await fetch('/api/audit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  const text = await res.text();
  let data = null;
  try {
    data = parseExactJSON(text);
  } catch (e) {
    if (!res.ok) {
      throw new Error(`审计请求失败：HTTP ${res.status}`);
    }
    throw new Error(`响应不是合法的精确整数 JSON：${e.message || e}`);
  }
  if (!res.ok) {
    const detail =
      data && (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data));
    throw new Error(detail || `审计请求失败：HTTP ${res.status}`);
  }
  return data;
}

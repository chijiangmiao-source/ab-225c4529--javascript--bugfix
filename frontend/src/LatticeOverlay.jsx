import React, { useMemo } from 'react';
import { toFinite } from './exact.js';

// Renders the exact integer lattice returned by the backend as an SVG
// overlay: unit-cell grid lines in canonical HNF basis, retained points
// (green) with their integer (m,n) labels and outliers (red rings).
//
// Business values (basis, origin, coordinates) are exact decimal strings.
// SVG geometry fundamentally needs finite floats, so conversion happens
// HERE AND ONLY HERE via toFinite(), purely for projection: the floats are
// never written back into result data, comparisons or re-submission.  When
// the magnitude is not representable (or distinct exact points project onto
// the same float pixel) the diagram says so, while the tables keep the exact
// values.
export default function LatticeOverlay({ result, allPoints }) {
  const geometry = useMemo(() => buildGeometry(result, allPoints), [result, allPoints]);

  if (!geometry) return null;
  if (geometry.unplottable) {
    return (
      <div className="hint">
        坐标超出 SVG 有限精度可绘制范围，已省略示意图形；基、原点、面积与逐点坐标仍为下方列出的精确整数值。
      </div>
    );
  }
  const { vbW, vbH, gridLines, vertices, retained, outliers, originSvg, lossy, gridSkipped } = geometry;

  return (
    <div>
      {lossy && (
        <div className="hint" data-testid="projection-lossy">
          示意图为有限精度投影：部分互异的精确整数点在该尺度下落在同一像素，精确坐标以表格为准。
        </div>
      )}
      {gridSkipped && (
        <div className="hint" data-testid="grid-skipped">
          晶胞网格在该坐标跨度过密，有限精度视图中无法逐条绘制，已省略网格线；基、原点与逐点坐标仍为精确值（见下表）。
        </div>
      )}
      <svg
        viewBox={`0 0 ${vbW} ${vbH}`}
        className="lattice-svg"
        role="img"
        aria-label="晶格叠加图"
      >
        {/* Unit-cell grid: lines along b1 (fixed n) and b2 (fixed m) */}
        <g>
          {gridLines.map((line, i) => (
            <line
              key={i}
              x1={line.a.x}
              y1={line.a.y}
              x2={line.b.x}
              y2={line.b.y}
              className={line.kind === 'b1' ? 'grid-line grid-line-b1' : 'grid-line grid-line-b2'}
            />
          ))}
        </g>

        {/* Grid vertices inside the view window (faint dots) */}
        {vertices.map((v, i) => (
          <circle key={`v${i}`} cx={v.x} cy={v.y} r={1.6} className="grid-vertex" />
        ))}

        {/* Canonical coset origin (exact label; float position only here) */}
        {Number.isFinite(originSvg.x) && Number.isFinite(originSvg.y) && (
          <>
            <circle cx={originSvg.x} cy={originSvg.y} r={5} className="origin-dot" />
            <text x={originSvg.x + 7} y={originSvg.y - 6} className="origin-label">
              o=({result.origin[0]},{result.origin[1]})
            </text>
          </>
        )}

        {/* Retained spots: positions are display-only projections; the
            (m,n) label text comes straight from the exact response. */}
        {retained.map((p) => (
          <g key={`r${p.id}`}>
            <circle cx={p.sx} cy={p.sy} r={6} className="retained-dot" />
            <text x={p.sx + 8} y={p.sy - 7} className="point-label">
              {p.id} ({p.coord[0]},{p.coord[1]})
            </text>
          </g>
        ))}

        {/* Outliers */}
        {outliers.map((p) => (
          <g key={`o${p.id}`}>
            <circle cx={p.sx} cy={p.sy} r={7} className="outlier-ring" />
            <line x1={p.sx - 5} y1={p.sy - 5} x2={p.sx + 5} y2={p.sy + 5} className="outlier-cross" />
            <line x1={p.sx - 5} y1={p.sy + 5} x2={p.sx + 5} y2={p.sy - 5} className="outlier-cross" />
            <text x={p.sx + 9} y={p.sy - 8} className="outlier-label">
              {p.id} 离群
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// Upper bound on enumerated unit cells (m-range times n-range).  Above
// this the finite projection cannot resolve individual cells anyway (a
// dense cell over a huge coordinate span), so the grid is skipped rather
// than enumerated -- points and the exact labels stay exact.
const GRID_MAX_CELLS = 20000;

function buildGeometry(result, allPoints) {
  if (!result) return null;

  // --- the single display-only float boundary for this diagram ---------
  const h = toFinite(result.basis.b1[0]);
  const r = toFinite(result.basis.b1[1]);
  const q = toFinite(result.basis.b2[1]);
  const origin = [toFinite(result.origin[0]), toFinite(result.origin[1])];
  // ---------------------------------------------------------------------

  const retainedById = new Map(result.retained.map((p) => [p.id, p]));
  const outlierIds = new Set(result.outliers);

  const plotted = allPoints
    .filter((p) => retainedById.has(p.id) || outlierIds.has(p.id))
    .map((p) => ({ id: p.id, x: toFinite(p.x), y: toFinite(p.y) }));
  if (plotted.length === 0) return null;

  const scalars = [h, r, q, origin[0], origin[1], ...plotted.flatMap((p) => [p.x, p.y])];
  if (scalars.some((v) => !Number.isFinite(v))) {
    return { unplottable: true };
  }

  // Distinct exact business points may share a finite projection at extreme
  // scales; the diagram flags this rather than pretending they coincide.
  const projectedKeys = new Map();
  let lossy = false;
  for (const p of plotted) {
    const key = `${p.x}|${p.y}`;
    if (projectedKeys.has(key) && projectedKeys.get(key) !== p.id) lossy = true;
    projectedKeys.set(key, p.id);
  }

  const xs = plotted.map((p) => p.x);
  const ys = plotted.map((p) => p.y);
  const minX = Math.min(...xs, origin[0]);
  const maxX = Math.max(...xs, origin[0]);
  const minY = Math.min(...ys, origin[1]);
  const maxY = Math.max(...ys, origin[1]);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const pad = 0.12;
  const wLo = minX - pad * spanX - 4;
  const wHi = maxX + pad * spanX + 4;
  const yLoData = minY - pad * spanY - 4;
  const yHiData = maxY + pad * spanY + 4;

  const vbW = wHi - wLo;
  const vbH = yHiData - yLoData;
  const project = (x, y) => ({ x: x - wLo, y: yHiData - y }); // y flip

  // Integer (m,n) range whose lattice points cover the window.
  // x = ox + h*m  =>  m in [(wLo-ox)/h, (wHi-ox)/h]
  const mLo = Math.floor((wLo - origin[0]) / h) - 1;
  const mHi = Math.ceil((wHi - origin[0]) / h) + 1;
  // y = oy + r*m + q*n; bound n using extreme m values.
  const nFor = (m, yv) => (yv - origin[1] - r * m) / q;
  const nCandidates = [mLo, mHi].flatMap((m) => [
    Math.floor(nFor(m, yLoData)) - 1,
    Math.ceil(nFor(m, yHiData)) + 1
  ]);
  const nLo = Math.min(...nCandidates);
  const nHi = Math.max(...nCandidates);
  const mCount = mHi - mLo + 1;
  const nCount = nHi - nLo + 1;
  // The grid is a purely visual aid; never enumerate more distinct cells
  // than the projection could possibly distinguish (e.g. a fine cell under
  // points at 10^16 would mean ~10^16 iterations and freeze the page).
  const gridEnabled =
    Number.isFinite(mCount) && Number.isFinite(nCount) &&
    mCount * nCount <= GRID_MAX_CELLS && mCount <= GRID_MAX_CELLS && nCount <= GRID_MAX_CELLS;

  const latticePoint = (m, n) => ({
    x: origin[0] + h * m,
    y: origin[1] + r * m + q * n,
    m,
    n
  });

  const inWindow = (p) =>
    p.x >= wLo - h && p.x <= wHi + h && p.y >= yLoData - q && p.y <= yHiData + q;

  const gridLines = [];
  const vertices = [];
  if (gridEnabled) {
    for (let n = nLo; n <= nHi; n++) {
      let prev = null;
      for (let m = mLo; m <= mHi; m++) {
        const p = latticePoint(m, n);
        if (inWindow(p)) {
          vertices.push(project(p.x, p.y));
          if (prev) gridLines.push({ a: project(prev.x, prev.y), b: project(p.x, p.y), kind: 'b1' });
          prev = p;
        } else {
          prev = null;
        }
      }
    }
    for (let m = mLo; m <= mHi; m++) {
      let prev = null;
      for (let n = nLo; n <= nHi; n++) {
        const p = latticePoint(m, n);
        if (inWindow(p)) {
          if (prev) gridLines.push({ a: project(prev.x, prev.y), b: project(p.x, p.y), kind: 'b2' });
          prev = p;
        } else {
          prev = null;
        }
      }
    }
  }

  const retained = result.retained.map((p) => {
    const s = project(toFinite(p.x), toFinite(p.y));
    return { ...p, sx: s.x, sy: s.y };
  });
  const outliers = plotted
    .filter((p) => outlierIds.has(p.id))
    .map((p) => {
      const s = project(p.x, p.y);
      return { ...p, sx: s.x, sy: s.y };
    });

  return {
    vbW,
    vbH,
    gridLines,
    vertices,
    retained,
    outliers,
    originSvg: project(origin[0], origin[1]),
    lossy,
    gridSkipped: !gridEnabled
  };
}

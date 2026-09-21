import React, { useMemo } from 'react';

import { ceilDiv, floorDiv, projectDouble } from './intmath.js';

// Renders the exact integer lattice returned by the backend as an SVG
// overlay: unit-cell grid lines in canonical HNF basis, retained points
// (green) with their integer (m,n) labels and outliers (red rings).
//
// Every grid vertex is reconstructed in exact data coordinates with
// p = origin + m*b1 + n*b2 (all arbitrary-precision integers, kept as
// BigInt).  The ONLY float conversions happen at the presentation boundary
// in `project`/`viewBox`: a small SVG-relative offset (data coord minus
// window origin) is converted to a double for positioning.  Those doubles
// are never written back into business coordinates, comparisons or
// re-submission.
export default function LatticeOverlay({ result, allPoints }) {
  const geometry = useMemo(() => buildGeometry(result, allPoints), [result, allPoints]);

  if (!geometry) return null;
  const { vbW, vbH, project, gridLines, vertices, retained, outliers, originSvg } = geometry;

  return (
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

      {/* Canonical coset origin */}
      <circle cx={originSvg.x} cy={originSvg.y} r={5} className="origin-dot" />
      <text x={originSvg.x + 7} y={originSvg.y - 6} className="origin-label">
        o=({result.origin[0]},{result.origin[1]})
      </text>

      {/* Retained spots */}
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
  );
}

const minInt = (acc, v) => (acc === undefined || v < acc ? v : acc);
const maxInt = (acc, v) => (acc === undefined || v > acc ? v : acc);

// Exact 12% padding (ceil(12 * span / 100)) plus the fixed 4-unit margin the
// presentation previously applied in floating point.
const padInt = (span) => (span * 12n + 99n) / 100n + 4n;

// Presentation-only caps on the enumerated grid.  Normal scenes have a few
// dozen cells; these only trip for pathological density (area-1 lattice
// spanning ~10^18 units), where drawing every cell is both impossible and
// visually meaningless.
const MAX_GRID_STEPS = 100000n;
const MAX_GRID_CELLS = 1_000_000n;

function buildGeometry(result, allPoints) {
  if (!result) return null;
  const b1 = result.basis.b1; // [h, r]
  const b2 = result.basis.b2; // [0, q]
  const h = BigInt(b1[0]);
  const r = BigInt(b1[1]);
  const q = BigInt(b2[1]);
  const ox0 = BigInt(result.origin[0]);
  const oy0 = BigInt(result.origin[1]);

  const retainedById = new Map(result.retained.map((p) => [p.id, p]));
  const outlierIds = new Set(result.outliers);

  // Keep the exact decimal identity of every plotted point; BigInt is used
  // solely for geometry below and never replaces x/y on the point objects.
  const plotted = allPoints
    .filter((p) => retainedById.has(p.id) || outlierIds.has(p.id))
    .map((p) => ({ id: p.id, x: BigInt(p.x), y: BigInt(p.y) }));
  if (plotted.length === 0) return null;

  let minX; let maxX; let minY; let maxY;
  for (const p of plotted) {
    minX = minInt(minX, p.x);
    maxX = maxInt(maxX, p.x);
    minY = minInt(minY, p.y);
    maxY = maxInt(maxY, p.y);
  }
  // The window hugs the *plotted points*; the canonical origin may live
  // arbitrarily far away (coordinates up to ~10^18 while the origin box is
  // [0,h) x [0,q)), so including it in the bounds could span ~10^18 units
  // and make the exact grid enumeration below astronomically large.  The
  // origin marker is simply off-canvas then; relative geometry is all that
  // SVG can portray anyway.
  const spanX = maxInt(maxX - minX, 1n);
  const spanY = maxInt(maxY - minY, 1n);
  const wLo = minX - padInt(spanX);
  const wHi = maxX + padInt(spanX);
  const yLoData = minY - padInt(spanY);
  const yHiData = maxY + padInt(spanY);

  // viewBox dimensions as doubles: presentation boundary.
  const vbW = projectDouble(wHi - wLo);
  const vbH = projectDouble(yHiData - yLoData);
  // Project exact data coords to SVG space on their *offset* from the window
  // origin: relative differences stay modest even when absolute coordinates
  // are 10^18.  This finite-precision value feeds SVG attributes only.
  const project = (x, y) => ({
    x: projectDouble(x - wLo),
    y: projectDouble(yHiData - y)
  }); // y flip

  // Integer (m,n) range whose lattice points cover the window, computed with
  // exact floor/ceil division.
  // x = ox + h*m  =>  m in [(wLo-ox)/h, (wHi-ox)/h]
  const mLo = floorDiv(wLo - ox0, h) - 1n;
  const mHi = ceilDiv(wHi - ox0, h) + 1n;
  // y = oy + r*m + q*n; bound n using extreme m values.
  // n = (yv - oy - r*m) / q
  const nFloorFor = (m, yv) => floorDiv(yv - oy0 - r * m, q);
  const nCeilFor = (m, yv) => ceilDiv(yv - oy0 - r * m, q);
  const nCandidates = [mLo, mHi].flatMap((m) => [
    nFloorFor(m, yLoData) - 1n,
    nCeilFor(m, yHiData) + 1n
  ]);
  let nLo; let nHi;
  for (const v of nCandidates) {
    nLo = minInt(nLo, v);
    nHi = maxInt(nHi, v);
  }

  const latticePoint = (m, n) => ({
    x: ox0 + h * m,
    y: oy0 + r * m + q * n,
    m,
    n
  });

  const inWindow = (p) =>
    p.x >= wLo - h && p.x <= wHi + h && p.y >= yLoData - q && p.y <= yHiData + q;

  const gridLines = [];
  const vertices = [];

  // Exact safety valve: a tiny generated lattice over a huge point spread
  // would mean billions of grid cells (e.g. an area-1 lattice with points
  // ~10^18 apart).  Draw no grid that dense (the lines would be
  // indistinguishable at any finite rendering scale anyway); retained /
  // outlier points, labels and the origin still render from exact data.
  // Business data is unaffected by this presentation-only decision.
  const mCount = mHi - mLo + 1n;
  const nCount = nHi - nLo + 1n;
  const drawGrid = mCount <= MAX_GRID_STEPS && nCount <= MAX_GRID_STEPS
    && mCount * nCount <= MAX_GRID_CELLS;

  if (drawGrid) {
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
    const s = project(BigInt(p.x), BigInt(p.y));
    return { ...p, sx: s.x, sy: s.y };
  });
  const outliers = plotted
    .filter((p) => outlierIds.has(p.id))
    .map((p) => {
      const s = project(p.x, p.y);
      return { id: p.id, sx: s.x, sy: s.y };
    });

  return {
    vbW,
    vbH,
    project,
    gridLines,
    vertices,
    retained,
    outliers,
    originSvg: project(ox0, oy0)
  };
}

// Map renderer.
//
// Pure drawing: give it a 2D context and a map document (the JSON the CLI
// exports) and it draws. No DOM lookups, no globals, no editing state - so the
// editor and the archive's thumbnail generator can share it unchanged.
//
// The JSON is row-major: terrain[y][x]. The save is column-major; the schema
// module owns that transpose, and nothing here needs to know about it.

import { terrain, team, UNIT_ABBR, HP_SCALE } from './terrain.js';

const GRID_LINE = 'rgba(0,0,0,0.13)';

/** Sparse `cells` as a lookup keyed by "x,y". */
export function cellIndex(doc) {
  const index = new Map();
  for (const c of doc.cells || []) index.set(c.x + ',' + c.y, c);
  return index;
}

/** The tile size that fits `doc` into a width x height box. */
export function fitTile(doc, width, height, max = 64) {
  const { cols, rows } = doc.size;
  return Math.max(1, Math.min(max, Math.floor(width / cols), Math.floor(height / rows)));
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawTile(ctx, doc, cells, x, y, px, py, size, opts) {
  const id = doc.terrain[y][x];
  const info = terrain(id);
  const cell = cells.get(x + ',' + y);

  if (info.property) {
    // A property is drawn in its owner's colour; that ownership is most of
    // what makes a map readable at a glance.
    const owner = team(cell ? cell.team : null);
    ctx.fillStyle = owner.color;
    ctx.fillRect(px, py, size, size);
    // HQs get a ring so they stand out from cities at thumbnail sizes.
    if (id === 512 && size >= 10) {
      ctx.strokeStyle = 'rgba(255,255,255,0.85)';
      ctx.lineWidth = Math.max(1, size / 12);
      ctx.strokeRect(px + size * 0.18, py + size * 0.18, size * 0.64, size * 0.64);
    }
  } else {
    ctx.fillStyle = info.color;
    ctx.fillRect(px, py, size, size);
  }

  if (opts.glyphs && info.glyph && size >= 12) {
    ctx.fillStyle = info.property ? 'rgba(255,255,255,0.92)' : 'rgba(0,0,0,0.5)';
    ctx.font = 'bold ' + Math.round(size * 0.5) + 'px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(info.glyph, px + size / 2, py + size / 2 + size * 0.04);
  }
}

function drawUnit(ctx, unit, px, py, size) {
  const owner = team(unit.team);
  const inset = size * 0.16;
  const w = size - inset * 2;

  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  roundRect(ctx, px + inset, py + inset + size * 0.06, w, w, w * 0.28);
  ctx.fill();

  ctx.fillStyle = owner.color;
  roundRect(ctx, px + inset, py + inset, w, w, w * 0.28);
  ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.45)';
  ctx.lineWidth = Math.max(1, size / 24);
  ctx.stroke();

  if (size >= 16) {
    ctx.fillStyle = '#fff';
    ctx.font = 'bold ' + Math.round(size * 0.34) + 'px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(UNIT_ABBR[unit.type] || '?', px + size / 2, py + size / 2);
  }

  // Damaged units carry a bar; full-health ones stay clean.
  if (unit.hp !== undefined && unit.hp < 100 * HP_SCALE && size >= 12) {
    const frac = Math.max(0, unit.hp / (100 * HP_SCALE));
    const barY = py + size - inset * 0.9;
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.fillRect(px + inset, barY, w, size * 0.09);
    ctx.fillStyle = frac > 0.5 ? '#6ad06a' : (frac > 0.25 ? '#e0c93c' : '#e05a5a');
    ctx.fillRect(px + inset, barY, w * frac, size * 0.09);
  }
}

/**
 * Draw `doc` onto `ctx`.
 *
 * opts: { size, originX, originY, width, height, grid, units, glyphs }
 *
 * `width`/`height` are the visible area in the same logical units as `size`.
 * They default to the canvas backing store, which is only correct when it is
 * not scaled for device pixel ratio - so a HiDPI caller passes them.
 */
export function drawMap(ctx, doc, opts = {}) {
  const size = opts.size || 24;
  const ox = opts.originX || 0;
  const oy = opts.originY || 0;
  const { cols, rows } = doc.size;
  const cells = cellIndex(doc);

  // Only draw what is actually on screen. A 40x30 map is 1200 tiles; a future
  // 100x100 would be 10000, and panning should stay smooth either way.
  const vw = opts.width !== undefined ? opts.width : ctx.canvas.width;
  const vh = opts.height !== undefined ? opts.height : ctx.canvas.height;
  const x0 = Math.max(0, Math.floor(-ox / size));
  const y0 = Math.max(0, Math.floor(-oy / size));
  const x1 = Math.min(cols, Math.ceil((vw - ox) / size));
  const y1 = Math.min(rows, Math.ceil((vh - oy) / size));

  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      drawTile(ctx, doc, cells, x, y, ox + x * size, oy + y * size, size, opts);
    }
  }

  if (opts.grid !== false && size >= 8) {
    ctx.strokeStyle = GRID_LINE;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = x0; x <= x1; x++) {
      ctx.moveTo(Math.round(ox + x * size) + 0.5, oy + y0 * size);
      ctx.lineTo(Math.round(ox + x * size) + 0.5, oy + y1 * size);
    }
    for (let y = y0; y <= y1; y++) {
      ctx.moveTo(ox + x0 * size, Math.round(oy + y * size) + 0.5);
      ctx.lineTo(ox + x1 * size, Math.round(oy + y * size) + 0.5);
    }
    ctx.stroke();
  }

  if (opts.units !== false) {
    for (const u of doc.units || []) {
      if (u.x < x0 || u.x >= x1 || u.y < y0 || u.y >= y1) continue;
      drawUnit(ctx, u, ox + u.x * size, oy + u.y * size, size);
    }
  }
}

/** Render a whole map into a fresh canvas, sized to fit. Used for thumbnails. */
export function thumbnail(doc, width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const size = fitTile(doc, width, height);
  const ctx = canvas.getContext('2d');
  drawMap(ctx, doc, {
    size,
    originX: Math.floor((width - size * doc.size.cols) / 2),
    originY: Math.floor((height - size * doc.size.rows) / 2),
    grid: false, glyphs: false,
  });
  return canvas;
}

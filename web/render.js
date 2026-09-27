// Map renderer.
//
// Pure drawing: give it a 2D context and a map document (the JSON the CLI
// exports) and it draws. No DOM lookups, no globals, no editing state - so the
// editor and the archive's thumbnail generator can share it unchanged.
//
// The JSON is row-major: terrain[y][x]. The save is column-major; the schema
// module owns that transpose, and nothing here needs to know about it.

import { terrain, team, UNIT_ABBR, HP_SCALE } from './terrain.js';
import { TERRAIN_ICONS, PROPERTY_ICONS, UNIT_ICONS } from './icons.js';
import { spriteFor } from './sprites.js';

const GRID_LINE = 'rgba(0,0,0,0.13)';

// Below this a tile is a few pixels across and an icon is mud; flat colour
// reads better, which is also what thumbnails want.
const ICON_MIN = 13;
const LABEL_MIN = 16;

/**
 * Ink that will actually be visible on `hex`.
 *
 * White-on-everything fails twice here: a neutral property is light grey, and
 * Yellow Comet is a light yellow. Both washed out completely.
 */
function inkFor(hex, alpha = 0.95) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  // Rec. 601 luma is good enough to choose between two inks.
  const luma = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luma > 0.62 ? 'rgba(22,22,26,' + alpha + ')'
                     : 'rgba(255,255,255,' + alpha + ')';
}

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

/**
 * Blit a pack sprite, bottom-aligned to the tile.
 *
 * Art taller than one tile overhangs upward - buildings and mountains do -
 * so the destination grows above `py` rather than below it.
 */
function blit(ctx, sprite, px, py, size) {
  const smooth = ctx.imageSmoothingEnabled;
  ctx.imageSmoothingEnabled = false;
  const h = Math.ceil(size * sprite.tall);
  ctx.drawImage(sprite.image, sprite.sx, sprite.sy, sprite.sw, sprite.sh,
                Math.round(px), Math.round(py + size - h),
                Math.ceil(size), h);
  ctx.imageSmoothingEnabled = smooth;
}

/**
 * Which sides a tile visually joins, as "N+E+S+W" in the order packs name it.
 *
 * Display only. The authoritative connection rule is autotile.py, which owns
 * the flags actually written to a save; this exists so a sprite pack can offer
 * a variant per junction and nothing here ever reaches a file.
 */
const VISUAL_LINKS = {
  128: new Set([128, 256]),          // road joins road and bridge
  256: new Set([256, 128]),          // and a bridge joins back
};

function dirsFor(terrain, x, y, id) {
  const links = VISUAL_LINKS[id];
  if (!links) return '';
  const at = (dx, dy) => {
    const ny = y + dy, nx = x + dx;
    return (ny >= 0 && ny < terrain.length && nx >= 0 && nx < terrain[0].length)
      ? terrain[ny][nx] : null;
  };
  const out = [];
  if (links.has(at(0, -1))) out.push('N');
  if (links.has(at(1, 0))) out.push('E');
  if (links.has(at(0, 1))) out.push('S');
  if (links.has(at(-1, 0))) out.push('W');
  return out.join('+');
}

/** A stable per-tile choice, so decoration does not flicker between redraws. */
function variantFor(x, y) {
  return Math.abs((x * 73856093) ^ (y * 19349663)) % 997;
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

  const owner = team(cell ? cell.team : null);

  // Fill first, always. Sprite packs commonly draw terrain as a transparent
  // overlay meant to sit on a base tile, and blitting one onto a cleared
  // canvas leaves black holes where the sprite is transparent.
  if (info.property) {
    // A property is drawn in its owner's colour; that ownership is most of
    // what makes a map readable at a glance.
    ctx.fillStyle = owner.color;
    ctx.fillRect(px, py, size, size);
  } else {
    ctx.fillStyle = info.base || info.color;
    ctx.fillRect(px, py, size, size);
  }

  const sprite = spriteFor(info.property ? 'property' : 'terrain', id, {
    team: cell ? cell.team : null,
    dirs: dirsFor(doc.terrain, x, y, id),
    variant: variantFor(x, y),
  });
  if (sprite) {
    blit(ctx, sprite, px, py, size);
    return;
  }

  if (info.property && id === 512 && size >= 10) {
    // HQs get a ring so they stand out from cities at thumbnail sizes.
    ctx.strokeStyle = 'rgba(255,255,255,0.85)';
    ctx.lineWidth = Math.max(1, size / 12);
    ctx.strokeRect(px + size * 0.18, py + size * 0.18, size * 0.64, size * 0.64);
  }

  if (!opts.glyphs || size < 12) return;

  const icon = info.property ? PROPERTY_ICONS[id] : TERRAIN_ICONS[id];
  const ink = info.property
    ? inkFor(team(cell ? cell.team : null).color, 0.93)
    : 'rgba(0,0,0,0.52)';
  if (icon && size >= ICON_MIN) {
    ctx.save();
    icon(ctx, px, py, size, ink);
    ctx.restore();
    return;
  }
  // No icon for this terrain, or too small to draw one: fall back to a letter.
  if (info.glyph) {
    ctx.fillStyle = ink;
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

  const sprite = spriteFor('unit', unit.type, { team: unit.team });
  if (sprite) {
    blit(ctx, sprite, px, py, size);
    drawHealth(ctx, unit, px, py, size, inset, w);
    return;
  }

  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  roundRect(ctx, px + inset, py + inset + size * 0.06, w, w, w * 0.28);
  ctx.fill();

  ctx.fillStyle = owner.color;
  roundRect(ctx, px + inset, py + inset, w, w, w * 0.28);
  ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.45)';
  ctx.lineWidth = Math.max(1, size / 24);
  ctx.stroke();

  const icon = UNIT_ICONS[unit.type];
  if (icon && size >= ICON_MIN) {
    ctx.save();
    // Inset so the silhouette sits inside the counter rather than on its edge.
    icon(ctx, px + size * 0.12, py + size * 0.12, size * 0.76, inkFor(owner.color));
    ctx.restore();
  } else if (size >= LABEL_MIN) {
    ctx.fillStyle = inkFor(owner.color);
    ctx.font = 'bold ' + Math.round(size * 0.34) + 'px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(UNIT_ABBR[unit.type] || '?', px + size / 2, py + size / 2);
  }

  drawHealth(ctx, unit, px, py, size, inset, w);
}

// Damaged units carry a bar; full-health ones stay clean.
function drawHealth(ctx, unit, px, py, size, inset, w) {
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

  // One row past the bottom, because two-tile art paints upward into view.
  const yDraw = Math.min(rows, y1 + 1);
  for (let y = y0; y < yDraw; y++) {
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

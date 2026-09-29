// Editing operations over a map document.
//
// Separate from render.js on purpose: the renderer is shared with archive
// thumbnails and must not carry editing state. Everything here mutates the
// plain JSON document, so what you edit is exactly what gets exported.
//
// Flags are deliberately NOT maintained here. The autotile rule lives in
// awrbc/core/autotile.py, and `schema.from_json` derives flags when the JSON
// omits them. Reimplementing it in JavaScript would mean two copies drifting
// apart, and the editor does not need flags for anything - it renders from
// terrain ids.

import { TERRAIN, PRODUCTION, CAPTURABLE, DIRECTIONAL, BREAKABLE_HP,
         MULTI_TILE, STRUCTURE_SPAN, STRUCTURE_HP_AT,
         UNIT_STATS, HP_SCALE } from './terrain.js';

const UNDO_LIMIT = 80;

export function emptyMap(cols, rows, name = 'Untitled') {
  return {
    schema: 1, name, author: 'anonymous',
    size: { cols, rows }, fog: false, waterColor: 0,
    terrain: Array.from({ length: rows }, () => Array(cols).fill(1)),
    cells: [], units: [],
  };
}

export function createEditor(doc, onChange) {
  const undo = [];
  const redo = [];
  let pending = null;

  function snapshot() {
    // `size` belongs here: undoing a resize has to put the dimensions back as
    // well as the grid, or the two disagree and every lookup is off.
    return JSON.stringify({
      size: doc.size, terrain: doc.terrain, cells: doc.cells, units: doc.units,
    });
  }

  function restore(s) {
    const o = JSON.parse(s);
    doc.size = o.size;
    doc.terrain = o.terrain;
    doc.cells = o.cells;
    doc.units = o.units;
  }

  /** Group a drag into one undo step: begin on pointerdown, commit on up. */
  function begin() {
    if (pending === null) pending = snapshot();
  }

  function commit() {
    if (pending === null) return;
    if (pending !== snapshot()) {
      undo.push(pending);
      if (undo.length > UNDO_LIMIT) undo.shift();
      redo.length = 0;
      onChange();
    }
    pending = null;
  }

  function inside(x, y) {
    return x >= 0 && y >= 0 && x < doc.size.cols && y < doc.size.rows;
  }

  function cellAt(x, y, create) {
    let c = doc.cells.find((c) => c.x === x && c.y === y);
    if (!c && create) { c = { x, y }; doc.cells.push(c); }
    return c;
  }

  function dropCell(x, y) {
    const i = doc.cells.findIndex((c) => c.x === x && c.y === y);
    if (i >= 0) doc.cells.splice(i, 1);
  }

  /** The top-left tile of the structure covering (x, y), or null. */
  function anchorOf(x, y) {
    if (!inside(x, y) || !MULTI_TILE.has(doc.terrain[y][x])) return null;
    const c = cellAt(x, y, false);
    const off = (c && c.offset) || [0, 0];
    return [x - off[0], y - off[1]];
  }

  /**
   * Remove the whole structure covering (x, y).
   *
   * Clearing one tile of a 3x3 and leaving the rest would produce eight
   * orphaned body tiles - a structure the game would read as broken - so any
   * edit that touches one takes all nine.
   */
  function clearStructure(x, y) {
    const at = anchorOf(x, y);
    if (!at) return false;
    for (let dy = 0; dy < STRUCTURE_SPAN; dy++) {
      for (let dx = 0; dx < STRUCTURE_SPAN; dx++) {
        const tx = at[0] + dx, ty = at[1] + dy;
        if (!inside(tx, ty)) continue;
        doc.terrain[ty][tx] = 1;
        dropCell(tx, ty);
      }
    }
    return true;
  }

  return {
    doc,
    begin,
    commit,
    anchorOf,

    /**
     * Place a 3x3 structure with its top-left at (x, y).
     *
     * Refuses rather than clipping when it will not fit, because a partial
     * structure is worse than none.
     */
    placeStructure(x, y, type, facing) {
      const span = STRUCTURE_SPAN;
      if (x < 0 || y < 0 ||
          x + span > doc.size.cols || y + span > doc.size.rows) {
        return false;
      }
      // Anything already here goes, including other structures in the way.
      for (let dy = 0; dy < span; dy++) {
        for (let dx = 0; dx < span; dx++) clearStructure(x + dx, y + dy);
      }
      for (let dy = 0; dy < span; dy++) {
        for (let dx = 0; dx < span; dx++) {
          doc.terrain[y + dy][x + dx] = type;
          dropCell(x + dx, y + dy);
          const c = cellAt(x + dx, y + dy, true);
          c.team = -1;
          if (dx || dy) c.offset = [dx, dy];
          else c.facing = facing || 'N';
          if (dx === STRUCTURE_HP_AT[0] && dy === STRUCTURE_HP_AT[1]) c.hp = 99;
        }
      }
      return true;
    },

    canUndo: () => undo.length > 0,
    canRedo: () => redo.length > 0,

    undo() {
      if (!undo.length) return;
      redo.push(snapshot());
      restore(undo.pop());
      onChange();
    },

    redo() {
      if (!redo.length) return;
      undo.push(snapshot());
      restore(redo.pop());
      onChange();
    },

    paint(x, y, type, team, facing) {
      if (MULTI_TILE.has(type)) return this.placeStructure(x, y, type, facing);
      // Painting over any part of a structure removes all of it.
      if (inside(x, y)) clearStructure(x, y);
      if (!inside(x, y) || doc.terrain[y][x] === type) {
        // Still allow re-owning, or re-aiming, the same thing.
        if (!inside(x, y) || !(CAPTURABLE.has(type) || DIRECTIONAL.has(type))) {
          return false;
        }
      }
      doc.terrain[y][x] = type;
      if (CAPTURABLE.has(type)) {
        const c = cellAt(x, y, true);
        c.team = team === undefined || team === null ? -1 : team;
        if (c.capture === undefined) c.capture = 20;
      } else if (DIRECTIONAL.has(type) || BREAKABLE_HP[type]) {
        // A cannon records which way it aims, and a breakable structure its
        // hit points. Both live on the cell, not in the terrain grid.
        const c = cellAt(x, y, true);
        c.team = -1;
        delete c.capture;
        delete c.offset;
        if (DIRECTIONAL.has(type)) c.facing = facing || 'N';
        else delete c.facing;
        if (BREAKABLE_HP[type]) c.hp = BREAKABLE_HP[type];
        else delete c.hp;
      } else {
        // Ownership and capture progress are meaningless on open terrain, and
        // leaving them behind is how a save ends up with an owned plain.
        dropCell(x, y);
      }
      return true;
    },

    /** Flood fill the contiguous region of like terrain at (x, y). */
    fill(x, y, type, team, facing) {
      if (!inside(x, y)) return false;
      const from = doc.terrain[y][x];
      if (from === type) return false;
      const queue = [[x, y]];
      const seen = new Set();
      while (queue.length) {
        const [cx, cy] = queue.pop();
        const key = cx + ',' + cy;
        if (seen.has(key) || !inside(cx, cy) || doc.terrain[cy][cx] !== from) continue;
        seen.add(key);
        this.paint(cx, cy, type, team, facing);
        queue.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
      }
      return true;
    },

    setTeam(x, y, team) {
      if (!inside(x, y)) return false;
      const type = doc.terrain[y][x];
      const unit = doc.units.find((u) => u.x === x && u.y === y);
      // A unit cannot go neutral, so leave it alone rather than corrupt it.
      if (unit && team !== null && team >= 0) unit.team = team;
      if (!CAPTURABLE.has(type)) return !!unit;
      const c = cellAt(x, y, true);
      c.team = team === null ? -1 : team;
      if (c.capture === undefined) c.capture = 20;
      return true;
    },

    placeUnit(x, y, type, team) {
      // Every unit belongs to an army. There is no neutral side to own one,
      // and silently reassigning a neutral brush to Orange Star was worse
      // than refusing.
      if (!inside(x, y) || team === null || team === undefined || team < 0) {
        return false;
      }
      const stats = UNIT_STATS[type] || { gas: 99, ammo: 0 };
      const existing = doc.units.find((u) => u.x === x && u.y === y);
      const unit = existing || { x, y };
      unit.type = type;
      unit.team = team === null || team === undefined ? 0 : team;
      unit.hp = 100 * HP_SCALE;
      unit.gas = stats.gas;
      unit.ammo = stats.ammo;
      if (!existing) doc.units.push(unit);
      return true;
    },

    removeUnit(x, y) {
      const i = doc.units.findIndex((u) => u.x === x && u.y === y);
      if (i < 0) return false;
      doc.units.splice(i, 1);
      return true;
    },

    /**
     * Change the grid size, keeping the top-left corner fixed.
     *
     * Growing fills with plains; shrinking drops whatever falls outside,
     * including the cells and units on those tiles - leaving them behind is
     * how a map ends up with a unit nobody can see.
     */
    resize(cols, rows) {
      if (!(cols > 0 && rows > 0)) return false;
      if (cols === doc.size.cols && rows === doc.size.rows) return false;
      begin();
      const old = doc.terrain;
      doc.terrain = Array.from({ length: rows }, (_, y) =>
        Array.from({ length: cols }, (_, x) =>
          (y < old.length && x < old[0].length) ? old[y][x] : 1));
      doc.size = { cols, rows };
      doc.cells = doc.cells.filter((c) => c.x < cols && c.y < rows);
      doc.units = doc.units.filter((u) => u.x < cols && u.y < rows);
      commit();
      return true;
    },
  };
}

/**
 * Per-team counts and whether the map is playable.
 *
 * The authoritative rule is `Map.is_playable` in awrbc/core/model.py: every
 * team needs an HQ, and at least one unit or one production property. This is
 * a copy so the editor can show it live; keep the two in step.
 */
export function stats(doc) {
  const perTeam = {};
  const need = (t) => (perTeam[t] = perTeam[t] ||
    { hq: 0, production: 0, properties: 0, units: 0 });

  for (const c of doc.cells || []) {
    if (c.team === undefined || c.team === null || c.team < 0) continue;
    const type = doc.terrain[c.y] && doc.terrain[c.y][c.x];
    if (!CAPTURABLE.has(type)) continue;
    const s = need(c.team);
    s.properties++;
    if (type === 512) s.hq++;
    if (PRODUCTION.has(type)) s.production++;
  }
  for (const u of doc.units || []) need(u.team).units++;

  const teams = Object.keys(perTeam).map(Number).sort();
  const reasons = [];
  for (const t of teams) {
    const s = perTeam[t];
    if (!s.hq) reasons.push('team ' + t + ' has no HQ');
    else if (!s.units && !s.production) reasons.push('team ' + t + ' has no units or production');
  }
  if (teams.length < 2) reasons.push('needs at least two armies');

  return { valid: reasons.length === 0, teams, perTeam, reasons };
}

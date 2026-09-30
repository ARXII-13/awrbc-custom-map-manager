// Repairs for problems that are easier to fix in a pass than to prevent while
// painting.
//
// Some faults only exist in the shape of the finished map. A river is not too
// wide until the tile that makes it too wide is placed, and refusing that
// stroke would be maddening. So the editor lets you draw, then offers to put
// it right.
//
// Every repair here states what it will change before it runs, applies as one
// undo step, and is skippable. None of them runs on its own.

const RIVER = 16;
const SEA = 2;
const PLAINS = 1;

/** Tiles belonging to a 2x2 or larger block of river. */
function wideRiverTiles(doc) {
  const { cols, rows } = doc.size;
  const found = new Set();
  for (let y = 0; y < rows - 1; y++) {
    for (let x = 0; x < cols - 1; x++) {
      if (doc.terrain[y][x] === RIVER && doc.terrain[y][x + 1] === RIVER &&
          doc.terrain[y + 1][x] === RIVER && doc.terrain[y + 1][x + 1] === RIVER) {
        found.add(x + "," + y);
        found.add((x + 1) + "," + y);
        found.add(x + "," + (y + 1));
        found.add((x + 1) + "," + (y + 1));
      }
    }
  }
  return [...found].map((k) => k.split(",").map(Number));
}

/** Structure tiles whose 3x3 is not whole - an anchor missing, or a hole. */
function brokenStructureTiles(doc, multiTile, span) {
  const { cols, rows } = doc.size;
  const cells = new Map();
  for (const c of doc.cells || []) cells.set(c.x + "," + c.y, c);
  const bad = [];
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const kind = doc.terrain[y][x];
      if (!multiTile.has(kind)) continue;
      const c = cells.get(x + "," + y);
      const off = (c && c.offset) || [0, 0];
      const ax = x - off[0], ay = y - off[1];
      let whole = ax >= 0 && ay >= 0 && ax + span <= cols && ay + span <= rows;
      if (whole) {
        for (let dy = 0; dy < span && whole; dy++) {
          for (let dx = 0; dx < span && whole; dx++) {
            const other = doc.terrain[ay + dy][ax + dx];
            const oc = cells.get((ax + dx) + "," + (ay + dy));
            const ooff = (oc && oc.offset) || [0, 0];
            if (other !== kind || ooff[0] !== dx || ooff[1] !== dy) whole = false;
          }
        }
      }
      if (!whole) bad.push([x, y]);
    }
  }
  return bad;
}

/**
 * Repairs that apply to this map, each with what it would do.
 *
 * `apply(ed)` performs it through the editor, so it lands on the undo stack
 * like anything else and can be taken back.
 */
export function available(doc, { MULTI_TILE, STRUCTURE_SPAN }) {
  const out = [];

  const wide = wideRiverTiles(doc);
  if (wide.length) {
    out.push({
      code: "river.wide",
      label: "Turn wide river into sea",
      detail: wide.length + " river tile" + (wide.length === 1 ? "" : "s") +
        " sit in a band more than one tile across. The game has no art for the " +
        "middle of a river, so they render as blocks. In Advance Wars a " +
        "waterway that wide is sea.\n\nThis changes who can cross: a river is " +
        "passable only by infantry and mech, sea carries ships.",
      apply(ed) {
        for (const [x, y] of wide) ed.paint(x, y, SEA, -1);
        return wide.length;
      },
    });
  }

  const broken = brokenStructureTiles(doc, MULTI_TILE, STRUCTURE_SPAN);
  if (broken.length) {
    out.push({
      code: "structure.incomplete",
      label: "Clear broken structures",
      detail: broken.length + " tile" + (broken.length === 1 ? "" : "s") +
        " belong to a cannon or death ray that is missing part of itself. The " +
        "game reads that as a broken object.\n\nThey will be cleared to plains.",
      apply(ed) {
        for (const [x, y] of broken) ed.paint(x, y, PLAINS, -1);
        return broken.length;
      },
    });
  }

  return out;
}

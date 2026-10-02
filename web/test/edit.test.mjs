// Editing operations.
//
// Run with `node --test web/test/` from the repository root.
//
// These exist because the editor once ran dead for five commits without
// anything noticing: a string literal broke the inline script, nothing
// executed, and the only check in place asked whether a button existed in the
// HTML - which it did. `tests/test_editor_syntax.py` now catches that class of
// break. This catches the quieter one, where the code runs and does the wrong
// thing.
//
// `edit.js` touches no DOM, which is deliberate (decision #48) and is what
// makes this possible with no dependency and no browser.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { createEditor, emptyMap, stats } from '../edit.js';
import {
  CAPTURABLE, MULTI_TILE, STRUCTURE_SPAN, MAX_UNITS_PER_TEAM,
} from '../terrain.js';

const PLAINS = 1;
const SEA = 2;
const WOODS = 8;
const RIVER = 16;
const HQ = 512;
const CITY = 1024;
const BASE = 2048;
const BLACK_CANNON = 524288;
const INFANTRY = 1;

/**
 * A map with one HQ per army and nothing else.
 *
 * Deliberately *not* playable: the rule is an HQ **and** a way to act, so this
 * is the floor to build on rather than a valid map. Naming it `playable` was
 * the first thing these tests caught.
 */
function withHQs(cols = 12, rows = 10, teams = 2) {
  const doc = emptyMap(cols, rows, 'Test');
  const ed = createEditor(doc, () => {});
  const spots = [[0, 0], [cols - 1, rows - 1], [0, rows - 1], [cols - 1, 0]];
  for (let t = 0; t < teams; t++) {
    const [x, y] = spots[t];
    ed.begin();
    ed.paint(x, y, HQ, t);
    ed.commit();
  }
  return { doc, ed };
}

function cellAt(doc, x, y) {
  return (doc.cells || []).find((c) => c.x === x && c.y === y);
}

describe('a new map', () => {
  it('is all plains and has no cells or units', () => {
    const doc = emptyMap(5, 4);
    assert.equal(doc.size.cols, 5);
    assert.equal(doc.size.rows, 4);
    assert.equal(doc.terrain.length, 4, 'terrain is indexed [y][x]');
    assert.equal(doc.terrain[0].length, 5);
    assert.ok(doc.terrain.every((row) => row.every((t) => t === PLAINS)));
    assert.deepEqual(doc.cells, []);
    assert.deepEqual(doc.units, []);
  });

  it('is not playable, and says why', () => {
    const s = stats(emptyMap(10, 10));
    assert.equal(s.valid, false);
    assert.ok(s.reasons.length > 0);
  });
});

describe('painting', () => {
  it('changes the tile', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.paint(5, 5, WOODS, -1);
    ed.commit();
    assert.equal(doc.terrain[5][5], WOODS);
  });

  it('ignores anything outside the map', () => {
    const { doc, ed } = withHQs(6, 6);
    ed.begin();
    assert.doesNotThrow(() => {
      ed.paint(-1, 0, WOODS, -1);
      ed.paint(0, -1, WOODS, -1);
      ed.paint(6, 0, WOODS, -1);
      ed.paint(0, 6, WOODS, -1);
    });
    ed.commit();
    assert.equal(doc.terrain.length, 6);
  });

  it('gives a capturable tile its owner, and plain terrain none', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.paint(3, 3, CITY, 1);
    ed.paint(4, 4, WOODS, 1);
    ed.commit();
    assert.equal(cellAt(doc, 3, 3).team, 1);
    const woods = cellAt(doc, 4, 4);
    assert.ok(woods === undefined || woods.team < 0,
      'plain terrain must not carry an owner');
  });

  it('does not leave the old tile\'s data on the new one', () => {
    // This is the bug that changed a map's content hash: painting a City over
    // a cannon kept the cannon's hp and facing.
    const { doc, ed } = withHQs(12, 12);
    ed.begin();
    ed.placeStructure(4, 4, BLACK_CANNON, 'S');
    ed.commit();
    ed.begin();
    ed.paint(4, 4, CITY, 0);
    ed.commit();

    const c = cellAt(doc, 4, 4);
    assert.equal(doc.terrain[4][4], CITY);
    assert.equal(c.hp, undefined, 'hp belonged to the cannon');
    assert.equal(c.facing, undefined, 'facing belonged to the cannon');
    assert.equal(c.offset, undefined, 'offset belonged to the cannon');
  });
});

describe('undo', () => {
  it('takes back a whole stroke, not one tile', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    for (let x = 2; x < 8; x++) ed.paint(x, 5, WOODS, -1);
    ed.commit();
    assert.equal(doc.terrain[5][4], WOODS);

    ed.undo();
    for (let x = 2; x < 8; x++) {
      assert.equal(doc.terrain[5][x], PLAINS, `tile ${x} should be back`);
    }
  });

  it('redoes what it undid', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.paint(5, 5, SEA, -1);
    ed.commit();
    ed.undo();
    assert.equal(doc.terrain[5][5], PLAINS);
    ed.redo();
    assert.equal(doc.terrain[5][5], SEA);
  });

  it('knows when there is nothing to undo', () => {
    const { ed } = withHQs();
    while (ed.canUndo()) ed.undo();
    assert.equal(ed.canUndo(), false);
    assert.doesNotThrow(() => ed.undo(), 'undo past the end must not throw');
  });

  it('drops the redo stack once you paint again', () => {
    const { doc, ed } = withHQs();
    ed.begin(); ed.paint(5, 5, SEA, -1); ed.commit();
    ed.undo();
    ed.begin(); ed.paint(6, 6, WOODS, -1); ed.commit();
    assert.equal(ed.canRedo(), false);
    assert.equal(doc.terrain[5][5], PLAINS, 'the undone stroke stays undone');
  });

  it('restores units, not just terrain', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.placeUnit(3, 3, INFANTRY, 0);
    ed.commit();
    assert.equal(doc.units.length, 1);
    ed.undo();
    assert.equal(doc.units.length, 0);
  });
});

describe('units', () => {
  it('places and removes one', () => {
    const { doc, ed } = withHQs();
    ed.begin(); ed.placeUnit(2, 2, INFANTRY, 0); ed.commit();
    assert.equal(doc.units.length, 1);
    assert.equal(doc.units[0].team, 0);

    ed.begin();
    assert.equal(ed.removeUnit(2, 2), true);
    ed.commit();
    assert.equal(doc.units.length, 0);
  });

  it('says so when there is nothing to remove', () => {
    const { ed } = withHQs();
    ed.begin();
    assert.equal(ed.removeUnit(7, 7), false);
    ed.commit();
  });

  it('never stacks two units on one tile', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.placeUnit(2, 2, INFANTRY, 0);
    ed.placeUnit(2, 2, INFANTRY, 1);
    ed.commit();
    assert.equal(doc.units.length, 1, 'the second replaces the first');
    assert.equal(doc.units[0].team, 1);
  });
});

describe('structures', () => {
  it('fills a 3x3 and marks the anchor', () => {
    const { doc, ed } = withHQs(12, 12);
    ed.begin();
    assert.equal(ed.placeStructure(4, 4, BLACK_CANNON, 'E'), true);
    ed.commit();

    let covered = 0;
    for (let dy = 0; dy < STRUCTURE_SPAN; dy++) {
      for (let dx = 0; dx < STRUCTURE_SPAN; dx++) {
        assert.equal(doc.terrain[4 + dy][4 + dx], BLACK_CANNON);
        covered++;
      }
    }
    assert.equal(covered, STRUCTURE_SPAN * STRUCTURE_SPAN);
    assert.equal(cellAt(doc, 4, 4).facing, 'E', 'the anchor carries the facing');
    assert.deepEqual(cellAt(doc, 5, 4).offset, [1, 0]);
  });

  it('refuses rather than clipping at an edge', () => {
    const { doc, ed } = withHQs(12, 12);
    ed.begin();
    assert.equal(ed.placeStructure(10, 10, BLACK_CANNON, 'N'), false,
      'a partial structure is worse than none');
    ed.commit();
    assert.equal(doc.terrain[10][10], PLAINS);
  });

  it('is neutral, whatever is selected', () => {
    // The game stores a team on a cannon and then ignores it (decision #42).
    const { doc, ed } = withHQs(12, 12);
    ed.begin();
    ed.placeStructure(4, 4, BLACK_CANNON, 'N');
    ed.commit();
    for (let dy = 0; dy < STRUCTURE_SPAN; dy++) {
      for (let dx = 0; dx < STRUCTURE_SPAN; dx++) {
        assert.equal(cellAt(doc, 4 + dx, 4 + dy).team, -1);
      }
    }
  });

  it('clears the whole of a structure it paints over', () => {
    const { doc, ed } = withHQs(14, 14);
    ed.begin(); ed.placeStructure(2, 2, BLACK_CANNON, 'N'); ed.commit();
    ed.begin(); ed.placeStructure(3, 3, BLACK_CANNON, 'S'); ed.commit();

    // The first cannon's tiles must not survive as orphans.
    let orphans = 0;
    for (let y = 0; y < 14; y++) {
      for (let x = 0; x < 14; x++) {
        if (!MULTI_TILE.has(doc.terrain[y][x])) continue;
        const c = cellAt(doc, x, y);
        const off = (c && c.offset) || [0, 0];
        const ax = x - off[0];
        const ay = y - off[1];
        if (ax !== 3 || ay !== 3) orphans++;
      }
    }
    assert.equal(orphans, 0, 'tiles left behind by the overwritten cannon');
  });
});

describe('resize', () => {
  it('keeps what still fits and fills the rest with plains', () => {
    const { doc, ed } = withHQs(10, 10);
    ed.begin(); ed.paint(2, 2, WOODS, -1); ed.commit();
    ed.begin(); ed.resize(14, 12); ed.commit();

    assert.equal(doc.size.cols, 14);
    assert.equal(doc.terrain.length, 12);
    assert.equal(doc.terrain[2][2], WOODS, 'existing terrain survives');
    assert.equal(doc.terrain[11][13], PLAINS, 'new ground is plains');
  });

  it('drops what falls outside, cells and units alike', () => {
    const { doc, ed } = withHQs(12, 10);
    ed.begin();
    ed.paint(11, 9, CITY, 0);
    ed.placeUnit(10, 8, INFANTRY, 0);
    ed.commit();

    ed.begin(); ed.resize(6, 6); ed.commit();
    assert.equal(doc.terrain.length, 6);
    assert.ok(doc.terrain.every((row) => row.length === 6));
    assert.equal(cellAt(doc, 11, 9), undefined, 'a cell outside must be gone');
    assert.ok(doc.units.every((u) => u.x < 6 && u.y < 6),
      'a unit outside must be gone');
  });

  it('is one undo step', () => {
    const { doc, ed } = withHQs(10, 10);
    ed.begin(); ed.resize(20, 20); ed.commit();
    ed.undo();
    assert.equal(doc.size.cols, 10);
    assert.equal(doc.terrain.length, 10);
  });
});

describe('fill', () => {
  it('spreads over matching terrain and stops at a boundary', () => {
    const { doc, ed } = withHQs(8, 8);
    ed.begin();
    for (let y = 0; y < 8; y++) ed.paint(4, y, SEA, -1);   // a wall
    ed.commit();

    ed.begin(); ed.fill(0, 4, WOODS, -1); ed.commit();
    assert.equal(doc.terrain[4][0], WOODS);
    assert.equal(doc.terrain[4][3], WOODS, 'fills up to the wall');
    assert.equal(doc.terrain[4][4], SEA, 'does not cross it');
    assert.equal(doc.terrain[4][5], PLAINS, 'nor past it');
  });

  it('does nothing when the target already is that terrain', () => {
    const { doc, ed } = withHQs(8, 8);
    ed.begin(); ed.fill(4, 4, PLAINS, -1); ed.commit();
    assert.ok(doc.terrain.every((row) => row.every((t) =>
      t === PLAINS || t === HQ)));
  });
});

describe('stats', () => {
  it('needs an HQ *and* a way to act, not just an HQ', () => {
    const { doc, ed } = withHQs(12, 10, 2);
    assert.equal(stats(doc).valid, false,
      'two HQs and nothing else is not a playable map');

    ed.begin();
    ed.paint(3, 3, BASE, 0);
    ed.paint(8, 6, BASE, 1);
    ed.commit();

    const s = stats(doc);
    assert.equal(s.valid, true, s.reasons.join('; '));
    assert.deepEqual(s.teams.sort(), [0, 1]);
    assert.equal(s.perTeam[0].hq, 1);
  });

  it('refuses a one-army map however well equipped', () => {
    const { doc, ed } = withHQs(12, 10, 1);
    ed.begin();
    ed.paint(3, 3, BASE, 0);
    ed.placeUnit(4, 4, INFANTRY, 0);
    ed.commit();
    assert.equal(stats(doc).valid, false, 'one army is never a match');
  });

  it('counts production separately from properties', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    ed.paint(3, 3, BASE, 0);
    ed.paint(4, 3, CITY, 0);
    ed.commit();
    const s = stats(doc);
    assert.equal(s.perTeam[0].production, 1, 'a base produces, a city does not');
    assert.equal(s.perTeam[0].properties, 3, 'HQ + base + city');
  });

  it('notices an army over the unit cap', () => {
    const { doc, ed } = withHQs(20, 20);
    ed.begin();
    let placed = 0;
    for (let y = 0; y < 20 && placed <= MAX_UNITS_PER_TEAM; y++) {
      for (let x = 0; x < 20 && placed <= MAX_UNITS_PER_TEAM; x++) {
        if (doc.terrain[y][x] !== PLAINS) continue;
        ed.placeUnit(x, y, INFANTRY, 0);
        placed++;
      }
    }
    ed.commit();
    const s = stats(doc);
    const said = (s.reasons.concat(s.notes || [])).join(' ');
    assert.ok(/\b50\b|units/.test(said), `expected a unit-cap note, got: ${said}`);
  });

  it('ignores a team on terrain that cannot be owned', () => {
    // decision #42 - the game stores it and ignores it, so two maps differing
    // only there are the same map.
    const { doc, ed } = withHQs();
    ed.begin(); ed.paint(5, 5, RIVER, 1); ed.commit();
    const s = stats(doc);
    assert.equal(s.perTeam[1] === undefined || s.perTeam[1].properties === 1,
      true, 'a river must not count as team 1 property');
  });

  it('agrees with CAPTURABLE about what counts', () => {
    const { doc, ed } = withHQs();
    ed.begin();
    let n = 0;
    let x = 2;
    for (const type of CAPTURABLE) {
      if (type === HQ) continue;
      ed.paint(x++, 6, type, 0);
      n++;
    }
    ed.commit();
    assert.equal(stats(doc).perTeam[0].properties, n + 1, 'plus the HQ');
  });
});

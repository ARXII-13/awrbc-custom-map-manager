// The repairs offered after validation.
//
// These exist for faults that only appear in the shape of a finished map, so
// the editor lets you draw and then offers to put it right. Each repair has to
// be honest about what it will change before it runs - that is most of what is
// tested here.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { createEditor, emptyMap } from '../edit.js';
import { available } from '../fixes.js';
import { MULTI_TILE, STRUCTURE_SPAN } from '../terrain.js';

const PLAINS = 1;
const SEA = 2;
const RIVER = 16;
const BLACK_CANNON = 524288;

const OPTS = { MULTI_TILE, STRUCTURE_SPAN };

function blank(cols = 14, rows = 12) {
  const doc = emptyMap(cols, rows, 'Test');
  return { doc, ed: createEditor(doc, () => {}) };
}

function codes(doc) {
  return available(doc, OPTS).map((r) => r.code);
}

describe('a clean map', () => {
  it('is offered no repairs', () => {
    const { doc } = blank();
    assert.deepEqual(available(doc, OPTS), []);
  });

  it('is not bothered by a one-tile-wide river', () => {
    const { doc, ed } = blank();
    ed.begin();
    for (let x = 1; x < 10; x++) ed.paint(x, 5, RIVER, -1);
    ed.commit();
    assert.deepEqual(codes(doc), [], 'a river is meant to be one tile wide');
  });
});

describe('a river wider than one tile', () => {
  function withBlock() {
    const { doc, ed } = blank();
    ed.begin();
    for (let y = 4; y < 6; y++) {
      for (let x = 4; x < 6; x++) ed.paint(x, y, RIVER, -1);
    }
    ed.commit();
    return { doc, ed };
  }

  it('is offered as a repair', () => {
    assert.deepEqual(codes(withBlock().doc), ['river.wide']);
  });

  it('says what it will change before it runs', () => {
    const [fix] = available(withBlock().doc, OPTS);
    assert.ok(fix.detail.startsWith('4 '),
      `expected the count of tiles it will touch, got: ${fix.detail}`);
    // Turning a river into sea changes who can cross it. That is not a detail
    // to discover afterwards.
    assert.match(fix.detail, /infantry|sea|cross/i);
  });

  it('turns the block into sea when applied', () => {
    const { doc, ed } = withBlock();
    const [fix] = available(doc, OPTS);
    const n = fix.apply(ed);
    assert.equal(n, 4);
    for (let y = 4; y < 6; y++) {
      for (let x = 4; x < 6; x++) assert.equal(doc.terrain[y][x], SEA);
    }
    assert.deepEqual(codes(doc), [], 'and the map is clean afterwards');
  });

  it('finds every tile of a bigger block, not just the first 2x2', () => {
    const { doc, ed } = blank();
    ed.begin();
    for (let y = 3; y < 7; y++) {
      for (let x = 3; x < 7; x++) ed.paint(x, y, RIVER, -1);
    }
    ed.commit();
    const [fix] = available(doc, OPTS);
    assert.equal(fix.apply(ed), 16);
  });
});

describe('a structure missing part of itself', () => {
  // The editor cannot produce this. Painting over any tile of a structure
  // removes all nine, which is the same principle as placeStructure refusing
  // to clip at an edge: a partial structure is worse than none. The repair is
  // for maps that arrive broken - hand-edited JSON, or something built by
  // another tool - so these build that state directly.
  it('cannot be made by painting, which removes the whole structure', () => {
    const { doc, ed } = blank();
    ed.begin(); ed.placeStructure(4, 4, BLACK_CANNON, 'N'); ed.commit();
    ed.begin(); ed.paint(5, 5, PLAINS, -1); ed.commit();

    let left = 0;
    for (const row of doc.terrain) {
      for (const t of row) if (MULTI_TILE.has(t)) left++;
    }
    assert.equal(left, 0, 'one stroke must take the whole structure with it');
    assert.deepEqual(codes(doc), [], 'so there is nothing to repair');
  });

  function arrivedBroken() {
    const { doc, ed } = blank();
    ed.begin(); ed.placeStructure(4, 4, BLACK_CANNON, 'N'); ed.commit();
    // Reach past the editor, the way a hand-edited file would.
    doc.terrain[5][5] = PLAINS;
    doc.cells = doc.cells.filter((c) => !(c.x === 5 && c.y === 5));
    return { doc, ed };
  }

  it('is offered as a repair', () => {
    assert.ok(codes(arrivedBroken().doc).includes('structure.incomplete'));
  });

  it('says how many tiles it will clear', () => {
    const fix = available(arrivedBroken().doc, OPTS).find(
      (r) => r.code === 'structure.incomplete');
    assert.ok(fix.detail.includes('8 tiles'),
      `expected the count it will clear, got: ${fix.detail}`);
  });

  it('clears the orphaned tiles to plains', () => {
    const { doc, ed } = arrivedBroken();
    const fix = available(doc, OPTS).find(
      (r) => r.code === 'structure.incomplete');
    fix.apply(ed);
    for (let y = 0; y < 12; y++) {
      for (let x = 0; x < 14; x++) {
        assert.ok(!MULTI_TILE.has(doc.terrain[y][x]),
          `a structure tile survived at ${x},${y}`);
      }
    }
    assert.deepEqual(codes(doc), []);
  });

  it('leaves a whole structure alone', () => {
    const { doc, ed } = blank();
    ed.begin();
    ed.placeStructure(4, 4, BLACK_CANNON, 'N');
    ed.commit();
    assert.deepEqual(codes(doc), []);
  });
});

describe('applying a repair', () => {
  it('is one undo step', () => {
    const { doc, ed } = blank();
    ed.begin();
    for (let y = 4; y < 6; y++) {
      for (let x = 4; x < 6; x++) ed.paint(x, y, RIVER, -1);
    }
    ed.commit();

    const [fix] = available(doc, OPTS);
    ed.begin();
    fix.apply(ed);
    ed.commit();
    assert.equal(doc.terrain[4][4], SEA);

    ed.undo();
    assert.equal(doc.terrain[4][4], RIVER, 'a repair must be takeable back');
  });

  it('reports both faults when a map has both', () => {
    const { doc, ed } = blank();
    ed.begin();
    for (let y = 1; y < 3; y++) {
      for (let x = 1; x < 3; x++) ed.paint(x, y, RIVER, -1);
    }
    ed.placeStructure(6, 6, BLACK_CANNON, 'N');
    ed.commit();
    doc.terrain[7][7] = PLAINS;        // as a hand-edited file would arrive
    doc.cells = doc.cells.filter((c) => !(c.x === 7 && c.y === 7));

    assert.deepEqual(codes(doc).sort(),
      ['river.wide', 'structure.incomplete']);
  });
});

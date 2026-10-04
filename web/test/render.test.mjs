// Which sprite a tile asks for.
//
// `render.js` had no tests at all, and this is the part of it worth having
// them: a pure function over the terrain grid whose rule is different for
// every kind of terrain it knows about. Getting it wrong does not throw - the
// lookup falls back and the map just draws wrong, which is how a bridge once
// rendered ninety degrees out and how a pipe seam beside a cannon drew as
// though it joined nothing.
//
// Drawing itself needs a canvas and is not tested here.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { dirsFor, paletteDirs } from '../render.js';

const PLAIN = 1, SEA = 2, RIVER = 16, SHOAL = 32, REEF = 64;
const ROAD = 128, BRIDGE = 256, SEAPORT = 8192;
const PIPE = 32768, SEAM = 65536, CANNON = 524288;

/** A grid from a picture, so the shape of the case is visible in the test. */
function grid(rows) {
  const key = {
    '.': PLAIN, 's': SEA, 'r': RIVER, 'h': SHOAL, 'f': REEF,
    '=': ROAD, 'b': BRIDGE, 'p': SEAPORT, 'i': PIPE, 'w': SEAM, 'c': CANNON,
  };
  return rows.map((row) => [...row].map((ch) => key[ch]));
}

const at = (rows, x, y, id) => dirsFor(grid(rows), x, y, id);

describe('a shoreline', () => {
  it('names the sides facing land, not the sides joining water', () => {
    //  . . .
    //  . s s     the sea at (1,1) has land north and west
    //  . s s
    assert.equal(at(['...', '.ss', '.ss'], 1, 1, SEA), 'N+W');
  });

  it('names them in N, E, S, W order whatever shape the coast is', () => {
    assert.equal(at(['...', '.s.', '...'], 1, 1, SEA), 'N+E+S+W');
  });

  it('is empty for open water, which is the unsuffixed sprite', () => {
    assert.equal(at(['sss', 'sss', 'sss'], 1, 1, SEA), '');
  });

  it('treats the edge of the map as water, not as a coast', () => {
    // A map that stops is not a coastline. Counting it as land frames every
    // sea map in a beach it never asked for.
    assert.equal(at(['sss', 'sss', 'sss'], 0, 0, SEA), '');
    assert.equal(at(['sss', 'sss', 'sss'], 2, 2, SEA), '');
  });

  it('counts river, shoal, reef and bridge as water', () => {
    // They are all WATER in autotile.py, which is what writes the flags the
    // game reads. Drawing a beach against a river would disagree with it.
    assert.equal(at(['.r.', 'hsf', '.b.'], 1, 1, SEA), '');
  });

  it('counts a seaport as water from every side', () => {
    // It is really water only from the side its dock faces, and this cannot
    // see which side that is. A missing shore edge beside a port is a smaller
    // wrong than a shore edge on the side the dock is on.
    assert.equal(at(['.p.', 'sss', '...'], 1, 1, SEA), 'S');
  });

  it('draws a shore against a road or a building', () => {
    assert.equal(at(['.=.', 'sss', '...'], 1, 1, SEA), 'N+S');
  });
});

describe('terrain that connects', () => {
  it('names a road by the sides it joins', () => {
    assert.equal(at(['.=.', '===', '.=.'], 1, 1, ROAD), 'N+E+S+W');
  });

  it('lets a road join a bridge, and the bridge join back', () => {
    // A road running into a bridge has to meet it, or the two draw as
    // separate pieces with a seam between them.
    assert.equal(at(['...', '=b=', '...'], 0, 1, ROAD), 'E');
    assert.equal(at(['...', '=b=', '...'], 2, 1, ROAD), 'W');
  });

  it('names a bridge by its railings, which are the sides it does not join',
     () => {
    // Read as a connection list this turns every bridge ninety degrees, which
    // is exactly what it looked like.
    assert.equal(at(['...', '=b=', '...'], 1, 1, BRIDGE), 'N+S');
  });

  it('joins a pipe seam to what a pipe joins', () => {
    // A seam is a weld in a pipeline, not a different kind of thing. It used
    // to draw as though it joined nothing when a cannon was beside it.
    assert.equal(at(['.i.', 'cw.', '...'], 1, 1, SEAM), 'N+W');
  });
});

describe('terrain with no direction at all', () => {
  it('answers empty, so the lookup lands on the plain sprite', () => {
    assert.equal(at(['...', '...', '...'], 1, 1, PLAIN), '');
    assert.equal(at(['fff', 'fff', 'fff'], 1, 1, REEF), '');
  });
});

describe('what a palette swatch asks for', () => {
  it('shows linking terrain as a full junction', () => {
    assert.equal(paletteDirs(ROAD), 'N+E+S+W');
    assert.equal(paletteDirs(PIPE), 'N+E+S+W');
  });

  it('shows everything else the way a brush stroke paints it', () => {
    // Reef's suffixed files mean adjacent land, so a junction would advertise
    // a variant painting cannot produce.
    assert.equal(paletteDirs(REEF), '');
    assert.equal(paletteDirs(PLAIN), '');
  });

  it('does not ask a shoreline for a junction either', () => {
    // "N+E+S+W" on sea means a one-tile pond, which is a strange thing for a
    // palette to advertise.
    assert.equal(paletteDirs(SEA), '');
  });
});

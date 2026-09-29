// Terrain, team and unit tables.
//
// Shared by the editor and by archive thumbnail rendering, so this file holds
// data only - no drawing, no DOM. Ids come from docs/id-tables.md.
//
// Colours are flat originals, deliberately not sampled from the game. Keeping
// the renderer free of ripped assets is what makes the archive publishable.

export const TERRAIN = {
  1:         { name: 'Plains',       color: '#a9cf75' },
  2:         { name: 'Sea',          color: '#4577bd' },
  // `base` is what gets filled before a sprite is blitted. Packs often draw
  // trees and rock as transparent overlays meant to sit on grass.
  4:         { name: 'Mountain',     color: '#9b8259', base: '#a9cf75', glyph: '^' },
  8:         { name: 'Woods',        color: '#5d9647', base: '#a9cf75', glyph: '*' },
  16:        { name: 'River',        color: '#72b4dd' },
  32:        { name: 'Shoal',        color: '#e6d6a0' },
  64:        { name: 'Reef',         color: '#3c6ba3', base: '#4577bd', glyph: 'o' },
  128:       { name: 'Road',         color: '#cac4b2' },
  256:       { name: 'Bridge',       color: '#b5915f' },
  512:       { name: 'HQ',           property: true, glyph: 'H' },
  1024:      { name: 'City',         property: true, glyph: 'C' },
  2048:      { name: 'Base',         property: true, glyph: 'B' },
  4096:      { name: 'Airport',      property: true, glyph: 'A' },
  8192:      { name: 'Seaport',      property: true, glyph: 'P' },
  32768:     { name: 'Pipe',         color: '#868b95' },
  65536:     { name: 'Pipe Seam',    color: '#a7acb6' },
  524288:    { name: 'Black Cannon', color: '#484850', glyph: 'X' },
  1048576:   { name: 'Mini Cannon',  color: '#585860', glyph: 'x' },
  2097152:   { name: 'Laser',        color: '#684870', glyph: 'L' },
  8388608:   { name: 'Death Ray',    color: '#783848', glyph: 'D' },
  33554432:  { name: 'Silo',         color: '#cdcdcd', glyph: 'i' },
  134217728: { name: 'Com Tower',    property: true, glyph: 'T' },
};

// Orange Star, Blue Moon, Green Earth, Yellow Comet, Black Hole.
export const TEAMS = [
  { name: 'Orange Star', color: '#e07f3a' },
  { name: 'Blue Moon',   color: '#4a7ed4' },
  { name: 'Green Earth', color: '#48a648' },
  { name: 'Yellow Comet',color: '#ddc63c' },
  { name: 'Black Hole',  color: '#8a5aa8' },
];

export const NEUTRAL = { name: 'Neutral', color: '#b4b4b4' };

// Sequential enum; see docs/id-tables.md for how the names were established.
export const UNITS = {
  1:  'Anti-Air',      2:  'APC',          3:  'Artillery',
  4:  'Battle Copter', 5:  'Battleship',   6:  'Bomber',
  7:  'Cruiser',       8:  'Fighter',      9:  'Infantry',
  10: 'Lander',        11: 'Mech',         12: 'Medium Tank',
  13: 'Missile',       14: 'Recon',        15: 'Rocket',
  16: 'Submarine',     17: 'Tank',         18: 'Transport Copter',
  19: 'Neotank',
};

// Short labels for drawing on a tile. Chosen to stay distinct at 2 characters.
export const UNIT_ABBR = {
  1: 'AA', 2: 'AP', 3: 'AR', 4: 'BC', 5: 'BS', 6: 'BM', 7: 'CR',
  8: 'FT', 9: 'IN', 10: 'LD', 11: 'ME', 12: 'MD', 13: 'MS', 14: 'RC',
  15: 'RK', 16: 'SU', 17: 'TK', 18: 'TC', 19: 'NT',
};

export const HP_SCALE = 1000000;

// Mirrors awrbc/core/model.py, which is authoritative.
export const PRODUCTION = new Set([2048, 4096, 8192]);
export const CAPTURABLE = new Set([512, 1024, 2048, 4096, 8192, 134217728]);

// Fuel and ammo a freshly placed unit gets. Observed directly in saves - see
// docs/id-tables.md, where they doubled as the evidence for the unit names.
export const UNIT_STATS = {
  1:  { gas: 60, ammo: 9 }, 2:  { gas: 70, ammo: 0 }, 3:  { gas: 50, ammo: 9 },
  4:  { gas: 99, ammo: 6 }, 5:  { gas: 99, ammo: 9 }, 6:  { gas: 99, ammo: 9 },
  7:  { gas: 99, ammo: 9 }, 8:  { gas: 99, ammo: 9 }, 9:  { gas: 99, ammo: 0 },
  10: { gas: 99, ammo: 0 }, 11: { gas: 70, ammo: 3 }, 12: { gas: 50, ammo: 8 },
  13: { gas: 50, ammo: 6 }, 14: { gas: 80, ammo: 0 }, 15: { gas: 50, ammo: 6 },
  16: { gas: 60, ammo: 6 }, 17: { gas: 70, ammo: 9 }, 18: { gas: 99, ammo: 0 },
  19: { gas: 99, ammo: 9 },
};

// The palette is split by who can own a thing, because that is the question
// the sidebar was failing to answer.

/** Ground. Never owned by anyone, so the army picker does not apply. */
export const TERRAIN_PALETTE = [1, 8, 4, 128, 256, 16, 32, 2, 64];

/** Structures any army can hold - and that can equally sit neutral. */
export const STRUCTURES = [512, 1024, 2048, 4096, 8192, 134217728];

/** Structures that are only ever neutral. */
export const NEUTRAL_STRUCTURES = [32768, 65536, 33554432, 1048576, 2097152,
                                   524288, 8388608];

/** Structures that aim, and so need a facing chosen when placed. */
export const DIRECTIONAL = new Set([524288, 8388608, 1048576]);

/**
 * Structures that occupy a 3x3 block rather than one tile.
 *
 * All nine tiles carry the terrain id. The top-left is the anchor and holds
 * the facing; the other eight record their offset from it; and the top-middle
 * carries the hit points - observed at offset [1,0] on every instance in the
 * sample, for both kinds.
 */
export const MULTI_TILE = new Set([524288, 8388608]);
export const STRUCTURE_SPAN = 3;
export const STRUCTURE_HP_AT = [1, 0];

/** Mirrors awrbc/core/validate.py; keep the two in step. */
export const MAX_UNITS_PER_TEAM = 50;
export const MAX_COLS = 64;
export const MAX_ROWS = 64;
export const IN_GAME_EDITOR_COLS = 30;
export const IN_GAME_EDITOR_ROWS = 20;

/** Breakable structures, which the game stores with full hit points. */
export const BREAKABLE_HP = { 65536: 99, 1048576: 99, 2097152: 99 };

export function team(n) {
  return (n === null || n === undefined || n < 0) ? NEUTRAL : (TEAMS[n] || NEUTRAL);
}

export function terrain(id) {
  return TERRAIN[id] || { name: 'Unknown ' + id, color: '#ff00ff' };
}

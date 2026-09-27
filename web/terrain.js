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
  4:         { name: 'Mountain',     color: '#9b8259', glyph: '^' },
  8:         { name: 'Woods',        color: '#5d9647', glyph: '*' },
  16:        { name: 'River',        color: '#72b4dd' },
  32:        { name: 'Shoal',        color: '#e6d6a0' },
  64:        { name: 'Reef',         color: '#3c6ba3', glyph: 'o' },
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

export function team(n) {
  return (n === null || n === undefined || n < 0) ? NEUTRAL : (TEAMS[n] || NEUTRAL);
}

export function terrain(id) {
  return TERRAIN[id] || { name: 'Unknown ' + id, color: '#ff00ff' };
}

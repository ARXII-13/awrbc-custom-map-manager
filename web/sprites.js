// Sprite packs.
//
// A pack in `sprites/` overrides the drawn icons. That directory is gitignored
// and never published - see sprites/README.md for the manifest format and for
// why that boundary exists. The repository itself ships no third-party art.
//
// Loading is best-effort by design: no pack, a broken manifest or a missing
// image all fall through to the drawn icons rather than failing the page.

let pack = null;
let packName = null;

/**
 * One drawable sprite, or null when the pack does not cover this id.
 *
 * `kind` is "terrain", "property" or "unit". `pick` carries what the renderer
 * knows about the tile: `team` for army-coloured art, `dirs` for terrain that
 * has a variant per connection ("N+E+S+W"), `variant` to choose between
 * interchangeable decorations, `part` ("dx,dy") for one tile of a multi-tile
 * structure such as a Black Cannon, and `facing` for a structure that aims.
 *
 * The returned `tall` is how many tiles high the art is. Buildings and
 * mountains are two, overhanging the tile above, which is what gives Advance
 * Wars its look.
 */
export function spriteFor(kind, id, pick = {}) {
  if (!pack) return null;
  const table = pack[kind];
  if (!table) return null;

  let entry = table[id];
  if (!entry) return null;

  if (entry && entry.parts) {
    // One tile of a structure, chosen by which way it aims and its offset from
    // the anchor. A one-tile cannon uses the same key shape with offset 0,0.
    const part = pick.part || '0,0';
    entry = entry.parts[(pick.facing || 'N') + '|' + part] ||
            entry.parts['N|' + part] ||
            entry.parts[part] ||
            entry.parts['N|0,0'] ||
            entry.parts['0,0'];
  }
  // An army-keyed entry: "0".."4", or "neutral" for an unowned property.
  if (entry && !Array.isArray(entry) && !entry.dirs && !entry.variants) {
    const t = pick.team;
    const key = (t === null || t === undefined || t < 0) ? 'neutral' : String(t);
    entry = entry[key] || entry.neutral || entry['0'];
  }
  if (entry && entry.dirs) {
    entry = entry.dirs[pick.dirs || ''] || entry.dirs[''] ||
            entry.dirs[Object.keys(entry.dirs)[0]];
  }
  if (entry && entry.variants) {
    const list = entry.variants;
    entry = list[(pick.variant || 0) % list.length];
  }
  if (!Array.isArray(entry)) return null;

  const sheet = pack.sheets[entry[2] || pack.defaultSheet];
  if (!sheet) return null;
  return {
    image: sheet.image,
    sx: entry[0] * sheet.cw,
    sy: entry[1] * sheet.ch,
    sw: sheet.cw,
    sh: sheet.ch,
    tall: sheet.ch / sheet.cw,
  };
}

/** Which pack loaded, for the UI to name. */
export function packLabel() {
  return packName;
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/**
 * Load the first pack that resolves.
 *
 * Resolves to true when a usable pack was found; never rejects, because having
 * no pack at all is a normal state.
 */
export async function loadPack(bases = ['sprites/']) {
  for (const base of [].concat(bases)) {
    if (await loadFrom(base)) return true;
  }
  return false;
}

async function loadFrom(base) {
  try {
    const res = await fetch(base + 'manifest.json', { cache: 'no-cache' });
    if (!res.ok) return false;
    const manifest = await res.json();

    const names = Object.keys(manifest.sheets || {});
    if (!names.length) return false;
    // A sheet is either "file.png" or { file, cw, ch }; the second form lets
    // one pack mix tile geometries, which any real tileset does.
    const specs = names.map((n) => {
      const v = manifest.sheets[n];
      const tile = manifest.tile || 16;
      return typeof v === 'string' ? { file: v, cw: tile, ch: tile } : v;
    });
    const loaded = await Promise.all(specs.map((sp) => loadImage(base + sp.file)));

    const sheets = {};
    names.forEach((n, i) => {
      if (loaded[i]) sheets[n] = { image: loaded[i], cw: specs[i].cw, ch: specs[i].ch };
    });
    if (!Object.keys(sheets).length) return false;

    packName = manifest.name || base.replace(/\/$/, '').split('/').pop();
    pack = {
      tile: manifest.tile || 16,
      sheets,
      defaultSheet: manifest.defaultSheet || names[0],
      terrain: manifest.terrain || {},
      property: manifest.properties || {},
      unit: manifest.units || {},
    };
    return true;
  } catch (e) {
    // A pack is optional; a broken one should not take the viewer down.
    console.warn('sprite pack ' + base + ' not loaded:', e.message);
    return false;
  }
}

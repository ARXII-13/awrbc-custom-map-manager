// Optional sprite packs.
//
// The renderer draws its own icons (icons.js). A sprite pack overrides them
// with images from a local `sprites/` directory, which is gitignored and never
// published - see sprites/README.md for why that boundary exists and for the
// manifest format.
//
// Loading is best-effort by design: no pack, a broken manifest or a missing
// image all fall through to the drawn icons rather than failing the page.

let pack = null;

/**
 * One drawable sprite, or null when the pack does not cover this id.
 *
 * `kind` is "terrain", "property" or "unit"; `team` is used only when the pack
 * supplies per-army art, which properties and units usually do.
 */
export function spriteFor(kind, id, team) {
  if (!pack) return null;
  const table = pack[kind];
  if (!table) return null;

  let entry = table[id];
  if (!entry) return null;

  // An entry is either [col, row] or a map of team -> [col, row]. "neutral"
  // covers an unowned property.
  if (!Array.isArray(entry)) {
    const key = (team === null || team === undefined || team < 0) ? 'neutral' : String(team);
    entry = entry[key] || entry.neutral || entry['0'];
    if (!Array.isArray(entry)) return null;
  }

  const sheet = pack.images[entry[2] || pack.defaultSheet];
  if (!sheet) return null;
  const tile = pack.tile;
  return { image: sheet, sx: entry[0] * tile, sy: entry[1] * tile, size: tile };
}

export function hasPack() {
  return pack !== null;
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
 * Look for `sprites/manifest.json` and load whatever it points at.
 *
 * Resolves to true when a usable pack was found. Never rejects: a missing pack
 * is the normal case, not an error.
 */
export async function loadPack(base = 'sprites/') {
  try {
    const res = await fetch(base + 'manifest.json', { cache: 'no-cache' });
    if (!res.ok) return false;
    const manifest = await res.json();

    const names = Object.keys(manifest.sheets || {});
    if (!names.length) return false;
    const loaded = await Promise.all(names.map((n) => loadImage(base + manifest.sheets[n])));

    const images = {};
    names.forEach((n, i) => { if (loaded[i]) images[n] = loaded[i]; });
    if (!Object.keys(images).length) return false;

    pack = {
      tile: manifest.tile || 16,
      images,
      defaultSheet: manifest.defaultSheet || names[0],
      terrain: manifest.terrain || {},
      property: manifest.properties || {},
      unit: manifest.units || {},
    };
    return true;
  } catch (e) {
    // A pack is optional; a broken one should not take the viewer down.
    console.warn('sprite pack not loaded:', e.message);
    return false;
  }
}

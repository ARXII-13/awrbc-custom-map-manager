// Talking to the save file, when there is one to talk to.
//
// Only the desktop app provides this. pywebview injects `window.pywebview.api`
// into the page it hosts; the hosted build has no such object and no code path
// to a file system (decision #52), so `available()` is false there and the
// save panel never appears. The boundary is structural, not a promise.
//
// Every call answers `{ok: false, error}` rather than throwing, because the
// Python side already turns its exceptions into data - a rejected promise
// across the bridge carries nothing a person could act on.

/** Is a save-capable host underneath us? */
export function available() {
  return typeof window !== 'undefined' &&
         !!(window.pywebview && window.pywebview.api);
}

/**
 * The bridge becomes available shortly after load, not at parse time.
 *
 * Polling rather than waiting on an event because pywebview's readiness event
 * has differed between versions and platforms, and a missed event would mean
 * a desktop app that never shows its save panel.
 */
export async function ready(timeoutMs = 5000, step = 50) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    if (available()) return true;
    await new Promise((r) => setTimeout(r, step));
  }
  return available();
}

function api() {
  if (!available()) {
    throw new Error('no save access in this build');
  }
  return window.pywebview.api;
}

/** Normalise whatever came back into something with `ok` on it. */
async function call(name, ...args) {
  try {
    const got = await api()[name](...args);
    if (got && typeof got === 'object' && 'ok' in got) return got;
    return { ok: false, error: `the ${name} call answered unexpectedly` };
  } catch (e) {
    return { ok: false, error: e?.message || String(e) };
  }
}

export const findSaves = (saveDir) => call('find_saves', saveDir ?? null);
export const openSave = (path) => call('open_save', path);
export const importMap = (path, document, name) =>
  call('import_map', path, document, name ?? null);
export const removeMap = (path, index) => call('remove_map', path, index);
export const snapshots = (path) => call('snapshots', path);
export const backupNow = (path) => call('backup_now', path);
export const restore = (path, name) => call('restore', path, name);
export const mapIdentity = (document) => call('map_identity', document);

/**
 * A one-line description of a map in a save, for a list.
 *
 * Built from the derived block rather than from anything stored, so it cannot
 * disagree with the map it describes.
 */
export function describe(entry) {
  const d = entry.derived ?? {};
  const size = entry.document?.size ?? {};
  const bits = [`${d.players ?? 0}p`, `${size.cols}x${size.rows}`];
  for (const k of ['predeployed', 'navy', 'structures', 'fog']) {
    if (d[k]) bits.push(k);
  }
  if (!entry.playable) bits.push('not playable');
  return bits.join(', ');
}

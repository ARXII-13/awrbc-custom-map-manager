// The save panel.
//
// Appears only in the desktop app. Separated from index.html so it ports to
// the framework application by changing who calls `attachSaves` (decision
// #47), and so the half that talks to Python (saves.js) stays free of DOM.
//
// Previews are drawn by the editor's own renderer from the documents the
// bridge returned - one renderer, with whatever sprite pack is loaded, same as
// everywhere else.

import * as saves from './saves.js';

const THUMB = 7;   // pixels per tile in the list; big enough to recognise

/**
 * Wire up the save panel.
 *
 * `poster(doc, tilePx)` and `loadMap(doc)` are passed in rather than imported,
 * so this file knows nothing about how the editor draws or loads.
 */
export function attachSaves({ panel, poster, loadMap, currentDoc }) {
  let savePath = null;
  let entries = [];

  const el = (tag, props = {}, ...kids) => {
    const node = Object.assign(document.createElement(tag), props);
    for (const k of kids) node.append(k);
    return node;
  };

  function say(message, isError = false) {
    panel.replaceChildren(el('div', {
      className: isError ? 'sub no' : 'sub', textContent: message }));
  }

  async function refresh() {
    const got = await saves.findSaves();
    if (!got.ok) return say(got.error, true);
    if (!got.saves.length) {
      return say('No Ryujinx save found on this machine.');
    }
    // One save is the common case; more than one means profiles, and the
    // path's tail is the only thing that tells them apart.
    savePath = savePath ?? got.saves[0].path;
    await open(savePath);
  }

  async function open(path) {
    say('Reading…');
    const got = await saves.openSave(path);
    if (!got.ok) return say(got.error, true);
    savePath = path;
    entries = got.maps;
    render();
  }

  function render() {
    const rows = entries.map((entry, i) => {
      const canvas = poster(entry.document, THUMB);
      canvas.style.cssText =
        'width:100%;image-rendering:pixelated;border-radius:3px';

      const open = el('button', {
        className: 'cellbtn', title: 'Open this map in the editor',
        textContent: 'Open' });
      open.onclick = () => loadMap(structuredClone(entry.document));

      const drop = el('button', {
        className: 'cellbtn', title: 'Remove this map from the save',
        textContent: 'Remove' });
      drop.onclick = () => removeAt(i);

      return el('div', { className: 'row', style:
        'display:block;border-top:1px solid var(--line);padding:6px 0' },
        canvas,
        el('div', { className: 'sub',
                    textContent: `${entry.name || '(unnamed)'} — ` +
                                 saves.describe(entry) }),
        el('div', {}, open, drop));
    });

    const add = el('button', { className: 'cellbtn',
      title: 'Put the map you are editing into the save',
      textContent: 'Add the current map' });
    add.onclick = addCurrent;

    panel.replaceChildren(
      el('div', { className: 'sub', textContent:
        `${entries.length} map${entries.length === 1 ? '' : 's'} in this save` }),
      add, ...rows);
  }

  async function addCurrent() {
    const doc = currentDoc();
    // Warn about the thing that cannot be undone by Ctrl-Z: this writes to a
    // file the game owns.
    if (!confirm(`Add "${doc.name || 'Untitled'}" to the save?\n\n` +
                 'A backup is taken first, and the game must be closed.')) {
      return;
    }
    say('Writing…');
    const got = await saves.importMap(savePath, doc);
    if (!got.ok) {
      const detail = (got.findings ?? [])
        .map((f) => `\n  ${f.code}: ${f.message}`).join('');
      alert(got.error + detail);
      return open(savePath);
    }
    await open(savePath);
    alert(`Added as slot ${got.slot}.\nBackup: ${got.backup}`);
  }

  async function removeAt(index) {
    const entry = entries[index];
    if (!confirm(`Remove "${entry.name || '(unnamed)'}" from the save?\n\n` +
                 'A backup is taken first.')) return;
    say('Writing…');
    const got = await saves.removeMap(savePath, index);
    if (!got.ok) {
      alert(got.error);
      return open(savePath);
    }
    await open(savePath);
  }

  refresh();
  return { refresh };
}

/**
 * Show the panel only where a save can actually be reached.
 *
 * Returns false in a browser, which is not a failure - it is the boundary
 * doing its job.
 */
export async function attachIfDesktop(options) {
  if (!await saves.ready()) return false;
  options.panel.hidden = false;
  if (options.heading) options.heading.hidden = false;
  attachSaves(options);
  return true;
}

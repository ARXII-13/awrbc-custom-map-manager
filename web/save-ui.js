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

    // Every write here takes a backup of its own, so these are for the times
    // that is not enough: before a run of edits, and after one went wrong.
    const takeBackup = el('button', { className: 'cellbtn',
      title: 'Copy this save somewhere safe, right now',
      textContent: 'Back up now' });
    takeBackup.onclick = backupNow;

    const roll = el('button', { className: 'cellbtn',
      title: 'Put an earlier copy of this save back',
      textContent: 'Restore…' });
    roll.onclick = restorePrompt;

    panel.replaceChildren(
      el('div', { className: 'sub', textContent:
        `${entries.length} map${entries.length === 1 ? '' : 's'} in this save` }),
      add,
      el('div', {}, takeBackup, roll),
      ...rows);
  }

  async function backupNow() {
    const got = await saves.backupNow(savePath);
    if (!got.ok) return alert(got.error);
    alert(`Backed up as ${got.name}.`);
  }

  /**
   * Choose a snapshot to put back.
   *
   * A numbered list and a prompt rather than a dialog, because this panel is
   * a toolbar column and the framework rebuild (decision #47) is where a real
   * one belongs. The names carry a timestamp, so they sort newest-last and
   * reading them is the whole of the choice.
   */
  async function restorePrompt() {
    const got = await saves.snapshots(savePath);
    if (!got.ok) return alert(got.error);
    if (!got.snapshots.length) {
      return alert('No backups of this save yet.\n\n' +
                   'One is taken automatically before every write, and ' +
                   '"Back up now" takes one on demand.');
    }

    const list = got.snapshots.map(
      (s, i) => `${i + 1}. ${s.name}  (${s.taken})`).join('\n');
    const answer = prompt(
      'Restore which backup?\n\n' + list +
      '\n\nType its number. The save as it is now is kept as a backup too, ' +
      'so this is itself undoable.', String(got.snapshots.length));
    if (answer === null) return;

    const pick = got.snapshots[Number(answer) - 1];
    if (!pick) return alert(`There is no backup ${answer}.`);
    if (!confirm(`Replace the current save with ${pick.name}?\n\n` +
                 'The game must be closed.')) return;

    say('Restoring…');
    const done = await saves.restore(savePath, pick.name);
    if (!done.ok) {
      alert(done.error);
      return open(savePath);
    }
    await open(savePath);
    alert(`Restored ${done.restored}.`);
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

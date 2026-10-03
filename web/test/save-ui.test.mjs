// The save panel.
//
// Only ever runs in the desktop app, so a mistake here does not show up in a
// browser or in CI - it shows up as a panel that will not draw on the one
// machine that can write to a save. That is reason enough to test it where it
// can be tested.
//
// The DOM it needs is small and deliberate (`el()` in save-ui.js touches
// createElement, append and replaceChildren and nothing else), so it is
// stubbed here rather than pulling in a browser.

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import { attachSaves } from '../save-ui.js';

/** Just enough DOM for `el()`. */
function node(tag = 'div') {
  const self = {
    tag, children: [], style: {}, className: '', textContent: '', title: '',
    hidden: false, onclick: null,
    append(...kids) { self.children.push(...kids); },
    replaceChildren(...kids) { self.children = [...kids]; },
  };
  return self;
}

/** Every button in the tree, depth first. */
function buttons(root) {
  const out = [];
  const walk = (n) => {
    if (!n || typeof n !== 'object') return;
    if (n.tag === 'button') out.push(n);
    for (const kid of n.children ?? []) walk(kid);
  };
  walk(root);
  return out;
}

const byText = (root, text) =>
  buttons(root).find((b) => b.textContent === text);

const stubs = [];
function global_(name, value) {
  stubs.push([name, globalThis[name]]);
  globalThis[name] = value;
}
afterEach(() => {
  while (stubs.length) {
    const [name, was] = stubs.pop();
    if (was === undefined) delete globalThis[name]; else globalThis[name] = was;
  }
});

const A_MAP = {
  name: 'Daibi', id: 'abc', playable: true,
  derived: { players: 2 },
  document: { size: { cols: 12, rows: 10 }, terrain: [], cells: [], units: [] },
};

/**
 * Attach the panel over a scripted bridge.
 *
 * `api` is what pywebview would inject; only the calls a test cares about
 * need to be present.
 */
function panelOver(api, { confirms = [], prompts = [], pickMap } = {}) {
  const asked = [];
  const alerts = [];
  global_('document', { createElement: (tag) => node(tag) });
  global_('window', { pywebview: { api: {
    find_saves: async () => ({ ok: true, saves: [{ path: 'C:/save/maps' }] }),
    open_save: async () => ({ ok: true, maps: [A_MAP] }),
    ...api,
  } } });
  global_('confirm', (m) => { asked.push(m); return confirms.length ? confirms.shift() : true; });
  global_('prompt', (m) => { asked.push(m); return prompts.length ? prompts.shift() : '1'; });
  global_('alert', (m) => { alerts.push(m); });

  const panel = node();
  const api_ = attachSaves({
    panel,
    poster: () => ({ style: {}, width: 1, height: 1 }),
    pickMap: pickMap ?? (() => null),
  });
  return { panel, api: api_, asked, alerts };
}

describe('the panel', () => {
  it('draws the maps and the controls without throwing', async () => {
    const p = panelOver({});
    await p.api.refresh();
    const labels = buttons(p.panel).map((b) => b.textContent);
    assert.ok(labels.includes('Remove'), labels.join(' | '));
    assert.ok(labels.includes('Back up now'));
    assert.ok(labels.includes('Restore…'));
  });

  it('offers nothing that needs a map editor', async () => {
    // The save editor is shipped apart from the map editor, so there is
    // nothing here to open a map into and no "current map" to add. Maps come
    // from a file the person picked.
    const p = panelOver({});
    await p.api.refresh();
    const labels = buttons(p.panel).map((b) => b.textContent);
    assert.ok(!labels.includes('Open'), 'nothing to open a map into');
    assert.ok(!labels.includes('Add the current map'),
              'there is no map being edited here');
  });
});

describe('importing a map from a file', () => {
  it('writes the picked document into the save', async () => {
    let seen = null;
    const doc = { name: 'Daibi', size: { cols: 12, rows: 10 } };
    const p = panelOver({
      import_map: async (path, document) => {
        seen = [path, document];
        return { ok: true, slot: 3, backup: 'b.bak' };
      },
    }, { pickMap: () => doc });

    await p.api.refresh();
    await p.api.addPicked();
    assert.deepEqual(seen, ['C:/save/maps', doc]);
  });

  it('does nothing when no map was picked', async () => {
    let called = false;
    const p = panelOver({
      import_map: async () => { called = true; return { ok: true }; },
    }, { pickMap: () => null });

    await p.api.refresh();
    await p.api.addPicked();
    assert.equal(called, false);
  });

  it('asks before writing, and does not write when declined', async () => {
    let called = false;
    const p = panelOver({
      import_map: async () => { called = true; return { ok: true }; },
    }, { pickMap: () => ({ name: 'Daibi' }), confirms: [false] });

    await p.api.refresh();
    await p.api.addPicked();
    assert.equal(called, false);
  });

  it('shows the findings when the map is refused', async () => {
    const p = panelOver({
      import_map: async () => ({
        ok: false, error: 'that map did not pass validation',
        findings: [{ code: 'play.noHQ', message: 'team 0 has no HQ' }],
      }),
    }, { pickMap: () => ({ name: 'Daibi' }) });

    await p.api.refresh();
    await p.api.addPicked();
    assert.ok(p.alerts.some((m) => m.includes('team 0 has no HQ')),
              p.alerts.join(' | '));
  });
});

describe('backing up on demand', () => {
  it('asks the bridge and says what it got', async () => {
    let seen = null;
    const p = panelOver({
      backup_now: async (path) => { seen = path; return { ok: true, name: 'maps-2026.bak' }; },
    });
    await p.api.refresh();
    await byText(p.panel, 'Back up now').onclick();
    assert.equal(seen, 'C:/save/maps');
    assert.ok(p.alerts.some((m) => m.includes('maps-2026.bak')), p.alerts.join(' | '));
  });

  it('shows the error rather than claiming success', async () => {
    const p = panelOver({
      backup_now: async () => ({ ok: false, error: 'the disk is full' }),
    });
    await p.api.refresh();
    await byText(p.panel, 'Back up now').onclick();
    assert.ok(p.alerts.some((m) => m.includes('the disk is full')));
  });
});

describe('restoring', () => {
  const twoSnapshots = {
    snapshots: async () => ({ ok: true, snapshots: [
      { name: 'older.bak', taken: '2026-09-01', size: 1 },
      { name: 'newer.bak', taken: '2026-09-30', size: 1 },
    ] }),
  };

  it('says so plainly when there are none, rather than offering a prompt',
     async () => {
    const p = panelOver({ snapshots: async () => ({ ok: true, snapshots: [] }) });
    await p.api.refresh();
    await byText(p.panel, 'Restore…').onclick();
    assert.ok(p.alerts.some((m) => /No backups/.test(m)), p.alerts.join(' | '));
  });

  it('restores the one that was chosen', async () => {
    let seen = null;
    const p = panelOver({
      ...twoSnapshots,
      restore: async (path, name) => { seen = [path, name]; return { ok: true, restored: name }; },
    }, { prompts: ['1'] });
    await p.api.refresh();
    await byText(p.panel, 'Restore…').onclick();
    assert.deepEqual(seen, ['C:/save/maps', 'older.bak']);
  });

  it('does nothing at all, and says nothing, when the prompt is cancelled',
     async () => {
    // Silence is the point. Falling through to the "no such backup" branch
    // would also restore nothing, but it scolds somebody for pressing Cancel.
    let called = false;
    const p = panelOver({
      ...twoSnapshots,
      restore: async () => { called = true; return { ok: true }; },
    }, { prompts: [null] });
    await p.api.refresh();
    await byText(p.panel, 'Restore…').onclick();
    assert.equal(called, false);
    assert.deepEqual(p.alerts, [], `cancelling should be quiet: ${p.alerts}`);
  });

  it('restores nothing when the number is not on the list', async () => {
    // An overwrite of the save is on the other side of this, so a typo must
    // not pick a neighbour.
    let called = false;
    const p = panelOver({
      ...twoSnapshots,
      restore: async () => { called = true; return { ok: true }; },
    }, { prompts: ['9'] });
    await p.api.refresh();
    await byText(p.panel, 'Restore…').onclick();
    assert.equal(called, false);
    assert.ok(p.alerts.some((m) => /no backup 9/i.test(m)), p.alerts.join(' | '));
  });

  it('restores nothing when the confirmation is declined', async () => {
    let called = false;
    const p = panelOver({
      ...twoSnapshots,
      restore: async () => { called = true; return { ok: true }; },
    }, { prompts: ['2'], confirms: [false] });
    await p.api.refresh();
    await byText(p.panel, 'Restore…').onclick();
    assert.equal(called, false);
  });
});

// Talking to the save file.
//
// The property worth protecting is the boundary: in a browser there is no
// bridge, so `available()` is false, the save panel never appears, and nothing
// here reaches for a file. That is decision #52 - the hosted build *cannot*
// read your save, as opposed to being asked not to.
//
// The bridge is faked here rather than imported, because the real one is
// injected by pywebview into a window this test does not have.

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import {
  available, describe as describeMap, findSaves, importMap, openSave, ready,
  removeMap,
} from '../saves.js';

/** Stand in for what pywebview injects. */
function withBridge(api) {
  globalThis.window = { pywebview: { api } };
}

afterEach(() => { delete globalThis.window; });

describe('the boundary', () => {
  it('reports no save access when there is no bridge', () => {
    globalThis.window = {};
    assert.equal(available(), false);
  });

  it('reports no save access when there is no window at all', () => {
    assert.equal(available(), false);
  });

  it('reports save access when the bridge is there', () => {
    withBridge({});
    assert.equal(available(), true);
  });

  it('does not throw in a browser, it answers', async () => {
    // A hosted editor must keep working, not break on a missing bridge.
    globalThis.window = {};
    const got = await findSaves();
    assert.equal(got.ok, false);
    assert.match(got.error, /no save access/);
  });

  it('gives up waiting rather than hanging', async () => {
    globalThis.window = {};
    const started = Date.now();
    assert.equal(await ready(120, 20), false);
    assert.ok(Date.now() - started >= 100, 'it actually waited');
  });

  it('notices a bridge that arrives late', async () => {
    globalThis.window = {};
    setTimeout(() => withBridge({}), 60);
    assert.equal(await ready(1000, 20), true);
  });
});

describe('calling across', () => {
  it('passes arguments through', async () => {
    let seen = null;
    withBridge({ open_save: async (...args) => { seen = args; return { ok: true }; } });
    await openSave('C:/saves/maps');
    assert.deepEqual(seen, ['C:/saves/maps']);
  });

  it('sends null rather than undefined for an absent argument', async () => {
    // undefined does not survive the bridge; Python would see a missing
    // positional and raise.
    let seen = null;
    withBridge({ find_saves: async (...args) => { seen = args; return { ok: true }; } });
    await findSaves();
    assert.deepEqual(seen, [null]);
  });

  it('passes a name through on import, null when there is none', async () => {
    let seen = null;
    withBridge({ import_map: async (...args) => { seen = args; return { ok: true }; } });
    await importMap('p', { name: 'x' });
    assert.deepEqual(seen, ['p', { name: 'x' }, null]);
  });

  it('returns what the bridge answered', async () => {
    withBridge({ remove_map: async () => ({ ok: true, removed: 'Daibi' }) });
    assert.deepEqual(await removeMap('p', 0), { ok: true, removed: 'Daibi' });
  });

  it('turns a thrown error into an answer', async () => {
    withBridge({ open_save: async () => { throw new Error('exploded'); } });
    const got = await openSave('p');
    assert.equal(got.ok, false);
    assert.equal(got.error, 'exploded');
  });

  it('refuses to believe an answer with no ok on it', async () => {
    // A bridge that returned something unexpected must not be read as
    // success; a write is on the other side of these calls.
    withBridge({ open_save: async () => 'surprise' });
    const got = await openSave('p');
    assert.equal(got.ok, false);
  });
});

describe('describing a map for the list', () => {
  const entry = (derived, size = { cols: 30, rows: 20 }, playable = true) => ({
    derived, document: { size }, playable,
  });

  it('leads with players and size', () => {
    assert.equal(describeMap(entry({ players: 4 })), '4p, 30x20');
  });

  it('adds the facts that are true', () => {
    const text = describeMap(entry({ players: 2, navy: true, fog: true }));
    assert.match(text, /navy/);
    assert.match(text, /fog/);
    assert.doesNotMatch(text, /predeployed/);
  });

  it('says when a map will not play', () => {
    assert.match(describeMap(entry({ players: 1 }, { cols: 8, rows: 8 }, false)),
                 /not playable/);
  });

  it('copes with a map that carries no derived block', () => {
    assert.doesNotThrow(() => describeMap({ document: {} }));
  });
});

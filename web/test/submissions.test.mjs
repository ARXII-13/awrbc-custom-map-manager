// What the editor remembers about maps it has sent.
//
// Run with `node --test web/test/` from the repository root.
//
// `submissions.js` touches no DOM and takes its storage, so this needs neither
// a browser nor localStorage. The behaviour worth protecting is that a stored
// value is treated as untrusted input: it is user-writable, it outlives any
// version of this code, and it ends up in an href.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { clear, load, remember } from '../submissions.js';

const KEY = 'awrbc.submissions';

/** localStorage's surface, as much of it as this uses. */
function fake(initial = null) {
  const map = new Map(initial === null ? [] : [[KEY, initial]]);
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    get raw() { return map.get(KEY) ?? null; },
  };
}

const entry = (over = {}) => ({
  url: 'https://github.com/o/r/pull/7', number: 7, name: 'daibi',
  path: 'maps/2p/daibi/v1.json', kind: 'added', ...over,
});

describe('remembering a submission', () => {
  it('keeps what came back from the archive', () => {
    const s = fake();
    const items = remember(entry(), s);
    assert.equal(items.length, 1);
    assert.equal(items[0].url, 'https://github.com/o/r/pull/7');
    assert.equal(items[0].number, 7);
    assert.equal(items[0].name, 'daibi');
    assert.equal(load(s).length, 1);
  });

  it('puts the newest first', () => {
    const s = fake();
    remember(entry(), s);
    remember(entry({ url: 'https://x/pull/8', number: 8, name: 'renew' }), s);
    assert.deepEqual(load(s).map((i) => i.number), [8, 7]);
  });

  it('replaces rather than duplicates the same pull request', () => {
    // A retry or a double click records the same URL twice. Two rows pointing
    // at one pull request would read as two submissions.
    const s = fake();
    remember(entry(), s);
    remember(entry({ name: 'daibi renamed' }), s);
    const items = load(s);
    assert.equal(items.length, 1);
    assert.equal(items[0].name, 'daibi renamed');
  });

  it('caps the list', () => {
    const s = fake();
    for (let i = 0; i < 40; i++) {
      remember(entry({ url: 'https://x/pull/' + i, number: i }), s);
    }
    const items = load(s);
    assert.equal(items.length, 25);
    assert.equal(items[0].number, 39);
  });
});

describe('reading a stored value', () => {
  it('treats anything unreadable as nothing remembered', () => {
    for (const raw of ['', 'not json', '{', 'null', '[]', '{"items":[]}',
                       '{"schema":99,"items":[{"url":"https://x","name":"a"}]}',
                       '{"schema":1,"items":"nope"}']) {
      assert.deepEqual(load(fake(raw)), [], 'for ' + JSON.stringify(raw));
    }
  });

  it('drops entries that are not a link to somewhere', () => {
    const s = fake(JSON.stringify({ schema: 1, items: [
      { url: 'https://ok/pull/1', name: 'good' },
      { url: 'javascript:alert(1)', name: 'script url' },
      { url: 'data:text/html,x', name: 'data url' },
      { url: '/relative', name: 'relative' },
      { name: 'no url at all' },
      { url: 'https://ok/pull/2' },
      null,
    ] }));
    assert.deepEqual(load(s).map((i) => i.name), ['good']);
  });

  it('refuses to store an entry with no usable link', () => {
    const s = fake();
    remember(entry(), s);
    const after = remember(entry({ url: 'javascript:alert(1)' }), s);
    assert.equal(after.length, 1);
    assert.equal(after[0].url, 'https://github.com/o/r/pull/7');
  });
});

describe('a browser with no usable storage', () => {
  // Private windows and blocked site data throw on access rather than
  // returning null. None of that is worth an error message: the pull request
  // is open either way, which is the part that matters.
  const hostile = {
    getItem() { throw new Error('denied'); },
    setItem() { throw new Error('denied'); },
    removeItem() { throw new Error('denied'); },
  };

  it('reads as empty', () => {
    assert.deepEqual(load(hostile), []);
  });

  it('still reports the submission it could not store', () => {
    const items = remember(entry(), hostile);
    assert.equal(items.length, 1);
    assert.equal(items[0].number, 7);
  });

  it('clears without throwing', () => {
    assert.doesNotThrow(() => clear(hostile));
  });
});

describe('clearing', () => {
  it('forgets everything', () => {
    const s = fake();
    remember(entry(), s);
    clear(s);
    assert.deepEqual(load(s), []);
  });
});

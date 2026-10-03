// The Submit button's behaviour.
//
// `attachSubmit` takes what it needs rather than reaching for globals, which
// is what makes it testable without a DOM: the buttons are plain objects with
// the three properties it touches. `confirm`, `alert` and `open` are globals
// it does reach for, so those are stubbed per test.
//
// The behaviour worth protecting is the two-step after a name clash. The
// archive cannot tell "my own map, revised" from "somebody else's name, taken
// by accident", so this asks - and must only ask on that one refusal, must
// only resubmit if the answer is yes, and must send the same bytes both times.

import assert from 'node:assert/strict';
import { afterEach, describe, it } from 'node:test';

import { SubmitRejected } from '../intake.js';
import { attachSubmit } from '../submit-ui.js';

const BASE = 'https://intake.example';

/** Enough of a button for the three properties attachSubmit touches. */
const aButton = () => ({ hidden: true, disabled: false, textContent: '',
                         title: '', onclick: null });

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

const conflict = {
  status: 422,
  body: { error: 'maps/2p/daibi already exists', code: 'conflict',
          folder: 'maps/2p/daibi' },
};
const accepted = { body: { ok: true, pullRequest: 'https://x/pull/7' } };

/**
 * Wire up a button against scripted server answers.
 *
 * Answers are routed by endpoint rather than queued positionally, because
 * `attachSubmit` calls /auth/me on its own schedule - a shared queue puts the
 * sign-in answer wherever the test did not expect it, and the whole thing
 * then passes or fails for reasons that have nothing to do with the subject.
 *
 * `submits` is consumed one per POST /submit; the last one repeats.
 */
function wire({ submits = [accepted], signedIn = true, open = false,
                doc, confirms = [] }) {
  const calls = [];
  const asked = [];
  const alerts = [];

  global_('confirm', (message) => {
    asked.push(message);
    return confirms.length ? confirms.shift() : true;
  });
  global_('alert', (message) => { alerts.push(message); });
  global_('open', () => {});
  global_('location', { href: '' });

  const button = aButton();
  const label = aButton();
  const signOut = aButton();
  const queue = [...submits];

  global_('fetch', async (url, init) => {
    const href = String(url);
    calls.push({ url: href, body: init?.body });

    if (href.endsWith('/auth/me')) {
      return { ok: true, status: 200, json: async () => (
        signedIn
          ? { signedIn: true, user: { username: 'debbie' },
              openSubmissions: open }
          : { signedIn: false, openSubmissions: open }) };
    }
    if (href.endsWith('/auth/logout')) {
      return { ok: true, status: 200, json: async () => ({}) };
    }

    const answer = queue.length > 1 ? queue.shift() : queue[0];
    if (answer instanceof Error) throw answer;
    return {
      ok: (answer.status ?? 200) < 300,
      status: answer.status ?? 200,
      json: async () => answer.body,
    };
  });

  let built = 0;
  const api = attachSubmit({
    base: BASE, button, label, signOut,
    bundle: async () => { built += 1; return new Blob(['zip-bytes']); },
    currentDoc: () => doc ?? {
      name: 'Daibi', author: 'debbie', size: { cols: 12, rows: 10 },
    },
    stats: () => ({ valid: true, reasons: [] }),
  });

  return {
    api, button, label, signOut, calls, asked, alerts,
    bundled: () => built,
    sent: () => calls.filter((c) => c.url.endsWith('/submit')),
  };
}

/** Click, with the sign-in state already settled. */
async function click(w) {
  // attachSubmit's own refresh() is in flight from attach; let one land so
  // the handler sees a settled `who` rather than racing it.
  await w.api.refresh();
  await w.button.onclick();
}

describe('a name clash', () => {
  it('asks whether it is a revision, and names the folder', async () => {
    const w = wire({ submits: [conflict, accepted] });
    await click(w);
    const question = w.asked.find((m) => m.includes('maps/2p/daibi'));
    assert.ok(question, `no question named the folder: ${w.asked.join(' | ')}`);
  });

  it('resubmits against that folder when the answer is yes', async () => {
    const w = wire({ submits: [conflict, accepted] });
    await click(w);
    const submits = w.sent();
    assert.equal(submits.length, 2, 'the first attempt and the revision');
    assert.equal(submits[0].body.has('update'), false);
    assert.equal(submits[1].body.get('update'), 'maps/2p/daibi');
  });

  it('builds the bundle once and sends that, not a fresh one', async () => {
    // Rebuilding would send whatever is on screen by the time the question
    // gets answered, which is not what the person confirmed. Counted rather
    // than compared, because FormData wraps each blob in a File stamped with
    // the moment it was set - identical bytes, different objects.
    const w = wire({ submits: [conflict, accepted] });
    await click(w);
    assert.equal(w.sent().length, 2, 'the first attempt and the revision');
    assert.equal(w.bundled(), 1, 'one bundle, sent twice');
  });

  it('gives up when the answer is no, and says why it was refused', async () => {
    // confirms: [licence yes, revision no]
    const w = wire({ submits: [conflict, accepted], confirms: [true, false] });
    await click(w);
    assert.equal(w.sent().length, 1);
    assert.ok(w.alerts.some((m) => m.includes('already exists')),
              `the refusal should be shown: ${w.alerts.join(' | ')}`);
  });
});

describe('every other refusal', () => {
  it('is shown, not retried', async () => {
    const invalid = {
      status: 422,
      body: { error: 'that map did not pass validation', code: 'invalid',
              findings: [{ code: 'play.noHQ', message: 'team 0 has no HQ' }] },
    };
    const w = wire({ submits: [invalid] });
    await click(w);
    assert.equal(w.sent().length, 1,
                 'only a conflict has a second attempt to offer');
    assert.ok(w.alerts.some((m) => m.includes('team 0 has no HQ')));
  });

  it('does not retry a conflict with no folder on it', async () => {
    // An older server, or one that refused for a reason it could not name.
    // Guessing the folder is exactly the thing this must not do.
    const bare = { status: 422,
                   body: { error: 'already exists', code: 'conflict' } };
    const w = wire({ submits: [bare] });
    await click(w);
    assert.equal(w.sent().length, 1);
    assert.equal(w.asked.filter((m) => m.includes('newer version')).length, 0);
  });
});

describe('the licence question', () => {
  it('is asked before anything is uploaded', async () => {
    const w = wire({ confirms: [false] });
    await click(w);
    assert.equal(w.sent().length, 0,
                 'declining must not upload');
  });
});

describe('a server that takes submissions without signing in', () => {
  it('offers Submit rather than Sign in', async () => {
    const w = wire({ signedIn: false, open: true });
    await w.api.refresh();
    assert.equal(w.button.textContent, 'Submit');
  });

  it('says the author field is the only name it will get', async () => {
    // Otherwise the first anyone hears of it is the pull request.
    const w = wire({ signedIn: false, open: true });
    await w.api.refresh();
    assert.equal(w.label.hidden, false);
    assert.match(w.label.textContent, /Author/i);
  });

  it('uploads instead of redirecting to sign-in', async () => {
    const w = wire({ signedIn: false, open: true });
    await click(w);
    assert.equal(w.sent().length, 1, 'it should have submitted');
    assert.equal(globalThis.location.href, '',
                 'it must not bounce through sign-in');
  });

  it('offers no sign-out, because there is no session', async () => {
    const w = wire({ signedIn: false, open: true });
    await w.api.refresh();
    assert.equal(w.signOut.hidden, true);
  });

  it('still asks the licence question before uploading', async () => {
    const w = wire({ signedIn: false, open: true, confirms: [false] });
    await click(w);
    assert.equal(w.sent().length, 0);
  });
});

describe('a server that does require signing in', () => {
  it('sends you to sign in rather than uploading', async () => {
    const w = wire({ signedIn: false, open: false });
    await click(w);
    assert.equal(w.sent().length, 0);
    assert.match(globalThis.location.href, /\/auth\/login$/);
  });
});

describe('the sign-out button', () => {
  it('is hidden while signed out and shown while signed in', async () => {
    const w = wire({ signedIn: false });
    await w.api.refresh();
    assert.equal(w.signOut.hidden, true);

    const b = wire({});
    await b.api.refresh();
    assert.equal(b.signOut.hidden, false);
  });

  it('asks the server again rather than assuming it worked', async () => {
    // intake.signOut swallows failures, so believing it would leave the
    // toolbar claiming "signed out" over a session that is still live.
    const w = wire({});
    await w.api.refresh();
    w.calls.length = 0;
    await w.signOut.onclick();
    assert.ok(w.calls.some((c) => c.url.endsWith('/auth/logout')));
    assert.ok(w.calls.some((c) => c.url.endsWith('/auth/me')),
              'the state must be re-read, not inferred');
  });
});

// Talking to the intake server.
//
// `fetch` is injected rather than stubbed globally, so these say what the
// client does with each answer without a server or a network.
//
// The behaviour worth protecting is what happens when things go wrong:
// editing a map has never needed a server (decision #50), so an intake server
// that is down, absent or misconfigured must leave the editor working.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  explain, intakeBase, SIGNED_OUT, signInUrl, submit, SubmitRejected, whoAmI,
} from '../intake.js';

const BASE = 'https://intake.example';

function serving(status, body) {
  return async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

function failing(message = 'network down') {
  return async () => { throw new Error(message); };
}

describe('where the intake server is', () => {
  it('uses the fallback when nothing is given', () => {
    assert.equal(intakeBase('', 'https://fallback.example'),
                 'https://fallback.example');
  });

  it('takes an override from the query', () => {
    assert.equal(intakeBase('?intake=http://127.0.0.1:5000', ''),
                 'http://127.0.0.1:5000');
  });

  it('keeps only the origin', () => {
    // A link carrying a path could otherwise decide where somebody's map goes.
    assert.equal(intakeBase('?intake=https://evil.example/collect', ''),
                 'https://evil.example');
  });

  it('falls back rather than throwing on nonsense', () => {
    assert.equal(intakeBase('?intake=not a url', 'https://ok.example'),
                 'https://ok.example');
  });
});

describe('who am i', () => {
  it('reports a signed-in user', async () => {
    const got = await whoAmI(BASE, serving(200, {
      signedIn: true, user: { id: '1', username: 'debbie' },
    }));
    assert.equal(got.signedIn, true);
    assert.equal(got.user.username, 'debbie');
  });

  it('reports signed out', async () => {
    assert.deepEqual(await whoAmI(BASE, serving(200, { signedIn: false })),
                     SIGNED_OUT);
  });

  it('treats an unreachable server as signed out, not as an error', async () => {
    // The editor must keep working with no server at all.
    assert.deepEqual(await whoAmI(BASE, failing()), SIGNED_OUT);
  });

  it('treats a 500 as signed out', async () => {
    assert.deepEqual(await whoAmI(BASE, serving(500, {})), SIGNED_OUT);
  });

  it('treats an unparseable answer as signed out', async () => {
    const broken = async () => ({
      ok: true, status: 200,
      json: async () => { throw new Error('not json'); },
    });
    assert.deepEqual(await whoAmI(BASE, broken), SIGNED_OUT);
  });

  it('is signed out when there is no server configured at all', async () => {
    let called = false;
    await whoAmI('', async () => { called = true; });
    assert.equal(called, false, 'must not fetch without a base');
  });
});

describe('the sign-in link', () => {
  it('points at the server', () => {
    assert.equal(signInUrl(BASE), `${BASE}/auth/login`);
  });
});

describe('submitting', () => {
  const bundle = new Blob([new Uint8Array([1, 2, 3])]);

  it('sends the file and the licence confirmation', async () => {
    let seen;
    const fetchImpl = async (url, init) => {
      seen = { url, body: init.body, credentials: init.credentials };
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    };
    await submit(BASE, { bundle, agree: true, fetchImpl });

    assert.equal(seen.url, `${BASE}/submit`);
    assert.equal(seen.credentials, 'include', 'the session is a cookie');
    assert.equal(seen.body.get('agree'), 'true');
    assert.ok(seen.body.get('file'));
  });

  it('passes the confirmation through rather than assuming it', async () => {
    // A client that quietly sent `true` would be manufacturing consent to
    // publish somebody's work under CC BY.
    let seen;
    const fetchImpl = async (_url, init) => {
      seen = init.body;
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    };
    await submit(BASE, { bundle, agree: false, fetchImpl });
    assert.equal(seen.get('agree'), 'false');
  });

  it('sends an update target when there is one', async () => {
    let seen;
    const fetchImpl = async (_url, init) => {
      seen = init.body;
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    };
    await submit(BASE, { bundle, agree: true, update: '2p/daibi', fetchImpl });
    assert.equal(seen.get('update'), '2p/daibi');
  });

  it('returns what the server said on success', async () => {
    const got = await submit(BASE, {
      bundle, agree: true,
      fetchImpl: serving(200, { ok: true, pullRequest: 'https://x/pull/7' }),
    });
    assert.equal(got.pullRequest, 'https://x/pull/7');
  });

  it('raises a rejection carrying every finding', async () => {
    await assert.rejects(
      () => submit(BASE, {
        bundle, agree: true,
        fetchImpl: serving(422, {
          error: 'that map did not pass validation', code: 'invalid',
          findings: [
            { code: 'play.noHQ', severity: 'error', message: 'team 0 has no HQ' },
            { code: 'play.oneTeam', severity: 'error', message: 'one army' },
          ],
        }),
      }),
      (err) => {
        assert.ok(err instanceof SubmitRejected);
        assert.equal(err.code, 'invalid');
        assert.equal(err.findings.length, 2,
          'all of them, not one per round trip');
        return true;
      });
  });

  it('says plainly when the server cannot be reached', async () => {
    await assert.rejects(
      () => submit(BASE, { bundle, agree: true, fetchImpl: failing() }),
      (err) => {
        assert.equal(err.code, 'unreachable');
        assert.match(err.message, /could not reach/);
        return true;
      });
  });

  it('copes with an error page that is not JSON', async () => {
    const proxyError = async () => ({
      ok: false, status: 502,
      json: async () => { throw new Error('<html>'); },
    });
    await assert.rejects(
      () => submit(BASE, { bundle, agree: true, fetchImpl: proxyError }),
      (err) => {
        assert.equal(err.code, '502');
        return true;
      });
  });
});

describe('explaining a rejection', () => {
  it('is just the message when there are no findings', () => {
    assert.equal(explain(new SubmitRejected('already here', 'duplicate')),
                 'already here');
  });

  it('lists every finding under the message', () => {
    const text = explain(new SubmitRejected('did not pass', 'invalid', [
      { code: 'play.noHQ', message: 'team 0 has no HQ' },
    ]));
    assert.match(text, /did not pass/);
    assert.match(text, /play\.noHQ: team 0 has no HQ/);
  });
});

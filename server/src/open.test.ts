/**
 * Submissions with nobody signed in.
 *
 * A separate file from index.test.ts because `config` is a module-level const
 * built when ./index.js is first imported - so OPEN_SUBMISSIONS has to be set
 * before that import, and a file testing the closed server cannot also test
 * the open one. Setting it in a hook would be the module-load ordering trap
 * this project has now hit twice.
 *
 * What matters here is that opening the door gives up exactly what it is
 * documented to give up, and nothing else: no sign-in, the file's own author
 * name, rate limiting by address. The licence confirmation, the size limit
 * and the validator are unchanged, because none of them were ever about who
 * was asking.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import type { AddressInfo } from 'node:net';
import type { Server } from 'node:http';

process.env['OPEN_SUBMISSIONS'] = '1';
process.env['EDITOR_URL'] = 'http://127.0.0.1:8731/';
// GITHUB_TOKEN deliberately unset: it is what lets the test below observe
// that the token is still demanded. The endpoint tests never reach GitHub -
// they are refused for the licence or the missing file long before that.

const { anonymousFrom, createApp, missingConfig } =
  await import('./index.js');
const { Store } = await import('./db.js');
type Store = Awaited<ReturnType<typeof Store.open>>;

describe('who an anonymous submitter is', () => {
  it('is keyed on the address, with no name attached', () => {
    // The empty username is load-bearing: `awrbc prepare` reads it as
    // "nobody vouched" and publishes the name inside the file instead.
    assert.deepEqual(anonymousFrom({ ip: '203.0.113.7' }),
                     { id: 'ip:203.0.113.7', username: '' });
  });

  it('still produces a key when there is no address to use', () => {
    // Rate limiting everyone-without-an-ip as one bucket is worse than
    // nothing per request, but better than a crash or an undefined key that
    // silently exempts them.
    assert.equal(anonymousFrom({}).id, 'ip:unknown');
  });
});

describe('what the server asks for', () => {
  it('does not want Discord credentials it will never use', () => {
    const missing = missingConfig();
    assert.ok(!missing.includes('DISCORD_CLIENT_ID'),
              `got ${missing.join(', ')}`);
    assert.ok(!missing.includes('DISCORD_CLIENT_SECRET'));
  });

  it('still wants the token, because nothing can be pushed without one', () => {
    // Asserted as the only thing missing, which is what makes this test able
    // to fail: with the token *set*, `missing` is empty either way and
    // deleting the check entirely would still pass.
    assert.deepEqual(missingConfig(), ['GITHUB_TOKEN']);
  });
});

describe('the open endpoint', () => {
  let server: Server;
  let base: string;

  before(async () => {
    server = createApp(await Store.open(':memory:')).listen(0);
    await new Promise((r) => server.once('listening', r));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  after(() => { server.close(); });

  it('tells the editor it is open, so Submit can be offered', async () => {
    const body = await (await fetch(`${base}/auth/me`)).json() as
      { signedIn: boolean; openSubmissions: boolean };
    assert.equal(body.signedIn, false);
    assert.equal(body.openSubmissions, true);
  });

  it('does not refuse a stranger', async () => {
    // Past the gate, not past everything: no licence confirmation, so this
    // is a 400 about the licence rather than a 401 about who is asking.
    const form = new FormData();
    form.set('file', new Blob([new Uint8Array([1, 2, 3])]), 'map.json');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form });

    assert.notEqual(res.status, 401, 'an open server has nobody to refuse');
    assert.equal(res.status, 400);
    assert.equal((await res.json()).code, 'no-licence');
  });

  it('still requires the licence confirmation', async () => {
    // The grant of rights has nothing to do with sign-in, and cannot be
    // retrofitted across contributors later.
    const form = new FormData();
    form.set('agree', 'false');
    form.set('file', new Blob([new Uint8Array([1, 2, 3])]), 'map.json');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form });
    assert.equal(res.status, 400);
    assert.equal((await res.json()).code, 'no-licence');
  });

  it('still refuses an upload with no file in it', async () => {
    const form = new FormData();
    form.set('agree', 'true');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form });
    assert.equal(res.status, 400);
    assert.equal((await res.json()).code, 'no-file');
  });

  it('still answers JSON rather than an HTML error page', async () => {
    const res = await fetch(`${base}/no-such-endpoint`);
    assert.match(res.headers.get('content-type') ?? '', /application\/json/);
  });
});

describe('listing submissions with nobody signed in', () => {
  // `signedIn` lets anonymous requests through on an open server, so this
  // route is reachable without an account. It has to refuse rather than
  // answer with an empty list: the editor treats a 200 as the server's
  // record and prefers it to its own, so an empty one erases the only copy
  // of the pull request links an anonymous contributor will ever have.
  let server: Server;
  let base: string;

  before(async () => {
    server = createApp(await Store.open(':memory:')).listen(0);
    await new Promise((r) => server.once('listening', r));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  after(() => { server.close(); });

  it('refuses rather than returning an empty list', async () => {
    const res = await fetch(`${base}/submissions`);
    assert.equal(res.status, 401);
    assert.equal((await res.json() as { code: string }).code,
                 'unauthenticated');
  });
});

describe('when the database is having a bad day', () => {
  // Express 4 does not await a route handler, so a rejected promise inside
  // one answers nobody and, by default, takes the process with it. A locked
  // database, a full disk or a read-only volume all arrive this way, and
  // none of them should cost a reply - least of all an unparseable one, to a
  // client that only reads JSON.
  let server: Server;
  let base: string;

  const broken = {
    async submissionTimesSince(): Promise<string[]> {
      throw new Error('SQLITE_BUSY: database is locked');
    },
    async submissionsFor(): Promise<never[]> {
      throw new Error('SQLITE_BUSY: database is locked');
    },
    async recordSubmission(): Promise<void> {},
    async cachePrStates(): Promise<void> {},
    async cachedPrStates(): Promise<Map<number, unknown>> { return new Map<number, unknown>(); },
    async version(): Promise<number> { return 0; },
    async findByHash(): Promise<null> { return null; },
    async close(): Promise<void> {},
  } as unknown as Store;

  let unhandled: unknown = null;
  const onUnhandled = (e: unknown) => { unhandled = e; };

  before(async () => {
    process.on('unhandledRejection', onUnhandled);
    server = createApp(broken).listen(0);
    await new Promise((r) => server.once('listening', r));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  after(() => {
    server.close();
    process.off('unhandledRejection', onUnhandled);
  });

  it('answers a submission with JSON instead of hanging', async () => {
    const form = new FormData();
    form.set('agree', 'true');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form,
                                                signal: AbortSignal.timeout(4000) });
    assert.equal(res.status, 500);
    assert.match(res.headers.get('content-type') ?? '', /json/);
  });

  it('leaves no unhandled rejection behind', async () => {
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(unhandled, null,
                 'a rejected handler must reach the error middleware');
  });
});

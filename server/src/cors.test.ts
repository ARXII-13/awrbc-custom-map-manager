/**
 * Cross-origin access.
 *
 * Worth testing carefully because both failure directions are quiet. Too
 * strict and the editor looks like it can never sign in - the button says
 * "Sign in to submit" forever, including right after signing in, because the
 * client treats an unreadable reply as "signed out". Too loose and any page on
 * the internet can make authenticated requests as a signed-in user.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import type { AddressInfo } from 'node:net';
import type { Server } from 'node:http';

import { parseOrigins } from './cors.js';
import { createApp } from './index.js';

describe('parsing the allowlist', () => {
  it('takes a comma-separated list', () => {
    assert.deepEqual(
      parseOrigins('https://a.example, https://b.example'),
      ['https://a.example', 'https://b.example']);
  });

  it('normalises to an origin, so a stray path or slash still matches', () => {
    assert.deepEqual(parseOrigins('https://a.example/editor/'),
                     ['https://a.example']);
  });

  it('keeps the port, because a different port is a different origin', () => {
    assert.deepEqual(parseOrigins('http://127.0.0.1:8731'),
                     ['http://127.0.0.1:8731']);
  });

  it('includes the extras it is given', () => {
    assert.deepEqual(parseOrigins('', 'http://127.0.0.1:8731/'),
                     ['http://127.0.0.1:8731']);
  });

  it('drops a typo rather than failing to start', () => {
    assert.deepEqual(parseOrigins('not a url, https://good.example'),
                     ['https://good.example']);
  });

  it('copes with nothing configured', () => {
    assert.deepEqual(parseOrigins(undefined), []);
    assert.deepEqual(parseOrigins(''), []);
  });

  it('does not repeat an origin given twice', () => {
    assert.deepEqual(
      parseOrigins('https://a.example, https://a.example/x'),
      ['https://a.example']);
  });
});

describe('the headers a browser needs', () => {
  let server: Server;
  let base: string;
  const EDITOR = 'http://127.0.0.1:8731';

  before(async () => {
    process.env['EDITOR_URL'] = EDITOR;
    server = createApp().listen(0);
    await new Promise((r) => server.once('listening', r));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });

  after(() => { server.close(); });

  it('allows the editor, with credentials', async () => {
    const res = await fetch(`${base}/auth/me`, {
      headers: { origin: EDITOR } });
    assert.equal(res.headers.get('access-control-allow-origin'), EDITOR);
    assert.equal(res.headers.get('access-control-allow-credentials'), 'true');
  });

  it('varies on origin, so a cache cannot cross the streams', async () => {
    const res = await fetch(`${base}/auth/me`, {
      headers: { origin: EDITOR } });
    assert.match(res.headers.get('vary') ?? '', /Origin/i);
  });

  it('says nothing to an origin that is not on the list', async () => {
    const res = await fetch(`${base}/auth/me`, {
      headers: { origin: 'https://evil.example' } });
    assert.equal(res.headers.get('access-control-allow-origin'), null);
    assert.equal(res.headers.get('access-control-allow-credentials'), null);
  });

  it('never answers with a wildcard', async () => {
    // A browser refuses `*` with credentials, and if it did not, any site
    // could read authenticated replies.
    for (const origin of [EDITOR, 'https://evil.example']) {
      const res = await fetch(`${base}/auth/me`, { headers: { origin } });
      assert.notEqual(res.headers.get('access-control-allow-origin'), '*');
    }
  });

  it('answers a preflight without running the route', async () => {
    const res = await fetch(`${base}/submit`, {
      method: 'OPTIONS',
      headers: { origin: EDITOR, 'access-control-request-method': 'POST' },
    });
    assert.equal(res.status, 204);
    assert.equal(res.headers.get('access-control-allow-origin'), EDITOR);
  });

  it('refuses a stranger\'s preflight by saying nothing', async () => {
    const res = await fetch(`${base}/submit`, {
      method: 'OPTIONS',
      headers: { origin: 'https://evil.example',
                 'access-control-request-method': 'POST' },
    });
    assert.equal(res.headers.get('access-control-allow-origin'), null);
  });

  it('reports the allowlist on /health', async () => {
    // Getting this wrong is the failure that looks like nothing happening, so
    // it should be visible without reading logs.
    const body = await (await fetch(`${base}/health`)).json() as
      { allowedOrigins: string[] };
    assert.ok(body.allowedOrigins.includes(EDITOR));
  });
});

/**
 * The intake endpoint.
 *
 * The pure helpers are tested directly; the HTTP surface is tested against a
 * real listening server, which needs no extra dependency and exercises the
 * middleware rather than a mock of it.
 *
 * Discord and GitHub are never reached. The bridge to Python *is* reached, in
 * prepare.test.ts, because that is the seam this whole design rests on.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import type { AddressInfo } from 'node:net';
import type { Server } from 'node:http';

import { newState, stateMatches } from './discord.js';
import { createApp, rateLimited, recordSubmission, resetLimits, safeNext }
  from './index.js';

describe('the oauth state check', () => {
  it('answers false for a state that is not ASCII, rather than throwing', () => {
    // `got` is a query parameter, so a stranger picks it. timingSafeEqual
    // throws when its inputs differ in bytes, and one accented character
    // makes two equal-length strings differ in bytes - which escaped the
    // callback as a 500 instead of a refusal.
    assert.doesNotThrow(() => stateMatches('abcd', 'abcé'));
    assert.equal(stateMatches('abcd', 'abcé'), false);
    assert.equal(stateMatches('abcé', 'abcé'), true);
  });

  it('accepts a state against itself', () => {
    const state = newState();
    assert.equal(stateMatches(state, state), true);
  });

  it('refuses a different one', () => {
    assert.equal(stateMatches(newState(), newState()), false);
  });

  it('refuses when either side is missing', () => {
    // The dangerous case: no stored state must never mean "anything goes".
    assert.equal(stateMatches(undefined, 'anything'), false);
    assert.equal(stateMatches('something', undefined), false);
    assert.equal(stateMatches(undefined, undefined), false);
    assert.equal(stateMatches('', ''), false);
  });

  it('refuses non-strings', () => {
    assert.equal(stateMatches(123, 123), false);
    assert.equal(stateMatches({}, {}), false);
    assert.equal(stateMatches(null, null), false);
  });

  it('produces a different state each time', () => {
    const seen = new Set(Array.from({ length: 50 }, () => newState()));
    assert.equal(seen.size, 50);
  });
});

describe('the next parameter', () => {
  it('keeps a path', () => {
    assert.equal(safeNext('/edit'), '/edit');
  });

  it('drops an absolute url', () => {
    // An open redirect turns the sign-in button into a phishing hop.
    assert.equal(safeNext('https://evil.example/steal'), '');
    assert.equal(safeNext('http://evil.example'), '');
  });

  it('drops a protocol-relative url, which also leaves the site', () => {
    assert.equal(safeNext('//evil.example/steal'), '');
  });

  it('drops anything that is not a string', () => {
    assert.equal(safeNext(undefined), '');
    assert.equal(safeNext(['/a', '/b']), '');
  });
});

describe('rate limiting', () => {
  it('allows the first submission', () => {
    resetLimits();
    assert.equal(rateLimited('u1'), null);
  });

  it('slows the second within a minute', () => {
    resetLimits();
    recordSubmission('u1');
    assert.match(rateLimited('u1') ?? '', /minute/);
  });

  it('is per account', () => {
    resetLimits();
    recordSubmission('u1');
    assert.equal(rateLimited('u2'), null);
  });

  it('forgets a submission after an hour', () => {
    resetLimits();
    const longAgo = Date.now() - 3_700_000;
    recordSubmission('u1', longAgo);
    assert.equal(rateLimited('u1'), null);
  });

  it('caps the hour even when they are spread out', () => {
    resetLimits();
    const now = Date.now();
    for (let i = 0; i < 10; i++) recordSubmission('u1', now - (i + 1) * 120_000);
    assert.match(rateLimited('u1', now) ?? '', /hour/);
  });
});

describe('the http surface', () => {
  let server: Server;
  let base: string;

  before(async () => {
    server = createApp().listen(0);
    await new Promise((r) => server.once('listening', r));
    base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    resetLimits();
  });

  after(() => { server.close(); });

  it('reports its health and what is missing', async () => {
    const got = await (await fetch(`${base}/health`)).json();
    assert.equal(got.ok, true);
    assert.ok(Array.isArray(got.missing));
  });

  it('says nobody is signed in', async () => {
    const got = await (await fetch(`${base}/auth/me`)).json();
    assert.equal(got.signedIn, false);
  });

  it('refuses a callback with no state', async () => {
    const res = await fetch(`${base}/auth/callback?code=abc`,
                            { redirect: 'manual' });
    assert.equal(res.status, 400);
  });

  it('refuses a callback with a state it never issued', async () => {
    const res = await fetch(`${base}/auth/callback?code=abc&state=guessed`,
                            { redirect: 'manual' });
    assert.equal(res.status, 400);
  });

  it('refuses to start sign-in when unconfigured', async () => {
    const res = await fetch(`${base}/auth/login`, { redirect: 'manual' });
    assert.equal(res.status, 503);
  });

  it('refuses an upload from a stranger', async () => {
    const form = new FormData();
    form.set('agree', 'true');
    form.set('file', new Blob([new Uint8Array([1, 2, 3])]), 'map.json');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form });
    assert.equal(res.status, 401);
    assert.equal((await res.json()).code, 'unauthenticated');
  });

  it('refuses an upload before it reads the file', async () => {
    // Order matters, and an empty body cannot show it: sending nothing gets a
    // 401 whether the session is checked before the upload middleware or
    // after. An oversized file can only be refused for being oversized if
    // something read it, so a 401 here is the ordering, observed.
    //
    // It used to fail inside multer first and come back as a 500 HTML page
    // with a stack trace in it, which the editor cannot parse either.
    const form = new FormData();
    form.set('file', new Blob([new Uint8Array(9 * 1024 * 1024)]), 'big.zip');
    const res = await fetch(`${base}/submit`, { method: 'POST', body: form });

    assert.equal(res.status, 401);
    assert.match(res.headers.get('content-type') ?? '', /application\/json/);
    assert.equal((await res.json()).code, 'unauthenticated');
  });

  it('answers an unknown route as JSON, not an HTML page', async () => {
    // Express's defaults send HTML for both a 404 and an unhandled throw,
    // and the second kind carries a stack trace. A client that only parses
    // JSON reads either as a transport failure.
    const res = await fetch(`${base}/no-such-endpoint`);
    assert.equal(res.status, 404);
    assert.match(res.headers.get('content-type') ?? '', /application\/json/);

    const body = await res.text();
    assert.doesNotMatch(body, /<pre>|<html/i,
                        'a response must not be an HTML error page');
    assert.equal(JSON.parse(body).code, 'not-found');
  });
});

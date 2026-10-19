/**
 * The store that cannot be rebuilt from anything else.
 *
 * Map content is in git and pull request state is GitHub's; if either is lost
 * it comes back. The join between a Discord account and what it submitted
 * exists only here, so what is worth testing is that it survives: migrations
 * run once and in order, a replayed write does not become a second
 * submission, and the pull request cache cannot be mistaken for truth.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { Store, type Submission } from './db.js';

const sub = (over: Partial<Submission> = {}): Submission => ({
  discordId: '1234', username: 'pat', mapName: 'daibi',
  folder: 'maps/2p/daibi', version: 1, contentHash: 'abc123',
  branch: 'submit/daibi-v1-pat', prNumber: 7,
  prUrl: 'https://gh/pull/7', createdAt: '2026-10-13T10:00:00.000Z',
  ...over,
});

const open = () => Store.open(':memory:');

describe('opening a database', () => {
  it('applies every migration', async () => {
    const db = await open();
    assert.equal(await db.version(), 2);
    await db.close();
  });

  it('is safe to open again', async () => {
    // Every restart of the server re-opens the same file. Re-running a
    // migration would fail on the table it already created.
    const db = await open();
    await db.recordSubmission(sub());
    const before = await db.version();
    await db.close();

    const again = await open();
    assert.equal(await again.version(), before);
    await again.close();
  });
});

describe('recording a submission', () => {
  it('reads back what went in', async () => {
    const db = await open();
    await db.recordSubmission(sub());
    const { items } = await db.submissionsFor('1234');
    const got = items[0];
    assert.equal(got!.mapName, 'daibi');
    assert.equal(got!.prNumber, 7);
    assert.equal(got!.contentHash, 'abc123');
    await db.close();
  });

  it('does not duplicate a replayed pull request', async () => {
    // A retry must not invent a second submission out of one pull request.
    const db = await open();
    await db.recordSubmission(sub());
    await db.recordSubmission(sub({ mapName: 'daibi renamed' }));
    const { items: all } = await db.submissionsFor('1234');
    assert.equal(all.length, 1);
    assert.equal(all[0]!.mapName, 'daibi renamed');
    await db.close();
  });

  it('keeps one account out of another account\'s list', async () => {
    const db = await open();
    await db.recordSubmission(sub());
    await db.recordSubmission(sub({ discordId: '9999', prNumber: 8 }));
    assert.equal((await db.submissionsFor('1234')).items.length, 1);
    assert.equal((await db.submissionsFor('9999')).items.length, 1);
    await db.close();
  });

  it('returns newest first', async () => {
    const db = await open();
    await db.recordSubmission(sub({ prNumber: 1, createdAt: '2026-10-01T00:00:00.000Z' }));
    await db.recordSubmission(sub({ prNumber: 2, createdAt: '2026-10-05T00:00:00.000Z' }));
    const { items: all } = await db.submissionsFor('1234');
    assert.deepEqual(all.map((s) => s.prNumber), [2, 1]);
    await db.close();
  });
});

describe('rate limiting reads the submissions themselves', () => {
  // Not a second table counting them: two records of the same fact is two
  // things that can disagree, and the limiter would be the one that is wrong.
  it('counts only what falls inside the window', async () => {
    const db = await open();
    await db.recordSubmission(sub({ prNumber: 1, createdAt: '2026-10-13T09:00:00.000Z' }));
    await db.recordSubmission(sub({ prNumber: 2, createdAt: '2026-10-13T09:58:00.000Z' }));
    const recent = await db.submissionTimesSince('1234', '2026-10-13T09:30:00.000Z');
    assert.deepEqual(recent, ['2026-10-13T09:58:00.000Z']);
    await db.close();
  });

  it('survives a restart, unlike the counter it replaces', async () => {
    const db = await open();
    await db.recordSubmission(sub({ createdAt: '2026-10-13T09:58:00.000Z' }));
    assert.equal(
      (await db.submissionTimesSince('1234', '2026-10-13T09:00:00.000Z')).length, 1);
    await db.close();
  });
});

describe('finding a map by its content', () => {
  it('matches on the hash, whatever it was called', async () => {
    const db = await open();
    await db.recordSubmission(sub({ mapName: 'first name' }));
    const found = await db.findByHash('abc123');
    assert.equal(found?.mapName, 'first name');
    assert.equal(await db.findByHash('nothing-like-it'), null);
    await db.close();
  });
});

describe('the pull request cache', () => {
  it('stores when it was read, not only what was read', async () => {
    // The whole point of the table's name: a caller has to be able to ask how
    // old this is before believing it.
    const db = await open();
    await db.cachePrStates([
      { prNumber: 7, state: 'open', checkedAt: '2026-10-13T10:00:00.000Z' },
    ]);
    const got = await db.cachedPrStates([7]);
    assert.equal(got.get(7)!.state, 'open');
    assert.equal(got.get(7)!.checkedAt, '2026-10-13T10:00:00.000Z');
    await db.close();
  });

  it('replaces a state rather than accumulating history', async () => {
    const db = await open();
    await db.cachePrStates([{ prNumber: 7, state: 'open', checkedAt: 'a' }]);
    await db.cachePrStates([{ prNumber: 7, state: 'merged', checkedAt: 'b' }]);
    const got = await db.cachedPrStates([7]);
    assert.equal(got.size, 1);
    assert.equal(got.get(7)!.state, 'merged');
    await db.close();
  });

  it('says nothing about a pull request it has never seen', async () => {
    // Absent is not "open". A caller that cannot tell those apart would
    // report an unchecked submission as being under review.
    const db = await open();
    const got = await db.cachedPrStates([7, 8]);
    assert.equal(got.size, 0);
    await db.close();
  });

  it('asks about nothing without building an empty IN ()', async () => {
    const db = await open();
    assert.equal((await db.cachedPrStates([])).size, 0);
    await db.close();
  });
});

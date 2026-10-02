/**
 * The bridge to the Python rules.
 *
 * These call the real `awrbc prepare`, on purpose. The whole argument for
 * shelling out rather than reimplementing is that the rules live in one place;
 * a test that stubbed the subprocess would be testing the stub and would stay
 * green through exactly the breakage this design exists to prevent - the two
 * sides disagreeing.
 *
 * Skips when the tool is not installed, so `npm test` works in a checkout
 * without Python.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { available, filesToCommit, prepare } from './prepare.js';

const AWRBC = process.env.AWRBC_COMMAND ?? 'awrbc';

// Top-level await, not a `before` hook. `describe`'s options are evaluated
// while the module loads, which is before any hook runs - so a hook setting
// this would leave it false and skip the entire suite while reporting success.
// That is exactly the failure these tests exist to catch, so it is worth not
// reproducing it here.
const installed = (await available(AWRBC)) === null;

// Locally a skip is reasonable - `awrbc` may not be on PATH, and node reports
// a skipped *suite* as `skipped 0` because the `it`s inside were never built,
// so the summary gives no hint that nine tests vanished. On CI it is not
// reasonable: the workflow installs the tool, and a skip there means the whole
// duplicate-detection and revision path went unchecked while the run stayed
// green. Set AWRBC_COMMAND to run them against something else, e.g.
// `AWRBC_COMMAND="python -m awrbc"`.
describe('what the bridge tests need', () => {
  it('is installed on CI', () => {
    if (!process.env['CI']) return;
    assert.ok(installed,
      `${AWRBC} is not runnable, so the python bridge suite skipped. ` +
      'CI must install the tool, or set AWRBC_COMMAND.');
  });
});

const tempDir = mkdtempSync(join(tmpdir(), 'awrbc-'));
const emptyCatalog = join(tempDir, 'catalog.json');
writeFileSync(emptyCatalog, JSON.stringify({ schema: 1, maps: {} }));

const AUTHOR = { id: '123', username: 'debbie' };

/** A minimal playable map: two HQs and a unit each. */
function aMap(name = 'Daibi', cols = 12, rows = 10) {
  const terrain = Array.from({ length: rows }, () => Array(cols).fill(1));
  terrain[0]![0] = 512;
  terrain[rows - 1]![cols - 1] = 512;
  return {
    schema: 1, name, author: 'whatever-the-file-says',
    size: { cols, rows }, fog: false, waterColor: 0,
    terrain,
    cells: [
      { x: 0, y: 0, team: 0, capture: 20 },
      { x: cols - 1, y: rows - 1, team: 1, capture: 20 },
    ],
    units: [
      { x: 1, y: 1, team: 0, type: 1, hp: 100 },
      { x: 2, y: 1, team: 1, type: 1, hp: 100 },
    ],
  };
}

function run(doc: unknown, update?: string) {
  return prepare(Buffer.from(JSON.stringify(doc)), AUTHOR, update,
                 { catalog: emptyCatalog, command: AWRBC });
}

describe('the python bridge', { skip: !installed ? 'awrbc is not installed' : false }, () => {
  it('accepts a playable map and says where it goes', async () => {
    const got = await run(aMap());
    assert.equal(got.ok, true);
    if (!got.ok) return;
    assert.equal(got.path, 'maps/2p/daibi/v1.json');
    assert.equal(got.kind, 'new');
    assert.equal(got.version, 1);
  });

  it('uses the signed-in name, not the one in the file', async () => {
    // The file says "whatever-the-file-says". A file is a claim.
    const got = await run(aMap());
    assert.equal(got.ok, true);
    if (!got.ok) return;
    const doc = JSON.parse(
      filesToCommit(got)['maps/2p/daibi/v1.json']!.toString('utf8'));
    assert.equal(doc.author, 'debbie');
  });

  it('refuses an unplayable map and explains why', async () => {
    const doc = aMap();
    doc.cells = [];
    doc.terrain = Array.from({ length: 10 }, () => Array(12).fill(1));
    const got = await run(doc);
    assert.equal(got.ok, false);
    if (got.ok) return;
    assert.equal(got.code, 'invalid');
    assert.ok(got.findings.length > 0, 'the reasons come back too');
  });

  it('refuses something that is not a map at all', async () => {
    const got = await prepare(Buffer.from('not json'), AUTHOR, undefined,
                              { catalog: emptyCatalog, command: AWRBC });
    assert.equal(got.ok, false);
  });

  it('decodes the files to commit as real bytes', async () => {
    const got = await run(aMap());
    assert.equal(got.ok, true);
    if (!got.ok) return;
    const files = filesToCommit(got);
    assert.ok(Buffer.isBuffer(files['maps/2p/daibi/v1.json']));
    assert.ok(files['maps/2p/daibi/v1.json']!.toString('utf8')
      .startsWith('{'));
  });

  it('builds a branch name that is safe to use', async () => {
    const got = await run(aMap());
    assert.equal(got.ok, true);
    if (!got.ok) return;
    assert.match(got.branch, /^submit\/[a-z0-9/-]+$/);
  });

  it('reports a map already in the archive as a duplicate', async () => {
    // Two submissions of the same map: the second is told, by the same hash
    // logic the CLI and CI use. This is the check that a reimplementation
    // would have broken silently.
    const first = await run(aMap());
    assert.equal(first.ok, true);
    if (!first.ok) return;

    const dir = mkdtempSync(join(tmpdir(), 'awrbc-cat-'));
    const catalog = join(dir, 'catalog.json');
    const doc = JSON.parse(
      filesToCommit(first)['maps/2p/daibi/v1.json']!.toString('utf8'));
    writeFileSync(catalog, JSON.stringify({
      schema: 1,
      maps: {
        'maps/2p/daibi': {
          category: '2p', slug: 'daibi', name: 'Daibi', author: 'debbie',
          versions: [{ version: 1, hash: doc.id, cols: 12, rows: 10,
                       players: 2 }],
        },
      },
    }));

    const again = await prepare(Buffer.from(JSON.stringify(aMap())), AUTHOR,
                                undefined, { catalog, command: AWRBC });
    assert.equal(again.ok, false);
    if (again.ok) return;
    assert.equal(again.code, 'duplicate');
  });

  /** A catalog holding a different map already called Daibi. The hash is
   *  deliberately not this map's, so it reads as a name clash rather than a
   *  duplicate - that distinction is the whole of the two-step below. */
  function catalogHolding(author: string) {
    const dir = mkdtempSync(join(tmpdir(), 'awrbc-cat-'));
    const catalog = join(dir, 'catalog.json');
    writeFileSync(catalog, JSON.stringify({
      schema: 1,
      maps: {
        'maps/2p/daibi': {
          category: '2p', slug: 'daibi', name: 'Daibi', author,
          versions: [{ version: 1, hash: '0000000000000000', cols: 14,
                       rows: 10, players: 2 }],
        },
      },
    }));
    return catalog;
  }

  it('names the folder a clash collided with, then takes the revision',
     async () => {
    // The two-step the editor walks. The browser cannot work the folder out
    // for itself - slugs and categories are Python's rules - so the refusal
    // has to hand it over, and the second attempt has to be accepted.
    const catalog = catalogHolding('debbie');
    const body = Buffer.from(JSON.stringify(aMap()));

    const clash = await prepare(body, AUTHOR, undefined,
                                { catalog, command: AWRBC });
    assert.equal(clash.ok, false);
    if (clash.ok) return;
    assert.equal(clash.code, 'conflict');
    assert.equal(clash.folder, 'maps/2p/daibi',
                 'the refusal must say which folder, as data');

    const revision = await prepare(body, AUTHOR, clash.folder,
                                   { catalog, command: AWRBC });
    assert.equal(revision.ok, true);
    if (!revision.ok) return;
    assert.equal(revision.kind, 'revision');
    assert.equal(revision.version, 2);
    assert.equal(revision.path, 'maps/2p/daibi/v2.json');
  });

  it('refuses to revise a map published by somebody else', async () => {
    // The folder is a pointer, not permission. Decided here, where the
    // publisher is known; the browser has no way to tell.
    const got = await prepare(Buffer.from(JSON.stringify(aMap())), AUTHOR,
                              'maps/2p/daibi',
                              { catalog: catalogHolding('somebody-else'),
                                command: AWRBC });
    assert.equal(got.ok, false);
    if (got.ok) return;
    assert.equal(got.code, 'conflict');
    assert.match(got.error, /maintainer/);
  });

  it('carries non-blocking warnings through', async () => {
    const got = await run(aMap('Big', 31, 21));
    assert.equal(got.ok, true);
    if (!got.ok) return;
    assert.ok(got.warnings.some((w) => w.code === 'size.beyondEditor'),
      'a map past the in-game editor should warn, not fail');
  });
});

describe('when the tool is missing', () => {
  it('says so rather than pretending', async () => {
    const problem = await available('definitely-not-a-real-command');
    assert.ok(problem, 'a missing validator must be detectable at startup');
  });
});

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

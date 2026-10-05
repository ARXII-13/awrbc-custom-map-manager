// The zip writer.
//
// Hand-written, so nothing else in the stack would notice if it produced
// something only *nearly* valid. It was cross-checked against Python's
// `zipfile` once by hand; `tests/test_zip_interop.py` now does that
// automatically. These cover the structure without leaving node.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { mapFromBundle, unzip, zip } from '../zip.js';

const LOCAL = 0x04034b50;
const CENTRAL = 0x02014b50;
const END = 0x06054b50;

async function bytes(blob) {
  return new Uint8Array(await blob.arrayBuffer());
}

function u16(b, at) {
  return b[at] | (b[at + 1] << 8);
}

function u32(b, at) {
  return (b[at] | (b[at + 1] << 8) | (b[at + 2] << 16) | (b[at + 3] << 24)) >>> 0;
}

/** Walk the local headers, which is what every unzipper does first. */
function entries(b) {
  const out = [];
  let at = 0;
  while (at + 30 <= b.length && u32(b, at) === LOCAL) {
    const nameLen = u16(b, at + 26);
    const extraLen = u16(b, at + 28);
    const size = u32(b, at + 18);
    const name = new TextDecoder().decode(
      b.subarray(at + 30, at + 30 + nameLen));
    const start = at + 30 + nameLen + extraLen;
    out.push({
      name,
      flags: u16(b, at + 6),
      method: u16(b, at + 8),
      crc: u32(b, at + 14),
      data: b.subarray(start, start + size),
    });
    at = start + size;
  }
  return out;
}

describe('a zip', () => {
  it('starts with a local header and ends with a central directory', async () => {
    const b = await bytes(zip({ 'a.txt': 'hello' }));
    assert.equal(u32(b, 0), LOCAL);
    assert.equal(u32(b, b.length - 22), END,
      'the end-of-central-directory record must be last');
  });

  it('round-trips text', async () => {
    const b = await bytes(zip({ 'map.json': '{"name":"Daibi"}' }));
    const [e] = entries(b);
    assert.equal(e.name, 'map.json');
    assert.equal(new TextDecoder().decode(e.data), '{"name":"Daibi"}');
  });

  it('round-trips binary without mangling it', async () => {
    // A PNG starts with a high byte and carries NULs; anything treating this
    // as text corrupts it.
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
                                0x00, 0xff, 0x00, 0xff]);
    const b = await bytes(zip({ 'preview.png': png }));
    const [e] = entries(b);
    assert.deepEqual(Array.from(e.data), Array.from(png));
  });

  it('keeps entries in the order they were given', async () => {
    const b = await bytes(zip({
      'map.json': '{}', 'preview.png': new Uint8Array([1, 2, 3]),
    }));
    assert.deepEqual(entries(b).map((e) => e.name),
      ['map.json', 'preview.png']);
  });

  it('stores rather than compresses', async () => {
    const b = await bytes(zip({ 'a.txt': 'x'.repeat(500) }));
    const [e] = entries(b);
    assert.equal(e.method, 0, 'method 0 is stored');
    assert.equal(e.data.length, 500);
  });

  it('flags names as UTF-8 and round-trips a non-ASCII one', async () => {
    const b = await bytes(zip({ 'マップ.json': '{}' }));
    const [e] = entries(b);
    assert.equal(e.flags & 0x0800, 0x0800, 'bit 11 says the name is UTF-8');
    assert.equal(e.name, 'マップ.json');
  });

  it('writes a CRC that matches the data', async () => {
    // Recomputed here rather than trusted: a zip with a wrong CRC opens in
    // some tools and fails in others, which is the worst kind of broken.
    const table = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
    const crc32 = (d) => {
      let c = 0xFFFFFFFF;
      for (const byte of d) c = table[(c ^ byte) & 0xFF] ^ (c >>> 8);
      return (c ^ 0xFFFFFFFF) >>> 0;
    };

    const payload = 'the quick brown fox';
    const b = await bytes(zip({ 'a.txt': payload }));
    const [e] = entries(b);
    assert.equal(e.crc, crc32(new TextEncoder().encode(payload)));
  });

  it('counts its entries in the end record', async () => {
    const b = await bytes(zip({ 'a': '1', 'b': '2', 'c': '3' }));
    assert.equal(u16(b, b.length - 22 + 8), 3);
    assert.equal(u16(b, b.length - 22 + 10), 3);
  });

  it('has one central directory header per entry', async () => {
    const b = await bytes(zip({ 'a': '1', 'b': '2' }));
    let found = 0;
    for (let at = 0; at + 4 <= b.length; at++) {
      if (u32(b, at) === CENTRAL) found++;
    }
    assert.equal(found, 2);
  });

  it('handles an empty file', async () => {
    const b = await bytes(zip({ 'empty.txt': '' }));
    const [e] = entries(b);
    assert.equal(e.data.length, 0);
    assert.equal(e.crc, 0, 'the CRC of nothing is zero');
  });

  it('is deterministic when given a fixed timestamp', async () => {
    const when = new Date(2026, 0, 2, 3, 4, 6);
    const a = await bytes(zip({ 'a.txt': 'x' }, when));
    const b = await bytes(zip({ 'a.txt': 'x' }, when));
    assert.deepEqual(Array.from(a), Array.from(b));
  });
});

describe('reading one back', () => {
  // The editor could write a bundle and not open one, so a map exported that
  // way had no road home - Open took a bare .json only. These go through the
  // writer and back, because a reader tested against hand-built bytes can
  // agree with a writer that is wrong.

  const aMap = {
    schema: 1, name: 'Twin Rivers', author: 'debbie',
    size: { cols: 12, rows: 10 }, fog: false, waterColor: 0,
    terrain: [[1, 2], [2, 1]], cells: [{ x: 1, y: 1, team: 0 }], units: [],
  };

  const bundle = () => zip({
    'map.json': JSON.stringify(aMap, null, 1),
    'preview.png': new Uint8Array([0x89, 0x50, 0x4E, 0x47, 1, 2, 3]).buffer,
  });

  it('finds every file that was put in', async () => {
    const got = await unzip(await bundle().arrayBuffer());
    assert.deepEqual(Object.keys(got).sort(), ['map.json', 'preview.png']);
  });

  it('gives back exactly the bytes that went in', async () => {
    const got = await unzip(await bundle().arrayBuffer());
    assert.deepEqual([...got['preview.png']], [0x89, 0x50, 0x4E, 0x47, 1, 2, 3]);
  });

  it('round-trips the map itself', async () => {
    const got = await mapFromBundle(await bundle().arrayBuffer());
    assert.deepEqual(got, aMap);
  });

  it('survives a zip comment', async () => {
    // Ours never has one; somebody else's might, and the end-of-central
    // record is then not at the very end.
    const raw = new Uint8Array(await bundle().arrayBuffer());
    const commented = new Uint8Array(raw.length + 5);
    commented.set(raw);
    commented.set([0x68, 0x69, 0x21, 0x21, 0x21], raw.length);
    // The comment length field has to agree, or it is a damaged zip.
    const view = new DataView(commented.buffer);
    view.setUint16(raw.length - 2, 5, true);
    assert.deepEqual(await mapFromBundle(commented.buffer), aMap);
  });

  it('refuses something that is not a zip at all', async () => {
    const junk = new TextEncoder().encode('this is a map, honest').buffer;
    await assert.rejects(() => mapFromBundle(junk), /not a zip/);
  });

  it('refuses a zip with no map in it', async () => {
    const other = await zip({ 'notes.txt': 'nothing to do with maps' })
      .arrayBuffer();
    await assert.rejects(() => mapFromBundle(other), /no map\.json/);
  });

  it('finds a map.json inside a folder', async () => {
    // Some tools add one when re-zipping.
    const nested = zip({ 'bundle/map.json': JSON.stringify(aMap) });
    assert.deepEqual(await mapFromBundle(await nested.arrayBuffer()), aMap);
  });
});

describe('a zip somebody else made', () => {
  // Our own writer puts the same extra field in the local header and the
  // central entry, so the two agree and a reader that confuses them still
  // works - on our bundles. Other tools pad the local header (alignment,
  // timestamps), and then the data does not start where the central entry
  // implies. Built by hand here because our writer cannot produce it.

  const aMap = { schema: 1, name: 'Padded', size: { cols: 2, rows: 2 } };

  /** Our zip, with `pad` bytes of extra spliced into the local header. */
  async function withLocalExtra(pad) {
    const raw = new Uint8Array(
      await zip({ 'map.json': JSON.stringify(aMap) }).arrayBuffer());
    const view = new DataView(raw.buffer);

    const nameLen = u16(raw, 26);
    const extraLen = u16(raw, 28);
    const dataAt = 30 + nameLen + extraLen;

    const out = new Uint8Array(raw.length + pad);
    out.set(raw.subarray(0, dataAt), 0);              // header
    out.set(new Uint8Array(pad).fill(0xAA), dataAt);  // the padding
    out.set(raw.subarray(dataAt), dataAt + pad);      // everything after

    const edit = new DataView(out.buffer);
    edit.setUint16(28, extraLen + pad, true);         // local extra length

    // One entry, so only the central directory's own offset moves.
    const end = out.length - 22;
    edit.setUint32(end + 16, u32(raw, raw.length - 22 + 16) + pad, true);
    return out.buffer;
  }

  it('reads it, because the data offset comes from the local header',
     async () => {
    assert.deepEqual(await mapFromBundle(await withLocalExtra(16)), aMap);
  });

  it('reads it whatever the padding is', async () => {
    for (const pad of [1, 7, 64]) {
      assert.deepEqual(await mapFromBundle(await withLocalExtra(pad)), aMap,
                       `failed with ${pad} bytes of local extra`);
    }
  });
});

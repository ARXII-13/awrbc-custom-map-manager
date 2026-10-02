// The zip writer.
//
// Hand-written, so nothing else in the stack would notice if it produced
// something only *nearly* valid. It was cross-checked against Python's
// `zipfile` once by hand; `tests/test_zip_interop.py` now does that
// automatically. These cover the structure without leaving node.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { zip } from '../zip.js';

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

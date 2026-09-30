// A minimal zip writer.
//
// Store-only: no compression. The two things a bundle holds are JSON and a PNG
// - one already compresses poorly at this size and the other is compressed
// already - so deflate would buy a few percent in exchange for pulling in a
// compression library. The editor ships as a static page with no build step
// and no dependencies, and this keeps it that way.
//
// Produces the classic 32-bit format: no zip64, no encryption, no directory
// entries. That is every zip tool in existence, for archives under 4 GB.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) {
    c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  }
  return (c ^ 0xFFFFFFFF) >>> 0;
}

/** MS-DOS date and time, which is what a zip header carries. */
function dosStamp(date) {
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) |
          (date.getSeconds() >> 1),
    date: ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) |
          date.getDate(),
  };
}

function bytesOf(content) {
  return typeof content === 'string'
    ? new TextEncoder().encode(content)
    : new Uint8Array(content);
}

/**
 * Build a zip from `{ name: string | Uint8Array | ArrayBuffer }`.
 *
 * Returns a Blob. Entry order is the order of the object's keys, which is what
 * decides how a file manager lists them.
 */
export function zip(files, when = new Date()) {
  const stamp = dosStamp(when);
  const parts = [];
  const central = [];
  let offset = 0;

  for (const [name, content] of Object.entries(files)) {
    const nameBytes = new TextEncoder().encode(name);
    const data = bytesOf(content);
    const sum = crc32(data);

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034B50, true);       // local file header
    local.setUint16(4, 20, true);               // version needed
    local.setUint16(6, 0x0800, true);           // UTF-8 names
    local.setUint16(8, 0, true);                // stored
    local.setUint16(10, stamp.time, true);
    local.setUint16(12, stamp.date, true);
    local.setUint32(14, sum, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, nameBytes.length, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, data);

    const entry = new DataView(new ArrayBuffer(46));
    entry.setUint32(0, 0x02014B50, true);       // central directory header
    entry.setUint16(4, 20, true);               // version made by
    entry.setUint16(6, 20, true);
    entry.setUint16(8, 0x0800, true);
    entry.setUint16(10, 0, true);
    entry.setUint16(12, stamp.time, true);
    entry.setUint16(14, stamp.date, true);
    entry.setUint32(16, sum, true);
    entry.setUint32(20, data.length, true);
    entry.setUint32(24, data.length, true);
    entry.setUint16(28, nameBytes.length, true);
    entry.setUint32(42, offset, true);          // where its local header is
    central.push(new Uint8Array(entry.buffer), nameBytes);

    offset += 30 + nameBytes.length + data.length;
  }

  const centralSize = central.reduce((n, p) => n + p.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054B50, true);           // end of central directory
  end.setUint16(8, Object.keys(files).length, true);
  end.setUint16(10, Object.keys(files).length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);

  return new Blob([...parts, ...central, new Uint8Array(end.buffer)],
                  { type: 'application/zip' });
}

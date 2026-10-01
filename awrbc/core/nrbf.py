"""Lossless MS-NRBF (.NET BinaryFormatter) reader/writer.

Parses to a record tree that preserves the exact stream encoding (record kinds,
object ids, null-run encoding) so that write(parse(x)) == x byte-for-byte.
"""
import struct

# PrimitiveTypeEnum (4 is unused in the spec)
PRIM = {1: 'Boolean', 2: 'Byte', 3: 'Char', 5: 'Decimal', 6: 'Double', 7: 'Int16',
        8: 'Int32', 9: 'Int64', 10: 'SByte', 11: 'Single', 12: 'TimeSpan',
        13: 'DateTime', 14: 'UInt16', 15: 'UInt32', 16: 'UInt64', 17: 'Null',
        18: 'String'}


class Rec:
    __slots__ = ('rt', 'd')

    def __init__(self, rt, **d):
        self.rt, self.d = rt, d

    def __repr__(self):
        return 'Rec(%d,%s)' % (self.rt, list(self.d))


# --------------------------------------------------------------------- read
class R:
    def __init__(self, d):
        self.d, self.p = d, 0

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def i8(self):
        v = struct.unpack_from('<b', self.d, self.p)[0]; self.p += 1; return v

    def i16(self):
        v = struct.unpack_from('<h', self.d, self.p)[0]; self.p += 2; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def i64(self):
        v = struct.unpack_from('<q', self.d, self.p)[0]; self.p += 8; return v

    def u64(self):
        v = struct.unpack_from('<Q', self.d, self.p)[0]; self.p += 8; return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]; self.p += 4; return v

    def f64(self):
        v = struct.unpack_from('<d', self.d, self.p)[0]; self.p += 8; return v

    def varint(self):
        r = s = 0
        while True:
            b = self.u8()
            r |= (b & 0x7f) << s
            s += 7
            if not b & 0x80:
                return r

    def string(self):
        n = self.varint()
        v = self.d[self.p:self.p + n].decode('utf-8')
        self.p += n
        return v

    def char(self):
        b = self.d[self.p]
        n = 1 if b < 0x80 else 2 if b < 0xE0 else 3 if b < 0xF0 else 4
        v = self.d[self.p:self.p + n].decode('utf-8')
        self.p += n
        return v

    def prim(self, pt):
        return {1: lambda: self.u8() != 0, 2: self.u8, 3: self.char, 5: self.string,
                6: self.f64, 7: self.i16, 8: self.i32, 9: self.i64, 10: self.i8,
                11: self.f32, 12: self.i64, 13: self.u64, 14: self.u16,
                15: self.u32, 16: self.u64, 18: self.string}[pt]()


class Parser:
    def __init__(self, data):
        self.r = R(data)
        self.records = []
        self.classes = {}
        self.objects = {}
        self.libs = {}
        self.header = None

    def parse(self):
        while True:
            rt = self.r.u8()
            if rt == 11:
                self.records.append(Rec(11))
                break
            rec = self.rec(rt)
            self.records.append(rec)
            if rt == 0:
                self.header = rec
        self.end = self.r.p
        return self

    def class_info(self):
        oid = self.r.i32()
        name = self.r.string()
        n = self.r.i32()
        return oid, name, [self.r.string() for _ in range(n)]

    def mtypes(self, n):
        bt = [self.r.u8() for _ in range(n)]
        ex = []
        for t in bt:
            if t in (0, 7):
                ex.append(self.r.u8())
            elif t == 3:
                ex.append(self.r.string())
            elif t == 4:
                ex.append((self.r.string(), self.r.i32()))
            else:
                ex.append(None)
        return list(zip(bt, ex))

    def values(self, mt):
        out = []
        for bt, ex in mt:
            out.append(self.r.prim(ex) if bt == 0 else self.rec(self.r.u8()))
        return out

    def rec(self, rt):
        r = self.r
        if rt == 0:
            return Rec(0, root=r.i32(), hdr=r.i32(), maj=r.i32(), min=r.i32())
        if rt == 12:
            i = r.i32(); n = r.string(); self.libs[i] = n
            return Rec(12, id=i, name=n)
        if rt in (4, 5):
            oid, name, mn = self.class_info()
            mt = self.mtypes(len(mn))
            lib = r.i32() if rt == 5 else None
            self.classes[oid] = (name, mn, mt)
            rec = Rec(rt, oid=oid, name=name, mnames=mn, mtypes=mt, libid=lib,
                      values=None)
            self.objects[oid] = rec
            rec.d['values'] = self.values(mt)
            return rec
        if rt == 1:
            oid = r.i32(); mid = r.i32()
            name, mn, mt = self.classes[mid]
            rec = Rec(1, oid=oid, mid=mid, name=name, mnames=mn, mtypes=mt,
                      values=None)
            self.objects[oid] = rec
            rec.d['values'] = self.values(mt)
            return rec
        if rt == 6:
            oid = r.i32(); v = r.string()
            rec = Rec(6, oid=oid, val=v)
            self.objects[oid] = rec
            return rec
        if rt == 9:
            return Rec(9, idref=r.i32())
        if rt == 10:
            return Rec(10)
        if rt == 8:
            pt = r.u8()
            return Rec(8, pt=pt, val=r.prim(pt))
        if rt == 13:
            return Rec(13, count=r.u8())
        if rt == 14:
            return Rec(14, count=r.i32())
        if rt == 15:
            oid = r.i32(); n = r.i32(); pt = r.u8()
            rec = Rec(15, oid=oid, n=n, pt=pt,
                      vals=[r.prim(pt) for _ in range(n)])
            self.objects[oid] = rec
            return rec
        if rt in (16, 17):
            oid = r.i32(); n = r.i32()
            rec = Rec(rt, oid=oid, n=n, items=None)
            self.objects[oid] = rec
            rec.d['items'] = self.items(n, 2 if rt == 16 else 1, None)
            return rec
        if rt == 7:
            oid = r.i32(); at = r.u8(); rank = r.i32()
            lens = [r.i32() for _ in range(rank)]
            lb = [r.i32() for _ in range(rank)] if at in (3, 4, 5) else None
            bt = r.u8()
            if bt in (0, 7):
                ex = r.u8()
            elif bt == 3:
                ex = r.string()
            elif bt == 4:
                ex = (r.string(), r.i32())
            else:
                ex = None
            tot = 1
            for l in lens:
                tot *= l
            rec = Rec(7, oid=oid, at=at, rank=rank, lens=lens, lb=lb, bt=bt,
                      ex=ex, items=None)
            self.objects[oid] = rec
            rec.d['items'] = self.items(tot, bt, ex)
            return rec
        raise ValueError('unknown record %d at %d' % (rt, r.p - 1))

    def items(self, n, bt, ex):
        out = []
        filled = 0
        while filled < n:
            if bt == 0:
                out.append(self.r.prim(ex)); filled += 1; continue
            rec = self.rec(self.r.u8())
            out.append(rec)
            filled += rec.d['count'] if rec.rt in (13, 14) else 1
        return out

    # -------------------------------------------------------- semantic view
    def resolve(self, v, seen=frozenset()):
        if isinstance(v, Rec):
            if v.rt == 9:
                return self.resolve(self.objects[v.d['idref']], seen)
            if v.rt == 6:
                return v.d['val']
            if v.rt == 10:
                return None
            if v.rt == 8:
                return v.d['val']
            if v.rt in (1, 4, 5):
                if v.d['oid'] in seen:
                    return '<cycle %d>' % v.d['oid']
                s = seen | {v.d['oid']}
                out = {'$type': v.d['name']}
                for k, x in zip(v.d['mnames'], v.d['values']):
                    out[k] = self.resolve(x, s)
                return out
            if v.rt == 15:
                return list(v.d['vals'])
            if v.rt in (7, 16, 17):
                out = []
                for it in v.d['items']:
                    if isinstance(it, Rec) and it.rt in (13, 14):
                        out += [None] * it.d['count']
                    else:
                        out.append(self.resolve(it, seen))
                return out
        return v

    def root(self):
        return self.resolve(Rec(9, idref=self.header.d['root']))


# -------------------------------------------------------------------- write
class W:
    def __init__(self):
        self.b = bytearray()

    def u8(self, v):
        self.b.append(v & 0xff)

    def i8(self, v):
        self.b += struct.pack('<b', v)

    def i16(self, v):
        self.b += struct.pack('<h', v)

    def u16(self, v):
        self.b += struct.pack('<H', v)

    def i32(self, v):
        self.b += struct.pack('<i', v)

    def u32(self, v):
        self.b += struct.pack('<I', v)

    def i64(self, v):
        self.b += struct.pack('<q', v)

    def u64(self, v):
        self.b += struct.pack('<Q', v)

    def f32(self, v):
        self.b += struct.pack('<f', v)

    def f64(self, v):
        self.b += struct.pack('<d', v)

    def varint(self, n):
        while True:
            b = n & 0x7f
            n >>= 7
            if n:
                self.u8(b | 0x80)
            else:
                self.u8(b)
                return

    def string(self, s):
        e = s.encode('utf-8')
        self.varint(len(e))
        self.b += e

    def char(self, s):
        self.b += s.encode('utf-8')

    def prim(self, pt, v):
        {1: lambda: self.u8(1 if v else 0), 2: lambda: self.u8(v),
         3: lambda: self.char(v), 5: lambda: self.string(v),
         6: lambda: self.f64(v), 7: lambda: self.i16(v), 8: lambda: self.i32(v),
         9: lambda: self.i64(v), 10: lambda: self.i8(v), 11: lambda: self.f32(v),
         12: lambda: self.i64(v), 13: lambda: self.u64(v),
         14: lambda: self.u16(v), 15: lambda: self.u32(v),
         16: lambda: self.u64(v), 18: lambda: self.string(v)}[pt]()


def _mtypes(w, mt):
    for bt, _ in mt:
        w.u8(bt)
    for bt, ex in mt:
        if bt in (0, 7):
            w.u8(ex)
        elif bt == 3:
            w.string(ex)
        elif bt == 4:
            w.string(ex[0]); w.i32(ex[1])


def _values(w, mt, vals):
    for (bt, ex), v in zip(mt, vals):
        if bt == 0:
            w.prim(ex, v)
        else:
            _rec(w, v)


def _rec(w, r):
    d = r.d
    w.u8(r.rt)
    if r.rt == 0:
        for k in ('root', 'hdr', 'maj', 'min'):
            w.i32(d[k])
    elif r.rt == 11:
        pass
    elif r.rt == 12:
        w.i32(d['id']); w.string(d['name'])
    elif r.rt in (4, 5):
        w.i32(d['oid']); w.string(d['name']); w.i32(len(d['mnames']))
        for n in d['mnames']:
            w.string(n)
        _mtypes(w, d['mtypes'])
        if r.rt == 5:
            w.i32(d['libid'])
        _values(w, d['mtypes'], d['values'])
    elif r.rt == 1:
        w.i32(d['oid']); w.i32(d['mid'])
        _values(w, d['mtypes'], d['values'])
    elif r.rt == 6:
        w.i32(d['oid']); w.string(d['val'])
    elif r.rt == 9:
        w.i32(d['idref'])
    elif r.rt == 10:
        pass
    elif r.rt == 8:
        w.u8(d['pt']); w.prim(d['pt'], d['val'])
    elif r.rt == 13:
        w.u8(d['count'])
    elif r.rt == 14:
        w.i32(d['count'])
    elif r.rt == 15:
        w.i32(d['oid']); w.i32(d['n']); w.u8(d['pt'])
        for v in d['vals']:
            w.prim(d['pt'], v)
    elif r.rt in (16, 17):
        w.i32(d['oid']); w.i32(d['n'])
        for it in d['items']:
            _rec(w, it)
    elif r.rt == 7:
        w.i32(d['oid']); w.u8(d['at']); w.i32(d['rank'])
        for l in d['lens']:
            w.i32(l)
        if d['lb']:
            for l in d['lb']:
                w.i32(l)
        w.u8(d['bt'])
        bt, ex = d['bt'], d['ex']
        if bt in (0, 7):
            w.u8(ex)
        elif bt == 3:
            w.string(ex)
        elif bt == 4:
            w.string(ex[0]); w.i32(ex[1])
        for it in d['items']:
            _rec(w, it)
    else:
        raise ValueError('cannot write record %d' % r.rt)


def write(parser):
    # No padding here. Sizing the file is savefile._file_size_for's job, which
    # rounds to a power of two. Nothing ever passed `pad_to`, and a second
    # padding mechanism was one more place for the two to disagree about how
    # big a save should be.
    w = W()
    for rec in parser.records:
        _rec(w, rec)
    return bytes(w.b)


def load(path):
    with open(path, 'rb') as fh:
        return Parser(fh.read()).parse()

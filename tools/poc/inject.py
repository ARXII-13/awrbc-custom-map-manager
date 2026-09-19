"""Duplicate a CustomMap inside a maps save file - PoC for map injection."""
import nrbf
from nrbf import Rec


class Copier:
    """Deep-copies a record subtree, assigning fresh object ids."""

    def __init__(self, p, pos_start=None, neg_start=None):
        # Object ids come from ONE counter shared by both signs: BinaryFormatter
        # registers objects by ABSOLUTE value, and the sign only marks value
        # types. Allocating positive and negative ids independently makes n and
        # -n collide -> "An object cannot be registered twice".
        self.p = p
        self.idmap = {}
        self.emitted = set()
        self.extra = []
        self.next = max((abs(o) for o in p.objects), default=0) + 1

    def newid(self, old):
        if old in self.idmap:
            return self.idmap[old]
        nid = self.next if old >= 0 else -self.next
        self.next += 1
        self.idmap[old] = nid
        return nid

    def val(self, bt, v):
        return v if bt == 0 else self.copy(v)

    def copy(self, r):
        d = r.d
        old = d.get('oid')
        if old is not None and r.rt != 9:
            if old in self.emitted:
                return Rec(9, idref=self.idmap[old])
            self.emitted.add(old)
        if r.rt == 9:
            old = d['idref']
            if old not in self.idmap:
                self.newid(old)                       # reserve before recursing
                self.extra.append(self.copy(self.p.objects[old]))
            return Rec(9, idref=self.idmap[old])
        if r.rt == 10:
            return Rec(10)
        if r.rt == 13:
            return Rec(13, count=d['count'])
        if r.rt == 14:
            return Rec(14, count=d['count'])
        if r.rt == 8:
            return Rec(8, pt=d['pt'], val=d['val'])
        if r.rt == 6:
            return Rec(6, oid=self.newid(d['oid']), val=d['val'])
        if r.rt in (4, 5):
            oid = self.newid(d['oid'])
            return Rec(r.rt, oid=oid, name=d['name'], mnames=list(d['mnames']),
                       mtypes=list(d['mtypes']), libid=d['libid'],
                       values=[self.val(bt, v)
                               for (bt, _), v in zip(d['mtypes'], d['values'])])
        if r.rt == 1:
            oid = self.newid(d['oid'])
            return Rec(1, oid=oid, mid=d['mid'], name=d['name'],
                       mnames=d['mnames'], mtypes=d['mtypes'],
                       values=[self.val(bt, v)
                               for (bt, _), v in zip(d['mtypes'], d['values'])])
        if r.rt == 15:
            return Rec(15, oid=self.newid(d['oid']), n=d['n'], pt=d['pt'],
                       vals=list(d['vals']))
        if r.rt in (16, 17):
            return Rec(r.rt, oid=self.newid(d['oid']), n=d['n'],
                       items=[self.copy(i) for i in d['items']])
        if r.rt == 7:
            return Rec(7, oid=self.newid(d['oid']), at=d['at'], rank=d['rank'],
                       lens=list(d['lens']), lb=d['lb'], bt=d['bt'], ex=d['ex'],
                       items=[self.val(d['bt'], i) for i in d['items']])
        raise ValueError('cannot copy record %d' % r.rt)


def member(p, rec, name):
    """Resolve a class record's member to the record it names."""
    i = rec.d['mnames'].index(name)
    v = rec.d['values'][i]
    return p.objects[v.d['idref']] if isinstance(v, Rec) and v.rt == 9 else v


def set_string(objs, rec, name, value):
    i = rec.d['mnames'].index(name)
    v = rec.d['values'][i]
    target = objs[v.d['idref']] if v.rt == 9 else v
    target.d['val'] = value


def duplicate_map(p, index, display_name, level_name):
    """Append a copy of CustomMaps[index] plus its metadata entry."""
    root = p.objects[p.header.d['root']]
    maps_arr = member(p, root, 'CustomMaps')
    meta_arr = member(p, root, 'CustomMapMetadata')

    src_map = p.objects[maps_arr.d['items'][index].d['idref']]

    # Metadata is keyed by LevelSaveData.Name, NOT by array position - the two
    # arrays are in different orders once a save has more than one map.
    def slot_of(rec):
        lv = member(p, rec, 'LevelSaveData') if rec.d.get('name') != 'AW.UserMapMetadata' else rec
        v = lv.d['values'][lv.d['mnames'].index('Name')]
        return p.objects[v.d['idref']].d['val'] if v.rt == 9 else v.d['val']

    want = slot_of(src_map)
    src_meta = None
    for it in meta_arr.d['items']:
        md = p.objects[it.d['idref']] if it.rt == 9 else it
        if slot_of(md) == want:
            src_meta = md
            break
    if src_meta is None:
        raise ValueError('no metadata entry for slot %r' % want)

    c = Copier(p)
    new_map = c.copy(src_map)
    new_meta = c.copy(src_meta)

    # every object that now exists, old and new
    made = c.extra + [new_map, new_meta]
    objs = dict(p.objects)
    objs.update({r.d['oid']: r for r in made if 'oid' in r.d})

    # rename the copy so it is distinguishable in-game
    set_string(objs, new_map, 'Name', display_name)
    set_string(objs, new_meta, 'Name', level_name)
    for r in made:
        if r.d.get('name') == 'LevelSaveData':
            set_string(objs, r, 'Name', level_name)

    # splice the new records in before MessageEnd
    end = p.records.pop()
    assert end.rt == 11
    p.records += made + [end]

    # extend both arrays
    for arr, rec in ((maps_arr, new_map), (meta_arr, new_meta)):
        arr.d['lens'][0] += 1
        arr.d['items'].append(Rec(9, idref=rec.d['oid']))

    return new_map, new_meta, len(c.idmap)

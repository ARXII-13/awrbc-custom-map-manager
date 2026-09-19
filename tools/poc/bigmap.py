"""Build an oversized map (beyond the editor's 30x20 cap) by injection."""
import nrbf, inject
from nrbf import Rec


def deref(p, v):
    return p.objects[v.d['idref']] if isinstance(v, Rec) and v.rt == 9 else v


def member_rec(p, rec, name):
    i = rec.d['mnames'].index(name)
    return deref(p, rec.d['values'][i])


def set_prim(rec, name, value):
    i = rec.d['mnames'].index(name)
    rec.d['values'][i] = value


def tile_type(p, tile_rec):
    t = member_rec(p, tile_rec, 'type')
    return t.d['values'][t.d['mnames'].index('value__')]


def tile_team(p, tile_rec):
    t = member_rec(p, tile_rec, 'teamID')
    if t is None or t.rt == 10:
        return None
    return t.d['values'][t.d['mnames'].index('value__')]


def count_items(items):
    n = 0
    for it in items:
        n += it.d['count'] if isinstance(it, Rec) and it.rt in (13, 14) else 1
    return n


def check_ids(records):
    """No object id may be defined twice anywhere in the document."""
    import collections
    seen = set()
    oids = []

    def go(r):
        if not isinstance(r, Rec) or id(r) in seen:
            return
        seen.add(id(r))
        if r.d.get('oid') is not None:
            oids.append(r.d['oid'])
        if r.rt in (1, 4, 5):
            for v in r.d['values']:
                go(v)
        elif r.rt in (7, 16, 17):
            for it in r.d['items']:
                go(it)

    for r in records:
        go(r)
    dup = {k: v for k, v in collections.Counter(oids).items() if v > 1}
    return dup


def check_arrays(p):
    """Every array's declared length must match what it actually holds."""
    bad = []
    seen = set()

    def walk(r):
        if not isinstance(r, Rec) or id(r) in seen:
            return
        seen.add(id(r))
        if r.rt == 7:
            want = 1
            for l in r.d['lens']:
                want *= l
            got = count_items(r.d['items'])
            if want != got:
                bad.append('BinaryArray oid=%s declares %d, holds %d'
                           % (r.d.get('oid'), want, got))
            for it in r.d['items']:
                walk(it)
        elif r.rt in (16, 17):
            got = count_items(r.d['items'])
            if r.d['n'] != got:
                bad.append('array oid=%s declares %d, holds %d' % (r.d.get('oid'), r.d['n'], got))
            for it in r.d['items']:
                walk(it)
        elif r.rt in (1, 4, 5):
            for v in r.d['values']:
                walk(v)

    for r in p.records:
        walk(r)
    return bad


def build(save_path, out_path, W, H, display_name):
    p = nrbf.load(save_path)
    root = p.objects[p.header.d['root']]
    maps_arr = member_rec(p, root, 'CustomMaps')
    meta_arr = member_rec(p, root, 'CustomMapMetadata')

    # source: the first map, whatever it is — we only need its object shapes
    src_map = deref(p, maps_arr.d['items'][0])
    src_lvl = member_rec(p, src_map, 'LevelSaveData')
    src_tiles_arr = member_rec(p, src_lvl, 'SerializableTiles')
    src_tiles = [deref(p, it) for it in src_tiles_arr.d['items']]

    # pick template tiles by type
    tmpl = {}
    for t in src_tiles:
        tmpl.setdefault((tile_type(p, t), tile_team(p, t)), t)
    plains = next(t for (ty, tm), t in tmpl.items() if ty == 1)
    hq = {tm: t for (ty, tm), t in tmpl.items() if ty == 512}
    base = {tm: t for (ty, tm), t in tmpl.items() if ty == 2048}
    if len(hq) < 2 or len(base) < 2:
        raise SystemExit('source map needs 2 HQs and 2 bases; found hq=%s base=%s'
                         % (list(hq), list(base)))
    teams = sorted(hq)
    print('templates: plains ok, HQ teams %s, base teams %s' % (list(hq), list(base)))

    # layout: team A top-left corner, team B bottom-right, column-major index = x*H + y
    layout = {}
    layout[(0, 0)] = hq[teams[0]]
    layout[(1, 0)] = base[teams[0]]
    layout[(0, 1)] = base[teams[0]]
    layout[(W - 1, H - 1)] = hq[teams[1]]
    layout[(W - 2, H - 1)] = base[teams[1]]
    layout[(W - 1, H - 2)] = base[teams[1]]

    # fresh id space well clear of everything in use
    c = inject.Copier(p)      # single shared id counter - see format.md

    new_map = c.copy(src_map)
    def _slot(rec):
        v = rec.d['values'][rec.d['mnames'].index('Name')]
        return p.objects[v.d['idref']].d['val'] if v.rt == 9 else v.d['val']
    _want = _slot(member_rec(p, src_map, 'LevelSaveData'))
    _src_meta = next(deref(p, it) for it in meta_arr.d['items']
                     if _slot(deref(p, it)) == _want)
    new_meta = c.copy(_src_meta)
    new_lvl = None
    for r in c.extra + [new_map]:
        if r.d.get('name') == 'LevelSaveData':
            new_lvl = r
    if new_lvl is None:
        new_lvl = member_rec(p, new_map, 'LevelSaveData')

    # build the new tile array.  Match the game's own encoding: the array holds
    # MemberReferences and the tile records sit at top level.
    tile_recs = []
    items = []
    counts = {}
    for x in range(W):
        for y in range(H):
            src = layout.get((x, y), plains)
            c.idmap = {}          # each tile is an independent object graph
            c.emitted = set()     # ...so reset both, or they desync
            rec = c.copy(src)
            tile_recs.append(rec)
            items.append(Rec(9, idref=rec.d['oid']))
            ty = tile_type(p, src)
            counts[ty] = counts.get(ty, 0) + 1

    tiles_arr = None
    for r in c.extra + [new_lvl]:
        if r.rt == 7 and len(r.d['items']) == len(src_tiles_arr.d['items']) \
                and r.d['bt'] == src_tiles_arr.d['bt'] and tiles_arr is None:
            tiles_arr = r
    # the copy of SerializableTiles is reachable from new_lvl
    ti = new_lvl.d['mnames'].index('SerializableTiles')
    tv = new_lvl.d['values'][ti]
    tiles_arr = tv if tv.rt == 7 else next(r for r in c.extra if r.d.get('oid') == tv.d['idref'])

    tiles_arr.d['lens'] = [W, H]          # rank-2 array [cols, rows]
    tiles_arr.d['items'] = items

    # units: one null-run covering the whole grid
    ui = new_lvl.d['mnames'].index('SerializableUnits')
    uv = new_lvl.d['values'][ui]
    units_arr = uv if uv.rt == 7 else next(r for r in c.extra if r.d.get('oid') == uv.d['idref'])
    units_arr.d['lens'] = [W, H]
    units_arr.d['items'] = [Rec(10) for _ in range(W * H)]

    # names and metadata
    made = c.extra + [new_map, new_meta] + tile_recs
    objs = dict(p.objects)
    objs.update({r.d['oid']: r for r in made if 'oid' in r.d})

    slot = str(max(int(deref(p, it).d['values'][deref(p, it).d['mnames'].index('Name')].d['val']
                       if False else 0) for it in maps_arr.d['items']) + 0)
    used = []
    for it in maps_arr.d['items']:
        m = deref(p, it)
        lv = member_rec(p, m, 'LevelSaveData')
        used.append(int(objs[lv.d['values'][lv.d['mnames'].index('Name')].d['idref']].d['val']
                        if lv.d['values'][lv.d['mnames'].index('Name')].rt == 9
                        else lv.d['values'][lv.d['mnames'].index('Name')].d['val']))
    slot = str(max(used) + 1)
    print('new slot index: %s' % slot)

    inject.set_string(objs, new_map, 'Name', display_name)
    inject.set_string(objs, new_lvl, 'Name', slot)
    inject.set_string(objs, new_meta, 'Name', slot)

    for fld, val in (('NumCols', W), ('NumRows', H),
                     ('NumHQs', counts.get(512, 0)),
                     ('NumCities', 0),
                     ('NumBases', counts.get(2048, 0)),
                     ('NumAirports', 0), ('NumSeaports', 0), ('NumSilos', 0),
                     ('NumPipeSeams', 0),
                     ('NumVersusProperties', counts.get(512, 0) + counts.get(2048, 0)),
                     ('MaxInitiallyOwnedVersusProperties', 3),
                     ('NumSurplusTiles', counts.get(512, 0) + counts.get(2048, 0))):
        set_prim(new_meta, fld, val)

    end = p.records.pop()
    assert end.rt == 11
    p.records += made + [end]
    for arr, rec in ((maps_arr, new_map), (meta_arr, new_meta)):
        arr.d['lens'][0] += 1
        arr.d['items'].append(Rec(9, idref=rec.d['oid']))

    dup = check_ids(p.records)
    if dup:
        print('  DUPLICATE OBJECT IDS: %d ids, sample %s'
              % (len(dup), list(dup.items())[:6]))
        raise SystemExit('refusing to write a document with duplicate object ids')
    problems = check_arrays(p)
    if problems:
        for msg in problems:
            print('  ARRAY MISMATCH:', msg)
        raise SystemExit('refusing to write an inconsistent document')
    out = nrbf.write(p)
    open(out_path, 'wb').write(out)
    return out, counts


if __name__ == '__main__':
    import sys
    W, H = int(sys.argv[1]), int(sys.argv[2])
    src = 'backup-big/maps.profile0.pre'
    out, counts = build(src, 'maps.big', W, H, 'BIG %dx%d' % (W, H))
    print('wrote maps.big: %d bytes, tile counts %s' % (len(out), counts))
    q = nrbf.Parser(out).parse()
    r = q.root()
    print('re-parsed: consumed %d/%d' % (q.end, len(out)))
    for i, m in enumerate(r['CustomMaps']):
        md = [x for x in r['CustomMapMetadata'] if x['Name'] == m['LevelSaveData']['Name']]
        print('  [%d] %-12r level=%-3r %sx%s tiles=%d units=%d'
              % (i, m['Name'], m['LevelSaveData']['Name'],
                 md[0]['NumCols'] if md else '?', md[0]['NumRows'] if md else '?',
                 len(m['LevelSaveData']['SerializableTiles']),
                 sum(1 for u in m['LevelSaveData']['SerializableUnits'] if u)))

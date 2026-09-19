"""Build a playable oversized 4-player map by injection."""
import nrbf, inject
from nrbf import Rec
import bigmap as B

PLAINS, ROAD = 1, 128
HQ, CITY, BASE, AIRPORT = 512, 1024, 2048, 4096


def name_of(p, rec):
    v = rec.d['values'][rec.d['mnames'].index('Name')]
    return p.objects[v.d['idref']].d['val'] if v.rt == 9 else v.d['val']


def find_map(p, display):
    root = p.objects[p.header.d['root']]
    for it in B.member_rec(p, root, 'CustomMaps').d['items']:
        m = B.deref(p, it)
        if name_of(p, m) == display:
            return m
    raise SystemExit('no map named %r' % display)


def find_meta(p, slot):
    root = p.objects[p.header.d['root']]
    for it in B.member_rec(p, root, 'CustomMapMetadata').d['items']:
        md = B.deref(p, it)
        if name_of(p, md) == slot:
            return md
    raise SystemExit('no metadata for slot %r' % slot)


def layout_4p(W, H):
    """Symmetric four-corner layout. Returns {(x, y): (type, team)}."""
    cells = {}

    # roads: a cross through the middle
    for x in range(6, W - 6):
        cells[(x, H // 2)] = (ROAD, None)
    for y in range(6, H - 6):
        cells[(W // 2, y)] = (ROAD, None)

    # neutral properties around the centre
    for (x, y) in [(12, 10), (W - 13, 10), (12, H - 11), (W - 13, H - 11),
                   (W // 2, 7), (W // 2, H - 8), (8, H // 2), (W - 9, H // 2)]:
        cells[(x, y)] = (CITY, -1)
    for (x, y) in [(W // 2, H // 2 - 3), (W // 2, H // 2 + 3)]:
        cells[(x, y)] = (BASE, -1)

    # one corner per team: HQ, two bases, two cities, one airport
    corners = [(4, 4, 0), (W - 5, 4, 1), (4, H - 5, 2), (W - 5, H - 5, 3)]
    for cx, cy, team in corners:
        cells[(cx, cy)] = (HQ, team)
        cells[(cx - 1, cy)] = (BASE, team)
        cells[(cx + 1, cy)] = (BASE, team)
        cells[(cx, cy - 1)] = (CITY, team)
        cells[(cx, cy + 1)] = (CITY, team)
        cells[(cx - 1, cy - 1)] = (AIRPORT, team)
    return cells


def build(save_path, out_path, W, H, display_name, template_map='ALL'):
    p = nrbf.load(save_path)
    src_map = find_map(p, template_map)
    src_lvl = B.member_rec(p, src_map, 'LevelSaveData')
    src_meta = find_meta(p, name_of(p, src_lvl))
    tiles = [B.deref(p, t) for t in B.member_rec(p, src_lvl, 'SerializableTiles').d['items']]

    tmpl = {}
    for t in tiles:
        tmpl.setdefault((B.tile_type(p, t), B.tile_team(p, t)), t)

    cells = layout_4p(W, H)
    need = set(cells.values()) | {(PLAINS, None)}
    missing = [k for k in need if k not in tmpl]
    if missing:
        raise SystemExit('template map %r lacks: %s' % (template_map, missing))

    c = inject.Copier(p)
    new_map = c.copy(src_map)
    new_meta = c.copy(src_meta)
    new_lvl = next(r for r in c.extra + [new_map] if r.d.get('name') == 'LevelSaveData')

    tile_recs, items, counts, per_team = [], [], {}, {}
    for x in range(W):
        for y in range(H):
            ty, team = cells.get((x, y), (PLAINS, None))
            c.idmap, c.emitted = {}, set()
            rec = c.copy(tmpl[(ty, team)])
            tile_recs.append(rec)
            items.append(Rec(9, idref=rec.d['oid']))
            counts[ty] = counts.get(ty, 0) + 1
            if team is not None and team >= 0 and ty in (HQ, CITY, BASE, AIRPORT):
                per_team[team] = per_team.get(team, 0) + 1

    ti = new_lvl.d['mnames'].index('SerializableTiles')
    tv = new_lvl.d['values'][ti]
    tiles_arr = tv if tv.rt == 7 else next(r for r in c.extra if r.d.get('oid') == tv.d['idref'])
    tiles_arr.d['lens'] = [W, H]
    tiles_arr.d['items'] = items

    ui = new_lvl.d['mnames'].index('SerializableUnits')
    uv = new_lvl.d['values'][ui]
    units_arr = uv if uv.rt == 7 else next(r for r in c.extra if r.d.get('oid') == uv.d['idref'])
    units_arr.d['lens'] = [W, H]
    units_arr.d['items'] = [Rec(10) for _ in range(W * H)]

    made = c.extra + [new_map, new_meta] + tile_recs
    objs = dict(p.objects)
    objs.update({r.d['oid']: r for r in made if 'oid' in r.d})

    root = p.objects[p.header.d['root']]
    maps_arr = B.member_rec(p, root, 'CustomMaps')
    meta_arr = B.member_rec(p, root, 'CustomMapMetadata')
    used = []
    for it in maps_arr.d['items']:
        lv = B.member_rec(p, B.deref(p, it), 'LevelSaveData')
        v = lv.d['values'][lv.d['mnames'].index('Name')]
        used.append(int(objs[v.d['idref']].d['val'] if v.rt == 9 else v.d['val']))
    slot = str(max(used) + 1)

    inject.set_string(objs, new_map, 'Name', display_name)
    inject.set_string(objs, new_lvl, 'Name', slot)
    inject.set_string(objs, new_meta, 'Name', slot)

    versus = sum(counts.get(t, 0) for t in (HQ, CITY, BASE, AIRPORT))
    for fld, val in (('NumCols', W), ('NumRows', H),
                     ('NumHQs', counts.get(HQ, 0)),
                     ('NumCities', counts.get(CITY, 0)),
                     ('NumBases', counts.get(BASE, 0)),
                     ('NumAirports', counts.get(AIRPORT, 0)),
                     ('NumSeaports', 0), ('NumSilos', 0), ('NumPipeSeams', 0),
                     ('NumVersusProperties', versus),
                     ('MaxInitiallyOwnedVersusProperties', max(per_team.values())),
                     ('NumSurplusTiles', versus)):
        B.set_prim(new_meta, fld, val)

    dup = B.check_ids(p.records + made)
    if dup:
        raise SystemExit('duplicate object ids: %s' % list(dup)[:5])

    end = p.records.pop()
    assert end.rt == 11
    p.records += made + [end]
    for arr, rec in ((maps_arr, new_map), (meta_arr, new_meta)):
        arr.d['lens'][0] += 1
        arr.d['items'].append(Rec(9, idref=rec.d['oid']))

    bad = B.check_arrays(p)
    if bad:
        raise SystemExit('array mismatch: %s' % bad[:3])

    out = nrbf.write(p)
    open(out_path, 'wb').write(out)
    return out, counts, per_team, slot

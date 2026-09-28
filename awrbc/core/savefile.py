"""Read and write the maps file.

Two things about this format bite hard and are handled explicitly — see
docs/format.md for the full record:

* The tile and unit arrays are **rank-2 ``[cols, rows]``**, so the flat stream
  order is column-major: ``index = x * rows + y``. A transposed square map still
  parses and still round-trips, so this is easy to get wrong silently.
* ``CustomMaps`` and ``CustomMapMetadata`` are **parallel arrays in different
  orders**. Metadata is keyed by ``LevelSaveData.Name``, never by position.

Nothing here writes to disk without passing :func:`check_document` first.
"""
import collections
import os

from . import derive, identify, nrbf
from .builder import Copier, Factory, Ids, NoTemplate, Types
from .errors import (AwrbcError, MapNotFound, SaveUnreadable,
                     UnsupportedSaveVersion, WrongGame)
from .model import Coord, Map, SaveDocument, Tile, Unit
from .nrbf import Rec

#: Save layouts this build understands. Refuse anything else rather than guess.
SUPPORTED_VERSIONS = (0,)

#: The game allocates the file in powers of two, smallest 16 KiB.
MIN_FILE_SIZE = 16384


# --------------------------------------------------------------------- read

def _enum(v):
    """Unwrap an enum record ({'$type': 'TileType', 'value__': n}) to its int."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("value__")
    return v


def _coord(v):
    if not isinstance(v, dict):
        return None
    x, y = v.get("X", 0), v.get("Y", 0)
    # The game writes null instead of (0,0) on some tiles; both mean absent.
    return None if (x == 0 and y == 0) else Coord(x, y)


def _tile(d) -> Tile:
    return Tile(
        type=_enum(d.get("type")) or 0,
        flags=_enum(d.get("flags")) or 0,
        team=_enum(d.get("teamID")),
        capture_points=d.get("capturePoints", 0),
        hp=d.get("hp", 0),
        offset=_coord(d.get("offsetFromPrimaryTile")),
        has_launched=bool(d.get("hasLaunched", False)),
    )


def _unit(d):
    if d is None:
        return None
    return Unit(
        type=_enum(d.get("type")) or 0,
        team=_enum(d.get("teamID")),
        hp=d.get("hp", 0),
        gas=d.get("gas", 0),
        ammo=d.get("ammo", 0),
        moved_this_turn=bool(d.get("movedThisTurn", False)),
        is_capturing=bool(d.get("isCapturing", False)),
        is_diving=bool(d.get("isDiving", False)),
        is_predeployed=bool(d.get("isPredeployed", False)),
    )


def _reshape(flat, cols, rows, convert):
    """Column-major flat list -> [x][y] grid."""
    return [[convert(flat[x * rows + y]) for y in range(rows)] for x in range(cols)]


def read(path: str) -> SaveDocument:
    """Parse a maps file. Raises SaveUnreadable or UnsupportedSaveVersion."""
    try:
        parser = nrbf.load(path)
    except Exception as exc:                       # noqa: BLE001 - want the cause
        raise SaveUnreadable("could not parse %s: %s" % (path, exc)) from exc

    # Confirm this is our game before reading anything into it. Otherwise a
    # save from another title fails later with a misleading complaint about the
    # version number.
    who = identify.inspect(parser, path)
    if not who.ok:
        raise WrongGame(who, path)

    try:
        root = parser.root()
    except Exception as exc:                       # noqa: BLE001
        raise SaveUnreadable("could not parse %s: %s" % (path, exc)) from exc

    version = root.get("CurrentSaveVersionNumber", None)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedSaveVersion(version, SUPPORTED_VERSIONS)

    by_slot = {}
    for md in root.get("CustomMapMetadata", []) or []:
        if isinstance(md, dict):
            by_slot[md.get("Name")] = md

    maps = []
    for entry in root.get("CustomMaps", []) or []:
        lvl = entry.get("LevelSaveData") or {}
        slot = lvl.get("Name")
        md = by_slot.get(slot, {})
        tiles_flat = lvl.get("SerializableTiles") or []
        units_flat = lvl.get("SerializableUnits") or []

        cols = md.get("NumCols") or 0
        rows = md.get("NumRows") or 0
        if cols * rows != len(tiles_flat):
            raise SaveUnreadable(
                "map %r: metadata says %dx%d (%d cells) but the tile array holds %d"
                % (entry.get("Name"), cols, rows, cols * rows, len(tiles_flat)))

        maps.append(Map(
            name=entry.get("Name") or "",
            creator=entry.get("Creator") or "",
            slot=slot or "",
            cols=cols, rows=rows,
            fog=bool(lvl.get("HasFogOfWar", False)),
            water_color=lvl.get("m_WaterColorIndex", 0),
            tiles=_reshape(tiles_flat, cols, rows, _tile),
            units=_reshape(units_flat, cols, rows, _unit),
        ))

    return SaveDocument(maps=maps, save_version=version, path=path, raw=parser,
                        title_id=who.title_id)


# ---------------------------------------------------------------- invariants

def _walk(records):
    seen = set()
    out = []

    def go(r):
        if not isinstance(r, Rec) or id(r) in seen:
            return
        seen.add(id(r))
        out.append(r)
        if r.rt in (1, 4, 5):
            for v in r.d["values"]:
                go(v)
        elif r.rt in (7, 16, 17):
            for it in r.d["items"]:
                go(it)

    for r in records:
        go(r)
    return out


def check_document(parser) -> list:
    """Every invariant that, if broken, makes the game show zero custom maps.

    Returns a list of problems; empty means safe to write. Cheap, and it has
    caught every class of corruption this project has produced.
    """
    problems = []
    records = _walk(parser.records)

    ids = [r.d["oid"] for r in records if r.d.get("oid") is not None]
    duplicate = [k for k, n in collections.Counter(ids).items() if n > 1]
    if duplicate:
        problems.append("object ids defined more than once: %s" % duplicate[:6])

    problems.extend(_check_metadata(parser))

    # BinaryFormatter registers objects by ABSOLUTE value: n and -n collide.
    positive = {i for i in ids if i > 0}
    negated = {abs(i) for i in ids if i < 0}
    clash = sorted(positive & negated)
    if clash:
        problems.append(
            "object id collides with the negation of another (BinaryFormatter "
            "registers by absolute value): %s" % clash[:6])

    defined = set(ids)
    dangling = {r.d["idref"] for r in records if r.rt == 9} - defined
    if dangling:
        problems.append("references to undefined objects: %s" % sorted(dangling)[:6])

    for r in records:
        if r.rt == 7:
            want = 1
            for length in r.d["lens"]:
                want *= length
            got = 0
            for it in r.d["items"]:
                got += it.d["count"] if isinstance(it, Rec) and it.rt in (13, 14) else 1
            if want != got:
                problems.append("array %s declares %d elements but holds %d"
                                % (r.d.get("oid"), want, got))
    return problems


# --------------------------------------------------------------------- write

def _root(parser):
    return parser.objects[parser.header.d["root"]]


def _member(rec, name):
    return rec.d["values"][rec.d["mnames"].index(name)]


def _deref(parser, extra, v):
    if isinstance(v, Rec) and v.rt == 9:
        return extra.get(v.d["idref"]) or parser.objects[v.d["idref"]]
    return v


def _check_metadata(parser):
    """Each slot must have exactly one metadata entry, and it must be honest.

    The game looks a slot's metadata up by name and takes the first match. A
    stale entry left by a removed map therefore wins over the real one, and if
    it claims a bigger grid the game reads past the end of the tile array and
    hangs - no crash, nothing logged. That cost several days to find, so it is
    checked on every write.
    """
    problems = []
    try:
        root = _root(parser)
        maps_arr = _deref(parser, {}, _member(root, "CustomMaps"))
        meta_arr = _deref(parser, {}, _member(root, "CustomMapMetadata"))
    except Exception:                                   # noqa: BLE001
        return problems                                 # not our document

    shape = {}
    for it in maps_arr.d["items"] or []:
        m = _deref(parser, {}, it)
        if m is None or m.rt == 10:
            continue
        lvl = _deref(parser, {}, _member(m, "LevelSaveData"))
        tiles = _deref(parser, {}, _member(lvl, "SerializableTiles"))
        shape[_text(parser, {}, lvl, "Name")] = tuple(tiles.d["lens"])

    seen = collections.Counter()
    for it in meta_arr.d["items"] or []:
        md = _deref(parser, {}, it)
        if md is None or md.rt == 10:
            continue
        slot = _text(parser, {}, md, "Name")
        seen[slot] += 1
        if slot not in shape:
            continue
        get = lambda n: md.d["values"][md.d["mnames"].index(n)]
        dims = (get("NumCols"), get("NumRows"))
        if dims != shape[slot]:
            problems.append(
                "metadata for slot %s says %dx%d but its tile array is %dx%d"
                % (slot, dims[0], dims[1], shape[slot][0], shape[slot][1]))

    for slot, n in seen.items():
        if n > 1:
            problems.append("slot %s has %d metadata entries; the game reads "
                            "the first and ignores the rest" % (slot, n))
    for slot in shape:
        if seen[slot] == 0:
            problems.append("map in slot %s has no metadata entry" % slot)
    return problems


def _text(parser, extra, rec, member):
    target = _deref(parser, extra, _member(rec, member))
    return target.d["val"] if isinstance(target, Rec) else target


def _set_text(parser, extra, rec, member, value):
    target = _deref(parser, extra, _member(rec, member))
    target.d["val"] = value


def _set_prim(rec, member, value):
    rec.d["values"][rec.d["mnames"].index(member)] = value


def _set_enum(parser, extra, rec, member, value):
    target = _deref(parser, extra, _member(rec, member))
    _set_prim(target, "value__", value)


def _find_unit_template(parser):
    for r in _walk(parser.records):
        if r.rt in (1, 4, 5) and r.d.get("name") == "SerializableUnit" and r.d["values"]:
            return r
    return None


def add_map(doc: SaveDocument, m: Map, name: str = None) -> str:
    """Inject ``m`` as a new custom map. Returns its slot index.

    Needs the save to already hold one map, whose LevelSaveData supplies the
    shapes of the always-empty AIWaypoints / MagmaTargets / TransportedUnits
    members. The tile and unit grids are constructed, not copied.
    """
    parser = doc.raw
    types = Types(parser)
    types.require("SerializableTile", "TileType", "TileFlags", "TeamID",
                  "AW.Coordinates")

    root = _root(parser)
    maps_arr = _deref(parser, {}, _member(root, "CustomMaps"))
    meta_arr = _deref(parser, {}, _member(root, "CustomMapMetadata"))
    if not maps_arr.d["items"]:
        raise NoTemplate(
            "this save holds no custom maps to model a new one on.\n"
            "Create one map in the game's Design Room first, then import.")

    src_map = _deref(parser, {}, maps_arr.d["items"][0])
    src_lvl = _deref(parser, {}, _member(src_map, "LevelSaveData"))
    src_slot = _text(parser, {}, src_lvl, "Name")
    src_meta = None
    for it in meta_arr.d["items"]:
        md = _deref(parser, {}, it)
        if _text(parser, {}, md, "Name") == src_slot:
            src_meta = md
            break
    if src_meta is None:
        raise SaveUnreadable("no metadata entry for slot %r" % src_slot)

    unit_template = _find_unit_template(parser) if any(
        u is not None for _, _, u in m.iter_units()) else None
    if unit_template is None and any(True for _ in m.iter_units()):
        raise NoTemplate(
            "this map places units, but the save has no existing unit to model "
            "them on. Place one unit in any map in the Design Room first.")

    ids = Ids(parser)
    factory = Factory(types, ids)
    chassis = Copier(parser, ids)
    new_map = chassis.copy(src_map)
    new_meta = chassis.copy(src_meta)
    made = list(chassis.extra) + [new_map, new_meta]
    extra = {r.d["oid"]: r for r in made if r.d.get("oid") is not None}

    new_lvl = None
    for r in made:
        if r.d.get("name") == "LevelSaveData":
            new_lvl = r
    if new_lvl is None:
        raise SaveUnreadable("could not locate the copied LevelSaveData")

    # --- construct the grids -------------------------------------------------
    tile_records, tile_items = [], []
    unit_records, unit_items = [], []
    for x in range(m.cols):
        for y in range(m.rows):
            rec = factory.tile(m.tiles[x][y])
            tile_records.append(rec)
            tile_items.append(Rec(9, idref=rec.d["oid"]))

            u = m.units[x][y]
            if u is None:
                unit_items.append(Rec(10))
                continue
            copier = Copier(parser, ids)
            urec = copier.copy(unit_template)
            ulocal = {r.d["oid"]: r for r in copier.extra if r.d.get("oid") is not None}
            _set_enum(parser, ulocal, urec, "type", u.type)
            _set_enum(parser, ulocal, urec, "teamID", u.team)
            for field, value in (("hp", u.hp), ("gas", u.gas), ("ammo", u.ammo)):
                _set_prim(urec, field, Rec(8, pt=8, val=value))
            for field, value in (("movedThisTurn", u.moved_this_turn),
                                 ("isCapturing", u.is_capturing),
                                 ("isDiving", u.is_diving),
                                 ("isPredeployed", u.is_predeployed)):
                _set_prim(urec, field, bool(value))
            unit_records.extend(copier.extra)
            unit_records.append(urec)
            unit_items.append(Rec(9, idref=urec.d["oid"]))

    tiles_arr = _deref(parser, extra, _member(new_lvl, "SerializableTiles"))
    units_arr = _deref(parser, extra, _member(new_lvl, "SerializableUnits"))
    tiles_arr.d["lens"] = [m.cols, m.rows]
    tiles_arr.d["items"] = tile_items
    units_arr.d["lens"] = [m.cols, m.rows]
    units_arr.d["items"] = unit_items

    # --- identity and metadata ----------------------------------------------
    used = []
    for it in maps_arr.d["items"]:
        lvl = _deref(parser, extra, _member(_deref(parser, extra, it), "LevelSaveData"))
        try:
            used.append(int(_text(parser, extra, lvl, "Name")))
        except (TypeError, ValueError):
            pass
    slot = str(max(used) + 1 if used else 0)

    _set_text(parser, extra, new_map, "Name", name or m.name or "Imported")
    _set_text(parser, extra, new_lvl, "Name", slot)
    _set_text(parser, extra, new_meta, "Name", slot)

    # The game already has a first-class notion of a map that came from somebody
    # else. An imported map is exactly that, whatever the chassis we cloned said.
    _set_prim(new_map, "IsDownload", True)
    _set_prim(new_lvl, "HasFogOfWar", bool(m.fog))
    _set_prim(new_lvl, "m_WaterColorIndex", m.water_color)

    meta = derive.metadata(m)
    for field, value in meta.items():
        if field == "TeamsPlaying":
            _set_enum(parser, extra, new_meta, "TeamsPlaying", value)
        else:
            _set_prim(new_meta, field, value)

    # --- splice --------------------------------------------------------------
    made = made + tile_records + unit_records
    end = parser.records.pop()
    if end.rt != 11:
        parser.records.append(end)
        raise SaveUnreadable("document does not end with MessageEnd")
    parser.records += made + [end]

    # Register what we just built. `Ids` seeds its counter from parser.objects,
    # so without this a second add_map on the same document starts over and
    # hands out ids that already exist - the collision that empties the map
    # list. It only showed up when two maps were added before writing.
    for rec in _walk(made):
        oid = rec.d.get("oid")
        if oid is not None and rec.rt != 9:
            parser.objects[oid] = rec

    maps_arr.d["lens"][0] += 1
    maps_arr.d["items"].append(Rec(9, idref=new_map.d["oid"]))
    # A freed slot can still carry metadata from whatever used to live there.
    # Appending beside it leaves two entries for one slot, and the game reads
    # the first - so a 30x20 map inherits a 40x30 entry and the game tries to
    # read 1200 tiles out of a 600-tile array. That hangs it, with no crash and
    # nothing logged. Drop anything already claiming this slot.
    _drop_metadata_for(parser, meta_arr, slot)
    meta_arr.d["lens"][0] += 1
    meta_arr.d["items"].append(Rec(9, idref=new_meta.d["oid"]))

    problems = check_document(parser)
    if problems:
        raise AwrbcError("refusing to build an inconsistent save:\n  %s"
                         % "\n  ".join(problems))

    # Keep the domain view in step with the record tree.
    m.slot = slot
    m.name = name or m.name or "Imported"
    doc.maps.append(m)
    return slot


def _drop_metadata_for(parser, meta_arr, slot):
    """Remove every metadata entry claiming `slot`.

    Every, not the first: duplicates are exactly the failure this guards
    against, and stopping early would leave one behind.
    """
    kept = []
    for it in meta_arr.d["items"]:
        md = _deref(parser, {}, it)
        if md is not None and md.rt != 10 and _text(parser, {}, md, "Name") == slot:
            continue
        kept.append(it)
    removed = len(meta_arr.d["items"]) - len(kept)
    meta_arr.d["items"] = kept
    meta_arr.d["lens"][0] -= removed
    return removed


def remove_map(doc: SaveDocument, index: int) -> str:
    """Drop a map and its paired metadata entry. Returns the freed slot."""
    parser = doc.raw
    root = _root(parser)
    maps_arr = _deref(parser, {}, _member(root, "CustomMaps"))
    meta_arr = _deref(parser, {}, _member(root, "CustomMapMetadata"))
    if not 0 <= index < len(maps_arr.d["items"]):
        raise MapNotFound("no map at index %d" % index)

    target = _deref(parser, {}, maps_arr.d["items"][index])
    lvl = _deref(parser, {}, _member(target, "LevelSaveData"))
    slot = _text(parser, {}, lvl, "Name")

    del maps_arr.d["items"][index]
    maps_arr.d["lens"][0] -= 1
    _drop_metadata_for(parser, meta_arr, slot)

    problems = check_document(parser)
    if problems:
        raise AwrbcError("refusing to build an inconsistent save:\n  %s"
                         % "\n  ".join(problems))
    del doc.maps[index]
    return slot


def _file_size_for(stream_length, existing):
    size = max(MIN_FILE_SIZE, existing or 0)
    while size < stream_length:
        size *= 2
    return size


def serialize(doc: SaveDocument, existing_size: int = None) -> bytes:
    """The bytes for this document, padded the way the game pads."""
    problems = check_document(doc.raw)
    if problems:
        raise AwrbcError("refusing to serialize an inconsistent save:\n  %s"
                         % "\n  ".join(problems))
    stream = nrbf.write(doc.raw)
    return stream + b"\0" * (_file_size_for(len(stream), existing_size) - len(stream))


def write(doc: SaveDocument, path: str = None) -> int:
    """Write the document. Serializes fully in memory first, then replaces.

    Never leaves a partially written save behind.
    """
    path = path or doc.path
    existing = os.path.getsize(path) if os.path.exists(path) else None
    data = serialize(doc, existing)
    tmp = path + ".awrbc-tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return len(data)

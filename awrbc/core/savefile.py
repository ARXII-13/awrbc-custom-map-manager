"""Read a maps file into domain objects.

Only the read path lives here for now; writing arrives with M3.

Two things about this format bite hard and are handled explicitly below — see
docs/format.md for the full record:

* The tile and unit arrays are **rank-2 ``[cols, rows]``**, so the flat stream
  order is column-major: ``index = x * rows + y``. A transposed square map still
  parses and still round-trips, so this is easy to get wrong silently.
* ``CustomMaps`` and ``CustomMapMetadata`` are **parallel arrays in different
  orders**. Metadata is keyed by ``LevelSaveData.Name``, never by position.
"""
from . import nrbf
from .errors import SaveUnreadable, UnsupportedSaveVersion
from .model import Coord, Map, SaveDocument, Tile, Unit

#: Save layouts this build understands. Refuse anything else rather than guess.
SUPPORTED_VERSIONS = (0,)


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
    # The game writes null instead of (0,0) on some tiles; treat both as absent.
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
        root = parser.root()
    except Exception as exc:                       # noqa: BLE001 - want the cause
        raise SaveUnreadable("could not parse %s: %s" % (path, exc)) from exc

    version = root.get("CurrentSaveVersionNumber", None)
    if version not in SUPPORTED_VERSIONS:
        raise UnsupportedSaveVersion(version, SUPPORTED_VERSIONS)

    # Metadata is keyed by slot, NOT by array position.
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
            cols=cols,
            rows=rows,
            fog=bool(lvl.get("HasFogOfWar", False)),
            water_color=lvl.get("m_WaterColorIndex", 0),
            tiles=_reshape(tiles_flat, cols, rows, _tile),
            units=_reshape(units_flat, cols, rows, _unit),
        ))

    return SaveDocument(maps=maps, save_version=version, path=path, raw=parser)

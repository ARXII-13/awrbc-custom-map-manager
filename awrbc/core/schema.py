"""Map JSON: the neutral interchange format.

This is the contract every other component is written against — the CLI converts
to and from it, the archive stores it, CI validates it, the editor edits it.

Two shape notes:

* The **JSON is row-major** (``terrain[y][x]``) because that is what reads
  correctly in a diff and on screen. The **save is column-major** rank-2
  ``[cols, rows]``. This module is where the transpose happens; nothing else
  should know about it.
* Per-tile extras are a single sparse ``cells`` list rather than several parallel
  lists. It carries ownership, capture progress, terrain HP and multi-tile
  offsets — everything that is not just "what terrain is here".

Values are raw game values. Friendly names are a presentation concern.
"""
from .errors import SaveUnreadable
from . import autotile
from .model import CAPTURABLE, Coord, Map, Tile, Unit

SCHEMA_VERSION = 1

#: Members we refuse to silently drop. None has ever been non-empty in an
#: observed map, but losing them quietly would corrupt an archive.
UNSUPPORTED = ("AIWaypoints", "MagmaTargets", "TransportedUnits")


class SchemaError(SaveUnreadable):
    """Map JSON that cannot be read as schema v1."""


def to_json(m: Map, *, author: str = None, map_id: str = None) -> dict:
    """Domain map -> plain dict ready for json.dump."""
    terrain = [[m.tiles[x][y].type for x in range(m.cols)] for y in range(m.rows)]
    flags = [[m.tiles[x][y].flags for x in range(m.cols)] for y in range(m.rows)]

    cells = []
    for y in range(m.rows):
        for x in range(m.cols):
            t = m.tiles[x][y]
            cell = {}
            if t.team is not None:
                # Only capturable terrain has a meaningful owner. The game will
                # happily store a team on a cannon or a silo and then ignore it
                # entirely - confirmed in play 2026-09-28 - so normalise it to
                # neutral. Two maps that differ only there play identically and
                # must not hash differently.
                cell["team"] = t.team if t.type in CAPTURABLE else -1
            if t.capture_points:
                cell["capture"] = t.capture_points
            if t.hp:
                cell["hp"] = t.hp
            # null and (0,0) both mean "not offset" - normalise to absent so the
            # same map always produces the same bytes, and the same id.
            if t.offset is not None and (t.offset.x or t.offset.y):
                cell["offset"] = [t.offset.x, t.offset.y]
            if t.has_launched:
                cell["launched"] = True
            # A cannon aims somewhere, and only its anchor records that. Without
            # it here, an editor cannot express the direction and derived flags
            # would silently point every cannon the same way.
            if t.type in autotile.DIRECTIONAL and not cell.get("offset"):
                where = autotile.facing_of(t.flags)
                if where:
                    cell["facing"] = where
            if cell:
                cells.append(dict(x=x, y=y, **cell))

    units = []
    for y in range(m.rows):
        for x in range(m.cols):
            u = m.units[x][y]
            if u is None:
                continue
            entry = dict(x=x, y=y, type=u.type, hp=u.hp, gas=u.gas, ammo=u.ammo)
            if u.team is not None:
                entry["team"] = u.team
            for name, val in (("capturing", u.is_capturing),
                              ("diving", u.is_diving),
                              ("predeployed", u.is_predeployed)):
                if val:
                    entry[name] = True
            units.append(entry)

    doc = {
        "schema": SCHEMA_VERSION,
        "name": m.name,
        "author": author if author is not None else m.creator,
        "size": {"cols": m.cols, "rows": m.rows},
        "fog": m.fog,
        "waterColor": m.water_color,
        "terrain": terrain,
        "flags": flags,
        "cells": cells,
        "units": units,
    }
    if map_id is not None:
        doc["id"] = map_id
    return doc


def build_document(m: Map, *, author: str = None, keep_creator: bool = False,
                   save_version: int = None) -> dict:
    """The complete map JSON: content, identity and derived data.

    Composed here rather than in the CLI so the editor's server produces exactly
    the same document.
    """
    from . import anonymize, derive, identity

    doc = to_json(m, author=anonymize.author_for(
        m.creator, keep=keep_creator, override=author))
    doc["id"] = identity.content_hash(doc)
    doc["derived"] = derive.derived_block(m)
    if save_version is not None:
        doc["source"] = {"gameSaveVersion": save_version}
    return doc


def from_json(doc: dict) -> Map:
    """Plain dict -> domain map. Raises SchemaError on anything unreadable."""
    if not isinstance(doc, dict):
        raise SchemaError("map JSON must be an object")

    version = doc.get("schema")
    if version != SCHEMA_VERSION:
        raise SchemaError("unsupported schema version %r (this build reads %d)"
                          % (version, SCHEMA_VERSION))

    present = [k for k in UNSUPPORTED if doc.get(k)]
    if present:
        # Fail loudly. Silent loss is what quietly corrupts an archive.
        raise SchemaError("map uses features this build cannot represent: %s"
                          % ", ".join(present))

    size = doc.get("size") or {}
    cols, rows = size.get("cols"), size.get("rows")
    if not isinstance(cols, int) or not isinstance(rows, int) or cols <= 0 or rows <= 0:
        raise SchemaError("size.cols and size.rows must be positive integers")

    terrain = doc.get("terrain")
    if not isinstance(terrain, list) or len(terrain) != rows:
        raise SchemaError("terrain must hold %d rows, found %s"
                          % (rows, len(terrain) if isinstance(terrain, list) else "none"))
    for y, row in enumerate(terrain):
        if not isinstance(row, list) or len(row) != cols:
            raise SchemaError("terrain row %d must hold %d columns" % (y, cols))

    flags = doc.get("flags")
    if flags is not None:
        if len(flags) != rows or any(len(r) != cols for r in flags):
            raise SchemaError("flags must match the terrain grid shape")

    tiles = [[Tile(type=terrain[y][x],
                   flags=flags[y][x] if flags else 0)
              for y in range(rows)] for x in range(cols)]
    # Flags are filled in below once ownership is known, because an HQ's flags
    # depend on its team.

    for c in doc.get("cells") or []:
        x, y = c.get("x"), c.get("y")
        if not (isinstance(x, int) and isinstance(y, int)
                and 0 <= x < cols and 0 <= y < rows):
            raise SchemaError("cell out of range: %r" % (c,))
        t = tiles[x][y]
        team = c.get("team")
        t.team = team if (team is None or t.type in CAPTURABLE) else -1
        t.capture_points = c.get("capture", 0)
        t.hp = c.get("hp", 0)
        off = c.get("offset")
        t.offset = Coord(off[0], off[1]) if off and (off[0] or off[1]) else None
        t.has_launched = bool(c.get("launched", False))
        t.facing = c.get("facing")

    units = [[None for _ in range(rows)] for _ in range(cols)]
    for u in doc.get("units") or []:
        x, y = u.get("x"), u.get("y")
        if not (isinstance(x, int) and isinstance(y, int)
                and 0 <= x < cols and 0 <= y < rows):
            raise SchemaError("unit out of range: %r" % (u,))
        if units[x][y] is not None:
            raise SchemaError("two units at (%d, %d)" % (x, y))
        units[x][y] = Unit(
            type=u.get("type", 0), team=u.get("team"),
            hp=u.get("hp", 0), gas=u.get("gas", 0), ammo=u.get("ammo", 0),
            is_capturing=bool(u.get("capturing", False)),
            is_diving=bool(u.get("diving", False)),
            is_predeployed=bool(u.get("predeployed", False)),
        )

    if flags is None:
        # Nothing supplied them, so derive them. Zero is not a safe default -
        # it is a value no real map ever contains - and requiring an authoring
        # tool to reimplement the autotile rule would mean two copies of it
        # drifting apart. See autotile.py and docs/format.md.
        owners = {(x, y): tiles[x][y].team
                  for x in range(cols) for y in range(rows)
                  if tiles[x][y].team is not None and tiles[x][y].team >= 0}
        computed = autotile.compute(terrain, owners)
        for x in range(cols):
            for y in range(rows):
                t = tiles[x][y]
                offset = (t.offset.x, t.offset.y) if t.offset else None
                built = autotile.structure_flags(t.type, offset, t.facing)
                t.flags = computed[y][x] if built is None else built

    return Map(
        name=doc.get("name") or "",
        creator=doc.get("author") or "",
        cols=cols, rows=rows,
        fog=bool(doc.get("fog", False)),
        water_color=doc.get("waterColor", 0),
        tiles=tiles, units=units,
    )

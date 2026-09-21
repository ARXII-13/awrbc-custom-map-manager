"""Build a save file from the type table, with no real save involved.

``tests/fixtures/typetable.json`` holds only the game's class definitions —
member names and types, the same schema already written out in docs/format.md.
No map content and no creator names. Everything here is generated, which is what
lets the test suite run anywhere (decisions.md #12).
"""
import json
import os

from awrbc.core import derive
from awrbc.core.builder import VALUE_TYPES
from awrbc.core.nrbf import Parser, Rec
from awrbc.core.nrbf import write as nrbf_write
from awrbc.core.model import BASE, HQ, Map, Tile

TABLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "fixtures", "typetable.json")
LIBRARY_ID = 2


def load_table(path=TABLE):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _mtypes(entry):
    """JSON turns the (bt, extra) pairs into lists; restore the shapes."""
    out = []
    for bt, ex in entry["types"]:
        if bt == 4 and isinstance(ex, list):
            ex = (ex[0], ex[1])
        out.append((bt, ex))
    return out


class Builder:
    """Assembles a whole document; each class is defined once, then reused."""

    def __init__(self, table):
        self.table = table
        self.next = 1
        self.defined = {}          # class name -> object id of its definition
        self.records = []

    def _id(self, name):
        value = self.next
        self.next += 1
        return -value if name in VALUE_TYPES else value

    def instance(self, name, values, top_level=True):
        entry = self.table["classes"][name]
        mnames, mtypes = entry["members"], _mtypes(entry)
        oid = self._id(name)
        ordered = [values[m] for m in mnames]
        if name in self.defined:
            rec = Rec(1, oid=oid, mid=self.defined[name], name=name,
                      mnames=mnames, mtypes=mtypes, values=ordered)
        else:
            self.defined[name] = oid
            rec = Rec(5, oid=oid, name=name, mnames=list(mnames),
                      mtypes=mtypes, libid=LIBRARY_ID, values=ordered)
        if top_level:
            self.records.append(rec)
        return rec

    def enum(self, name, value, top_level=False):
        return self.instance(name, {"value__": value}, top_level=top_level)

    def coord(self, x=0, y=0, top_level=False):
        return self.instance("AW.Coordinates", {"X": x, "Y": y},
                             top_level=top_level)

    def string(self, text):
        """An inline string. NOT appended: a record that is embedded as a
        member value must not also be emitted at top level, or it is written
        twice under the same id."""
        return Rec(6, oid=self._id("string"), val=text)

    def string_ref(self, text):
        rec = self.string(text)
        self.records.append(rec)
        return self.ref(rec)

    def array(self, key, items, lens):
        shape = self.table["arrays"][key]
        ex = shape["ex"]
        rec = Rec(7, oid=self._id("array"), at=shape["at"], rank=shape["rank"],
                  lens=list(lens), lb=None, bt=shape["bt"],
                  ex=(ex[0], ex[1]) if isinstance(ex, list) else ex,
                  items=items)
        self.records.append(rec)
        return rec

    def ref(self, rec):
        return Rec(9, idref=rec.d["oid"])


def _tile(b, t: Tile):
    return b.instance("SerializableTile", {
        "type": b.enum("TileType", t.type),
        "flags": b.enum("TileFlags", t.flags),
        "teamID": Rec(10) if t.team is None else b.enum("TeamID", t.team),
        "capturePoints": t.capture_points,
        "hp": t.hp,
        "offsetFromPrimaryTile": b.coord(),
        "hasLaunched": bool(t.has_launched),
    })


def _level(b, m: Map, slot: str):
    tiles = [b.ref(_tile(b, m.tiles[x][y]))
             for x in range(m.cols) for y in range(m.rows)]
    tiles_arr = b.array("LevelSaveData.SerializableTiles", tiles, [m.cols, m.rows])
    units_arr = b.array("LevelSaveData.SerializableUnits",
                        [Rec(10) for _ in range(m.cols * m.rows)], [m.cols, m.rows])
    waypoints = b.array("LevelSaveData.AIWaypoints", [], [0])

    magma = b.instance("MagmaTargets", {
        "OddDayTargets": b.ref(b.array("MagmaTargets.OddDayTargets", [], [0])),
        "EvenDayTargets": b.ref(b.array("MagmaTargets.EvenDayTargets", [], [0])),
    })
    list_name = next(n for n in b.table["classes"]
                     if n.startswith("System.Collections.Generic.List")
                     and "SerializableUnit" in n)
    transported = b.instance(list_name, {
        "_items": b.ref(b.array("%s._items" % list_name, [], [0])),
        "_size": 0, "_version": 0,
    })

    return b.instance("LevelSaveData", {
        "Name": b.string_ref(slot),
        "SerializableTiles": b.ref(tiles_arr),
        "SerializableUnits": b.ref(units_arr),
        "TransportedUnits": b.ref(transported),
        "HasFogOfWar": bool(m.fog),
        "AIWaypoints": b.ref(waypoints),
        "MagmaTargets": b.ref(magma),
        "m_WaterColorIndex": m.water_color,
    })


def _metadata(b, m: Map, slot: str):
    values = derive.metadata(m)
    fields = {"Name": b.string_ref(slot),
              "TeamsPlaying": b.enum("TeamIDFlag", values["TeamsPlaying"])}
    for key, value in values.items():
        if key != "TeamsPlaying":
            fields[key] = value
    return b.instance("AW.UserMapMetadata", fields)


def build_document(maps) -> bytes:
    """Serialize a complete maps file holding ``maps``."""
    table = load_table()
    b = Builder(table)
    b.records.append(Rec(0, root=0, hdr=-1, maj=1, min=0))
    b.records.append(Rec(12, id=LIBRARY_ID, name=table["library"]))

    root_id = b.next
    b.next += 1

    map_recs, meta_recs = [], []
    for index, m in enumerate(maps):
        slot = str(index)
        level = _level(b, m, slot)
        map_recs.append(b.instance("AW.CustomMap", {
            "LevelSaveData": b.ref(level),
            "Creator": b.string("fixture"),
            "Name": b.string(m.name or "Fixture"),
            "IsNew": False,
            "IsDownload": False,
            "LastCursorPosition": b.coord(),
            "LastTileType": b.enum("TileType", 1),
            "LastUnitType": Rec(10),
            "LastTeamID": b.enum("TeamID", -1),
        }))
        meta_recs.append(_metadata(b, m, slot))

    maps_arr = b.array("AW.UserGeneratedContent.CustomMaps",
                       [b.ref(r) for r in map_recs], [len(map_recs)])
    sets_arr = b.array("AW.UserGeneratedContent.CustomMapSets", [], [0])
    meta_arr = b.array("AW.UserGeneratedContent.CustomMapMetadata",
                       [b.ref(r) for r in meta_recs], [len(meta_recs)])

    entry = table["classes"]["AW.UserGeneratedContent"]
    root = Rec(5, oid=root_id, name="AW.UserGeneratedContent",
               mnames=list(entry["members"]), mtypes=_mtypes(entry),
               libid=LIBRARY_ID,
               values=[{"CustomMaps": b.ref(maps_arr),
                        "CustomMapSets": b.ref(sets_arr),
                        "CustomMapMetadata": b.ref(meta_arr),
                        "CurrentSaveVersionNumber": table["saveVersion"] or 0
                        }[n] for n in entry["members"]])
    # The root has to appear before anything references it.
    b.records.insert(2, root)
    b.records[0] = Rec(0, root=root_id, hdr=-1, maj=1, min=0)
    b.records.append(Rec(11))

    parser = Parser(b"")
    parser.records = b.records
    stream = nrbf_write(parser)
    return stream + b"\0" * (16384 - len(stream) if len(stream) < 16384 else 0)


def simple_map(cols=8, rows=6, name="Fixture") -> Map:
    """A small, valid, two-player map."""
    tiles = [[Tile(type=1) for _ in range(rows)] for _ in range(cols)]
    units = [[None for _ in range(rows)] for _ in range(cols)]
    m = Map(name=name, creator="fixture", cols=cols, rows=rows,
            tiles=tiles, units=units)
    m.tiles[0][0] = Tile(type=HQ, team=0, capture_points=20)
    m.tiles[1][0] = Tile(type=BASE, team=0, capture_points=20)
    m.tiles[cols - 1][rows - 1] = Tile(type=HQ, team=1, capture_points=20)
    m.tiles[cols - 2][rows - 1] = Tile(type=BASE, team=1, capture_points=20)
    return m


def write_fixture_save(path, maps=None):
    data = build_document(maps or [simple_map()])
    with open(path, "wb") as fh:
        fh.write(data)
    return path

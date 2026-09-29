"""Construct new records for injection into a save.

Two rules govern everything here, both learned the hard way. See docs/format.md.

**Object ids come from ONE counter shared by both signs.** BinaryFormatter
registers objects by *absolute value*; the sign only marks value types. Allocating
positive and negative ids independently lets ``n`` and ``-n`` coexist, which makes
the game silently show zero custom maps.

**An object is emitted exactly once.** Something defined inline in one record and
referenced from another must not be written twice.

The approach is a hybrid, chosen because it is the version that is proven to work
in-game: an existing map supplies the *chassis* (LevelSaveData and its always-empty
AIWaypoints / MagmaTargets / TransportedUnits, whose shapes are fiddly and never
vary), while the tile and unit grids are **constructed** from the domain model, so
an imported map is real content and not a copy of something already present.
"""
from .errors import AwrbcError
from .nrbf import Rec

#: Value types. The game always gives these negative object ids.
VALUE_TYPES = frozenset({
    "TileType", "TileFlags", "TeamID", "TeamIDFlag", "UnitType",
    "AW.Coordinates", "AW.PreDeployedBehavior",
})


class NoTemplate(AwrbcError):
    """The save has nothing to model a new map on."""

    exit_code = 4


class Ids:
    """One counter, shared by both signs."""

    def __init__(self, parser):
        self.next = max((abs(o) for o in parser.objects), default=0) + 1

    def take(self, negative=False):
        value = -self.next if negative else self.next
        self.next += 1
        return value

    def for_class(self, name):
        return self.take(negative=name in VALUE_TYPES)


class Copier:
    """Deep-copies a record subtree with fresh ids."""

    def __init__(self, parser, ids):
        self.p = parser
        self.ids = ids
        self.map = {}
        self.emitted = set()
        self.extra = []

    def _id(self, old, name=None):
        if old not in self.map:
            negative = old < 0 if name is None else name in VALUE_TYPES
            self.map[old] = self.ids.take(negative=negative)
        return self.map[old]

    def _value(self, bt, v):
        return v if bt == 0 else self.copy(v)

    def copy(self, r):
        d = r.d
        oid = d.get("oid")
        if oid is not None and r.rt != 9:
            if oid in self.emitted:
                return Rec(9, idref=self.map[oid])
            self._id(oid, d.get("name"))
            self.emitted.add(oid)

        if r.rt == 9:
            old = d["idref"]
            if old not in self.emitted:
                target = self.p.objects[old]
                self._id(old, target.d.get("name"))
                self.emitted.add(old)
                self.extra.append(self._copy_body(target))
            return Rec(9, idref=self.map[old])
        return self._copy_body(r)

    def _copy_body(self, r):
        d = r.d
        if r.rt == 10:
            return Rec(10)
        if r.rt == 8:
            return Rec(8, pt=d["pt"], val=d["val"])
        if r.rt in (13, 14):
            return Rec(r.rt, count=d["count"])
        if r.rt == 6:
            return Rec(6, oid=self.map[d["oid"]], val=d["val"])
        if r.rt in (4, 5):
            return Rec(r.rt, oid=self.map[d["oid"]], name=d["name"],
                       mnames=list(d["mnames"]), mtypes=list(d["mtypes"]),
                       libid=d.get("libid"),
                       values=[self._value(bt, v)
                               for (bt, _), v in zip(d["mtypes"], d["values"])])
        if r.rt == 1:
            return Rec(1, oid=self.map[d["oid"]], mid=d["mid"], name=d["name"],
                       mnames=d["mnames"], mtypes=d["mtypes"],
                       values=[self._value(bt, v)
                               for (bt, _), v in zip(d["mtypes"], d["values"])])
        if r.rt == 15:
            return Rec(15, oid=self.map[d["oid"]], n=d["n"], pt=d["pt"],
                       vals=list(d["vals"]))
        if r.rt in (16, 17):
            return Rec(r.rt, oid=self.map[d["oid"]], n=d["n"],
                       items=[self.copy(i) for i in d["items"]])
        if r.rt == 7:
            return Rec(7, oid=self.map[d["oid"]], at=d["at"], rank=d["rank"],
                       lens=list(d["lens"]), lb=d["lb"], bt=d["bt"], ex=d["ex"],
                       items=[self._value(d["bt"], i) for i in d["items"]])
        raise AwrbcError("cannot copy record type %d" % r.rt)


class Types:
    """Class definitions present in a document, looked up by name."""

    def __init__(self, parser):
        self.defs = {}
        for oid, (name, mnames, mtypes) in parser.classes.items():
            self.defs.setdefault(name, (oid, mnames, mtypes))

    def __contains__(self, name):
        return name in self.defs

    def require(self, *names):
        missing = [n for n in names if n not in self.defs]
        if missing:
            raise NoTemplate(
                "this save has no definition for %s.\n"
                "Import needs a save that already holds at least one custom map "
                "to model new records on." % ", ".join(missing))


class Factory:
    """Builds fresh instances against a document's existing class definitions."""

    def __init__(self, types: Types, ids: Ids):
        self.types = types
        self.ids = ids

    def instance(self, name, values):
        """A ClassWithId referencing the existing definition of ``name``."""
        oid, mnames, mtypes = self.types.defs[name]
        return Rec(1, oid=self.ids.for_class(name), mid=oid, name=name,
                   mnames=mnames, mtypes=mtypes,
                   values=[values[n] for n in mnames])

    def enum(self, name, value):
        return self.instance(name, {"value__": value})

    def coord(self, x, y):
        return self.instance("AW.Coordinates", {"X": x, "Y": y})

    def tile(self, t):
        """A SerializableTile built from the domain model."""
        return self.instance("SerializableTile", {
            "type": self.enum("TileType", t.type),
            "flags": self.enum("TileFlags", t.flags),
            "teamID": (Rec(10) if t.team is None
                       else self.enum("TeamID", t.team)),
            "capturePoints": t.capture_points,
            "hp": t.hp,
            "offsetFromPrimaryTile": self.coord(
                t.offset.x if t.offset else 0, t.offset.y if t.offset else 0),
            "hasLaunched": bool(t.has_launched),
        })

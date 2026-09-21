"""Extract the game's class definitions from a save into a type table.

    python tools/extract_types.py <maps-file> tests/fixtures/typetable.json

The output holds **schema only** — class names, member names and member types.
No map content, no creator names, no save data. It is the same information
already written out in prose in docs/format.md, in a form the fixture builder
can use, which is what lets the test suite run without anyone's real save.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from awrbc.core import nrbf                                        # noqa: E402

WANTED = [
    "AW.UserGeneratedContent", "AW.CustomMap", "AW.UserMapMetadata",
    "LevelSaveData", "SerializableTile", "SerializableUnit",
    "TileType", "TileFlags", "TeamID", "TeamIDFlag", "UnitType",
    "AW.Coordinates", "AW.PreDeployedBehavior", "MagmaTargets",
]


def array_shapes(parser):
    """Rank/element-type of each named array member, so fixtures match."""
    shapes = {}
    seen = set()

    def go(rec, owner=None):
        if not isinstance(rec, nrbf.Rec) or id(rec) in seen:
            return
        seen.add(id(rec))
        if rec.rt in (1, 4, 5):
            for name, value in zip(rec.d["mnames"], rec.d["values"]):
                target = value
                if isinstance(value, nrbf.Rec) and value.rt == 9:
                    target = parser.objects.get(value.d["idref"])
                if isinstance(target, nrbf.Rec) and target.rt == 7:
                    key = "%s.%s" % (rec.d.get("name"), name)
                    shapes.setdefault(key, {
                        "at": target.d["at"], "rank": target.d["rank"],
                        "bt": target.d["bt"], "ex": target.d["ex"],
                    })
                go(value, rec)
        elif rec.rt in (7, 16, 17):
            for item in rec.d["items"]:
                go(item, owner)

    for rec in parser.records:
        go(rec)
    return shapes


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 1
    parser = nrbf.load(argv[1])

    classes = {}
    for oid, (name, mnames, mtypes) in parser.classes.items():
        if name in WANTED or name.startswith("System.Collections.Generic.List"):
            classes.setdefault(name, {
                "members": list(mnames),
                "types": [[bt, ex] for bt, ex in mtypes],
            })

    missing = [n for n in WANTED if n not in classes]
    table = {
        "library": next(iter(parser.libs.values()), None),
        "saveVersion": parser.root().get("CurrentSaveVersionNumber"),
        "classes": classes,
        "arrays": array_shapes(parser),
    }
    os.makedirs(os.path.dirname(argv[2]) or ".", exist_ok=True)
    with open(argv[2], "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("wrote %s" % argv[2])
    print("  classes: %d" % len(classes))
    print("  arrays : %d" % len(table["arrays"]))
    if missing:
        print("  MISSING: %s" % ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

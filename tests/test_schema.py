"""Schema, identity and anonymisation tests."""
import unittest

from awrbc.core import anonymize, identity, schema
from awrbc.core.model import BASE, CITY, HQ, Coord, Map, Tile, Unit
from awrbc.core.schema import SchemaError


def make(cols=5, rows=3):
    """Deliberately NON-SQUARE: a transposed square map looks fine."""
    tiles = [[Tile(type=1, flags=0x40001) for _ in range(rows)] for _ in range(cols)]
    units = [[None for _ in range(rows)] for _ in range(cols)]
    m = Map(name="Test", creator="ARX II-13", cols=cols, rows=rows,
            tiles=tiles, units=units)
    # placed relative to size so the helper works at any dimensions
    m.tiles[0][0] = Tile(type=HQ, team=0, capture_points=20)
    m.tiles[1][0] = Tile(type=BASE, team=0, capture_points=20)
    m.tiles[cols - 1][rows - 1] = Tile(type=HQ, team=1, capture_points=20)
    m.tiles[cols - 2][rows - 1] = Tile(type=BASE, team=1, capture_points=20)
    m.tiles[cols // 2][rows // 2] = Tile(type=CITY, team=-1, capture_points=20)
    m.units[2][0] = Unit(type=9, team=0, hp=100_000_000, gas=99, ammo=0)
    return m


class Orientation(unittest.TestCase):
    """The JSON is row-major; the save is column-major. Guard the transpose."""

    def test_json_grid_is_rows_of_columns(self):
        d = schema.to_json(make(cols=5, rows=3))
        self.assertEqual(len(d["terrain"]), 3)
        self.assertEqual(len(d["terrain"][0]), 5)

    def test_tile_lands_at_the_same_coordinates(self):
        m = make()
        d = schema.to_json(m)
        # HQ is at x=0,y=0 and the other at x=4,y=2
        self.assertEqual(d["terrain"][0][0], HQ)      # x=0, y=0
        self.assertEqual(d["terrain"][2][4], HQ)      # x=4, y=2
        self.assertEqual(d["terrain"][1][2], CITY)    # x=2, y=1

    def test_round_trip_preserves_position_on_a_non_square_map(self):
        m = make(cols=7, rows=2)
        m.tiles[6][1] = Tile(type=BASE, team=1)
        back = schema.from_json(schema.to_json(m))
        self.assertEqual(back.cols, 7)
        self.assertEqual(back.rows, 2)
        self.assertEqual(back.tiles[6][1].type, BASE)


class RoundTrip(unittest.TestCase):
    def test_everything_survives(self):
        m = make()
        back = schema.from_json(schema.to_json(m))
        for x, y, t in m.iter_tiles():
            b = back.tiles[x][y]
            self.assertEqual((t.type, t.team, t.capture_points, t.hp, t.flags),
                             (b.type, b.team, b.capture_points, b.hp, b.flags),
                             "tile (%d,%d)" % (x, y))
        self.assertEqual(back.units[2][0].type, 9)
        self.assertEqual(back.units[2][0].hp, 100_000_000)

    def test_multi_tile_offsets_survive(self):
        m = make()
        m.tiles[1][1] = Tile(type=524288, offset=Coord(1, 0), hp=99, flags=0x20000000)
        back = schema.from_json(schema.to_json(m))
        t = back.tiles[1][1]
        self.assertEqual((t.offset.x, t.offset.y), (1, 0))
        self.assertEqual(t.hp, 99)
        self.assertEqual(t.flags, 0x20000000)

    def test_null_and_zero_offset_are_both_absent(self):
        m = make()
        m.tiles[1][1] = Tile(type=1, offset=Coord(0, 0))
        self.assertIsNone(schema.from_json(schema.to_json(m)).tiles[1][1].offset)


class Identity(unittest.TestCase):
    def setUp(self):
        self.doc = schema.build_document(make())

    def test_rename_keeps_the_id(self):
        other = dict(self.doc, name="Renamed", author="someone else")
        self.assertEqual(identity.content_hash(other), self.doc["id"])

    def test_flags_do_not_affect_the_id(self):
        """Flags may be autotile variants the game recomputes."""
        other = dict(self.doc, flags=[[0] * 5 for _ in range(3)])
        self.assertEqual(identity.content_hash(other), self.doc["id"])

    def test_content_changes_the_id(self):
        m = make()
        m.tiles[2][2] = Tile(type=BASE, team=1)
        self.assertNotEqual(schema.build_document(m)["id"], self.doc["id"])

    def test_id_is_stable_across_a_round_trip(self):
        back = schema.from_json(self.doc)
        self.assertEqual(schema.build_document(back)["id"], self.doc["id"])


class Anonymise(unittest.TestCase):
    def test_scrubbed_by_default(self):
        self.assertEqual(schema.build_document(make())["author"], "anonymous")

    def test_keep_creator_opts_in(self):
        d = schema.build_document(make(), keep_creator=True)
        self.assertEqual(d["author"], "ARX II-13")

    def test_override_wins(self):
        d = schema.build_document(make(), author="Someone", keep_creator=True)
        self.assertEqual(d["author"], "Someone")

    def test_helper(self):
        self.assertEqual(anonymize.author_for("Real Name"), "anonymous")
        self.assertEqual(anonymize.author_for("Real Name", keep=True), "Real Name")


class Rejects(unittest.TestCase):
    def test_wrong_schema_version(self):
        d = schema.to_json(make())
        d["schema"] = 99
        with self.assertRaises(SchemaError):
            schema.from_json(d)

    def test_grid_shape_mismatch(self):
        d = schema.to_json(make())
        d["terrain"].pop()
        with self.assertRaises(SchemaError):
            schema.from_json(d)

    def test_two_units_on_one_cell(self):
        d = schema.to_json(make())
        d["units"].append(dict(d["units"][0]))
        with self.assertRaises(SchemaError):
            schema.from_json(d)

    def test_out_of_range_cell(self):
        d = schema.to_json(make())
        d["cells"].append({"x": 99, "y": 0, "team": 0})
        with self.assertRaises(SchemaError):
            schema.from_json(d)

    def test_unrepresentable_features_fail_loudly(self):
        """Silent loss is what quietly corrupts an archive."""
        d = schema.to_json(make())
        d["AIWaypoints"] = [{"id": "a"}]
        with self.assertRaises(SchemaError):
            schema.from_json(d)


if __name__ == "__main__":
    unittest.main()

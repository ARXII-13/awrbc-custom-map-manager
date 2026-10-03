"""Autotiling tests.

Flags select sprites, so the editor has to author them or maps render wrong.
These pin the rules derived in docs/format.md.

The fidelity test that compares these against what the game itself wrote needs
to read a save, so it lives with the save editor now. These are the rules.
"""
import os
import random
import unittest

from awrbc.core import autotile as A
from awrbc.core import schema

P, S, R, V, H, B, D, O = 1, 2, 16, 32, 128, 256, 8192, 2


def grid(rows):
    """A terrain grid from a compact picture."""
    key = {'.': 1, 's': 2, 'r': 16, 'h': 32, '=': 128, 'b': 256, 'p': 8192,
           'q': 512, 'i': 32768}
    return [[key[c] for c in row] for row in rows]


def masks(flags):
    return [[f & 0x1F for f in row] for row in flags]


class ConnectionMask(unittest.TestCase):
    """bit1 = N, bit2 = W, bit3 = E, bit4 = S."""

    def test_a_horizontal_road_links_east_and_west(self):
        f = masks(A.compute(grid(['....', '====', '....'])))
        self.assertEqual(f[1], [1 << 3, (1 << 2) | (1 << 3),
                                (1 << 2) | (1 << 3), 1 << 2])

    def test_a_vertical_road_links_north_and_south(self):
        f = masks(A.compute(grid(['.=.', '.=.', '.=.'])))
        self.assertEqual([r[1] for r in f],
                         [1 << 4, (1 << 1) | (1 << 4), 1 << 1])

    def test_a_crossroads_links_all_four_ways(self):
        f = masks(A.compute(grid(['.=.', '===', '.=.'])))
        self.assertEqual(f[1][1], 0b11110)

    def test_a_road_does_not_link_to_plains(self):
        f = masks(A.compute(grid(['...', '.=.', '...'])))
        self.assertEqual(f[1][1] & 0x1E, 0)

    def test_a_river_links_to_river_and_to_sea(self):
        f = masks(A.compute(grid(['.r.', '.r.', '.s.'])))
        self.assertEqual(f[1][1], (1 << 1) | (1 << 4))

    def test_a_river_does_not_link_to_a_road(self):
        f = masks(A.compute(grid(['.=.', '.r.', '...'])))
        self.assertEqual(f[1][1] & 0x1E, 0)

    def test_terrain_with_no_mask_carries_bit_zero(self):
        f = masks(A.compute(grid(['...', '...', '...'])))
        self.assertTrue(all(v == 1 for row in f for v in row))


class RiverOrientation(unittest.TestCase):
    """Bit 18 on a river is flow direction, not decoration.

    It was treated as one of two interchangeable decorations, so a straight run
    got the perpendicular sprite roughly half the time and the river rendered
    as disconnected blocks. Found by playing a map, not by reading flags.
    """

    def test_a_horizontal_run_is_marked_horizontal(self):
        f = A.compute(grid(['...', 'rrr', '...']))
        self.assertTrue(f[1][1] & A.RIVER_HORIZONTAL)

    def test_a_vertical_run_is_not(self):
        f = A.compute(grid(['.r.', '.r.', '.r.']))
        self.assertFalse(f[1][1] & A.RIVER_HORIZONTAL)

    def test_a_corner_is_not(self):
        f = A.compute(grid(['...', '.rr', '.r.']))
        self.assertFalse(f[1][1] & A.RIVER_HORIZONTAL)

    def test_a_junction_is_not(self):
        f = A.compute(grid(['.r.', 'rrr', '.r.']))
        self.assertFalse(f[1][1] & A.RIVER_HORIZONTAL)

    def test_it_does_not_depend_on_the_random_source(self):
        """Two runs with different seeds must agree, or a river flickers."""
        import random as rnd
        a = A.compute(grid(['...', 'rrr', '...']), rng=rnd.Random(1))
        b = A.compute(grid(['...', 'rrr', '...']), rng=rnd.Random(99))
        self.assertEqual([r[1] & (0x1E | A.RIVER_HORIZONTAL) for r in a],
                         [r[1] & (0x1E | A.RIVER_HORIZONTAL) for r in b])


class Shoreline(unittest.TestCase):
    def test_sea_marks_the_sides_facing_land(self):
        f = masks(A.compute(grid(['sss', 's.s', 'sss'])))
        self.assertEqual(f[0][1], 1 << 4)          # land to the south
        self.assertEqual(f[1][0], 1 << 3)          # land to the east

    def test_open_water_carries_bit_zero_instead(self):
        f = A.compute(grid(['sssss', 'sssss', 'sssss']))
        self.assertEqual(f[1][2] & 0x1FF, 1)

    def test_a_river_is_water_to_the_sea_beside_it(self):
        f = masks(A.compute(grid(['sss', 'srs', 'sss'])))
        self.assertEqual(f[1][0] & 0x1E, 0)

    def test_off_map_is_water_not_shore(self):
        f = masks(A.compute(grid(['ss', 'ss'])))
        self.assertEqual(f[0][0] & 0x1E, 0)


class Seaport(unittest.TestCase):
    def test_a_port_points_one_bit_at_the_sea(self):
        f = A.compute(grid(['...', '.p.', '.s.']))
        self.assertEqual(f[1][1] & 0x1F, 1 << 4)

    def test_a_port_always_carries_bit_nineteen(self):
        f = A.compute(grid(['...', '.p.', '.s.']))
        self.assertTrue(f[1][1] & A.SEAPORT_BIT)

    def test_a_port_is_water_only_from_the_side_it_faces(self):
        """Its dock side reads as water; its back reads as land."""
        f = masks(A.compute(grid(['.s.', 'sps', '.s.'])))
        facing = A._port_faces(grid(['.s.', 'sps', '.s.']), 1, 1)
        self.assertEqual(facing, A.SOUTH)
        self.assertEqual(f[2][1] & (1 << 1), 0)     # sea below: no shore
        self.assertTrue(f[0][1] & (1 << 4))         # sea above: shore


class Bridges(unittest.TestCase):
    def test_a_horizontal_bridge_uses_the_three_fixed_values(self):
        f = masks(A.compute(grid(['sssss', '=bbb=', 'sssss'])))
        self.assertEqual(f[1][1:4], [4, A.BRIDGE_MIDDLE['h'], 8])

    def test_a_vertical_bridge_uses_the_other_three(self):
        f = masks(A.compute(grid(['s=s', 'sbs', 'sbs', 'sbs', 's=s'])))
        self.assertEqual([r[1] for r in f[1:4]],
                         [2, A.BRIDGE_MIDDLE['v'], 16])

    def test_a_bridge_end_prefers_a_road_over_plain_land(self):
        g = grid(['...', '=bb', '...'])
        self.assertEqual(A._bridge_value(g, 1, 1), 1 << A.WEST)


class TeamsAndVariants(unittest.TestCase):
    def test_each_team_gets_its_own_hq_bit(self):
        g = grid(['q'])
        seen = {A.flags_for(g, 0, 0, team=t) & 0x1F000 for t in range(5)}
        self.assertEqual(len(seen), 5)

    def test_plains_variants_are_drawn_from_the_observed_eight(self):
        g = grid(['.'])
        seen = {A.flags_for(g, 0, 0, rng=random.Random(n)) & ~1
                for n in range(60)}
        self.assertTrue(seen <= set(A.VARIANTS), seen)

    def test_a_seeded_rng_is_reproducible(self):
        g = grid(['....', '....'])
        a = A.compute(g, rng=random.Random(7))
        b = A.compute(g, rng=random.Random(7))
        self.assertEqual(a, b)

    def test_nothing_ever_comes_out_zero(self):
        """No real map has a zero tile, so we never emit one either."""
        g = grid(['.s=rb', 'q.hp.', '=====', 'sssss'])
        for row in A.compute(g, teams={(0, 1): 0}):
            self.assertTrue(all(v != 0 for v in row), row)


class SchemaDerivesFlags(unittest.TestCase):
    """A map JSON without flags must still produce a loadable map.

    This is what lets an authoring tool stay out of the autotile business: it
    writes terrain and ownership, and the rule lives in one place.
    """

    def _doc(self, terrain, cells=None):
        return {
            "schema": 1, "name": "t", "author": "t",
            "size": {"cols": len(terrain[0]), "rows": len(terrain)},
            "fog": False, "waterColor": 0,
            "terrain": terrain, "cells": cells or [], "units": [],
        }

    def test_absent_flags_are_computed_not_zeroed(self):
        m = schema.from_json(self._doc(grid(["===", "...", "..."])))
        self.assertEqual(m.tiles[1][0].flags & 0x1E,
                         (1 << A.WEST) | (1 << A.EAST))

    def test_no_tile_is_left_at_zero(self):
        m = schema.from_json(self._doc(grid([".s=r", "q.hp", "===="])))
        for x in range(m.cols):
            for y in range(m.rows):
                self.assertNotEqual(m.tiles[x][y].flags, 0, (x, y))

    def test_an_hq_gets_the_bit_for_its_owner(self):
        doc = self._doc(grid(["q"]), cells=[{"x": 0, "y": 0, "team": 3}])
        m = schema.from_json(doc)
        self.assertTrue(m.tiles[0][0].flags & A.TEAM_BIT[3])

    def test_supplied_flags_are_left_alone(self):
        doc = self._doc(grid(["==", ".."]))
        doc["flags"] = [[123, 124], [125, 126]]
        m = schema.from_json(doc)
        self.assertEqual(m.tiles[0][0].flags, 123)
        self.assertEqual(m.tiles[1][0].flags, 124)


class Structures(unittest.TestCase):
    """Cannons record which way they aim, on their anchor tile.

    Confirmed against real maps 2026-09-27: a Black Cannon anchor carries
    0x40000000 plus a facing bit, its body tiles 0x20000000, and a one-tile
    Mini Cannon just the facing.
    """

    def test_a_one_tile_cannon_is_only_its_facing(self):
        self.assertEqual(A.structure_flags(A.MINI_CANNON, None, "W"),
                         1 << A.WEST)

    def test_an_anchor_carries_the_anchor_bit_and_the_facing(self):
        self.assertEqual(A.structure_flags(A.BLACK_CANNON, None, "N"),
                         A.STRUCTURE_ANCHOR | (1 << A.NORTH))

    def test_a_body_tile_is_the_body_bit_alone(self):
        self.assertEqual(A.structure_flags(A.BLACK_CANNON, (1, 2), "N"),
                         A.STRUCTURE_BODY)

    def test_facing_reads_back_from_flags(self):
        for where in ("N", "W", "E", "S"):
            flags = A.structure_flags(A.BLACK_CANNON, None, where)
            self.assertEqual(A.facing_of(flags), where)

    def test_ordinary_terrain_is_not_a_structure(self):
        self.assertIsNone(A.structure_flags(1, None, None))


class AuthoredStructures(unittest.TestCase):
    """A 3x3 structure described the way the editor writes it.

    Nine tiles carrying the terrain id, the anchor holding a facing, the rest
    their offset, and hit points at [1, 0]. Nothing says "anchor" or "body" -
    those flags are derived from the offsets.
    """

    def _doc(self, kind, facing, ax=1, ay=1):
        terrain = [[1] * 6 for _ in range(6)]
        cells = []
        for dy in range(3):
            for dx in range(3):
                terrain[ay + dy][ax + dx] = kind
                cell = {"x": ax + dx, "y": ay + dy, "team": -1}
                if dx or dy:
                    cell["offset"] = [dx, dy]
                else:
                    cell["facing"] = facing
                if (dx, dy) == (1, 0):
                    cell["hp"] = 99
                cells.append(cell)
        return {"schema": 1, "name": "t", "author": "t",
                "size": {"cols": 6, "rows": 6}, "fog": False, "waterColor": 0,
                "terrain": terrain, "cells": cells, "units": []}

    def test_the_anchor_carries_the_anchor_bit_and_the_facing(self):
        m = schema.from_json(self._doc(A.BLACK_CANNON, "E"))
        self.assertEqual(m.tiles[1][1].flags,
                         A.STRUCTURE_ANCHOR | (1 << A.EAST))

    def test_every_other_tile_is_a_body_tile(self):
        m = schema.from_json(self._doc(A.DEATH_RAY, "S"))
        for dy in range(3):
            for dx in range(3):
                if not (dx or dy):
                    continue
                self.assertEqual(m.tiles[1 + dx][1 + dy].flags,
                                 A.STRUCTURE_BODY, (dx, dy))

    def test_no_tile_of_a_structure_comes_out_zero(self):
        m = schema.from_json(self._doc(A.BLACK_CANNON, "N"))
        for x in range(m.cols):
            for y in range(m.rows):
                self.assertNotEqual(m.tiles[x][y].flags, 0, (x, y))

    def test_the_facing_survives_a_round_trip(self):
        for where in ("N", "E", "S", "W"):
            built = schema.build_document(
                schema.from_json(self._doc(A.BLACK_CANNON, where)))
            anchor = next(c for c in built["cells"]
                          if c["x"] == 1 and c["y"] == 1)
            self.assertEqual(anchor["facing"], where)


class OwnershipThatDoesNotExist(unittest.TestCase):
    """A cannon can be assigned a team, and the game ignores it.

    Verified in play 2026-09-28: cannons fire at every army and every army can
    fire back, whoever the tile says owns them. The save keeps whatever is
    written, so identity has to normalise it - otherwise two maps that play
    identically hash differently and the archive sees two maps.
    """

    def _doc(self, cannon_team):
        terrain = [[1] * 4 for _ in range(3)]
        terrain[1][1] = 1048576
        return {
            "schema": 1, "name": "t", "author": "t",
            "size": {"cols": 4, "rows": 3}, "fog": False, "waterColor": 0,
            "terrain": terrain, "units": [],
            "cells": [{"x": 1, "y": 1, "team": cannon_team, "hp": 99,
                       "facing": "S"}],
        }

    def test_a_cannon_is_always_neutral_however_it_was_written(self):
        for assigned in (0, 3, -1):
            doc = schema.build_document(schema.from_json(self._doc(assigned)))
            cell = next(c for c in doc["cells"] if c["x"] == 1 and c["y"] == 1)
            self.assertEqual(cell["team"], -1, "team %r" % assigned)

    def test_assigning_one_does_not_change_the_map_id(self):
        ids = {schema.build_document(schema.from_json(self._doc(t)))["id"]
               for t in (0, 1, 2, 3, 4, -1)}
        self.assertEqual(len(ids), 1, ids)

    def test_a_real_property_keeps_its_owner(self):
        doc = self._doc(-1)
        doc["terrain"][0][0] = 512
        doc["cells"].append({"x": 0, "y": 0, "team": 2, "capture": 20})
        built = schema.build_document(schema.from_json(doc))
        hq = next(c for c in built["cells"] if c["x"] == 0 and c["y"] == 0)
        self.assertEqual(hq["team"], 2)


if __name__ == "__main__":
    unittest.main()

"""Autotiling tests.

A map whose flags are all zero crashes Versus, so the editor has to author
them. These pin the rules derived in docs/format.md.

The fidelity test needs real maps and is skipped without AWRBC_TEST_SAVE; the
rule tests below run everywhere.
"""
import os
import random
import unittest

from awrbc.core import autotile as A
from awrbc.core import savefile, schema

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
        """Zeroed flags crash the game; no tile may be left at zero."""
        g = grid(['.s=rb', 'q.hp.', '=====', 'sssss'])
        for row in A.compute(g, teams={(0, 1): 0}):
            self.assertTrue(all(v != 0 for v in row), row)


class FidelityAgainstRealMaps(unittest.TestCase):
    """The rules must reproduce what the game itself wrote."""

    def setUp(self):
        path = os.environ.get("AWRBC_TEST_SAVE")
        if not path or not os.path.isfile(path):
            self.skipTest("set AWRBC_TEST_SAVE to a real maps file")
        self.maps = [schema.build_document(m)
                     for m in savefile.read(path).maps]

    def test_connection_mask_matches_the_game(self):
        structures = A.STRUCTURE_ANCHOR | A.STRUCTURE_BODY
        total = same = 0
        for d in self.maps:
            terrain, flags = d["terrain"], d["flags"]
            teams = {(c["x"], c["y"]): c["team"] for c in d["cells"]
                     if c.get("team") is not None}
            ours = A.compute(terrain, teams, random.Random(1))
            for y, row in enumerate(flags):
                for x, f in enumerate(row):
                    if f & structures:
                        continue            # membership is not derivable
                    total += 1
                    same += (f & 0x1E) == (ours[y][x] & 0x1E)
        if total < 200:
            self.skipTest("save too small to measure against")
        self.assertGreater(same / total, 0.97,
                           "connection mask fidelity %d/%d" % (same, total))


if __name__ == "__main__":
    unittest.main()

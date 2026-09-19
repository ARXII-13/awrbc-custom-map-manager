"""Model tests — pure, no fixtures, no save files."""
import unittest

from awrbc.core.model import AIRPORT, BASE, CITY, HQ, Map, Tile, Unit


def grid(cols, rows, fill=1):
    return [[Tile(type=fill) for _ in range(rows)] for _ in range(cols)]


def empty_units(cols, rows):
    return [[None for _ in range(rows)] for _ in range(cols)]


def make(cols=6, rows=6):
    return Map(name="t", cols=cols, rows=rows,
               tiles=grid(cols, rows), units=empty_units(cols, rows))


class ValidityRule(unittest.TestCase):
    """The rule the game enforces, decoded in docs/format.md:
    every team needs an HQ AND either a unit or a production property."""

    def test_empty_map_is_not_playable(self):
        self.assertFalse(make().is_playable)

    def test_hq_plus_base_each_side_is_playable(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)
        m.tiles[4][5] = Tile(type=BASE, team=1)
        self.assertTrue(m.is_playable)

    def test_hq_without_production_or_units_is_not_playable(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)          # team 1: HQ only
        self.assertFalse(m.is_playable)

    def test_a_unit_satisfies_the_second_clause(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)
        m.units[4][5] = Unit(type=9, team=1)           # one infantry is enough
        self.assertTrue(m.is_playable)

    def test_production_means_base_airport_or_seaport(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=AIRPORT, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)
        m.tiles[4][5] = Tile(type=BASE, team=1)
        self.assertTrue(m.is_playable)

    def test_a_city_is_not_production(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)
        m.tiles[4][5] = Tile(type=CITY, team=1)        # income, but cannot build
        self.assertFalse(m.is_playable)

    def test_imbalance_is_allowed(self):
        """Confirmed in-game: uneven property counts still pass."""
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[2][0] = Tile(type=BASE, team=0)
        m.tiles[3][0] = Tile(type=BASE, team=0)
        m.tiles[5][5] = Tile(type=HQ, team=1)
        m.tiles[4][5] = Tile(type=BASE, team=1)
        self.assertTrue(m.is_playable)


class Ownership(unittest.TestCase):
    def test_neutral_property_is_not_owned(self):
        self.assertFalse(Tile(type=CITY, team=-1).is_owned)

    def test_terrain_has_no_team(self):
        self.assertFalse(Tile(type=1).is_owned)

    def test_neutral_properties_do_not_create_a_team(self):
        m = make()
        m.tiles[2][2] = Tile(type=CITY, team=-1)
        self.assertEqual(m.teams, [])

    def test_per_team_counts(self):
        m = make()
        m.tiles[0][0] = Tile(type=HQ, team=0)
        m.tiles[1][0] = Tile(type=BASE, team=0)
        m.tiles[2][0] = Tile(type=CITY, team=0)
        m.units[3][0] = Unit(type=9, team=0)
        c = m.per_team()[0]
        self.assertEqual((c.hq, c.production, c.properties, c.units), (1, 1, 3, 1))


if __name__ == "__main__":
    unittest.main()

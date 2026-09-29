"""Map validation.

The codes are a stable contract - the CLI renders them, the editor shows them
live and archive CI will key off them - so these pin the codes, not just the
pass/fail.

Severity is the other half of the contract. An error blocks publishing; a
warning is a design choice. Getting that boundary wrong is worse than missing
a check, because it either blocks maps that play fine or waves through maps
that do not.
"""
import unittest

from awrbc.core import schema, validate


def a_map(cols=12, rows=10, units=None, cells=None, terrain=None):
    """A minimal playable two-army map to mutate."""
    grid = [[1] * cols for _ in range(rows)]
    grid[0][0] = 512
    grid[rows - 1][cols - 1] = 512
    base = [
        {"x": 0, "y": 0, "team": 0, "capture": 20},
        {"x": cols - 1, "y": rows - 1, "team": 1, "capture": 20},
    ]
    troops = [
        {"x": 2, "y": 0, "type": 9, "team": 0, "hp": 100000000, "gas": 99, "ammo": 0},
        {"x": cols - 3, "y": rows - 1, "type": 9, "team": 1,
         "hp": 100000000, "gas": 99, "ammo": 0},
    ]
    if terrain:
        for (x, y), value in terrain.items():
            grid[y][x] = value
    doc = {
        "schema": 1, "name": "t", "author": "a",
        "size": {"cols": cols, "rows": rows}, "fog": False, "waterColor": 0,
        "terrain": grid,
        "cells": base + (cells or []),
        "units": troops if units is None else units,
    }
    return schema.from_json(doc)


def codes(report):
    return {f.code for f in report.findings}


class Playability(unittest.TestCase):
    """The rule the game itself enforces."""

    def test_a_plain_two_army_map_passes(self):
        self.assertTrue(validate.check(a_map()).ok)

    def test_one_army_is_not_a_map(self):
        # Everything - both HQs and both units - belongs to team 0, so team 1
        # is absent rather than merely badly equipped.
        m = a_map(units=[{"x": 2, "y": 0, "type": 9, "team": 0,
                          "hp": 100000000, "gas": 99, "ammo": 0}])
        m.tiles[m.cols - 1][m.rows - 1].team = 0
        self.assertIn("play.oneTeam", codes(validate.check(m)))

    def test_a_team_needs_an_hq(self):
        m = a_map()
        m.tiles[0][0].type = 1024                      # demote it to a city
        self.assertIn("play.noHQ", codes(validate.check(m)))

    def test_a_team_needs_units_or_production(self):
        m = a_map(units=[{"x": 9, "y": 9, "type": 9, "team": 1,
                          "hp": 100000000, "gas": 99, "ammo": 0}])
        self.assertIn("play.cannotAct", codes(validate.check(m)))


class UnitLimit(unittest.TestCase):
    """Advance Wars caps an army at 50."""

    def _with(self, count):
        units = [{"x": i % 12, "y": 2 + i // 12, "type": 9, "team": 0,
                  "hp": 100000000, "gas": 99, "ammo": 0} for i in range(count)]
        units.append({"x": 11, "y": 9, "type": 9, "team": 1,
                      "hp": 100000000, "gas": 99, "ammo": 0})
        return a_map(units=units)

    def test_fifty_is_allowed(self):
        self.assertTrue(validate.check(self._with(50)).ok)

    def test_fifty_one_is_an_error(self):
        report = validate.check(self._with(51))
        self.assertIn("units.tooMany", codes(report))
        self.assertFalse(report.ok)

    def test_the_message_names_the_team_and_the_count(self):
        finding = next(f for f in validate.check(self._with(51)).findings
                       if f.code == "units.tooMany")
        self.assertIn("team 0", finding.message)
        self.assertIn("51", finding.message)


class Size(unittest.TestCase):
    """Oversized maps play; they just cannot be edited in the game."""

    def test_within_the_in_game_editor_says_nothing(self):
        self.assertEqual(codes(validate.check(a_map(30, 20))), set())

    def test_beyond_the_in_game_editor_warns_but_does_not_block(self):
        report = validate.check(a_map(40, 30))
        self.assertIn("size.beyondEditor", codes(report))
        self.assertTrue(report.ok, "40x30 was played to completion")

    def test_beyond_the_largest_tested_size_warns(self):
        report = validate.check(a_map(70, 70))
        self.assertIn("size.untested", codes(report))
        self.assertTrue(report.ok, "unknown is not the same as broken")

    def test_an_absurd_size_is_an_error(self):
        report = validate.check(a_map(200, 200))
        self.assertIn("size.absurd", codes(report))
        self.assertFalse(report.ok)


class Structures(unittest.TestCase):
    """A 3x3 structure must be whole, or the game reads a broken object."""

    def _complete(self, ax=4, ay=4, kind=524288):
        terrain, cells = {}, []
        for dy in range(3):
            for dx in range(3):
                terrain[(ax + dx, ay + dy)] = kind
                cell = {"x": ax + dx, "y": ay + dy, "team": -1}
                if dx or dy:
                    cell["offset"] = [dx, dy]
                else:
                    cell["facing"] = "N"
                cells.append(cell)
        return terrain, cells

    def test_a_whole_structure_passes(self):
        terrain, cells = self._complete()
        self.assertTrue(validate.check(a_map(terrain=terrain, cells=cells)).ok)

    def test_a_lone_structure_tile_is_an_error(self):
        m = a_map(terrain={(4, 4): 524288},
                  cells=[{"x": 4, "y": 4, "team": -1, "facing": "N"}])
        self.assertIn("structure.incomplete", codes(validate.check(m)))

    def test_a_hole_in_a_structure_is_an_error(self):
        terrain, cells = self._complete()
        del terrain[(5, 5)]                            # punch out the middle
        cells = [c for c in cells if not (c["x"] == 5 and c["y"] == 5)]
        report = validate.check(a_map(terrain=terrain, cells=cells))
        self.assertIn("structure.incomplete", codes(report))

    def test_the_message_names_the_missing_tiles(self):
        m = a_map(terrain={(4, 4): 524288},
                  cells=[{"x": 4, "y": 4, "team": -1, "facing": "N"}])
        finding = next(f for f in validate.check(m).findings
                       if f.code == "structure.incomplete")
        self.assertIn("2,2", finding.message)


class RealMapsStayValid(unittest.TestCase):
    """Nothing here may start rejecting maps the game itself accepts."""

    def test_every_sample_map_passes(self):
        import glob
        import json
        import os
        paths = glob.glob(os.path.join("web", "samples", "*.json"))
        if not paths:
            self.skipTest("no sample maps checked out")
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            report = validate.check(schema.from_json(doc))
            self.assertTrue(report.ok,
                            "%s: %s" % (doc["name"],
                                        [f.message for f in report.errors]))


if __name__ == "__main__":
    unittest.main()

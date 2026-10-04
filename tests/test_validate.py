"""Map validation.

The codes are a stable contract - the CLI renders them, the editor shows them
live and archive CI will key off them - so these pin the codes, not just the
pass/fail.

Severity is the other half of the contract. An error blocks publishing; a
warning is a design choice. Getting that boundary wrong is worse than missing
a check, because it either blocks maps that play fine or waves through maps
that do not.
"""
import os
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

    def test_the_largest_confirmed_size_is_allowed(self):
        self.assertTrue(validate.check(a_map(64, 64)).ok)

    def test_past_the_limit_is_rejected(self):
        report = validate.check(a_map(70, 70))
        self.assertIn("size.tooLarge", codes(report))
        self.assertFalse(report.ok, "the archive must not serve untested sizes")

    def test_one_dimension_over_is_enough_to_reject(self):
        self.assertIn("size.tooLarge", codes(validate.check(a_map(65, 20))))
        self.assertIn("size.tooLarge", codes(validate.check(a_map(20, 65))))


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

        REPO = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))

        # Anchored to the repo, not the working directory: a cwd-relative glob
        # turns this guard into a silent skip depending on where it was run from.
        paths = glob.glob(os.path.join(REPO, "web", "samples", "*.json"))
        if not paths:
            self.skipTest("no sample maps checked out")
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            report = validate.check(schema.from_json(doc))
            self.assertTrue(report.ok,
                            "%s: %s" % (doc["name"],
                                        [f.message for f in report.errors]))


class TheName(unittest.TestCase):
    """A name is shown to people, so it has to behave like a line of text.

    Not about script injection: every surface that displays a name puts it in
    as text rather than markup, so there is nothing to inject into. These are
    about names that are not names.
    """

    def named(self, name):
        m = a_map()
        m.name = name
        return codes(validate.check(m))

    def test_an_ordinary_name_is_fine(self):
        self.assertNotIn("name.long", self.named("Twin Rivers"))
        self.assertNotIn("name.control", self.named("Twin Rivers"))

    def test_an_empty_name_is_not_an_error(self):
        """Maps in a save often have none, and the display says Untitled."""
        found = self.named("")
        self.assertNotIn("name.control", found)
        self.assertNotIn("name.tooLong", found)

    def test_a_newline_is_refused(self):
        """It breaks one line into two wherever the name is shown."""
        self.assertIn("name.control", self.named("two\nlines"))

    def test_a_tab_is_refused(self):
        self.assertIn("name.control", self.named("a\tb"))

    def test_a_right_to_left_override_is_refused(self):
        """The one that matters. It reorders the text around it, so a name can
        be made to display as something it is not - and nothing escapes it,
        because textContent renders it faithfully."""
        self.assertIn("name.control", self.named("gnp.\u202exe"))

    def test_a_bidi_isolate_is_refused_too(self):
        self.assertIn("name.control", self.named("a\u2066b"))

    def test_the_message_names_the_codepoint(self):
        """"Remove the invisible character" is not an actionable instruction
        unless it says which one."""
        m = a_map()
        m.name = "a\u202eb"
        said = [f.message for f in validate.check(m).findings
                if f.code == "name.control"]
        self.assertTrue(said)
        self.assertIn("U+202E", said[0])

    def test_a_long_name_warns_rather_than_refusing(self):
        """The game's own limit is not known. Refusing on a guess would block
        maps that play."""
        found = self.named("x" * (validate.LONG_NAME + 1))
        self.assertIn("name.long", found)
        self.assertNotIn("name.tooLong", found)

    def test_a_name_at_the_limit_does_not_warn(self):
        self.assertNotIn("name.long", self.named("x" * validate.LONG_NAME))

    def test_an_absurd_name_is_refused(self):
        found = self.named("x" * (validate.MAX_NAME + 1))
        self.assertIn("name.tooLong", found)

    def test_surrounding_space_is_flagged(self):
        """Invisible, and it changes the slug the archive would give it."""
        self.assertIn("name.space", self.named("  Daibi  "))

    def test_the_long_warning_does_not_block_publishing(self):
        m = a_map()
        m.name = "x" * (validate.LONG_NAME + 5)
        report = validate.check(m)
        self.assertEqual([f.code for f in report.errors], [])

    def test_a_control_character_does_block_it(self):
        m = a_map()
        m.name = "a\u202eb"
        self.assertTrue(validate.check(m).errors)


if __name__ == "__main__":
    unittest.main()

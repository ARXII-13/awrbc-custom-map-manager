"""The bridge the desktop app exposes to the page.

Two things matter here and neither is about maps.

A failure must arrive as data. pywebview turns a Python exception into an
unhelpful rejection in the page, so a call that raises gives the UI nothing to
show a person. Every method answers ``{"ok": False, "error": ...}`` instead,
and these pin that for the ways a save can go wrong.

And a write must refuse while the game is running, because the emulator
flushes its own copy of the save over anything put underneath it. The check is
injected so a test can control it rather than owning a process table.

Builds its own save from the type table, like the rest of the suite, so it
runs on a machine with no game and no save.
"""
import os
import shutil
import tempfile
import unittest

from awrbc.core.model import BASE, HQ, Map, Tile
from awrbc.desktop.api import SaveApi

from . import fixture


def a_map(name="Fixture", cols=10, rows=8, teams=2):
    """A playable map: an HQ and a base per army."""
    tiles = [[Tile(type=1) for _ in range(rows)] for _ in range(cols)]
    spots = [(0, 0), (cols - 1, rows - 1), (0, rows - 1), (cols - 1, 0)]
    for t in range(teams):
        x, y = spots[t]
        tiles[x][y] = Tile(type=HQ, team=t)
        tiles[x][(y + 1) % rows] = Tile(type=BASE, team=t)
    return Map(name=name, cols=cols, rows=rows, tiles=tiles,
               units=[[None] * rows for _ in range(cols)])


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "maps")
        with open(self.path, "wb") as fh:
            fh.write(fixture.build_document([a_map("One"), a_map("Two")]))
        self.api = SaveApi(game_running=lambda: False)


class OpeningASave(ApiCase):
    def test_it_reads_every_map(self):
        got = self.api.open_save(self.path)
        self.assertTrue(got["ok"])
        self.assertEqual([m["name"] for m in got["maps"]], ["One", "Two"])

    def test_each_map_comes_back_whole_so_the_page_can_draw_it(self):
        """The list shows real previews, drawn by the editor's own renderer -
        which needs the document, not a summary."""
        entry = self.api.open_save(self.path)["maps"][0]
        self.assertIn("terrain", entry["document"])
        self.assertIn("cells", entry["document"])
        self.assertEqual(entry["document"]["size"]["cols"], 10)

    def test_it_carries_identity_and_derived_facts(self):
        entry = self.api.open_save(self.path)["maps"][0]
        self.assertEqual(len(entry["id"]), 16)
        self.assertEqual(entry["derived"]["players"], 2)
        self.assertTrue(entry["playable"])

    def test_a_missing_file_is_data_not_an_exception(self):
        got = self.api.open_save(os.path.join(self.tmp, "nothing-here"))
        self.assertFalse(got["ok"])
        self.assertIn("error", got)

    def test_a_file_that_is_not_a_save_is_data_too(self):
        junk = os.path.join(self.tmp, "junk")
        with open(junk, "wb") as fh:
            fh.write(b"not a save at all")
        got = self.api.open_save(junk)
        self.assertFalse(got["ok"])

    def test_an_unexpected_failure_still_answers(self):
        """Anything at all, rather than a rejected promise the UI cannot
        explain."""
        got = self.api.open_save(None)
        self.assertFalse(got["ok"])
        self.assertIn("error", got)


class Importing(ApiCase):
    def document(self, name="New"):
        from awrbc.core import schema
        return schema.build_document(a_map(name))

    def test_a_map_goes_in_and_a_backup_comes_out(self):
        before = len(self.api.open_save(self.path)["maps"])
        got = self.api.import_map(self.path, self.document())
        self.assertTrue(got["ok"], got.get("error"))
        self.assertTrue(os.path.exists(got["backup"]),
                        "a write must be recoverable")
        self.assertEqual(len(self.api.open_save(self.path)["maps"]), before + 1)

    def test_an_unplayable_map_is_refused_with_its_reasons(self):
        from awrbc.core import schema
        empty = Map(name="Empty", cols=8, rows=8,
                    tiles=[[Tile(type=1) for _ in range(8)] for _ in range(8)],
                    units=[[None] * 8 for _ in range(8)])
        got = self.api.import_map(self.path, schema.build_document(empty))
        self.assertFalse(got["ok"])
        self.assertTrue(got["findings"], "the UI shows them all at once")

    def test_it_refuses_while_the_game_is_running(self):
        """The emulator writes its own copy over anything underneath it, so
        this is data loss, not an inconvenience."""
        api = SaveApi(game_running=lambda: True)
        got = api.import_map(self.path, self.document())
        self.assertFalse(got["ok"])
        self.assertIn("running", got["error"])

    def test_nothing_is_written_when_the_game_is_running(self):
        api = SaveApi(game_running=lambda: True)
        before = read_bytes(self.path)
        api.import_map(self.path, self.document())
        self.assertEqual(read_bytes(self.path), before)


class Removing(ApiCase):
    def test_a_map_goes_away(self):
        got = self.api.remove_map(self.path, 0)
        self.assertTrue(got["ok"], got.get("error"))
        self.assertEqual(got["removed"], "One")
        self.assertEqual([m["name"] for m in
                          self.api.open_save(self.path)["maps"]], ["Two"])

    def test_an_index_that_is_not_there(self):
        got = self.api.remove_map(self.path, 99)
        self.assertFalse(got["ok"])
        self.assertIn("99", got["error"])

    def test_it_refuses_while_the_game_is_running(self):
        api = SaveApi(game_running=lambda: True)
        self.assertFalse(api.remove_map(self.path, 0)["ok"])


class Backups(ApiCase):
    def test_one_can_be_taken_and_listed(self):
        taken = self.api.backup_now(self.path)
        self.assertTrue(taken["ok"])
        listed = self.api.snapshots(self.path)
        self.assertIn(taken["name"], [s["name"] for s in listed["snapshots"]])

    def test_restoring_puts_the_file_back(self):
        original = read_bytes(self.path)
        taken = self.api.backup_now(self.path)
        self.api.remove_map(self.path, 0)
        self.assertNotEqual(read_bytes(self.path), original)

        got = self.api.restore(self.path, taken["name"])
        self.assertTrue(got["ok"], got.get("error"))
        self.assertEqual(read_bytes(self.path), original)

    def test_restoring_something_that_is_not_there(self):
        got = self.api.restore(self.path, "no-such-snapshot")
        self.assertFalse(got["ok"])


class NothingAboutTheArchive(ApiCase):
    """The bridge is the save side of the split, and nothing else.

    It used to carry `map_identity`, which computed a map's content hash and
    the archive folder it would live in. Nothing ever called it - and it was
    the single reason `awrbc.core.archive` ended up inside the downloaded save
    editor, because PyInstaller follows imports.
    """

    def test_it_offers_nothing_that_talks_about_the_archive(self):
        offered = [n for n in dir(self.api) if not n.startswith("_")]
        self.assertNotIn("map_identity", offered)
        for name in offered:
            self.assertNotIn("archive", name)

    def test_the_module_does_not_import_the_archive(self):
        """What actually keeps it out of the bundle."""
        import awrbc.desktop.api as api
        source = open(api.__file__, encoding="utf-8").read()
        self.assertNotIn("import archive", source)
        self.assertNotIn("core import archive", source)


if __name__ == "__main__":
    unittest.main()

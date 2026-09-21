"""Save reading tests.

Tests that need a real save are skipped unless AWRBC_TEST_SAVE points at one.
Real saves are never committed: they carry creator names and game-format data
(docs/decisions.md #12). Generated fixtures arrive with M5, once the writer
exists to produce them.
"""
import os
import tempfile
import unittest

from awrbc.core import locate, savefile
from awrbc.core.errors import SaveUnreadable

from .support import a_save


class Locate(unittest.TestCase):
    def test_missing_directory_yields_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(locate.find_saves(os.path.join(d, "nope")), [])

    def test_directory_holding_a_maps_file(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "maps"), "wb").write(b"x")
            found = locate.find_saves(d)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].source, "directory")

    def test_jksv_style_savedata_subdirectory(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "SaveData"))
            open(os.path.join(d, "SaveData", "maps"), "wb").write(b"x")
            self.assertEqual(len(locate.find_saves(d)), 1)

    def test_a_maps_file_given_directly(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "maps")
            open(p, "wb").write(b"x")
            found = locate.find_saves(p)
            self.assertEqual(found[0].path, p)
            self.assertEqual(found[0].source, "explicit")

    def test_select_by_profile(self):
        a = locate.SaveCandidate(path="a", profile="0")
        b = locate.SaveCandidate(path="b", profile="1")
        self.assertEqual(locate.select([a, b], "1").path, "b")
        self.assertIsNone(locate.select([a, b], "9"))
        self.assertEqual(locate.select([a, b]).path, "a")


class Reading(unittest.TestCase):
    def test_garbage_raises_save_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "maps")
            open(p, "wb").write(b"not an nrbf stream at all")
            with self.assertRaises(SaveUnreadable):
                savefile.read(p)


class AgainstASave(unittest.TestCase):
    """Exercises the reader against a fixture, or the real save if provided."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path, self.kind = a_save(self.tmp)
        self.doc = savefile.read(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_version_is_supported(self):
        self.assertIn(self.doc.save_version, savefile.SUPPORTED_VERSIONS)

    def test_grid_shape_matches_declared_size(self):
        for m in self.doc.maps:
            self.assertEqual(len(m.tiles), m.cols, m.name)
            self.assertEqual(len(m.units), m.cols, m.name)
            for col in m.tiles:
                self.assertEqual(len(col), m.rows, m.name)

    def test_codec_round_trips_byte_for_byte(self):
        """The reader must not perturb the document it parsed."""
        from awrbc.core import nrbf
        with open(self.path, "rb") as fh:
            raw = fh.read()
        parser = nrbf.load(self.path)
        out = nrbf.write(parser)
        self.assertEqual(out, raw[:len(out)])

    def test_every_map_has_a_metadata_entry(self):
        """Metadata is keyed by slot, not array position."""
        for m in self.doc.maps:
            self.assertTrue(m.slot, "map %r has no slot" % m.name)
            self.assertGreater(m.cols * m.rows, 0, m.name)


if __name__ == "__main__":
    unittest.main()

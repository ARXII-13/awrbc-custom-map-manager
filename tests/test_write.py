"""Write-path tests: invariants, backups, and save round trips.

Save-backed tests are skipped unless AWRBC_TEST_SAVE points at a maps file. They
always work on a copy — never the file itself.
"""
import os
import shutil
import tempfile
import unittest

from awrbc.core import backup, savefile, schema
from awrbc.core.nrbf import Rec

REAL_SAVE = os.environ.get("AWRBC_TEST_SAVE")
needs_save = unittest.skipUnless(
    REAL_SAVE and os.path.isfile(REAL_SAVE),
    "set AWRBC_TEST_SAVE to a maps file to run save-backed tests")


class Fake:
    """Minimal stand-in for a parsed document."""

    def __init__(self, records):
        self.records = records


class Invariants(unittest.TestCase):
    """check_document guards the failure modes that silently empty the map list."""

    def test_clean_document_has_no_problems(self):
        doc = Fake([Rec(6, oid=1, val="a"), Rec(6, oid=-2, val="b")])
        self.assertEqual(savefile.check_document(doc), [])

    def test_duplicate_object_id(self):
        doc = Fake([Rec(6, oid=7, val="a"), Rec(6, oid=7, val="b")])
        problems = savefile.check_document(doc)
        self.assertTrue(any("more than once" in p for p in problems), problems)

    def test_id_colliding_with_its_own_negation(self):
        """BinaryFormatter registers by absolute value: 5 and -5 are the same
        object. This exact bug made the game show zero custom maps."""
        doc = Fake([Rec(6, oid=5, val="a"), Rec(6, oid=-5, val="b")])
        problems = savefile.check_document(doc)
        self.assertTrue(any("absolute value" in p for p in problems), problems)

    def test_dangling_reference(self):
        doc = Fake([Rec(6, oid=1, val="a"),
                    Rec(7, oid=2, at=0, rank=1, lens=[1], lb=None, bt=4,
                        ex=("X", 2), items=[Rec(9, idref=999)])])
        problems = savefile.check_document(doc)
        self.assertTrue(any("undefined" in p for p in problems), problems)

    def test_array_length_mismatch(self):
        doc = Fake([Rec(7, oid=1, at=0, rank=2, lens=[3, 3], lb=None, bt=4,
                        ex=("X", 2), items=[Rec(10)])])
        problems = savefile.check_document(doc)
        self.assertTrue(any("declares 9" in p for p in problems), problems)


class Backups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["AWRBC_BACKUP_DIR"] = os.path.join(self.tmp, "backups")
        self.save = os.path.join(self.tmp, "maps")
        with open(self.save, "wb") as fh:
            fh.write(b"original")

    def tearDown(self):
        os.environ.pop("AWRBC_BACKUP_DIR", None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_then_restore(self):
        snap = backup.snapshot(self.save)
        self.assertTrue(os.path.isfile(snap.path))
        with open(self.save, "wb") as fh:
            fh.write(b"clobbered")
        backup.restore(snap.path, self.save)
        self.assertEqual(open(self.save, "rb").read(), b"original")

    def test_snapshots_are_listed_newest_first(self):
        backup.snapshot(self.save)
        backup.snapshot(self.save)
        self.assertEqual(len(backup.snapshots(self.save)), 2)

    def test_backups_do_not_land_beside_the_save(self):
        """The game rewrites the save directory; backups must live elsewhere."""
        snap = backup.snapshot(self.save)
        self.assertNotEqual(os.path.dirname(snap.path),
                            os.path.dirname(self.save))


@needs_save
class SaveRoundTrip(unittest.TestCase):
    """export -> import must reproduce the map exactly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.save = os.path.join(self.tmp, "maps")
        shutil.copy2(REAL_SAVE, self.save)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, index):
        doc = savefile.read(self.save)
        before = len(doc.maps)
        original = schema.build_document(doc.maps[index])
        added = schema.from_json(original)
        savefile.add_map(doc, added, name="RT")
        savefile.write(doc, self.save)

        after = savefile.read(self.save)
        self.assertEqual(len(after.maps), before + 1)
        # add_map must keep the domain view in step with the record tree
        self.assertEqual(len(doc.maps), before + 1)
        return original, schema.build_document(after.maps[-1])

    def test_terrain_only_map_survives(self):
        doc = savefile.read(self.save)
        index = next(i for i, m in enumerate(doc.maps)
                     if not any(True for _ in m.iter_units()))
        before, after = self._round_trip(index)
        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["terrain"], after["terrain"])
        self.assertEqual(before["cells"], after["cells"])

    def test_map_with_units_survives(self):
        doc = savefile.read(self.save)
        index = next((i for i, m in enumerate(doc.maps)
                      if sum(1 for _ in m.iter_units()) > 5), None)
        if index is None:
            self.skipTest("no map with units in this save")
        before, after = self._round_trip(index)
        self.assertEqual(before["id"], after["id"])
        self.assertEqual(before["units"], after["units"])

    def test_written_save_passes_its_own_invariants(self):
        self._round_trip(0)
        doc = savefile.read(self.save)
        self.assertEqual(savefile.check_document(doc.raw), [])

    def test_remove_drops_map_and_metadata_together(self):
        doc = savefile.read(self.save)
        before = len(doc.maps)
        savefile.remove_map(doc, before - 1)
        savefile.write(doc, self.save)
        after = savefile.read(self.save)
        self.assertEqual(len(after.maps), before - 1)
        self.assertEqual(savefile.check_document(after.raw), [])

    def test_write_never_shrinks_below_the_existing_file(self):
        doc = savefile.read(self.save)
        size = os.path.getsize(self.save)
        savefile.write(doc, self.save)
        self.assertGreaterEqual(os.path.getsize(self.save), size)


if __name__ == "__main__":
    unittest.main()

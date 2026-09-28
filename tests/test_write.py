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

from .support import BinaryFormatterMixin, a_save


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


class SaveRoundTrip(BinaryFormatterMixin, unittest.TestCase):
    """export -> import must reproduce the map exactly.

    Runs against a generated fixture by default, and against the genuine save
    when AWRBC_TEST_SAVE points at one. Always on a throwaway copy.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.save, self.kind = a_save(self.tmp)

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
        # The gate that matters: would the game actually load this?
        self.assertLoadsInBinaryFormatter(self.save)
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
            self.skipTest("no map with units in this save (fixtures have none)")
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
        if before < 2:
            savefile.add_map(doc, doc.maps[0], name="spare")
            savefile.write(doc, self.save)
            doc = savefile.read(self.save)
            before = len(doc.maps)
        savefile.remove_map(doc, before - 1)
        savefile.write(doc, self.save)
        after = savefile.read(self.save)
        self.assertEqual(len(after.maps), before - 1)
        self.assertEqual(savefile.check_document(after.raw), [])
        self.assertLoadsInBinaryFormatter(self.save)

    def test_an_id_colliding_with_its_negation_is_caught_before_writing(self):
        """The bug that cost a week, guarded end to end.

        Hand-build the collision the old allocator produced and confirm the
        write path refuses it rather than handing the game an empty map list.
        """
        doc = savefile.read(self.save)
        ids = [r.d["oid"] for r in savefile._walk(doc.raw.records)
               if r.d.get("oid") is not None]
        victim = next(r for r in savefile._walk(doc.raw.records)
                      if r.rt == 6 and r.d.get("oid", 0) > 0)
        victim.d["oid"] = -next(i for i in ids if i > 0)
        with self.assertRaises(Exception):
            savefile.serialize(doc)

    def test_imported_maps_are_marked_as_downloads(self):
        """The game already distinguishes a map that came from somebody else."""
        doc = savefile.read(self.save)
        added = schema.from_json(schema.build_document(doc.maps[0]))
        savefile.add_map(doc, added, name="DL")
        savefile.write(doc, self.save)

        flags = {}
        for r in savefile._walk(savefile.read(self.save).raw.records):
            if r.rt in (1, 4, 5) and r.d.get("name") == "AW.CustomMap" \
                    and r.d.get("values"):
                name = r.d["values"][r.d["mnames"].index("Name")]
                parser = savefile.read(self.save).raw
                name = (parser.objects[name.d["idref"]].d["val"]
                        if name.rt == 9 else name.d["val"])
                flags[name] = r.d["values"][r.d["mnames"].index("IsDownload")]
        self.assertTrue(flags.get("DL"), "imported map should be a download")
        others = [v for k, v in flags.items() if k != "DL"]
        self.assertTrue(all(v is False for v in others),
                        "existing maps must not be relabelled: %r" % flags)

    def test_several_maps_can_be_added_before_writing(self):
        """Ids seeds from the parser, so each add must register what it built.

        Without that, the second add_map starts its counter over and hands out
        ids that already exist - the same collision that empties the map list.
        It only appears when two maps are added before a write.
        """
        doc = savefile.read(self.save)
        before = len(doc.maps)
        added = schema.from_json(schema.build_document(doc.maps[0]))
        for name in ("M1", "M2", "M3"):
            savefile.add_map(doc, added, name=name)
        self.assertEqual(savefile.check_document(doc.raw), [])
        savefile.write(doc, self.save)

        after = savefile.read(self.save)
        self.assertEqual(len(after.maps), before + 3)
        self.assertLoadsInBinaryFormatter(self.save)

    def test_write_never_shrinks_below_the_existing_file(self):
        doc = savefile.read(self.save)
        size = os.path.getsize(self.save)
        savefile.write(doc, self.save)
        self.assertGreaterEqual(os.path.getsize(self.save), size)


if __name__ == "__main__":
    unittest.main()

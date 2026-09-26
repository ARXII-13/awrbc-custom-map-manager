"""Game identification tests.

Pointing the tool at another title's save used to fail with a misleading
complaint about the version number. These cover the two signals that tell us
whether a file is ours.
"""
import os
import struct
import tempfile
import unittest

from awrbc.core import identify, nrbf, savefile
from awrbc.core.errors import WrongGame
from awrbc.core.nrbf import Rec

from . import fixture
from .support import a_save


def _document(root_name, members):
    """A minimal NRBF document with a chosen root class."""
    p = nrbf.Parser(b"")
    root = Rec(5, oid=1, name=root_name, mnames=list(members),
               mtypes=[(0, 8)] * len(members), libid=2,
               values=[0] * len(members))
    p.records = [Rec(0, root=1, hdr=-1, maj=1, min=0),
                 Rec(12, id=2, name="Assembly-CSharp"),
                 root, Rec(11)]
    p.objects = {1: root}
    p.header = p.records[0]
    return p


class RootTypeSignal(unittest.TestCase):
    def test_our_root_is_accepted(self):
        p = _document(identify.ROOT_TYPE, sorted(identify.ROOT_MEMBERS))
        self.assertTrue(identify.inspect(p).ok)

    def test_another_games_root_is_rejected(self):
        p = _document("Zelda.SaveData", ["Rupees", "Hearts"])
        who = identify.inspect(p)
        self.assertFalse(who.ok)
        self.assertIn("Zelda.SaveData", who.reason)

    def test_the_same_games_other_document_is_rejected(self):
        """gameState is also Assembly-CSharp NRBF, but it is not the map file."""
        p = _document("AW.State", ["Global", "AW1_State", "AW2_State"])
        who = identify.inspect(p)
        self.assertFalse(who.ok)
        self.assertEqual(who.root_type, "AW.State")

    def test_right_name_but_wrong_members_is_rejected(self):
        p = _document(identify.ROOT_TYPE, ["Something", "Else"])
        who = identify.inspect(p)
        self.assertFalse(who.ok)
        self.assertIn("missing", who.reason)


class TitleIdSignal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # <save-id>/<profile>/SaveData/maps, ExtraData beside the save id
        self.save_id = os.path.join(self.tmp, "0000000000000001")
        savedata = os.path.join(self.save_id, "0", "SaveData")
        os.makedirs(savedata)
        self.maps = os.path.join(savedata, "maps")
        open(self.maps, "wb").close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_extradata(self, title_id):
        with open(os.path.join(self.save_id, "ExtraData0"), "wb") as fh:
            fh.write(struct.pack("<Q", title_id) + b"\0" * 504)

    def test_reads_our_title_id(self):
        self._write_extradata(identify.TITLE_ID)
        self.assertEqual(identify.title_id_for(self.maps), identify.TITLE_ID)

    def test_absent_extradata_is_not_an_error(self):
        """A JKSV dump of just SaveData has no ExtraData; that proves nothing."""
        self.assertIsNone(identify.title_id_for(self.maps))
        p = _document(identify.ROOT_TYPE, sorted(identify.ROOT_MEMBERS))
        self.assertTrue(identify.inspect(p, self.maps).ok)

    def test_a_different_title_id_rejects_even_with_the_right_root(self):
        self._write_extradata(0x0100000000010000)      # some other game
        p = _document(identify.ROOT_TYPE, sorted(identify.ROOT_MEMBERS))
        who = identify.inspect(p, self.maps)
        self.assertFalse(who.ok)
        self.assertIn("title id", who.reason)


class ThroughTheReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_real_save_still_reads(self):
        path, _ = a_save(self.tmp)
        self.assertGreaterEqual(len(savefile.read(path).maps), 1)

    def test_wrong_game_raises_wrong_game_not_a_version_complaint(self):
        path = os.path.join(self.tmp, "maps")
        p = _document("AW.State", ["Global"])
        with open(path, "wb") as fh:
            fh.write(nrbf.write(p))
        with self.assertRaises(WrongGame) as caught:
            savefile.read(path)
        self.assertIn("not an Advance Wars save", str(caught.exception))

    def test_fixtures_identify_as_this_game(self):
        path = fixture.write_fixture_save(os.path.join(self.tmp, "maps"))
        parser = nrbf.load(path)
        self.assertTrue(identify.inspect(parser, path).ok)


if __name__ == "__main__":
    unittest.main()

"""Turning an upload into a submission.

What the intake server asks `awrbc prepare` on every upload, tested directly.
The server itself is TypeScript and tested in `server/src/`; it holds no
opinion about what a valid map is, which is the point of the split.

The one that matters most is `test_the_author_is_the_session_not_the_file`. A
map JSON carries an `author` field and anybody can type anything into it; what
gets committed is the account that signed in. A file is a claim.
"""
import io
import json
import unittest
import zipfile


from .test_archive import a_map

from awrbc.core import submission as submit


def a_bundle(doc, preview=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("map.json", json.dumps(doc))
        if preview is not None:
            z.writestr("preview.png", preview)
    return buf.getvalue()


def a_preview(cols=12, rows=10):
    from .test_preview_check import make_png
    from awrbc.core import preview as pv
    return make_png(cols * pv.PREVIEW_TILE, rows * pv.PREVIEW_TILE)


USER = {"id": "1234567890", "username": "debbie", "avatar": None}


class Reading(unittest.TestCase):
    """What the browser sends, unpacked."""

    def test_a_bare_map_json(self):
        _, doc = a_map(name="Daibi")
        got, image = submit.read_upload(json.dumps(doc).encode("utf-8"))
        self.assertEqual(got["name"], "Daibi")
        self.assertIsNone(image)

    def test_a_bundle_with_a_preview(self):
        _, doc = a_map(name="Daibi")
        got, image = submit.read_upload(a_bundle(doc, a_preview()))
        self.assertEqual(got["name"], "Daibi")
        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_a_zip_with_no_map(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("readme.txt", "nothing")
        with self.assertRaises(submit.Rejected):
            submit.read_upload(buf.getvalue())

    def test_something_that_is_neither(self):
        with self.assertRaises(submit.Rejected):
            submit.read_upload(b"\x00\x01\x02 not a map")

    def test_an_oversized_upload_is_refused_before_parsing(self):
        with self.assertRaises(submit.Rejected) as caught:
            submit.read_upload(b"x" * (submit.MAX_UPLOAD + 1))
        self.assertEqual(caught.exception.code, "too-large")


class Preparing(unittest.TestCase):
    """Deciding what would be committed, without committing it."""

    def prepared(self, catalog=None, **kw):
        _, doc = a_map(name="Daibi", **kw)
        return submit.prepare(a_bundle(doc, a_preview()), catalog or {}, USER)

    def test_a_good_map_becomes_two_files(self):
        got = self.prepared()
        self.assertEqual(got["placement"].path, "maps/2p/daibi/v1.json")
        self.assertEqual(sorted(got["files"]),
                         ["maps/2p/daibi/v1.json", "maps/2p/daibi/v1.png"])

    def test_the_author_is_the_session_not_the_file(self):
        """A file is a claim; a signed-in account is not."""
        _, doc = a_map(name="Daibi")
        doc["author"] = "somebody-else-entirely"
        got = submit.prepare(a_bundle(doc, a_preview()), {}, USER)
        self.assertEqual(got["document"]["author"], "debbie")

    def test_an_unplayable_map_is_refused_with_its_findings(self):
        _, doc = a_map(name="Daibi")
        doc["terrain"] = [[1] * 12 for _ in range(10)]
        doc["cells"] = []
        with self.assertRaises(submit.Rejected) as caught:
            submit.prepare(a_bundle(doc), {}, USER)
        self.assertEqual(caught.exception.code, "invalid")
        self.assertTrue(caught.exception.findings)

    def test_a_preview_that_is_not_an_image_is_refused(self):
        _, doc = a_map(name="Daibi")
        with self.assertRaises(submit.Rejected) as caught:
            submit.prepare(a_bundle(doc, b"MZ\x90\x00 an executable"), {}, USER)
        self.assertEqual(caught.exception.code, "invalid")

    def test_a_preview_of_the_wrong_size_is_refused(self):
        _, doc = a_map(name="Daibi")
        bad = a_preview(cols=40, rows=30)          # not this map's size
        with self.assertRaises(submit.Rejected):
            submit.prepare(a_bundle(doc, bad), {}, USER)

    def test_a_map_already_in_the_archive_is_refused(self):
        from awrbc.core import archive, schema
        _, doc = a_map(name="Daibi")
        m = schema.from_json(doc)
        catalog = {"maps/2p/daibi": {
            "category": "2p", "slug": "daibi", "name": "Daibi",
            "author": "someone",
            "versions": [{"version": 1, "hash": archive.map_hash(m),
                          "cols": 12, "rows": 10, "players": 2}]}}
        with self.assertRaises(submit.Rejected) as caught:
            submit.prepare(a_bundle(doc, a_preview()), catalog, USER)
        self.assertEqual(caught.exception.code, "duplicate")

    def test_a_map_with_no_preview_still_goes_through(self):
        _, doc = a_map(name="Daibi")
        got = submit.prepare(json.dumps(doc).encode("utf-8"), {}, USER)
        self.assertFalse(got["has_preview"])
        self.assertEqual(list(got["files"]), ["maps/2p/daibi/v1.json"])


class ThePullRequest(unittest.TestCase):
    def test_it_says_who_submitted_and_what(self):
        _, doc = a_map(name="Daibi")
        prepared = submit.prepare(a_bundle(doc, a_preview()), {}, USER)
        title, body = submit.pull_request_text(prepared, USER)
        self.assertEqual(title, "Add Daibi")
        self.assertIn("debbie", body)
        self.assertIn("maps/2p/daibi/v1.json", body)
        self.assertIn("CC BY 4.0", body)

    def test_it_flags_a_missing_preview_to_the_reviewer(self):
        _, doc = a_map(name="Daibi")
        prepared = submit.prepare(json.dumps(doc).encode("utf-8"), {}, USER)
        _, body = submit.pull_request_text(prepared, USER)
        self.assertIn("none", body.lower())

    def test_the_branch_name_is_safe_and_readable(self):
        _, doc = a_map(name="Daibi")
        prepared = submit.prepare(a_bundle(doc, a_preview()), {}, USER)
        name = submit.branch_name(prepared["placement"], USER)
        self.assertEqual(name, "submit/daibi-v1-debbie")

    def test_a_hostile_username_cannot_shape_the_branch(self):
        prepared = submit.prepare(
            a_bundle(a_map(name="Daibi")[1], a_preview()), {}, USER)
        nasty = {"id": "1", "username": "../../evil master"}
        name = submit.branch_name(prepared["placement"], nasty)
        self.assertNotIn("..", name)
        self.assertNotIn(" ", name)


if __name__ == "__main__":
    unittest.main()

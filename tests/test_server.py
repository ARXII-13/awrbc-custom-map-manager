"""The intake endpoint.

Nothing here touches the network. Discord and GitHub are both stubbed, which
is the only way to test an OAuth flow and a pull-request bot without an
account, a token and a live repository.

The security properties get the most attention, because they are the ones that
fail silently: an endpoint with no `state` check still signs people in, an
endpoint that trusts the uploaded author field still opens pull requests, and
neither looks wrong from the outside.

Skips entirely when Flask is not installed - the tool does not depend on it,
only the server does.
"""
import io
import json
import unittest
import zipfile

try:
    import flask                                        # noqa: F401
    HAVE_FLASK = True
except ImportError:                                     # pragma: no cover
    HAVE_FLASK = False

from .test_archive import a_map

if HAVE_FLASK:
    from server import app as server_app
    from server import auth, github, submit


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


@unittest.skipUnless(HAVE_FLASK, "flask is not installed")
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


@unittest.skipUnless(HAVE_FLASK, "flask is not installed")
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


@unittest.skipUnless(HAVE_FLASK, "flask is not installed")
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


@unittest.skipUnless(HAVE_FLASK, "flask is not installed")
class SigningIn(unittest.TestCase):
    def setUp(self):
        server_app.app.config["TESTING"] = True
        self.client = server_app.app.test_client()
        server_app._recent.clear()

    def test_health_reports_what_is_missing(self):
        got = self.client.get("/health").get_json()
        self.assertIn("configured", got)

    def test_nobody_is_signed_in_to_begin_with(self):
        self.assertEqual(self.client.get("/auth/me").get_json()["signedIn"],
                         False)

    def test_a_callback_with_no_state_is_refused(self):
        """Without this check, a crafted link signs a victim into the
        attacker's account and their uploads carry the attacker's name."""
        r = self.client.get("/auth/callback?code=abc")
        self.assertEqual(r.status_code, 400)

    def test_a_callback_with_the_wrong_state_is_refused(self):
        with self.client.session_transaction() as s:
            s["oauth_state"] = "the-real-one"
        r = self.client.get("/auth/callback?code=abc&state=a-guess")
        self.assertEqual(r.status_code, 400)

    def test_a_state_can_only_be_used_once(self):
        with self.client.session_transaction() as s:
            s["oauth_state"] = "single-use"
        server_app.auth.exchange = lambda *a, **k: "token"
        server_app.auth.identity = lambda token: USER
        self.addCleanup(setattr, server_app.auth, "exchange", auth.exchange)
        self.addCleanup(setattr, server_app.auth, "identity", auth.identity)

        first = self.client.get("/auth/callback?code=abc&state=single-use")
        self.assertEqual(first.status_code, 302)
        replayed = self.client.get("/auth/callback?code=abc&state=single-use")
        self.assertEqual(replayed.status_code, 400, "a replayed state must fail")

    def test_the_next_parameter_cannot_be_an_absolute_url(self):
        """An open redirect turns a sign-in button into a phishing link."""
        server_app.DISCORD_ID = "id"
        server_app.DISCORD_SECRET = "secret"
        server_app.GITHUB_TOKEN = "token"
        self.addCleanup(setattr, server_app, "DISCORD_ID", "")
        self.addCleanup(setattr, server_app, "DISCORD_SECRET", "")
        self.addCleanup(setattr, server_app, "GITHUB_TOKEN", "")

        self.client.get("/auth/login?next=https://evil.example/steal")
        with self.client.session_transaction() as s:
            self.assertEqual(s.get("after_login"), "")

    def test_login_refuses_when_unconfigured(self):
        r = self.client.get("/auth/login")
        self.assertEqual(r.status_code, 503)


@unittest.skipUnless(HAVE_FLASK, "flask is not installed")
class Submitting(unittest.TestCase):
    def setUp(self):
        server_app.app.config["TESTING"] = True
        self.client = server_app.app.test_client()
        server_app._recent.clear()
        self.opened = []

        # Neither Discord nor GitHub is reachable from a test, and neither
        # should be.
        def fake_submit(branch, files, title, body):
            self.opened.append({"branch": branch, "files": sorted(files),
                                "title": title})
            return "https://github.com/x/y/pull/7", 7
        self.fake = fake_submit
        self.real_library = github.Library
        github.Library = lambda *a, **k: type("L", (), {"submit": staticmethod(fake_submit)})()
        server_app.github.Library = github.Library
        self.addCleanup(setattr, github, "Library", self.real_library)
        self.addCleanup(setattr, server_app.github, "Library", self.real_library)

        from awrbc.core import repo as core_repo
        self.real_fetch = core_repo.fetch_catalog
        core_repo.fetch_catalog = lambda *a, **k: ({}, None)
        server_app.repo.fetch_catalog = core_repo.fetch_catalog
        self.addCleanup(setattr, core_repo, "fetch_catalog", self.real_fetch)
        self.addCleanup(setattr, server_app.repo, "fetch_catalog",
                        self.real_fetch)

    def sign_in(self):
        with self.client.session_transaction() as s:
            s["user"] = USER

    def post(self, blob, agree="true", **extra):
        data = {"file": (io.BytesIO(blob), "bundle.zip"), "agree": agree}
        data.update(extra)
        return self.client.post("/submit", data=data,
                                content_type="multipart/form-data")

    def test_a_stranger_cannot_submit(self):
        r = self.post(a_bundle(a_map()[1], a_preview()))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.opened, [], "nothing must reach GitHub")

    def test_the_licence_confirmation_is_required(self):
        self.sign_in()
        r = self.post(a_bundle(a_map()[1], a_preview()), agree="no")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["code"], "no-licence")
        self.assertEqual(self.opened, [])

    def test_a_signed_in_submission_opens_a_pull_request(self):
        self.sign_in()
        r = self.post(a_bundle(a_map(name="Daibi")[1], a_preview()))
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        got = r.get_json()
        self.assertEqual(got["pullRequest"], "https://github.com/x/y/pull/7")
        self.assertEqual(got["path"], "maps/2p/daibi/v1.json")
        self.assertEqual(self.opened[0]["files"],
                         ["maps/2p/daibi/v1.json", "maps/2p/daibi/v1.png"])

    def test_a_bad_map_never_reaches_github(self):
        self.sign_in()
        _, doc = a_map()
        doc["terrain"] = [[1] * 12 for _ in range(10)]
        doc["cells"] = []
        r = self.post(a_bundle(doc))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.opened, [])

    def test_the_second_submission_in_a_minute_is_slowed_down(self):
        self.sign_in()
        first = self.post(a_bundle(a_map(name="One")[1], a_preview()))
        self.assertEqual(first.status_code, 200)
        second = self.post(a_bundle(a_map(name="Two")[1], a_preview()))
        self.assertEqual(second.status_code, 429)
        self.assertEqual(len(self.opened), 1)

    def test_a_rejected_submission_does_not_count_against_the_limit(self):
        """Being refused for a broken map should not lock you out while you
        fix it."""
        self.sign_in()
        for _ in range(3):
            _, doc = a_map()
            doc["cells"] = []
            doc["terrain"] = [[1] * 12 for _ in range(10)]
            self.assertEqual(self.post(a_bundle(doc)).status_code, 422)
        ok = self.post(a_bundle(a_map(name="Fine")[1], a_preview()))
        self.assertEqual(ok.status_code, 200)


if __name__ == "__main__":
    unittest.main()

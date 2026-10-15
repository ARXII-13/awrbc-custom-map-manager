"""`awrbc publish` and `awrbc catalog`, against a real directory tree.

These use the filesystem rather than mocks. The whole point of the command is
that a file lands in the right place in a checkout, and a mock would assert
that we called ourselves correctly rather than that a contributor ends up with
a submittable repository.

Exit codes matter here as much as behaviour: the intake endpoint tells a broken
map from a refused placement by exit code, without parsing text.
"""
import io
import json
import os
import shutil
import tempfile
import unittest

from awrbc.cli.__main__ import main
from awrbc.core import archive, catalog, preview
from awrbc.core.errors import PublishRefused, ValidationFailed

from .test_archive import a_map
from .test_preview_check import make_png

#: Stands in for whatever the editor drew; nothing here inspects it, because
#: this package can no longer reproduce it. It does have to be a real PNG of
#: the size a 12x10 map renders at - what `a_map` produces - since `publish`
#: now refuses anything else, and a placeholder string would be rejected the
#: same way a smuggled file would.
EDITOR_PNG = make_png(12 * preview.PREVIEW_TILE, 10 * preview.PREVIEW_TILE)


def write_map(path, name="Daibi", teams=2, tags=None, terrain=None,
              author="tester"):
    _, doc = a_map(name=name, teams=teams, tags=tags, terrain=terrain)
    doc["author"] = author
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return doc


class PublishCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.library = os.path.join(self.tmp, "library")
        os.makedirs(os.path.join(self.library, archive.ROOT))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), out=out)
        return code, out.getvalue()

    def publish(self, src, *extra):
        return self.run_cli("publish", src, "--library", self.library, *extra)

    def source(self, filename="map.json", **kw):
        path = os.path.join(self.tmp, filename)
        return path, write_map(path, **kw)

    def read_published(self, rel):
        with open(os.path.join(self.library, *rel.split("/")),
                  encoding="utf-8") as fh:
            return json.load(fh)


class FirstUpload(PublishCase):
    def test_a_map_lands_at_v1(self):
        src, _ = self.source(name="Daibi")
        code, text = self.publish(src)
        self.assertEqual(code, 0, text)
        self.assertTrue(os.path.exists(
            os.path.join(self.library, "maps", "2p", "daibi", "v1.json")))
        self.assertIn("maps/2p/daibi/v1.json", text)

    def test_the_category_folder_comes_from_the_map(self):
        src, _ = self.source(name="Big Fight", teams=4)
        self.publish(src)
        self.assertTrue(os.path.exists(os.path.join(
            self.library, "maps", "4p", "big-fight", "v1.json")))

    def test_the_published_file_agrees_with_its_path(self):
        """What CI checks. If these two can disagree, every submission bounces."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        from awrbc.core import schema
        doc = self.read_published("maps/2p/daibi/v1.json")
        m = schema.from_json(doc)
        self.assertEqual(
            archive.check_path("maps/2p/daibi/v1.json", m).errors, [])

    def test_the_file_is_canonical_not_a_copy(self):
        """Published JSON carries id and derived, whatever the submitter sent."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        doc = self.read_published("maps/2p/daibi/v1.json")
        self.assertIn("id", doc)
        self.assertIn("derived", doc)
        self.assertEqual(doc["derived"]["players"], 2)

    def test_dry_run_writes_nothing(self):
        src, _ = self.source()
        code, text = self.publish(src, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("dry run", text)
        self.assertEqual(catalog.map_files(self.library), [])

    def test_it_prints_the_git_commands(self):
        """Phase 3 has no intake endpoint yet, so the person runs these."""
        src, _ = self.source()
        _, text = self.publish(src)
        self.assertIn("git checkout -b", text)
        self.assertIn("git push", text)


class Revisions(PublishCase):
    def test_an_update_lands_at_v2(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)

        changed = os.path.join(self.tmp, "v2.json")
        doc = write_map(changed, name="Daibi")
        doc["terrain"][5][5] = 16
        with open(changed, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        code, text = self.publish(changed, "--update", "2p/daibi")
        self.assertEqual(code, 0, text)
        self.assertIn("revised maps/2p/daibi/v2.json", text)

    def test_the_version_is_written_into_the_file(self):
        """The archive assigns it; a file that disagrees is what CI rejects."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        changed = os.path.join(self.tmp, "v2.json")
        doc = write_map(changed, name="Daibi")
        doc["terrain"][5][5] = 16
        with open(changed, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self.publish(changed, "--update", "2p/daibi")
        self.assertEqual(self.read_published("maps/2p/daibi/v2.json")["version"],
                         2)

    def test_both_versions_stay_downloadable(self):
        """The reason versions are files and not git history."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        changed = os.path.join(self.tmp, "v2.json")
        doc = write_map(changed, name="Daibi")
        doc["terrain"][5][5] = 16
        with open(changed, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self.publish(changed, "--update", "2p/daibi")
        self.assertEqual(catalog.map_files(self.library),
                         ["maps/2p/daibi/v1.json", "maps/2p/daibi/v2.json"])


class Refusals(PublishCase):
    def test_republishing_the_same_map_is_refused(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        code, _ = self.publish(src)
        self.assertEqual(code, PublishRefused.exit_code)

    def test_the_same_map_under_a_new_name_is_still_a_duplicate(self):
        """The dedupe test that cannot pass by hitting the slug conflict first.

        It caught a real bug: the hash was taken over the submitted JSON rather
        than the canonical form, so two files describing one map hashed
        differently and de-duplication quietly did nothing.
        """
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)

        renamed = os.path.join(self.tmp, "renamed.json")
        doc = write_map(renamed, name="Totally Different Map")
        with open(renamed, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        code, _ = self.publish(renamed)
        self.assertEqual(code, PublishRefused.exit_code)
        self.assertEqual(len(catalog.map_files(self.library)), 1)

    def test_a_hand_edited_file_still_dedupes(self):
        """A submitter's JSON need not look like ours to be the same map."""
        src, doc = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)

        # Same map, differently expressed: no flags grid, reordered keys, and a
        # team on terrain that cannot own one (decision #42).
        messy = os.path.join(self.tmp, "messy.json")
        doc.pop("flags", None)
        doc["cells"] = list(reversed(doc["cells"]))
        with open(messy, "w", encoding="utf-8") as fh:
            json.dump(dict(reversed(list(doc.items()))), fh)

        code, _ = self.publish(messy)
        self.assertEqual(code, PublishRefused.exit_code)

    def test_a_revision_with_no_change_is_refused(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        code, _ = self.publish(src, "--update", "2p/daibi")
        self.assertEqual(code, PublishRefused.exit_code)

    def test_a_refusal_is_a_different_exit_code_from_a_bad_map(self):
        """An intake endpoint has to tell "fix your map" from "already here"."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        refused, _ = self.publish(src)

        lonely = os.path.join(self.tmp, "bad.json")
        doc = write_map(lonely, name="Lonely")
        doc["terrain"] = [[1] * 12 for _ in range(10)]   # no HQs at all
        doc["cells"] = []
        with open(lonely, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        invalid, _ = self.publish(lonely)

        self.assertEqual(refused, PublishRefused.exit_code)
        self.assertEqual(invalid, ValidationFailed.exit_code)
        self.assertNotEqual(refused, invalid)

    def test_an_unplayable_map_is_blocked_unlike_export(self):
        path = os.path.join(self.tmp, "wip.json")
        doc = write_map(path)
        doc["terrain"] = [[1] * 12 for _ in range(10)]
        doc["cells"] = []
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        code, _ = self.publish(path)
        self.assertEqual(code, ValidationFailed.exit_code)
        self.assertEqual(catalog.map_files(self.library), [])

    def test_a_taken_slug_is_refused_not_silently_versioned(self):
        src, _ = self.source(name="Daibi", author="first-author")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)

        other = os.path.join(self.tmp, "other.json")
        doc = write_map(other, name="Daibi", author="someone-else")
        doc["terrain"][5][5] = 16
        with open(other, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        code, _ = self.publish(other)
        self.assertEqual(code, PublishRefused.exit_code)
        self.assertEqual(len(catalog.map_files(self.library)), 1)

    def test_a_bundle_zip_publishes_with_its_own_preview(self):
        """What the editor's Export bundle produces."""
        import zipfile
        src, doc = self.source(name="Daibi")
        bundle = os.path.join(self.tmp, "daibi.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("map.json", json.dumps(doc))
            z.writestr("preview.png", EDITOR_PNG)

        code, text = self.publish(bundle)
        self.assertEqual(code, 0, text)
        with open(os.path.join(self.library, "maps", "2p", "daibi", "v1.png"),
                  "rb") as fh:
            self.assertEqual(fh.read(), EDITOR_PNG)

    def test_a_bundle_wrapped_in_a_folder_still_works(self):
        """A round trip through a file manager usually adds one."""
        import zipfile
        src, doc = self.source(name="Daibi")
        bundle = os.path.join(self.tmp, "wrapped.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("daibi/map.json", json.dumps(doc))
            z.writestr("daibi/preview.png", EDITOR_PNG)

        code, text = self.publish(bundle)
        self.assertEqual(code, 0, text)
        with open(os.path.join(self.library, "maps", "2p", "daibi", "v1.png"),
                  "rb") as fh:
            self.assertEqual(fh.read(), EDITOR_PNG)

    def test_publishing_without_a_preview_succeeds_but_says_so(self):
        """A map with no picture is still a playable map. Only the person
        publishing it can fix that, so they get told rather than refused."""
        src, _ = self.source(name="Daibi")
        code, text = self.publish(src)
        self.assertEqual(code, 0, text)
        self.assertIn("no preview", text)
        self.assertIn("Export bundle", text)
        self.assertFalse(os.path.exists(
            os.path.join(self.library, "maps", "2p", "daibi", "v1.png")))

    def test_a_bundle_directory_works_too(self):
        """Somebody will unzip it before running the command."""
        src, doc = self.source(name="Daibi")
        folder = os.path.join(self.tmp, "daibi-bundle")
        os.makedirs(folder)
        with open(os.path.join(folder, "map.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        with open(os.path.join(folder, "preview.png"), "wb") as fh:
            fh.write(EDITOR_PNG)

        self.assertEqual(self.publish(folder)[0], 0)
        with open(os.path.join(self.library, "maps", "2p", "daibi", "v1.png"),
                  "rb") as fh:
            self.assertEqual(fh.read(), EDITOR_PNG)

    def test_every_form_the_editor_can_produce_is_readable(self):
        """`import` and `publish` share this reader, so neither can be the one
        that rejects what the other accepts - which is what made two export
        buttons a trap rather than a choice."""
        import zipfile
        from awrbc.cli.__main__ import _read_submission

        _, doc = self.source(name="Daibi")
        bare = os.path.join(self.tmp, "bare.json")
        with open(bare, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        bundle = os.path.join(self.tmp, "readable.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("map.json", json.dumps(doc))
            z.writestr("preview.png", EDITOR_PNG)

        folder = os.path.join(self.tmp, "unpacked-readable")
        os.makedirs(folder)
        with open(os.path.join(folder, "map.json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh)

        for source, expect_preview in ((bare, False), (bundle, True),
                                       (folder, False)):
            read, preview = _read_submission(source)
            self.assertEqual(read["name"], "Daibi", source)
            self.assertEqual(bool(preview), expect_preview, source)

    def test_a_zip_with_no_map_in_it_says_so(self):
        import zipfile
        bundle = os.path.join(self.tmp, "empty.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("readme.txt", "nothing here")
        code, _ = self.publish(bundle)
        self.assertNotEqual(code, 0)

    def test_a_missing_library_is_refused_before_anything_is_read(self):
        src, _ = self.source()
        out = io.StringIO()
        code = main(["publish", src, "--library",
                     os.path.join(self.tmp, "nope")], out=out)
        self.assertNotEqual(code, 0)


class Catalog(PublishCase):
    def test_it_indexes_what_was_published(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        code, text = self.run_cli("catalog", "--library", self.library)
        self.assertEqual(code, 0, text)
        index = catalog.load(self.library)
        self.assertIn("maps/2p/daibi", index)
        entry = index["maps/2p/daibi"]
        self.assertEqual(entry["name"], "Daibi")
        self.assertEqual(entry["versions"][0]["players"], 2)

    def test_check_reports_without_writing(self):
        src, _ = self.source()
        self.publish(src)
        self.run_cli("catalog", "--library", self.library, "--check")
        self.assertFalse(os.path.exists(
            os.path.join(self.library, catalog.FILENAME)))

    def test_publishing_records_the_date_beside_the_map(self):
        """When a version appeared is not in the map file, so it is written
        next to it - meta.json, keyed by version (decision #57)."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        meta = catalog.read_meta(self.library, "maps/2p/daibi")
        self.assertEqual(sorted(meta["added"]), ["1"])
        self.assertRegex(meta["added"]["1"], r"^\d{4}-\d{2}-\d{2}$")

    def test_rebuilding_keeps_submission_dates(self):
        """A rebuild takes dates from meta.json, not from the catalog it is
        replacing - which is what lets the catalog be thrown away."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        path = os.path.join(self.library, "maps", "2p", "daibi", catalog.META)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(catalog.meta_document({"1": "2020-01-01"}), fh)

        self.run_cli("catalog", "--library", self.library)
        rebuilt = catalog.load(self.library)
        self.assertEqual(rebuilt["maps/2p/daibi"]["versions"][0]["added"],
                         "2020-01-01")

    def test_an_archive_with_no_meta_still_keeps_its_dates(self):
        """The fallback that lets this ship before the catalog is gone: an
        existing archive has catalog dates and no meta.json yet, and a
        rebuild must not restamp every map with today."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        os.remove(os.path.join(self.library, "maps", "2p", "daibi",
                               catalog.META))
        index = catalog.load(self.library)
        index["maps/2p/daibi"]["versions"][0]["added"] = "2019-05-05"
        with open(os.path.join(self.library, catalog.FILENAME), "wb") as fh:
            fh.write(catalog.payload_bytes(index))

        self.run_cli("catalog", "--library", self.library)
        rebuilt = catalog.load(self.library)
        self.assertEqual(rebuilt["maps/2p/daibi"]["versions"][0]["added"],
                         "2019-05-05")

    def test_one_unreadable_file_does_not_sink_the_catalog(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        broken = os.path.join(self.library, "maps", "2p", "broken", "v1.json")
        os.makedirs(os.path.dirname(broken))
        with open(broken, "w", encoding="utf-8") as fh:
            fh.write("{not json")

        code, text = self.run_cli("catalog", "--library", self.library)
        self.assertEqual(code, ValidationFailed.exit_code)
        self.assertIn("unreadable", text)
        self.assertIn("maps/2p/daibi", catalog.load(self.library))

    def test_rebuilding_twice_gives_an_identical_file(self):
        """A regeneration commit should show real changes or nothing at all."""
        src, _ = self.source()
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        path = os.path.join(self.library, catalog.FILENAME)
        first = open(path, encoding="utf-8").read()
        self.run_cli("catalog", "--library", self.library)
        self.assertEqual(first, open(path, encoding="utf-8").read())

    def test_it_generates_a_readme_but_never_a_preview(self):
        """The editor draws previews; a second renderer here could only be a
        worse picture of the same map, kept in step forever."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        folder = os.path.join(self.library, "maps", "2p", "daibi")
        self.assertTrue(os.path.exists(os.path.join(folder, "README.md")))
        self.assertFalse(os.path.exists(os.path.join(folder, "v1.png")))

    def test_a_readme_with_no_preview_embeds_no_image(self):
        """Better than a broken image where a picture should be."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        with open(os.path.join(self.library, "maps", "2p", "daibi",
                               "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(".png", text)
        self.assertIn("# Daibi", text)
        self.assertIn("2 players", text)

    def test_a_bundled_preview_is_kept_and_the_readme_shows_it(self):
        import zipfile
        src, doc = self.source(name="Daibi")
        bundle = os.path.join(self.tmp, "shown.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("map.json", json.dumps(doc))
            z.writestr("preview.png", EDITOR_PNG)

        self.publish(bundle)
        self.run_cli("catalog", "--library", self.library)
        folder = os.path.join(self.library, "maps", "2p", "daibi")
        self.assertTrue(os.path.exists(os.path.join(folder, "v1.png")))
        with open(os.path.join(folder, "README.md"), encoding="utf-8") as fh:
            self.assertIn("![Daibi](v1.png)", fh.read())

    def test_a_removed_preview_drops_out_of_the_readme(self):
        """The README is the only thing that has to keep up with an image
        appearing or going away, so that is what --check watches."""
        import zipfile
        src, doc = self.source(name="Daibi")
        bundle = os.path.join(self.tmp, "gone.zip")
        with zipfile.ZipFile(bundle, "w") as z:
            z.writestr("map.json", json.dumps(doc))
            z.writestr("preview.png", EDITOR_PNG)
        self.publish(bundle)
        self.run_cli("catalog", "--library", self.library)

        os.remove(os.path.join(self.library, "maps", "2p", "daibi", "v1.png"))
        code, text = self.run_cli("catalog", "--library", self.library,
                                  "--check")
        self.assertEqual(code, ValidationFailed.exit_code, text)
        self.assertIn("README.md", text)

    def test_regenerating_leaves_an_existing_preview_alone(self):
        """A bundle's preview is drawn by the editor, which has the icons. This
        package cannot reproduce it, so it must not overwrite it."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        shot = os.path.join(self.library, "maps", "2p", "daibi", "v1.png")
        with open(shot, "wb") as fh:
            fh.write(b"pretend this came from the editor")

        self.run_cli("catalog", "--library", self.library)
        with open(shot, "rb") as fh:
            self.assertEqual(fh.read(), b"pretend this came from the editor")

    def test_check_notices_a_missing_readme(self):
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        os.remove(os.path.join(self.library, "maps", "2p", "daibi",
                               "README.md"))
        code, text = self.run_cli("catalog", "--library", self.library,
                                  "--check")
        self.assertEqual(code, ValidationFailed.exit_code)
        self.assertIn("README.md", text)

    def test_check_passes_on_a_freshly_generated_tree(self):
        """The check has to be quiet when nothing is wrong, or it is ignored."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        code, _ = self.run_cli("catalog", "--library", self.library, "--check")
        self.assertEqual(code, 0)

    def test_regenerating_writes_nothing_when_nothing_changed(self):
        """Otherwise every CI run commits a no-op diff."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        _, text = self.run_cli("catalog", "--library", self.library)
        self.assertNotIn("wrote", text)

    def test_publish_can_read_the_tree_instead_of_the_index(self):
        """A stale catalog must not let a duplicate through."""
        src, _ = self.source(name="Daibi")
        self.publish(src)                       # no catalog regenerated
        code, _ = self.publish(src, "--rescan")
        self.assertEqual(code, PublishRefused.exit_code)


if __name__ == "__main__":
    unittest.main()


class WhatAPullRequestIsJudgedOn(PublishCase):
    """`verify --changed` runs on a submission, not on the archive.

    This is the check that made every submission impossible: the index is
    stale in every pull request by definition, because it is rebuilt on
    merge - and the submission rules refuse a pull request that contains it.
    Stale if left out, refused if put in, with no third option (decision #57).
    """

    def submitted(self):
        """Publish a map and generate what travels with it."""
        src, _ = self.source(name="Daibi")
        self.publish(src)
        self.run_cli("catalog", "--library", self.library)
        return ["maps/2p/daibi/v1.json", "maps/2p/daibi/README.md",
                "maps/2p/daibi/meta.json"]

    def verify(self, *changed):
        return self.run_cli("verify", "--library", self.library,
                            "--changed", *changed)

    def test_a_complete_submission_passes(self):
        code, out = self.verify(*self.submitted())
        self.assertEqual(code, 0, out)
        self.assertIn("0 problems", out)

    def test_a_stale_index_is_not_the_submission_s_problem(self):
        changed = self.submitted()
        # Exactly what a merge would fix, and what no contributor can.
        os.remove(os.path.join(self.library, catalog.FILENAME))
        code, out = self.verify(*changed)
        self.assertEqual(code, 0, out)

    def test_the_index_is_still_refused_inside_a_pull_request(self):
        changed = self.submitted()
        code, out = self.verify(*changed, catalog.FILENAME)
        self.assertNotEqual(code, 0)
        self.assertIn("remove it from this pull request", out)

    def test_a_folder_readme_may_travel_with_its_map(self):
        """The opposite of the index: it belongs to one map and must be
        current, so refusing it was what left submissions no way through."""
        code, out = self.verify(*self.submitted())
        self.assertNotIn("README.md\n    generated by", out)

    def test_a_stale_folder_readme_is_caught(self):
        changed = self.submitted()
        readme = os.path.join(self.library, "maps", "2p", "daibi", "README.md")
        with open(readme, "a", encoding="utf-8") as fh:
            fh.write("drifted\n")
        code, out = self.verify(*changed)
        self.assertNotEqual(code, 0)
        self.assertIn("out of date", out)

    def test_another_map_s_stale_readme_is_not(self):
        """A submission is answerable for what it touched. Failing it for a
        folder it never saw is a dead end for whoever is holding it."""
        changed = self.submitted()
        # Three teams, so it is a different map and not refused as a
        # duplicate - the content hash does not include the name.
        other, _ = self.source(filename="other.json", name="Renew", teams=3)
        self.publish(other)
        self.run_cli("catalog", "--library", self.library)
        # 3p, because the category folder is the derived player count.
        readme = os.path.join(self.library, "maps", "3p", "renew", "README.md")
        with open(readme, "a", encoding="utf-8") as fh:
            fh.write("drifted\n")
        code, out = self.verify(*changed)
        self.assertEqual(code, 0, out)

    def test_a_submission_without_its_date_is_refused(self):
        changed = self.submitted()
        os.remove(os.path.join(self.library, "maps", "2p", "daibi",
                               catalog.META))
        code, out = self.verify(*changed)
        self.assertNotEqual(code, 0)
        self.assertIn("when each version arrived", out)

    def test_a_date_for_a_version_that_is_not_there_is_refused(self):
        changed = self.submitted()
        path = os.path.join(self.library, "maps", "2p", "daibi", catalog.META)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(catalog.meta_document({"1": "2026-01-01",
                                             "7": "2026-01-02"}), fh)
        code, out = self.verify(*changed)
        self.assertNotEqual(code, 0)
        self.assertIn("which is not here", out)

    def test_the_whole_archive_is_still_checked_on_main(self):
        """Without --changed there is no submission to be answerable for, so
        everything is fair game - that is where a bad merge shows up."""
        self.submitted()
        os.remove(os.path.join(self.library, catalog.FILENAME))
        code, out = self.run_cli("verify", "--library", self.library)
        self.assertNotEqual(code, 0)
        self.assertIn("out of date", out)

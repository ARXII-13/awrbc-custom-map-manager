"""Archive paths and the submission pipeline.

Paths are a contract between three things that never talk to each other: the
CLI that writes a submission, the library's CI that checks one, and the website
that links to it. So these pin the exact strings, not just the shape.

The ``plan`` tests are the write pipeline. Its whole job is to refuse to guess -
a duplicate and a name collision are both "I will not decide this for you", and
that is the behaviour worth protecting.
"""
import unittest

from awrbc.core import archive, schema, validate


def a_map(cols=12, rows=10, name="Daibi", teams=2, tags=None, version=1,
          terrain=None):
    """A minimal playable map with `teams` HQs, one per army."""
    grid = [[1] * cols for _ in range(rows)]
    cells = []
    spots = [(0, 0), (cols - 1, rows - 1), (0, rows - 1), (cols - 1, 0),
             (cols // 2, rows // 2)]
    for team in range(teams):
        x, y = spots[team]
        grid[y][x] = 512
        cells.append({"x": x, "y": y, "team": team, "capture": 20})
    doc = {
        "schema": schema.SCHEMA_VERSION,
        "size": {"cols": cols, "rows": rows},
        "name": name,
        "author": "tester",
        "fog": False,
        "waterColor": 0,
        "terrain": terrain or grid,
        "cells": cells,
        "units": [{"x": 1 + t, "y": 1, "team": t, "type": 1, "hp": 100}
                  for t in range(teams)],
        "tags": list(tags or []),
        "version": version,
    }
    return schema.from_json(doc), doc


class Slugs(unittest.TestCase):
    def test_ordinary_names(self):
        self.assertEqual(archive.slugify("Daibi"), "daibi")
        self.assertEqual(archive.slugify("Twin Rivers"), "twin-rivers")
        self.assertEqual(archive.slugify("  Fog of War!  "), "fog-of-war")
        self.assertEqual(archive.slugify("4P Big 40x30"), "4p-big-40x30")

    def test_runs_and_separators_collapse(self):
        self.assertEqual(archive.slugify("a___b  c//d"), "a-b-c-d")
        self.assertEqual(archive.slugify("--edge--"), "edge")

    def test_name_with_no_ascii_falls_back(self):
        """A Japanese map name is ordinary, not an error."""
        self.assertEqual(archive.slugify("マップ"), "")
        self.assertEqual(archive.slugify("マップ", "a3f91c2e"),
                         "a3f91c2e")

    def test_windows_device_names_are_escaped(self):
        """`maps/2p/aux/` is a directory Windows will not create."""
        for name in ("Aux", "CON", "com1", "LPT9"):
            self.assertEqual(archive.slugify(name), name.lower() + "-map")

    def test_long_names_cut_at_a_word_boundary(self):
        slug = archive.slugify("the island of endless summer and winter wars "
                               "forever and ever")
        self.assertLessEqual(len(slug), archive.MAX_SLUG)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(slug.startswith("the-island-of-endless-summer"))

    def test_a_slug_is_always_a_legal_slug(self):
        for name in ("Aux", "マップ 2", "a" * 80, "-- ? --", "4p!!"):
            slug = archive.slugify(name, "deadbeef")
            self.assertRegex(slug, archive.SLUG_RE)


class Categories(unittest.TestCase):
    def test_player_count_comes_from_the_map(self):
        for teams in (2, 3, 4, 5):
            m, _ = a_map(teams=teams)
            self.assertEqual(archive.category_for(m), "%dp" % teams)

    def test_special_tag_overrides_the_player_count(self):
        m, _ = a_map(teams=3, tags=["special"])
        self.assertEqual(archive.category_for(m), "special")

    def test_other_tags_do_not_move_a_map(self):
        m, _ = a_map(teams=3, tags=["competitive", "symmetric"])
        self.assertEqual(archive.category_for(m), "3p")

    def test_every_category_parses(self):
        for teams in (2, 3, 4, 5):
            m, doc = a_map(teams=teams)
            archive.parse(archive.folder_for(m) + "/" +
                          archive.version_file(1))


class Paths(unittest.TestCase):
    def test_folder_comes_from_the_map(self):
        m, doc = a_map(name="Twin Rivers", teams=4, version=3)
        self.assertEqual(archive.folder_for(m), "maps/4p/twin-rivers")
        # Not folder_for's business: the filename follows the version the
        # archive assigns, which only `plan` knows.
        self.assertEqual(archive.version_file(3), "v3.json")

    def test_round_trip(self):
        p = archive.parse("maps/2p/daibi/v2.json")
        self.assertEqual((p.category, p.slug, p.version), ("2p", "daibi", 2))
        self.assertEqual(p.folder, "maps/2p/daibi")
        self.assertEqual(str(p), "maps/2p/daibi/v2.json")

    def test_windows_separators_are_accepted(self):
        """Contributors submit from Windows; the path they paste has backslashes."""
        p = archive.parse("maps\\2p\\daibi\\v1.json")
        self.assertEqual(p.slug, "daibi")

    def test_rejected_paths_say_which_part_is_wrong(self):
        bad = {
            "daibi/v1.json": "category",
            "maps/6p/daibi/v1.json": "category",
            "maps/2p/daibi/daibi.json": "version file",
            "maps/2p/daibi/v0.json": "version file",
            "maps/2p/Daibi/v1.json": "folder name",
            "maps/2p/daibi/extra/v1.json": "expected",
            "maps/2p/v1.json": "expected",
        }
        for path, wanted in bad.items():
            with self.assertRaises(ValueError) as caught:
                archive.parse(path)
            self.assertIn(wanted, str(caught.exception), path)


class PathAgreesWithMap(unittest.TestCase):
    def test_a_correct_path_is_clean(self):
        m, doc = a_map(teams=2, version=1)
        self.assertEqual(archive.check_path("maps/2p/daibi/v1.json", m).findings,
                         [])

    def test_wrong_player_folder(self):
        m, _ = a_map(teams=4)
        r = archive.check_path("maps/2p/daibi/v1.json", m)
        self.assertFalse(r.ok)
        self.assertEqual([f.code for f in r.errors], ["path.category"])
        self.assertIn("4 armies", r.errors[0].message)

    def test_special_folder_without_the_tag(self):
        m, _ = a_map(teams=2)
        r = archive.check_path("maps/special/daibi/v1.json", m)
        self.assertIn("does not carry", r.errors[0].message)

    def test_special_tag_filed_under_a_player_count(self):
        m, _ = a_map(teams=2, tags=["special"])
        r = archive.check_path("maps/2p/daibi/v1.json", m)
        self.assertIn("carries", r.errors[0].message)

    def test_version_must_match_the_filename(self):
        m, _ = a_map(version=2)
        r = archive.check_path("maps/2p/daibi/v1.json", m)
        self.assertEqual([f.code for f in r.errors], ["path.version"])

    def test_a_renamed_map_warns_rather_than_blocks(self):
        """Renaming must not orphan earlier revisions, so the folder stays."""
        m, _ = a_map(name="Daibi Revised")
        r = archive.check_path("maps/2p/daibi/v2.json", m)
        self.assertTrue(any(f.code == "path.slug" for f in r.warnings))
        self.assertEqual([f.code for f in r.errors], ["path.version"])

    def test_a_malformed_path_stops_there(self):
        m, _ = a_map()
        r = archive.check_path("somewhere/else.json", m)
        self.assertEqual([f.code for f in r.errors], ["path.shape"])


def catalog_of(*entries):
    return {folder: {"author": author,
                     "versions": [{"version": v, "hash": h}
                                  for v, h in versions]}
            for folder, author, versions in entries}


class Publishing(unittest.TestCase):
    def test_a_first_upload_lands_at_v1(self):
        m, doc = a_map(name="Daibi")
        p = archive.plan(m, {})
        self.assertEqual(p.kind, archive.NEW)
        self.assertEqual(p.path, "maps/2p/daibi/v1.json")
        self.assertEqual(p.version, 1)
        self.assertTrue(p.ok)

    def test_the_uploader_does_not_pick_the_category_or_the_version(self):
        """Everything but the JSON is worked out, which is the point of deriving."""
        m, doc = a_map(name="Big Fight", teams=4, version=99)
        p = archive.plan(m, {})
        self.assertEqual(p.path, "maps/4p/big-fight/v1.json")

    def test_an_update_takes_the_next_version(self):
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "tester", [(1, "old"), (2, "older")]))
        p = archive.plan(m, cat, update="2p/daibi", author="tester")
        self.assertEqual(p.kind, archive.REVISION)
        self.assertEqual(p.path, "maps/2p/daibi/v3.json")

    def test_update_accepts_a_full_path_or_a_bare_folder(self):
        m, doc = a_map()
        cat = catalog_of(("maps/2p/daibi", None, [(1, "old")]))
        for ref in ("2p/daibi", "maps/2p/daibi", "maps/2p/daibi/v1.json"):
            self.assertEqual(archive.plan(m, cat, update=ref).path,
                             "maps/2p/daibi/v2.json", ref)

    def test_identical_bytes_are_a_duplicate_wherever_they_came_from(self):
        m, doc = a_map(name="Daibi")
        digest = archive.map_hash(m)
        cat = catalog_of(("maps/2p/something-else", "tester", [(1, digest)]))
        p = archive.plan(m, cat)
        self.assertEqual(p.kind, archive.DUPLICATE)
        self.assertFalse(p.ok)
        self.assertIn("maps/2p/something-else/v1.json", p.reason)

    def test_a_revision_that_changed_nothing_is_refused(self):
        """The hash excludes name, author, tags and version - so a v2 with no
        actual edit cannot be published, even renamed and retagged."""
        m, doc = a_map(name="Daibi")
        digest = archive.map_hash(m)
        cat = catalog_of(("maps/2p/daibi", "tester", [(1, digest)]))
        m.name, m.tags, m.version = "Daibi Remastered", ["competitive"], 2
        doc["name"], doc["tags"], doc["version"] = m.name, m.tags, m.version
        p = archive.plan(m, cat, update="2p/daibi", author="tester")
        self.assertEqual(p.kind, archive.DUPLICATE)

    def test_a_real_edit_publishes_as_the_next_version(self):
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "tester",
                          [(1, archive.map_hash(m))]))
        m2, doc2 = a_map(name="Daibi")
        doc2["terrain"][5][5] = 16
        m2 = schema.from_json(doc2)
        p = archive.plan(m2, cat, update="2p/daibi", author="tester")
        self.assertEqual(p.kind, archive.REVISION)
        self.assertEqual(p.path, "maps/2p/daibi/v2.json")

    def test_a_taken_name_is_a_conflict_not_a_silent_revision(self):
        """Two people naming a map the same thing is not lineage."""
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "someone-else", [(1, "other")]))
        p = archive.plan(m, cat)
        self.assertEqual(p.kind, archive.CONFLICT)
        self.assertIn("--update", p.reason)

    def test_a_taken_name_says_which_folder_it_collided_with(self):
        """Structured, not only inside the sentence.

        The editor offers "submit this as a new version of that one", and
        reading the path back out of English is not a thing to build on."""
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "someone-else", [(1, "other")]))
        self.assertEqual(archive.plan(m, cat).folder, "maps/2p/daibi")

    def test_carrying_the_folder_is_not_a_promise_it_may_be_revised(self):
        """Planning it as an update is a separate decision, and it refuses."""
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "original-author", [(1, "old")]))
        clash = archive.plan(m, cat, author="someone-else")
        self.assertEqual(clash.folder, "maps/2p/daibi")

        again = archive.plan(m, cat, update=clash.folder, author="someone-else")
        self.assertEqual(again.kind, archive.CONFLICT)
        self.assertIn("maintainer", again.reason)

    def test_updating_something_that_is_not_there(self):
        m, doc = a_map()
        p = archive.plan(m, {}, update="2p/nothing")
        self.assertEqual(p.kind, archive.CONFLICT)
        self.assertIn("nothing at maps/2p/nothing", p.reason)

    def test_revising_someone_elses_map_needs_a_maintainer(self):
        m, doc = a_map(name="Daibi")
        cat = catalog_of(("maps/2p/daibi", "original-author", [(1, "old")]))
        p = archive.plan(m, cat, update="2p/daibi", author="someone-else")
        self.assertEqual(p.kind, archive.CONFLICT)
        self.assertIn("maintainer", p.reason)

    def test_the_planned_path_is_one_ci_would_accept(self):
        """The two halves of the pipeline have to agree, or submissions bounce."""
        m, doc = a_map(name="Twin Rivers", teams=4)
        p = archive.plan(m, {})
        m.version = p.version
        self.assertEqual(archive.check_path(p.path, m).errors, [])

    def test_a_planned_revision_needs_the_version_written_back(self):
        """The archive assigns the version; the file has to be told."""
        m, doc = a_map(name="Daibi", version=1)
        cat = catalog_of(("maps/2p/daibi", "tester", [(1, "old"), (2, "old2")]))
        p = archive.plan(m, cat, update="2p/daibi", author="tester")
        self.assertEqual([f.code for f in archive.check_path(p.path, m).errors],
                         ["path.version"])
        m.version = p.version
        self.assertEqual(archive.check_path(p.path, m).errors, [])


class PublishedMapsAreValid(unittest.TestCase):
    def test_planning_does_not_replace_validation(self):
        """Placement and soundness are different questions; CI asks both."""
        m, doc = a_map(name="Daibi")
        self.assertTrue(archive.plan(m, {}).ok)
        self.assertTrue(validate.check(m).ok)


if __name__ == "__main__":
    unittest.main()

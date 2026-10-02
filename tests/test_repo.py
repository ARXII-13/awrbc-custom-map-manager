"""Reading the published archive.

Everything here runs against a checkout on disk rather than the network. That
is not only for speed: a test suite that needs the internet fails for reasons
that have nothing to do with the change being tested, and these run on CI
runners with no particular reason to reach GitHub.

The network path is one function (``repo._get``) and is covered by the two
cache tests, which stub it.
"""
import json
import os
import shutil
import tempfile
import time
import unittest

from awrbc.core import repo
from awrbc.core.repo import ArchiveUnreachable, MapNotInArchive


def an_entry(slug, category="2p", name=None, author="someone", players=2,
             cols=20, rows=15, versions=(1,), **facts):
    return ("maps/%s/%s" % (category, slug), {
        "category": category, "slug": slug, "name": name or slug.title(),
        "author": author,
        "versions": [{
            "version": v, "hash": "%s-h%d" % (slug, v), "cols": cols,
            "rows": rows, "players": players, "predeployed": False,
            "navy": False, "structures": False, "fog": False, "tags": [],
            "added": "2026-09-%02d" % (20 + v),
            **facts,
        } for v in versions],
    })


def a_catalog(*entries):
    return dict(entries)


CATALOG = a_catalog(
    an_entry("daibi", "2p", name="Daibi", author="arxii", players=2),
    an_entry("twin-rivers", "4p", name="Twin Rivers", author="debbie",
             players=4, cols=30, rows=20, versions=(1, 2), navy=True),
    an_entry("foggy", "4p", name="Foggy", author="arxii", players=4, fog=True),
)


class Searching(unittest.TestCase):
    def names(self, query):
        return [e["slug"] for _, e in repo.search(CATALOG, query)]

    def test_no_query_lists_everything(self):
        self.assertEqual(self.names(""), ["daibi", "foggy", "twin-rivers"])

    def test_matches_name_author_and_category(self):
        self.assertEqual(self.names("daibi"), ["daibi"])
        self.assertEqual(self.names("debbie"), ["twin-rivers"])
        self.assertEqual(self.names("4p"), ["foggy", "twin-rivers"])

    def test_words_narrow_rather_than_widen(self):
        """Typing a second word is asking for less, not more."""
        self.assertEqual(self.names("4p"), ["foggy", "twin-rivers"])
        self.assertEqual(self.names("4p arxii"), ["foggy"])

    def test_derived_facts_are_searchable(self):
        self.assertEqual(self.names("fog"), ["foggy"])
        self.assertEqual(self.names("navy"), ["twin-rivers"])

    def test_size_is_searchable(self):
        self.assertEqual(self.names("30x20"), ["twin-rivers"])

    def test_case_does_not_matter(self):
        self.assertEqual(self.names("DAIBI"), ["daibi"])


class Resolving(unittest.TestCase):
    def test_a_bare_slug(self):
        folder, _, version = repo.resolve(CATALOG, "daibi")
        self.assertEqual((folder, version), ("maps/2p/daibi", 1))

    def test_the_latest_version_by_default(self):
        _, _, version = repo.resolve(CATALOG, "twin-rivers")
        self.assertEqual(version, 2)

    def test_an_explicit_version(self):
        _, _, version = repo.resolve(CATALOG, "twin-rivers@v1")
        self.assertEqual(version, 1)
        self.assertEqual(repo.resolve(CATALOG, "twin-rivers@2")[2], 2)

    def test_qualified_forms(self):
        for ref in ("2p/daibi", "maps/2p/daibi", "/maps/2p/daibi/"):
            self.assertEqual(repo.resolve(CATALOG, ref)[0], "maps/2p/daibi",
                             ref)

    def test_an_unknown_slug_points_at_search(self):
        with self.assertRaises(MapNotInArchive) as caught:
            repo.resolve(CATALOG, "nope")
        self.assertIn("awrbc search", str(caught.exception))

    def test_a_version_that_does_not_exist_lists_the_ones_that_do(self):
        with self.assertRaises(MapNotInArchive) as caught:
            repo.resolve(CATALOG, "daibi@v7")
        self.assertIn("v1", str(caught.exception))

    def test_a_nonsense_version(self):
        with self.assertRaises(MapNotInArchive):
            repo.resolve(CATALOG, "daibi@latest")

    def test_an_ambiguous_slug_asks_for_the_longer_form(self):
        """The archive's path rules prevent this, but a hand-edited or
        half-merged catalog can still produce it."""
        clash = dict(CATALOG)
        folder, entry = an_entry("daibi", "4p")
        clash[folder] = entry
        with self.assertRaises(MapNotInArchive) as caught:
            repo.resolve(clash, "daibi")
        self.assertIn("more than one", str(caught.exception))


class ReadingACheckout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.makedirs(os.path.join(self.tmp, "maps", "2p", "daibi"))
        with open(os.path.join(self.tmp, "catalog.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"schema": 1, "maps": CATALOG}, fh)
        with open(os.path.join(self.tmp, "maps", "2p", "daibi", "v1.json"),
                  "w", encoding="utf-8") as fh:
            json.dump({"schema": 1, "name": "Daibi"}, fh)

    def test_the_catalog_loads(self):
        index, stale = repo.load_local(self.tmp)
        self.assertIn("maps/2p/daibi", index)
        self.assertIsNone(stale)

    def test_a_map_loads(self):
        doc = repo.fetch_map("maps/2p/daibi", 1, root=self.tmp)
        self.assertEqual(doc["name"], "Daibi")

    def test_a_checkout_with_no_catalog_says_so(self):
        with self.assertRaises(ArchiveUnreachable):
            repo.load_local(os.path.join(self.tmp, "maps"))


class TheCache(unittest.TestCase):
    """Offline is a normal state. These stub the one function that touches the
    network, rather than reaching for it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        os.environ["AWRBC_CACHE_DIR"] = self.tmp
        self.addCleanup(os.environ.pop, "AWRBC_CACHE_DIR", None)
        self.real_get = repo._get
        self.addCleanup(setattr, repo, "_get", self.real_get)

    def serve(self, payload):
        repo._get = lambda url: json.dumps(payload).encode("utf-8")

    def offline(self):
        """Cut the network off.

        Not named `fail`: TestCase.fail is what every assertion calls when it
        trips, so shadowing it turns an ordinary assertion failure into a
        TypeError about argument counts and hides what actually went wrong.
        """
        def boom(url):
            raise OSError("no network")
        repo._get = boom

    def test_a_fetch_is_cached(self):
        self.serve({"maps": CATALOG})
        index, stale = repo.fetch_catalog()
        self.assertEqual(len(index), 3)
        self.assertIsNone(stale)

        self.offline()                       # second call must not need the net
        index, stale = repo.fetch_catalog()
        self.assertEqual(len(index), 3)
        self.assertIsNone(stale)

    def test_a_stale_cache_beats_nothing(self):
        """A map you downloaded yesterday is still a map you can play."""
        self.serve({"maps": CATALOG})
        repo.fetch_catalog()
        self.offline()

        index, stale = repo.fetch_catalog(max_age=0)
        self.assertEqual(len(index), 3)
        self.assertIsNotNone(stale)       # the caller can warn

    def test_a_cache_stamped_in_the_future_can_still_go_stale(self):
        """Its age is clamped at zero rather than going negative.

        A negative age compares as fresher than any limit, so such a cache
        could never expire. This is not hypothetical: time.time() is granular
        to about 16ms on Windows while the filesystem is far finer, so a file
        just written can be stamped ahead of the clock - which is what made
        the test below it fail on CI and pass everywhere else.
        """
        self.serve({"maps": CATALOG})
        repo.fetch_catalog()
        path = os.path.join(self.tmp, repo.CATALOG)
        future = time.time() + 3600
        os.utime(path, (future, future))

        self.offline()
        index, stale = repo.fetch_catalog(max_age=0)
        self.assertEqual(len(index), 3)
        self.assertIsNotNone(stale, "a future mtime must not read as fresh")
        self.assertGreaterEqual(stale, 0)

    def test_no_cache_and_no_network_is_an_error(self):
        self.offline()
        with self.assertRaises(ArchiveUnreachable) as caught:
            repo.fetch_catalog()
        self.assertIn("--library", str(caught.exception))

    def test_refresh_goes_back_to_the_network(self):
        self.serve({"maps": CATALOG})
        repo.fetch_catalog()
        self.serve({"maps": a_catalog(an_entry("new-one"))})
        index, _ = repo.fetch_catalog(refresh=True)
        self.assertEqual(list(index), ["maps/2p/new-one"])


if __name__ == "__main__":
    unittest.main()

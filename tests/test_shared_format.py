"""The map-document layer, pinned to literal values.

This layer exists twice. awrbc-save-editor has its own copy, because the two
repositories are deliberately independent - neither depends on the other.

That is a decision with one sharp edge, and this is the guard for it. A
content hash that drifts does not raise: de-duplication quietly stops working
and the archive fills with copies of one map. Pinning the hash of a fixed
document to a literal means whichever copy changes fails its own suite, so the
two cannot drift apart in silence.

**This file is kept byte-identical in both repositories.** If you change it
here, change it there. If a value below has to move, it has to move in both,
in the same commit, and everything already published keeps the old hash.
"""
import unittest

from awrbc.core import identity, schema
from awrbc.core.model import BASE, HQ, Map, Tile


def golden_map(name="Golden", cols=10, rows=8, teams=2):
    """A boring, fixed map. Nothing about it is arbitrary except its size."""
    tiles = [[Tile(type=1) for _ in range(rows)] for _ in range(cols)]
    spots = [(0, 0), (cols - 1, rows - 1), (0, rows - 1), (cols - 1, 0)]
    for t in range(teams):
        x, y = spots[t]
        tiles[x][y] = Tile(type=HQ, team=t)
        tiles[x][(y + 1) % rows] = Tile(type=BASE, team=t)
    return Map(name=name, cols=cols, rows=rows, tiles=tiles,
               units=[[None] * rows for _ in range(cols)])


#: The hash of `golden_map()` as JSON. Changing this breaks every published
#: map's identity, so it moves only with a schema version.
GOLDEN_HASH = "6b1408b2f16dc62f"


class TheContentHash(unittest.TestCase):
    def test_it_is_what_it_has_always_been(self):
        doc = schema.to_json(golden_map(), author="nobody")
        self.assertEqual(identity.content_hash(doc), GOLDEN_HASH,
                         "the content hash moved. Every published map's id "
                         "depends on this, and the other repository has its "
                         "own copy of the code that computes it.")

    def test_the_name_is_not_part_of_it(self):
        """Renaming a map does not make it a new one (decision #8)."""
        a = schema.to_json(golden_map(name="One"), author="nobody")
        b = schema.to_json(golden_map(name="Two"), author="nobody")
        self.assertEqual(identity.content_hash(a), identity.content_hash(b))

    def test_the_author_is_not_part_of_it(self):
        a = schema.to_json(golden_map(), author="debbie")
        b = schema.to_json(golden_map(), author="somebody-else")
        self.assertEqual(identity.content_hash(a), identity.content_hash(b))

    def test_the_terrain_is(self):
        m = golden_map()
        m.tiles[5][5] = Tile(type=2)          # one tile of sea
        changed = schema.to_json(m, author="nobody")
        self.assertNotEqual(identity.content_hash(changed), GOLDEN_HASH)


class TheDocumentShape(unittest.TestCase):
    """Both copies have to agree on what a map document *is*, not only on its
    hash - the hash is computed over this."""

    def test_the_keys_are_what_both_sides_expect(self):
        doc = schema.to_json(golden_map(), author="nobody")
        for key in ("schema", "name", "author", "size", "fog", "waterColor",
                    "terrain", "cells", "units"):
            self.assertIn(key, doc)

    def test_terrain_is_row_major(self):
        """The save is column-major and the JSON is not; whichever copy
        forgets that produces maps the other reads transposed."""
        doc = schema.to_json(golden_map(cols=10, rows=8), author="nobody")
        self.assertEqual(len(doc["terrain"]), 8, "one entry per row")
        self.assertEqual(len(doc["terrain"][0]), 10, "each row is cols wide")

    def test_it_round_trips(self):
        doc = schema.to_json(golden_map(), author="nobody")
        again = schema.to_json(schema.from_json(doc), author="nobody")
        self.assertEqual(identity.content_hash(again), GOLDEN_HASH)


if __name__ == "__main__":
    unittest.main()

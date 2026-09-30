"""Map previews.

Two things are worth protecting here. The PNG has to be a real PNG, because it
is hand-encoded and nothing else in the stack would notice if it were not. And
the palette has to match the editor's, because they are written out twice - once
in Python and once in `web/terrain.js` - and a test is what stands in for the
build step that would otherwise be needed to share thirty colours.

The rest is legibility, which a test can only partly speak to: it can pin that
an HQ is drawn differently from a city, not that a person can tell.
"""
import binascii
import os
import re
import struct
import unittest
import zlib

from awrbc.core import preview, schema

from .test_archive import a_map

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   os.pardir, "web", "terrain.js")


def decode_png(data):
    """Unpack our own PNG back to (width, height, pixel rows of RGB tuples)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, chunks = 8, {}
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        want = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        assert binascii.crc32(tag + payload) & 0xFFFFFFFF == want, \
            "bad CRC on %r" % tag
        chunks.setdefault(tag, b"")
        chunks[tag] += payload
        pos += 12 + length

    width, height, depth, mode = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (depth, mode) == (8, 2), "expected 8-bit RGB"
    raw = zlib.decompress(chunks[b"IDAT"])
    stride = width * 3
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        assert raw[start] == 0, "expected filter type 0"
        line = raw[start + 1:start + 1 + stride]
        rows.append([tuple(line[i:i + 3]) for i in range(0, stride, 3)])
    return width, height, rows


class Encoder(unittest.TestCase):
    def test_it_writes_a_png_a_decoder_accepts(self):
        m, _ = a_map(cols=4, rows=3)
        w, h, rows = decode_png(preview.render(m, scale=2))
        self.assertEqual((w, h), (8, 6))
        self.assertEqual(len(rows), 6)
        self.assertEqual(len(rows[0]), 8)

    def test_dimensions_follow_the_map(self):
        m, _ = a_map(cols=30, rows=20)
        w, h, _ = decode_png(preview.render(m))
        self.assertEqual((w, h), (30 * preview.SCALE, 20 * preview.SCALE))

    def test_rendering_is_deterministic(self):
        """Previews are committed; a preview that changed run to run would put
        noise in every regeneration commit."""
        m, _ = a_map()
        self.assertEqual(preview.render(m), preview.render(m))

    def test_a_64x64_map_stays_small(self):
        m, _ = a_map(cols=64, rows=64, teams=4)
        self.assertLess(len(preview.render(m)), 60 * 1024)


class Drawing(unittest.TestCase):
    def pixels(self, m, scale=preview.SCALE):
        return decode_png(preview.render(m, scale))[2]

    def tile_centre(self, rows, x, y, scale=preview.SCALE):
        return rows[y * scale + scale // 2][x * scale + scale // 2]

    def test_plains_is_the_plains_colour(self):
        m, _ = a_map(cols=6, rows=6)
        rows = self.pixels(m)
        self.assertEqual(self.tile_centre(rows, 3, 3),
                         preview._rgb(preview.TERRAIN_COLOR[1]))

    def test_a_property_takes_its_owners_colour(self):
        m, _ = a_map(cols=6, rows=6, teams=2)
        rows = self.pixels(m)
        corner = rows[preview.SCALE // 2][1]          # inside tile (0, 0)
        self.assertEqual(corner, preview._rgb(preview.TEAM_COLOR[0]))

    def test_an_hq_is_marked_differently_from_its_own_colour(self):
        """Starting positions are the first thing anyone looks for."""
        m, _ = a_map(cols=6, rows=6, teams=2)
        rows = self.pixels(m)
        self.assertEqual(self.tile_centre(rows, 0, 0), preview.HQ_MARK)

    def test_the_hq_mark_is_the_same_on_every_army(self):
        """A brightened team colour clipped on yellow; a flat mark cannot."""
        m, _ = a_map(cols=8, rows=8, teams=4)
        rows = self.pixels(m)
        for x, y in ((0, 0), (7, 7), (0, 7), (7, 0)):
            self.assertEqual(self.tile_centre(rows, x, y), preview.HQ_MARK)

    def test_a_unit_is_smaller_than_the_tile_it_stands_on(self):
        """So a unit on its own base does not hide the base."""
        m, _ = a_map(cols=6, rows=6, teams=2)      # unit at (1, 1) on plains
        rows = self.pixels(m)
        plains = preview._rgb(preview.TERRAIN_COLOR[1])
        self.assertNotEqual(self.tile_centre(rows, 1, 1), plains)
        self.assertEqual(rows[1 * preview.SCALE][1 * preview.SCALE], plains)

    def test_unknown_terrain_is_loud(self):
        """An unnamed tile type should be visible, not quietly drawn as grass."""
        _, doc = a_map(cols=6, rows=6)
        doc["terrain"][3][3] = 4194304              # not in any table
        m = schema.from_json(doc)
        rows = self.pixels(m)
        self.assertEqual(self.tile_centre(rows, 3, 3),
                         preview._rgb(preview.UNKNOWN_COLOR))


class PaletteMatchesTheEditor(unittest.TestCase):
    """The colours exist twice. This is what keeps the copies honest."""

    def setUp(self):
        if not os.path.exists(WEB):
            self.skipTest("web/terrain.js not present")
        with open(WEB, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_terrain_colours_agree(self):
        found = {}
        for line in self.source.splitlines():
            m = re.match(r"\s*(\d+):\s*\{.*?color:\s*'(#[0-9a-fA-F]{6})'", line)
            if m:
                found[int(m.group(1))] = m.group(2).lower()
        self.assertTrue(found, "could not read any colours out of terrain.js")
        for tile, color in found.items():
            self.assertIn(tile, preview.TERRAIN_COLOR,
                          "terrain.js has %d and preview.py does not" % tile)
            self.assertEqual(preview.TERRAIN_COLOR[tile], color,
                             "colour for tile %d differs" % tile)

    def test_team_colours_agree(self):
        block = self.source.split("export const TEAMS")[1].split("]")[0]
        found = re.findall(r"color:\s*'(#[0-9a-fA-F]{6})'", block)
        self.assertEqual([c.lower() for c in found], preview.TEAM_COLOR)

    def test_properties_have_no_colour_of_their_own_in_either(self):
        """They take the owner's colour, so a hardcoded one would be a bug."""
        for tile in preview.PROPERTY:
            self.assertNotIn(tile, preview.TERRAIN_COLOR)


class Readme(unittest.TestCase):
    def entry(self, versions=1, **kw):
        base = {"category": "2p", "slug": "daibi", "name": "Daibi",
                "author": "tester", "versions": []}
        base.update(kw)
        for v in range(1, versions + 1):
            base["versions"].append({
                "version": v, "hash": "h%d" % v, "cols": 30, "rows": 20,
                "players": 2, "predeployed": True, "navy": False,
                "structures": False, "fog": False, "tags": [],
                "added": "2026-09-%02d" % v})
        return base

    def test_it_shows_the_newest_preview(self):
        text = preview.readme(self.entry(versions=3), "maps/2p/daibi")
        self.assertIn("![Daibi](v3.png)", text)
        self.assertNotIn("(v1.png)", text)

    def test_every_version_stays_linked(self):
        """Both revisions have to be reachable - that is the point of keeping
        them as files."""
        text = preview.readme(self.entry(versions=2), "maps/2p/daibi")
        self.assertIn("[v1.json](v1.json)", text)
        self.assertIn("[v2.json](v2.json)", text)

    def test_it_says_what_the_map_is(self):
        text = preview.readme(self.entry(), "maps/2p/daibi")
        self.assertIn("2 players", text)
        self.assertIn("30x20", text)
        self.assertIn("predeployed", text)
        self.assertIn("tester", text)

    def test_it_says_it_is_generated(self):
        """Someone will otherwise hand-edit one and lose the edit."""
        self.assertIn("generated", preview.readme(self.entry(), "maps/2p/d"))

    def test_it_survives_a_map_with_nothing_optional(self):
        entry = self.entry()
        entry["author"] = ""
        text = preview.readme(entry, "maps/2p/daibi")
        self.assertIn("# Daibi", text)


if __name__ == "__main__":
    unittest.main()

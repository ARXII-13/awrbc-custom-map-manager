"""Checking a preview that somebody else produced.

The image is untrusted input copied into a public repository, so it is checked
like any other. What these pin is the boundary of what the check can honestly
claim: that the file is a plain PNG of exactly the size that map renders at, and
nothing more. It does **not** prove the picture is of that map. Only a renderer
could, and the one that drew it runs in a browser.

A secret stamped into the header by the editor would not help, which is why
there is no test for one: the editor is a static page, so anything it knows is
public. Signing belongs where a key can be kept - the intake endpoint.
"""
import binascii
import os
import re
import struct
import unittest
import zlib

from awrbc.core import preview

from .test_archive import a_map

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   os.pardir, "web", "index.html")


def make_png(width, height, extra_chunks=(), trailing=b"", break_crc=False):
    """A real, minimal PNG, with hooks for the ways one can be abused."""
    def chunk(tag, payload):
        crc = binascii.crc32(tag + payload) & 0xFFFFFFFF
        if break_crc and tag == b"IHDR":
            crc ^= 0xFFFF
        return struct.pack(">I", len(payload)) + tag + payload + \
            struct.pack(">I", crc)

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    out = [preview.PNG_MAGIC,
           chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))]
    for tag, payload in extra_chunks:
        out.append(chunk(tag, payload))
    out.append(chunk(b"IDAT", zlib.compress(raw, 1)))
    out.append(chunk(b"IEND", b""))
    return b"".join(out) + trailing


def for_map(m, **kw):
    return make_png(m.cols * preview.PREVIEW_TILE,
                    m.rows * preview.PREVIEW_TILE, **kw)


class AGoodPreview(unittest.TestCase):
    def test_passes(self):
        m, _ = a_map(cols=12, rows=10)
        self.assertEqual(preview.check_png(for_map(m), m).findings, [])

    def test_the_real_editor_output_passes(self):
        """Built by hand above; this is the shape a canvas actually emits."""
        m, _ = a_map(cols=12, rows=10)
        png = for_map(m, extra_chunks=[(b"pHYs",
                                        struct.pack(">IIB", 2835, 2835, 1))])
        self.assertTrue(preview.check_png(png, m).ok)

    def test_structure_alone_is_checkable(self):
        """CI sometimes has the file and not the map."""
        self.assertTrue(preview.check_png(make_png(32, 32)).ok)


class ThingsThatAreNotAPreview(unittest.TestCase):
    def check(self, data, m=None):
        return [f.code for f in preview.check_png(data, m).errors]

    def test_not_a_png_at_all(self):
        self.assertEqual(self.check(b"MZ\x90\x00 this is an exe"),
                         ["preview.notPng"])

    def test_a_zip_renamed_to_png(self):
        self.assertEqual(self.check(b"PK\x03\x04 and the rest"),
                         ["preview.notPng"])

    def test_data_hidden_after_the_image(self):
        """A PNG that displays fine can still carry a whole other file."""
        m, _ = a_map(cols=12, rows=10)
        png = for_map(m, trailing=b"PK\x03\x04" + b"x" * 500)
        self.assertIn("preview.trailingData", self.check(png, m))

    def test_a_truncated_file(self):
        m, _ = a_map(cols=12, rows=10)
        self.assertTrue(self.check(for_map(m)[:60], m))

    def test_a_chunk_claiming_to_be_huge(self):
        """The length field is attacker-controlled and must not be trusted."""
        png = preview.PNG_MAGIC + struct.pack(">I", 0x7FFFFFFF) + b"IHDR" \
            + b"\x00" * 8
        self.assertEqual(self.check(png), ["preview.malformed"])

    def test_a_tampered_chunk(self):
        m, _ = a_map(cols=12, rows=10)
        self.assertIn("preview.badChunk",
                      self.check(for_map(m, break_crc=True), m))

    def test_no_header(self):
        png = preview.PNG_MAGIC + b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
        self.assertEqual(self.check(png), ["preview.malformed"])


class ItHasToBeThisMapsSize(unittest.TestCase):
    def test_an_image_of_the_wrong_size_is_refused(self):
        """The tie between picture and map: one tile size, so one image size."""
        m, _ = a_map(cols=31, rows=21)
        r = preview.check_png(make_png(800, 600), m)
        self.assertEqual([f.code for f in r.errors], ["preview.wrongSize"])
        self.assertIn("496x336", r.errors[0].message)

    def test_off_by_one_tile_is_refused(self):
        m, _ = a_map(cols=12, rows=10)
        png = make_png(13 * preview.PREVIEW_TILE, 10 * preview.PREVIEW_TILE)
        self.assertFalse(preview.check_png(png, m).ok)

    def test_dimensions_can_come_from_the_catalog_instead(self):
        """CI checks committed files against the index, not re-parsed maps."""
        png = make_png(31 * preview.PREVIEW_TILE, 21 * preview.PREVIEW_TILE)
        self.assertTrue(preview.check_png(png, tiles=(31, 21)).ok)
        self.assertFalse(preview.check_png(png, tiles=(30, 20)).ok)


class ExtraPayload(unittest.TestCase):
    def test_text_chunks_are_flagged_but_not_fatal(self):
        """A canvas does not emit tEXt. Somebody adding one wants a look, but
        it is not grounds to refuse a map."""
        m, _ = a_map(cols=12, rows=10)
        png = for_map(m, extra_chunks=[(b"tEXt", b"Comment\x00anything at all")])
        r = preview.check_png(png, m)
        self.assertTrue(r.ok)
        self.assertEqual([f.code for f in r.warnings], ["preview.extraChunks"])


class TileSizeMatchesTheEditor(unittest.TestCase):
    """The constant exists in two places and nothing else would notice."""

    def test_it_agrees_with_index_html(self):
        if not os.path.exists(WEB):
            self.skipTest("web/index.html not present")
        with open(WEB, encoding="utf-8") as fh:
            found = re.search(r"const PREVIEW_TILE = (\d+)", fh.read())
        self.assertIsNotNone(found, "PREVIEW_TILE not found in index.html")
        self.assertEqual(int(found.group(1)), preview.PREVIEW_TILE,
                         "the editor renders at a different tile size than "
                         "preview.py expects, so every preview would be "
                         "refused for being the wrong size")


if __name__ == "__main__":
    unittest.main()

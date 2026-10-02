"""The sprite pack that ships in the repository.

Commander Wars art is almost all masks: a pixel's red and green are (x, y)
into a biome palette, and `build_terrain.py` resolves them at build time. Pick
the wrong palette and the art still builds, still loads and still draws - it
just draws in the wrong colours, which no amount of structural checking would
notice. Reef shipped that way once: resolved through the ground palette it came
out magenta coral on bright grass, and nothing failed.

Two things are pinned here. The palettes leave unused table entries at a
distinctive magenta, so magenta in the output means an index the palette does
not define - which is the mistake itself, visible in the pixels. And reef is
water terrain, so its art must sit on something sea-coloured rather than on the
plains tile the renderer lays under everything else.

Skipped where Pillow is absent; it is a build dependency, not a runtime one.
"""
import json
import os
import unittest

try:
    from PIL import Image
except ImportError:  # pragma: no cover - exercised only where Pillow is absent
    Image = None

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "web", "sprites")

#: What a palette holds where nothing is defined. An index that lands here is
#: an index the palette has no colour for, so a sprite carrying it was resolved
#: against the wrong one. Sampled from palette_clear+aw2 at (2, 17), the entry
#: the reef mask used to hit.
UNDEFINED = (160, 73, 140)
UNDEFINED_TOLERANCE = 24

#: Reef, which is coral in open water rather than anything standing on grass.
REEF = "64"


def near(pixel, colour, tolerance):
    return all(abs(pixel[i] - colour[i]) <= tolerance for i in range(3))


@unittest.skipIf(Image is None, "Pillow is not installed")
@unittest.skipUnless(os.path.exists(os.path.join(ROOT, "manifest.json")),
                     "no sprite pack in web/sprites")
class ThePack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "manifest.json"), encoding="utf-8") as fh:
            cls.manifest = json.load(fh)
        cls.sheets = {}
        for name, spec in cls.manifest["sheets"].items():
            path = os.path.join(ROOT, spec["file"] if isinstance(spec, dict)
                                else spec)
            if os.path.exists(path):
                cls.sheets[name] = (Image.open(path).convert("RGBA"),
                                    spec["cw"], spec["ch"])

    def frames(self):
        """Every (label, frame) the manifest names, whatever shape it is in."""
        def walk(label, node):
            if isinstance(node, list) and node and isinstance(node[0], int):
                yield label, node
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    for out in walk("%s[%d]" % (label, i), v):
                        yield out
            elif isinstance(node, dict):
                for k, v in node.items():
                    for out in walk("%s.%s" % (label, k), v):
                        yield out

        for kind in ("terrain", "properties", "units"):
            for tid, entry in (self.manifest.get(kind) or {}).items():
                for out in walk("%s %s" % (kind, tid), entry):
                    yield out

    def crop(self, frame):
        """One frame, or None when its sheet image is not there.

        A pack with a sheet missing is a normal state everywhere else in this
        project - the editor falls through to glyphs - so it is skipped rather
        than raised on."""
        name = frame[2] if len(frame) > 2 else self.manifest["defaultSheet"]
        if name not in self.sheets:
            return None
        sheet, cw, ch = self.sheets[name]
        x, y = frame[0] * cw, frame[1] * ch
        return sheet.crop((x, y, x + cw, y + ch))

    def test_no_sprite_was_resolved_through_a_palette_that_lacks_its_ramps(self):
        """Magenta is the palettes' marker for an index they do not define."""
        bad, looked = [], 0
        for label, frame in self.frames():
            tile = self.crop(frame)
            if tile is None:
                continue
            looked += 1
            px = tile.load()
            for y in range(tile.height):
                for x in range(tile.width):
                    p = px[x, y]
                    if p[3] > 0 and near(p, UNDEFINED, UNDEFINED_TOLERANCE):
                        bad.append("%s at (%d, %d) is %s" % (label, x, y, p[:3]))
                        break
                else:
                    continue
                break
        # Count what was examined. Skipping a frame whose sheet is missing is
        # right, but skipping every frame and reporting an empty list is a
        # pass with nothing behind it - and a build that dropped the sheets is
        # exactly the case pages.yml warns about.
        self.assertGreater(looked, 0, "no frames were examined; is the sheet "
                                      "missing?")
        self.assertEqual(bad, [], "wrong biome palette for: " + "; ".join(bad))

    def test_reef_is_art_rather_than_a_letter_on_flat_colour(self):
        entry = (self.manifest.get("terrain") or {}).get(REEF)
        self.assertIsNotNone(entry, "the pack carries no reef")
        self.assertIn("dirs", entry)
        self.assertIn("", entry["dirs"],
                      "the unsuffixed file is the isolated reef, and the only "
                      "variant dirsFor can currently ask for")

    def test_reef_sits_inside_its_tile_rather_than_filling_it(self):
        """Edge to edge it read as a solid block of coral; inset, it has sea
        around it.

        This also pins the frame width. Reef art is an eight-frame strip, and
        the builder used to cut frame 0 at the display width rather than the
        source width - taking two frames, and getting away with it only
        because the overhang was clipped at the cell edge. Centring a sprite
        does not clip, so a frame carrying two would sit off to one side and
        show up here as art touching an edge.
        """
        tile = self.crop(self.manifest["terrain"][REEF]["dirs"][""])
        self.assertIsNotNone(tile, "the reef frame's sheet is missing")
        box = tile.getchannel("A").getbbox()
        self.assertIsNotNone(box, "the reef frame is empty")
        left, top, right, bottom = box
        self.assertGreater(left, 0, "reef touches the left edge of its tile")
        self.assertLess(right, tile.width,
                        "reef touches the right edge of its tile")
        # The art is one tile tall and sits in the lower half of a two-tile
        # cell, so the floor is the top of that tile rather than the cell.
        self.assertGreater(top, tile.height // 2,
                           "reef reaches above its own tile")
        self.assertLess(bottom, tile.height,
                        "reef touches the bottom edge of its tile")

    def test_reef_is_drawn_to_sit_on_water(self):
        """Its surround is sea rather than the plains the renderer would
        otherwise lay underneath, which is what `onWater` in terrain.js turns
        off. A green surround here is the bug that made reef look wrong."""
        tile = self.crop(self.manifest["terrain"][REEF]["dirs"][""])
        self.assertIsNotNone(tile, "the reef frame's sheet is missing")
        px = tile.load()
        ring = [px[x, y] for y in range(tile.height) for x in range(tile.width)
                if px[x, y][3] > 0]
        self.assertTrue(ring, "the reef frame is empty")
        bluish = [p for p in ring if p[2] > p[0] and p[2] > p[1]]
        self.assertTrue(len(bluish) >= len(ring) * 0.2,
                        "reef should be mostly water; got %d blue of %d"
                        % (len(bluish), len(ring)))


if __name__ == "__main__":
    unittest.main()

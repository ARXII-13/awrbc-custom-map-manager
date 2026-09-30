"""Map previews for the archive.

A folder of JSON files tells a browsing human nothing. These put a picture next
to each version, and a README in each map folder, so GitHub's own directory
view answers "what am I looking at" without anything being installed.

**Original art only, and that is not a style choice.** The renderer here draws
flat colour from ``web/terrain.js`` - colours deliberately not sampled from the
game. The sprite pack is local and gitignored (decision #37); a preview rendered
with it would put game-derived art in a public repository, which is the single
thing that decision exists to prevent. This module therefore has no sprite path
at all, rather than one guarded by a flag somebody could pass.

Previews are generated, like the catalog. They can fall out of step with the
map beside them, so CI regenerates and compares rather than trusting what was
committed.

PNG is written by hand out of ``zlib`` and ``struct``. Adding Pillow for one
encoder that a tile grid needs forty lines of would be a poor trade, and this
keeps the package dependency-free.
"""
import binascii
import struct
import zlib

from . import archive, derive
from .model import HQ

#: Mirrors TERRAIN in web/terrain.js. The two are checked against each other by
#: tests/test_preview.py rather than generated from one another - a build step
#: to share thirty colours between a static page and a Python package costs more
#: than a test that fails when they drift.
TERRAIN_COLOR = {
    1: "#a9cf75",           # Plains
    2: "#4577bd",           # Sea
    4: "#9b8259",           # Mountain
    8: "#5d9647",           # Woods
    16: "#72b4dd",          # River
    32: "#e6d6a0",          # Shoal
    64: "#3c6ba3",          # Reef
    128: "#cac4b2",         # Road
    256: "#b5915f",         # Bridge
    32768: "#a9cf75",       # Pipe
    65536: "#a9cf75",       # Pipe Seam
    524288: "#484850",      # Black Cannon
    1048576: "#585860",     # Mini Cannon
    2097152: "#684870",     # Laser
    8388608: "#783848",     # Death Ray
    33554432: "#cdcdcd",    # Silo
}

#: Terrain that takes an owner's colour instead of one of its own.
PROPERTY = frozenset([512, 1024, 2048, 4096, 8192, 134217728])

TEAM_COLOR = ["#e07f3a", "#4a7ed4", "#48a648", "#ddc63c", "#8a5aa8"]
NEUTRAL_COLOR = "#b4b4b4"

#: Terrain this build has no colour for. Magenta on purpose: an unnamed tile
#: type should be obvious in a preview, not quietly drawn as grass.
UNKNOWN_COLOR = "#ff00ff"

#: The centre of an HQ. Flat, so it reads the same on every army colour.
HQ_MARK = (245, 245, 245)

#: Pixels per tile. Ten keeps a 64x64 map at 640px - large enough that a unit
#: dot reads as smaller than the property tile under it, which at eight pixels
#: it did not, and small enough that the file stays a few kilobytes.
SCALE = 10


def _rgb(text):
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))


def _shade(rgb, factor):
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF))


def encode_png(width, height, pixels):
    """A minimal 8-bit RGB PNG. ``pixels`` is one bytes-like row per scanline.

    Filter type 0 on every row: the images are flat colour blocks, so the
    filters that would help a photograph buy nothing here and the encoder stays
    something a person can check.
    """
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    return b"".join([
        b"\x89PNG\r\n\x1a\n",
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(raw, 9)),
        _chunk(b"IEND", b""),
    ])


def _tile_color(tile):
    """The base colour of one tile, before markings."""
    if tile.type in PROPERTY:
        team = tile.team
        if team is None or team < 0 or team >= len(TEAM_COLOR):
            return _rgb(NEUTRAL_COLOR)
        return _rgb(TEAM_COLOR[team])
    return _rgb(TERRAIN_COLOR.get(tile.type, UNKNOWN_COLOR))


def render(m, scale=SCALE):
    """A map as PNG bytes.

    Three things are marked, because they are what someone skimming needs: a
    property is outlined so it reads as a building rather than a coloured tile,
    an HQ carries a bright centre so the starting positions are findable at a
    glance, and a unit is a dot in its owner's colour so a predeployed map looks
    predeployed.
    """
    width, height = m.cols * scale, m.rows * scale
    rows = [bytearray(width * 3) for _ in range(height)]

    def put(px, py, rgb):
        if 0 <= px < width and 0 <= py < height:
            rows[py][px * 3:px * 3 + 3] = bytes(rgb)

    def block(tx, ty, rgb, inset=0):
        for dy in range(inset, scale - inset):
            for dx in range(inset, scale - inset):
                put(tx * scale + dx, ty * scale + dy, rgb)

    for x, y, tile in m.iter_tiles():
        color = _tile_color(tile)
        block(x, y, color)
        if tile.type in PROPERTY:
            # A dark outline, so an owned city does not read as flat terrain
            # that happens to be orange.
            edge = _shade(color, 0.55)
            for d in range(scale):
                put(x * scale + d, y * scale, edge)
                put(x * scale + d, y * scale + scale - 1, edge)
                put(x * scale, y * scale + d, edge)
                put(x * scale + scale - 1, y * scale + d, edge)
            if tile.type == HQ:
                # Near-white rather than a brightened team colour: 1.6x clips
                # on yellow and orange, so two of the five armies had an HQ
                # that looked like an ordinary city.
                block(x, y, HQ_MARK, inset=max(1, scale // 3))

    for ux, uy, u in m.iter_units():
        color = _rgb(TEAM_COLOR[u.team]) if u.team is not None \
            and 0 <= u.team < len(TEAM_COLOR) else _rgb(NEUTRAL_COLOR)
        cx, cy = ux * scale + scale // 2, uy * scale + scale // 2
        # Deliberately smaller than half a tile: a unit standing on its own
        # base has to stay distinguishable from the base.
        radius = max(1, scale // 5)
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx * dx + dy * dy <= radius * radius:
                    put(cx + dx, cy + dy, color)
                elif dx * dx + dy * dy <= (radius + 1) * (radius + 1):
                    put(cx + dx, cy + dy, _shade(color, 0.4))

    return encode_png(width, height, rows)


def preview_file(version):
    return "v%d.png" % version


def _facts(m):
    d = derive.derived_block(m)
    out = ["%d player%s" % (d["players"], "" if d["players"] == 1 else "s"),
           "%dx%d" % (m.cols, m.rows)]
    for key, label in (("predeployed", "predeployed"), ("navy", "navy"),
                       ("structures", "structures"), ("fog", "fog")):
        if d[key]:
            out.append(label)
    return out


def readme(entry, folder):
    """The README GitHub renders under a map folder's file listing.

    Built from the catalog entry rather than from the map files, so it says the
    same thing the index does - a README that disagreed with the catalog would
    be worse than no README.
    """
    versions = sorted(entry.get("versions", []),
                      key=lambda v: v["version"], reverse=True)
    latest = versions[0] if versions else {}
    name = entry.get("name") or entry.get("slug", "")
    lines = ["# %s" % name, ""]

    if latest:
        lines += ["![%s](%s)" % (name, preview_file(latest["version"])), ""]
        facts = ["%d player%s" % (latest["players"],
                                  "" if latest["players"] == 1 else "s"),
                 "%dx%d" % (latest["cols"], latest["rows"])]
        for key in ("predeployed", "navy", "structures", "fog"):
            if latest.get(key):
                facts.append(key)
        lines += [" · ".join(facts), ""]

    author = entry.get("author")
    if author:
        lines += ["By **%s**" % author, ""]
    if latest.get("tags"):
        lines += ["Tagged %s" % ", ".join("`%s`" % t for t in latest["tags"]),
                  ""]

    lines += ["| Version | Added | Download |", "|---|---|---|"]
    for v in versions:
        lines.append("| v%d | %s | [%s](%s) |"
                     % (v["version"], v.get("added", ""),
                        archive.version_file(v["version"]),
                        archive.version_file(v["version"])))
    lines += ["",
              "<sub>In the preview: an outlined square is a property in its "
              "owner's colour, a white centre marks an HQ, and a dot is a "
              "unit. Grey is unowned.</sub>", "",
              "*This file and the images beside it are generated by "
              "`awrbc catalog`; edits here are overwritten.*", ""]
    return "\n".join(lines)

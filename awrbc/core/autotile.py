"""Compute TileFlags from terrain.

Flags select sprites, and the game renders what the save tells it to rather
than recomputing them. So anything that authors a map has to author flags too,
or the map renders wrong. This module is that.

(An earlier version of this docstring said zeroed flags crash Versus. That was
retracted - the black screen was a Ryujinx input-config problem, not the map.
See docs/format.md. Whether zero actually breaks anything is untested.)

Six independent things share the one 32-bit field:

    bit 0       set on terrain that has no connection mask
    bits 1-4    connection mask: N, W, E, S
    bits 1-4    again, as a facing on a structure's anchor
    bits 5-8    inner shoreline corners, sea only
    bits 12-16  per-team sprite, HQ only
    bits 18-25  decorative variant, chosen at random by the editor
    bits 29,30  multi-tile structure: 30 anchor, 29 body

Derived by correlating ~1,900 tiles of game-authored maps against their
neighbours; see docs/format.md. Terrain that carries a connection mask is
reproduced exactly. Decorative variants are not reproducible and do not need
to be - identical neighbourhoods carry nine different values, so the game is
picking at random too.
"""
import random

from .model import HQ, SEAPORT

PLAINS = 1
SEA = 2
MOUNTAIN = 4
WOODS = 8
RIVER = 16
SHOAL = 32
REEF = 64
ROAD = 128
BRIDGE = 256
PIPE = 32768
PIPE_SEAM = 65536
MINI_CANNON = 1048576
LASER = 2097152
BLACK_CANNON = 524288
DEATH_RAY = 8388608

NORTH, WEST, EAST, SOUTH = 1, 2, 3, 4
DIRECTIONS = ((NORTH, 0, -1), (WEST, -1, 0), (EAST, 1, 0), (SOUTH, 0, 1))

#: A tile with no connection mask carries this instead.
PLAIN_BIT = 1

#: What sea considers water, and so draws no shoreline against. A seaport is
#: water only from the side its dock faces; see `_is_water_for`.
WATER = frozenset([SEA, RIVER, SHOAL, REEF, BRIDGE, SEAPORT])

#: Shoal draws a shoreline against rivers and ports, where sea does not.
SHOAL_WATER = frozenset([SEA, SHOAL, REEF, BRIDGE])

#: Sea also draws inner corners, in bits 5-8. Only 17 tiles in the sample carry
#: one, so the assignment below is the best fit to thin data rather than a
#: settled rule. Corners are cosmetic - a wrong one looks slightly off, it does
#: not crash anything - so they are deliberately excluded from `STRUCTURAL`.
CORNERS = (("sw", 5, -1, 1), ("se", 6, 1, 1), ("nw", 7, -1, -1), ("ne", 8, 1, -1))

#: Terrain whose mask links to its own kind.
LINKS_TO = {
    ROAD: frozenset([ROAD, BRIDGE]),
    RIVER: frozenset([RIVER, SEA]),
    PIPE: frozenset([PIPE, PIPE_SEAM, MINI_CANNON, LASER,
                     BLACK_CANNON, DEATH_RAY]),
    PIPE_SEAM: frozenset([PIPE, PIPE_SEAM, MINI_CANNON, LASER,
                          BLACK_CANNON, DEATH_RAY]),
}

#: Terrain that draws a shoreline: the mask marks sides facing land.
SHORELINE = frozenset([SEA, SHOAL])

#: A bridge end points its one bit at the land it abuts; a middle sets both
#: bits along its axis, plus bit 0.
BRIDGE_MIDDLE = {"h": 13, "v": 19}

#: bits 18-25, the eight decorative alternatives observed on plains.
VARIANTS = tuple(1 << b for b in range(18, 26))
VARIANTS_FOR = {
    PLAINS: VARIANTS,
    WOODS: (0, 1 << 18, 1 << 19),
    RIVER: (0, 1 << 18, 1 << 19),
}

#: A seaport always carries this, on top of its single direction bit.
SEAPORT_BIT = 1 << 19

TEAM_BIT = {0: 1 << 12, 1: 1 << 13, 2: 1 << 14, 3: 1 << 15, 4: 1 << 16}

STRUCTURE_ANCHOR = 1 << 30
STRUCTURE_BODY = 1 << 29

#: Structures that aim, and so record which way they face.
DIRECTIONAL = frozenset([BLACK_CANNON, DEATH_RAY, MINI_CANNON])

#: A facing, written on the anchor tile in the same bits the connection mask
#: uses. Confirmed 2026-09-27: a Black Cannon anchor carries 0x40000002 (north)
#: and a Mini Cannon 0x4 (west), while every body tile is 0x20000000 with the
#: low bits clear.
FACING_BIT = {"N": 1 << NORTH, "W": 1 << WEST, "E": 1 << EAST, "S": 1 << SOUTH}


#: Structures that span more than one tile, and so mark an anchor and a body.
MULTI_TILE = frozenset([BLACK_CANNON, DEATH_RAY])


def facing_of(flags):
    """The facing a structure's anchor records, or None for a default."""
    for name, bit in FACING_BIT.items():
        if flags & bit:
            return name
    return None


def structure_flags(kind, offset, facing):
    """Flags for one tile of a structure, or None if it is not one.

    Observed on real maps: a 3x3 anchor is `0x40000000 | facing`, its body
    tiles are `0x20000000` with the low bits clear, and a one-tile cannon is
    just its facing bit. None of them carries the plain bit, so these cannot
    go through the ordinary path.
    """
    if kind in MULTI_TILE:
        if offset and (offset[0] or offset[1]):
            return STRUCTURE_BODY
        return STRUCTURE_ANCHOR | FACING_BIT.get(facing, 0)
    if kind in DIRECTIONAL:
        # Every one-tile cannon observed carries a facing bit - the pair on
        # BLACK are both 0x4, west - so a missing facing means the caller did
        # not record one rather than that the game writes none. North is the
        # fallback, matching what the renderer assumes.
        return FACING_BIT.get(facing or "N", 0)
    return None

#: The bits this module claims to reproduce exactly. Everything else is
#: decoration, and comparing it against a real save is meaningless.
STRUCTURAL = 0x1F | 0x1F000 | STRUCTURE_ANCHOR | STRUCTURE_BODY


def _at(terrain, x, y):
    if 0 <= y < len(terrain) and 0 <= x < len(terrain[0]):
        return terrain[y][x]
    return None


def _port_faces(terrain, x, y):
    """The direction bit a seaport at (x, y) points its dock.

    The game prefers south, then north, then west, then east when a port has
    more than one sea side.
    """
    for bit, dx, dy in ((SOUTH, 0, 1), (NORTH, 0, -1),
                        (WEST, -1, 0), (EAST, 1, 0)):
        if _at(terrain, x + dx, y + dy) == SEA:
            return bit
    return None


def _is_water_for(terrain, x, y, dx, dy, water):
    """Whether the neighbour at (dx, dy) reads as water from (x, y).

    A seaport is a special case: it is water from the side its dock faces and
    land from every other side, which is exactly how it is drawn.
    """
    nx, ny = x + dx, y + dy
    nbr = _at(terrain, nx, ny)
    if nbr is None:
        return True
    if nbr == SEAPORT:
        if water is SHOAL_WATER:
            return False
        facing = _port_faces(terrain, nx, ny)
        return facing == {(-1, 0): EAST, (1, 0): WEST,
                          (0, -1): SOUTH, (0, 1): NORTH}[(dx, dy)]
    return nbr in water


def _bridge_value(terrain, x, y):
    """A bridge is a straight run; ends point at land, middles at both ends."""
    def is_bridge(dx, dy):
        return _at(terrain, x + dx, y + dy) == BRIDGE
    w, e, n, s = (is_bridge(-1, 0), is_bridge(1, 0),
                  is_bridge(0, -1), is_bridge(0, 1))
    if w and e:
        return BRIDGE_MIDDLE["h"]
    if n and s:
        return BRIDGE_MIDDLE["v"]
    # Point at whatever it lands on, preferring a road. A lone bridge tile with
    # land on both sides of one axis is a middle on that axis.
    if not (w or e or n or s):
        solid = lambda dx, dy: not _is_water_for(terrain, x, y, dx, dy, WATER)
        if solid(-1, 0) and solid(1, 0):
            return BRIDGE_MIDDLE["h"]
        if solid(0, -1) and solid(0, 1):
            return BRIDGE_MIDDLE["v"]
    land = [(bit, _at(terrain, x + dx, y + dy))
            for bit, dx, dy in DIRECTIONS]
    for want in (lambda t: t == ROAD,
                 lambda t: t is not None and t not in WATER):
        for bit, nbr in land:
            if want(nbr):
                return 1 << bit
    return BRIDGE_MIDDLE["h"]


def _never_zero(value):
    """No observed tile is ever zero, so an unconnected one still gets bit 0.

    A conservative default: it matches every real map and costs nothing.
    """
    return value if value else PLAIN_BIT


def flags_for(terrain, x, y, team=None, rng=random):
    """The flags for one tile, from its terrain and its neighbours.

    `team` is required for an HQ and ignored elsewhere. `rng` picks decorative
    variants; pass a seeded Random for reproducible output.
    """
    kind = terrain[y][x]

    if kind == BRIDGE:
        return _bridge_value(terrain, x, y)

    if kind == SEAPORT:
        facing = _port_faces(terrain, x, y)
        return ((1 << facing) if facing else PLAIN_BIT) | SEAPORT_BIT

    value = 0
    links = LINKS_TO.get(kind)
    if links is not None:
        for bit, dx, dy in DIRECTIONS:
            if _at(terrain, x + dx, y + dy) in links:
                value |= 1 << bit
    elif kind in SHORELINE:
        water = SHOAL_WATER if kind == SHOAL else WATER
        for bit, dx, dy in DIRECTIONS:
            if not _is_water_for(terrain, x, y, dx, dy, water):
                value |= 1 << bit
        if kind == SEA:
            for _, bit, dx, dy in CORNERS:
                nbr = _at(terrain, x + dx, y + dy)
                flank_a = _is_water_for(terrain, x, y, dx, 0, WATER)
                flank_b = _is_water_for(terrain, x, y, 0, dy, WATER)
                if nbr is not None and nbr not in WATER and flank_a and flank_b:
                    value |= 1 << bit
        if value == 0:
            # Open water with neither shore nor corner carries the no-mask bit.
            value = PLAIN_BIT
    else:
        value |= PLAIN_BIT

    if kind == HQ:
        value |= TEAM_BIT.get(team, TEAM_BIT[0])

    variants = VARIANTS_FOR.get(kind)
    if variants:
        value |= rng.choice(variants)
    return _never_zero(value)


def compute(terrain, teams=None, rng=random):
    """Flags for a whole row-major terrain grid.

    `teams` maps (x, y) to a team number, and only matters for HQs. Multi-tile
    structures are not handled here - whatever places them owns bits 29 and 30,
    because membership is not derivable from terrain alone.
    """
    teams = teams or {}
    return [[flags_for(terrain, x, y, teams.get((x, y)), rng)
             for x in range(len(terrain[0]))]
            for y in range(len(terrain))]

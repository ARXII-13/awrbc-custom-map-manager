"""Domain objects.

Plain dataclasses with no serialization logic. Every other module speaks these:
savefile reads the game's NRBF into them, schema converts them to and from JSON,
validate and derive inspect them.

Values are stored **raw**, exactly as the game holds them. Friendly names for
TileType/UnitType are a presentation concern (see docs/id-tables.md), so a
partially decoded enum never blocks a correct round trip.
"""
from dataclasses import dataclass, field
from typing import Optional

# Raw TileType values that are capturable properties. See docs/id-tables.md.
HQ = 512
CITY = 1024
BASE = 2048
AIRPORT = 4096
SEAPORT = 8192
COM_TOWER = 134217728

PRODUCTION = (BASE, AIRPORT, SEAPORT)
CAPTURABLE = (HQ, CITY, BASE, AIRPORT, SEAPORT, COM_TOWER)

NEUTRAL_TEAM = -1

#: Unit hp is fixed point; the game shows hp/HP_SCALE/10.
HP_SCALE = 1_000_000
FULL_HP = 100 * HP_SCALE


@dataclass
class Coord:
    x: int
    y: int


@dataclass
class Tile:
    """One grid cell.

    ``team`` is None for terrain with no ownership concept, -1 for a neutral
    capturable property, and 0..4 for an owned one.

    ``offset`` is the cell's position within a multi-tile structure, measured
    from the structure's top-left. The game writes null instead of (0,0) on some
    tiles; both mean "not offset".

    ``flags`` is NOT purely cosmetic: bit 30 marks a structure's anchor and bit
    29 its body cells. Do not drop it.

    ``facing`` is "N", "W", "E" or "S" on the anchor of a structure that aims -
    a cannon or a death ray - and None everywhere else. It lives in the same
    flag bits the connection mask uses, so it has to survive a round trip
    independently of them.
    """

    type: int
    flags: int = 0
    team: Optional[int] = None
    facing: Optional[str] = None
    capture_points: int = 0
    hp: int = 0
    offset: Optional[Coord] = None
    has_launched: bool = False

    @property
    def is_production(self) -> bool:
        return self.type in PRODUCTION

    @property
    def is_owned(self) -> bool:
        return self.team is not None and self.team >= 0


@dataclass
class Unit:
    type: int
    team: Optional[int] = None
    hp: int = FULL_HP
    gas: int = 0
    ammo: int = 0
    moved_this_turn: bool = False
    is_capturing: bool = False
    is_diving: bool = False
    is_predeployed: bool = False


@dataclass
class TeamCounts:
    hq: int = 0
    production: int = 0
    properties: int = 0
    units: int = 0

    @property
    def can_play(self) -> bool:
        """The rule the game enforces: an HQ, and something to act with."""
        return self.hq >= 1 and (self.production >= 1 or self.units >= 1)


@dataclass
class Map:
    """A custom map, independent of how it is stored.

    ``tiles`` and ``units`` are indexed ``[x][y]`` to match the game's rank-2
    ``[cols, rows]`` arrays. ``units`` holds None where a cell is empty.

    ``tags`` and ``version`` are the author's, not the game's - nothing in a
    save carries them. They are excluded from the content hash, so retagging a
    map or bumping its version does not make it a different map. Anything that
    *can* be worked out from the terrain, such as how many armies it supports,
    is derived instead, because a stored answer can disagree with the map and a
    derived one cannot.
    """

    name: str = ""
    creator: str = ""
    slot: str = ""
    cols: int = 0
    rows: int = 0
    fog: bool = False
    water_color: int = 0
    tiles: list = field(default_factory=list)
    units: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    version: int = 1

    def iter_tiles(self):
        for x in range(self.cols):
            for y in range(self.rows):
                yield x, y, self.tiles[x][y]

    def iter_units(self):
        for x in range(self.cols):
            for y in range(self.rows):
                u = self.units[x][y]
                if u is not None:
                    yield x, y, u

    @property
    def teams(self) -> list:
        found = set()
        for _, _, t in self.iter_tiles():
            if t.is_owned:
                found.add(t.team)
        for _, _, u in self.iter_units():
            if u.team is not None and u.team >= 0:
                found.add(u.team)
        return sorted(found)

    def per_team(self) -> dict:
        out = {t: TeamCounts() for t in self.teams}
        for _, _, t in self.iter_tiles():
            if t.is_owned and t.team in out:
                c = out[t.team]
                c.properties += 1
                if t.type == HQ:
                    c.hq += 1
                if t.is_production:
                    c.production += 1
        for _, _, u in self.iter_units():
            if u.team in out:
                out[u.team].units += 1
        return out

    @property
    def is_playable(self) -> bool:
        counts = self.per_team()
        return bool(counts) and all(c.can_play for c in counts.values())


@dataclass
class SaveDocument:
    """A parsed maps file. ``raw`` is kept so writes stay lossless."""

    maps: list = field(default_factory=list)
    save_version: int = 0
    path: Optional[str] = None
    raw: object = None
    #: From the save's ExtraData when present; None for a bare SaveData dump.
    title_id: Optional[int] = None

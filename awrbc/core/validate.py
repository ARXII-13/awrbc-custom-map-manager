"""Map checks.

Returns structured findings, never text. The CLI renders them, CI keys off the
codes, and the editor shows them live — so the codes are a stable contract.

Severity decides what blocks:

* ``error``   — blocks publishing to the archive, and blocks writing to a save
* ``warning`` — advisory; design choices, not defects

**Validation is advisory on export and blocking on publish.** Refusing to export
a work-in-progress map would be obnoxious; refusing to publish an unplayable one
is correct.
"""
from dataclasses import dataclass, field

from . import autotile
from .model import CAPTURABLE, Map

ERROR = "error"
WARNING = "warning"

#: Every TileType value seen in a real save. See docs/id-tables.md. Unknown
#: values are a warning rather than an error: the table is still incomplete, and
#: refusing a map because we have not named its terrain would be wrong.
KNOWN_TILE_TYPES = {
    1, 2, 4, 8, 16, 32, 64, 128, 256,
    512, 1024, 2048, 4096, 8192,
    32768, 65536, 524288, 1048576, 2097152, 8388608, 33554432, 134217728,
}
KNOWN_UNIT_TYPES = set(range(1, 20))

#: Advance Wars caps an army at 50 units, and the game enforces it in play.
MAX_UNITS_PER_TEAM = 50

#: What the in-game Design Room will open. Bigger maps import and play fine -
#: 40x30 was played to completion and 64x64 loads - but they can only be edited
#: here, which is worth saying rather than discovering.
IN_GAME_EDITOR_COLS = 30
IN_GAME_EDITOR_ROWS = 20

#: The hard ceiling, in each dimension. 64x64 is the largest size confirmed to
#: load and play, and it is where the line is drawn rather than a guess at
#: where the game breaks: past here a map is rejected, not warned about, so the
#: archive never serves something nobody has run.
MAX_COLS = 64
MAX_ROWS = 64


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    path: str = ""


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def add(self, code, severity, message, path=""):
        self.findings.append(Finding(code, severity, message, path))

    @property
    def errors(self):
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == WARNING]

    @property
    def ok(self) -> bool:
        """True when nothing blocks. Warnings do not block."""
        return not self.errors


def check(m: Map) -> Report:
    r = Report()

    if m.cols <= 0 or m.rows <= 0:
        r.add("size.invalid", ERROR, "map has no area", "size")
        return r
    if len(m.tiles) != m.cols or any(len(c) != m.rows for c in m.tiles):
        r.add("grid.shape", ERROR,
              "tile grid does not match the declared %dx%d" % (m.cols, m.rows),
              "terrain")
        return r

    unknown_tiles = set()
    for x, y, t in m.iter_tiles():
        if t.type not in KNOWN_TILE_TYPES:
            unknown_tiles.add(t.type)
        if t.team is not None and not -1 <= t.team <= 4:
            r.add("cell.team", ERROR, "team %r is out of range" % t.team,
                  "cells[%d,%d]" % (x, y))
        # team -1 means "neutral" and the game writes it on plenty of
        # non-capturable terrain (silos, pipe seams, Black Hole structures).
        # Only an actual owner implies a capturable property.
        if t.team is not None and t.team >= 0 and t.type not in CAPTURABLE:
            r.add("cell.ownership", ERROR,
                  "terrain %d cannot be owned by a team" % t.type,
                  "cells[%d,%d]" % (x, y))
    for value in sorted(unknown_tiles):
        r.add("terrain.unknown", WARNING,
              "terrain value %d is not in the known table" % value, "terrain")

    unknown_units = set()
    for x, y, u in m.iter_units():
        if u.type not in KNOWN_UNIT_TYPES:
            unknown_units.add(u.type)
        if u.team is None or not 0 <= u.team <= 4:
            r.add("unit.team", ERROR, "unit at (%d,%d) has team %r" % (x, y, u.team),
                  "units[%d,%d]" % (x, y))
    for value in sorted(unknown_units):
        r.add("unit.unknown", WARNING,
              "unit value %d is not in the known table" % value, "units")

    # The rule the game itself enforces - see docs/format.md.
    teams = m.teams
    if not teams:
        r.add("play.noTeams", ERROR, "no team owns anything", "cells")
    elif len(teams) < 2:
        r.add("play.oneTeam", ERROR,
              "only team %d is present; a map needs at least two" % teams[0], "cells")
    for team, counts in sorted(m.per_team().items()):
        if counts.hq < 1:
            r.add("play.noHQ", ERROR, "team %d has no HQ" % team, "cells")
        if counts.production < 1 and counts.units < 1:
            r.add("play.cannotAct", ERROR,
                  "team %d has no production property and no units" % team, "cells")

    for team, counts in sorted(m.per_team().items()):
        if counts.units > MAX_UNITS_PER_TEAM:
            r.add("units.tooMany", ERROR,
                  "team %d has %d units; the limit is %d"
                  % (team, counts.units, MAX_UNITS_PER_TEAM), "units")

    _check_structures(m, r)

    # Advisory: design choices, not defects. The game accepts uneven maps.
    per = m.per_team()
    if per:
        counts = [c.properties for c in per.values()]
        if max(counts) - min(counts) > 2:
            r.add("balance.uneven", WARNING,
                  "property counts range from %d to %d across teams"
                  % (min(counts), max(counts)), "cells")
    if m.cols > MAX_COLS or m.rows > MAX_ROWS:
        r.add("size.tooLarge", ERROR,
              "%dx%d is past the %dx%d limit"
              % (m.cols, m.rows, MAX_COLS, MAX_ROWS), "size")
    if m.cols > IN_GAME_EDITOR_COLS or m.rows > IN_GAME_EDITOR_ROWS:
        r.add("size.beyondEditor", WARNING,
              "%dx%d is past the in-game editor's %dx%d; it will play but can "
              "only be edited outside the game"
              % (m.cols, m.rows, IN_GAME_EDITOR_COLS, IN_GAME_EDITOR_ROWS),
              "size")
    if len({t.type for _, _, t in m.iter_tiles()}) < 2:
        r.add("terrain.flat", WARNING, "the map is a single terrain type", "terrain")

    return r


def _check_structures(m: Map, r: Report) -> None:
    """Every 3x3 structure must be whole.

    Eight tiles pointing at an anchor that is not there is a map the game reads
    as broken. The editor cannot produce one, but a hand-written or converted
    JSON can, so this is checked rather than assumed.
    """
    span = 3
    seen = set()
    for x, y, t in m.iter_tiles():
        if t.type not in autotile.MULTI_TILE or (x, y) in seen:
            continue
        off = (t.offset.x, t.offset.y) if t.offset else (0, 0)
        ax, ay = x - off[0], y - off[1]
        if (ax, ay) in seen:
            continue
        missing = []
        for dy in range(span):
            for dx in range(span):
                tx, ty = ax + dx, ay + dy
                if not (0 <= tx < m.cols and 0 <= ty < m.rows):
                    missing.append((dx, dy))
                    continue
                other = m.tiles[tx][ty]
                want = (dx, dy)
                got = (other.offset.x, other.offset.y) if other.offset else (0, 0)
                if other.type != t.type or got != want:
                    missing.append(want)
                else:
                    seen.add((tx, ty))
        if missing:
            r.add("structure.incomplete", ERROR,
                  "structure at (%d,%d) is missing tiles %s"
                  % (ax, ay, ", ".join("%d,%d" % o for o in missing)),
                  "cells[%d,%d]" % (ax, ay))
        seen.add((ax, ay))

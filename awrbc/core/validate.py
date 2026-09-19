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

from .model import CAPTURABLE, HQ, Map

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

MAX_REASONABLE_CELLS = 10_000


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

    # Advisory: design choices, not defects. The game accepts uneven maps.
    per = m.per_team()
    if per:
        counts = [c.properties for c in per.values()]
        if max(counts) - min(counts) > 2:
            r.add("balance.uneven", WARNING,
                  "property counts range from %d to %d across teams"
                  % (min(counts), max(counts)), "cells")
    if m.cols * m.rows > MAX_REASONABLE_CELLS:
        r.add("size.large", WARNING,
              "%dx%d is %d cells; untested at this size"
              % (m.cols, m.rows, m.cols * m.rows), "size")
    if len({t.type for _, _, t in m.iter_tiles()}) < 2:
        r.add("terrain.flat", WARNING, "the map is a single terrain type", "terrain")

    return r

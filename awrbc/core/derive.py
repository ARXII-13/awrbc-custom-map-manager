"""Derived data.

The game keeps a parallel ``CustomMapMetadata`` record holding counts that are
computable from the grid. It is regenerated here rather than carried through,
because stale counts make the in-game browser show wrong numbers.

The per-team breakdown is also stored in the map JSON. That is not redundancy:
``CustomMapMetadata`` provably cannot express playability - two maps with
identical metadata differ in validity by one unit - so the archive would have to
re-parse every map to answer "is this playable" without it.
"""
from .model import AIRPORT, BASE, CITY, COM_TOWER, HQ, SEAPORT, Map

#: The game folds Com Towers / Labs into its city count.
CITY_LIKE = (CITY, COM_TOWER)


def tile_counts(m: Map) -> dict:
    counts = {}
    for _, _, t in m.iter_tiles():
        counts[t.type] = counts.get(t.type, 0) + 1
    return counts


def metadata(m: Map) -> dict:
    """The values the game's UserMapMetadata record needs."""
    c = tile_counts(m)
    versus = sum(c.get(t, 0) for t in
                 (HQ, CITY, BASE, AIRPORT, SEAPORT, COM_TOWER))
    per = m.per_team()
    return {
        "NumCols": m.cols,
        "NumRows": m.rows,
        "NumHQs": c.get(HQ, 0),
        "NumCities": sum(c.get(t, 0) for t in CITY_LIKE),
        "NumBases": c.get(BASE, 0),
        "NumAirports": c.get(AIRPORT, 0),
        "NumSeaports": c.get(SEAPORT, 0),
        "NumSilos": c.get(33554432, 0),
        "NumPipeSeams": c.get(65536, 0),
        "NumVersusProperties": versus,
        "MaxInitiallyOwnedVersusProperties": max(
            (v.properties for v in per.values()), default=0),
        # Not decoded. It equals NumVersusProperties in every observed map, so
        # that is what gets written - which is a working guess, not knowledge
        # of what the field counts. tools/poc/bigmap.py computes it as
        # HQs + Bases instead; one of the two is wrong.
        "NumSurplusTiles": versus,
        "TeamsPlaying": sum(1 << t for t in m.teams),
    }


#: Water a ship can sit on, so a map can be filtered for naval play.
NAVIGABLE = frozenset([2, 8192])

#: The Black Hole hardware, which is what "special" usually means in practice.
BLACK_HOLE_STRUCTURES = frozenset([32768, 65536, 524288, 1048576, 2097152,
                                   8388608, 33554432])


def derived_block(m: Map) -> dict:
    """The ``derived`` section of the map JSON.

    Regenerated on every read and write; CI recomputes and rejects a mismatch, so
    it is never trusted - it exists so the catalog can filter without re-parsing
    the whole archive.
    """
    per = m.per_team()
    terrain = {t.type for _, _, t in m.iter_tiles()}
    return {
        "valid": m.is_playable,
        "teams": m.teams,
        # The categories a browser wants to filter on, worked out from the map
        # rather than declared beside it. A stored player count can disagree
        # with the terrain; a derived one cannot.
        "players": len(m.teams),
        "predeployed": any(c.units for c in per.values()),
        "navy": bool(terrain & NAVIGABLE),
        "structures": bool(terrain & BLACK_HOLE_STRUCTURES),
        "fog": bool(m.fog),
        "perTeam": {str(t): {"hq": c.hq, "production": c.production,
                             "properties": c.properties, "units": c.units}
                    for t, c in per.items()},
    }

"""Find save data.

Pure path logic — no parsing, no I/O beyond existence checks. Returns candidates
with enough context for ``doctor`` to explain what it found and why.

Two shapes are supported:

* a Ryujinx data root, which contains ``bis/user/save/<id>/<profile>/SaveData/maps``
* a directory containing a ``maps`` file directly, which is what a JKSV dump from
  real hardware looks like
"""
import os
from dataclasses import dataclass
from typing import Optional

MAPS_FILE = "maps"
SAVE_SUBPATH = os.path.join("bis", "user", "save")


@dataclass
class SaveCandidate:
    """One maps file we could operate on."""

    path: str            #: the maps file itself
    profile: Optional[str] = None
    save_id: Optional[str] = None
    source: str = "unknown"   #: "ryujinx" | "directory" | "explicit"
    size: int = 0

    @property
    def label(self) -> str:
        if self.profile is not None:
            return "%s profile %s" % (self.source, self.profile)
        return self.source


def ryujinx_roots() -> list:
    """Platform locations Ryujinx keeps its data in, most likely first.

    Ryujinx also supports a portable mode that puts data beside the executable,
    which is why an explicit override always has to be available.
    """
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(os.path.join(appdata, "Ryujinx"))
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, ".config", "Ryujinx"))
    roots.append(os.path.join(home, "Library", "Application Support", "Ryujinx"))
    return roots


def scan_ryujinx_root(root: str) -> list:
    """Every maps file under one Ryujinx data root."""
    base = os.path.join(root, SAVE_SUBPATH)
    if not os.path.isdir(base):
        return []
    found = []
    for save_id in sorted(os.listdir(base)):
        save_dir = os.path.join(base, save_id)
        if not os.path.isdir(save_dir):
            continue
        for profile in sorted(os.listdir(save_dir)):
            maps = os.path.join(save_dir, profile, "SaveData", MAPS_FILE)
            if os.path.isfile(maps):
                found.append(SaveCandidate(
                    path=maps, profile=profile, save_id=save_id,
                    source="ryujinx", size=os.path.getsize(maps)))
    return found


def from_directory(path: str) -> list:
    """Accept a directory holding a maps file, or the maps file itself.

    Covers JKSV dumps from real hardware, which are just the SaveData contents.
    """
    if os.path.isfile(path):
        return [SaveCandidate(path=path, source="explicit",
                              size=os.path.getsize(path))]
    direct = os.path.join(path, MAPS_FILE)
    if os.path.isfile(direct):
        return [SaveCandidate(path=direct, source="directory",
                              size=os.path.getsize(direct))]
    nested = os.path.join(path, "SaveData", MAPS_FILE)
    if os.path.isfile(nested):
        return [SaveCandidate(path=nested, source="directory",
                              size=os.path.getsize(nested))]
    return scan_ryujinx_root(path)


def find_saves(save_dir: Optional[str] = None) -> list:
    """All candidates, best first.

    ``save_dir`` overrides discovery entirely — needed for portable Ryujinx
    installs and for hardware dumps in arbitrary locations.
    """
    if save_dir:
        return from_directory(save_dir)
    out = []
    for root in ryujinx_roots():
        out.extend(scan_ryujinx_root(root))
    return out


def select(candidates: list, profile: Optional[str] = None) -> Optional[SaveCandidate]:
    """Pick one candidate, optionally by profile. None if the choice is empty."""
    if not candidates:
        return None
    if profile is None:
        return candidates[0]
    for c in candidates:
        if c.profile == profile:
            return c
    return None

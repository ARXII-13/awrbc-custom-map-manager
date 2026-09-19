"""Save backups.

Every write is preceded by a snapshot. Not a flag — the failure mode this guards
against is destroying somebody's campaign.

Snapshots go to a user data directory, deliberately **not** next to the save (the
game rewrites that directory) and **not** in the repo. Nothing is ever pruned
automatically.
"""
import os
import shutil
import time
from dataclasses import dataclass

STAMP = "%Y%m%d-%H%M%S"


@dataclass
class Snapshot:
    path: str
    taken: str
    size: int
    source: str = ""

    @property
    def name(self):
        return os.path.basename(self.path)


def backup_root() -> str:
    base = os.environ.get("AWRBC_BACKUP_DIR")
    if base:
        return base
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "awrbc", "backups")
    return os.path.join(os.path.expanduser("~"), ".local", "share",
                        "awrbc", "backups")


def _key(save_path: str) -> str:
    """A stable folder name per save, so profiles do not collide."""
    full = os.path.abspath(save_path)
    parts = full.replace("\\", "/").split("/")
    tail = [p for p in parts[-4:] if p not in ("", "SaveData", "maps")]
    return "-".join(tail) or "save"


def snapshot(save_path: str) -> Snapshot:
    """Copy the save aside. Returns the snapshot taken."""
    folder = os.path.join(backup_root(), _key(save_path))
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime(STAMP)
    dest = os.path.join(folder, "maps-%s" % stamp)
    n = 1
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(folder, "maps-%s-%d" % (stamp, n))
    shutil.copy2(save_path, dest)
    return Snapshot(path=dest, taken=stamp, size=os.path.getsize(dest),
                    source=save_path)


def snapshots(save_path: str) -> list:
    """Every snapshot for this save, newest first."""
    folder = os.path.join(backup_root(), _key(save_path))
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder), reverse=True):
        full = os.path.join(folder, name)
        if os.path.isfile(full):
            out.append(Snapshot(path=full, taken=name.replace("maps-", ""),
                                size=os.path.getsize(full), source=save_path))
    return out


def restore(snapshot_path: str, save_path: str) -> int:
    """Put a snapshot back. Returns the number of bytes restored."""
    shutil.copy2(snapshot_path, save_path)
    return os.path.getsize(save_path)

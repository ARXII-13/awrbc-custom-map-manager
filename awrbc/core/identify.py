"""Confirm a save actually belongs to this game.

Without this, pointing the tool at another title's save produces a confusing
error — the stream parses as NRBF, the members we look for are simply absent,
and the failure surfaces as "save version None is not supported", which tells the
user nothing useful.

Two independent signals, with different availability:

1. **The root class inside the maps file** — ``AW.UserGeneratedContent``, from
   ``Assembly-CSharp``. Always present, because it is the file we operate on.
   This is the primary check.
2. **The title id in ``ExtraData0``** — ``0100300012F2A000``. Definitive, but it
   lives three levels up from the maps file and only exists when the full
   Ryujinx save directory is present. A JKSV dump of just ``SaveData`` will not
   have it, so its absence is not evidence of anything.

Matching (1) accepts. A mismatch on (2) rejects even if (1) matched, since a
wrong title id means the file was taken from somewhere unexpected.
"""
import os
import struct
from dataclasses import dataclass
from typing import Optional

#: Advance Wars 1+2: Re-Boot Camp.
TITLE_ID = 0x0100300012F2A000
TITLE_NAME = "Advance Wars 1+2: Re-Boot Camp"

ROOT_TYPE = "AW.UserGeneratedContent"
ASSEMBLY = "Assembly-CSharp"

#: Members the root must carry. Guards against a future title that happens to
#: reuse the type name.
ROOT_MEMBERS = frozenset({"CustomMaps", "CustomMapMetadata",
                          "CurrentSaveVersionNumber"})

EXTRA_DATA = ("ExtraData0", "ExtraData1")


@dataclass
class Identity:
    ok: bool
    root_type: Optional[str] = None
    title_id: Optional[int] = None
    reason: Optional[str] = None

    @property
    def title_hex(self):
        return None if self.title_id is None else "%016X" % self.title_id


def title_id_for(maps_path: str) -> Optional[int]:
    """Read the title id from the save's ExtraData, if it is reachable.

    Layout: ``<save-id>/<profile>/SaveData/maps``, with ExtraData beside the
    save id — three directories up.
    """
    try:
        save_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(maps_path))))
        for name in EXTRA_DATA:
            candidate = os.path.join(save_root, name)
            if os.path.isfile(candidate):
                with open(candidate, "rb") as fh:
                    head = fh.read(8)
                if len(head) == 8:
                    return struct.unpack("<Q", head)[0]
    except OSError:
        pass
    return None


def inspect(parser, path: str = None) -> Identity:
    """Decide whether this document is one of ours."""
    try:
        root = parser.objects[parser.header.d["root"]]
        root_type = root.d.get("name")
        members = set(root.d.get("mnames") or ())
    except Exception:                               # noqa: BLE001
        return Identity(ok=False, reason="the file has no readable root object")

    title = title_id_for(path) if path else None

    if root_type != ROOT_TYPE:
        return Identity(
            ok=False, root_type=root_type, title_id=title,
            reason="the root object is %r, not %r - this save belongs to a "
                   "different game" % (root_type, ROOT_TYPE))

    if not ROOT_MEMBERS.issubset(members):
        missing = ", ".join(sorted(ROOT_MEMBERS - members))
        return Identity(
            ok=False, root_type=root_type, title_id=title,
            reason="the root object is missing %s - the layout is not one this "
                   "build understands" % missing)

    if title is not None and title != TITLE_ID:
        return Identity(
            ok=False, root_type=root_type, title_id=title,
            reason="the save's title id is %016X, but %s is %016X"
                   % (title, TITLE_NAME, TITLE_ID))

    return Identity(ok=True, root_type=root_type, title_id=title)

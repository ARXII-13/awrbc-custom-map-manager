"""Stable map identity.

The id is a content hash. It is the filename in the archive and the join key the
future ratings database will use, so it has to stay the same for the same map
forever — including after the game has opened and re-saved it.

That is why the hashed subset is narrower than the file:

* **Volatile editor state** (``LastCursorPosition``, ``IsNew``, ...) changes just
  from opening a map in the Design Room. Never stored, never hashed.
* **name and author** are excluded so renaming a map does not create a new one.
* **flags** are excluded because they are suspected autotile/sprite variants the
  game may recompute. Structure membership lives in bits 29/30, but the same
  information is already carried by terrain type plus cell offsets, so dropping
  flags from the hash loses nothing and protects against churn.
"""
import hashlib
import json

#: Bump if the hashed subset ever changes - ids are not comparable across
#: versions.
HASH_VERSION = 1

HASHED_FIELDS = ("size", "fog", "waterColor", "terrain", "cells", "units")


def canonical(doc: dict) -> str:
    """Deterministic JSON over the content subset only."""
    subset = {k: doc[k] for k in HASHED_FIELDS if k in doc}
    for key in ("cells", "units"):
        if key in subset:
            subset[key] = sorted(subset[key], key=lambda c: (c["y"], c["x"]))
    return json.dumps(subset, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def content_hash(doc: dict, length: int = 16) -> str:
    return hashlib.sha256(canonical(doc).encode("utf-8")).hexdigest()[:length]

"""Creator scrubbing.

The save stores the console profile name in ``Creator``, which for many people is
their real name. Exports scrub it by default; opting in is a deliberate act.
"""
DEFAULT_AUTHOR = "anonymous"


def author_for(creator: str, *, keep: bool = False, override: str = None) -> str:
    """Decide what to publish as the author.

    ``override`` wins, then ``keep`` (the console name), then the placeholder.
    """
    if override:
        return override.strip()
    if keep and creator:
        return creator
    return DEFAULT_AUTHOR


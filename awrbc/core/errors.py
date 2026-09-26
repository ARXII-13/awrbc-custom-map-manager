"""Typed errors raised by core.

core never prints and never exits. It raises from here; the CLI maps these to
messages and exit codes, and the server (phase 2, connected mode) maps the same
errors to HTTP status codes.
"""


class AwrbcError(Exception):
    """Base for everything this package raises."""

    exit_code = 1


class SaveNotFound(AwrbcError):
    """No save directory could be located, or the given path has no maps file."""

    exit_code = 3


class SaveUnreadable(AwrbcError):
    """The maps file exists but could not be parsed."""

    exit_code = 3


class WrongGame(AwrbcError):
    """The file parses, but it is not this game's save.

    Separate from SaveUnreadable so the message can say what was actually
    found rather than blaming the file for being corrupt.
    """

    exit_code = 3

    def __init__(self, identity, path=None):
        self.identity = identity
        self.path = path
        detail = identity.reason or "unrecognised layout"
        where = " (%s)" % path if path else ""
        super().__init__("not an Advance Wars save%s: %s" % (where, detail))


class UnsupportedSaveVersion(AwrbcError):
    """CurrentSaveVersionNumber is not one this build understands.

    Refuse rather than guess: writing against an unknown layout risks destroying
    a save.
    """

    exit_code = 4

    def __init__(self, found, supported):
        self.found = found
        self.supported = supported
        super().__init__(
            "save version %r is not supported (this build understands %s)"
            % (found, ", ".join(repr(v) for v in supported))
        )


class SaveInUse(AwrbcError):
    """The game is running and holds the save; it would overwrite our write."""

    exit_code = 4


class MapNotFound(AwrbcError):
    """No map at the requested index or id."""

    exit_code = 1


class ValidationFailed(AwrbcError):
    """A map failed checks that block the requested operation."""

    exit_code = 2

    def __init__(self, report):
        self.report = report
        super().__init__("map failed validation")

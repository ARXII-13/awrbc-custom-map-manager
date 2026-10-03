"""Entry script for the packaged app.

PyInstaller runs its entry script as `__main__`, with no parent package - so
pointing it straight at `awrbc/desktop/__main__.py` makes that file's
`from .api import SaveApi` fail at the first line, before anything can report
why. The app built, zipped and died on launch with a bare ImportError.

So the packaged entry is this instead: import the package properly, then call
the same `main()` the console script does.
"""
import sys

from awrbc.desktop.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

"""Lets the package be run as ``python -m awrbc``.

The console script installed by ``pip install -e .`` is the normal way in. This
exists so the form the docs use - and the one anybody tries first - works from a
checkout without installing anything.
"""
import sys

from .cli.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

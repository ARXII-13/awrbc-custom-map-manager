"""The desktop app: the editor, hosted by a Python process that can reach your
save.

Separate from `awrbc.cli` because they are different front doors to the same
core, and from `awrbc.core` because neither of those should import a GUI.
"""

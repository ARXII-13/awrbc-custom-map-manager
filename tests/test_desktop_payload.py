"""What the save editor is allowed to contain.

The save editor is downloaded and writes to a file the game owns. The map
editor is hosted and talks to a public archive. They are shipped apart so they
stay separable, and this is the check that keeps them that way.

It is a test rather than a convention because the convention already failed
once: the first packaged build bundled the whole of `web/`, so the downloaded
save editor contained the editing engine, Export bundle, and the path that
submits a map to the archive - Submit button and CC BY licence dialog with it.
Nothing failed, nothing warned, and it shipped.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import desktop_payload as dp                              # noqa: E402

WEB = os.path.join(ROOT, "web")


class ThePayload(unittest.TestCase):
    def setUp(self):
        self.shipped = dp.payload(WEB)
        self.names = {os.path.basename(src) for src, _ in self.shipped}

    def test_the_map_editor_is_not_in_it(self):
        leaked = sorted(self.names & set(dp.FORBIDDEN))
        self.assertEqual(leaked, [], "the save editor would ship: %s"
                                     % ", ".join(leaked))

    def test_the_archive_submission_path_is_not_in_it(self):
        """Named separately from the rest because this is the part with a
        licence grant attached. A tool for managing your own save has no
        business carrying the thing that publishes maps to a public archive."""
        for name in ("intake.js", "submit-ui.js"):
            self.assertNotIn(name, self.names)

    def test_it_carries_what_it_needs_to_draw_a_map(self):
        for name in dp.ALLOWED:
            self.assertIn(name, self.names, "%s is required" % name)

    def test_it_carries_the_sprite_pack(self):
        """Deliberate, and weighed: the art is Advance Wars derived, and a
        preview that does not look like the game is harder to recognise."""
        self.assertIn("manifest.json", self.names)
        self.assertIn("terrain.png", self.names)

    def test_it_does_not_carry_personal_save_data(self):
        """web/samples is somebody's own maps - .gitignore says so. A build on
        a developer's machine was putting them in the zip."""
        for src, _ in self.shipped:
            rel = os.path.relpath(src, WEB).replace("\\", "/")
            self.assertNotIn("samples/", rel)
            self.assertNotIn("cache/", rel)

    def test_everything_it_names_actually_exists(self):
        for src, _ in self.shipped:
            self.assertTrue(os.path.exists(src), src)

    def test_a_missing_module_is_refused_rather_than_shipped(self):
        """A bundle quietly missing its renderer opens to a blank panel."""
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in dp.ALLOWED:
            if name == "render.js":
                continue
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as fh:
                fh.write("")
        with self.assertRaises(SystemExit) as caught:
            dp.payload(tmp)
        self.assertIn("render.js", str(caught.exception))


class WhatTheSavePageImports(unittest.TestCase):
    """The allow-list is only half of it: a page that imports edit.js would
    still be broken, it would just fail at runtime instead of shipping it."""

    def imports_of(self, path):
        import re
        with open(path, encoding="utf-8") as fh:
            return set(re.findall(r'from\s+"\./([^"]+)"', fh.read()) +
                       re.findall(r"from\s+'\./([^']+)'", fh.read()))

    def test_the_save_page_imports_nothing_forbidden(self):
        used = self.imports_of(os.path.join(WEB, "save.html"))
        self.assertEqual(sorted(used & set(dp.FORBIDDEN)), [])

    def test_everything_the_save_page_imports_is_shipped(self):
        shipped = {os.path.basename(s) for s, _ in dp.payload(WEB)}
        for name in self.imports_of(os.path.join(WEB, "save.html")):
            self.assertIn(name, shipped,
                          "save.html imports %s, which is not bundled" % name)

    def test_save_ui_does_not_reach_for_the_editor(self):
        used = self.imports_of(os.path.join(WEB, "save-ui.js"))
        self.assertEqual(sorted(used & set(dp.FORBIDDEN)), [])

    def test_the_map_editor_no_longer_carries_save_access(self):
        """The other direction. The hosted editor cannot reach a save, and
        now it does not contain the code that would try."""
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotIn("save-ui.js", page)
        self.assertNotIn("saves.js", page)


if __name__ == "__main__":
    unittest.main()

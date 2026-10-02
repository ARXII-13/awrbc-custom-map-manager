"""The editor's JavaScript at least parses.

Parsing is the half that behaviour tests cannot reach: `web/test/` covers the
editor's modules under node, but nothing there loads `index.html`. That gap has
cost real time - a string literal in it picked up a real newline where an escape
was meant, the whole inline module failed to parse, and the editor ran nothing
at all for five commits while checks that looked like verification passed
anyway.
The check that missed it asked whether a button *existed* - it did, because it
is in the HTML - rather than whether the code behind it had ever run.

These are not a substitute for testing the editor's behaviour. They catch the
one failure that keeps recurring, and they catch it in the suite rather than in
a browser nobody opened.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "web")
BACKSLASH = chr(92)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def module_sources():
    """Every piece of JavaScript the editor loads: each module, and the inline
    script inside the page."""
    out = {}
    for name in sorted(os.listdir(WEB)):
        if name.endswith(".js"):
            with open(os.path.join(WEB, name), encoding="utf-8") as fh:
                out[name] = fh.read()

    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    found = re.search(r'<script type="module">(.*?)</script>', page, re.S)
    if found:
        out["index.html"] = found.group(1)
    return out


def _without_block_comments(source):
    """Blank out /* ... */ but keep the line count, so numbers still line up.

    Every apostrophe in English prose lives in a comment, and this scanner would
    otherwise report every one of them.
    """
    return BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), source)


def unterminated(source):
    """Lines where a quoted literal opens and never closes.

    Deliberately small: it reads one line at a time, so a template literal
    spanning lines is not its business and neither is anything clever. What it
    knows is that a plain '...' or "..." has to finish on the line it started
    on - which is exactly the mistake that keeps being made here.
    """
    bad = []
    for number, line in enumerate(_without_block_comments(source).split("\n"), 1):
        i, quote = 0, None
        while i < len(line):
            c = line[i]
            if c == BACKSLASH:
                i += 2
                continue
            if quote:
                if c == quote:
                    quote = None
            elif c in ('"', "'"):
                quote = c
            elif line[i:i + 2] == "//":
                break
            i += 1
        if quote:
            bad.append((number, line.strip()[:70]))
    return bad


class EditorParses(unittest.TestCase):
    def test_no_string_literal_runs_off_its_line(self):
        """The recurring bug, in the form it keeps taking."""
        for name, source in module_sources().items():
            bad = unterminated(source)
            self.assertEqual(bad, [], "%s has an unterminated string literal "
                                      "at %s" % (name, bad))

    def test_the_page_has_an_inline_module_to_check(self):
        """Guards the test above: if that script tag is ever renamed or moved,
        these would otherwise pass by checking nothing."""
        self.assertIn("index.html", module_sources())

    def test_the_scanner_catches_the_bug_it_is_for(self):
        """The shape the real breakage took, so a scanner that stops working
        does not sit here quietly reporting success."""
        broken = 'alert("Applied:\n  " + done);'
        self.assertTrue(unterminated(broken))
        self.assertFalse(unterminated(r'alert("Applied:\n  " + done);'))
        self.assertFalse(unterminated("/* an editor's comment */"))
        self.assertFalse(unterminated("// an editor's comment"))


@unittest.skipIf(not shutil.which("node"), "node is not installed")
class NodeAgrees(unittest.TestCase):
    """The real check, when a JavaScript engine is around to do it."""

    def test_every_module_parses(self):
        for name, source in module_sources().items():
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "check.mjs")
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(source)
                done = subprocess.run(["node", "--check", path],
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0,
                                 "%s does not parse:\n%s" % (name, done.stderr))


if __name__ == "__main__":
    unittest.main()

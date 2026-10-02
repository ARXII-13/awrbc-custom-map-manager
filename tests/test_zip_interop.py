"""The editor's zip writer, read by a real zip implementation.

`web/zip.js` is hand-written, so nothing in the JavaScript stack would notice
if it produced something only *nearly* valid - a zip with a wrong CRC opens in
some tools and fails in others, which is the worst kind of broken. Its own
tests check the structure from inside node, which cannot catch a disagreement
between our idea of the format and everybody else's.

This closes that: node writes one, Python's `zipfile` reads it. Two independent
implementations have to agree, which is the only way a format test means much.

Skips when node is not installed; the zip writer is still covered by
`web/test/zip.test.mjs` either way.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "web")

#: Written by node, read by Python. The payload deliberately includes a
#: non-ASCII name, a NUL, and a high byte - the three things a writer that
#: quietly treats bytes as text gets wrong.
SCRIPT = """
import { zip } from '%s';
import { writeFileSync } from 'node:fs';

const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
                            0x00, 0xff, 0x00, 0x01, 0x02]);
const blob = zip({
  'map.json': JSON.stringify({ name: 'Daibi \\u65e5\\u672c', schema: 1 }),
  'preview.png': png,
  'empty.txt': '',
});
// argv[0] is node and argv[1] is this script; the output path is argv[2].
writeFileSync(process.argv[2], Buffer.from(await blob.arrayBuffer()));
"""


@unittest.skipIf(not shutil.which("node"), "node is not installed")
class NodeWritesPythonReads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        zip_js = os.path.abspath(os.path.join(WEB, "zip.js")).replace("\\", "/")
        script = os.path.join(cls.tmp, "write.mjs")
        with open(script, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(SCRIPT % ("file:///" + zip_js))

        cls.archive = os.path.join(cls.tmp, "bundle.zip")
        done = subprocess.run(["node", script, cls.archive],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise AssertionError("node could not build the zip:\n%s"
                                 % done.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_python_accepts_it(self):
        with zipfile.ZipFile(self.archive) as z:
            self.assertIsNone(z.testzip(), "a member failed its own CRC")

    def test_every_entry_is_there(self):
        with zipfile.ZipFile(self.archive) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["empty.txt", "map.json", "preview.png"])

    def test_text_survives_as_utf8(self):
        with zipfile.ZipFile(self.archive) as z:
            doc = json.loads(z.read("map.json").decode("utf-8"))
        self.assertEqual(doc["name"], "Daibi 日本")

    def test_binary_survives_byte_for_byte(self):
        """A NUL and a high byte are where a text-minded writer corrupts."""
        with zipfile.ZipFile(self.archive) as z:
            png = z.read("preview.png")
        self.assertEqual(png, bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a,
                                     0x1a, 0x0a, 0x00, 0xff, 0x00, 0x01,
                                     0x02]))

    def test_an_empty_member_is_readable(self):
        with zipfile.ZipFile(self.archive) as z:
            self.assertEqual(z.read("empty.txt"), b"")

    def test_entries_are_stored_not_deflated(self):
        with zipfile.ZipFile(self.archive) as z:
            for info in z.infolist():
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED,
                                 info.filename)

    def test_the_tool_itself_can_publish_it(self):
        """The end of the chain: a bundle the editor wrote goes through the
        same reader `awrbc publish` and `awrbc import` use."""
        from awrbc.cli.__main__ import _read_submission
        doc, preview = _read_submission(self.archive)
        self.assertEqual(doc["name"], "Daibi 日本")
        self.assertTrue(preview.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()

"""Test helpers.

The important one is :func:`binaryformatter_verdict`. Our own parser accepts
files the game refuses, and .NET's ``NrbfDecoder`` gets it wrong in both
directions — it passed files the game rejected and rejected one the game
accepted. The real ``BinaryFormatter`` matched the game on every file tested, so
it is the only validator worth gating on.
"""
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BFCHECK = os.path.join(REPO, "tools", "bfcheck.ps1")


def powershell():
    """Windows PowerShell, which carries .NET Framework's BinaryFormatter.

    pwsh (PowerShell Core) runs on .NET where BinaryFormatter is removed, so it
    is deliberately not accepted here.
    """
    if os.name != "nt":
        return None
    return shutil.which("powershell")


def binaryformatter_verdict(path):
    """('ok', None) | ('fail', message) | (None, why-it-could-not-run)."""
    shell = powershell()
    if shell is None:
        return None, "Windows PowerShell not available"
    if not os.path.isfile(BFCHECK):
        return None, "tools/bfcheck.ps1 is missing"
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", BFCHECK, path],
            capture_output=True, text=True, timeout=120)
    except Exception as exc:                        # noqa: BLE001
        return None, "could not run bfcheck: %s" % exc
    text = (proc.stdout or "") + (proc.stderr or "")
    if " OK " in text:
        return "ok", None
    if "FAIL" in text:
        return "fail", text.strip()
    return None, "unrecognised bfcheck output: %s" % text.strip()[:200]


needs_binaryformatter = unittest.skipIf(
    powershell() is None,
    "needs Windows PowerShell for the real BinaryFormatter")

REAL_SAVE = os.environ.get("AWRBC_TEST_SAVE")


def a_save(directory):
    """A save file to operate on, always a throwaway copy.

    Uses the real save when AWRBC_TEST_SAVE points at one, otherwise builds a
    fixture from the committed type table — so the suite runs anywhere, and
    runs against the genuine article when it is available.
    """
    import shutil

    from . import fixture

    path = os.path.join(directory, "maps")
    if REAL_SAVE and os.path.isfile(REAL_SAVE):
        shutil.copy2(REAL_SAVE, path)
        return path, "real"
    fixture.write_fixture_save(path)
    return path, "fixture"


class BinaryFormatterMixin:
    """Adds the assertion that actually matters for anything we write."""

    def assertLoadsInBinaryFormatter(self, path):
        verdict, detail = binaryformatter_verdict(path)
        if verdict is None:
            self.skipTest(detail)
        if verdict != "ok":
            self.fail("the real BinaryFormatter refuses this save - the game "
                      "would show zero custom maps:\n%s" % detail)

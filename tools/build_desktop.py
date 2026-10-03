"""Build the desktop app into a zip somebody can unzip and run.

    pip install -e ".[package]"
    python tools/build_desktop.py

Produces `dist/awrbc-<platform>.zip` holding one folder: the executable, its
runtime, and the editor with its sprite pack. No installer (decision #55) -
an installer is a thing to trust, and this writes to a save file people care
about; a folder they can look inside asks for less.

Not run by CI. It needs a machine of the target platform, and what it makes is
a release artifact rather than a check. The smoke test at the end is the part
worth keeping honest: a build that cannot find its own editor still produces a
zip, and nobody would know until they ran it.
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "tools", "awrbc.spec")
DIST = os.path.join(ROOT, "dist")
BUILT = os.path.join(DIST, "awrbc")

#: What the zip is called. The platform is in the name because the bundle is
#: a runtime for one, and a file called `awrbc.zip` that only runs on Windows
#: is a support question waiting to happen.
PLATFORM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def run(argv):
    print("$", " ".join(argv))
    result = subprocess.run(argv, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit("failed: %s" % " ".join(argv))


def smoke_test():
    """Does the built app find its own editor?

    The one failure this build can introduce on its own: data files that did
    not get bundled, or got bundled somewhere the frozen app does not look.
    It is invisible until launch, so it is checked here rather than reported
    by whoever downloads it.
    """
    index = os.path.join(BUILT, "_internal", "web", "index.html")
    if not os.path.exists(index):
        # PyInstaller < 6 put data beside the executable.
        index = os.path.join(BUILT, "web", "index.html")
    if not os.path.exists(index):
        raise SystemExit(
            "the build has no web/index.html in it - the editor was not "
            "bundled, and the app would open to nothing.")

    pack = os.path.join(os.path.dirname(index), "sprites", "manifest.json")
    if not os.path.exists(pack):
        raise SystemExit(
            "the build has no sprite pack (decision #54); terrain would "
            "render as letters on flat colour.")
    print("bundled editor:", index)

    # And then actually run it. Checking for files is not the same as the
    # thing starting: the first build of this passed every file check above,
    # zipped cleanly, and died on launch with an ImportError, because
    # PyInstaller runs its entry script with no parent package. `--check`
    # does everything a launch does except open the window.
    exe = os.path.join(BUILT, "awrbc.exe" if sys.platform == "win32"
                       else "awrbc")
    started = subprocess.run([exe, "--check"], capture_output=True, text=True,
                             timeout=120)
    if started.returncode != 0:
        raise SystemExit(
            "the built app does not start (exit %d).\n%s\n%s"
            % (started.returncode, started.stdout.strip(),
               started.stderr.strip()))
    print("starts cleanly:", started.stdout.strip() or "(no console output)")


def zip_up():
    name = "awrbc-%s.zip" % PLATFORM
    path = os.path.join(DIST, name)
    if os.path.exists(path):
        os.remove(path)
    total = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, _dirs, files in os.walk(BUILT):
            for f in files:
                full = os.path.join(folder, f)
                # Kept rooted at a folder name, so unzipping never sprays a
                # few hundred files into somebody's Downloads.
                z.write(full, os.path.join(
                    "awrbc", os.path.relpath(full, BUILT)))
                total += 1
    print("%s  (%d files, %.1f MB)"
          % (path, total, os.path.getsize(path) / 1e6))
    return path


def main():
    try:
        import PyInstaller                                 # noqa: F401
    except ImportError:
        raise SystemExit('this needs PyInstaller:\n'
                         '    pip install -e ".[package]"')

    shutil.rmtree(BUILT, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm",
         "--distpath", DIST,
         "--workpath", os.path.join(ROOT, "build"), SPEC])
    smoke_test()
    zip_up()
    return 0


if __name__ == "__main__":
    sys.exit(main())

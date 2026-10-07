# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Установка rhino3dm внутрь плагина: $H3DM/vendor/<py>-<os>-<arch>/.

rhino3dm — одно колесо без зависимостей (MIT), ставится встроенным pip Houdini.
"""
import glob
import os
import subprocess
import sys

from . import ensure_vendor_path, vendor_dir, has_rhino3dm


def houdini_python():
    """Путь к интерпретатору Python, встроенному в Houdini."""
    hfs = os.environ.get("HFS", "")
    ver = "%d.%d" % sys.version_info[:2]
    cands = [
        os.path.join(hfs, "Frameworks", "Python.framework", "Versions", ver, "bin", "python" + ver),   # macOS
        os.path.join(hfs, "Frameworks", "Python.framework", "Versions", "Current", "bin", "python3"),
        os.path.join(hfs, "python%s%s" % sys.version_info[:2], "python.exe"),                          # Windows
        os.path.join(hfs, "python", "bin", "python" + ver),                                              # Linux
        os.path.join(hfs, "python", "bin", "python3"),
    ]
    cands += glob.glob(os.path.join(hfs, "Frameworks", "Python.framework", "Versions", "*", "bin", "python3*"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def install(upgrade=False, log=print):
    target = vendor_dir()
    os.makedirs(target, exist_ok=True)
    py = houdini_python()
    if not py:
        raise RuntimeError("Houdini Python not found (HFS=%s)" % os.environ.get("HFS"))
    # pip может отсутствовать во встроенном Python
    subprocess.call([py, "-m", "ensurepip", "--user"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = [py, "-m", "pip", "install", "--target", target, "--no-warn-script-location", "--no-deps", "rhino3dm>=8,<9"]
    if upgrade:
        cmd.insert(4, "--upgrade")
    log("[H3DM] " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    log(r.stdout[-3000:])
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-3000:])
    ensure_vendor_path()
    return target


def status():
    ok = has_rhino3dm()
    ver = ""
    if ok:
        import rhino3dm
        ver = getattr(rhino3dm, "__version__", "")
    return {"rhino3dm": ok, "version": ver, "vendor": vendor_dir(), "python": sys.version.split()[0]}

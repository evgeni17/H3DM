# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Установка H3DM из папки разработки в рабочую папку.

    python deploy.py                         # -> ~/tools_houdini/H3DM
    python deploy.py /path/to/install        # другая папка
    python deploy.py --clean                 # удалить в установке файлы, которых нет в разработке

Копируются только изменённые файлы. Не копируются: .git, tests/private, tests/out, backup, __pycache__, .DS_Store.
После установки в Houdini: H3DM > Rebuild HDAs не нужен (HDA копируются готовыми), достаточно перезапуска
или hou.hda.reloadAllFiles().
"""
import filecmp
import os
import shutil
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
SKIP_DIRS = {".git", "__pycache__", "backup", os.path.join("tests", "private"), os.path.join("tests", "out")}
SKIP_FILES = {".DS_Store", ".gitignore", ".gitattributes", "deploy.py"}


def _skip_dir(rel):
    return rel in SKIP_DIRS or os.path.basename(rel) in {".git", "__pycache__", "backup"}


def deploy(dst, clean=False, log=print):
    dst = os.path.abspath(os.path.expanduser(dst))
    if os.path.normcase(dst) == os.path.normcase(SRC):
        raise SystemExit("Target is the development folder itself.")
    copied, same, wanted = 0, 0, set()
    for root, dirs, files in os.walk(SRC):
        rel_root = os.path.relpath(root, SRC)
        rel_root = "" if rel_root == "." else rel_root
        dirs[:] = [d for d in dirs if not _skip_dir(os.path.join(rel_root, d))]
        for fn in files:
            if fn in SKIP_FILES or fn.endswith((".pyc", ".rhl", ".3dmbak")):
                continue
            rel = os.path.join(rel_root, fn)
            wanted.add(rel)
            s, d = os.path.join(SRC, rel), os.path.join(dst, rel)
            if os.path.exists(d) and filecmp.cmp(s, d, shallow=False):
                same += 1
                continue
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            copied += 1
    stale = []
    for root, dirs, files in os.walk(dst):
        rel_root = os.path.relpath(root, dst)
        rel_root = "" if rel_root == "." else rel_root
        dirs[:] = [x for x in dirs if not _skip_dir(os.path.join(rel_root, x))]
        for fn in files:
            rel = os.path.join(rel_root, fn)
            if rel not in wanted and fn not in SKIP_FILES and not fn.endswith(".pyc"):
                stale.append(rel)
    if clean:
        for rel in stale:
            os.remove(os.path.join(dst, rel))
    log("H3DM deploy -> %s: copied %d, unchanged %d, %s %d" % (dst, copied, same, "removed" if clean else "stale", len(stale)))
    for rel in stale[:20]:
        log("  %s %s" % ("removed" if clean else "stale:", rel))
    return copied, stale


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    deploy(args[0] if args else "~/tools_houdini/H3DM", clean="--clean" in sys.argv)

# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Заморозка версии ассетов H3DM (выполняется при выпуске релиза).

    python freeze.py 4.0            # python3.13libs/h3dm -> python3.13libs/h3dm_4_0, ассеты ::4.0

Что делается:
  * копия пакета h3dm (все .py) в h3dm_<версия> с переписанными ссылками на модули (h3dm.sop_import ->
    h3dm_4_0.sop_import и т.п.; строки данных вида "h3dm.trims" не трогаются);
  * копия скриптов Rhino (rhino/*.py) внутрь пакета — у замороженной версии свои;
  * в __init__ копии: HDA_VERSION = <версия>, FROZEN = True.
После этого в Houdini (один раз):
    import h3dm_4_0.hda_build as b; b.build_all(force=True)
— получаются otls/h3dm_3dm_import_4.0.hda и h3dm_3dm_export_4.0.hda, которые ссылаются только на h3dm_4_0.
и печать (контрольные суммы пакета и файлов HDA в h3dm_4_0/FROZEN.sha256; tests/test_frozen.py их проверяет):
    python freeze.py --seal 4.0
Затем в h3dm/__init__.py поднимается HDA_VERSION разработки (5.0 или 4.1) и собираются её HDA.
Замороженные копии больше не меняются: ноды этой версии в рабочих сценах считаются тем же кодом всегда.
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LIBS = os.path.join(ROOT, "python3.13libs")


def freeze(version, src_pkg="h3dm"):
    if not re.fullmatch(r"\d+(\.\d+)+", version):
        raise SystemExit("Version must be digits and dots, e.g. 4.0")
    pkg = "h3dm_" + version.replace(".", "_")
    src = os.path.join(LIBS, src_pkg)
    dst = os.path.join(LIBS, pkg)
    if os.path.exists(dst):
        raise SystemExit("%s already exists — frozen versions are never overwritten." % dst)
    mods = sorted(f[:-3] for f in os.listdir(src) if f.endswith(".py") and f != "__init__.py")
    os.makedirs(dst)

    def rewrite(text):
        for m in mods:
            text = re.sub(r"\b%s\.%s\b" % (src_pkg, m), "%s.%s" % (pkg, m), text)
        text = re.sub(r"\bimport %s\b(?![.\w])" % src_pkg, "import " + pkg, text)
        text = re.sub(r"\bfrom %s import\b" % src_pkg, "from %s import" % pkg, text)
        return text

    for f in sorted(os.listdir(src)):
        if not f.endswith(".py"):
            continue
        with open(os.path.join(src, f), encoding="utf-8") as fh:
            text = rewrite(fh.read())
        if f == "__init__.py":
            text, n1 = re.subn(r'^HDA_VERSION = "[^"]*"', 'HDA_VERSION = "%s"' % version, text, flags=re.M)
            text, n2 = re.subn(r"^FROZEN = False", "FROZEN = True", text, flags=re.M)
            if not (n1 and n2):
                raise SystemExit("HDA_VERSION / FROZEN not found in %s/__init__.py" % src_pkg)
            text = text.replace('"""H3DM', '"""H3DM (ЗАМОРОЖЕННАЯ версия ассетов %s — не изменять)' % version, 1)
        with open(os.path.join(dst, f), "w", encoding="utf-8") as fh:
            fh.write(text)
    rh = os.path.join(dst, "rhino")
    os.makedirs(rh)
    for f in sorted(os.listdir(os.path.join(ROOT, "rhino"))):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(ROOT, "rhino", f), os.path.join(rh, f))
    # проверка: в копии не осталось ссылок на разрабатываемый пакет
    left = []
    for f in os.listdir(dst):
        if f.endswith(".py"):
            t = open(os.path.join(dst, f), encoding="utf-8").read()
            for m in mods:
                if re.search(r"\b%s\.%s\b" % (src_pkg, m), t):
                    left.append("%s: %s.%s" % (f, src_pkg, m))
    if left:
        raise SystemExit("References left: %s" % left)
    print("Frozen %s -> %s (%d modules). Now in Houdini: import %s.hda_build as b; b.build_all(force=True)"
          % (src_pkg, pkg, len(mods) + 1, pkg))
    return dst


def frozen_files(version):
    """Файлы замороженной версии (относительно корня): пакет, его скрипты Rhino и два HDA."""
    pkg = "h3dm_" + version.replace(".", "_")
    base = os.path.join(LIBS, pkg)
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(root, f), ROOT))
    out += [os.path.join("otls", "h3dm_3dm_%s_%s.hda" % (k, version)) for k in ("import", "export")]
    return pkg, sorted(out)


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seal(version):
    """Записать контрольные суммы замороженной версии (после сборки её HDA)."""
    pkg, files = frozen_files(version)
    missing = [f for f in files if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        raise SystemExit("Missing (build the HDAs first): %s" % missing)
    man = os.path.join(LIBS, pkg, "FROZEN.sha256")
    if os.path.exists(man):
        raise SystemExit("%s already sealed." % pkg)
    with open(man, "w", encoding="utf-8") as fh:
        for f in files:
            fh.write("%s  %s\n" % (_sha(os.path.join(ROOT, f)), f.replace(os.sep, "/")))
    print("Sealed %s: %d files" % (pkg, len(files)))


def verify(version):
    """-> список расхождений с FROZEN.sha256 (пусто — версия не менялась)."""
    pkg, files = frozen_files(version)
    man = os.path.join(LIBS, pkg, "FROZEN.sha256")
    if not os.path.isfile(man):
        return ["%s is not sealed" % pkg]
    want = {}
    for line in open(man, encoding="utf-8"):
        if line.strip():
            h, f = line.strip().split("  ", 1)
            want[f] = h
    bad = []
    for f in sorted(set(want) | {x.replace(os.sep, "/") for x in files}):
        p = os.path.join(ROOT, f)
        if f not in want:
            bad.append("new file: " + f)
        elif not os.path.isfile(p):
            bad.append("missing: " + f)
        elif _sha(p) != want[f]:
            bad.append("changed: " + f)
    return bad


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    if "--seal" in sys.argv:
        seal(args[0])
    elif "--verify" in sys.argv:
        bad = verify(args[0])
        print("\n".join(bad) if bad else "OK")
        raise SystemExit(1 if bad else 0)
    else:
        freeze(args[0])

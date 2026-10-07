# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Замороженные версии ассетов не изменились (контрольные суммы FROZEN.sha256): python tests/test_frozen.py"""
import importlib.util
import os
import re

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
spec = importlib.util.spec_from_file_location("freeze", os.path.join(root, "freeze.py"))
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

FAIL = []
versions = sorted(d[5:].replace("_", ".") for d in os.listdir(os.path.join(root, "python3.13libs"))
                  if re.fullmatch(r"h3dm_\d+(_\d+)+", d))
for v in versions:
    FAIL += ["%s: %s" % (v, x) for x in F.verify(v)]
# текущая версия ассетов выше всех замороженных (Houdini создаёт старшую)
init = open(os.path.join(root, "python3.13libs", "h3dm", "__init__.py"), encoding="utf-8").read()
cur = re.search(r'^HDA_VERSION = "([^"]+)"', init, re.M).group(1)
key = lambda s: tuple(int(x) for x in s.split("."))
if versions and key(cur) <= max(key(v) for v in versions):
    FAIL.append("current HDA_VERSION %s is not above frozen %s" % (cur, versions))
print("test_frozen: %s (frozen: %s, current: %s)" % ("OK" if not FAIL else "FAILED\n  " + "\n  ".join(FAIL),
                                                    ", ".join(versions) or "-", cur))
raise SystemExit(1 if FAIL else 0)

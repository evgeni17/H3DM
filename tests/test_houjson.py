# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тесты двоичного JSON Houdini (обычный Python + numpy): python tests/test_houjson.py

Байты сверены с файлами, которые пишет сам Houdini 22 (hou.Geometry.saveToFile(".bgeo")).
Загрузка в Houdini и совпадение с текстовым .geo проверяются в houdini_regression.py (точные площади обрезки).
"""
import importlib.util
import os
import struct

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("houjson", os.path.join(here, "..", "python3.13libs", "h3dm", "houjson.py"))
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def decode(b):
    """Минимальный разбор двоичного JSON Houdini (без токенов-ссылок — H3DM их не пишет)."""
    assert b[:5] == b"\x7fNSJb"
    pos = [5]

    def ln():
        c = b[pos[0]]
        pos[0] += 1
        if c < 0xF0:
            return c
        fmt = {0xF2: "<H", 0xF4: "<I", 0xF8: "<Q"}[c]
        v = struct.unpack_from(fmt, b, pos[0])[0]
        pos[0] += struct.calcsize(fmt)
        return v

    def val():
        c = b[pos[0]]
        pos[0] += 1
        if c == 0x5B:
            out = []
            while b[pos[0]] != 0x5D:
                out.append(val())
            pos[0] += 1
            return out
        if c == 0x7B:
            out = {}
            while b[pos[0]] != 0x7D:
                k = val()
                out[k] = val()
            pos[0] += 1
            return out
        if c == 0x27:
            n = ln()
            s = b[pos[0]:pos[0] + n].decode("utf-8")
            pos[0] += n
            return s
        if c in (0x30, 0x31):
            return c == 0x31
        ints = {0x11: "<b", 0x12: "<h", 0x13: "<i", 0x14: "<q", 0x1A: "<d"}
        if c in ints:
            v = struct.unpack_from(ints[c], b, pos[0])[0]
            pos[0] += struct.calcsize(ints[c])
            return v
        if c == 0x40:
            t = b[pos[0]]
            pos[0] += 1
            n = ln()
            dt = {0x1A: "<f8", 0x13: "<i4"}[t]
            a = np.frombuffer(b, dtype=dt, count=n, offset=pos[0])
            pos[0] += a.nbytes
            return ("uniform", a.tolist())
        raise ValueError("token %x" % c)
    v = val()
    assert pos[0] == len(b), "trailing bytes"
    return v


# 1) отдельные значения — как у Houdini: "pointcount",9 -> 0x27 'pointcount' 0x11 09; true 0x31
b = H.binary(["pointcount", 9, "hasindex", True, "x", 300, "y", -70000, "z", 2.5, "Тест", {"k": False}])
check(b[:5] == b"\x7fNSJb", "magic")
check(b"\x27\x0apointcount\x11\x09" in b, "string + int8")
check(b"\x12" + struct.pack("<h", 300) in b, "int16")
check(b"\x13" + struct.pack("<i", -70000) in b, "int32")
check(decode(b) == ["pointcount", 9, "hasindex", True, "x", 300, "y", -70000, "z", 2.5, "Тест", {"k": False}],
      "round trip scalars")

# 2) однородные массивы и длины: 1 байт, 0xf2 + uint16, 0xf4 + uint32 (у Houdini: @ 13 f4 <uint32>)
for n, prefix in ((5, b"\x05"), (300, b"\xf2" + struct.pack("<H", 300)), (70000, b"\xf4" + struct.pack("<I", 70000))):
    a = np.arange(n, dtype=np.int32)
    bb = H.binary(a)
    check(bb[5:7] == b"\x40\x13" and bb[7:7 + len(prefix)] == prefix, "uniform int32 length %d" % n)
    check(decode(bb) == ("uniform", list(range(n))), "uniform round trip %d" % n)
f = H.binary(np.array([0.5, -1.25]))
check(f[5:8] == b"\x40\x1a\x02", "uniform real64")

# 3) документ NURBS: поверхность с обрезкой и кривая; узлы сдвинуты к 0, P плоско (rawpagedata)
items = [{"kind": "surface", "cv": np.arange(18, dtype=float).reshape(2, 3, 3), "w": np.ones((2, 3)),
          "order_u": 2, "order_v": 2, "knots_u": [-1, -1, 0, 1, 1], "knots_v": [2, 2, 3, 3],
          "trims": [[{"order": 2, "knots": [-1, -1, 0, 1, 1], "cv": [(-1, 2), (1, 2), (-1, 2)]}]]},
         {"kind": "curve", "cv": np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0.5]]), "w": np.array([1, 0.7, 1]),
          "order": 3, "knots": [5, 5, 5, 6, 6, 6]}]
doc = decode(H.binary(H.nurbs_geo(items)))
d = dict(zip(doc[0::2], doc[1::2]))
check(d["pointcount"] == 9 and d["primitivecount"] == 2, "counts")
pattr = d["attributes"][1][0]
vals = pattr[1][pattr[1].index("values") + 1]
raw = vals[vals.index("rawpagedata") + 1]
check(raw[0] == "uniform" and raw[1][:3] == [0.0, 1.0, 2.0] and len(raw[1]) == 27, "P rawpagedata")
surf = d["primitives"][0][1]
ub = surf[surf.index("ubasis") + 1]
check(ub[ub.index("knots") + 1][1] == [0.0, 0.0, 1.0, 2.0, 2.0], "surface knots start at 0")
prof = surf[surf.index("profiles") + 1]
pd = dict(zip(prof[0::2], prof[1::2]))
praw = pd["attributes"][1][0][1]
praw = praw[praw.index("values") + 1]
praw = praw[praw.index("rawpagedata") + 1][1]
check(praw[:3] == [0.0, 0.0, 1.0], "trim UV shifted with the knots (u-su, v-sv, 1)")
crv = d["primitives"][1][1]
cb = crv[crv.index("basis") + 1]
check(cb[cb.index("knots") + 1][1] == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0], "curve knots start at 0")

# 4) подпись обрезки (экспорт: менялась ли обрезка): из петель импорта и из .geo — одинаковая
import json as _json
loops = [[{"order": 2, "knots": [-1, -1, 0, 1, 1], "cv": [(-1, 2), (1, 2), (1, 3), (-1, 2)]}],
         [{"order": 2, "knots": [0, 0, 1, 2, 2], "cv": [(0, 2.2), (0.5, 2.5), (0, 2.8), (0, 2.2)]}]]
sig = H.profiles_signature(loops, -1.0, 2.0)
geo = _json.loads(_json.dumps(H._profiles(loops, -1.0, 2.0), default=lambda o: o.tolist()))
check(H.profiles_signature_doc(geo) == sig, "trim signature: import == .geo (rawpagedata)")
gd = dict(zip(geo[0::2], geo[1::2]))
P = np.array(gd["attributes"][1][0][1][gd["attributes"][1][0][1].index("values") + 1][7]).reshape(-1, 3)
v = gd["attributes"][1][0][1][gd["attributes"][1][0][1].index("values") + 1]
v[v.index("rawpagedata")] = "tuples"
v[v.index("tuples") + 1] = P.tolist()
check(H.profiles_signature_doc(geo) == sig, "trim signature: tuples form")
check(H.profiles_signature(loops[:1], -1.0, 2.0) != sig, "trim signature: removed hole differs")
moved = [loops[0], [dict(loops[1][0], cv=[(0, 2.3), (0.5, 2.5), (0, 2.8), (0, 2.3)])]]
check(H.profiles_signature(moved, -1.0, 2.0) != sig, "trim signature: moved hole differs")
check(H.profiles_signature(None, 0, 0) == H.profiles_signature_doc(None), "trim signature: no trims")
run = [["type", "run", "runtype", "NURBMesh", "varyingfields", ["vertex", "profiles"], "uniformfields", {"surface": "quads"}],
       [[[[0, 1]], None], [[[2, 3]], geo]]]
pr = H.surface_profiles(["primitives", [run]])
check(len(pr) == 2 and pr[0] is None and H.profiles_signature_doc(pr[1]) == sig, "run-encoded NURBMesh profiles")

print("test_houjson: %s" % ("OK" if not FAIL else "FAILED\n  " + "\n  ".join(FAIL)))
raise SystemExit(1 if FAIL else 0)

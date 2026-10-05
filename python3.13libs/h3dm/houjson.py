# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Геометрия Houdini в формате JSON (.geo) для NURBS-кривых и поверхностей (в том числе обрезанных). Без hou.

HOM не позволяет задать узлы (knots) NURBS и кривые обрезки, а формат .geo — позволяет: строим JSON и
загружаем его через hou.Geometry.loadFromFile. Позиции — уже в осях/единицах сцены, веса — атрибут Pw.

Особенности Houdini, учтённые здесь (проверено на Houdini 22.0.429):
  * узловой вектор, начинающийся с отрицательного числа, ломает вычисление на краю (бесконечность,
    Convert не работает) — все узлы сдвигаются так, чтобы начинались с 0; кривые обрезки — на тот же сдвиг;
  * обрезка: у NURBMesh вложенная геометрия "profiles" — кривые в координатах узлового домена поверхности
    (точки (u, v, 1), тип hpoint) и "trimregions" — замкнутые области из нескольких кривых;
    внешняя петля против часовой стрелки, отверстия по часовой (как в Rhino); altitude 0;
  * веса кривых обрезки Houdini не учитывает — рациональные кривые обрезки приходят сюда уже ломаными.

Запись — двоичный JSON Houdini (.bgeo): числа массивами (uniform array) без текстового преобразования.
На 5 млн управляющих точек: ~1 с вместо ~60 с у текстового .geo (json + разбор в Houdini).
Формат (как пишет сам Houdini 22): магия 0x7f "NSJb"; [ ] { } — 0x5b 0x5d 0x7b 0x7d; строка 0x27+длина+UTF-8;
целые 0x11/0x12/0x13/0x14 (8/16/32/64 бит), вещественное 0x1a (64 бит), true/false 0x31/0x30;
однородный массив 0x40 + тип + длина + данные; длина: 1 байт (< 0xf0), 0xf2+uint16, 0xf4+uint32, 0xf8+uint64.
"""
import json
import struct

import numpy as np

# ---------------------------------------------------------------- двоичный JSON Houdini

_MAGIC = b"\x7fNSJb"


def _len(n):
    if n < 0xF0:
        return bytes((n,))
    if n < 0x10000:
        return b"\xf2" + struct.pack("<H", n)
    if n < 0x100000000:
        return b"\xf4" + struct.pack("<I", n)
    return b"\xf8" + struct.pack("<Q", n)


def _enc(o, out):
    if isinstance(o, np.ndarray):
        a = o.reshape(-1)
        if a.dtype.kind == "f":
            a = np.ascontiguousarray(a, dtype="<f8")
            out.append(b"\x40\x1a" + _len(len(a)))
        else:
            a = np.ascontiguousarray(a, dtype="<i4")
            out.append(b"\x40\x13" + _len(len(a)))
        out.append(a.tobytes())
    elif isinstance(o, bool) or isinstance(o, np.bool_):
        out.append(b"\x31" if o else b"\x30")
    elif isinstance(o, (int, np.integer)):
        o = int(o)
        if -128 <= o < 128:
            out.append(b"\x11" + struct.pack("<b", o))
        elif -32768 <= o < 32768:
            out.append(b"\x12" + struct.pack("<h", o))
        elif -2147483648 <= o < 2147483648:
            out.append(b"\x13" + struct.pack("<i", o))
        else:
            out.append(b"\x14" + struct.pack("<q", o))
    elif isinstance(o, (float, np.floating)):
        out.append(b"\x1a" + struct.pack("<d", float(o)))
    elif isinstance(o, str):
        b = o.encode("utf-8")
        out.append(b"\x27" + _len(len(b)) + b)
    elif isinstance(o, dict):
        out.append(b"\x7b")
        for k, v in o.items():
            _enc(str(k), out)
            _enc(v, out)
        out.append(b"\x7d")
    elif isinstance(o, (list, tuple)):
        out.append(b"\x5b")
        for v in o:
            _enc(v, out)
        out.append(b"\x5d")
    elif o is None:
        out.append(b"\x00")
    else:
        raise TypeError("houjson: cannot encode %r" % type(o))


def binary(doc):
    out = [_MAGIC]
    _enc(doc, out)
    return b"".join(out)


def _ascii_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o))


# ---------------------------------------------------------------- документ геометрии

def _values(arr, size):
    """Значения атрибута точек: плоский массив float64 (страницы по 1024 точки, компоненты подряд)."""
    return ["size", size, "storage", "fpreal64", "pagesize", 1024, "rawpagedata",
            np.ascontiguousarray(arr, dtype=np.float64).reshape(-1)]


def _points_doc(P, prims, W=None, ptype=None, extra=None):
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    n = len(P)
    popt = {"type": {"type": "string", "value": ptype}} if ptype else {}
    attrs = [[["scope", "public", "type", "numeric", "name", "P", "options", popt],
              ["size", 3, "storage", "fpreal64", "values", _values(P, 3)]]]
    if W is not None:
        attrs.append([["scope", "public", "type", "numeric", "name", "Pw", "options", {}],
                      ["size", 1, "storage", "fpreal64", "values", _values(W, 1)]])
    doc = ["fileversion", "22.0", "hasindex", False,
           "pointcount", n, "vertexcount", n, "primitivecount", len(prims),
           "topology", ["pointref", ["indices", np.arange(n, dtype=np.int32)]],
           "attributes", ["pointattributes", attrs],
           "primitives", prims]
    return doc + (extra or [])


def _curve_prim(start, n, order, knots):
    knots = np.asarray(knots, dtype=np.float64)
    clamped = len(knots) >= 2 and knots[0] == knots[1]
    return [["type", "NURBCurve"], [
        "vertex", np.arange(start, start + n, dtype=np.int32), "closed", False,
        "basis", ["type", "NURBS", "order", int(order), "endinterpolation", bool(clamped), "knots", knots]]]


def _profiles(loops, su, sv):
    """Петли кривых обрезки (UV в домене поверхности) -> вложенная геометрия profiles."""
    P, prims, regions, n = [], [], [], 0
    for loop in loops:
        faces = []
        for c in loop:
            uv = np.asarray(c["cv"], dtype=np.float64).reshape(-1, 2)
            P.append(np.column_stack([uv[:, 0] - su, uv[:, 1] - sv, np.ones(len(uv))]))
            kn = np.asarray(c["knots"], dtype=np.float64)
            kn = kn - kn[0]
            prims.append(_curve_prim(n, len(uv), c["order"], kn))
            n += len(uv)
            faces.append(["face", len(prims) - 1, "u0", float(kn[0]), "u1", float(kn[-1])])
        if faces:
            regions.append(["opencasual", False, "faces", faces])
    P = np.concatenate(P) if P else np.zeros((0, 3))
    return _points_doc(P, prims, ptype="hpoint", extra=["altitude", 0, "trimregions", regions])


def nurbs_geo(items):
    """items: [{'kind': 'curve'|'surface', 'cv': (n,3) или (nv,nu,3), 'w': ..., 'order'/'order_u','order_v',
    'knots'/'knots_u','knots_v', 'trims' (необязательно, для поверхностей)}] -> JSON-объект геометрии Houdini
    (числовые массивы — numpy).

    Порядок примитивов = порядок items.
    """
    P, W, prims = [], [], []
    base = 0
    for it in items:
        cv = np.asarray(it["cv"], dtype=np.float64)
        w = np.asarray(it["w"], dtype=np.float64)
        if it["kind"] == "surface":
            nv, nu = cv.shape[:2]
            P.append(cv.reshape(-1, 3))
            W.append(w.reshape(-1))
            rows = list(np.arange(base, base + nv * nu, dtype=np.int32).reshape(nv, nu))
            ku = np.asarray(it["knots_u"], dtype=np.float64)
            kv = np.asarray(it["knots_v"], dtype=np.float64)
            su, sv = float(ku[0]), float(kv[0])
            body = ["vertex", rows, "surface", "quads", "uwrap", False, "vwrap", False,
                    "ubasis", ["type", "NURBS", "order", int(it["order_u"]), "endinterpolation", True, "knots", ku - su],
                    "vbasis", ["type", "NURBS", "order", int(it["order_v"]), "endinterpolation", True, "knots", kv - sv]]
            if it.get("trims"):
                body += ["profiles", _profiles(it["trims"], su, sv)]
            prims.append([["type", "NURBMesh"], body])
            base += nv * nu
        else:
            cv = cv.reshape(-1, 3)
            P.append(cv)
            W.append(w.reshape(-1))
            kn = np.asarray(it["knots"], dtype=np.float64)
            prims.append(_curve_prim(base, len(cv), it["order"], kn - kn[0]))
            base += len(cv)
    P = np.concatenate(P) if P else np.zeros((0, 3))
    W = np.concatenate(W) if W else np.zeros(0)
    return _points_doc(P, prims, W=W)


def dump(items, path):
    """Записать NURBS в файл: .bgeo — двоичный JSON (быстро), иначе текстовый .geo (для отладки)."""
    doc = nurbs_geo(items)
    if path.endswith(".bgeo"):
        with open(path, "wb") as fh:
            fh.write(binary(doc))
    else:
        with open(path, "w") as fh:
            fh.write(json.dumps(doc, separators=(",", ":"), default=_ascii_default))
    return path

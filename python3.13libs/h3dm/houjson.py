# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Геометрия Houdini в формате JSON (.geo) для NURBS-кривых и поверхностей. Без hou.

HOM не позволяет задать узлы (knots) NURBS, а формат .geo — позволяет: строим JSON и загружаем
его через hou.Geometry.loadFromFile. Позиции — уже в осях/единицах сцены (после глобального трансформа),
веса рациональных NURBS — точечный атрибут Pw (P — евклидовы координаты).
"""
import json

import numpy as np


def nurbs_geo(items):
    """items: [{'kind': 'curve'|'surface', 'cv': (n,3) или (nv,nu,3), 'w': ..., 'order'/'order_u','order_v',
    'knots'/'knots_u','knots_v', 'closed'}] -> JSON-объект (list) геометрии Houdini.

    Порядок примитивов = порядок items.
    """
    P, W, prims = [], [], []
    for it in items:
        base = len(P)
        if it["kind"] == "surface":
            cv = np.asarray(it["cv"], dtype=np.float64)
            w = np.asarray(it["w"], dtype=np.float64)
            nv, nu = cv.shape[:2]
            P.extend(cv.reshape(-1, 3).tolist())
            W.extend(w.reshape(-1).tolist())
            rows = [[base + j * nu + i for i in range(nu)] for j in range(nv)]
            prims.append([["type", "NURBMesh"], [
                "vertex", rows, "surface", "quads", "uwrap", False, "vwrap", False,
                "ubasis", ["type", "NURBS", "order", int(it["order_u"]), "endinterpolation", True,
                           "knots", [float(x) for x in it["knots_u"]]],
                "vbasis", ["type", "NURBS", "order", int(it["order_v"]), "endinterpolation", True,
                           "knots", [float(x) for x in it["knots_v"]]]]])
        else:
            cv = np.asarray(it["cv"], dtype=np.float64)
            w = np.asarray(it["w"], dtype=np.float64)
            n = len(cv)
            P.extend(cv.tolist())
            W.extend(w.tolist())
            knots = [float(x) for x in it["knots"]]
            clamped = len(knots) >= 2 and knots[0] == knots[1]
            prims.append([["type", "NURBCurve"], [
                "vertex", list(range(base, base + n)), "closed", False,
                "basis", ["type", "NURBS", "order", int(it["order"]), "endinterpolation", bool(clamped),
                          "knots", knots]]])
    n = len(P)
    return [
        "fileversion", "22.0", "hasindex", False,
        "pointcount", n, "vertexcount", n, "primitivecount", len(prims),
        "topology", ["pointref", ["indices", list(range(n))]],
        "attributes", ["pointattributes", [
            [["scope", "public", "type", "numeric", "name", "P", "options", {}],
             ["size", 3, "storage", "fpreal32", "values", ["size", 3, "storage", "fpreal32", "tuples", P]]],
            [["scope", "public", "type", "numeric", "name", "Pw", "options", {}],
             ["size", 1, "storage", "fpreal32", "values", ["size", 1, "storage", "fpreal32", "arrays", [W]]]],
        ]],
        "primitives", prims,
    ]


def dump(items, path):
    with open(path, "w") as fh:
        json.dump(nurbs_geo(items), fh)
    return path

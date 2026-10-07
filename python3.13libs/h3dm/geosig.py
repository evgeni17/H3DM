# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Отпечатки геометрии объектов Rhino в Houdini: быстрый ответ «объект не менялся с импорта».

Импорт записывает в каждый примитив объекта rhino_geo_sig — отпечаток всех его примитивов (число вершин,
номер грани, позиции и веса в float32, у NURBS — порядки и узлы), а в detail rhino_file_sig — отпечаток
содержимого исходного .3dm. Экспорт считает тот же отпечаток по текущей геометрии массивами (без обхода
вершин через HOM): если он совпал и исходный файл тот же, объект берётся из исходника без сравнения точек
с исходными (это секунды на больших моделях). Иначе — полное сравнение (passthrough.object_match).
"""
import hashlib
import os

import numpy as np

import hou

SIG_ATTR = "rhino_geo_sig"
FILE_SIG_ATTR = "rhino_file_sig"
_FILE_SIGS = {}


def _verb(name, parms):
    v = hou.sopNodeTypeCategory().nodeVerb(name)
    v.setParms(parms)
    return v


def topology(geo):
    """Точки вершин всех примитивов разом (HOM по одной вершине — секунды на больших моделях):
    -> (начало вершин примитива (n+1), номера точек вершин). Вершины примитива — в порядке prim.vertices()
    (у NURBS-поверхности строками по V: индекс v * nu + u, как prim.vertex(u, v))."""
    n = geo.intrinsicValue("primitivecount")
    if not n:
        return np.zeros(1, dtype=np.int64), np.zeros(0, dtype=np.int64)
    # номер точки -> атрибут точки -> перенос на вершины; число вершин примитива — сумма единиц по вершинам
    tmp = hou.Geometry()
    tmp.merge(geo)
    npt, nvx = tmp.intrinsicValue("pointcount"), tmp.intrinsicValue("vertexcount")
    tmp.addAttrib(hou.attribType.Point, "__h3dm_pt", 0)
    tmp.setPointIntAttribValuesFromString("__h3dm_pt", np.arange(npt, dtype=np.int32).tobytes())
    tmp.addAttrib(hou.attribType.Vertex, "__h3dm_one", 0)
    tmp.setVertexIntAttribValuesFromString("__h3dm_one", np.ones(nvx, dtype=np.int32).tobytes())
    t1 = hou.Geometry()
    _verb("attribpromote", {"inname": "__h3dm_pt", "inclass": 2, "outclass": 3, "method": 8}).execute(t1, [tmp])
    t2 = hou.Geometry()
    _verb("attribpromote", {"inname": "__h3dm_one", "inclass": 3, "outclass": 1, "method": 5,
                            "useoutname": 1, "outname": "__h3dm_nv", "deletein": 0}).execute(t2, [t1])
    vpt = np.frombuffer(t2.vertexIntAttribValuesAsString("__h3dm_pt"), dtype=np.int32).astype(np.int64)
    cnt = np.frombuffer(t2.primIntAttribValuesAsString("__h3dm_nv"), dtype=np.int32).astype(np.int64)
    off = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(cnt, out=off[1:])
    if off[-1] != len(vpt):
        raise RuntimeError("H3DM: vertex table mismatch (%d vs %d)" % (off[-1], len(vpt)))
    return off, vpt


def _str_values(geo, name, n):
    return np.array(geo.primStringAttribValues(name), dtype=object) if geo.findPrimAttrib(name) is not None \
        else np.full(n, "", dtype=object)


def object_signatures(geo, topo=None, exclude=()):
    """{rhino_id: отпечаток} для объектов Rhino в geo (примитивы с rhino_id, не части вставок блоков).
    exclude — номера примитивов, которые не входят в объект (вспомогательные кривые границ)."""
    n = geo.intrinsicValue("primitivecount")
    if not n or geo.findPrimAttrib("rhino_id") is None:
        return {}
    off, vpt = topo if topo is not None else topology(geo)
    rid = _str_values(geo, "rhino_id", n)
    inst = _str_values(geo, "rhino_instance_id", n)
    rf = (np.frombuffer(geo.primIntAttribValuesAsString("rhino_face"), dtype=np.int32)
          if geo.findPrimAttrib("rhino_face") is not None else np.full(n, -1, dtype=np.int32))
    keep = (rid != "") & (inst == "")
    if len(exclude):
        keep[np.asarray(list(exclude), dtype=np.int64)] = False
    idx = np.nonzero(keep)[0]
    if not len(idx):
        return {}
    P = np.frombuffer(geo.pointFloatAttribValuesAsString("P"), dtype=np.float32).reshape(-1, 3)
    W = (np.frombuffer(geo.pointFloatAttribValuesAsString("Pw"), dtype=np.float32)
         if geo.findPointAttrib("Pw") is not None else None)
    basis = {}
    for p in geo.iterPrimsOfType(hou.primType.NURBSSurface):
        i = p.number()
        if keep[i]:
            basis[i] = (np.int32([p.intrinsicValue("uorder"), p.intrinsicValue("vorder"),
                                  bool(p.intrinsicValue("uwrap")), bool(p.intrinsicValue("vwrap"))]).tobytes()
                        + np.asarray(p.intrinsicValue("uknots"), dtype=np.float32).tobytes()
                        + np.asarray(p.intrinsicValue("vknots"), dtype=np.float32).tobytes())
    for p in geo.iterPrimsOfType(hou.primType.NURBSCurve):
        i = p.number()
        if keep[i]:
            basis[i] = (np.int32([p.intrinsicValue("order"), bool(p.intrinsicValue("closed"))]).tobytes()
                        + np.asarray(p.intrinsicValue("knots"), dtype=np.float32).tobytes())
    rk = rid[idx]
    uniq, inv = np.unique(rk.astype(str), return_inverse=True)
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(len(uniq) + 1))
    cnt = (off[1:] - off[:-1])
    out = {}
    for k, r in enumerate(uniq):
        prims = idx[order[bounds[k]:bounds[k + 1]]]
        if prims[-1] - prims[0] + 1 == len(prims):
            vids = vpt[off[prims[0]]:off[prims[-1] + 1]]
        else:
            vids = np.concatenate([vpt[off[i]:off[i + 1]] for i in prims])
        h = hashlib.sha1(b"H3DM-geo-1")
        h.update(cnt[prims].astype(np.int32).tobytes())
        h.update(rf[prims].astype(np.int32).tobytes())
        h.update(P[vids].tobytes())
        if W is not None:
            h.update(W[vids].tobytes())
        for i in prims:
            b = basis.get(int(i))
            if b is not None:
                h.update(b)
        out[str(r)] = h.hexdigest()[:24]
    return out


def write_signatures(geo, exclude=()):
    """Импорт: rhino_geo_sig на каждый примитив объекта."""
    sigs = object_signatures(geo, exclude=exclude)
    if not sigs:
        return 0
    n = geo.intrinsicValue("primitivecount")
    rid = geo.primStringAttribValues("rhino_id")
    inst = geo.primStringAttribValues("rhino_instance_id") if geo.findPrimAttrib("rhino_instance_id") else [""] * n
    vals = [sigs.get(r, "") if r and not inst[i] else "" for i, r in enumerate(rid)]
    if geo.findPrimAttrib(SIG_ATTR) is None:
        geo.addAttrib(hou.attribType.Prim, SIG_ATTR, "")
    geo.setPrimStringAttribValues(SIG_ATTR, vals)
    return len(sigs)


def file_signature(path):
    """Отпечаток содержимого файла (sha1; кэш по пути, размеру и времени изменения)."""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    sig = _FILE_SIGS.get(key)
    if sig is None:
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        sig = "%d:%s" % (st.st_size, h.hexdigest())
        _FILE_SIGS[key] = sig
    return sig

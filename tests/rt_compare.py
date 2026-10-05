# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сравнение двух .3dm для проверки цикла Rhino -> Houdini -> .3dm (rhino3dm, без Houdini).

compare(a, b) -> список расхождений по объектам с общими id: тип, имя, слой, User Text, материал, группы,
габарит (с допуском tol в единицах файла), а также слои, Document User Text и единицы.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python3.13libs"))


def _box(g, rr):
    """Габарит для сравнения: у Brep/Extrusion — по сеткам отображения граней (как их видит импорт сетками),
    иначе GetBoundingBox(). None — для типов, которые экспорт не повторяет (SubD, аннотации, блоки)."""
    import numpy as np
    k = rr.enum_name(g.ObjectType)
    pts = None
    if k in ("Brep", "Extrusion"):
        allp = []
        meshes = [g.GetMesh(rr._r().MeshType.Any)] if k == "Extrusion" else \
            [g.Faces[i].GetMesh(rr._r().MeshType.Any) for i in range(len(g.Faces))]
        for m in meshes:
            if m is not None:
                allp.extend((p.X, p.Y, p.Z) for p in m.Vertices.ToPoint3dArray())
        if allp:
            pts = np.array(allp)
    if pts is not None:
        mn, mx = pts.min(0), pts.max(0)
        return tuple(mn) + tuple(mx)
    if k in ("SubD", "InstanceReference", "Annotation", "Light", "TextDot"):
        return None
    bb = g.GetBoundingBox()
    return (bb.Min.X, bb.Min.Y, bb.Min.Z, bb.Max.X, bb.Max.Y, bb.Max.Z)


def info(path):
    import h3dm.rhino_read as rr
    f = rr.read(path)
    lay = {l.Index: l.FullPath for l in f.Layers}
    mats = {i: m.Name for i, m in enumerate(f.Materials)}
    grp = {g.Index: g.Name for g in f.Groups}
    objs = {}
    for o in f.Objects:
        a = o.Attributes
        g = o.Geometry
        box = _box(g, rr)
        objs.setdefault(str(a.Id), []).append({
            "type": rr.enum_name(g.ObjectType), "name": a.Name or "", "layer": lay.get(a.LayerIndex),
            "ut": dict(a.GetUserStrings()) if a.UserStringCount else {},
            "mat": mats.get(a.MaterialIndex) if rr.enum_name(a.MaterialSource) == "MaterialFromObject" else None,
            "groups": sorted(grp.get(i, "?") for i in (a.GetGroupList() or [])), "box": box,
            "color_source": rr.enum_name(a.ColorSource), "color": tuple(a.ObjectColor)[:3]})
    doc = {}
    try:
        for k, v in rr.doc_strings(f).items():
            doc[k] = v
    except Exception:
        pass
    return {"objects": objs, "layers": sorted(l.FullPath for l in f.Layers), "doc": doc,
            "units": rr.enum_name(f.Settings.ModelUnitSystem)}


def compare(path_a, path_b, tol=0.01, fields=("type", "name", "layer", "ut", "mat", "groups", "box")):
    A, B = info(path_a), info(path_b)
    out = []
    common = sorted(set(A["objects"]) & set(B["objects"]))
    for k in common:
        a, b = A["objects"][k][0], B["objects"][k][0]
        for f in fields:
            va, vb = a[f], b[f]
            if f == "box":
                if va is None or vb is None:
                    if (va is None) != (vb is None) and a["type"] not in ("SubD", "InstanceReference"):
                        out.append((k, f, va, vb))
                elif max(abs(x - y) for x, y in zip(va, vb)) > tol:
                    out.append((k, f, va, vb))
            elif va != vb:
                out.append((k, f, va, vb))
    missing = sorted(set(A["objects"]) - set(B["objects"]))
    if set(A["layers"]) - set(B["layers"]):
        out.append(("layers", "missing", sorted(set(A["layers"]) - set(B["layers"])), None))
    if A["doc"] != B["doc"]:
        out.append(("doc", "user text", A["doc"], B["doc"]))
    return {"diffs": out, "common": len(common), "missing": missing, "a": A, "b": B}


def _norm_points(geom, n=9):
    """Точки кривой/поверхности на равномерной сетке нормированных параметров."""
    import numpy as np
    out = []
    if hasattr(geom, "Domain") and not hasattr(geom, "OrderU"):
        d = geom.Domain
        for t in np.linspace(0.0, 1.0, n):
            p = geom.PointAt(d.T0 + t * (d.T1 - d.T0))
            out.append((p.X, p.Y, p.Z))
        return np.array(out)
    du, dv = geom.Domain(0), geom.Domain(1)
    for v in np.linspace(0.0, 1.0, n):
        row = []
        for u in np.linspace(0.0, 1.0, n):
            p = geom.PointAt(du.T0 + u * (du.T1 - du.T0), dv.T0 + v * (dv.T1 - dv.T0))
            row.append((p.X, p.Y, p.Z))
        out.append(row)
    return np.array(out)


def shape_deviation(path_a, path_b):
    """Наибольшее расстояние между одноимёнными кривыми (по id) и между поверхностями граней
    (сопоставление по ближайшему габариту; U может быть развёрнут). -> {'curves': max, 'surfaces': max, 'n': ...}"""
    import numpy as np
    import h3dm.rhino_read as rr
    fa, fb = rr.read(path_a), rr.read(path_b)
    A = {str(o.Attributes.Id): o.Geometry for o in fa.Objects}
    cur, n_c = 0.0, 0
    faces_a = []
    idefs = {str(d.Id): d for d in fa.InstanceDefinitions}

    def add_geom(g, xf, depth=0):
        k = rr.enum_name(g.ObjectType)
        if k == "Brep":
            for i in range(len(g.Faces)):
                s = g.Faces[i].UnderlyingSurface().ToNurbsSurface()
                if xf:
                    s = s.Duplicate()
                    for t in reversed(xf):          # сначала внутренняя вставка, затем внешние
                        s.Transform(t)
                faces_a.append(s)
        elif k == "InstanceReference" and depth < 8:
            d = idefs.get(str(g.ParentIdefId))
            if d is None:
                return
            x = (xf or []) + [g.Xform]
            for oid in d.GetObjectIds():
                ob = fa.Objects.FindId(oid)
                if ob is not None:
                    add_geom(ob.Geometry, x, depth + 1)
    for o in fa.Objects:
        if not o.Attributes.IsInstanceDefinitionObject:
            add_geom(o.Geometry, None)
    srf, n_s = 0.0, 0
    for o in fb.Objects:
        g = o.Geometry
        k = rr.enum_name(g.ObjectType)
        if k == "Curve" and str(o.Attributes.Id) in A:
            ga = A[str(o.Attributes.Id)]
            if rr.enum_name(ga.ObjectType) != "Curve":
                continue
            pa, pb = _norm_points(ga.ToNurbsCurve(), 33), _norm_points(g.ToNurbsCurve(), 33)
            d = min(np.abs(pa - pb).max(), np.abs(pa - pb[::-1]).max())
            cur = max(cur, float(d))
            n_c += 1
        elif k == "Brep" and len(g.Faces) == 1 and faces_a:
            sb = g.Faces[0].UnderlyingSurface().ToNurbsSurface()
            pb = _norm_points(sb)
            best = None
            for sa in faces_a:
                pa = _norm_points(sa)
                for cand in (pa, pa[:, ::-1], pa[::-1], pa[::-1, ::-1]):
                    d = float(np.abs(cand - pb).max())
                    best = d if best is None or d < best else best
            srf = max(srf, best)
            n_s += 1
    return {"curves": cur, "n_curves": n_c, "surfaces": srf, "n_surfaces": n_s}

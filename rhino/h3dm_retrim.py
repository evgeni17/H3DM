# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""H3DM: пересборка изменённых обрезанных граней в Rhino 8 (Python 3) при экспорте из Houdini.

rhino3dm не умеет обрезать поверхность несколькими петлями, поэтому экспорт отдаёт сюда изменённые объекты:
для каждой грани — поверхность NURBS (управляющие точки уже в координатах и единицах файла экспорта, веса,
полные узлы Houdini, порядки) и петли обрезки в параметрах примитива Houdini (точные петли импорта, если
обрезку в Houdini не меняли, иначе текущие кривые обрезки Houdini). Здесь:
  * поверхность строится как в экспорте необрезанных поверхностей (U разворачивается: нормаль Rhino = нормали
    в Houdini), петли переводятся в её параметры;
  * петли разбираются по вложенности: внешняя (против часовой) и отверстия (по часовой); несколько внешних
    петель — несколько граней;
  * Brep грани собирается вручную (поверхность, 2D-кривые обрезки, 3D-рёбра Pushup, вершины, особые обрезки на
    полюсах), швы замкнутых поверхностей соединяются (JoinNakedEdges); проверка IsValidWithLog;
  * грани объекта объединяются (Brep.JoinBreps); замкнутость сообщается.
Результат: .3dm (Brep с пользовательской строкой "h3dm.key" = ключ объекта) и <задание>.result.json
{id, status, out, objects: {ключ: {ok, breps, faces, solid, error}}}. Ошибка одного объекта не мешает остальным:
Houdini пишет такие объекты сетками с предупреждением.
"""
import json
import math
import os
import time
import traceback

import Rhino
import Rhino.Geometry as G

RETRIM_VERSION = 1


# ---------------------------------------------------------------- поверхность и кривые

def _rhino_knots(full):
    """Полный узловой вектор Houdini (order + count) -> узлы Rhino (без крайних)."""
    return list(full[1:-1])


def make_surface(f):
    """Данные грани -> NurbsSurface (U развёрнут относительно Houdini). -> (поверхность, a + b для u)."""
    ou, ov = int(f["ou"]), int(f["ov"])
    cv, w = f["cv"], f["w"]
    nv, nu = len(cv), len(cv[0])
    ku, kv = [float(x) for x in f["ku"]], [float(x) for x in f["kv"]]
    a, b = ku[0], ku[-1]
    ku_r = [a + b - x for x in reversed(ku)]
    rational = any(abs(float(x) - 1.0) > 1e-12 for row in w for x in row)
    s = G.NurbsSurface.Create(3, rational, ou, ov, nu, nv)
    for j in range(nv):
        for i in range(nu):
            x, y, z = cv[j][nu - 1 - i]
            ww = float(w[j][nu - 1 - i])
            s.Points.SetControlPoint(i, j, G.ControlPoint(G.Point3d(x, y, z), ww))
    for i, k in enumerate(_rhino_knots(ku_r)):
        s.KnotsU[i] = k
    for i, k in enumerate(_rhino_knots(kv)):
        s.KnotsV[i] = k
    return s, a + b


def make_curve2d(c, ab):
    """Кривая петли {'o', 'k' (полные узлы), 'p': [[u, v, w]]} в параметрах Houdini -> 2D NurbsCurve в
    параметрах поверхности Rhino (u -> a + b - u)."""
    order = int(c["o"])
    pts = c["p"]
    kn = [float(x) for x in c["k"]]
    rational = any(abs(float(p[2]) - 1.0) > 1e-12 for p in pts)
    nc = G.NurbsCurve(3, rational, order, len(pts))
    for i, p in enumerate(pts):
        nc.Points.SetPoint(i, G.Point3d(ab - float(p[0]), float(p[1]), 0.0), float(p[2]))
    for i, k in enumerate(_rhino_knots(kn)):
        nc.Knots[i] = k
    nc.ChangeDimension(2)
    return nc


# ---------------------------------------------------------------- петли

def _polygon(curves, n=24):
    pts = []
    for c in curves:
        d = c.Domain
        for i in range(n):
            p = c.PointAt(d.T0 + (d.T1 - d.T0) * i / float(n))
            pts.append((p.X, p.Y))
    return pts


def _area(poly):
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def _inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[i - 1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def _reverse_loop(curves):
    out = []
    for c in reversed(curves):
        c = c.DuplicateCurve()
        c.Reverse()
        out.append(c)
    return out


def classify(loops):
    """Петли (списки 2D-кривых) -> грани [(внешняя, [отверстия])]: по вложенности, ориентация Rhino
    (внешняя против часовой стрелки, отверстия по часовой)."""
    info = []
    for curves in loops:
        poly = _polygon(curves)
        info.append({"curves": curves, "poly": poly, "area": _area(poly)})
    info.sort(key=lambda d: -abs(d["area"]))
    for i, d in enumerate(info):
        probe = d["poly"][0]
        d["parents"] = [j for j in range(i) if _inside(probe, info[j]["poly"])]
    faces = []
    index = {}
    for i, d in enumerate(info):
        depth = len(d["parents"])
        curves = d["curves"]
        if depth % 2 == 0:
            if d["area"] < 0:
                curves = _reverse_loop(curves)
            index[i] = len(faces)
            faces.append((curves, []))
        else:
            parent = max(d["parents"])          # ближайшая охватывающая петля (наименьшая из охватывающих)
            if d["area"] > 0:
                curves = _reverse_loop(curves)
            if parent in index:
                faces[index[parent]][1].append(curves)
    return faces


# ---------------------------------------------------------------- Brep грани

def face_brep(srf, outer, holes, tol):
    """Brep одной грани из поверхности и 2D-петель (вручную, как в примерах RhinoCommon)."""
    brep = G.Brep()
    si = brep.AddSurface(srf)
    face = brep.Faces.Add(si)
    for li, curves in enumerate([outer] + holes):
        loop = brep.Loops.Add(G.BrepLoopType.Outer if li == 0 else G.BrepLoopType.Inner, face)
        n = len(curves)
        starts = []
        c3 = []
        for c in curves:
            p = c.PointAtStart
            starts.append(srf.PointAt(p.X, p.Y))
            e = srf.Pushup(c, tol)
            if e is not None and e.GetLength() <= tol:
                e = None
            c3.append(e)
        # вершины по углам петли: совпадающие (полюс, шов) — одна вершина
        verts = []

        def vertex(pt):
            for v in verts:
                if v.Location.DistanceTo(pt) <= tol:
                    return v
            v = brep.Vertices.Add(pt, tol)
            verts.append(v)
            return v
        corner = [vertex(p) for p in starts]
        for k in range(n):
            c2i = brep.AddTrimCurve(curves[k])
            iso = srf.IsIsoparametric(curves[k])
            if c3[k] is None:
                tr = brep.Trims.AddSingularTrim(corner[k], loop, iso, c2i)
            else:
                c3i = brep.AddEdgeCurve(c3[k])
                edge = brep.Edges.Add(corner[k], corner[(k + 1) % n], c3i, tol)
                tr = brep.Trims.Add(edge, False, loop, c2i)
                tr.IsoStatus = iso
            tr.SetTolerances(tol, tol)
    brep.SetTolerancesBoxesAndFlags(False, True, True, True, True, True, True, True)
    brep.JoinNakedEdges(tol)
    brep.Compact()
    return brep


def build_object(obj, tol):
    """Объект {'key', 'faces': [...]} -> (список Brep, сведения)."""
    pieces, errors, nfaces = [], [], 0
    for f in obj["faces"]:
        try:
            srf, ab = make_surface(f)
            if not srf.IsValid:
                errors.append("face %s: invalid surface" % f.get("prim"))
                continue
            loops = f.get("loops") or []
            if not loops:
                b = G.Brep.CreateFromSurface(srf)
                if b is None:
                    errors.append("face %s: CreateFromSurface failed" % f.get("prim"))
                    continue
                pieces.append(b)
                nfaces += 1
                continue
            loops2d = [[make_curve2d(c, ab) for c in lp["c"]] for lp in loops if lp.get("c")]
            for outer, holes in classify(loops2d):
                b = face_brep(srf, outer, holes, tol)
                ok, log = b.IsValidWithLog()
                if not ok:
                    b.Repair(tol)
                    ok, log = b.IsValidWithLog()
                if not ok:
                    errors.append("face %s: %s" % (f.get("prim"), (log or "").strip().splitlines()[:2]))
                    continue
                pieces.append(b)
                nfaces += 1
        except Exception as ex:
            errors.append("face %s: %s" % (f.get("prim"), ex))
    if errors:
        return [], {"ok": False, "error": "; ".join(str(e) for e in errors)[:1000], "faces": nfaces}
    joined = list(G.Brep.JoinBreps(pieces, tol) or []) if len(pieces) > 1 else pieces
    if not joined:
        joined = pieces
    out = []
    for b in joined:
        ok, log = b.IsValidWithLog()
        if not ok:
            return [], {"ok": False, "error": "joined brep invalid: %s" % (log or "").strip()[:300], "faces": nfaces}
        out.append(b)
    return out, {"ok": True, "breps": len(out), "faces": nfaces, "solid": all(b.IsSolid for b in out)}


# ---------------------------------------------------------------- задание

def run(job):
    tol = float(job.get("tol") or 0.001)
    out_path = job["out"]
    f3 = Rhino.FileIO.File3dm()
    res = {"objects": {}, "version": RETRIM_VERSION}
    for obj in job.get("objects", []):
        breps, info = build_object(obj, tol)
        res["objects"][obj["key"]] = info
        for b in breps:
            b.SetUserString("h3dm.key", obj["key"])
            f3.Objects.AddBrep(b)
    tmp = out_path + ".tmp.3dm"
    if not f3.Write(tmp, 8):
        raise RuntimeError("could not write %s" % tmp)
    os.replace(tmp, out_path)
    res["status"] = "ok"
    res["out"] = out_path
    return res


def run_job(job_path):
    res_path = job_path + ".result.json"
    result = {"id": None, "status": "error"}
    try:
        with open(job_path, encoding="utf-8") as fh:
            job = json.load(fh)
        result["id"] = job.get("id")
        result.update(run(job))
    except Exception:
        result["error"] = traceback.format_exc()
    tmp = res_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    os.replace(tmp, res_path)
    return result


if "H3DM_JOB" in globals():
    run_job(globals()["H3DM_JOB"])

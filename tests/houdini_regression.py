# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Регрессия HDA в Houdini (Python Shell или hython):
    exec(open("<H3DM>/tests/houdini_regression.py").read())
Создаёт временный /obj/__h3dm_regression и удаляет его. Возвращает список ошибок (пустой = OK).
"""
import collections
import os

import hou

ROOT = os.environ.get("H3DM") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FX = os.path.join(ROOT, "tests", "fixtures")


def _outward(prims):
    bb = prims[0].boundingBox()
    for p in prims[1:]:
        bb.enlargeToContain(p.boundingBox())
    c = bb.center()
    n = 0
    for p in prims:
        if p.type() == hou.primType.NURBSSurface:
            pos, nn = p.positionAt(0.5, 0.5), p.normalAt(0.5, 0.5)
        else:
            pos = sum((v.point().position() for v in p.vertices()), hou.Vector3()) / p.numVertices()
            nn = p.normal()
        n += (pos - c).dot(nn) > 0
    return n


def run():
    fails = []
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression")
    try:
        n = tmp.createNode("h3dm::3dm_import", "imp")
        n.parm("file").set(os.path.join(FX, "h3dm_fixture_v001.3dm"))
        for mode in ("nurbs", "polys", "packed"):
            n.parm("surfout").set(mode)
            n.cook(force=True)
            if n.node("GEO").errors():
                fails.append("%s: %s" % (mode, n.node("GEO").errors()))
                continue
            g = n.geometry(0)
            kinds = collections.Counter(p.type().name() for p in g.prims())
            if mode == "nurbs" and kinds.get("NURBSSurface", 0) < 10:
                fails.append("nurbs: мало NURBS %s" % dict(kinds))
            if mode != "packed":
                box = [p for p in g.prims() if p.attribValue("name") == "Panel_01"]
                if _outward(box) != 6:
                    fails.append("%s: нормали Panel_01 смотрят внутрь" % mode)
                if g.findPrimGroup("Gruppa_fasad") is None:
                    fails.append("%s: нет группы Gruppa_fasad" % mode)
                lays = set(g.primStringAttribValues("layer"))
                if "Fasad::Paneli" not in lays:
                    fails.append("%s: слои %s" % (mode, sorted(lays)[:5]))
                if "Фасад::Панели" not in set(g.primStringAttribValues("layer_orig")):
                    fails.append("%s: нет layer_orig" % mode)
                if g.findPrimAttrib("Marka") is None or g.findPrimAttrib("thickness") is None:
                    fails.append("%s: User Text не развёрнут в атрибуты" % mode)
        # необрезанные NURBS + кривые границ
        n.parm("surfout").set("nurbs")
        n.parm("trimnurbs").set(1)
        g = n.geometry(0)
        if len(g.findPrimGroup("rhino_trim_curves").prims()) < 10:
            fails.append("trim curves: мало кривых границ")
        n.parm("trimnurbs").set(0)
        # Info и Xform
        gi = n.geometry(1)
        types = collections.Counter(gi.pointStringAttribValues("info_type"))
        for t in ("textdot", "text", "dimension", "leader", "point", "light"):
            if not types.get(t):
                fails.append("info: нет %s" % t)
        gx = n.geometry(2)
        if gx.intrinsicValue("pointcount") != 1 or gx.findPointAttrib("h3dm_xform") is None:
            fails.append("xform: нет точки с h3dm_xform")
        # Manual origin + передача через вход другого импорта
        n.parm("xformmode").set("manual")
        n.parmTuple("manualorigin").set((1000.0, 2000.0, 0.0))
        n2 = tmp.createNode("h3dm::3dm_import", "imp2")
        n2.parm("file").set(os.path.join(FX, "h3dm_fixture_v001.3dm"))
        n2.setInput(0, n, 2)
        d2 = n2.geometry(0).dictAttribValue("h3dm_xform")
        if d2.get("source") != "input" or d2.get("origin_text", "").split()[:2] != ["1000.000000000", "2000.000000000"]:
            fails.append("xform input: %s" % d2)
        b1, b2 = n.geometry(0).boundingBox(), n2.geometry(0).boundingBox()
        if (b1.minvec() - b2.minvec()).length() > 1e-5:
            fails.append("xform input: геометрия не совпала")
        # файл без сеток: предупреждение, без ошибок
        n.parm("xformmode").set("auto_far")
        n.parm("file").set(os.path.join(FX, "h3dm_fixture_small_v001.3dm"))
        n.parm("surfout").set("polys")
        n.cook(force=True)
        if n.node("GEO").errors():
            fails.append("small: %s" % n.node("GEO").errors())
    finally:
        tmp.destroy()
    print("houdini_regression: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


# ---------------------------------------------------------------- пограничные случаи (отчёт проверки 0.2)

def _rhino_file(path):
    import h3dm  # noqa: F401  (vendor в sys.path)
    import rhino3dm
    return rhino3dm, rhino3dm.File3dm.Read(path)


def _prims(g, name, kind=None):
    return [p for p in g.prims() if p.attribValue("name") == name and (kind is None or p.type() == kind)]


def run_edgecases():
    import numpy as np
    from h3dm.xform import GlobalXform
    fails = []
    path = os.path.join(FX, "h3dm_edgecases_v001.3dm")
    rh, f = _rhino_file(path)
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression_edge")
    try:
        n = tmp.createNode("h3dm::3dm_import", "imp")
        n.parm("file").set(path)
        n.parm("nonlatin").set("translit_keep")
        n.parm("surfout").set("nurbs")
        g = n.geometry(0)
        gx = GlobalXform.from_dict(g.dictAttribValue("h3dm_xform"))
        src = {o.Attributes.Name: o.Geometry for o in f.Objects}

        # 1. периодическая кривая: форма и замкнутость
        c = _prims(g, "periodic_curve", hou.primType.NURBSCurve)
        if len(c) != 1:
            fails.append("periodic curve: %d NURBS" % len(c))
        else:
            rc = src["periodic_curve"]
            d = rc.Domain
            us = np.linspace(0.0, 1.0, 41)
            ref = gx.to_houdini([tuple((lambda p: (p.X, p.Y, p.Z))(rc.PointAt(d.T0 + u * (d.T1 - d.T0)))) for u in us])
            got = np.array([tuple(c[0].positionAt(float(u))) for u in us])
            err = float(np.abs(got - ref).max())
            gap = float(np.linalg.norm(got[0] - got[-1]))
            if err > 1e-4 or gap > 1e-5:
                fails.append("periodic curve: max error %.6f, end gap %.6f" % (err, gap))
        # периодическая поверхность (U в Houdini развёрнут: u_h = 1 - u_rhino)
        sp = _prims(g, "periodic_tube", hou.primType.NURBSSurface)
        if len(sp) != 1:
            fails.append("periodic surface: %d NURBS" % len(sp))
        else:
            rs = src["periodic_tube"].Faces[0].UnderlyingSurface()
            du, dv = rs.Domain(0), rs.Domain(1)
            err = 0.0
            for u in np.linspace(0, 1, 9):
                for v in np.linspace(0, 1, 5):
                    p = rs.PointAt(du.T0 + (1 - u) * (du.T1 - du.T0), dv.T0 + v * (dv.T1 - dv.T0))
                    ref = gx.to_houdini([(p.X, p.Y, p.Z)])[0]
                    err = max(err, float(np.abs(np.array(tuple(sp[0].positionAt(float(u), float(v)))) - ref).max()))
            if err > 1e-4:
                fails.append("periodic surface: max error %.6f" % err)

        # 2. User Text: ключи name и ut_name не сливаются; числа
        ut = _prims(g, "usertext")[0]
        vals = {a.name(): ut.attribValue(a.name()) for a in g.primAttribs()}
        if not ({"first", "second"} <= {v for v in vals.values() if isinstance(v, str)}):
            fails.append("user text collision: name/ut_name -> %s" % {k: v for k, v in vals.items() if "name" in k})
        if vals.get("id") != 123456789 and vals.get("id") != "123456789":
            fails.append("user text id: %r" % vals.get("id"))
        if vals.get("code") != "007":
            fails.append("user text code: %r" % vals.get("code"))
        if vals.get("big") not in ("12345678901", 12345678901):
            fails.append("user text big: %r" % vals.get("big"))
        if not isinstance(vals.get("ratio"), float) or abs(vals["ratio"] - 0.25) > 1e-7:
            fails.append("user text ratio: %r" % vals.get("ratio"))

        # 3. коллизии имён кириллица/латиница
        orig = {}
        for p in g.prims():
            no = p.attribValue("name_orig") if g.findPrimAttrib("name_orig") else ""
            nm = no or p.attribValue("name")
            if nm in ("Еда", "Эда", "Eda", "Eda_2"):
                orig[nm] = (p.attribValue("layer"), p.attribValue("name"), p.attribValue("path"))
        for i in range(3):
            col = {v[i] for v in orig.values()}
            if len(orig) != 4 or len(col) != 4:
                fails.append("name collision (%s): %s" % (("layer", "name", "path")[i], orig))
                break

        # 4. By Parent в блоках: Expand и Packed
        expect = {"instance_0": ((1.0, 0.0, 0.0), "Beton"), "instance_1": ((0.0, 1.0, 0.0), "Steklo")}
        for blocks in ("expand", "packed"):
            n.parm("blocks").set(blocks)
            g = n.geometry(0)
            for inst, (cd, mat) in expect.items():
                if blocks == "expand":
                    kids = [p for p in g.prims() if p.attribValue("rhino_id") == _id_of(f, inst)
                            and p.attribValue("name") == "child_by_parent"]
                else:
                    pk = [p for p in g.prims() if p.type().name() == "PackedGeometry" and p.attribValue("name") == inst]
                    kids = [q for p in pk for q in p.getEmbeddedGeometry().prims() if q.attribValue("name") == "child_by_parent"]
                if not kids:
                    fails.append("by parent (%s, %s): child not found" % (blocks, inst))
                    continue
                got = tuple(round(x, 3) for x in kids[0].attribValue("Cd"))
                gm = kids[0].attribValue("material") if kids[0].geometry().findPrimAttrib("material") else ""
                if got != cd or gm != mat:
                    fails.append("by parent (%s, %s): Cd %s material %r" % (blocks, inst, got, gm))
        n.parm("blocks").set("packed")

        # 5. цвета: облако рядом с цветной сеткой; Packed сохраняет цвета вершин
        n.parm("surfout").set("polys")
        g = n.geometry(0)
        grp = g.findPointGroup("rhino_point_clouds")
        if grp is None or len({tuple(round(x, 3) for x in p.attribValue("Cd")) for p in grp.points()}) < 50:
            fails.append("cloud colors lost next to a coloured mesh")
        elif grp.points()[0].attribValue("name") != "cloud" or not g.findPointAttrib("scan"):
            fails.append("cloud metadata (name / User Text) missing")
        n.parm("surfout").set("packed")
        g = n.geometry(0)
        pk = [p for p in g.prims() if p.attribValue("name") == "vertex_colors"]
        eg = pk[0].getEmbeddedGeometry() if pk else None
        if eg is None or eg.findPointAttrib("Cd") is None or len({tuple(p.attribValue("Cd")) for p in eg.points()}) < 4:
            fails.append("packed: vertex colours lost")

        # 6. фильтры: Geometry и Info одинаково
        n.parm("surfout").set("polys")
        for parm, gone in (("skiphidden", ("on_hidden_layer", "hidden_object", "hidden_dot", "child_hidden")),
                           ("skiplocked", ("on_locked_layer",))):
            n.parm(parm).set(1)
            n.parm("blocks").set("expand")
            g0, g1 = n.geometry(0), n.geometry(1)
            names0 = set(g0.primStringAttribValues("name"))
            names1 = set(g1.pointStringAttribValues("name")) if g1.findPointAttrib("name") else set()
            left = [x for x in gone if x in names0 or x in names1]
            if left:
                fails.append("%s: still present %s" % (parm, left))
            if "visible_dot" not in names1:
                fails.append("%s: visible_dot removed" % parm)
            n.parm(parm).set(0)
        n.parm("blocks").set("packed")

        # 7. Packed + Expand: дочерние объекты блоков — отдельные packed
        n.parm("surfout").set("packed")
        n.parm("blocks").set("expand")
        g = n.geometry(0)
        if not any(p.attribValue("name") == "child_by_parent" for p in g.prims()):
            fails.append("packed + expand: block children not expanded")
        n.parm("blocks").set("packed")

        # 8. допуск кривых влияет на полилинии
        n.parm("surfout").set("polys")
        n.parm("curves").set("poly")
        counts = []
        for tol in (0.01, 50.0):
            n.parm("curvetol").set(tol)
            counts.append(sum(p.numVertices() for p in _prims(n.geometry(0), "periodic_curve")))
        if not counts[0] > counts[1]:
            fails.append("curvetol has no effect: %s" % counts)

        # 9. повреждённый файл: понятная ошибка без traceback
        bad = os.path.join(hou.text.expandString("$HOUDINI_TEMP_DIR"), "h3dm_broken.3dm")
        with open(bad, "wb") as fh:
            fh.write(b"3D Geometry File Format " + b"\x00" * 200)
        n.parm("file").set(bad)
        try:
            n.cook(force=True)
        except Exception:
            pass
        err = " ".join(n.node("GEO").errors())
        if not err or "Traceback" in err:
            fails.append("broken file: %r" % err[:200])
    finally:
        tmp.destroy()
    print("houdini_regression edge cases: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


def _id_of(f, name):
    for o in f.Objects:
        if o.Attributes.Name == name:
            return str(o.Attributes.Id)
    return ""


result = run() + run_edgecases()

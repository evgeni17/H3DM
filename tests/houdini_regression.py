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
        n.parm("geomode").set("legacy")      # проверки 0.2: поведение старых сцен
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
        n2.parm("geomode").set("legacy")
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
        n.parm("geomode").set("legacy")
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


# ---------------------------------------------------------------- 0.3: режимы, точная обрезка, группы типов, Xform

def _check_type_groups(g, label, fails):
    """Каждый примитив ровно в одной группе h3dm_type_*, счётчики = статистика типов."""
    import collections
    names = {"Poly": "h3dm_type_polygon", "NURBCurve": "h3dm_type_nurbs_curve", "NURBMesh": "h3dm_type_nurbs_surface",
             "PackedGeometry": "h3dm_type_packed_geometry"}
    stat = collections.Counter(names.get(p.intrinsicValue("typename"), "h3dm_type_other") for p in g.prims())
    member = collections.Counter()
    for grp in g.primGroups():
        if grp.name().startswith("h3dm_type_"):
            got = len(grp.prims())
            if got != stat.get(grp.name(), 0):
                fails.append("%s: group %s has %d, type count %d" % (label, grp.name(), got, stat.get(grp.name(), 0)))
            for p in grp.prims():
                member[p.number()] += 1
    if any(v != 1 for v in member.values()) or len(member) != len(g.prims()):
        fails.append("%s: primitives not in exactly one h3dm_type_ group (%d of %d)" % (label, len(member), len(g.prims())))


def run_v03():
    import collections
    from h3dm import rhino_read as rr
    fails = []
    prepared = os.path.join(FX, "h3dm_fixture_prepared_v001.3dm")
    small = os.path.join(FX, "h3dm_fixture_small_v001.3dm")
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression_v03")
    try:
        n = tmp.createNode("h3dm::3dm_import", "imp")
        if n.parm("geomode").evalAsString() != "mesh_curves":
            fails.append("new node mode: %s" % n.parm("geomode").evalAsString())
        n.parm("file").set(prepared)
        expect = {"mesh_curves": (0, None), "nurbs_surfaces": (2, 2), "all_nurbs": (24, 7)}
        for mode, (nsurf, exact) in expect.items():
            n.parm("geomode").set(mode)
            for pack in (0, 1):
                n.parm("pack").set(pack)
                n.cook(force=True)
                if n.node("GEO").errors():
                    fails.append("%s pack=%d: %s" % (mode, pack, n.node("GEO").errors()))
                    continue
                g = n.geometry(0)
                _check_type_groups(g, "%s pack=%d" % (mode, pack), fails)
                if pack:
                    if any(p.intrinsicValue("typename") != "PackedGeometry" for p in g.prims()):
                        fails.append("%s pack=1: non-packed primitives on top level" % mode)
                    continue
                kinds = collections.Counter(p.intrinsicValue("typename") for p in g.prims())
                if kinds.get("NURBMesh", 0) != nsurf:
                    fails.append("%s: NURBS surfaces %d, expected %d" % (mode, kinds.get("NURBMesh", 0), nsurf))
                grp = g.findPrimGroup("rhino_trimmed_exact")
                if exact is not None and (grp is None or len(grp.prims()) != exact):
                    fails.append("%s: exact trimmed %s, expected %d" % (mode, len(grp.prims()) if grp else 0, exact))
                if mode == "mesh_curves" and kinds.get("NURBCurve", 0) != 5:
                    fails.append("mesh_curves: NURBS curves %d (lines/polylines must be NURBS too)" % kinds.get("NURBCurve", 0))
        n.parm("pack").set(0)
        # точность обрезки: площадь каждой точной грани против площади Rhino из подготовки
        n.parm("geomode").set("all_nurbs")
        g = n.geometry(0)
        f = rr.read(prepared)
        areas = {}
        for o in f.Objects:
            if type(o.Geometry).__name__ == "Brep":
                for fi, fd in (rr.brep_trims(o.Geometry) or {}).items():
                    areas[(str(o.Attributes.Id), fi)] = fd["a"]
        verb = hou.sopNodeTypeCategory().nodeVerb("convert")
        verb.setParms({"totype": 0, "lodu": 20.0, "lodv": 20.0, "lodtrim": 20.0})
        unit = g.attribValue("rhino_unit_m")
        for p in g.findPrimGroup("rhino_trimmed_exact").prims():
            sub = hou.Geometry()
            sub.merge(g)
            sub.deletePrims([q for q in sub.prims() if q.number() != p.number()])
            out = hou.Geometry()
            verb.execute(out, [sub])
            a = sum(q.intrinsicValue("measuredarea") for q in out.prims()) / (unit * unit)
            ra = areas.get((p.attribValue("rhino_id"), p.attribValue("rhino_face")))
            if not ra or abs(a - ra) / ra > 0.002:
                fails.append("trimmed area %s f%d: %s vs Rhino %s" % (p.attribValue("name"), p.attribValue("rhino_face"), a, ra))
        # без подготовки: обрезанные грани — необрезанные NURBS + кривые границ с предупреждением
        n.parm("file").set(small)
        n.cook(force=True)
        if not any("Prepare in Rhino" in w for w in n.node("GEO").warnings()):
            fails.append("unprepared all_nurbs: no Prepare in Rhino warning")
        if not n.geometry(0).findPrimGroup("rhino_trimmed_surfaces"):
            fails.append("unprepared all_nurbs: no rhino_trimmed_surfaces group")
        # строгий вход Xform: подключена посторонняя геометрия -> ошибка
        box = tmp.createNode("box", "not_xform")
        n.setInput(0, box)
        try:
            n.cook(force=True)
        except hou.OperationFailed:
            pass
        if not n.node("GEO").errors() or "Xform input" not in " ".join(n.node("GEO").errors()):
            fails.append("strict xform: no error for a wrong input")
        # нулевой входной сдвиг обязателен; масштаб/оси — со входа
        src = tmp.createNode("h3dm::3dm_import", "src")
        src.parm("file").set(small)
        src.parm("xformmode").set("none")
        src.parm("scale").set(1000.0)
        n.setInput(0, src, 2)
        n.parm("xformmode").set("auto")
        g = n.geometry(0)
        d = g.dictAttribValue("h3dm_xform")
        if d.get("origin_text", "").split() != ["0.000000000"] * 3 or abs(d.get("scale", 0) - 1000.0) > 1e-9:
            fails.append("xform input: %s" % d)
        if not any("Xform input" in w for w in n.node("GEO").warnings()):
            fails.append("xform input: no warning about inherited scale")
    finally:
        tmp.destroy()
    print("houdini_regression 0.3: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


def run_prepare():
    """Prepare in Rhino: нужен запущенный Rhino 8 (иначе пропуск). Путь с пробелами и кириллицей."""
    import shutil
    import tempfile
    from h3dm import rhino_bridge as rb, prepare_ui as pu, rhino_read as rr
    fails = []
    inst = rb.list_instances()
    if not inst:
        print("houdini_regression prepare: SKIPPED (no running Rhino 8)")
        return fails
    d = os.path.join(tempfile.mkdtemp(prefix="h3dm_prep_"), "папка с пробелом")
    os.makedirs(d)
    src = os.path.join(d, "малый файл.3dm")
    shutil.copy(os.path.join(FX, "h3dm_fixture_small_v001.3dm"), src)
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression_prep")
    try:
        r = rb.wait(rb.submit(src, {"preset": "coarse"}, inst[0]["id"]), 120)
        out = r.get("output") or ""
        if r.get("status") != "ok" or not out.endswith("малый файл_h3dm_v001.3dm"):
            fails.append("prepare: %s" % {k: r.get(k) for k in ("status", "output", "error")})
        else:
            st = r.get("stats", {})
            if st.get("check_faces_meshed") != st.get("check_faces") or not st.get("check_faces"):
                fails.append("prepare: faces without mesh %s" % st)
            if rr.prepare_source(out) != src:
                fails.append("prepare: stamp source %s" % rr.prepare_source(out))
            # повтор с исходником и теми же настройками -> skipped
            r2 = rb.wait(rb.submit(src, {"preset": "coarse"}, inst[0]["id"]), 60)
            if r2.get("status") != "skipped" or r2.get("output") != out:
                fails.append("prepare repeat: %s" % r2.get("status"))
            # нода: штамп в detail, все грани обрезаны точно, без предупреждений
            n = tmp.createNode("h3dm::3dm_import", "imp")
            n.parm("file").set(out)
            n.parm("geomode").set("all_nurbs")
            g = n.geometry(0)
            warn = [w for w in n.node("GEO").warnings() if "Rhino meshes stay meshes" not in w]
            if warn or n.node("GEO").errors():
                fails.append("prepared all_nurbs: %s %s" % (n.node("GEO").warnings(), n.node("GEO").errors()))
            if g.findGlobalAttrib("h3dm_prepare") is None:
                fails.append("prepared: no h3dm_prepare detail attribute")
            if "h3dm.prepare" in g.dictAttribValue("rhino_doc_text"):
                fails.append("prepared: stamp leaked into rhino_doc_text")
            if "Prepared in Rhino" not in rr.file_info(out):
                fails.append("prepared: File Info has no stamp")
            # синхронный путь ноды (как в hython): поздний/изменённый файл не трогается
            n.parm("file").set(src)
            res = pu.start(src, {"preset": "coarse"}, inst[0]["id"], node=None) if not hou.isUIAvailable() else None
            if res is not None and res.get("status") != "skipped":
                fails.append("prepare_ui sync: %s" % res.get("status"))
        bad = os.path.join(d, "битый.3dm")
        with open(bad, "wb") as fh:
            fh.write(b"not a 3dm" * 50)
        try:
            rb.submit(bad, {}, inst[0]["id"])
            fails.append("prepare: non-3dm file accepted")
        except rb.BridgeError:
            pass
        try:
            rb.submit(src, {}, "rhinocode_remotepipe_0")
            fails.append("prepare: unknown Rhino id accepted")
        except rb.BridgeError:
            pass
    finally:
        tmp.destroy()
        shutil.rmtree(os.path.dirname(d), ignore_errors=True)
    print("houdini_regression prepare: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


def run_cache():
    """Дисковый кэш: попадание, инвалидирование по параметру, файлу и входу Xform, Reload, предупреждения."""
    import shutil
    import tempfile
    import time
    from h3dm import geocache, sop_import as si
    fails = []
    cdir = tempfile.mkdtemp(prefix="h3dm_cache_")
    work = tempfile.mkdtemp(prefix="h3dm_cfile_")
    src = os.path.join(work, "файл с пробелом.3dm")
    shutil.copy(os.path.join(FX, "h3dm_fixture_small_v001.3dm"), src)
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression_cache")
    try:
        n = tmp.createNode("h3dm::3dm_import", "imp")
        n.parm("file").set(src)
        n.parm("geomode").set("all_nurbs")
        n.parm("cachedir").set(cdir)
        n.parm("cachemin").set(0.0)
        geo = n.node("GEO")

        def entries():
            return geocache.stats(cdir)[1]

        def cook():
            geo.cook(force=True)
            return n.geometry().intrinsicValue("primitivecount"), geo.warnings()
        c1 = cook()
        if entries() != 1 or not c1[1]:
            fails.append("cache: first cook entries=%d warnings=%s" % (entries(), c1[1]))
        # попадание: файл не читается (кэш rhino3dm в памяти очищен, сам файл временно недоступен для чтения)
        si._CACHE.clear()
        orig = si.open_file
        si.open_file = lambda path: (_ for _ in ()).throw(RuntimeError("file read on a cache hit"))
        try:
            c2 = cook()
        finally:
            si.open_file = orig
        if c2 != c1 or entries() != 1:
            fails.append("cache hit: %s vs %s, entries %d" % (c2, c1, entries()))
        # параметр -> новый ключ
        n.parm("trimtol").set(0.5)
        cook()
        if entries() != 2:
            fails.append("cache: parameter change entries=%d" % entries())
        # файл изменён (время) -> новый ключ
        st = os.stat(src)
        os.utime(src, (st.st_atime, st.st_mtime + 10))
        cook()
        if entries() != 3:
            fails.append("cache: file change entries=%d" % entries())
        # вход Xform -> новый ключ
        x = tmp.createNode("h3dm::3dm_import", "x")
        x.parm("file").set(src)
        x.parm("xformmode").set("manual")
        x.parmTuple("manualorigin").set((1000.0, 0.0, 0.0))
        n.setInput(0, x, 2)
        cook()
        if entries() < 4:
            fails.append("cache: xform input entries=%d" % entries())
        # Reload: следующая готовка мимо кэша (файл читается)
        n.setInput(0, None)
        calls = []
        si.open_file = lambda path, _o=orig: (calls.append(path), _o(path))[1]
        try:
            si.clear_cache({"node": n})
        finally:
            si.open_file = orig
        if not calls:
            fails.append("cache: Reload did not re-read the file")
        # Clear Disk Cache
        si.clear_disk_cache({"node": n})
        if entries() != 0:
            fails.append("cache: clear left %d entries" % entries())
    finally:
        tmp.destroy()
        shutil.rmtree(cdir, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    print("houdini_regression cache: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


def run_layer_levels():
    """LL0, LL1, ...: уровни s@layer на примитивах, точках облаков и точках Info; префикс; выключение."""
    fails = []
    tmp = hou.node("/obj").createNode("geo", "__h3dm_regression_ll")
    try:
        n = tmp.createNode("h3dm::3dm_import", "imp")
        n.parm("file").set(os.path.join(FX, "h3dm_fixture_v001.3dm"))
        n.parm("diskcache").set(0)
        if not n.evalParm("layerlevels"):
            fails.append("layer levels: off by default")
        for out_i, cls in ((0, "prim"), (1, "point")):
            g = n.geometry(out_i)
            find = g.findPrimAttrib if cls == "prim" else g.findPointAttrib
            names = [a.name() for a in (g.primAttribs() if cls == "prim" else g.pointAttribs())]
            lv = sorted([a for a in names if a.startswith("LL") and a[2:].isdigit()], key=lambda a: int(a[2:]))
            if not lv:
                fails.append("layer levels: none on output %d" % out_i)
                continue
            if lv != ["LL%d" % i for i in range(len(lv))]:
                fails.append("layer levels: gaps %s" % lv)
            elems = g.prims() if cls == "prim" else g.points()
            for e in elems[:2000]:
                layer = e.attribValue("layer")
                parts = [e.attribValue(a) for a in lv]
                if "::".join(p for p in parts if p) != layer or (layer and parts[0] == ""):
                    fails.append("layer levels: %s -> %s" % (layer, parts))
                    break
        n.parm("layerlevelprefix").set("Lvl")
        g = n.geometry(0)
        if g.findPrimAttrib("Lvl0") is None or g.findPrimAttrib("LL0") is not None:
            fails.append("layer levels: prefix not applied")
        n.parm("layerlevels").set(0)
        g = n.geometry(0)
        if any(a.name().startswith("Lvl") for a in g.primAttribs()):
            fails.append("layer levels: still written when off")
    finally:
        tmp.destroy()
    print("houdini_regression layer levels: %s" % ("OK" if not fails else "FAILED\n  " + "\n  ".join(fails)))
    return fails


result = run() + run_edgecases() + run_v03() + run_prepare() + run_cache() + run_layer_levels()

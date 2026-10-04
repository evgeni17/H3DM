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


result = run()

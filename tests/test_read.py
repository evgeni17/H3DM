# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тесты чтения .3dm без Houdini (нужны rhino3dm и numpy): python tests/test_read.py"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "python3.13libs"))
import h3dm.rhino_read as rr  # noqa: E402

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


FX = os.path.join(HERE, "fixtures")
f = rr.read(os.path.join(FX, "h3dm_fixture_v001.3dm"))
d = rr.doc_info(f)
check(d["units"] == "Millimeters" and abs(d["unit_m"] - 0.001) < 1e-15, "единицы: %s" % d["units"])
check(rr.doc_strings(f).get("Проект") == "МФЗ тест", "Document User Text")
paths = [l["full_path"] for l in rr.layers(f)]
check("Фасад::Панели" in paths and "Прочее::СЦЮ ПА1" in paths, "иерархия слоёв")

for mode, expect in (("nurbs", {"nsurf", "mesh", "poly", "ncurve", "points", "instance"}),
                     ("polys", {"mesh", "poly", "ncurve", "points", "instance"})):
    opt = rr.Options()
    opt.surfout = mode
    st = {}
    recs = list(rr.iter_objects(f, opt, stats=st))
    kinds = collections.Counter(p["t"] for r in recs for p in r["parts"])
    check(set(kinds) == expect, "%s: части %s" % (mode, dict(kinds)))
    check(not st.get("faces_without_mesh"), "%s: грани без сетки %s" % (mode, st))
    panel = [r for r in recs if r["name"] == "Панель_01"][0]
    check(panel["layer"] == "Фасад::Панели", "слой объекта")
    check(panel["user_text"].get("Марка") == "П-1" and panel["user_text"].get("thickness") == "200", "User Text")
    check(panel["groups"] == ["Группа фасад"], "группы: %s" % panel["groups"])
    check(panel["material"] == "Бетон" and panel["color_source"] == "ColorFromObject", "материал/цвет")

# обрезанные грани в режиме nurbs + trimnurbs: поверхности и кривые границ
opt = rr.Options()
opt.trimnurbs = True
recs = list(rr.iter_objects(f, opt))
hole = [r for r in recs if r["name"] == "Панель с отверстием"][0]
check(sum(1 for p in hole["parts"] if p["t"] == "nsurf" and p["trimmed"]) == 1, "обрезанная поверхность")
loops = {p["loop"] for p in hole["parts"] if p["t"] == "ncurve" and p.get("trim")}
check(loops == {0, 1}, "две петли границы (внешняя + отверстие): %s" % loops)

# файл без сеток: обрезанные грани отмечаются
fs = rr.read(os.path.join(FX, "h3dm_fixture_small_v001.3dm"))
opt = rr.Options()
opt.surfout = "polys"
st = {}
list(rr.iter_objects(fs, opt, stats=st))
check(st.get("faces_without_mesh", 0) > 0, "small: грани без сетки должны быть отмечены")

# информация: размер 3000 мм, текстовая метка, свет
T = rr.Tables(f)
info = rr.info_records(f, T, {"dots", "text", "dims", "points", "lights", "blocks"})
by = collections.defaultdict(list)
for i in info:
    by[i["type"]].append(i)
check(abs(by["dimension"][0]["measurement"] - 3000.0) < 1e-9, "размер")
check(by["textdot"][0]["text"] == "Марка П-1", "TextDot")
check(by["light"][0]["text"] == "Лампа", "свет")
check(len(by["block"]) == 4, "вставки блоков: %d" % len(by["block"]))

# ---------- пограничные случаи
import numpy as np  # noqa: E402
import h3dm.nurbs as nb  # noqa: E402
fe = rr.read(os.path.join(FX, "h3dm_edgecases_v001.3dm"))
src = {o.Attributes.Name: o.Geometry for o in fe.Objects}
c = src["periodic_curve"]
d = rr.nurbs_curve_data(c)
dom = c.Domain
err = max(float(np.abs(nb.eval_curve(d["cv"], d["w"], d["knots"], d["order"], t) -
                       [c.PointAt(t).X, c.PointAt(t).Y, c.PointAt(t).Z]).max())
          for t in np.linspace(dom.T0, dom.T1, 41))
check(err < 1e-9, "periodic curve: error %g" % err)
check(np.linalg.norm(d["cv"][0] - d["cv"][-1]) < 1e-9, "periodic curve: not closed after clamp")
s = src["periodic_tube"].Faces[0].UnderlyingSurface()
ds = rr.nurbs_surface_data(s)
du, dv = s.Domain(0), s.Domain(1)
err = 0.0
for u in np.linspace(du.T0, du.T1, 9):
    for v in np.linspace(dv.T0, dv.T1, 5):
        q = s.PointAt(u, v)
        e = nb.eval_surface(ds["cv"], ds["w"], ds["knots_u"], ds["knots_v"], ds["order_u"], ds["order_v"], u, v)
        err = max(err, float(np.abs(e - [q.X, q.Y, q.Z]).max()))
check(err < 1e-9, "periodic surface: error %g" % err)

# фильтры: модель, блоки и Info одинаково
Te = rr.Tables(fe)
for flag, gone in (("skiphidden", {"on_hidden_layer", "hidden_object"}), ("skiplocked", {"on_locked_layer"})):
    opt = rr.Options()
    setattr(opt, flag, True)
    names_geo = {r["name"] for r in rr.iter_objects(fe, opt, Te)}
    names_info = {r["name"] for r in rr.info_records(fe, Te, {"dots"}, None, opt.skiphidden, opt.skiplocked)}
    check(not (gone & (names_geo | names_info)), "%s: %s" % (flag, gone & (names_geo | names_info)))
    check("visible_dot" in names_info, "%s removed visible_dot" % flag)
opt = rr.Options()
opt.skiphidden = True
idef = [d for d in fe.InstanceDefinitions][0]
kids = {r["name"] for r in rr.block_definition(fe, Te, str(idef.Id), opt, {}, {})}
check(kids == {"child_by_parent"}, "block children with skiphidden: %s" % kids)

# By Parent
inst = [r for r in rr.iter_objects(fe, rr.Options(), Te) if r["name"] == "instance_0"][0]
child = [r for r in rr.block_definition(fe, Te, str(idef.Id), rr.Options(), {}, {}) if r["name"] == "child_by_parent"][0]
res = rr.apply_parent(child, inst)
check(res["display"][:3] == (1.0, 0.0, 0.0) and res["material"] == "Бетон", "by parent: %s %s" % (res["display"], res["material"]))
check(rr.uses_parent(fe, Te, str(idef.Id)), "uses_parent")

# допуск кривых
c = src["periodic_curve"]
n_fine, n_coarse = len(rr.sample_curve(c, 0.01)), len(rr.sample_curve(c, 50.0))
check(n_fine > n_coarse, "curve tolerance: %d vs %d" % (n_fine, n_coarse))

if FAIL:
    print("FAILED (%d):" % len(FAIL))
    for x in FAIL:
        print("  " + x)
    sys.exit(1)
print("test_read: OK")

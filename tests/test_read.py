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

# допуск кривых: фактическое максимальное отклонение полилинии от кривой (плотная выборка), не только число вершин
def _max_dev(curve, poly):
    dom = curve.Domain
    worst = 0.0
    for t in np.linspace(dom.T0, dom.T1, 2001):
        q = curve.PointAt(t)
        p = np.array([q.X, q.Y, q.Z])
        best = 1e300
        for a, b in zip(poly[:-1], poly[1:]):
            ab = b - a
            L = float(np.dot(ab, ab))
            u = 0.0 if L == 0 else min(1.0, max(0.0, float(np.dot(p - a, ab)) / L))
            best = min(best, float(np.linalg.norm(p - (a + u * ab))))
        worst = max(worst, best)
    return worst
for nm in ("Сплайн", "Дуга", "Составная кривая"):
    cc = [o.Geometry for o in f.Objects if o.Attributes.Name == nm][0]
    for tol in (0.5, 5.0, 50.0):
        poly = rr.sample_curve(cc, tol)
        dev = _max_dev(cc, poly)
        check(dev <= tol * 1.01, "curve tolerance %s tol=%g: real deviation %g" % (nm, tol, dev))

# кривые обрезки: при развороте U направление обхода петли сохраняется (внешняя — против часовой)
def _signed_area(loop):
    pts = [pt for c in loop for pt in c["cv"]]
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
fd = {"l": [{"t": "Outer", "c": [
    {"o": 2, "k": [0, 1], "p": [[1, 1, 1], [9, 1, 1]], "r": False},
    {"o": 2, "k": [0, 1], "p": [[9, 1, 1], [9, 9, 1]], "r": False},
    {"o": 2, "k": [0, 1], "p": [[9, 9, 1], [1, 9, 1]], "r": False},
    {"o": 2, "k": [0, 1], "p": [[1, 9, 1], [1, 1, 1]], "r": False}]}]}
for rev in (False, True):
    loops = rr.face_profile_loops(fd, rev, (0.0, 10.0), 0.01)
    check(_signed_area(loops[0]) > 0, "trim loop orientation after reverse=%s" % rev)

# допуск обрезки — в пространстве модели (замечание проверки 0.3.0: 20,78 мм при 0,1 мм).
# Плоскость S(u, v) = (1000u, 1000v, 0) мм, четверть окружности радиуса 0,4 в UV (рациональная, степень 2).
import numpy as _np  # noqa: E402
_r, _c = 0.4, 0.5
_w = 2 ** -0.5
quarter = [[_c + _r, _c, 1.0], [_c + _r, _c + _r, _w], [_c, _c + _r, 1.0]]
plane = {"cv": _np.array([[[0, 0, 0], [1000, 0, 0]], [[0, 1000, 0], [1000, 1000, 0]]], dtype=float),
         "w": _np.ones((2, 2)), "order_u": 2, "order_v": 2, "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1]}
S = rr.surface_evaluator(plane)


def _max_dev_mm(poly_uv):
    """Наибольшее расстояние от точек дуги (в мм) до ломаной (плоскость линейна — ломаная прямая и в 3D)."""
    P = _np.array([S(u, v) for u, v in poly_uv])
    worst = 0.0
    for t in _np.linspace(0.0, _np.pi / 2, 2001):
        q = _np.array(S(_c + _r * _np.cos(t), _c + _r * _np.sin(t)))
        best = 1e30
        for a, b in zip(P[:-1], P[1:]):
            ab = b - a
            s_ = min(max(float((q - a) @ ab) / float(ab @ ab), 0.0), 1.0)
            best = min(best, float(_np.linalg.norm(q - (a + s_ * ab))))
        worst = max(worst, best)
    return worst


for tol in (0.1, 0.01):
    pts = rr._sample_trim(quarter, [0, 0, 1, 1], 3, tol, S)
    dev = _max_dev_mm(pts)
    check(dev <= tol * 1.0001, "trim tolerance in model space: tol %g mm -> %.4f mm (%d points)" % (tol, dev, len(pts)))
check(_max_dev_mm(rr._sample_trim(quarter, [0, 0, 1, 1], 3, 0.1)) > 1.0, "UV-only sampling must be coarser")

if FAIL:
    print("FAILED (%d):" % len(FAIL))
    for x in FAIL:
        print("  " + x)
    sys.exit(1)
print("test_read: OK")

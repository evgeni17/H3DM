# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Файл пограничных случаев для тестов (только rhino3dm, без Rhino):
    python tests/make_edgecases.py  ->  tests/fixtures/h3dm_edgecases_v001.3dm

Содержит: периодическую замкнутую кривую и периодическую поверхность, коллизии имён (кириллица/латиница),
коллизию ключей User Text после префикса, длинные числовые id, блок с объектом By Parent и объектом на выключенном слое,
облако точек вместе с сеткой с цветами вершин, текстовые метки на скрытом/заблокированном слое и скрытый объект.
"""
import math
import os

import rhino3dm as r

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "h3dm_edgecases_v001.3dm")


def layer(f, path, color=(0, 0, 0, 255), visible=True, locked=False):
    parent = None
    idx = -1
    for i, name in enumerate(path.split("::")):
        full = "::".join(path.split("::")[:i + 1])
        found = [l for l in f.Layers if l.FullPath == full]
        if found:
            parent = found[0]
            idx = parent.Index
            continue
        L = r.Layer()
        L.Name = name
        L.Color = color
        if parent is not None:
            L.ParentLayerId = parent.Id
        if full == path:
            L.Visible = visible
            L.Locked = locked
        idx = f.Layers.Add(L)
        parent = f.Layers.FindIndex(idx)
    return idx


def attrs(li, name, ut=None):
    a = r.ObjectAttributes()
    a.LayerIndex = li
    a.Name = name
    for k, v in (ut or {}).items():
        a.SetUserString(k, v)
    return a


def quad(x, y, z=0.0, s=100.0):
    m = r.Mesh()
    for p in ((x, y, z), (x + s, y, z), (x + s, y + s, z), (x, y + s, z)):
        m.Vertices.Add(*p)
    m.Faces.AddFace(0, 1, 2, 3)
    return m


def build():
    f = r.File3dm()
    f.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
    L_vis = layer(f, "Видимый", (0, 0, 0, 255))
    L_hid = layer(f, "Скрытый", (0, 0, 0, 255), visible=False)
    L_lock = layer(f, "Заблокированный", (0, 0, 0, 255), locked=True)
    L_win = layer(f, "Окна", (0, 0, 255, 255))

    # материалы: 0 Бетон, 1 Стекло; слой «Окна» — стекло
    for name, col in (("Бетон", (150, 150, 150, 255)), ("Стекло", (120, 180, 220, 255))):
        m = r.Material()
        m.Name = name
        m.DiffuseColor = col
        f.Materials.Add(m)
    lw = f.Layers.FindIndex(L_win)
    lw.RenderMaterialIndex = 1

    # 1) периодическая замкнутая кривая степени 3 (8 CV)
    pts = [r.Point3d(1000 * math.cos(a), 1000 * math.sin(a), 0) for a in [i * 2 * math.pi / 8 for i in range(8)]]
    pc = r.NurbsCurve.Create(True, 3, pts)
    f.Objects.AddCurve(pc, attrs(L_vis, "periodic_curve"))

    # 2) поверхность с периодическими (незажатыми) узлами по U: замкнутая трубка
    nu, nv, ou, ov = 7, 4, 4, 4
    s = r.NurbsSurface.Create(3, False, ou, ov, nu, nv)
    for i in range(nu + ou - 2):
        s.KnotsU[i] = float(i)          # равномерные незажатые узлы
    for i, k in enumerate([0, 0, 0, 1, 1, 1]):
        s.KnotsV[i] = float(k)
    ring = [(2000 + 300 * math.cos(a), 300 * math.sin(a)) for a in [i * 2 * math.pi / (nu - 3) for i in range(nu - 3)]]
    ring = ring + ring[:3]              # последние order-1 CV повторяют первые — периодичность
    for i in range(nu):
        for j in range(nv):
            s.Points[i, j] = r.Point4d(ring[i][0], ring[i][1], j * 300.0, 1.0)
    b = r.Brep.CreateFromSurface(s)
    f.Objects.AddBrep(b, attrs(L_vis, "periodic_tube"))

    # 3) User Text: коллизия после префикса и числовые значения
    f.Objects.AddMesh(quad(0, 2000), attrs(L_vis, "usertext", {
        "name": "first", "ut_name": "second", "id": "123456789", "code": "007", "big": "12345678901",
        "ratio": "0.25", "count": "42"}))

    # 4) коллизии имён: кириллица и уже латинские имена
    for i, (path, nm) in enumerate((("Корень::Еда", "Еда"), ("Корень::Эда", "Эда"),
                                    ("Koren::Eda", "Eda"), ("Koren::Eda_2", "Eda_2"))):
        li = layer(f, path)
        f.Objects.AddMesh(quad(i * 200, 3000), attrs(li, nm))

    # 5) блок: дочерний объект By Parent и скрытый дочерний объект
    child = attrs(L_win, "child_by_parent")
    child.ColorSource = r.ObjectColorSource.ColorFromParent
    child.MaterialSource = r.ObjectMaterialSource.MaterialFromParent
    # дочерний объект на выключенном слое: Rhino не показывает его во вставках
    hidden_child = attrs(L_hid, "child_hidden")
    idef = f.InstanceDefinitions.Add("Блок_родитель", "", "", "", r.Point3d(0, 0, 0),
                                     (quad(0, 0), quad(200, 0)), (child, hidden_child))
    did = f.InstanceDefinitions.FindIndex(idef).Id
    for k, (col, mat) in enumerate((((255, 0, 0, 255), 0), ((0, 255, 0, 255), 1))):
        a = attrs(L_vis, "instance_%d" % k)
        a.ObjectColor = col
        a.ColorSource = r.ObjectColorSource.ColorFromObject
        a.MaterialIndex = mat
        a.MaterialSource = r.ObjectMaterialSource.MaterialFromObject
        f.Objects.AddInstanceObject(r.InstanceReference(did, r.Transform.Translation(0, 4000 + k * 500, 0)), a)

    # 6) облако точек с цветами + сетка с цветами вершин в одном файле
    cloud = r.PointCloud()
    for i in range(10):
        for j in range(10):
            cloud.Add(r.Point3d(5000 + i * 10, j * 10, 0), (i * 28, j * 28, 128, 255))
    f.Objects.AddPointCloud(cloud, attrs(L_vis, "cloud", {"scan": "A1"}))
    vm = quad(6000, 0)
    for c in ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)):
        vm.VertexColors.Add(c[0], c[1], c[2])
    f.Objects.AddMesh(vm, attrs(L_vis, "vertex_colors"))

    # 7) фильтры: объекты и метки на скрытом/заблокированном слое, скрытый объект на видимом слое
    for li, tag in ((L_hid, "on_hidden_layer"), (L_lock, "on_locked_layer")):
        f.Objects.AddMesh(quad(7000, 0), attrs(li, tag))
        f.Objects.AddTextDot(tag, r.Point3d(7000, 0, 0), attrs(li, tag))
    hid = attrs(L_vis, "hidden_object")
    hid.Visible = False
    f.Objects.AddMesh(quad(8000, 0), hid)
    hid2 = attrs(L_vis, "hidden_dot")
    hid2.Visible = False
    f.Objects.AddTextDot("hidden_dot", r.Point3d(8000, 0, 0), hid2)
    f.Objects.AddTextDot("visible_dot", r.Point3d(9000, 0, 0), attrs(L_vis, "visible_dot"))
    return f


if __name__ == "__main__":
    f = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("written" if f.Write(OUT, 8) else "FAILED", OUT)

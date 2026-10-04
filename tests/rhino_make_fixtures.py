# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тестовые файлы H3DM — запускать в Rhino 8 (ScriptEditor, Python 3) в ПУСТОМ документе.

Создаёт объекты всех типов, слои с кириллицей и иерархией, группы, вложенные блоки, User Text,
материалы, Document User Text, сетки отображения; сохраняет в tests/fixtures:
  h3dm_fixture_v001.3dm        — с render mesh
  h3dm_fixture_small_v001.3dm  — без render mesh (как Save Small)
Перед публикацией файлы очищаются от автора и путей: python tests/sanitize_3dm.py in.3dm out.3dm
"""
import os

import Rhino
import Rhino.Geometry as G
import System

try:
    doc = __rhino_doc__  # noqa: F821  (Rhino MCP)
except NameError:
    doc = Rhino.RhinoDoc.ActiveDoc

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures") if "__file__" in globals() else \
    os.path.join(os.getcwd(), "fixtures")
D = System.Drawing.Color
P = G.Point3d


def layer(path, color):
    idx = doc.Layers.FindByFullPath(path, -1)
    if idx >= 0:
        return idx
    parts = path.split("::")
    parent = System.Guid.Empty
    if len(parts) > 1:
        parent = doc.Layers[layer("::".join(parts[:-1]), color)].Id
    L = Rhino.DocObjects.Layer()
    L.Name, L.Color, L.ParentLayerId = parts[-1], color, parent
    return doc.Layers.Add(L)


def mat(name, color, transp=0.0):
    i = doc.Materials.Find(name, True)
    if i >= 0:
        return i
    m = Rhino.DocObjects.Material()
    m.Name, m.DiffuseColor, m.Transparency = name, color, transp
    return doc.Materials.Add(m)


def attrs(li, name, ut=None, color=None, mi=None):
    a = Rhino.DocObjects.ObjectAttributes()
    a.LayerIndex, a.Name = li, name
    if color is not None:
        a.ObjectColor, a.ColorSource = color, Rhino.DocObjects.ObjectColorSource.ColorFromObject
    if mi is not None:
        a.MaterialIndex, a.MaterialSource = mi, Rhino.DocObjects.ObjectMaterialSource.MaterialFromObject
    for k, v in (ut or {}).items():
        a.SetUserString(k, v)
    return a


doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
m_beton = mat("Бетон", D.FromArgb(150, 150, 150))
m_glass = mat("Стекло", D.FromArgb(120, 180, 220), 0.6)
L_pan = layer("Фасад::Панели", D.FromArgb(200, 80, 60))
L_win = layer("Фасад::Окна", D.FromArgb(60, 120, 200))
lw = doc.Layers[L_win]
lw.RenderMaterialIndex = m_glass
doc.Layers.Modify(lw, L_win, True)
L_col = layer("Конструкции::Колонны", D.FromArgb(90, 90, 90))
L_misc = layer("Прочее::СЦЮ ПА1", D.FromArgb(0, 150, 0))
L_axis = layer("AXIS", D.FromArgb(255, 0, 0))
L_txt = layer("Аннотации", D.FromArgb(0, 0, 0))

# Brep: необрезанные грани, плоская с отверстием, булева разность, обрезанная сфера; Extrusion
box = G.Brep.CreateFromBox(G.BoundingBox(P(0, 0, 0), P(3000, 200, 3000)))
id_box = doc.Objects.AddBrep(box, attrs(L_pan, "Панель_01", {"id": "P-001", "thickness": "200", "category": "Wall", "Марка": "П-1"},
                                        D.FromArgb(220, 120, 40), m_beton))
rect = G.Rectangle3d(G.Plane(P(4000, 0, 0), G.Vector3d.XAxis, G.Vector3d.ZAxis), 2000, 3000).ToNurbsCurve()
hole = G.Circle(G.Plane(P(5000, 0, 1500), G.Vector3d.XAxis, G.Vector3d.ZAxis), 400).ToNurbsCurve()
id_pl = doc.Objects.AddBrep(G.Brep.CreatePlanarBreps([rect, hole], 0.01)[0],
                            attrs(L_pan, "Панель с отверстием", {"id": "P-002", "thickness": "150"}))
b2 = G.Brep.CreateFromBox(G.BoundingBox(P(7000, 0, 0), P(9000, 1000, 1000)))
cy = G.Brep.CreateFromCylinder(G.Cylinder(G.Circle(G.Plane(P(8000, 500, -100), G.Vector3d.ZAxis), 300), 1200), True, True)
doc.Objects.AddBrep(G.Brep.CreateBooleanDifference(b2, cy, 0.01)[0], attrs(L_col, "Колонна_вырез", {"id": "C-001", "category": "Column"}))
sph = G.Brep.CreateFromSphere(G.Sphere(P(11000, 500, 500), 500))
tr = sph.Trim(G.Plane(P(11000, 500, 700), G.Vector3d.ZAxis), 0.01)
doc.Objects.AddBrep(tr[0] if tr else sph, attrs(L_misc, "Купол", {"category": "Dome"}))
ext = G.Extrusion.Create(G.Circle(G.Plane(P(13000, 500, 0), G.Vector3d.ZAxis), 150).ToNurbsCurve(), 3000, True)
doc.Objects.AddExtrusion(ext, attrs(L_col, "Колонна_круглая", {"id": "C-002", "category": "Column", "thickness": "300"}))

# Mesh с цветами вершин, SubD
m = G.Mesh()
for (x, y, z) in [(15000, 0, 0), (16000, 0, 0), (16000, 1000, 0), (15000, 1000, 0), (15500, 500, 500)]:
    m.Vertices.Add(x, y, z)
for f in ((0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)):
    m.Faces.AddFace(*f)
for c in (D.Red, D.Green, D.Blue, D.Yellow, D.White):
    m.VertexColors.Add(c)
m.Normals.ComputeNormals()
doc.Objects.AddMesh(m, attrs(L_misc, "Сетка_пирамида", {"category": "Mesh"}))
sd = G.SubD.CreateFromMesh(G.Mesh.CreateFromBox(G.BoundingBox(P(17000, 0, 0), P(18000, 1000, 1000)), 1, 1, 1))
doc.Objects.AddSubD(sd, attrs(L_misc, "SubD_куб"))

# кривые
doc.Objects.AddLine(G.Line(P(0, -2000, 0), P(20000, -2000, 0)), attrs(L_axis, "Ось_А"))
doc.Objects.AddArc(G.Arc(P(0, -3000, 0), P(1000, -3500, 0), P(2000, -3000, 0)), attrs(L_axis, "Дуга"))
doc.Objects.AddPolyline(G.Polyline([P(3000, -3000, 0), P(4000, -3500, 0), P(5000, -3000, 0), P(6000, -3500, 0)]), attrs(L_axis, "Полилиния"))
doc.Objects.AddCurve(G.NurbsCurve.Create(False, 3, [P(7000, -3000, 0), P(7500, -4000, 300), P(8500, -2500, 0), P(9000, -3500, 0)]),
                     attrs(L_axis, "Сплайн"))
pc = G.PolyCurve()
pc.Append(G.Line(P(10000, -3000, 0), P(11000, -3000, 0)))
pc.Append(G.Arc(P(11000, -3000, 0), G.Vector3d.XAxis, P(11500, -2500, 0)))
doc.Objects.AddCurve(pc, attrs(L_axis, "Составная кривая"))

# точки, облако, аннотации
doc.Objects.AddPoint(P(500, 500, 3500), attrs(L_txt, "Отметка +3.500", {"elevation": "3500", "Тип": "Высотная отметка"}))
cloud = G.PointCloud()
for i in range(10):
    for j in range(10):
        cloud.Add(P(19000 + i * 100, j * 100, 0), D.FromArgb(i * 25, j * 25, 100))
doc.Objects.AddPointCloud(cloud, attrs(L_misc, "Облако"))
doc.Objects.AddTextDot(G.TextDot("Марка П-1", P(1500, -200, 3200)), attrs(L_txt, "Марка", {"ref": "P-001"}))
ds = doc.DimStyles.Current
te = G.TextEntity.Create("Фасад в осях 1-5\nМФЗ", G.Plane(P(0, -1000, 0), G.Vector3d.XAxis, G.Vector3d.YAxis), ds, False, 0, 0)
te.TextHeight = 250
doc.Objects.AddText(te, attrs(L_txt, "Надпись"))
dim = G.LinearDimension.Create(G.AnnotationType.Aligned, ds, G.Plane.WorldXY, G.Vector3d.XAxis,
                               P(0, -1500, 0), P(3000, -1500, 0), P(1500, -1800, 0), 0)
doc.Objects.AddLinearDimension(dim, attrs(L_txt, "Размер"))
doc.Objects.AddLeader(G.Leader.Create("Выноска", G.Plane.WorldXY, ds, [P(5000, -1200, 0), P(5500, -800, 0), P(6000, -800, 0)]),
                      attrs(L_txt, "Выноска"))
doc.Groups.Add("Группа фасад", [id_box, id_pl])

# свет
lt = G.Light()
lt.LightStyle, lt.Location, lt.Diffuse, lt.Intensity, lt.Name = G.LightStyle.WorldPoint, P(5000, 3000, 4000), D.FromArgb(255, 240, 200), 0.8, "Лампа"
doc.Lights.Add(lt)

# блоки: окно (рама + стекло) x3 и вложенный блок «пара окон» с поворотом
frame = G.Brep.CreateFromBox(G.BoundingBox(P(0, 0, 0), P(1200, 100, 1500)))
glass = G.Brep.CreateFromBox(G.BoundingBox(P(50, 40, 50), P(1150, 60, 1450)))
a_gl = attrs(L_win, "Стекло", {"part": "glass"})
a_gl.MaterialSource = Rhino.DocObjects.ObjectMaterialSource.MaterialFromLayer
win = doc.InstanceDefinitions.Add("Окно_тип1", "окно 1200x1500", P(0, 0, 0), [frame, glass],
                                  [attrs(L_win, "Рама", {"part": "frame"}, None, m_beton), a_gl])
for k, x in enumerate((0, 1500, 3000)):
    doc.Objects.AddInstanceObject(win, G.Transform.Translation(x, -6000, 900), attrs(L_win, "Окно %d" % (k + 1), {"id": "W-%03d" % (k + 1)}))
wid = doc.InstanceDefinitions[win].Id
pair = doc.InstanceDefinitions.Add("Блок_окон", "", P(0, 0, 0),
                                   [G.InstanceReferenceGeometry(wid, G.Transform.Identity),
                                    G.InstanceReferenceGeometry(wid, G.Transform.Translation(1500, 0, 0))],
                                   [attrs(L_win, "a"), attrs(L_win, "b")])
doc.Objects.AddInstanceObject(pair, G.Transform.Translation(0, -9000, 0) * G.Transform.Rotation(0.3, G.Vector3d.ZAxis, P.Origin),
                              attrs(L_win, "Пара окон"))

doc.Strings.SetString("Проект", "МФЗ тест")
doc.Strings.SetString("stage", "P")

mp = G.MeshingParameters.Default
for o in doc.Objects:
    o.CreateMeshes(G.MeshType.Render, mp, False)

os.makedirs(OUT, exist_ok=True)
opt = Rhino.FileIO.FileWriteOptions()
opt.FileVersion, opt.WriteGeometryOnly, opt.SuppressAllInput = 8, False, True
opt.IncludeRenderMeshes = True
print(doc.WriteFile(os.path.join(OUT, "h3dm_fixture_v001.3dm"), opt))
opt.IncludeRenderMeshes = False
print(doc.WriteFile(os.path.join(OUT, "h3dm_fixture_small_v001.3dm"), opt))

# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Запись .3dm через rhino3dm (без hou): слои, материалы, группы, объекты с атрибутами.

Все координаты — уже в системе и единицах файла Rhino (float64): обратный глобальный трансформ
считает слой Houdini (sop_export). Узлы NURBS приходят в виде Houdini (полный вектор: cv + order),
Rhino хранит cv + order - 2 — крайние отбрасываются. Замкнутые (wrap) кривые/поверхности Houdini
разворачиваются в периодические: к CV добавляются первые order-1, узлы — как есть.
"""
import os
import uuid

import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()

UNITS = {"mm": ("Millimeters", 1e-3), "cm": ("Centimeters", 1e-2), "m": ("Meters", 1.0),
         "in": ("Inches", 0.0254), "ft": ("Feet", 0.3048)}


def _r():
    import rhino3dm
    return rhino3dm


def layer_material_ok(material, layer_material, material_color=None):
    """Материал объекта совпадает с материалом его слоя (и не задан таблицей ноды) -> «по слою»."""
    return bool(material) and material == layer_material and material_color is None


def _rgba255(c, a=1.0):
    """(r, g, b[, a]) 0..1 -> (r, g, b, a) 0..255."""
    c = list(c) + [a] * (4 - len(c))
    return tuple(int(round(min(max(float(x), 0.0), 1.0) * 255)) for x in c[:4])


class Writer(object):
    """Собирает File3dm. Таблицы заполняются по требованию (слой создаётся при первом объекте на нём)."""

    def __init__(self, units="Millimeters", abs_tol=0.001, angle_tol_deg=1.0, layer_props=None, mat_props=None):
        r = _r()
        self.f = r.File3dm()
        s = self.f.Settings
        s.ModelUnitSystem = getattr(r.UnitSystem, units)
        s.ModelAbsoluteTolerance = float(abs_tol)
        s.ModelAngleToleranceDegrees = float(angle_tol_deg)
        self._layers = {}            # полный путь (исходные имена, "::") -> индекс
        self._mats = {}              # имя -> индекс
        self._groups = {}            # имя -> индекс
        self.layer_props = layer_props or {}     # путь -> {'color', 'visible', 'locked', 'user_text'}
        self.mat_props = mat_props or {}         # имя -> {'diffuse', 'transparency', ...}
        self.counts = {}
        self.warnings = []
        self._sink = None            # при сборке определения блока объекты копятся здесь, а не в таблице
        self._layer_materials = set()
        self._defs = {}              # ключ определения -> id

    # ------------------------------------------------------------ таблицы
    def layer(self, path):
        """Слой по полному пути с исходными именами ('Фасад::Панели'); родители создаются сами."""
        path = path or "Default"
        if path in self._layers:
            return self._layers[path]
        r = _r()
        segs = path.split("::")
        parent = "::".join(segs[:-1])
        L = r.Layer()
        L.Name = segs[-1]
        if parent:
            pidx = self.layer(parent)
            L.ParentLayerId = self.f.Layers[pidx].Id
        p = self.layer_props.get(path) or {}
        if p.get("material"):
            try:
                L.RenderMaterialIndex = self.material(p["material"])
            except Exception:
                pass
        if p.get("color"):
            L.Color = _rgba255(p["color"])
        if "visible" in p:
            L.Visible = bool(p["visible"])
        if "locked" in p:
            L.Locked = bool(p["locked"])
        for k, v in (p.get("user_text") or {}).items():
            L.SetUserString(str(k), str(v))
        idx = self.f.Layers.Add(L)
        self._layers[path] = idx
        return idx

    def layer_color(self, path):
        p = self.layer_props.get(path or "Default") or {}
        return p.get("color")

    def material(self, name, color=None, transparency=None):
        if not name:
            return -1
        if name in self._mats:
            return self._mats[name]
        r = _r()
        m = r.Material()
        m.Name = name
        p = self.mat_props.get(name) or {}
        col = color if color is not None else p.get("diffuse")
        if col is not None:
            m.DiffuseColor = _rgba255(col)
        tr = transparency if transparency is not None else p.get("transparency")
        if tr is not None:
            m.Transparency = float(tr)
        for key, attr in (("shine", "Shine"), ("reflectivity", "Reflectivity"), ("ior", "IndexOfRefraction")):
            if p.get(key) is not None:
                try:
                    setattr(m, attr, float(p[key]))
                except Exception:
                    pass
        idx = self.f.Materials.Add(m)
        self._mats[name] = idx
        return idx

    def group(self, name):
        if name in self._groups:
            return self._groups[name]
        r = _r()
        g = r.Group()
        g.Name = name
        self.f.Groups.Add(g)
        idx = len(self.f.Groups) - 1
        self._groups[name] = self.f.Groups[idx].Index
        return self._groups[name]

    def doc_strings(self, d):
        for k, v in (d or {}).items():
            self.f.Strings[str(k)] = str(v)

    # ------------------------------------------------------------ атрибуты
    def attributes(self, layer="", name="", color=None, material="", groups=(), user_text=None, obj_id=None,
                   material_color=None, material_transparency=None):
        """color: (r,g,b[,a]) 0..1 или None. Цвет, равный цвету слоя, пишется «по слою»."""
        r = _r()
        a = r.ObjectAttributes()
        a.LayerIndex = self.layer(layer)
        if name:
            a.Name = name
        if color is not None:
            lc = self.layer_color(layer)
            if lc is not None and all(abs(float(x) - float(y)) < 1.5 / 255 for x, y in zip(color[:3], lc[:3])):
                a.ColorSource = r.ObjectColorSource.ColorFromLayer
            else:
                a.ColorSource = r.ObjectColorSource.ColorFromObject
                a.ObjectColor = _rgba255(color)
        lmat = (self.layer_props.get(layer or "Default") or {}).get("material") or ""
        if layer_material_ok(material, lmat, material_color):
            if lmat:
                self.material(lmat)                 # материал слоя должен быть в таблице
            self._layer_materials.add(layer or "Default")
            a.MaterialSource = r.ObjectMaterialSource.MaterialFromLayer
        elif material:
            a.MaterialIndex = self.material(material, material_color, material_transparency)
            a.MaterialSource = r.ObjectMaterialSource.MaterialFromObject
        for g in groups or ():
            a.AddToGroup(self.group(g))
        for k, v in (user_text or {}).items():
            if k:
                a.SetUserString(str(k), "" if v is None else str(v))
        if obj_id:
            try:
                a.Id = uuid.UUID(str(obj_id))
            except Exception:
                pass
        return a

    def _count(self, kind):
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def _add(self, kind, geom, attrs, adder):
        if self._sink is not None:
            self._sink.append((geom, attrs))
            self._count("block_" + kind)
            return None
        oid = adder(geom, attrs)
        self._count(kind)
        return oid

    # ------------------------------------------------------------ блоки
    def begin_definition(self):
        self._sink = []

    def end_definition(self, key, name, description=""):
        """Записать собранные объекты как определение блока. -> id определения."""
        r = _r()
        items, self._sink = self._sink or [], None
        geoms = tuple(g for g, _ in items)
        attrs = tuple(a for _, a in items)
        idx = self.f.InstanceDefinitions.Add(name, description, "", "", r.Point3d(0, 0, 0), geoms, attrs)
        if idx is None or idx < 0:
            self.warnings.append("block '%s' could not be written" % name)
            return None
        did = self.f.InstanceDefinitions[idx].Id
        self._defs[key] = did
        self._count("block_definition")
        return did

    def add_instance(self, key, xform, attrs):
        """Вставка блока: xform — 4x4 (столбцовые векторы, единицы файла)."""
        r = _r()
        did = self._defs.get(key)
        if did is None:
            return None
        t = r.Transform.Identity()
        X = np.asarray(xform, dtype=np.float64).reshape(4, 4)
        for i in range(4):
            for j in range(4):
                setattr(t, "M%d%d" % (i, j), float(X[i, j]))
        return self._add("instance", r.InstanceReference(did, t), attrs, self.f.Objects.AddInstanceObject)

    # ------------------------------------------------------------ геометрия
    def add_mesh(self, V, faces, attrs, colors=None, normals=None):
        """V (n,3) float64; faces — кортежи по 3–4 индекса (обход Rhino, против часовой)."""
        r = _r()
        faces, dropped = _clean_faces(np.asarray(V, dtype=np.float64), faces)
        if dropped:
            self.counts["degenerate_faces"] = self.counts.get("degenerate_faces", 0) + dropped
        m = r.Mesh()
        mv = m.Vertices
        # AddPoint3d хранит double; Add(x, y, z) округляет до float (у далёких моделей — до сантиметров)
        add = mv.AddPoint3d
        for x, y, z in np.asarray(V, dtype=np.float64).tolist():
            add(x, y, z)
        mf = m.Faces
        for fc in faces:
            if len(fc) == 3:
                mf.AddFace(fc[0], fc[1], fc[2])
            else:
                mf.AddFace(fc[0], fc[1], fc[2], fc[3])
        try:
            culled = m.Faces.CullDegenerateFaces()       # нулевые грани (совпавшие вершины) Rhino считает ошибкой
            if culled:
                self.counts["degenerate_faces"] = self.counts.get("degenerate_faces", 0) + int(culled)
        except Exception:
            pass
        if colors is not None:
            vc = m.VertexColors
            for c in np.asarray(colors, dtype=np.float64).tolist():
                vc.Add(*[int(round(min(max(x, 0.0), 1.0) * 255)) for x in c[:3]])
        if normals is not None:
            try:
                nl = m.Normals
                for n in np.asarray(normals, dtype=np.float64).tolist():
                    nl.Add(*n)
            except Exception:
                pass
        return self._add("mesh", m, attrs, self.f.Objects.AddMesh)

    def add_polyline(self, pts, closed, attrs):
        r = _r()
        pts = np.asarray(pts, dtype=np.float64).tolist()
        if closed and pts:
            pts = pts + [pts[0]]
        pl = r.Polyline(0)
        for x, y, z in pts:
            pl.Add(x, y, z)
        crv = r.PolylineCurve(pl) if hasattr(r, "PolylineCurve") else pl.ToNurbsCurve()
        return self._add("polyline", crv, attrs, self.f.Objects.AddCurve)

    @staticmethod
    def _rhino_knots(full):
        return [float(k) for k in list(full)[1:-1]]

    def nurbs_curve(self, cv, w, order, knots_full, closed=False):
        r = _r()
        cv = np.asarray(cv, dtype=np.float64).reshape(-1, 3)
        w = np.asarray(w, dtype=np.float64).reshape(-1)
        if closed:
            cv = np.concatenate([cv, cv[:order - 1]])
            w = np.concatenate([w, w[:order - 1]])
        n = len(cv)
        kn = self._rhino_knots(knots_full)
        if len(kn) != n + order - 2:
            raise ValueError("curve knots: %d for %d CVs of order %d" % (len(kn), n, order))
        rational = bool(np.any(np.abs(w - 1.0) > 1e-12))
        c = r.NurbsCurve(3, rational, int(order), n)
        for i in range(n):
            x, y, z = cv[i]
            c.Points[i] = r.Point4d(x * w[i], y * w[i], z * w[i], w[i]) if rational else r.Point4d(x, y, z, 1.0)
        for i, k in enumerate(kn):
            c.Knots[i] = k
        return c

    def add_nurbs_curve(self, cv, w, order, knots_full, attrs, closed=False):
        c = self.nurbs_curve(cv, w, order, knots_full, closed)
        if not c.IsValid:
            self.warnings.append("invalid NURBS curve skipped")
            return None
        return self._add("curve", c, attrs, self.f.Objects.AddCurve)

    def nurbs_surface(self, cv, w, order_u, order_v, knots_u_full, knots_v_full, wrap_u=False, wrap_v=False):
        """cv (nv, nu, 3) — строки по V, как вершины NURBMesh Houdini."""
        r = _r()
        cv = np.asarray(cv, dtype=np.float64)
        w = np.asarray(w, dtype=np.float64)
        if wrap_u:
            cv = np.concatenate([cv, cv[:, :order_u - 1]], axis=1)
            w = np.concatenate([w, w[:, :order_u - 1]], axis=1)
        if wrap_v:
            cv = np.concatenate([cv, cv[:order_v - 1]], axis=0)
            w = np.concatenate([w, w[:order_v - 1]], axis=0)
        nv, nu = cv.shape[:2]
        ku, kv = self._rhino_knots(knots_u_full), self._rhino_knots(knots_v_full)
        if len(ku) != nu + order_u - 2 or len(kv) != nv + order_v - 2:
            raise ValueError("surface knots do not match the control net")
        rational = bool(np.any(np.abs(w - 1.0) > 1e-12))
        s = r.NurbsSurface.Create(3, rational, int(order_u), int(order_v), nu, nv)
        for j in range(nv):
            for i in range(nu):
                x, y, z = cv[j, i]
                ww = w[j, i] if rational else 1.0
                s.Points[i, j] = r.Point4d(x * ww, y * ww, z * ww, ww)
        for i, k in enumerate(ku):
            s.KnotsU[i] = k
        for i, k in enumerate(kv):
            s.KnotsV[i] = k
        return s

    def add_surface(self, cv, w, order_u, order_v, knots_u_full, knots_v_full, attrs, wrap_u=False, wrap_v=False):
        r = _r()
        s = self.nurbs_surface(cv, w, order_u, order_v, knots_u_full, knots_v_full, wrap_u, wrap_v)
        b = r.Brep.CreateFromSurface(s) if s.IsValid else None
        if b is None or not b.IsValid:
            self.warnings.append("invalid NURBS surface skipped")
            return None
        return self._add("surface", b, attrs, self.f.Objects.AddBrep)

    def add_trimmed_plane(self, plane, curves, attrs):
        """plane = (начало, ось X, ось Y); curves — сегменты внешней петли {'cv','w','order','knots'}."""
        r = _r()
        o, x, y = [np.asarray(v, dtype=np.float64) for v in plane]
        pl = r.Plane(r.Point3d(*o), r.Vector3d(*x), r.Vector3d(*y))
        loop = r.PolyCurve()
        for c in curves:
            loop.Append(self.nurbs_curve(c["cv"], c["w"], c["order"], c["knots"]))
        b = r.Brep.CreateTrimmedPlane(pl, loop)
        if b is None or not b.IsValid:
            self.warnings.append("trimmed planar face could not be built")
            return None
        return self._add("trimmed_plane", b, attrs, self.f.Objects.AddBrep)

    def add_source(self, geom, scale, attrs, xform=None):
        """Исходная геометрия из файла импорта (неизменённый или целиком перенесённый объект), в единицах файла."""
        from .passthrough import source_geometry
        g = source_geometry(geom, scale, xform)
        return self._add("source", g, attrs, self.f.Objects.Add)

    def add_textdot(self, text, pt, attrs):
        r = _r()
        dot = r.TextDot(str(text), r.Point3d(*[float(x) for x in pt]))
        return self._add("textdot", dot, attrs, lambda g, a: self.f.Objects.AddTextDot(g.Text, g.Point, a))

    def add_point(self, pt, attrs):
        r = _r()
        pnt = r.Point(r.Point3d(*[float(x) for x in pt]))
        return self._add("point", pnt, attrs, lambda g, a: self.f.Objects.AddPoint(g.Location, a))

    def add_point_cloud(self, pts, attrs, colors=None):
        r = _r()
        pc = r.PointCloud()
        P = np.asarray(pts, dtype=np.float64).tolist()
        if colors is not None:
            C = [_rgba255(c) for c in np.asarray(colors, dtype=np.float64).tolist()]
            for p, c in zip(P, C):
                pc.Add(r.Point3d(*p), c)
        else:
            for p in P:
                pc.Add(r.Point3d(*p))
        return self._add("pointcloud", pc, attrs, self.f.Objects.AddPointCloud)

    # ------------------------------------------------------------ запись
    def write(self, path, version=8):
        """Атомарно: во временный файл рядом, затем замена. -> путь."""
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, ".%s.h3dm_tmp_%s.3dm" % (os.path.basename(path), uuid.uuid4().hex[:8]))
        try:
            if not self.f.Write(tmp, int(version)):
                raise IOError("rhino3dm could not write %s" % tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return path


def _clean_faces(V, faces):
    """Грани с совпадающими ПОЛОЖЕНИЯМИ вершин (не только индексами): четырёхугольник с одной парой — в
    треугольник, остальные вырожденные — прочь. Rhino считает такие сетки ошибочными. Поиск — векторно."""
    n = len(faces)
    if n == 0:
        return faces, 0
    lens = np.fromiter(map(len, faces), dtype=np.int64, count=n)
    idx = np.full((n, 4), -1, dtype=np.int64)
    for k in (3, 4):
        sel = np.nonzero(lens == k)[0]
        if len(sel):
            idx[sel, :k] = np.array([faces[i] for i in sel.tolist()], dtype=np.int64)
    valid = idx >= 0
    P = V[np.where(valid, idx, 0)]
    bad = np.zeros(n, dtype=bool)
    for i in range(4):
        for j in range(i + 1, 4):
            bad |= valid[:, i] & valid[:, j] & np.all(P[:, i] == P[:, j], axis=1)
    if not bad.any():
        return faces, 0
    out, dropped = [], 0
    for k, fc in enumerate(faces):
        if not bad[k]:
            out.append(fc)
            continue
        uniq = []
        for i in fc:
            if not any((V[j] == V[i]).all() for j in uniq):
                uniq.append(i)
        if len(uniq) >= 3:
            out.append(tuple(uniq))
        else:
            dropped += 1
    return out, dropped


def next_version(path):
    """Свободное имя: <stem>_v###.3dm (если путь уже кончается на _v###, номер увеличивается)."""
    import re
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    m = re.match(r"^(.*)_v(\d{3,})$", stem)
    base, num = (m.group(1), int(m.group(2))) if m else (stem, 1)
    while True:
        num += 1
        cand = os.path.join(folder, "%s_v%03d%s" % (base, num, ext or ".3dm"))
        if not os.path.exists(cand):
            return cand


def summary(path):
    """Контрольное чтение: число объектов по типам, слоёв, групп, материалов."""
    from .rhino_read import read, enum_name
    f = read(path)
    kinds = {}
    for o in f.Objects:
        k = enum_name(o.Geometry.ObjectType)
        kinds[k] = kinds.get(k, 0) + 1
    return {"objects": sum(kinds.values()), "kinds": kinds, "layers": len(f.Layers), "groups": len(f.Groups),
            "materials": len(f.Materials), "units": enum_name(f.Settings.ModelUnitSystem)}

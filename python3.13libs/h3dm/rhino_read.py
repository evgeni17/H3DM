# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Чтение .3dm через rhino3dm — без hou (тестируется обычным Python).

Здесь только данные файла: документ, таблицы (слои, материалы, группы, блоки), сводка.
Геометрия по объектам — этап 2 (iter_objects).
"""
import collections
import os

from . import ensure_vendor_path

ensure_vendor_path()

# метров в единице модели (имена членов rhino3dm.UnitSystem)
UNIT_M = {
    "None": 1.0, "Angstroms": 1e-10, "Nanometers": 1e-9, "Microns": 1e-6, "Millimeters": 1e-3,
    "Centimeters": 1e-2, "Decimeters": 0.1, "Meters": 1.0, "Dekameters": 10.0, "Hectometers": 100.0,
    "Kilometers": 1e3, "Megameters": 1e6, "Gigameters": 1e9, "Microinches": 2.54e-8, "Mils": 2.54e-5,
    "Inches": 0.0254, "Feet": 0.3048, "Yards": 0.9144, "Miles": 1609.344, "PrinterPoints": 0.0254 / 72.0,
    "PrinterPicas": 0.0254 / 6.0, "NauticalMiles": 1852.0, "AstronomicalUnits": 1.495978707e11,
    "LightYears": 9.4607304725808e15, "Parsecs": 3.08567758149137e16, "CustomUnits": 1.0, "Unset": 1.0,
}


def _r():
    import rhino3dm
    return rhino3dm


def enum_name(v):
    return str(v).split(".")[-1]


def read(path):
    """Открыть .3dm; понятная ошибка вместо None."""
    r = _r()
    if not os.path.isfile(path):
        raise IOError("File not found: %s" % path)
    f = r.File3dm.Read(path)
    if f is None:
        raise IOError("Not a readable Rhino .3dm file (or newer than rhino3dm %s): %s"
                      % (getattr(r, "__version__", "?"), path))
    return f


def color(c):
    """(r,g,b,a) 0..255 -> (r,g,b,a) 0..1."""
    return tuple(round(x / 255.0, 6) for x in tuple(c)[:4])


def user_strings(obj):
    try:
        return dict(obj.GetUserStrings()) if obj.UserStringCount else {}
    except Exception:
        return {}


def doc_info(f):
    """Свойства документа: единицы, допуски, авторы, гео-привязка."""
    s = f.Settings
    units = enum_name(s.ModelUnitSystem)
    e = s.EarthAnchorPoint
    bp = s.ModelBasePoint
    info = {
        "units": units,
        "unit_m": UNIT_M.get(units, 1.0),
        "abs_tolerance": s.ModelAbsoluteTolerance,
        "angle_tolerance_deg": s.ModelAngleToleranceDegrees,
        "rel_tolerance": s.ModelRelativeTolerance,
        "base_point": [bp.X, bp.Y, bp.Z],
        "archive_version": f.ArchiveVersion,
        "application": f.ApplicationName or "",
        "created": str(f.Created or ""),
        "created_by": f.CreatedBy or "",
        "last_edited": str(f.LastEdited or ""),
        "last_edited_by": f.LastEditedBy or "",
        "revision": f.Revision,
        "earth_anchor": {
            "set": bool(e.EarthLocationIsSet()) if callable(getattr(e, "EarthLocationIsSet", None)) else False,
            "latitude": e.EarthBasepointLatitude,
            "longitude": e.EarthBasepointLongitude,
            "elevation": e.EarthBasepointElevation,
            "model_base_point": [e.ModelBasePoint.X, e.ModelBasePoint.Y, e.ModelBasePoint.Z],
            "model_north": [e.ModelNorth.X, e.ModelNorth.Y, e.ModelNorth.Z],
            "model_east": [e.ModelEast.X, e.ModelEast.Y, e.ModelEast.Z],
            "name": e.Name or "",
        },
    }
    return info


def doc_strings(f):
    """Document User Text: {ключ: значение}."""
    out = {}
    for i in range(len(f.Strings)):
        k, v = f.Strings[i]
        out[k] = v
    return out


def layers(f):
    out = []
    for l in f.Layers:
        out.append({
            "index": l.Index, "id": str(l.Id), "name": l.Name, "full_path": l.FullPath,
            "parent_id": str(l.ParentLayerId), "color": color(l.Color), "visible": bool(l.Visible),
            "locked": bool(l.Locked), "material_index": l.RenderMaterialIndex,
            "user_text": user_strings(l),
        })
    return out


def materials(f):
    out = []
    for i, m in enumerate(f.Materials):
        out.append({
            "index": i, "id": str(m.Id), "name": m.Name or "", "diffuse": color(m.DiffuseColor),
            "transparency": m.Transparency, "shine": m.Shine, "reflectivity": m.Reflectivity,
            "ior": m.IndexOfRefraction, "emission": color(m.EmissionColor),
            "texture": _texture_file(m),
        })
    return out


def _texture_file(m):
    try:
        t = m.GetBitmapTexture()
        return t.FileName if t is not None else ""
    except Exception:
        return ""


def groups(f):
    return [{"index": g.Index, "id": str(g.Id), "name": g.Name or ""} for g in f.Groups]


def instance_definitions(f):
    out = []
    for d in f.InstanceDefinitions:
        out.append({"id": str(d.Id), "name": d.Name or "", "description": d.Description or "",
                    "objects": [str(x) for x in d.GetObjectIds()], "user_text": user_strings(d)})
    return out


def geometry_kind(g):
    """Короткое имя типа геометрии (имя класса rhino3dm)."""
    return type(g).__name__


def summary(f):
    """Сводка для File Info: объекты по типам, render mesh, обрезанные грани, кириллица."""
    from .names import has_cyrillic
    r = _r()
    kinds = collections.Counter()
    in_blocks = collections.Counter()
    brep_faces = trimmed = faces_meshed = 0
    extr = extr_meshed = 0
    cyr_names = 0
    for o in f.Objects:
        g, a = o.Geometry, o.Attributes
        k = geometry_kind(g)
        (in_blocks if a.IsInstanceDefinitionObject else kinds)[k] += 1
        if has_cyrillic(a.Name or ""):
            cyr_names += 1
        if isinstance(g, r.Brep):
            for i in range(len(g.Faces)):
                fc = g.Faces[i]
                brep_faces += 1
                if fc.GetMesh(r.MeshType.Any) is not None:
                    faces_meshed += 1
                try:
                    if not fc.DuplicateFace(False).IsSurface:
                        trimmed += 1
                except Exception:
                    pass
        elif isinstance(g, r.Extrusion):
            extr += 1
            if g.GetMesh(r.MeshType.Any) is not None:
                extr_meshed += 1
    lay = layers(f)
    return {
        "objects": dict(kinds), "block_objects": dict(in_blocks),
        "brep_faces": brep_faces, "trimmed_faces": trimmed, "faces_with_render_mesh": faces_meshed,
        "extrusions": extr, "extrusions_with_render_mesh": extr_meshed,
        "layers": len(lay), "layers_cyrillic": sum(1 for l in lay if has_cyrillic(l["name"])),
        "object_names_cyrillic": cyr_names,
        "materials": len(f.Materials), "groups": len(f.Groups), "blocks": len(f.InstanceDefinitions),
    }


def file_info(path):
    """Текст для кнопки File Info."""
    f = read(path)
    d = doc_info(f)
    s = summary(f)
    lines = ["File: %s" % path,
             "Rhino archive: %s   Application: %s" % (d["archive_version"], d["application"]),
             "Created: %s %s   Edited: %s %s   Revision: %s" % (d["created"], d["created_by"], d["last_edited"],
                                                             d["last_edited_by"], d["revision"]),
             "Units: %s (1 unit = %g m)   Tolerance: %g" % (d["units"], d["unit_m"], d["abs_tolerance"]),
             ""]
    lines.append("Objects:")
    for k, n in sorted(s["objects"].items(), key=lambda kv: -kv[1]):
        lines.append("  %-20s %d" % (k, n))
    if s["block_objects"]:
        lines.append("Objects inside block definitions: %d" % sum(s["block_objects"].values()))
    lines.append("")
    lines.append("Brep faces: %d (trimmed %d), with render mesh: %d" % (s["brep_faces"], s["trimmed_faces"],
                                                                      s["faces_with_render_mesh"]))
    if s["extrusions"]:
        lines.append("Extrusions: %d, with render mesh: %d" % (s["extrusions"], s["extrusions_with_render_mesh"]))
    if s["brep_faces"] and s["faces_with_render_mesh"] < s["brep_faces"]:
        lines.append("  Note: some faces have no render mesh (file saved with Save Small?) -> H3DM tessellates them.")
    lines.append("Layers: %d (Cyrillic names: %d)   Object names in Cyrillic: %d"
                 % (s["layers"], s["layers_cyrillic"], s["object_names_cyrillic"]))
    lines.append("Materials: %d   Groups: %d   Blocks: %d" % (s["materials"], s["groups"], s["blocks"]))
    ds = doc_strings(f)
    if ds:
        lines.append("")
        lines.append("Document User Text:")
        for k, v in ds.items():
            lines.append("  %s = %s" % (k, v))
    lines.append("")
    lines.append("Layer tree:")
    for l in layers(f):
        depth = l["full_path"].count("::")
        flags = ("" if l["visible"] else " [hidden]") + (" [locked]" if l["locked"] else "")
        lines.append("  " + "  " * depth + l["name"] + flags)
    return "\n".join(lines)


# =====================================================================
# Объекты и геометрия (все координаты — мировые Rhino, float64)
# =====================================================================

import fnmatch  # noqa: E402

import numpy as np  # noqa: E402


def _xf_np(x):
    """rhino3dm.Transform -> numpy 4x4 (столбцовые векторы)."""
    return np.array([[getattr(x, "M%d%d" % (i, j)) for j in range(4)] for i in range(4)], dtype=np.float64)


def _pt(p):
    return (p.X, p.Y, p.Z)


def _apply(m, v):
    """Применить 4x4 к точкам (N,3) в double."""
    if m is None or len(v) == 0:
        return v
    return v @ m[:3, :3].T + m[:3, 3]


# ---------- сетки ----------

def mesh_arrays(m, colors=False):
    """rhino3dm.Mesh -> (вершины float64 (N,3), грани [tuple], цвета (N,4) 0..1 или None)."""
    if m is None or len(m.Vertices) == 0:
        return None
    v = np.array([_pt(p) for p in m.Vertices.ToPoint3dArray()], dtype=np.float64)
    faces = []
    for i in range(len(m.Faces)):
        a, b, c, d = m.Faces[i]
        faces.append((a, b, c) if c == d else (a, b, c, d))
    vc = None
    if colors and len(m.VertexColors) == len(v):
        vc = np.array([tuple(m.VertexColors[i]) for i in range(len(v))], dtype=np.float64) / 255.0
    return v, faces, vc


# ---------- NURBS ----------

def _full_knots(k):
    """Узлы Rhino (order+cv-2) -> Houdini (order+cv): добавить крайние."""
    k = [k[i] for i in range(len(k))]
    return [k[0]] + k + [k[-1]]


def nurbs_curve_data(c):
    """Кривая -> {'cv','w','order','knots','rational','closed','periodic'} (мировые, double)."""
    nc = c if isinstance(c, _r().NurbsCurve) else c.ToNurbsCurve()
    if nc is None:
        return None
    n = len(nc.Points)
    P = np.empty((n, 3))
    W = np.ones(n)
    rational = nc.IsRational
    for i in range(n):
        p = nc.Points[i]
        w = p.W if rational else 1.0
        W[i] = w
        P[i] = (p.X / w, p.Y / w, p.Z / w) if rational and w else (p.X, p.Y, p.Z)
    return {"cv": P, "w": W, "order": nc.Order, "knots": _full_knots(nc.Knots), "rational": rational,
            "closed": bool(nc.IsClosed), "periodic": bool(nc.IsPeriodic)}


def nurbs_surface_data(s, reverse=False):
    """Поверхность -> {'cv' (nv,nu,3), 'w' (nv,nu), 'order_u','order_v','knots_u','knots_v'}.

    reverse=True — развернуть направление U (нормаль меняется на противоположную).
    Нормаль NURBS в Houdini направлена противоположно Rhino (u x v), поэтому для совпадения с Rhino
    разворачиваем U у обычных граней и НЕ разворачиваем у граней с OrientationIsReversed: см. houdini_reverse().
    """
    ns = s if isinstance(s, _r().NurbsSurface) else s.ToNurbsSurface()
    if ns is None:
        return None
    nu, nv = ns.Points.CountU, ns.Points.CountV
    rational = ns.IsRational
    P = np.empty((nv, nu, 3))
    W = np.ones((nv, nu))
    for j in range(nv):
        for i in range(nu):
            p = ns.Points.GetControlPoint(i, j)
            w = p.W if rational else 1.0
            W[j, i] = w
            P[j, i] = (p.X / w, p.Y / w, p.Z / w) if rational and w else (p.X, p.Y, p.Z)
    ku, kv = _full_knots(ns.KnotsU), _full_knots(ns.KnotsV)
    if reverse:
        P, W = P[:, ::-1], W[:, ::-1]
        a, b = ku[0], ku[-1]
        ku = [a + b - x for x in reversed(ku)]
    return {"cv": P, "w": W, "order_u": ns.OrderU, "order_v": ns.OrderV, "knots_u": ku, "knots_v": kv,
            "rational": rational}


def houdini_reverse(face_reversed=False):
    """Разворот U для Houdini: нормаль Houdini = -(u x v) Rhino."""
    return not face_reversed


def face_boundary_curves(brep, face):
    """Рёбра петель грани -> список данных NURBS-кривых (внешняя петля первой)."""
    out = []
    try:
        loops = [face.Loops[i] for i in range(len(face.Loops))]
    except Exception:
        return out
    for li, loop in enumerate(loops):
        for tr in loop.Trims:
            ei = tr.EdgeIndex
            if ei < 0:
                continue          # шов/сингулярность — ребра нет
            d = nurbs_curve_data(brep.Edges[ei])
            if d is not None:
                d["loop"] = li
                d["loop_type"] = enum_name(loop.LoopType)
                out.append(d)
    return out


def sample_curve(c, segments_per_span=8):
    """Полилиния по кривой (для режима Polylines)."""
    r = _r()
    if isinstance(c, r.LineCurve):
        return np.array([_pt(c.PointAtStart), _pt(c.PointAtEnd)])
    if isinstance(c, r.PolylineCurve):
        return np.array([_pt(c.Point(i)) for i in range(c.PointCount)])
    dom = c.Domain
    n = max(8, c.SpanCount * segments_per_span * max(1, c.Degree))
    ts = np.linspace(dom.T0, dom.T1, n + 1)
    return np.array([_pt(c.PointAt(float(t))) for t in ts])


# ---------- атрибуты объекта ----------

class Tables(object):
    """Таблицы файла для быстрого разрешения цвета/материала/видимости слоёв."""

    def __init__(self, f):
        self.f = f
        self.layers = list(f.Layers)
        self.by_index = {l.Index: l for l in self.layers}
        self.by_id = {str(l.Id): l for l in self.layers}
        self.materials = list(f.Materials)
        self.groups = [g.Name or ("Group%d" % g.Index) for g in f.Groups]
        self.idefs = {str(d.Id): d for d in f.InstanceDefinitions}
        self._vis = {}

    def layer(self, idx):
        return self.by_index.get(idx)

    def layer_path(self, idx):
        l = self.by_index.get(idx)
        return l.FullPath if l is not None else ""

    def layer_visible(self, idx):
        """Слой видим, только если видимы все его родители."""
        if idx in self._vis:
            return self._vis[idx]
        l = self.by_index.get(idx)
        vis, locked = True, False
        while l is not None:
            vis = vis and bool(l.Visible)
            locked = locked or bool(l.Locked)
            l = self.by_id.get(str(l.ParentLayerId))
        self._vis[idx] = (vis, locked)
        return self._vis[idx]

    def material(self, idx):
        if 0 <= idx < len(self.materials):
            return self.materials[idx]
        return None


def resolve_style(tables, a, parent=None):
    """Цвет отображения (r,g,b,a 0..1), цвет объекта, материал (индекс) с учётом источников.

    parent — уже разрешённый стиль вставки блока для объектов «By Parent».
    """
    cs = enum_name(a.ColorSource)
    lay = tables.layer(a.LayerIndex)
    layer_col = color(lay.Color) if lay is not None else (0.0, 0.0, 0.0, 1.0)
    ms = enum_name(a.MaterialSource)
    if ms == "MaterialFromObject":
        mat = a.MaterialIndex
    elif ms == "MaterialFromParent" and parent is not None:
        mat = parent["material"]
    else:
        mat = lay.RenderMaterialIndex if lay is not None else -1
    if cs == "ColorFromObject":
        disp = color(a.ObjectColor)
    elif cs == "ColorFromMaterial":
        m = tables.material(mat)
        disp = color(m.DiffuseColor) if m is not None else layer_col
    elif cs == "ColorFromParent" and parent is not None:
        disp = parent["display"]
    else:
        disp = layer_col
    return {"display": disp, "object": color(a.ObjectColor), "color_source": cs, "material": mat}


def object_record(o, tables, parent_style=None):
    """Общие данные объекта (без геометрии)."""
    a = o.Attributes
    st = resolve_style(tables, a, parent_style)
    m = tables.material(st["material"])
    return {
        "id": str(a.Id), "name": a.Name or "", "kind": geometry_kind(o.Geometry),
        "layer_index": a.LayerIndex, "layer": tables.layer_path(a.LayerIndex),
        "display": st["display"], "object_color": st["object"], "color_source": st["color_source"],
        "material_index": st["material"], "material": (m.Name or "") if m is not None else "",
        "transparency": float(m.Transparency) if m is not None else 0.0,
        "user_text": user_strings(a),
        "groups": [tables.groups[g] for g in a.GetGroupList() if 0 <= g < len(tables.groups)],
        "visible": bool(a.Visible), "style": st,
    }


# ---------- извлечение геометрии ----------

class Options(object):
    """Параметры извлечения (значения по умолчанию = значения HDA)."""
    surfout = "nurbs"         # nurbs | polys | packed
    trimnurbs = False         # обрезанные грани в режиме nurbs: True = необрезанная поверхность + кривые границ
    rendermesh = True
    curves = "nurbs"          # nurbs | poly
    blocks = "packed"         # packed | expand
    layers = "*"
    skiphidden = False
    skiplocked = False
    types = {"surfaces", "meshes", "subd", "curves", "points", "blocks"}


KIND_TYPE = {
    "Brep": "surfaces", "Extrusion": "surfaces", "NurbsSurface": "surfaces", "PlaneSurface": "surfaces",
    "RevSurface": "surfaces", "SumSurface": "surfaces", "Surface": "surfaces",
    "Mesh": "meshes", "SubD": "subd",
    "LineCurve": "curves", "ArcCurve": "curves", "PolylineCurve": "curves", "NurbsCurve": "curves",
    "PolyCurve": "curves", "Curve": "curves",
    "PointCloud": "points", "InstanceReference": "blocks",
}
INFO_KINDS = {"TextDot", "Text", "Leader", "Point", "Light", "DimLinear", "DimAngular", "DimRadial", "DimOrdinate",
              "Dimension", "Centermark", "AnnotationBase"}


def layer_filter(patterns):
    """Глобы по полному пути слоя; ^ — исключение."""
    inc = [p for p in (patterns or "*").split() if not p.startswith("^")] or ["*"]
    exc = [p[1:] for p in (patterns or "").split() if p.startswith("^")]

    def ok(path):
        return any(fnmatch.fnmatchcase(path, p) for p in inc) and not any(fnmatch.fnmatchcase(path, p) for p in exc)
    return ok


def _brep_parts(brep, opt, stats):
    """Brep -> части: сетки граней / NURBS-грани / кривые границ."""
    r = _r()
    parts = []
    for fi in range(len(brep.Faces)):
        face = brep.Faces[fi]
        try:
            untrimmed = face.DuplicateFace(False).IsSurface
        except Exception:
            untrimmed = False
        want_nurbs = opt.surfout == "nurbs" and (untrimmed or opt.trimnurbs)
        if want_nurbs:
            d = nurbs_surface_data(face.UnderlyingSurface(), reverse=houdini_reverse(face.OrientationIsReversed))
            if d is not None:
                d.update({"t": "nsurf", "face": fi, "trimmed": not untrimmed})
                parts.append(d)
                if not untrimmed:
                    for cd in face_boundary_curves(brep, face):
                        cd.update({"t": "ncurve", "face": fi, "trim": True})
                        parts.append(cd)
                continue
        mesh = face.GetMesh(r.MeshType.Any) if opt.rendermesh else None
        if mesh is not None:
            v, faces, _ = mesh_arrays(mesh)
            parts.append({"t": "mesh", "v": v, "f": faces, "face": fi})
        elif untrimmed:
            # нет сетки — необрезанную грань разобьёт Houdini (Convert NURBS -> полигоны)
            d = nurbs_surface_data(face.UnderlyingSurface(), reverse=houdini_reverse(face.OrientationIsReversed))
            if d is not None:
                d.update({"t": "nsurf", "face": fi, "trimmed": False, "to_polys": True})
                parts.append(d)
        else:
            stats["faces_without_mesh"] = stats.get("faces_without_mesh", 0) + 1
    return parts


def geometry_parts(g, opt, stats):
    """Геометрия одного объекта -> список частей в мировых координатах (или локальных — для блоков)."""
    r = _r()
    k = geometry_kind(g)
    if isinstance(g, r.Brep):
        return _brep_parts(g, opt, stats)
    if isinstance(g, r.Extrusion):
        m = g.GetMesh(r.MeshType.Any) if (opt.rendermesh and opt.surfout != "nurbs") else None
        if m is not None:
            v, faces, _ = mesh_arrays(m)
            return [{"t": "mesh", "v": v, "f": faces, "face": -1}]
        b = g.ToBrep(True)
        if b is None:
            return []
        local = {}
        parts = _brep_parts(b, opt, local)
        if local.get("faces_without_mesh"):
            # торцы — обрезанные плоскости без сетки: берём сетку всего объекта (своё разбиение — этап 4)
            m = g.GetMesh(r.MeshType.Any) if opt.rendermesh else None
            if m is not None:
                v, faces, _ = mesh_arrays(m)
                return [{"t": "mesh", "v": v, "f": faces, "face": -1}]
            stats["faces_without_mesh"] = stats.get("faces_without_mesh", 0) + local["faces_without_mesh"]
        return parts
    if isinstance(g, r.Surface):
        d = nurbs_surface_data(g, reverse=houdini_reverse(False))
        if d is None:
            return []
        d.update({"t": "nsurf", "face": 0, "trimmed": False, "to_polys": opt.surfout != "nurbs"})
        return [d]
    if isinstance(g, r.Mesh):
        res = mesh_arrays(g, colors=True)
        if res is None:
            return []
        v, faces, vc = res
        return [{"t": "mesh", "v": v, "f": faces, "face": -1, "vc": vc}]
    if isinstance(g, r.SubD):
        m = r.Mesh.CreateFromSubDControlNet(g, False)
        res = mesh_arrays(m)
        if res is None:
            return []
        return [{"t": "mesh", "v": res[0], "f": res[1], "face": -1, "subd": True}]
    if isinstance(g, r.Curve):
        if isinstance(g, (r.LineCurve, r.PolylineCurve)) or opt.curves == "poly":
            v = sample_curve(g)
            closed = bool(g.IsClosed) and len(v) > 2
            if closed and np.allclose(v[0], v[-1]):
                v = v[:-1]
            return [{"t": "poly", "v": v, "closed": closed}]
        d = nurbs_curve_data(g)
        if d is None:
            return []
        d["t"] = "ncurve"
        return [d]
    if isinstance(g, r.PointCloud):
        v = np.array([_pt(p) for p in g.GetPoints()], dtype=np.float64)
        c = None
        if g.ContainsColors:
            c = np.array([tuple(x) for x in g.GetColors()], dtype=np.float64) / 255.0
        return [{"t": "points", "v": v, "c": c}]
    if isinstance(g, r.InstanceReference):
        return [{"t": "instance", "idef": str(g.ParentIdefId), "m": _xf_np(g.Xform)}]
    stats.setdefault("skipped_kinds", {})
    stats["skipped_kinds"][k] = stats["skipped_kinds"].get(k, 0) + 1
    return []


def iter_objects(f, opt, tables=None, stats=None):
    """Объекты модели (не из определений блоков) -> записи с частями геометрии."""
    tables = tables or Tables(f)
    stats = stats if stats is not None else {}
    lay_ok = layer_filter(opt.layers)
    for o in f.Objects:
        a = o.Attributes
        if a.IsInstanceDefinitionObject:
            continue
        kind = geometry_kind(o.Geometry)
        if kind in INFO_KINDS:
            continue
        typ = KIND_TYPE.get(kind)
        if typ is None and isinstance(o.Geometry, _r().Curve):
            typ = "curves"
        if typ is not None and typ not in opt.types:
            continue
        vis, locked = tables.layer_visible(a.LayerIndex)
        if (opt.skiphidden and (not vis or not a.Visible)) or (opt.skiplocked and locked):
            continue
        if not lay_ok(tables.layer_path(a.LayerIndex)):
            continue
        rec = object_record(o, tables)
        rec["parts"] = geometry_parts(o.Geometry, opt, stats)
        yield rec


def block_definition(f, tables, idef_id, opt, stats, cache):
    """Записи объектов определения блока (локальные координаты блока). Кэшируется по id."""
    if idef_id in cache:
        return cache[idef_id]
    d = tables.idefs.get(idef_id)
    recs = []
    if d is not None:
        for oid in d.GetObjectIds():
            o = f.Objects.FindId(oid) if hasattr(f.Objects, "FindId") else None
            if o is None:
                continue
            rec = object_record(o, tables)
            rec["parts"] = geometry_parts(o.Geometry, opt, stats)
            recs.append(rec)
    cache[idef_id] = recs
    return recs


# ---------- габарит ----------

def object_bbox(o, f=None):
    r = _r()
    g = o.Geometry
    try:
        if isinstance(g, r.AnnotationBase):
            ds = f.DimStyles.FindId(g.DimensionStyleId) if f is not None else None
            b = g.GetBoundingBox(ds) if ds is not None else None
            if b is None:
                p = g.Plane.Origin
                return np.array(_pt(p)), np.array(_pt(p))
        elif isinstance(g, r.Light):
            p = g.Location
            return np.array(_pt(p)), np.array(_pt(p))
        else:
            b = g.GetBoundingBox()
        if b is None or not b.IsValid:
            return None
        return np.array(_pt(b.Min)), np.array(_pt(b.Max))
    except Exception:
        return None


def file_bbox(f):
    """Габарит модели (без объектов в определениях блоков), double."""
    mn = mx = None
    for o in f.Objects:
        if o.Attributes.IsInstanceDefinitionObject:
            continue
        b = object_bbox(o, f)
        if b is None:
            continue
        mn = b[0] if mn is None else np.minimum(mn, b[0])
        mx = b[1] if mx is None else np.maximum(mx, b[1])
    return None if mn is None else (mn, mx)


# ---------- информация: тексты, размеры, точки, свет ----------

def info_records(f, tables, want, layer_ok=None, skiphidden=False):
    """Тексты, метки, размеры, выноски, точки, свет -> записи для выхода Info (мировые координаты)."""
    r = _r()
    out = []
    for o in f.Objects:
        a = o.Attributes
        if a.IsInstanceDefinitionObject:
            continue
        g = o.Geometry
        if layer_ok is not None and not layer_ok(tables.layer_path(a.LayerIndex)):
            continue
        if skiphidden and not tables.layer_visible(a.LayerIndex)[0]:
            continue
        rec = None
        if isinstance(g, r.TextDot) and "dots" in want:
            rec = {"type": "textdot", "P": _pt(g.Point), "text": g.Text or "", "text2": g.SecondaryText or "",
                   "height": float(g.FontHeight), "font": g.FontFace or ""}
        elif isinstance(g, r.Leader) and "dims" in want:
            pts = [_pt(p) for p in g.Points]
            rec = {"type": "leader", "P": pts[-1] if pts else _pt(g.Plane.Origin), "text": g.PlainText or "",
                   "points": pts, "plane": g.Plane}
        elif isinstance(g, r.Dimension) and "dims" in want:
            try:
                pts = g.Points
            except Exception:
                pts = {}
            meas = None
            if "defpt1" in pts and "defpt2" in pts:
                meas = float(np.linalg.norm(np.subtract(_pt(pts["defpt2"]), _pt(pts["defpt1"]))))
            tp = pts.get("textpt") or pts.get("dimline") or g.Plane.Origin
            rec = {"type": "dimension", "P": _pt(tp), "text": g.PlainText or "", "measurement": meas,
                   "dim_kind": geometry_kind(g), "plane": g.Plane,
                   "points": {k: _pt(v) for k, v in pts.items()}}
        elif isinstance(g, r.AnnotationBase) and "text" in want:
            rec = {"type": "text", "P": _pt(g.Plane.Origin), "text": g.PlainText or "", "rich_text": g.RichText or "",
                   "plane": g.Plane, "rotation_deg": float(g.TextRotationDegrees)}
            try:
                rec["height"] = float(g.GetTextHeight(f.DimStyles.FindId(g.DimensionStyleId)))
            except Exception:
                pass
        elif isinstance(g, r.Point) and "points" in want:
            rec = {"type": "point", "P": _pt(g.Location), "text": a.Name or ""}
        elif isinstance(g, r.Light) and "lights" in want:
            rec = {"type": "light", "P": _pt(g.Location), "text": g.Name or "", "light_style": enum_name(g.LightStyle),
                   "direction": _pt(g.Direction), "light_color": color(g.Diffuse), "intensity": float(g.Intensity),
                   "enabled": bool(g.IsEnabled)}
        elif isinstance(g, r.InstanceReference) and "blocks" in want:
            m = _xf_np(g.Xform)
            d = tables.idefs.get(str(g.ParentIdefId))
            rec = {"type": "block", "P": tuple(m[:3, 3]), "text": d.Name if d is not None else "", "matrix": m}
        if rec is not None:
            rec.update(object_record(o, tables))
            out.append(rec)
    return out

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


PREPARE_KEY = "h3dm.prepare"


def doc_strings(f, service=False):
    """Document User Text: {ключ: значение}. Служебные ключи H3DM ("h3dm.*") — только при service=True."""
    out = {}
    for i in range(len(f.Strings)):
        k, v = f.Strings[i]
        if service or not str(k).startswith("h3dm."):
            out[k] = v
    return out


def prepare_stamp(f):
    """Отпечаток подготовки (Prepare in Rhino) или None."""
    import json
    v = doc_strings(f, service=True).get(PREPARE_KEY)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def prepare_stamp_text(st):
    """Краткое описание отпечатка подготовки для File Info."""
    if not st:
        return "Not prepared in Rhino (no H3DM stamp)."
    k = st.get("key", {})
    src = st.get("source", {})
    m = st.get("mesh", {})
    sset = k.get("settings", {})
    stt = st.get("stats", {})
    lines = ["Prepared in Rhino %s on %s (prepare script v%s)" % (k.get("rhino", "?"), st.get("created", "?"),
                                                                 k.get("prep_version", "?")),
             "  Source: %s" % src.get("path", "?"),
             "  Mesh preset: %s   tolerance %g, refine angle %g deg, max edge %g"
             % (sset.get("preset", "normal"), m.get("tolerance", 0) or 0, m.get("refine_angle_deg", 0) or 0,
                m.get("max_edge", 0) or 0),
             "  Faces meshed: %s / %s   SubD converted: %s   Breps: %s"
             % (stt.get("check_faces_meshed", "?"), stt.get("check_faces", "?"), stt.get("subd_converted", 0),
                stt.get("breps", "?"))]
    return "\n".join(lines)


def prepare_source(path):
    """Если path — подготовленная копия, вернуть путь исходника (если он существует), иначе path."""
    import os
    try:
        st = prepare_stamp(read(path))
    except Exception:
        st = None
    src = ((st or {}).get("source") or {}).get("path")
    if src and os.path.isfile(src):
        return src
    return path


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
    lines.append(prepare_stamp_text(prepare_stamp(f)))
    lines.append("")
    lines.append("Brep faces: %d (trimmed %d), with render mesh: %d" % (s["brep_faces"], s["trimmed_faces"],
                                                                      s["faces_with_render_mesh"]))
    if s["extrusions"]:
        lines.append("Extrusions: %d, with render mesh: %d" % (s["extrusions"], s["extrusions_with_render_mesh"]))
    if s["brep_faces"] and s["faces_with_render_mesh"] < s["brep_faces"]:
        lines.append("  Note: some faces have no render mesh (file saved with Save Small?). Use Prepare in Rhino "
                     "to create meshes and exact trims; without it trimmed faces without a mesh are skipped.")
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
    return np.einsum("ij,nj->ni", m[:3, :3], v) + m[:3, 3]


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
    from .nurbs import clamp_curve
    # периодические (незажатые) кривые -> эквивалентные зажатые: Houdini понимает их однозначно
    P, W, knots = clamp_curve(P, W, _full_knots(nc.Knots), nc.Order)
    return {"cv": P, "w": W, "order": nc.Order, "knots": knots, "rational": rational,
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
    from .nurbs import clamp_surface
    P, W, ku, kv = clamp_surface(P, W, ku, kv, ns.OrderU, ns.OrderV)
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


def sample_curve(c, tol):
    """Полилиния по кривой с отклонением хорды не больше tol (единицы модели)."""
    r = _r()
    if isinstance(c, r.LineCurve):
        return np.array([_pt(c.PointAtStart), _pt(c.PointAtEnd)])
    if isinstance(c, r.PolylineCurve):
        return np.array([_pt(c.Point(i)) for i in range(c.PointCount)])
    dom = c.Domain
    t0, t1 = dom.T0, dom.T1
    # стартовое разбиение: границы пролётов, каждый — на 2*степень частей
    nc = c.ToNurbsCurve()
    if nc is not None:
        ks = sorted({nc.Knots[i] for i in range(len(nc.Knots)) if t0 <= nc.Knots[i] <= t1} | {t0, t1})
    else:
        ks = [t0, t1]
    deg = max(1, c.Degree)
    ts = []
    for k0, k1 in zip(ks[:-1], ks[1:]):
        ts.extend(np.linspace(k0, k1, 2 * deg + 1)[:-1].tolist())
    ts.append(t1)
    pt = {t: np.array(_pt(c.PointAt(t))) for t in ts}

    def dev_of(p, pa, pb):
        ab = pb - pa
        L = float(np.dot(ab, ab))
        if L == 0:
            return float(np.linalg.norm(p - pa))
        t = min(1.0, max(0.0, float(np.dot(p - pa, ab)) / L))
        return float(np.linalg.norm(p - (pa + t * ab)))

    def refine(ta, tb, depth):
        # отклонение от хорды проверяется в трёх точках отрезка (1/4, 1/2, 3/4), а не только в середине
        pa, pb = pt[ta], pt[tb]
        tm = 0.5 * (ta + tb)
        probes = [(tq, np.array(_pt(c.PointAt(tq)))) for tq in (ta + 0.25 * (tb - ta), tm, ta + 0.75 * (tb - ta))]
        dev = max(dev_of(p, pa, pb) for _, p in probes)
        if dev <= tol or depth >= 16:
            return [tb]
        pt[tm] = probes[1][1]
        return refine(ta, tm, depth + 1) + refine(tm, tb, depth + 1)

    out = [ts[0]]
    for ta, tb in zip(ts[:-1], ts[1:]):
        out += refine(ta, tb, 0)
    return np.array([pt[t] for t in out])


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
        "material_source": enum_name(a.MaterialSource), "locked": enum_name(a.Mode) == "Locked",
        "id": str(a.Id), "name": a.Name or "", "kind": geometry_kind(o.Geometry),
        "layer_index": a.LayerIndex, "layer": tables.layer_path(a.LayerIndex),
        "display": st["display"], "object_color": st["object"], "color_source": st["color_source"],
        "material_index": st["material"], "material": (m.Name or "") if m is not None else "",
        "transparency": float(m.Transparency) if m is not None else 0.0,
        "user_text": user_strings(a),
        "groups": [tables.groups[g] for g in a.GetGroupList() if 0 <= g < len(tables.groups)],
        "visible": bool(a.Visible), "style": st,
    }


def apply_parent(rec, parent):
    """Объект определения блока со стилем «By Parent» получает цвет/материал вставки (копия записи)."""
    if parent is None:
        return rec
    out = dict(rec)
    if rec.get("color_source") == "ColorFromParent":
        out["display"] = parent["display"]
    if rec.get("material_source") == "MaterialFromParent":
        for k in ("material_index", "material", "transparency"):
            out[k] = parent[k]
    return out


def uses_parent(f, tables, idef_id, depth=0, _memo=None):
    """Есть ли в определении блока (с учётом вложенных) объекты «By Parent» — тогда вид зависит от вставки."""
    _memo = {} if _memo is None else _memo
    if idef_id in _memo:
        return _memo[idef_id]
    _memo[idef_id] = False
    d = tables.idefs.get(idef_id)
    res = False
    if d is not None and depth < 16:
        for oid in d.GetObjectIds():
            o = f.Objects.FindId(oid)
            if o is None:
                continue
            a = o.Attributes
            if enum_name(a.ColorSource) == "ColorFromParent" or enum_name(a.MaterialSource) == "MaterialFromParent":
                res = True
                break
            g = o.Geometry
            if isinstance(g, _r().InstanceReference) and uses_parent(f, tables, str(g.ParentIdefId), depth + 1, _memo):
                res = True
                break
    _memo[idef_id] = res
    return res


# ---------- извлечение геометрии ----------

class Options(object):
    """Параметры извлечения (значения по умолчанию = значения HDA)."""
    # режим первого выхода Geometry:
    #   legacy         — как в 0.2 (Surface Output: nurbs | polys | packed)
    #   mesh_curves    — поверхности и тела сетками, кривые NURBS (по умолчанию для новых нод)
    #   nurbs_surfaces — поверхности (открытые оболочки) NURBS, тела (замкнутые) сетками
    #   all_nurbs      — всё, что возможно, в NURBS
    geomode = "legacy"
    surfout = "nurbs"         # только legacy: nurbs | polys | packed
    trimnurbs = False         # только legacy: обрезанные грани = необрезанная поверхность + кривые границ
    pack = False              # упаковка по объекту (независимо от режима)
    rendermesh = True
    curves = "nurbs"          # nurbs | poly
    blocks = "packed"         # packed | expand
    layers = "*"
    skiphidden = False
    skiplocked = False
    types = {"surfaces", "meshes", "subd", "curves", "points", "blocks"}
    curvetol = 0.0            # допуск полилиний, единицы модели (0 = 1 мм)
    trimtol = 0.0             # допуск ломаных для рациональных кривых обрезки, единицы модели (0 = 0,1 мм)

    @property
    def packed(self):
        return self.pack or (self.geomode == "legacy" and self.surfout == "packed")

    def surfaces_as_nurbs(self, solid):
        if self.geomode == "legacy":
            return self.surfout == "nurbs"
        if self.geomode == "all_nurbs":
            return True
        if self.geomode == "nurbs_surfaces":
            return not solid
        return False

    @property
    def lines_as_nurbs(self):
        """Отрезки и полилинии — точные NURBS степени 1 (в новых режимах при Curves = NURBS)."""
        return self.geomode != "legacy" and self.curves == "nurbs"


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


# ---------- кривые обрезки из подготовки в Rhino (строка геометрии "h3dm.trims")

def brep_trims(brep):
    """Данные кривых обрезки, сохранённые rhino/h3dm_prepare.py, или None."""
    import base64
    import json
    import zlib
    try:
        s = brep.GetUserString("h3dm.trims")
    except Exception:
        s = None
    if not s:
        return None
    try:
        d = json.loads(zlib.decompress(base64.b64decode(s)).decode("utf-8"))
    except Exception:
        return None
    return {f["f"]: f for f in d.get("faces", [])}


def face_trims_hash(fdata):
    """Отпечаток данных обрезки грани из подготовки (None — нет данных)."""
    if fdata is None:
        return "-"
    import hashlib
    import json
    return hashlib.sha1(json.dumps(fdata, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:20]


def surface_evaluator(d):
    """Данные поверхности (nurbs_surface_data, без разворота) -> S(u, v) в координатах модели."""
    from .nurbs import eval_surface
    cv, w = np.asarray(d["cv"], dtype=np.float64), np.asarray(d["w"], dtype=np.float64)
    Uu, Uv = np.asarray(d["knots_u"], dtype=np.float64), np.asarray(d["knots_v"], dtype=np.float64)
    ou, ov = int(d["order_u"]), int(d["order_v"])
    u0, u1 = float(Uu[ou - 1]), float(Uu[len(Uu) - ou])
    v0, v1 = float(Uv[ov - 1]), float(Uv[len(Uv) - ov])

    def S(u, v):
        return eval_surface(cv, w, Uu, Uv, ou, ov, min(max(u, u0), u1), min(max(v, v0), v1))
    return S


def _sample_trim(cv, knots, order, tol, S=None):
    """Рациональная кривая обрезки -> точки ломаной (u, v).

    S — поверхность грани S(u, v): отклонение меряется в ПРОСТРАНСТВЕ МОДЕЛИ — расстояние между точкой
    поверхности на кривой и точкой поверхности на хорде в UV (в 1/4, 1/2, 3/4 каждого участка). Без S —
    в единицах параметра (только для тестов). Хорда делится, пока отклонение > tol (до 2^16 частей).
    """
    from .nurbs import eval_curve
    P = np.array([[p[0], p[1], 0.0] for p in cv], dtype=np.float64)
    W = np.array([p[2] for p in cv], dtype=np.float64)
    U = _full_knots(knots)
    a, b = U[order - 1], U[len(cv)]
    ks = sorted({k for k in knots if a <= k <= b} | {a, b})
    ts = []
    for k0, k1 in zip(ks[:-1], ks[1:]):
        ts.extend(np.linspace(k0, k1, 5)[:-1].tolist())
    ts.append(b)
    pt = {t: eval_curve(P, W, U, order, t)[:2] for t in ts}

    def deviation(pa, pb, pm):
        ab = pb - pa
        L2 = float(ab @ ab)
        s = 0.0 if L2 == 0 else min(max(float((pm - pa) @ ab) / L2, 0.0), 1.0)
        q = pa + s * ab                       # ближайшая к кривой точка хорды в UV
        if S is None:
            return float(np.hypot(*(pm - q)))
        return float(np.linalg.norm(S(*pm) - S(*q)))

    def refine(ta, tb, depth):
        pa, pb = pt[ta], pt[tb]
        dev = 0.0
        for f in (0.25, 0.5, 0.75):
            tm = ta + f * (tb - ta)
            dev = max(dev, deviation(pa, pb, eval_curve(P, W, U, order, tm)[:2]))
            if dev > tol:
                break
        if dev <= tol or depth >= 16:
            return [tb]
        tm = 0.5 * (ta + tb)
        pt[tm] = eval_curve(P, W, U, order, tm)[:2]
        return refine(ta, tm, depth + 1) + refine(tm, tb, depth + 1)

    out = [ts[0]]
    for ta, tb in zip(ts[:-1], ts[1:]):
        out += refine(ta, tb, 0)
    return [pt[t] for t in out]


def face_profile_loops(fdata, reverse, u_domain, tol, S=None):
    """Петли кривых обрезки грани -> [[{'order','knots'(полные),'cv'[(u,v)]}...]...] в UV Houdini.

    Рациональные кривые -> ломаные с отклонением <= tol в пространстве модели (S — поверхность грани;
    Houdini не учитывает веса кривых обрезки); нерациональные — точно.
    reverse: U поверхности развёрнут (u' = a + b - u) — отражаем точки и меняем направление обхода петли.
    """
    from .nurbs import clamp_curve
    a, b = u_domain
    loops = []
    for lp in fdata.get("l", []):
        curves = []
        for c in lp.get("c", []):
            order = int(c["o"])
            if c.get("r"):
                pts = _sample_trim(c["p"], c["k"], order, tol, S)
                n = len(pts)
                kn = [0.0] + list(np.linspace(0.0, 1.0, n)) + [1.0]
                curves.append({"order": 2, "knots": kn, "cv": [(float(x), float(y)) for x, y in pts]})
            else:
                cv = np.array([[p[0], p[1], 0.0] for p in c["p"]], dtype=np.float64)
                w = np.ones(len(cv))
                cv, w, kn = clamp_curve(cv, w, _full_knots(c["k"]), order)
                curves.append({"order": order, "knots": [float(k) for k in kn], "cv": [(float(x), float(y)) for x, y, _ in cv]})
        if reverse:
            rev = []
            for c in reversed(curves):
                k = c["knots"]
                k0, k1 = k[0], k[-1]
                rev.append({"order": c["order"], "knots": [k0 + k1 - x for x in reversed(k)],
                            "cv": [(a + b - u, v) for u, v in reversed(c["cv"])]})
            curves = rev
        loops.append(curves)
    return loops


def face_trim_loops_exact(fdata, reverse, u_domain, su=0.0, sv=0.0):
    """Петли обрезки без упрощения: [[{'o': порядок, 'k': узлы (полные, Houdini), 'p': [[u, v, w], ...]}]]
    в параметрах примитива Houdini (разворот U как у поверхности, сдвиг узлов su/sv как в houjson).
    Первая петля — внешняя."""
    from .nurbs import clamp_curve
    a, b = u_domain
    loops = []
    for lp in sorted(fdata.get("l", []), key=lambda l: 0 if l.get("t") == "Outer" else 1):
        curves = []
        for c in lp.get("c", []):
            order = int(c["o"])
            cv = np.array([[q[0], q[1], 0.0] for q in c["p"]], dtype=np.float64)
            w = np.array([q[2] if c.get("r") else 1.0 for q in c["p"]], dtype=np.float64)
            cv, w, kn = clamp_curve(cv, w, _full_knots(c["k"]), order)
            curves.append({"o": order, "k": [float(k) for k in kn],
                           "p": [[float(x), float(y), float(ww)] for (x, y, _), ww in zip(cv, w)]})
        if reverse:
            rev = []
            for c in reversed(curves):
                k = c["k"]
                k0, k1 = k[0], k[-1]
                rev.append({"o": c["o"], "k": [k0 + k1 - x for x in reversed(k)],
                            "p": [[a + b - u, v, ww] for u, v, ww in reversed(c["p"])]})
            curves = rev
        for c in curves:
            c["p"] = [[u - su, v - sv, ww] for u, v, ww in c["p"]]
        loops.append({"t": lp.get("t", ""), "c": curves})
    return loops


def _face_nurbs(face, fi, opt, trims, stats, untrimmed):
    """NURBS-грань: точная (необрезанная или с кривыми обрезки) либо None, если обрезки нет."""
    rev = houdini_reverse(face.OrientationIsReversed)
    srf = face.UnderlyingSurface()
    d = nurbs_surface_data(srf, reverse=rev)
    if d is None:
        return None
    d.update({"t": "nsurf", "face": fi, "trimmed": not untrimmed})
    if untrimmed:
        return d
    fdata = trims.get(fi) if trims else None
    if fdata is None:
        return None
    ns = srf.ToNurbsSurface()
    dom = ns.Domain(0)
    S = None
    if any(c.get("r") for lp in fdata.get("l", []) for c in lp.get("c", [])):
        S = surface_evaluator(nurbs_surface_data(srf, reverse=False))   # допуск — в пространстве модели
    d["trims"] = face_profile_loops(fdata, rev, (dom.T0, dom.T1), opt.trimtol, S)
    # точные петли (с весами) в UV примитива Houdini — для экспорта (обрезанная плоскость, пересборка в Rhino)
    import json
    d["trim_loops"] = json.dumps(face_trim_loops_exact(fdata, rev, (dom.T0, dom.T1),
                                                       float(d["knots_u"][0]), float(d["knots_v"][0])),
                                 separators=(",", ":"))
    d["rhino_area"] = fdata.get("a")
    stats["trimmed_exact"] = stats.get("trimmed_exact", 0) + 1
    return d


def _brep_parts(brep, opt, stats, solid=None):
    """Brep -> части: сетки граней / NURBS-грани (точные, с обрезкой) / кривые границ."""
    r = _r()
    parts = []
    solid = bool(brep.IsSolid) if solid is None else solid
    as_nurbs = opt.surfaces_as_nurbs(solid)
    trims = brep_trims(brep) if as_nurbs and opt.geomode != "legacy" else None
    for fi in range(len(brep.Faces)):
        face = brep.Faces[fi]
        try:
            untrimmed = face.DuplicateFace(False).IsSurface
        except Exception:
            untrimmed = False
        if as_nurbs:
            if opt.geomode == "legacy":
                if untrimmed or opt.trimnurbs:
                    d = _face_nurbs(face, fi, opt, None, stats, True)
                    if d is not None:
                        d["trimmed"] = not untrimmed
                        parts.append(d)
                        if not untrimmed:
                            for cd in face_boundary_curves(brep, face):
                                cd.update({"t": "ncurve", "face": fi, "trim": True})
                                parts.append(cd)
                        continue
            else:
                d = _face_nurbs(face, fi, opt, trims, stats, untrimmed)
                if d is not None:
                    parts.append(d)
                    continue
                # обрезанная грань без кривых обрезки (файл не подготовлен в Rhino):
                # необрезанная поверхность + кривые границ, с предупреждением
                d = _face_nurbs(face, fi, opt, None, stats, True)
                if d is not None:
                    d["trimmed"] = True
                    parts.append(d)
                    for cd in face_boundary_curves(brep, face):
                        cd.update({"t": "ncurve", "face": fi, "trim": True})
                        parts.append(cd)
                    stats["trimmed_untrimmed"] = stats.get("trimmed_untrimmed", 0) + 1
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
    if as_nurbs:
        # отпечаток исходной обрезки граней: экспорт проверяет, что исходный файл с импорта не менялся
        src_tr = trims if trims is not None else brep_trims(brep)
        for p in parts:
            if p.get("t") == "nsurf" and p.get("face", -1) >= 0:
                p["src_trim_hash"] = face_trims_hash(src_tr.get(p["face"]) if src_tr else None)
    return parts


def geometry_parts(g, opt, stats):
    """Геометрия одного объекта -> список частей в мировых координатах (или локальных — для блоков)."""
    r = _r()
    k = geometry_kind(g)
    if isinstance(g, r.Brep):
        return _brep_parts(g, opt, stats)
    if isinstance(g, r.Extrusion):
        solid = bool(g.IsSolid)
        as_nurbs = opt.surfaces_as_nurbs(solid)
        m = g.GetMesh(r.MeshType.Any) if (opt.rendermesh and not as_nurbs) else None
        if m is not None:
            v, faces, _ = mesh_arrays(m)
            return [{"t": "mesh", "v": v, "f": faces, "face": -1}]
        b = g.ToBrep(True)
        if b is None:
            return []
        local = {}
        parts = _brep_parts(b, opt, local, solid)
        for key, val in local.items():
            if key != "faces_without_mesh":
                stats[key] = stats.get(key, 0) + val
        if local.get("faces_without_mesh"):
            # торцы — обрезанные плоскости без сетки: берём сетку всего объекта
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
        d.update({"t": "nsurf", "face": 0, "trimmed": False, "to_polys": not opt.surfaces_as_nurbs(False)})
        return [d]
    if isinstance(g, r.Mesh):
        res = mesh_arrays(g, colors=True)
        if res is None:
            return []
        if opt.geomode == "all_nurbs":
            stats["mesh_not_nurbs"] = stats.get("mesh_not_nurbs", 0) + 1
        v, faces, vc = res
        return [{"t": "mesh", "v": v, "f": faces, "face": -1, "vc": vc}]
    if isinstance(g, r.SubD):
        m = r.Mesh.CreateFromSubDControlNet(g, False)
        res = mesh_arrays(m)
        if res is None:
            return []
        if opt.geomode in ("all_nurbs", "nurbs_surfaces"):
            stats["subd_not_prepared"] = stats.get("subd_not_prepared", 0) + 1
        return [{"t": "mesh", "v": res[0], "f": res[1], "face": -1, "subd": True}]
    if isinstance(g, r.Curve):
        is_line = isinstance(g, (r.LineCurve, r.PolylineCurve))
        if opt.curves == "poly" or (is_line and not opt.lines_as_nurbs):
            v = sample_curve(g, opt.curvetol)
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


def type_allowed(g, opt):
    kind = geometry_kind(g)
    typ = KIND_TYPE.get(kind)
    if typ is None and isinstance(g, _r().Curve):
        typ = "curves"
    return typ is None or typ in opt.types


def visibility_allowed(tables, a, skiphidden, skiplocked):
    """Скрытый/заблокированный слой (с учётом родителей) или объект."""
    vis, locked = tables.layer_visible(a.LayerIndex)
    mode = enum_name(a.Mode)
    if skiphidden and (not vis or not a.Visible or mode == "Hidden"):
        return False
    if skiplocked and (locked or mode == "Locked"):
        return False
    return True


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
        if not type_allowed(o.Geometry, opt):
            continue
        if not visibility_allowed(tables, a, opt.skiphidden, opt.skiplocked):
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
            # содержимое блоков: те же фильтры типов и видимости слоёв, что у объектов модели
            # (глобы слоёв относятся только к объектам модели — вставка уже прошла фильтр)
            if not type_allowed(o.Geometry, opt):
                continue
            if not visibility_allowed(tables, o.Attributes, opt.skiphidden, opt.skiplocked):
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

def info_records(f, tables, want, layer_ok=None, skiphidden=False, skiplocked=False):
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
        if not visibility_allowed(tables, a, skiphidden, skiplocked):
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

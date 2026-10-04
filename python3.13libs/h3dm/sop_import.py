# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой импорта: .3dm -> геометрия Houdini.

Вызывается из Python SOP внутри HDA h3dm::3dm_import:
    m.cook(hou.pwd(), output=0)   # геометрия
    m.cook(hou.pwd(), output=1)   # Info: тексты, метки, размеры, точки, свет, вставки блоков
    m.cook(hou.pwd(), output=2)   # Xform: одна точка с глобальным трансформом (для экспорта и других импортов)
Вход 0 HDA (необязательный) — выход Xform другого импорта: тогда сдвиг берётся оттуда (общая привязка файлов).

Глобальный трансформ считается в float64 (h3dm.xform) ДО записи позиций во float32.
"""
import os
import re
import tempfile

import hou
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()

_CACHE = {}          # (путь, mtime, размер) -> File3dm
_CACHE_MAX = 2

GROUP_TRIM = "rhino_trim_curves"
GROUP_TRIMMED = "rhino_trimmed_surfaces"
GROUP_SUBD = "rhino_subd"
GROUP_INSTANCES = "rhino_instances"
RESERVED = {"P", "Pw", "N", "Cd", "Alpha", "uv", "v", "id", "name", "layer", "path", "material", "user_text",
            "rhino_id", "rhino_type", "rhino_face", "block", "layer_orig", "name_orig", "transform", "orient",
            "pscale", "scale", "up", "text", "type"}
# id — частый ключ User Text; он не конфликтует с геометрией Houdini, но имя «id» у точек занято системой частиц
RESERVED_UT = RESERVED - {"id"}


# ---------------------------------------------------------------- параметры

def _owner(node):
    p = node.parent()
    if p is not None and p.type().name().startswith("h3dm::3dm_import"):
        return p
    return node


def _ev(owner, name, default):
    p = owner.parm(name)
    if p is None:
        return default
    try:
        return p.evalAsString() if isinstance(default, str) else type(default)(p.eval())
    except Exception:
        return default


def _evt(owner, name, default=(0.0, 0.0, 0.0)):
    t = owner.parmTuple(name)
    return tuple(t.eval()) if t is not None else default


def read_options(owner):
    from .rhino_read import Options
    o = Options()
    o.surfout = _ev(owner, "surfout", "nurbs")
    o.trimnurbs = bool(_ev(owner, "trimnurbs", 0))
    o.rendermesh = bool(_ev(owner, "rendermesh", 1))
    o.curves = _ev(owner, "curves", "nurbs")
    o.blocks = _ev(owner, "blocks", "packed")
    o.layers = _ev(owner, "layers", "*")
    o.skiphidden = bool(_ev(owner, "skiphidden", 0))
    o.skiplocked = bool(_ev(owner, "skiplocked", 0))
    o.types = {t for t, parm in (("surfaces", "t_surfaces"), ("meshes", "t_meshes"), ("subd", "t_subd"),
                                 ("curves", "t_curves"), ("points", "t_points"), ("blocks", "t_blocks"))
               if _ev(owner, parm, 1)}
    o.weld = bool(_ev(owner, "weld", 1))
    o.subd = _ev(owner, "subd", "cage")
    o.subdlevel = _ev(owner, "subdlevel", 2)
    o.nonlatin = _ev(owner, "nonlatin", "translit_keep")
    o.layercase = _ev(owner, "layercase", "keep")
    o.layersep = _ev(owner, "layersep", "::") or "::"
    o.pathattr = bool(_ev(owner, "pathattr", 1))
    o.colormode = _ev(owner, "colormode", "display")
    o.usertext = bool(_ev(owner, "usertext", 1))
    o.utflat = bool(_ev(owner, "utflat", 1))
    o.utnumbers = bool(_ev(owner, "utnumbers", 1))
    o.groups = bool(_ev(owner, "groups", 1))
    o.materials = bool(_ev(owner, "materials", 1))
    o.yup = bool(_ev(owner, "yup", 1))
    o.scale = _ev(owner, "scale", 1.0)
    o.xformmode = _ev(owner, "xformmode", "auto_far")
    o.roundto = _ev(owner, "roundto", 1.0)
    o.farthreshold = _ev(owner, "farthreshold", 1000.0)
    o.manualorigin = _evt(owner, "manualorigin")
    return o


# ---------------------------------------------------------------- файл и кэш

def open_file(path):
    from . import rhino_read
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    f = _CACHE.get(key)
    if f is None:
        f = rhino_read.read(path)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = f
    return f


def clear_cache(kwargs=None):
    _CACHE.clear()
    _BBOX.clear()
    if kwargs and kwargs.get("node") is not None:
        n = kwargs["node"]
        for child in ("GEO", "INFO", "XFORM"):
            c = n.node(child)
            if c is not None:
                c.cook(force=True)


_BBOX = {}


def _file_bbox(path, f):
    from . import rhino_read
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    if key not in _BBOX:
        _BBOX[key] = rhino_read.file_bbox(f)
    return _BBOX[key]


# ---------------------------------------------------------------- глобальный трансформ

def xform_from_geometry(geo):
    """GlobalXform из геометрии (detail или первая точка: d@h3dm_xform)."""
    from .xform import GlobalXform
    if geo is None:
        return None
    a = geo.findGlobalAttrib("h3dm_xform")
    if a is not None:
        return GlobalXform.from_dict(geo.dictAttribValue("h3dm_xform"))
    a = geo.findPointAttrib("h3dm_xform")
    if a is not None and geo.intrinsicValue("pointcount") > 0:
        return GlobalXform.from_dict(geo.iterPoints()[0].dictAttribValue("h3dm_xform"))
    return None


def resolve_xform(node, opt, path, f):
    """Сдвиг: со входа (если подключён Xform) или по режиму."""
    from . import rhino_read
    from .xform import GlobalXform, choose_origin
    d = rhino_read.doc_info(f)
    inp = None
    try:
        ins = node.inputs()
        if ins and ins[0] is not None:
            inp = xform_from_geometry(ins[0].geometry())
    except Exception:
        inp = None
    if inp is not None:
        if abs(inp.unit_m - d["unit_m"]) > 1e-12:
            # другой файл в других единицах: origin пересчитываем в единицы этого файла
            inp.origin = inp.origin * inp.unit_m / d["unit_m"]
        inp.unit_m = d["unit_m"]
        inp.units = d["units"]
        inp.scale, inp.yup = opt.scale, opt.yup     # оси и масштаб — с этой ноды
        inp.source = "input"
        return inp
    bbox = _file_bbox(path, f) if opt.xformmode in ("auto", "auto_far") else None
    origin, src = choose_origin(opt.xformmode, bbox, d["unit_m"], opt.roundto, opt.farthreshold,
                                base_point=d["base_point"], manual=opt.manualorigin)
    return GlobalXform(origin, d["unit_m"], opt.scale, opt.yup, src, d["units"])


# ---------------------------------------------------------------- атрибуты: помощники

def _attr(geo, cls, name, default):
    finder = {hou.attribType.Prim: geo.findPrimAttrib, hou.attribType.Point: geo.findPointAttrib,
              hou.attribType.Global: geo.findGlobalAttrib}[cls]
    a = finder(name)
    if a is None:
        a = geo.addAttrib(cls, name, default)
    return a


def _set_strings(geo, cls, name, values):
    _attr(geo, cls, name, "")
    if cls == hou.attribType.Prim:
        geo.setPrimStringAttribValues(name, values)
    else:
        geo.setPointStringAttribValues(name, values)


def _set_floats(geo, cls, name, values, size=1, default=0.0):
    _attr(geo, cls, name, (default,) * size if size > 1 else default)
    buf = np.ascontiguousarray(values, dtype=np.float32).tobytes()
    if cls == hou.attribType.Prim:
        geo.setPrimFloatAttribValuesFromString(name, buf)
    else:
        geo.setPointFloatAttribValuesFromString(name, buf)


def _set_ints(geo, cls, name, values):
    _attr(geo, cls, name, 0)
    buf = np.ascontiguousarray(values, dtype=np.int32).tobytes()
    if cls == hou.attribType.Prim:
        geo.setPrimIntAttribValuesFromString(name, buf)
    else:
        geo.setPointIntAttribValuesFromString(name, buf)


def _set_dicts(geo, cls, name, values):
    _attr(geo, cls, name, {})
    setter = getattr(geo, "setPrimDictAttribValues" if cls == hou.attribType.Prim else "setPointDictAttribValues", None)
    if setter is not None:
        try:
            setter(name, values)
            return
        except Exception:
            pass
    items = geo.iterPrims() if cls == hou.attribType.Prim else geo.iterPoints()
    for el, v in zip(items, values):
        el.setAttribValue(name, v)


def _detail(geo, name, value):
    if isinstance(value, dict):
        _attr(geo, hou.attribType.Global, name, {})
    elif isinstance(value, (list, tuple)) and value and isinstance(value[0], dict):
        if geo.findGlobalAttrib(name) is None:
            geo.addArrayAttrib(hou.attribType.Global, name, hou.attribData.Dict)
    elif isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
        if geo.findGlobalAttrib(name) is None:
            geo.addArrayAttrib(hou.attribType.Global, name, hou.attribData.String)
    elif isinstance(value, str):
        _attr(geo, hou.attribType.Global, name, "")
    elif isinstance(value, float):
        _attr(geo, hou.attribType.Global, name, 0.0)
    elif isinstance(value, int):
        _attr(geo, hou.attribType.Global, name, 0)
    elif isinstance(value, (list, tuple)):
        _attr(geo, hou.attribType.Global, name, tuple(0.0 for _ in value))
    geo.setGlobalAttribValue(name, value if not isinstance(value, list) or not value or isinstance(value[0], (dict, str))
                             else tuple(value))


def _clean(v):
    """Значения для dict-атрибутов: только JSON-типы."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _write_xform(geo, gx, cls=hou.attribType.Global, point=None):
    d = _clean(gx.as_dict())
    if cls == hou.attribType.Global:
        _detail(geo, "h3dm_xform", d)
        _detail(geo, "h3dm_origin", d["origin_text"])
        _attr(geo, hou.attribType.Global, "global_xform", tuple([0.0] * 16))
        geo.setGlobalAttribValue("global_xform", tuple(gx.global_xform_houdini()))
        try:
            geo.findGlobalAttrib("global_xform").setOption("type", "matrix")
        except Exception:
            pass
    else:
        _attr(geo, hou.attribType.Point, "h3dm_xform", {})
        point.setAttribValue("h3dm_xform", d)
        _attr(geo, hou.attribType.Point, "h3dm_origin", "")
        point.setAttribValue("h3dm_origin", d["origin_text"])
        _attr(geo, hou.attribType.Point, "global_xform", tuple([0.0] * 16))
        point.setAttribValue("global_xform", tuple(gx.global_xform_houdini()))


# ---------------------------------------------------------------- имена

class Naming(object):
    """Имена слоёв/объектов/групп/ключей с транслитом и картой оригиналов."""

    def __init__(self, opt):
        from .names import NameMapper
        self.opt = opt
        self.m = NameMapper(opt.nonlatin, opt.layercase)
        self.keep_orig = opt.nonlatin == "translit_keep"

    def layer(self, full_path):
        out = self.m.layer(full_path, "::")
        if self.opt.layersep != "::":
            out = out.replace("::", self.opt.layersep)
        return out

    def name(self, n):
        return self.m.name(n)

    def group(self, g):
        return self.m.group(g)

    def key(self, k):
        a = self.m.attrib(k)
        return ("ut_" + a) if a in RESERVED_UT else a

    def path(self, layer_full, name, fallback):
        from .names import safe_identifier
        segs = [s.replace("/", "_") for s in self.m.layer(layer_full, "::").split("::") if s]
        leaf = (self.m.name(name) if name else fallback).replace("/", "_")
        return "/" + "/".join(segs + [leaf])


# ---------------------------------------------------------------- построение геометрии

class Builder(object):
    """Собирает части объектов и записывает их в hou.Geometry одним буфером."""

    def __init__(self, gx, opt, tol):
        self.gx, self.opt, self.tol = gx, opt, tol
        self.mesh_v, self.mesh_f, self.mesh_obj, self.mesh_face, self.mesh_subd, self.mesh_vc = [], [], [], [], [], []
        self.nv = 0
        self.poly = []           # (v_h, closed, obj)
        self.nurbs = []          # (item, obj, face, trim, trimmed, to_polys)
        self.cloud = []          # (v_h, colors, obj)
        self.packed = []         # (frozen geo, A, b, obj)

    # --- добавление (v — уже в осях Houdini, float64)
    def add_mesh(self, v, faces, obj, face=-1, subd=False, vc=None):
        base = self.nv
        self.mesh_v.append(v)
        self.mesh_vc.append(vc if vc is not None else None)
        self.nv += len(v)
        for fc in faces:
            # Rhino: против часовой; Houdini: по часовой — разворачиваем
            self.mesh_f.append(tuple(base + i for i in reversed(fc)))
            self.mesh_obj.append(obj)
            self.mesh_face.append(face)
            self.mesh_subd.append(subd)

    def add_parts(self, parts, obj, to_h):
        """parts — части в координатах Rhino; to_h — функция точек Rhino -> Houdini (float64)."""
        meshes = [p for p in parts if p["t"] == "mesh"]
        if self.opt.weld and len(meshes) > 1 and not any(p.get("subd") for p in meshes):
            v, faces, fidx = _weld(meshes, self.tol)
            base = self.nv
            self.mesh_v.append(to_h(v))
            self.mesh_vc.append(None)
            self.nv += len(v)
            for fc, fi in zip(faces, fidx):
                self.mesh_f.append(tuple(base + i for i in reversed(fc)))
                self.mesh_obj.append(obj)
                self.mesh_face.append(fi)
                self.mesh_subd.append(False)
        else:
            for p in meshes:
                self.add_mesh(to_h(p["v"]), p["f"], obj, p.get("face", -1), p.get("subd", False), p.get("vc"))
        for p in parts:
            t = p["t"]
            if t == "poly":
                self.poly.append((to_h(p["v"]), p["closed"], obj))
            elif t == "ncurve":
                item = {"kind": "curve", "cv": to_h(p["cv"]), "w": p["w"], "order": p["order"], "knots": p["knots"]}
                self.nurbs.append((item, obj, p.get("face", -1), bool(p.get("trim")), False, False))
            elif t == "nsurf":
                cv = p["cv"]
                item = {"kind": "surface", "cv": to_h(cv.reshape(-1, 3)).reshape(cv.shape), "w": p["w"],
                        "order_u": p["order_u"], "order_v": p["order_v"], "knots_u": p["knots_u"], "knots_v": p["knots_v"]}
                self.nurbs.append((item, obj, p.get("face", -1), False, bool(p.get("trimmed")), bool(p.get("to_polys"))))
            elif t == "points":
                self.cloud.append((to_h(p["v"]), p.get("c"), obj))

    # --- запись
    def write(self, geo):
        """-> (obj index на примитив, face на примитив, флаги групп) в порядке примитивов geo."""
        prim_obj, prim_face, groups = [], [], {GROUP_TRIM: [], GROUP_TRIMMED: [], GROUP_SUBD: []}
        # 1) полигоны
        if self.mesh_f:
            V = np.concatenate(self.mesh_v).astype(np.float32)
            pts0 = geo.intrinsicValue("pointcount")
            geo.createPoints(V.tolist())
            off = pts0
            polys = [tuple(i + off for i in fc) for fc in self.mesh_f] if off else self.mesh_f
            geo.createPolygons(polys)
            if any(c is not None for c in self.mesh_vc):
                cols = np.ones((len(V), 3), dtype=np.float32)
                k = 0
                for v, c in zip(self.mesh_v, self.mesh_vc):
                    if c is not None:
                        cols[k:k + len(v)] = c[:, :3]
                    k += len(v)
                self._point_cd = (pts0, cols)
            n0 = len(prim_obj)
            prim_obj += self.mesh_obj
            prim_face += self.mesh_face
            groups[GROUP_SUBD] += [n0 + i for i, s in enumerate(self.mesh_subd) if s]
        # 2) открытые/замкнутые полилинии
        for closed in (True, False):
            sel = [(v, o) for v, c, o in self.poly if c == closed]
            if not sel:
                continue
            base = geo.intrinsicValue("pointcount")
            V = np.concatenate([v for v, _ in sel]).astype(np.float32)
            geo.createPoints(V.tolist())
            polys, k = [], base
            for v, _ in sel:
                polys.append(tuple(range(k, k + len(v))))
                k += len(v)
            geo.createPolygons(polys, closed)
            prim_obj += [o for _, o in sel]
            prim_face += [-1] * len(sel)
        # 3) NURBS через JSON-геометрию (точные узлы и веса); поверхности без сетки в файле -> Convert в полигоны
        if self.nurbs:
            keep = [i for i, n in enumerate(self.nurbs) if not n[5]]
            conv = [i for i, n in enumerate(self.nurbs) if n[5]]
            for sel, convert in ((keep, False), (conv, True)):
                if not sel:
                    continue
                ng = _load_nurbs([self.nurbs[i][0] for i in sel])
                if convert:
                    src = _polys_from_nurbs(ng)
                    order = [sel[k] for k in src]
                else:
                    order = sel
                n0 = len(prim_obj)
                geo.merge(ng)
                for k, i in enumerate(order):
                    item, obj, face, trim, trimmed, _ = self.nurbs[i]
                    prim_obj.append(obj)
                    prim_face.append(face)
                    if trim:
                        groups[GROUP_TRIM].append(n0 + k)
                    if trimmed:
                        groups[GROUP_TRIMMED].append(n0 + k)
        # 4) облака точек — отдельные точки без примитивов
        self.cloud_points = []
        for v, c, obj in self.cloud:
            base = geo.intrinsicValue("pointcount")
            geo.createPoints(v.astype(np.float32).tolist())
            self.cloud_points.append((base, len(v), c, obj))
        # 5) packed (блоки, packed per object)
        for frozen, A, b, obj in self.packed:
            pt = geo.createPoint()
            pt.setPosition(hou.Vector3(*[float(x) for x in b]))
            prim = geo.createPackedGeometry(frozen, pt)
            if A is not None:
                _set_packed_transform(prim, A)
            prim_obj.append(obj)
            prim_face.append(-1)
        return prim_obj, prim_face, groups


def _load_nurbs(items):
    """Список NURBS -> hou.Geometry через временный .geo (JSON)."""
    from . import houjson
    tmp = os.path.join(tempfile.gettempdir(), "h3dm_nurbs_%d.geo" % os.getpid())
    houjson.dump(items, tmp)
    ng = hou.Geometry()
    ng.loadFromFile(tmp)
    try:
        os.remove(tmp)
    except Exception:
        pass
    return ng


def _polys_from_nurbs(ng, lod=1.0):
    """NURBS -> полигоны (Convert) на месте; -> индекс исходной поверхности для каждого полигона."""
    n = len(ng.prims())
    a = ng.addAttrib(hou.attribType.Prim, "__h3dm_src", 0)
    ng.setPrimIntAttribValuesFromString("__h3dm_src", np.arange(n, dtype=np.int32).tobytes())
    verb = hou.sopNodeTypeCategory().nodeVerb("convert")
    verb.setParms({"totype": 0, "lodu": lod, "lodv": lod})   # 0 = Polygon
    out = hou.Geometry()
    verb.execute(out, [ng])
    src = np.frombuffer(out.primIntAttribValuesAsString("__h3dm_src"), dtype=np.int32).tolist()
    out.findPrimAttrib("__h3dm_src").destroy()
    ng.clear()
    ng.merge(out)
    return src


def _set_packed_transform(prim, A):
    t = tuple(float(x) for x in np.asarray(A).T.reshape(9))  # Houdini: вектор-строка
    try:
        prim.setIntrinsicValue("transform", t)
    except Exception:
        prim.setTransform(hou.Matrix4([[t[0], t[1], t[2], 0], [t[3], t[4], t[5], 0], [t[6], t[7], t[8], 0], [0, 0, 0, 1]]))


def _weld(meshes, tol):
    """Слить сетки граней одного объекта: общие вершины по координатам (допуск tol, double)."""
    V = np.concatenate([m["v"] for m in meshes])
    q = np.round(V / max(tol, 1e-12)).astype(np.int64)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    first = np.full(len(uniq), -1, dtype=np.int64)
    order = np.arange(len(V))[::-1]
    first[inv[order]] = order
    Vw = V[first]
    faces, fidx, base = [], [], 0
    for m in meshes:
        for fc in m["f"]:
            faces.append(tuple(int(inv[base + i]) for i in fc))
            fidx.append(m.get("face", -1))
        base += len(m["v"])
    return Vw, faces, fidx


# ---------------------------------------------------------------- готовка

def cook(node, output=0):
    geo = node.geometry()
    geo.clear()   # Python SOP начинает с копии своего входа (точки Xform) — она не нужна
    owner = _owner(node)
    path = hou.text.expandString(_ev(owner, "file", ""))
    if not path:
        return
    if not os.path.isfile(path):
        raise hou.NodeError("File not found: %s" % path)
    from . import has_rhino3dm
    if not has_rhino3dm():
        raise hou.NodeError("rhino3dm is not installed. Run H3DM > Install / Update rhino3dm.")
    opt = read_options(owner)
    f = open_file(path)
    gx = resolve_xform(node, opt, path, f)
    if output == 2:
        pt = geo.createPoint()
        _write_xform(geo, gx, hou.attribType.Point, pt)
        _write_xform(geo, gx)
        return
    naming = Naming(opt)
    if output == 1:
        _cook_info(node, geo, f, opt, gx, naming)
        return
    _cook_geometry(node, geo, f, opt, gx, naming)


def _cook_geometry(node, geo, f, opt, gx, naming):
    from . import rhino_read
    tables = rhino_read.Tables(f)
    doc = rhino_read.doc_info(f)
    tol = doc["abs_tolerance"] or 1e-6
    stats = {}
    recs = list(rhino_read.iter_objects(f, opt, tables, stats))
    b = Builder(gx, opt, tol)
    objs = []                      # записи объектов в порядке индексов
    block_cache, frozen_cache = {}, {}

    def add_record(rec, to_h, parent_rec=None):
        oi = len(objs)
        objs.append((rec, parent_rec))
        if opt.surfout == "packed" and parent_rec is None:
            sub = _record_geometry(rec, opt, gx, tol, naming, tables, f, stats, block_cache, frozen_cache)
            if sub is not None:
                bb = sub[1]
                b.packed.append((sub[0], None, bb, oi))
            return
        inst = [p for p in rec["parts"] if p["t"] == "instance"]
        other = [p for p in rec["parts"] if p["t"] != "instance"]
        b.add_parts(other, oi, to_h)
        for p in inst:
            if opt.blocks == "expand":
                _expand_instance(p, to_h, rec, add_record, f, tables, opt, stats, block_cache)
            else:
                frozen = _idef_frozen(p["idef"], f, tables, opt, gx, tol, naming, stats, block_cache, frozen_cache)
                if frozen is not None:
                    A, bb = gx.placement(p["m"]) if parent_rec is None else (None, None)
                    b.packed.append((frozen, A, bb, oi))

    for rec in recs:
        add_record(rec, gx.to_houdini)

    prim_obj, prim_face, groups = b.write(geo)
    _write_prim_attribs(geo, objs, prim_obj, prim_face, groups, opt, naming, tables)
    _write_cloud_attribs(geo, b, objs, opt, naming)
    if getattr(b, "_point_cd", None) is not None:
        start, cols = b._point_cd
        _attr(geo, hou.attribType.Point, "Cd", (1.0, 1.0, 1.0))
        allc = np.ones((geo.intrinsicValue("pointcount"), 3), dtype=np.float32)
        allc[start:start + len(cols)] = cols
        geo.setPointFloatAttribValuesFromString("Cd", allc.tobytes())
    if opt.subd == "smooth" and groups[GROUP_SUBD]:
        _subdivide(geo, opt.subdlevel)

    write_document(geo, f, naming)
    _write_xform(geo, gx)
    warns = list(naming.m.warnings)
    if stats.get("faces_without_mesh"):
        warns.append("%d trimmed faces have no render mesh in the file (saved with Save Small?) and were skipped: "
                     "H3DM tessellation of trimmed faces comes in 0.3. Re-save the file in Rhino with meshes."
                     % stats["faces_without_mesh"])
    if stats.get("skipped_kinds"):
        warns.append("Skipped object types: %s" % ", ".join("%s x%d" % kv for kv in stats["skipped_kinds"].items()))
    if warns:
        _detail(geo, "h3dm_warnings", warns)
        for w in warns[:5]:
            node.addWarning(w)


def _record_geometry(rec, opt, gx, tol, naming, tables, f, stats, block_cache, frozen_cache):
    """Packed per Object: геометрия объекта относительно центра габарита."""
    sub = hou.Geometry()
    bld = Builder(gx, opt, tol)
    pts = [p for p in rec["parts"] if p["t"] in ("mesh", "poly", "points")]
    allv = [p["v"] for p in pts] + [p["cv"].reshape(-1, 3) for p in rec["parts"] if p["t"] in ("ncurve", "nsurf")]
    if not allv and not any(p["t"] == "instance" for p in rec["parts"]):
        return None
    if allv:
        h = gx.to_houdini(np.concatenate(allv))
        center = (h.min(axis=0) + h.max(axis=0)) * 0.5
    else:
        center = gx.to_houdini(rec["parts"][0]["m"][:3, 3].reshape(1, 3))[0]

    def to_h(v):
        return gx.to_houdini(v) - center
    bld.add_parts([p for p in rec["parts"] if p["t"] != "instance"], 0, to_h)
    for p in rec["parts"]:
        if p["t"] == "instance":
            frozen = _idef_frozen(p["idef"], f, tables, opt, gx, tol, naming, stats, block_cache, frozen_cache)
            if frozen is not None:
                A, bb = gx.placement(p["m"])
                bld.packed.append((frozen, A, bb - center, 0))
    bld.write(sub)
    return sub.freeze(True), center


def _idef_frozen(idef_id, f, tables, opt, gx, tol, naming, stats, block_cache, frozen_cache, depth=0):
    """Геометрия определения блока (локальные координаты блока, оси/единицы сцены), один раз на блок."""
    from . import rhino_read
    if idef_id in frozen_cache:
        return frozen_cache[idef_id]
    if depth > 16:
        return None
    recs = rhino_read.block_definition(f, tables, idef_id, opt, stats, block_cache)
    sub = hou.Geometry()
    bld = Builder(gx, opt, tol)
    objs = []
    for rec in recs:
        oi = len(objs)
        objs.append((rec, None))
        bld.add_parts([p for p in rec["parts"] if p["t"] != "instance"], oi, gx.local_to_houdini)
        for p in rec["parts"]:
            if p["t"] == "instance":
                inner = _idef_frozen(p["idef"], f, tables, opt, gx, tol, naming, stats, block_cache, frozen_cache, depth + 1)
                if inner is not None:
                    m = p["m"]
                    C = gx.C
                    A = C @ m[:3, :3] @ C.T
                    bb = gx.local_to_houdini(m[:3, 3].reshape(1, 3))[0]
                    bld.packed.append((inner, A, bb, oi))
    prim_obj, prim_face, groups = bld.write(sub)
    _write_prim_attribs(sub, objs, prim_obj, prim_face, groups, opt, naming, tables)
    d = tables.idefs.get(idef_id)
    _set_strings(sub, hou.attribType.Prim, "block", [d.Name if d is not None else ""] * len(sub.prims()))
    frozen = sub.freeze(True)
    frozen_cache[idef_id] = frozen
    return frozen


def _expand_instance(p, to_h, parent, add_record, f, tables, opt, stats, block_cache, depth=0):
    """Blocks = Expand: объекты определения ставятся в мир (двойная точность), рекурсивно."""
    from . import rhino_read
    if depth > 16:
        return
    m = p["m"]
    d = tables.idefs.get(p["idef"])
    for rec in rhino_read.block_definition(f, tables, p["idef"], opt, stats, block_cache):
        rec2 = dict(rec)
        rec2["block"] = d.Name if d is not None else ""
        rec2["instance_id"] = parent["id"]
        parts2 = []
        for q in rec["parts"]:
            q2 = dict(q)
            if "v" in q2:
                q2["v"] = rhino_read._apply(m, q["v"])
            if "cv" in q2:
                cv = q["cv"]
                q2["cv"] = rhino_read._apply(m, cv.reshape(-1, 3)).reshape(cv.shape)
            if q2["t"] == "instance":
                q2["m"] = m @ q["m"]
            parts2.append(q2)
        rec2["parts"] = [q for q in parts2 if q["t"] != "instance"]
        add_record(rec2, to_h, None)
        for q in parts2:
            if q["t"] == "instance":
                _expand_instance(q, to_h, rec2, add_record, f, tables, opt, stats, block_cache, depth + 1)


def _subdivide(geo, level):
    verb = hou.sopNodeTypeCategory().nodeVerb("subdivide")
    try:
        verb.setParms({"subdivide": GROUP_SUBD, "iterations": int(level)})
        out = hou.Geometry()
        verb.execute(out, [geo])
        geo.clear()
        geo.merge(out)
    except Exception:
        pass


# ---------------------------------------------------------------- атрибуты объектов

def _number(s):
    try:
        return float(str(s).replace(",", ".").strip())
    except Exception:
        return None


def _object_values(objs, opt, naming):
    """Значения атрибутов на объект."""
    out = {"layer": [], "layer_orig": [], "name": [], "name_orig": [], "rhino_id": [], "rhino_type": [],
           "path": [], "Cd": [], "Alpha": [], "material": [], "user_text": [], "block": [], "groups": []}
    for rec, _ in objs:
        lay = naming.layer(rec["layer"])
        nm = naming.name(rec["name"])
        out["layer"].append(lay)
        out["layer_orig"].append(rec["layer"])
        out["name"].append(nm)
        out["name_orig"].append(rec["name"])
        out["rhino_id"].append(rec.get("instance_id") or rec["id"])
        out["rhino_type"].append(rec["kind"])
        out["path"].append(naming.path(rec["layer"], rec["name"], "%s_%s" % (rec["kind"], rec["id"][:8])))
        col = rec["display"] if opt.colormode == "display" else rec["object_color"]
        out["Cd"].append(col[:3])
        out["Alpha"].append(1.0 - float(rec.get("transparency", 0.0)))
        out["material"].append(naming.name(rec["material"]) if rec["material"] else "")
        out["user_text"].append(dict(rec["user_text"]))
        out["block"].append(rec.get("block", ""))
        out["groups"].append(rec["groups"])
    return out


def _write_prim_attribs(geo, objs, prim_obj, prim_face, groups, opt, naming, tables):
    n = len(prim_obj)
    if n == 0:
        return
    vals = _object_values(objs, opt, naming)
    idx = np.asarray(prim_obj, dtype=np.int64)
    P = hou.attribType.Prim

    def per_prim(key):
        col = vals[key]
        return [col[i] for i in idx]

    if len(geo.prims()) != n:
        raise hou.NodeError("internal: primitive count mismatch (%d vs %d)" % (len(geo.prims()), n))
    _set_strings(geo, P, "layer", per_prim("layer"))
    _set_strings(geo, P, "name", per_prim("name"))
    if naming.keep_orig and naming.m.active:
        if any(a != b for a, b in zip(vals["layer"], vals["layer_orig"])):
            _set_strings(geo, P, "layer_orig", per_prim("layer_orig"))
        if any(a != b for a, b in zip(vals["name"], vals["name_orig"])):
            _set_strings(geo, P, "name_orig", per_prim("name_orig"))
    _set_strings(geo, P, "rhino_id", per_prim("rhino_id"))
    _set_strings(geo, P, "rhino_type", per_prim("rhino_type"))
    _set_ints(geo, P, "rhino_face", prim_face)
    if opt.pathattr:
        _set_strings(geo, P, "path", per_prim("path"))
    _set_floats(geo, P, "Cd", np.asarray(vals["Cd"], dtype=np.float32)[idx], 3, 1.0)
    _set_floats(geo, P, "Alpha", np.asarray(vals["Alpha"], dtype=np.float32)[idx], 1, 1.0)
    if opt.materials and any(vals["material"]):
        _set_strings(geo, P, "material", per_prim("material"))
    if any(vals["block"]):
        _set_strings(geo, P, "block", per_prim("block"))
    _write_user_text(geo, P, vals["user_text"], idx, opt, naming)
    if opt.groups:
        by_group = {}
        for pi, oi in enumerate(prim_obj):
            for g in vals["groups"][oi]:
                by_group.setdefault(g, []).append(pi)
        _make_groups(geo, by_group, naming)
    prims = None
    for gname, members in groups.items():
        if members:
            prims = prims or geo.prims()
            grp = geo.findPrimGroup(gname) or geo.createPrimGroup(gname)
            grp.add([prims[i] for i in members])


def _make_groups(geo, by_group, naming):
    prims = geo.prims()
    for g, members in by_group.items():
        name = naming.group(g)
        grp = geo.findPrimGroup(name) or geo.createPrimGroup(name)
        grp.add([prims[i] for i in members])


def _write_user_text(geo, cls, ut_list, idx, opt, naming):
    if not any(ut_list):
        return
    if opt.usertext:
        _set_dicts(geo, cls, "user_text", [ut_list[i] for i in idx])
    if not opt.utflat:
        return
    keys = []
    for d in ut_list:
        for k in d:
            if k not in keys:
                keys.append(k)
    for k in keys:
        col = [d.get(k) for d in ut_list]
        attr = naming.key(k)
        nums = [_number(v) for v in col if v is not None]
        if opt.utnumbers and nums and all(x is not None for x in nums):
            arr = np.array([(_number(v) if v is not None else 0.0) for v in col], dtype=np.float64)
            _set_floats(geo, cls, attr, arr[idx], 1, 0.0)
        else:
            _set_strings(geo, cls, attr, [(col[i] or "") for i in idx])


def _write_cloud_attribs(geo, b, objs, opt, naming):
    """Облака точек: атрибуты объекта на точках (у точек нет примитивов)."""
    if not b.cloud_points:
        return
    npts = geo.intrinsicValue("pointcount")
    vals = _object_values(objs, opt, naming)
    lay = [""] * npts
    nam = [""] * npts
    rid = [""] * npts
    cd = None
    for base, n, c, oi in b.cloud_points:
        for i in range(base, base + n):
            lay[i], nam[i], rid[i] = vals["layer"][oi], vals["name"][oi], vals["rhino_id"][oi]
        if c is not None:
            if cd is None:
                cd = np.ones((npts, 3), dtype=np.float32)
            cd[base:base + n] = c[:, :3]
    T = hou.attribType.Point
    _set_strings(geo, T, "layer", lay)
    _set_strings(geo, T, "name", nam)
    _set_strings(geo, T, "rhino_id", rid)
    if cd is not None:
        _set_floats(geo, T, "Cd", cd, 3, 1.0)
    grp = geo.findPointGroup("rhino_point_clouds") or geo.createPointGroup("rhino_point_clouds")
    pts = geo.points()
    grp.add([pts[i] for base, n, _, _ in b.cloud_points for i in range(base, base + n)])


# ---------------------------------------------------------------- Info

def _cook_info(node, geo, f, opt, gx, naming):
    from . import rhino_read
    owner = _owner(node)
    want = {k for k, parm in (("dots", "i_dots"), ("text", "i_text"), ("dims", "i_dims"), ("points", "i_points"),
                               ("lights", "i_lights"), ("blocks", "i_blocks")) if _ev(owner, parm, 1 if k != "blocks" else 0)}
    tables = rhino_read.Tables(f)
    recs = rhino_read.info_records(f, tables, want, rhino_read.layer_filter(opt.layers), opt.skiphidden)
    if not recs:
        return
    P = np.array([r["P"] for r in recs], dtype=np.float64)
    H = gx.to_houdini(P).astype(np.float32)
    geo.createPoints(H.tolist())
    T = hou.attribType.Point
    objs = [(r, None) for r in recs]
    vals = _object_values(objs, opt, naming)
    idx = np.arange(len(recs))
    _set_strings(geo, T, "info_type", [r["type"] for r in recs])
    _set_strings(geo, T, "text", [r.get("text", "") for r in recs])
    _set_strings(geo, T, "layer", vals["layer"])
    _set_strings(geo, T, "name", vals["name"])
    if naming.keep_orig and naming.m.active and any(a != b for a, b in zip(vals["layer"], vals["layer_orig"])):
        _set_strings(geo, T, "layer_orig", vals["layer_orig"])
    _set_strings(geo, T, "rhino_id", vals["rhino_id"])
    _set_strings(geo, T, "rhino_type", vals["rhino_type"])
    _set_floats(geo, T, "Cd", np.asarray(vals["Cd"], dtype=np.float32), 3, 1.0)
    if any(r.get("text2") for r in recs):
        _set_strings(geo, T, "text2", [r.get("text2", "") for r in recs])
    if any(r.get("rich_text") for r in recs):
        _set_strings(geo, T, "rich_text", [r.get("rich_text", "") for r in recs])
    if any("height" in r for r in recs):
        _set_floats(geo, T, "text_height", [float(r.get("height", 0.0)) * gx.s for r in recs])
    if any(r.get("font") for r in recs):
        _set_strings(geo, T, "font", [r.get("font", "") for r in recs])
    if any(r.get("measurement") is not None for r in recs):
        _set_floats(geo, T, "measurement", [float(r["measurement"]) * gx.unit_m if r.get("measurement") is not None
                                            else 0.0 for r in recs])
    # ориентация плоскостей текстов/размеров: N и up
    if any("plane" in r for r in recs):
        Nn = np.zeros((len(recs), 3))
        Up = np.zeros((len(recs), 3))
        for i, r in enumerate(recs):
            pl = r.get("plane")
            if pl is not None:
                Nn[i] = (pl.ZAxis.X, pl.ZAxis.Y, pl.ZAxis.Z)
                Up[i] = (pl.YAxis.X, pl.YAxis.Y, pl.YAxis.Z)
            else:
                Nn[i], Up[i] = (0, 0, 1), (0, 1, 0)
        _set_floats(geo, T, "N", gx.vectors_to_houdini(Nn), 3)
        _set_floats(geo, T, "up", gx.vectors_to_houdini(Up), 3)
    if any(r["type"] == "light" for r in recs):
        _set_strings(geo, T, "light_style", [r.get("light_style", "") for r in recs])
        _set_floats(geo, T, "light_color", [r.get("light_color", (1, 1, 1, 1))[:3] for r in recs], 3)
        _set_floats(geo, T, "intensity", [r.get("intensity", 0.0) for r in recs])
        _set_floats(geo, T, "direction", gx.vectors_to_houdini([r.get("direction", (0, 0, 0)) for r in recs]), 3)
    if any(r["type"] == "block" for r in recs):
        tr = np.zeros((len(recs), 9), dtype=np.float32)
        for i, r in enumerate(recs):
            if r["type"] == "block":
                A, _ = gx.placement(r["matrix"])
                tr[i] = A.T.reshape(9)
            else:
                tr[i] = np.eye(3).reshape(9)
        _set_floats(geo, T, "transform", tr, 9)
    _write_user_text(geo, T, vals["user_text"], idx, opt, naming)
    for r_type in sorted({r["type"] for r in recs}):
        grp = geo.createPointGroup("rhino_" + r_type)
        pts = geo.points()
        grp.add([pts[i] for i, r in enumerate(recs) if r["type"] == r_type])
    _write_xform(geo, gx)


# ---------------------------------------------------------------- документ

def write_document(geo, f, naming=None):
    from . import rhino_read
    d = rhino_read.doc_info(f)
    _detail(geo, "rhino_doc", _clean(d))
    _detail(geo, "rhino_units", d["units"])
    _detail(geo, "rhino_unit_m", float(d["unit_m"]))
    _detail(geo, "rhino_doc_text", rhino_read.doc_strings(f))
    _detail(geo, "rhino_layers", _clean(rhino_read.layers(f)) or [{}])
    _detail(geo, "rhino_materials", _clean(rhino_read.materials(f)) or [{}])
    _detail(geo, "rhino_groups", _clean(rhino_read.groups(f)) or [{}])
    _detail(geo, "rhino_blocks", _clean(rhino_read.instance_definitions(f)) or [{}])
    if naming is not None and naming.m.map:
        _detail(geo, "h3dm_name_map", dict(naming.m.map))


def info_text(kwargs):
    """Кнопка File Info."""
    from . import rhino_read
    node = kwargs["node"]
    path = hou.text.expandString(node.parm("file").evalAsString())
    try:
        txt = rhino_read.file_info(path)
    except Exception as ex:
        txt = "Cannot read file:\n%s" % ex
    if hou.isUIAvailable():
        hou.ui.displayMessage(txt.split("\n\nLayer tree:")[0], title="H3DM File Info", details=txt,
                              details_label="Full report", details_expanded=False)
    else:
        print(txt)
    return txt

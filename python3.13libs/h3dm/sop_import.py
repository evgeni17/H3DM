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
import itertools
import os
import time
import re
import tempfile

import hou
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()

_CACHE = {}          # (путь, mtime, размер) -> File3dm
_CACHE_MAX = 2
_FILE_PATH = {}      # id(File3dm) -> путь (файл источника для экспорта: защита от перезаписи)

GROUP_TRIM = "rhino_trim_curves"
GROUP_TRIMMED = "rhino_trimmed_surfaces"      # обрезанная грань, пришедшая БЕЗ обрезки (+ кривые границ)
GROUP_TRIMMED_EXACT = "rhino_trimmed_exact"   # точная обрезанная NURBS (кривые обрезки из подготовки в Rhino)
GROUP_SUBD = "rhino_subd"
GROUP_INSTANCES = "rhino_instances"
# группы по фактическому типу примитива на выходе (после всех преобразований); префикс зарезервирован
TYPE_GROUPS = {"Poly": "h3dm_type_polygon", "NURBCurve": "h3dm_type_nurbs_curve",
               "NURBMesh": "h3dm_type_nurbs_surface", "PackedGeometry": "h3dm_type_packed_geometry"}
TYPE_OTHER = "h3dm_type_other"
RESERVED = {"P", "Pw", "N", "Cd", "Alpha", "uv", "v", "id", "name", "layer", "path", "material", "user_text",
            "rhino_id", "rhino_type", "rhino_face", "block", "rhino_instance_id", "rhino_object_id",
            "rhino_part_path", "rhino_block_path", "rhino_xform", "rhino_trim_loops", "rhino_trim_sig", "rhino_geo_sig", "layer_orig", "name_orig", "transform", "orient",
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
    o.geomode = _ev(owner, "geomode", "legacy")
    o.surfout = _ev(owner, "surfout", "nurbs")
    o.trimnurbs = bool(_ev(owner, "trimnurbs", 0))
    o.pack = bool(_ev(owner, "pack", 0))
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
    o.layerlevels = bool(_ev(owner, "layerlevels", 1))
    o.layerlevelprefix = _level_prefix(_ev(owner, "layerlevelprefix", "LL"))
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
    o.curvetol = _ev(owner, "curvetol", 0.0)
    o.trimtol = _ev(owner, "trimtol", 0.0)
    o.uttextkeys = _ev(owner, "uttextkeys", "")
    return o


def _level_prefix(p):
    from .names import safe_identifier
    return safe_identifier(str(p or "").strip()) or "LL"


# ---------------------------------------------------------------- файл и кэш

def open_file(path):
    from . import rhino_read
    st = os.stat(path)
    key = (path, st.st_mtime, st.st_size)
    f = _CACHE.get(key)
    if f is None:
        f = rhino_read.read(path)
        _FILE_PATH[id(f)] = os.path.abspath(path)
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = f
    return f


def clear_cache(kwargs=None):
    """Reload: перечитать файл; дисковый кэш для следующей готовки ноды пропускается и перезаписывается."""
    _CACHE.clear()
    _BBOX.clear()
    if kwargs and kwargs.get("node") is not None:
        n = kwargs["node"]
        for child in ("GEO", "INFO", "XFORM"):
            c = n.node(child)
            if c is not None:
                _BYPASS.add(c.path())
                c.cook(force=True)


_BYPASS = set()


def clear_disk_cache(kwargs=None):
    """Кнопка Clear Disk Cache: удалить все записи кэша в папке ноды."""
    from . import geocache
    owner = kwargs["node"] if kwargs else None
    cdir = hou.text.expandString(_ev(owner, "cachedir", "") or "") if owner is not None else ""
    d, n, size = geocache.stats(cdir)
    removed = geocache.clear(cdir)
    msg = "H3DM disk cache cleared: %d entries, %.1f MB\n%s" % (n, size / 1048576.0, d)
    if hou.isUIAvailable():
        hou.ui.setStatusMessage(msg.replace("\n", "  "))
    else:
        print(msg)
    return removed


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
    """GlobalXform из геометрии (detail или первая точка: d@h3dm_xform); None, если его нет или он неверный."""
    from .xform import GlobalXform
    if geo is None:
        return None
    d = None
    if geo.findGlobalAttrib("h3dm_xform") is not None:
        d = geo.dictAttribValue("h3dm_xform")
    elif geo.findPointAttrib("h3dm_xform") is not None and geo.intrinsicValue("pointcount") > 0:
        d = geo.iterPoints()[0].dictAttribValue("h3dm_xform")
    if not d or "origin_text" not in d and "origin" not in d:
        return None
    gx = GlobalXform.from_dict(d)
    if gx is None or not (gx.unit_m > 0 and gx.scale > 0):
        return None
    return gx


def _xform_input_connected(node):
    owner = _owner(node)
    try:
        return owner.input(0) is not None if owner is not node else bool(node.inputs() and node.inputs()[0])
    except Exception:
        return False


def resolve_xform(node, opt, path, f):
    """Сдвиг: со входа Xform (если подключён — строго) или по режиму вкладки Global Transform."""
    from . import rhino_read
    from .xform import GlobalXform, choose_origin
    d = rhino_read.doc_info(f)
    if _xform_input_connected(node):
        src = node.inputs()[0].geometry() if node.inputs() and node.inputs()[0] is not None else None
        inp = xform_from_geometry(src)
        if inp is None:
            raise hou.NodeError("The Xform input is connected but carries no valid h3dm_xform. Connect the third "
                                "output (Xform) of another H3DM 3dm Import, or disconnect the input.")
        if abs(inp.unit_m - d["unit_m"]) > 1e-12:
            # другой файл в других единицах: origin пересчитываем в единицы этого файла (масштаб сцены тот же)
            inp.origin = inp.origin * inp.unit_m / d["unit_m"]
            inp.unit_m = d["unit_m"]
        inp.units = d["units"]
        # масштаб и оси — со входа (общее пространство); отличие от своих настроек — предупреждение
        if abs(inp.scale - opt.scale) > 1e-12 or inp.yup != opt.yup:
            inp.warning = ("Scale / axes come from the Xform input (scale %g, %s); this node's Conversion "
                           "settings are ignored." % (inp.scale, "Y-up" if inp.yup else "Z-up"))
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
    # ВНИМАНИЕ: значение по умолчанию у строковых и dict-атрибутов Houdini НЕ применяется к элементам
    # (проверено в 22.0: addAttrib(..., "abc") даёт ""), поэтому значения пишутся всегда явно
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


def _set_dicts_indexed(geo, cls, name, table, idx):
    """dict-атрибут: значение table[idx[k]] на k-й элемент класса cls (Prim или Point).

    В HOM нет пакетной записи dict-атрибутов, поэлементная — секунды на миллион примитивов. Поэтому значения
    пишутся по одному на объект во вспомогательную геометрию и разносятся verb attribcopy
    (Match by Attribute -> To Element по временному индексу объекта)."""
    idx = np.asarray(idx, dtype=np.int64)
    n = len(idx)
    if n == 0:
        return
    k = len(table)
    idx = np.mod(idx, k)                      # -1 = последняя (пустая) запись, как у списков Python
    if n < 2000 or k == 0:
        _set_dicts(geo, cls, name, [table[i] for i in idx.tolist()])
        return
    used = np.unique(idx)
    if len(used) == 1 and not table[int(used[0])]:
        _attr(geo, cls, name, {})             # все пустые — достаточно самого атрибута
        return
    prim = cls == hou.attribType.Prim
    src = hou.Geometry()
    if prim:
        src.createPoints([(0.0, 0.0, 0.0)] * 3)
        src.createPolygons([(0, 1, 2)] * k)
        items = src.prims()
    else:
        src.createPoints([(0.0, 0.0, 0.0)] * k)
        items = src.points()
    src.addAttrib(cls, name, {})
    for i in used.tolist():
        if table[i]:
            items[i].setAttribValue(name, table[i])
    tmp = "__h3dm_oi"
    geo.addAttrib(cls, tmp, 0)
    buf = idx.astype(np.int32).tobytes()
    (geo.setPrimIntAttribValuesFromString if prim else geo.setPointIntAttribValuesFromString)(tmp, buf)
    verb = hou.sopNodeTypeCategory().nodeVerb("attribcopy")
    verb.setParms({"srcgrouptype": 2 if prim else 1, "destgrouptype": 2 if prim else 1, "matchbyattribute": 1,
                   "matchbyattributemethod": 1, "attributetomatch": tmp, "attrib": 2, "attribname": name,
                   "class": 4 if prim else 3, "copyp": 0})
    out = hou.Geometry()
    verb.execute(out, [geo, src])
    geo.clear()
    geo.merge(out)
    a = geo.findPrimAttrib(tmp) if prim else geo.findPointAttrib(tmp)
    if a is not None:
        a.destroy()


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
    """Имена слоёв/объектов/групп/ключей с транслитом и картой оригиналов.

    Все имена файла регистрируются заранее (prepare_*): латинские имена занимаются первыми, и транслит
    не может с ними совпасть; порядок — как в файле, поэтому результат одинаков от готовки к готовке.
    """

    def __init__(self, opt, f=None):
        from .names import NameMapper
        self.opt = opt
        self.m = NameMapper(opt.nonlatin, opt.layercase)
        self.keep_orig = opt.nonlatin == "translit_keep"
        # имена атрибутов уровней слоя (LL0, LL1, ...) заняты: такие ключи User Text получат префикс ut_
        self.reserved = set(RESERVED_UT)
        if getattr(opt, "layerlevels", False):
            self.reserved |= {"%s%d" % (opt.layerlevelprefix, i) for i in range(64)}
        if f is not None:
            self._prepare(f)

    def _prepare(self, f):
        from . import rhino_read
        self.m.prepare_layers([l.FullPath for l in f.Layers])
        names, keys = [], []
        for o in f.Objects:
            a = o.Attributes
            names.append(a.Name or "")
            keys.extend(k for k, _ in (a.GetUserStrings() if a.UserStringCount else ()))
        names += [m.Name or "" for m in f.Materials]
        self.m.prepare_names(names)
        self.m.prepare_groups([g.Name or ("Group%d" % g.Index) for g in f.Groups])
        self.m.prepare_attribs(keys, self.reserved)

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
        return self.m.attrib(k, self.reserved)

    def path(self, layer_full, name, fallback):
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
        flat, lens = _flat_faces(faces)
        n = len(lens)
        self.mesh_f += _faces_out(flat, lens, base)
        self.mesh_obj += [obj] * n
        self.mesh_face += [face] * n
        self.mesh_subd += [subd] * n

    def add_parts(self, parts, obj, to_h):
        """parts — части в координатах Rhino; to_h — функция точек Rhino -> Houdini (float64)."""
        meshes = [p for p in parts if p["t"] == "mesh"]
        if self.opt.weld and len(meshes) > 1 and not any(p.get("subd") for p in meshes):
            v, flat, lens, fidx = _weld(meshes, self.tol)
            base = self.nv
            self.mesh_v.append(to_h(v))
            self.mesh_vc.append(None)
            self.nv += len(v)
            n = len(lens)
            self.mesh_f += _faces_out(flat, lens, base)
            self.mesh_obj += [obj] * n
            self.mesh_face += fidx
            self.mesh_subd += [False] * n
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
                        "trims": p.get("trims"), "trim_loops": p.get("trim_loops"),
                        "src_trim_hash": p.get("src_trim_hash"),
                        "order_u": p["order_u"], "order_v": p["order_v"], "knots_u": p["knots_u"], "knots_v": p["knots_v"]}
                trimmed = (2 if p.get("trims") else 1) if p.get("trimmed") else 0
                self.nurbs.append((item, obj, p.get("face", -1), False, trimmed, bool(p.get("to_polys"))))
            elif t == "points":
                self.cloud.append((to_h(p["v"]), p.get("c"), obj))

    # --- запись
    def write(self, geo):
        """-> (obj index на примитив, face на примитив, флаги групп) в порядке примитивов geo."""
        prim_obj, prim_face, groups = [], [], {GROUP_TRIM: [], GROUP_TRIMMED: [], GROUP_TRIMMED_EXACT: [], GROUP_SUBD: []}
        self.point_colors = []    # (первая точка, цвета (N,3)) — цвета вершин сеток
        self.trim_loop_prims = []  # (примитив, JSON точных петель обрезки)
        self.trim_sig_prims = []   # (примитив, подпись обрезки в Houdini : отпечаток обрезки исходника)
        tg = {}                   # группа типа -> индексы примитивов (известны по порядку записи)

        def typed(name, start, count):
            tg.setdefault(name, []).extend(range(start, start + count))
        self.cloud_points = []    # (первая точка, число, цвета или None, объект)
        # 1) полигоны
        if self.mesh_f:
            V = np.concatenate(self.mesh_v).astype(np.float32)
            pts0 = geo.intrinsicValue("pointcount")
            geo.createPoints(V.tolist())
            off = pts0
            polys = [tuple(i + off for i in fc) for fc in self.mesh_f] if off else self.mesh_f
            geo.createPolygons(polys)
            k = pts0
            for v, c in zip(self.mesh_v, self.mesh_vc):
                if c is not None:
                    self.point_colors.append((k, np.asarray(c, dtype=np.float32)))
                k += len(v)
            n0 = len(prim_obj)
            typed(TYPE_GROUPS["Poly"], n0, len(self.mesh_obj))
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
            typed(TYPE_GROUPS["Poly"], len(prim_obj), len(sel))
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
                    if convert:
                        tg.setdefault(TYPE_GROUPS["Poly"], []).append(n0 + k)
                    else:
                        tg.setdefault(TYPE_GROUPS["NURBMesh" if item["kind"] == "surface" else "NURBCurve"], []).append(n0 + k)
                    prim_obj.append(obj)
                    prim_face.append(face)
                    if trim:
                        groups[GROUP_TRIM].append(n0 + k)
                    if trimmed == 1:
                        groups[GROUP_TRIMMED].append(n0 + k)
                    elif trimmed == 2:
                        groups[GROUP_TRIMMED_EXACT].append(n0 + k)
                        if not convert and item.get("trim_loops"):
                            self.trim_loop_prims.append((n0 + k, _scale_loops(item)))
                    if not convert and item["kind"] == "surface" and item.get("src_trim_hash"):
                        from .houjson import profiles_signature, knot_scale
                        sig = profiles_signature(item.get("trims"), float(item["knots_u"][0]), float(item["knots_v"][0]),
                                                 knot_scale(item["knots_u"]), knot_scale(item["knots_v"]))
                        self.trim_sig_prims.append((n0 + k, sig + ":" + item["src_trim_hash"]))
        # 4) облака точек — отдельные точки без примитивов
        for v, c, obj in self.cloud:
            base = geo.intrinsicValue("pointcount")
            geo.createPoints(v.astype(np.float32).tolist())
            self.cloud_points.append((base, len(v), c, obj))
        # 5) packed (блоки, packed per object)
        self.instance_xforms = []   # (примитив, матрица Rhino 4x4 в double) — экспорт берёт её, если вставку не двигали
        for item in self.packed:
            frozen, A, b, obj = item[:4]
            if len(item) > 4 and item[4] is not None:
                self.instance_xforms.append((len(prim_obj), item[4]))
            pt = geo.createPoint()
            pt.setPosition(hou.Vector3(*[float(x) for x in b]))
            prim = geo.createPackedGeometry(frozen, pt)
            if A is not None:
                _set_packed_transform(prim, A)
            tg.setdefault(TYPE_GROUPS["PackedGeometry"], []).append(len(prim_obj))
            prim_obj.append(obj)
            prim_face.append(-1)
        groups.update(tg)
        return prim_obj, prim_face, groups


def _load_nurbs(items):
    """Список NURBS -> hou.Geometry через временный .bgeo (двоичный JSON Houdini)."""
    from . import houjson
    tmp = os.path.join(tempfile.gettempdir(), "h3dm_nurbs_%d.bgeo" % os.getpid())
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


def _flat_faces(faces):
    """Грани (кортежи по 3–4 индекса) -> (плоский массив индексов, длины граней)."""
    lens = np.fromiter(map(len, faces), dtype=np.int64, count=len(faces))
    flat = np.fromiter(itertools.chain.from_iterable(faces), dtype=np.int64, count=int(lens.sum()))
    return flat, lens


def _faces_out(flat, lens, base):
    """Развернуть обход каждой грани (Rhino — против часовой, Houdini — по часовой), прибавить base."""
    n = len(lens)
    if n == 0:
        return []
    if (lens == lens[0]).all():
        k = int(lens[0])
        return list(map(tuple, (flat.reshape(n, k)[:, ::-1] + base).tolist()))
    starts = np.cumsum(lens) - lens
    rep_s = np.repeat(starts, lens)
    rep_n = np.repeat(lens, lens)
    within = np.arange(len(flat), dtype=np.int64) - rep_s
    out = (flat[rep_s + rep_n - 1 - within] + base).tolist()
    return [tuple(out[a:a + k]) for a, k in zip(starts.tolist(), lens.tolist())]


def _weld(meshes, tol):
    """Слить сетки граней одного объекта: общие вершины по координатам (допуск tol, double).
    -> (вершины, плоские индексы граней, длины граней, номер грани Brep на каждую грань)."""
    V = np.concatenate([m["v"] for m in meshes])
    q = np.round(V / max(tol, 1e-12)).astype(np.int64)
    uniq, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    first = np.full(len(uniq), -1, dtype=np.int64)
    order = np.arange(len(V))[::-1]
    first[inv[order]] = order
    Vw = V[first]
    flats, lens, fidx, base = [], [], [], 0
    for m in meshes:
        fl, ln = _flat_faces(m["f"])
        flats.append(fl + base)
        lens.append(ln)
        fidx += [m.get("face", -1)] * len(ln)
        base += len(m["v"])
    flat = inv[np.concatenate(flats)] if flats else np.zeros(0, dtype=np.int64)
    return Vw, flat, np.concatenate(lens) if lens else np.zeros(0, dtype=np.int64), fidx


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
    from . import rhino3dm_warning
    vw = rhino3dm_warning()               # другая версия rhino3dm — в общее предупреждение ноды
    opt = read_options(owner)
    # дисковый кэш: ключ строится ДО чтения файла (файл при попадании не читается вовсе)
    key = None
    if bool(_ev(owner, "diskcache", 0)):
        from . import geocache
        cdir = hou.text.expandString(_ev(owner, "cachedir", "") or "")
        key = geocache.make_key(path, output, opt, _input_xform_dict(node))
        if node.path() in _BYPASS:
            _BYPASS.discard(node.path())
        else:
            ok, meta = geocache.load(geo, key, cdir)
            if ok:
                text = "\n".join(x for x in (vw, (meta or {}).get("warning")) if x)
                if text:
                    node.addWarning(text)
                return
    t0 = time.time()
    try:
        f = open_file(path)
    except Exception as ex:
        raise hou.NodeError("Cannot read the 3dm file: %s" % ex)
    unit_m = _unit_m(f)
    if opt.curvetol <= 0:
        opt.curvetol = 0.001 / unit_m          # авто: 1 мм в единицах модели
    if opt.trimtol <= 0:
        opt.trimtol = 0.0001 / unit_m          # авто: 0,1 мм в единицах модели
    gx = resolve_xform(node, opt, path, f)
    warning = getattr(gx, "warning", None)
    if output == 2:
        pt = geo.createPoint()
        _write_xform(geo, gx, hou.attribType.Point, pt)
        _write_xform(geo, gx)
        if warning or vw:
            node.addWarning("\n".join(x for x in (vw, warning) if x))
    else:
        naming = Naming(opt, f)
        if output == 1:
            _cook_info(node, geo, f, opt, gx, naming)
            warning = None
            if vw:
                node.addWarning(vw)
        else:
            warning = _cook_geometry(node, geo, f, opt, gx, naming)
    if key is not None and time.time() - t0 >= float(_ev(owner, "cachemin", 0.5)):
        geocache.save(geo, key, {"warning": warning, "file": path, "output": output,
                                 "cook_s": round(time.time() - t0, 3)},
                      cdir, float(_ev(owner, "cachelimit", geocache.DEFAULT_LIMIT_MB)))


def _input_xform_dict(node):
    """Трансформ со входа Xform для ключа кэша (та же строгая проверка, что в resolve_xform)."""
    if not _xform_input_connected(node):
        return None
    src = node.inputs()[0].geometry() if node.inputs() and node.inputs()[0] is not None else None
    inp = xform_from_geometry(src)
    if inp is None:
        raise hou.NodeError("The Xform input is connected but carries no valid h3dm_xform. Connect the third "
                            "output (Xform) of another H3DM 3dm Import, or disconnect the input.")
    return inp.as_dict()


def _unit_m(f):
    from . import rhino_read
    return rhino_read.UNIT_M.get(rhino_read.enum_name(f.Settings.ModelUnitSystem), 1.0) or 1.0


class Context(object):
    """Общие данные одной готовки: файл, таблицы, параметры, кэши блоков."""

    def __init__(self, f, opt, gx, naming):
        from . import rhino_read
        self.f, self.opt, self.gx, self.naming = f, opt, gx, naming
        self.tables = rhino_read.Tables(f)
        self.tol = rhino_read.doc_info(f)["abs_tolerance"] or 1e-6
        self.stats = {}
        self.block_cache = {}      # определения блоков: записи
        self.frozen_cache = {}     # (блок, стиль вставки) -> packed-геометрия
        self.parent_memo = {}


def _cook_geometry(node, geo, f, opt, gx, naming):
    from . import rhino_read
    ctx = Context(f, opt, gx, naming)
    recs = list(rhino_read.iter_objects(f, opt, ctx.tables, ctx.stats))
    b = Builder(gx, opt, ctx.tol)
    objs = []

    def add_record(rec, to_h):
        oi = len(objs)
        objs.append(rec)
        inst = [p for p in rec["parts"] if p["t"] == "instance"]
        other = [p for p in rec["parts"] if p["t"] != "instance"]
        if opt.packed:
            if inst and opt.blocks == "expand":
                # Packed + Expand: каждый объект блока — свой packed-примитив
                if other:
                    _pack_record(b, dict(rec, parts=other), oi, ctx)
                for p in inst:
                    _expand_instance(p, rec, add_record, ctx)
            else:
                _pack_record(b, rec, oi, ctx)
            return
        b.add_parts(other, oi, to_h)
        for p in inst:
            if opt.blocks == "expand":
                _expand_instance(p, rec, add_record, ctx)
            else:
                frozen = _idef_frozen(p["idef"], ctx, rec)
                if frozen is not None:
                    A, bb = gx.placement(p["m"])
                    b.packed.append((frozen, A, bb, oi, p["m"]))

    for rec in recs:
        add_record(rec, gx.to_houdini)

    groups = _emit(geo, b, objs, ctx)
    write_document(geo, f, naming)
    _write_xform(geo, gx)
    if not opt.pack:
        # отпечатки объектов: экспорт быстро узнаёт неизменённые (без сравнения с исходником по точкам)
        from .geosig import write_signatures
        tcg = geo.findPrimGroup(GROUP_TRIM)
        write_signatures(geo, [p.number() for p in tcg.prims()] if tcg is not None else ())
    from . import rhino3dm_warning
    warns = ([rhino3dm_warning()] if rhino3dm_warning() else []) + \
        ([gx.warning] if getattr(gx, "warning", None) else []) + list(naming.m.warnings)
    st = ctx.stats
    if st.get("faces_without_mesh"):
        warns.append("%d trimmed faces have no render mesh in the file (saved with Save Small?) and were skipped. "
                     "Use Prepare in Rhino (or re-save the file in Rhino with render meshes)." % st["faces_without_mesh"])
    if st.get("trimmed_untrimmed"):
        warns.append("%d trimmed faces came as untrimmed NURBS + boundary curves (group rhino_trimmed_surfaces): "
                     "the file has no trim curves. Use Prepare in Rhino for exact trimmed NURBS."
                     % st["trimmed_untrimmed"])
    if st.get("subd_not_prepared"):
        warns.append("%d SubD objects stay meshes: Prepare in Rhino converts SubD to NURBS." % st["subd_not_prepared"])
    if st.get("mesh_not_nurbs"):
        warns.append("%d Rhino meshes stay meshes (a mesh has no NURBS form)." % st["mesh_not_nurbs"])
    if st.get("skipped_kinds"):
        warns.append("Skipped object types: %s" % ", ".join("%s x%d" % kv for kv in st["skipped_kinds"].items()))
    if warns:
        _detail(geo, "h3dm_warnings", warns)
        # Houdini показывает только последнее addWarning — одно сообщение со всеми пунктами
        text = "\n".join(warns[:8]) + ("\n... (%d more in detail h3dm_warnings)" % (len(warns) - 8)
                                         if len(warns) > 8 else "")
        node.addWarning(text)
        return text
    return None


def _scale_loops(item):
    """Точные петли обрезки (JSON, UV примитива от 0) -> в параметре примитива Houdini (узлы поверхности
    масштабированы houjson.safe_knots, если их интервалы слишком малы для Houdini)."""
    import json
    from .houjson import knot_scale
    fu, fv = knot_scale(item["knots_u"]), knot_scale(item["knots_v"])
    if fu == 1.0 and fv == 1.0:
        return item["trim_loops"]
    loops = json.loads(item["trim_loops"])
    for lp in loops:
        for c in lp.get("c", []):
            c["p"] = [[u * fu, v * fv, w] for u, v, w in c["p"]]
    return json.dumps(loops, separators=(",", ":"))


def _emit(geo, b, objs, ctx):
    """Записать собранное в geo: примитивы, атрибуты объектов, облака, цвета точек, SubD."""
    prim_obj, prim_face, groups = b.write(geo)
    if getattr(b, "instance_xforms", None):
        vals = [""] * geo.intrinsicValue("primitivecount")
        for i, m in b.instance_xforms:
            vals[i] = " ".join("%.17g" % float(x) for x in np.asarray(m, dtype=np.float64).reshape(16))
        _set_strings(geo, hou.attribType.Prim, "rhino_xform", vals)
    if getattr(b, "trim_loop_prims", None):
        vals = [""] * geo.intrinsicValue("primitivecount")
        for i, js in b.trim_loop_prims:
            vals[i] = js
        _set_strings(geo, hou.attribType.Prim, "rhino_trim_loops", vals)
    if getattr(b, "trim_sig_prims", None):
        vals = [""] * geo.intrinsicValue("primitivecount")
        for i, sig in b.trim_sig_prims:
            vals[i] = sig
        _set_strings(geo, hou.attribType.Prim, "rhino_trim_sig", vals)
    _write_prim_attribs(geo, objs, prim_obj, prim_face, groups, ctx)
    _write_cloud_attribs(geo, b, objs, ctx)
    _write_point_colors(geo, b, objs, ctx)
    if ctx.opt.subd == "smooth" and groups[GROUP_SUBD]:
        _subdivide(geo, ctx.opt.subdlevel)
    return groups


def _pack_record(b, rec, oi, ctx):
    """Packed per Object: геометрия объекта относительно центра габарита -> packed-примитив в b."""
    gx = ctx.gx
    parts = rec["parts"]
    allv = [p["v"] for p in parts if p["t"] in ("mesh", "poly", "points")] + \
           [p["cv"].reshape(-1, 3) for p in parts if p["t"] in ("ncurve", "nsurf")]
    inst = [p for p in parts if p["t"] == "instance"]
    if not allv and not inst:
        return
    if allv:
        h = gx.to_houdini(np.concatenate(allv))
        center = (h.min(axis=0) + h.max(axis=0)) * 0.5
    else:
        center = gx.to_houdini(inst[0]["m"][:3, 3].reshape(1, 3))[0]
    sub = hou.Geometry()
    bld = Builder(gx, ctx.opt, ctx.tol)
    bld.add_parts([p for p in parts if p["t"] != "instance"], 0, lambda v: gx.to_houdini(v) - center)
    for p in inst:
        frozen = _idef_frozen(p["idef"], ctx, rec)
        if frozen is not None:
            A, bb = gx.placement(p["m"])
            bld.packed.append((frozen, A, bb - center, 0))
    _emit(sub, bld, [rec], ctx)
    b.packed.append((sub.freeze(True), None, center, oi))


def _style_key(rec):
    return (tuple(round(x, 6) for x in rec["display"]), rec.get("material_index", -1))


def _idef_frozen(idef_id, ctx, parent=None, depth=0):
    """Геометрия определения блока (локальные координаты, оси/единицы сцены).

    Одна на блок; если внутри есть объекты «By Parent» — одна на каждый стиль вставки.
    """
    from . import rhino_read
    if depth > 16:
        return None
    by_parent = rhino_read.uses_parent(ctx.f, ctx.tables, idef_id, _memo=ctx.parent_memo)
    key = (idef_id, _style_key(parent)) if (by_parent and parent is not None) else (idef_id, None)
    if key in ctx.frozen_cache:
        return ctx.frozen_cache[key]
    gx = ctx.gx
    recs = rhino_read.block_definition(ctx.f, ctx.tables, idef_id, ctx.opt, ctx.stats, ctx.block_cache)
    d = ctx.tables.idefs.get(idef_id)
    bname = d.Name if d is not None else ""
    sub = hou.Geometry()
    bld = Builder(gx, ctx.opt, ctx.tol)
    objs = []
    for rec in recs:
        rec = dict(rhino_read.apply_parent(rec, parent), block=bname)
        oi = len(objs)
        objs.append(rec)
        bld.add_parts([p for p in rec["parts"] if p["t"] != "instance"], oi, gx.local_to_houdini)
        for p in rec["parts"]:
            if p["t"] == "instance":
                inner = _idef_frozen(p["idef"], ctx, rec, depth + 1)
                if inner is not None:
                    m = p["m"]
                    A = gx.C @ m[:3, :3] @ gx.C.T
                    bb = gx.local_to_houdini(m[:3, 3].reshape(1, 3))[0]
                    bld.packed.append((inner, A, bb, oi, m))
    _emit(sub, bld, objs, ctx)
    frozen = sub.freeze(True)
    ctx.frozen_cache[key] = frozen
    return frozen


def _expand_instance(p, parent, add_record, ctx, depth=0):
    """Blocks = Expand: объекты определения ставятся в мир (двойная точность), рекурсивно.
    Объекты «By Parent» получают цвет/материал своей вставки."""
    from . import rhino_read
    if depth > 16:
        return
    m = p["m"]
    d = ctx.tables.idefs.get(p["idef"])
    for rec in rhino_read.block_definition(ctx.f, ctx.tables, p["idef"], ctx.opt, ctx.stats, ctx.block_cache):
        rec2 = rhino_read.apply_parent(rec, parent)
        rec2 = dict(rec2, block=d.Name if d is not None else "", instance_id=parent.get("instance_id") or parent["id"],
                    # цепочка id объектов определений от вставки верхнего уровня: уникальна внутри вставки,
                    # даже если одно определение вложено несколько раз (экспорт делит по вставке + цепочке)
                    part_chain=list(parent.get("part_chain", [])) + [rec["id"]],
                    block_names=list(parent.get("block_names", [])) + [d.Name if d is not None else ""])
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
        if rec2["parts"]:
            add_record(rec2, ctx.gx.to_houdini)
        for q in parts2:
            if q["t"] == "instance":
                _expand_instance(q, rec2, add_record, ctx, depth + 1)


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

from .names import number_kind as _number_kind  # noqa: E402


def _object_values(objs, opt, naming):
    """Значения атрибутов на объект."""
    out = {k: [] for k in ("layer", "layer_orig", "name", "name_orig", "rhino_id", "rhino_type", "path", "Cd",
                           "Alpha", "material", "user_text", "block", "groups", "instance_id", "object_id",
                           "part_path", "block_path")}
    for rec in objs:
        out["layer"].append(naming.layer(rec["layer"]))
        out["layer_orig"].append(rec["layer"])
        out["name"].append(naming.name(rec["name"]))
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
        out["instance_id"].append(rec.get("instance_id") or "")
        out["object_id"].append(rec["id"] if rec.get("instance_id") else "")
        out["part_path"].append("/".join(rec.get("part_chain", [])))
        out["block_path"].append("/".join(rec.get("block_names", [])))
    return out


def _take(col, idx):
    """[col[i] for i in idx]; для одного объекта на все элементы — без цикла."""
    n = len(idx)
    if n and idx[0] == idx[-1] and (idx == idx[0]).all():
        return [col[int(idx[0])]] * n
    return [col[i] for i in idx.tolist()]


def _write_layer_levels(geo, cls, layers, idx, opt):
    """s@layer по уровням: <prefix>0, <prefix>1, ... (строки; у мелких слоёв глубже — пустые)."""
    if not opt.layerlevels:
        return
    sep = opt.layersep or "::"
    splits = [l.split(sep) if l else [] for l in layers]
    depth = max((len(x) for x in splits), default=0)
    idx = np.asarray(idx, dtype=np.int64)
    for d in range(depth):
        col = [x[d] if d < len(x) else "" for x in splits]
        _set_strings(geo, cls, "%s%d" % (opt.layerlevelprefix, d), _take(col, idx))


def _write_object_attribs(geo, cls, vals, idx, ctx, with_color=True):
    """Атрибуты объектов на элементы класса cls; idx — индекс объекта для каждого элемента."""
    opt, naming = ctx.opt, ctx.naming
    idx = np.asarray(idx, dtype=np.int64)

    def per(key):
        return _take(vals[key], idx)

    _set_strings(geo, cls, "layer", per("layer"))
    _write_layer_levels(geo, cls, vals["layer"], idx, opt)
    _set_strings(geo, cls, "name", per("name"))
    if naming.keep_orig and naming.m.active:
        if any(a != b for a, b in zip(vals["layer"], vals["layer_orig"])):
            _set_strings(geo, cls, "layer_orig", per("layer_orig"))
        if any(a != b for a, b in zip(vals["name"], vals["name_orig"])):
            _set_strings(geo, cls, "name_orig", per("name_orig"))
    _set_strings(geo, cls, "rhino_id", per("rhino_id"))
    _set_strings(geo, cls, "rhino_type", per("rhino_type"))
    if opt.pathattr:
        _set_strings(geo, cls, "path", per("path"))
    if with_color:
        _set_floats(geo, cls, "Cd", np.asarray(vals["Cd"], dtype=np.float32)[idx], 3, 1.0)
        _set_floats(geo, cls, "Alpha", np.asarray(vals["Alpha"], dtype=np.float32)[idx], 1, 1.0)
    if opt.materials and any(vals["material"]):
        _set_strings(geo, cls, "material", per("material"))
    if any(vals["instance_id"]):
        # раскрытые блоки: части одной вставки делят rhino_id (id вставки) — для экспорта нужны и части
        _set_strings(geo, cls, "rhino_instance_id", per("instance_id"))
        _set_strings(geo, cls, "rhino_object_id", per("object_id"))
        _set_strings(geo, cls, "rhino_part_path", per("part_path"))
        _set_strings(geo, cls, "rhino_block_path", per("block_path"))
    if any(vals["block"]):
        _set_strings(geo, cls, "block", per("block"))
    _write_user_text(geo, cls, vals["user_text"], idx, opt, naming)


def _write_prim_attribs(geo, objs, prim_obj, prim_face, groups, ctx):
    n = len(prim_obj)
    if n == 0:
        return
    if geo.intrinsicValue("primitivecount") != n:
        raise hou.NodeError("internal: primitive count mismatch (%d vs %d)" % (geo.intrinsicValue("primitivecount"), n))
    cache = {}

    def prims():
        if "p" not in cache:
            cache["p"] = geo.prims()
        return cache["p"]
    vals = _object_values(objs, ctx.opt, ctx.naming)
    P = hou.attribType.Prim
    _write_object_attribs(geo, P, vals, prim_obj, ctx)
    _set_ints(geo, P, "rhino_face", prim_face)
    if ctx.opt.groups:
        by_group = {}
        for pi, oi in enumerate(prim_obj):
            for g in vals["groups"][oi]:
                by_group.setdefault(g, []).append(pi)
        _make_groups(geo, by_group, ctx.naming, prims)
    for gname, members in groups.items():
        if members:
            _group_add(geo, gname, members, prims)


def _group_add(geo, name, members, prims):
    grp = geo.findPrimGroup(name) or geo.createPrimGroup(name)
    pr = prims()
    if len(members) == len(pr) and members[0] == 0 and members[-1] == len(pr) - 1:
        grp.add(pr)                      # все примитивы (packed-объект) — без построения списка
    else:
        grp.add([pr[i] for i in members])


def _make_groups(geo, by_group, naming, prims=None):
    if prims is None:
        cache = []

        def prims():
            if not cache:
                cache.append(geo.prims())
            return cache[0]
    for g, members in by_group.items():
        _group_add(geo, naming.group(g), members, prims)


def _write_user_text(geo, cls, ut_list, idx, opt, naming):
    if not any(ut_list):
        return
    if opt.usertext:
        _set_dicts_indexed(geo, cls, "user_text", ut_list, idx)
    if not opt.utflat:
        return
    import fnmatch
    text_keys = [g for g in (opt.uttextkeys or "").split() if g]
    keys = []
    for d in ut_list:
        for k in d:
            if k not in keys:
                keys.append(k)
    for k in keys:
        col = [d.get(k) for d in ut_list]
        attr = naming.key(k)
        kind = None
        if opt.utnumbers and not any(fnmatch.fnmatchcase(k, g) for g in text_keys):
            kind = _number_kind(col)
        if kind == "int":
            arr = np.array([int(v) if v not in (None, "") else 0 for v in col], dtype=np.int64)
            _set_ints(geo, cls, attr, arr[idx])
        elif kind == "float":
            arr = np.array([float(v) if v not in (None, "") else 0.0 for v in col], dtype=np.float64)
            _set_floats(geo, cls, attr, arr[idx], 1, 0.0)
        else:
            _set_strings(geo, cls, attr, _take([(v or "") for v in col], np.asarray(idx, dtype=np.int64)))


def _write_cloud_attribs(geo, b, objs, ctx):
    """Облака точек: все атрибуты объекта на точках (у точек нет примитивов)."""
    if not b.cloud_points:
        return
    npts = geo.intrinsicValue("pointcount")
    idx = np.full(npts, -1, dtype=np.int64)
    for base, n, _, oi in b.cloud_points:
        idx[base:base + n] = oi
    sel = np.nonzero(idx >= 0)[0]
    vals = _object_values(objs, ctx.opt, ctx.naming)
    # элементы без объекта получают значения пустой записи (последний индекс)
    blank = {"layer": "", "layer_orig": "", "name": "", "name_orig": "", "rhino_id": "", "rhino_type": "",
             "path": "", "Cd": (1.0, 1.0, 1.0), "Alpha": 1.0, "material": "", "user_text": {}, "block": "", "groups": [],
             "instance_id": "", "object_id": "", "part_path": "", "block_path": ""}
    for k, v in blank.items():
        vals[k] = vals[k] + [v]
    full = np.where(idx >= 0, idx, len(objs))
    _write_object_attribs(geo, hou.attribType.Point, vals, full, ctx, with_color=False)
    grp = geo.findPointGroup("rhino_point_clouds") or geo.createPointGroup("rhino_point_clouds")
    pts = geo.points()
    grp.add([pts[i] for i in sel])


def _write_point_colors(geo, b, objs, ctx):
    """Точечный Cd — только если у сеток есть цвета вершин или у облаков свои цвета.

    Точки без своих цветов получают цвет своего объекта (иначе точечный Cd перекрыл бы Cd примитивов).
    """
    if not b.point_colors and not b.cloud_points:
        return
    npts = geo.intrinsicValue("pointcount")
    if npts == 0:
        return
    cd = np.ones((npts, 3), dtype=np.float32)
    if geo.findPrimAttrib("Cd") is not None and len(geo.prims()):
        verb = hou.sopNodeTypeCategory().nodeVerb("attribpromote")
        verb.setParms({"inname": "Cd", "inclass": 1, "outclass": 2, "method": 8, "useoutname": 1,
                       "outname": "__h3dm_pcd", "deletein": 0})
        tmp = hou.Geometry()
        verb.execute(tmp, [geo])
        if tmp.findPointAttrib("__h3dm_pcd") is not None and tmp.intrinsicValue("pointcount") == npts:
            cd = np.frombuffer(tmp.pointFloatAttribValuesAsString("__h3dm_pcd"), dtype=np.float32).reshape(-1, 3).copy()
    vals = _object_values(objs, ctx.opt, ctx.naming)
    for base, n, c, oi in b.cloud_points:
        cd[base:base + n] = c[:, :3] if c is not None else np.asarray(vals["Cd"][oi], dtype=np.float32)
    for base, cols in b.point_colors:
        cd[base:base + len(cols)] = cols[:, :3]
    _set_floats(geo, hou.attribType.Point, "Cd", cd, 3, 1.0)


# ---------------------------------------------------------------- Info

def _cook_info(node, geo, f, opt, gx, naming):
    from . import rhino_read
    owner = _owner(node)
    want = {k for k, parm in (("dots", "i_dots"), ("text", "i_text"), ("dims", "i_dims"), ("points", "i_points"),
                               ("lights", "i_lights"), ("blocks", "i_blocks")) if _ev(owner, parm, 1 if k != "blocks" else 0)}
    tables = rhino_read.Tables(f)
    recs = rhino_read.info_records(f, tables, want, rhino_read.layer_filter(opt.layers), opt.skiphidden, opt.skiplocked)
    if not recs:
        return
    P = np.array([r["P"] for r in recs], dtype=np.float64)
    H = gx.to_houdini(P).astype(np.float32)
    geo.createPoints(H.tolist())
    T = hou.attribType.Point
    objs = list(recs)
    vals = _object_values(objs, opt, naming)
    idx = np.arange(len(recs))
    _set_strings(geo, T, "info_type", [r["type"] for r in recs])
    _set_strings(geo, T, "text", [r.get("text", "") for r in recs])
    _set_strings(geo, T, "layer", vals["layer"])
    _write_layer_levels(geo, T, vals["layer"], idx, opt)
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

def export_name_maps(f, naming):
    """{'layers': {путь Houdini: путь Rhino}, 'names': {...}, 'groups': {...}, 'keys': {атрибут: ключ User Text}}."""
    out = {"layers": {}, "names": {}, "groups": {}, "keys": {}, "layersep": naming.opt.layersep or "::"}
    for l in f.Layers:
        out["layers"][naming.layer(l.FullPath)] = l.FullPath
    for o in f.Objects:
        a = o.Attributes
        if a.Name:
            out["names"][naming.name(a.Name)] = a.Name
        if a.UserStringCount:
            for k, _ in a.GetUserStrings():
                out["keys"][naming.key(k)] = k
    for m in f.Materials:
        if m.Name:
            out["names"][naming.name(m.Name)] = m.Name
    for g in f.Groups:
        nm = g.Name or ("Group%d" % g.Index)
        out["groups"][naming.group(nm)] = nm
    return out


def write_document(geo, f, naming=None):
    from . import rhino_read
    d = rhino_read.doc_info(f)
    _detail(geo, "rhino_doc", _clean(d))
    _detail(geo, "rhino_units", d["units"])
    _detail(geo, "rhino_unit_m", float(d["unit_m"]))
    _detail(geo, "rhino_doc_text", rhino_read.doc_strings(f))
    stamp = rhino_read.prepare_stamp(f)
    if stamp:
        _detail(geo, "h3dm_prepare", _clean(stamp))
    _detail(geo, "rhino_layers", _clean(rhino_read.layers(f)) or [{}])
    _detail(geo, "rhino_materials", _clean(rhino_read.materials(f)) or [{}])
    _detail(geo, "rhino_groups", _clean(rhino_read.groups(f)) or [{}])
    _detail(geo, "rhino_blocks", _clean(rhino_read.instance_definitions(f)) or [{}])
    if naming is not None and naming.m.map:
        _detail(geo, "h3dm_name_map", dict(naming.m.map))
    if naming is not None:
        # для экспорта: имя в Houdini -> исходное имя Rhino (если имя не меняли — вернётся оригинал)
        _detail(geo, "h3dm_export_names", _clean(export_name_maps(f, naming)))
    _detail(geo, "rhino_file", _FILE_PATH.get(id(f), ""))
    if _FILE_PATH.get(id(f)):
        from .geosig import file_signature, FILE_SIG_ATTR
        _detail(geo, FILE_SIG_ATTR, file_signature(_FILE_PATH[id(f)]))


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

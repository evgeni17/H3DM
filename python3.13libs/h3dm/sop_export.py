# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой экспорта: геометрия Houdini -> .3dm (H3DM 0.4, этап 1).

Кнопки HDA h3dm::3dm_export: Export 3dm (export_node), Check Attributes (check_node), Reveal File.
Логика: collect() собирает план (объекты Rhino с атрибутами, координаты уже в системе файла, double),
write_plan() пишет его через rhino_write. Check Attributes — тот же collect() без записи.

Этап 1: сетки, полилинии, NURBS-кривые, необрезанные NURBS-поверхности, точки/текстовые метки,
атрибуты (слои, имена, цвета, материалы, группы, User Text), обратный глобальный трансформ.
Обрезанные грани пока переводятся в сетку (Houdini Convert учитывает обрезку); точный перенос
неизменённых Brep и пересборка в Rhino — следующие этапы 0.4.
"""
import fnmatch
import os
import re

import hou
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()

# служебные атрибуты импорта — не User Text
SERVICE_ATTRIBS = {"P", "Pw", "N", "Cd", "Alpha", "uv", "v", "w", "id", "layer", "name", "path", "material", "user_text",
                   "block", "layer_orig", "name_orig", "shop_materialpath", "info_type", "text", "text2", "rich_text",
                   "text_height", "measurement", "up", "orient", "transform", "pscale", "scale", "light_style",
                   "light_color", "intensity", "direction", "class", "piece"}
SERVICE_PREFIXES = ("rhino_", "h3dm_", "__")
SERVICE_RE = re.compile(r"^(LL\d+|.*_orig)$")
SERVICE_GROUP_PREFIXES = ("h3dm_type_", "rhino_")
TRIM_GROUPS = ("rhino_trimmed_exact",)                 # обрезанные NURBS с профилями обрезки
UNTRIMMED_APPROX = "rhino_trimmed_surfaces"            # грань без данных обрезки (импорт без подготовки)
TRIM_CURVES = "rhino_trim_curves"                      # вспомогательные кривые границ


class ExportError(Exception):
    pass


# ---------------------------------------------------------------- параметры и трансформ

def _p(node, name, default):
    p = node.parm(name)
    if p is None:
        return default
    v = p.eval()
    if isinstance(default, str) and p.parmTemplate().type() == hou.parmTemplateType.Menu:
        return p.evalAsString()
    return v


def _globs_match(name, pattern):
    """Маски через пробел, ^маска исключает (как в Houdini)."""
    ok = False
    for g in (pattern or "").split():
        if g.startswith("^"):
            if fnmatch.fnmatchcase(name, g[1:]):
                ok = False
        elif fnmatch.fnmatchcase(name, g):
            ok = True
    return ok


def resolve_xform(node, geo, warn):
    """GlobalXform для обратного преобразования. Вход 2 главнее всего; без него — detail входа 1."""
    from .sop_import import xform_from_geometry
    from .xform import GlobalXform
    mode = _p(node, "xformsrc", "input2")
    if mode != "none":
        inp = node.input(1) if len(node.inputs()) > 1 else None
        if mode == "input2" and inp is not None:
            gx = xform_from_geometry(inp.geometry())
            if gx is None:
                raise ExportError("Input 2 (Xform) is connected but carries no valid h3dm_xform. Connect the Xform "
                                  "output of the H3DM 3dm Import, or disconnect the input.")
            gx.source = "input2"
            return gx
        gx = xform_from_geometry(geo)
        if gx is not None:
            gx.source = "detail"
            return gx
        if mode == "detail":
            raise ExportError("Global Transform = From Input 1 Detail, but the geometry has no h3dm_xform.")
    # без трансформа импорта: единицы сцены по параметрам
    scene_m = float(_p(node, "scale", 1.0)) or 1.0           # метров в единице сцены
    unit = _p(node, "unit", "source")
    from .rhino_write import UNITS
    unit_m = UNITS.get(unit if unit != "source" else "mm")[1]
    warn.append("No h3dm_xform: positions are taken as scene units (%g m each), %s axes, no shift."
                % (scene_m, "Y-up" if _p(node, "yup", 1) else "Z-up"))
    return GlobalXform((0.0, 0.0, 0.0), unit_m, 1.0 / scene_m, bool(_p(node, "yup", 1)), "params",
                       UNITS.get(unit if unit != "source" else "mm")[0])


def output_units(node, gx):
    """-> (имя UnitSystem, метров в единице, множитель из единиц трансформа)."""
    from .rhino_read import UNIT_M
    from .rhino_write import UNITS
    unit = _p(node, "unit", "source")
    if unit == "source":
        name = gx.units if gx.units in UNIT_M else "Millimeters"
        um = UNIT_M.get(name, 1e-3)
    else:
        name, um = UNITS[unit]
    return name, um, gx.unit_m / um


# ---------------------------------------------------------------- подготовка геометрии

def _verb(name, parms):
    v = hou.sopNodeTypeCategory().nodeVerb(name)
    v.setParms(parms)
    return v


def prepare_geometry(src, node, warn, keep_blocks=False):
    """Копия входа: packed раскрыты (с атрибутами; при keep_blocks блоки остаются packed), многоугольники
    > 4 сторон разбиты, обрезанные NURBS и прочие примитивы — в полигоны."""
    geo = hou.Geometry()
    geo.merge(src)
    unpacked = False
    for _ in range(16):
        todo = [p for p in _packed_prims(geo) if not (keep_blocks and _is_block(geo, p))]
        if not todo:
            break
        _mark_packed(geo, todo)
        grp = geo.findPrimGroup("__h3dm_unpack") or geo.createPrimGroup("__h3dm_unpack")
        grp.clear()
        grp.add(todo)
        out = hou.Geometry()
        _verb("unpack", {"group": "__h3dm_unpack", "transfer_attributes": "__h3dm_inst __h3dm_chain",
                         "transfer_groups": "*", "limit_iterations": 1, "iterations": 1}).execute(out, [geo])
        geo = out
        g = geo.findPrimGroup("__h3dm_unpack")
        if g is not None:
            g.destroy()
        unpacked = True
    if unpacked:
        _finish_unpack(geo)
    _mark_free_points(geo)
    trimmed_mode = _p(node, "trimmed", "mesh")
    # обрезанные плоские грани с одной (внешней) петлёй -> точная обрезанная плоскость (Brep без Rhino)
    n_plane = _mark_trimmed_planes(geo)
    trim_grp = [g for g in (geo.findPrimGroup(n) for n in TRIM_GROUPS) if g is not None]
    if n_plane:
        tp = geo.findPrimGroup("__h3dm_tplane")
        for g in trim_grp:
            g.remove(tp.prims())
    n_trim = sum(len(g.prims()) for g in trim_grp)
    if n_trim:
        if trimmed_mode == "skip":
            for g in trim_grp:
                geo.deletePrims(g.prims())
            warn.append("%d trimmed NURBS faces skipped (Trimmed Surfaces = Skip)." % n_trim)
        else:
            lod = float(_p(node, "meshlod", 4.0))
            names = " ".join(g.name() for g in trim_grp)
            out = hou.Geometry()
            _verb("convert", {"group": names, "totype": 0, "lodu": lod, "lodv": lod, "lodtrim": lod}).execute(out, [geo])
            geo = out
            warn.append("%d trimmed NURBS faces written as meshes (exact Brep transfer comes in the next 0.4 step)."
                        % n_trim)
    approx = geo.findPrimGroup(UNTRIMMED_APPROX)
    if approx is not None and approx.prims():
        n = len(approx.prims())
        geo.deletePrims(approx.prims())
        warn.append("%d faces were imported without trim data (group %s, untrimmed approximation) and are NOT "
                    "exported: import the file after Prepare in Rhino." % (n, UNTRIMMED_APPROX))
    tc = geo.findPrimGroup(TRIM_CURVES)
    if tc is not None and tc.prims():
        geo.deletePrims(tc.prims())
    # прочие типы (сферы, трубки, Bezier, metaball, polysoup ...) -> полигоны
    keep = (hou.primType.Polygon, hou.primType.NURBSCurve, hou.primType.NURBSSurface)
    other = [p for p in geo.prims() if p.type() not in keep and not (keep_blocks and _is_block(geo, p))]
    if other:
        tmp = geo.createPrimGroup("__h3dm_other")
        tmp.add(other)
        out = hou.Geometry()
        _verb("convert", {"group": "__h3dm_other", "totype": 0, "lodu": 1.0, "lodv": 1.0}).execute(out, [geo])
        geo = out
        g = geo.findPrimGroup("__h3dm_other")
        if g is not None:
            g.destroy()
    # многоугольники > 4 сторон -> треугольники/четырёхугольники (Rhino Mesh: 3–4 вершины)
    big = [p for p in geo.prims() if p.type() == hou.primType.Polygon and p.isClosed() and p.numVertices() > 4]
    if big:
        tmp = geo.createPrimGroup("__h3dm_ngons")
        tmp.add(big)
        out = hou.Geometry()
        _verb("divide", {"group": "__h3dm_ngons", "convex": 1, "usemaxsides": 1, "numsides": 4}).execute(out, [geo])
        geo = out
        g = geo.findPrimGroup("__h3dm_ngons")
        if g is not None:
            g.destroy()
    return geo


_PACKED = tuple(t for t in (getattr(hou.primType, n, None) for n in
                            ("PackedPrim", "PackedGeometry", "PackedFragment", "AlembicRef", "PackedDisk",
                             "PackedDiskSequence", "AgentShape")) if t is not None)


def _plane_frame(P):
    """Сетка 2x2 степени 1: (P00, P10, P01) при аффинной (плоской, параллелограммной) параметризации, иначе None."""
    P00, P10, P01, P11 = P[0, 0], P[0, 1], P[1, 0], P[1, 1]
    size = max(np.linalg.norm(P10 - P00), np.linalg.norm(P01 - P00), 1e-12)
    if np.linalg.norm(P11 - P10 - P01 + P00) > 1e-6 * size:
        return None
    return P00, P10, P01


def _mark_trimmed_planes(geo):
    """Группа __h3dm_tplane: обрезанные грани (rhino_trimmed_exact) с одной петлёй на аффинной плоской
    поверхности (степень 1, 2x2, без весов). rhino3dm строит их точно (Brep.CreateTrimmedPlane);
    грани с отверстиями так не строятся (в rhino3dm нет многопетлевой обрезки)."""
    import json
    tg = geo.findPrimGroup(TRIM_GROUPS[0])
    if tg is None or geo.findPrimAttrib("rhino_trim_loops") is None:
        return 0
    has_pw = geo.findPointAttrib("Pw") is not None
    sel = []
    for prim in tg.prims():
        if prim.type() != hou.primType.NURBSSurface:
            continue
        if (int(prim.intrinsicValue("uorder")), int(prim.intrinsicValue("vorder")),
                int(prim.intrinsicValue("nu")), int(prim.intrinsicValue("nv"))) != (2, 2, 2, 2):
            continue
        try:
            loops = json.loads(prim.attribValue("rhino_trim_loops") or "[]")
        except Exception:
            continue
        if len(loops) != 1:
            continue
        pts = [[prim.vertex(u, v).point() for u in range(2)] for v in range(2)]
        if has_pw and any(abs(p.attribValue("Pw") - 1.0) > 1e-9 for row in pts for p in row):
            continue
        P = np.array([[tuple(p.position()) for p in row] for row in pts], dtype=np.float64)
        if _plane_frame(P) is None:
            continue
        sel.append(prim)
    if sel:
        g = geo.findPrimGroup("__h3dm_tplane") or geo.createPrimGroup("__h3dm_tplane")
        g.add(sel)
    return len(sel)


def _mark_free_points(geo):
    """Точки без примитивов во входе (облака, точки, метки) помечаются ДО преобразований: Convert, удаление
    служебных примитивов и т.п. оставляют лишние точки, которые не должны стать объектами Rhino."""
    used = np.zeros(geo.intrinsicValue("pointcount"), dtype=bool)
    for prim in geo.iterPrims():
        for v in prim.vertices():
            used[v.point().number()] = True
    if used.all():
        return
    a = geo.addAttrib(hou.attribType.Point, "__h3dm_free", 0)
    geo.setPointIntAttribValuesFromString("__h3dm_free", (~used).astype(np.int32).tobytes())


def _mark_packed(geo, prims=None):
    """Перед раскрытием: на packed-примитивах — вставка верхнего уровня и цепочка вложенных вставок.
    Атрибуты самих частей (имя, слой, материал, User Text) остаются их собственными."""
    for nm in ("__h3dm_inst", "__h3dm_chain"):
        if geo.findPrimAttrib(nm) is None:
            geo.addAttrib(hou.attribType.Prim, nm, "")
    has_id = geo.findPrimAttrib("rhino_id") is not None
    for p in (prims if prims is not None else _packed_prims(geo)):
        rid = p.attribValue("rhino_id") if has_id else ""
        inst = p.attribValue("__h3dm_inst")
        if inst:
            p.setAttribValue("__h3dm_chain", p.attribValue("__h3dm_chain") + rid + "/")
        else:
            p.setAttribValue("__h3dm_inst", rid or ("packed%d" % p.number()))
            p.setAttribValue("__h3dm_chain", "")


def _finish_unpack(geo):
    """Части раскрытых вставок -> rhino_instance_id / rhino_part_path (как у Blocks = Expand импорта).
    Packed per Object (содержимое с тем же rhino_id) — не блок: остаётся обычным объектом."""
    n = geo.intrinsicValue("primitivecount")
    inst = list(geo.primStringAttribValues("__h3dm_inst"))
    chain = list(geo.primStringAttribValues("__h3dm_chain"))
    rid = list(geo.primStringAttribValues("rhino_id")) if geo.findPrimAttrib("rhino_id") else [""] * n
    old_i = list(geo.primStringAttribValues("rhino_instance_id")) if geo.findPrimAttrib("rhino_instance_id") else [""] * n
    old_p = list(geo.primStringAttribValues("rhino_part_path")) if geo.findPrimAttrib("rhino_part_path") else [""] * n
    out_i, out_p = [], []
    for k in range(n):
        if inst[k] and not (rid[k] == inst[k] and not chain[k]):
            out_i.append(inst[k])
            out_p.append(chain[k] + (rid[k] or "p%d" % k))
        else:
            out_i.append(old_i[k])
            out_p.append(old_p[k])
    for nm, vals in (("rhino_instance_id", out_i), ("rhino_part_path", out_p)):
        if geo.findPrimAttrib(nm) is None:
            geo.addAttrib(hou.attribType.Prim, nm, "")
        geo.setPrimStringAttribValues(nm, vals)
    for nm in ("__h3dm_inst", "__h3dm_chain"):
        a = geo.findPrimAttrib(nm)
        if a is not None:
            a.destroy()


def _is_block(geo, prim):
    """Packed-примитив пишется блоком, если у него есть своя геометрия и это не «Pack per Object» импорта
    (у тех rhino_type — тип самого объекта Rhino)."""
    if prim.type() not in _PACKED or not hasattr(prim, "getEmbeddedGeometry"):
        return False
    try:
        if prim.getEmbeddedGeometry() is None:
            return False
    except Exception:
        return False
    rt = prim.attribValue("rhino_type") if geo.findPrimAttrib("rhino_type") is not None else ""
    return rt in ("", "InstanceReference")


def _packed_prims(geo):
    out = []
    for t in _PACKED:
        try:
            out.extend(geo.primsOfType(t))
        except Exception:
            pass
    return out


def _has_packed(geo):
    return bool(_packed_prims(geo))


# ---------------------------------------------------------------- атрибуты

def _str_attr(geo, name, n):
    return list(geo.primStringAttribValues(name)) if geo.findPrimAttrib(name) else [""] * n


def _name_maps(geo):
    if geo.findGlobalAttrib("h3dm_export_names") is not None:
        d = _plain(geo.dictAttribValue("h3dm_export_names") or {})
    else:
        d = {}
    return {k: dict(d.get(k) or {}) for k in ("layers", "names", "groups", "keys")}, d.get("layersep", "::")


def _plain(v):
    """Значения dict-атрибутов Houdini (hou.Vector*, кортежи) -> обычные типы Python."""
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "__len__") and hasattr(v, "__getitem__") and not isinstance(v, str):
        try:
            return [float(v[i]) for i in range(len(v))]
        except Exception:
            return v
    return v


def _detail_list(geo, name):
    a = geo.findGlobalAttrib(name)
    if a is None:
        return []
    try:
        return [_plain(x) for x in geo.dictListAttribValue(name)]
    except Exception:
        return []


def _fmt_value(v):
    if isinstance(v, float):
        return "%.7g" % v
    if isinstance(v, (tuple, list)):
        return " ".join(_fmt_value(x) for x in v)
    return str(v)


class Plan(object):
    def __init__(self):
        self.objects = []        # {'kind', 'geom': {...}, 'attrs': {...}}
        self.warnings = []
        self.layers = set()
        self.materials = set()
        self.groups = set()
        self.units = "Millimeters"
        self.abs_tol = 0.001
        self.layer_props = {}
        self.layer_order = []    # слои импорта в исходном порядке (пустые слои тоже сохраняются)
        self.mat_props = {}
        self.doc_text = {}
        self.source_files = set()
        self.definitions = {}    # geometryid -> {'name', 'objects'}
        self.def_order = []      # вложенные определения раньше внешних


def collect(node):
    """Вход 1 -> Plan (без записи)."""
    if not node.inputs() or node.input(0) is None:
        raise ExportError("Nothing connected to input 1.")
    src = node.input(0).geometry()
    plan = Plan()
    warn = plan.warnings
    gx = resolve_xform(node, src, warn)
    unit_name, unit_m, factor = output_units(node, gx)
    plan.units = unit_name

    # данные документа импорта
    if src.findGlobalAttrib("rhino_doc") is not None:
        doc = _plain(src.dictAttribValue("rhino_doc") or {})
        tol = float(doc.get("abs_tolerance") or 0.001)
        plan.abs_tol = tol * float(doc.get("unit_m") or unit_m) / unit_m
    mats = _detail_list(src, "rhino_materials")
    for m in mats:
        if m.get("name"):
            plan.mat_props[m["name"]] = m
    for l in _detail_list(src, "rhino_layers"):
        if l.get("full_path"):
            mi = l.get("material_index", -1)
            mi = int(mi) if mi is not None else -1
            plan.layer_order.append(l["full_path"])
            plan.layer_props[l["full_path"]] = {"color": l.get("color"), "visible": l.get("visible", True),
                                                "locked": l.get("locked", False), "user_text": l.get("user_text") or {},
                                                "material": mats[mi].get("name", "") if 0 <= mi < len(mats) else ""}
    if src.findGlobalAttrib("rhino_doc_text") is not None and _p(node, "doctext", 1):
        plan.doc_text = {k: str(v) for k, v in (src.dictAttribValue("rhino_doc_text") or {}).items()}
    if src.findGlobalAttrib("rhino_file") is not None:
        f = src.attribValue("rhino_file")
        if f:
            plan.source_files.add(os.path.abspath(f))
    if src.findGlobalAttrib("h3dm_prepare") is not None:
        st = _plain(src.dictAttribValue("h3dm_prepare") or {})
        sp = (st.get("source") or {}).get("path")
        if sp:
            plan.source_files.add(os.path.abspath(sp))

    maps, imp_sep = _name_maps(src)
    restore = bool(_p(node, "restorenames", 1))
    sep = _p(node, "layersep", "::") or "::"
    default_layer = _p(node, "defaultlayer", "Houdini") or "Houdini"
    keep_blocks = _p(node, "packed", "blocks") == "blocks"
    used_ids = set()
    C, s_ = gx.C, gx.s

    def to_world(P):
        """Позиции Houdini (N,3) -> координаты файла (double): один обратный трансформ + единицы."""
        return gx.to_rhino(np.asarray(P, dtype=np.float64)) * factor

    def to_local(P):
        """Внутри определения блока: без origin (локальная система блока), оси/масштаб/единицы."""
        return np.einsum("ji,nj->ni", C, np.asarray(P, dtype=np.float64).reshape(-1, 3)) / s_ * factor

    def instance_xform(prim, top):
        """4x4 Rhino вставки: R = C^T A C, t = origin + C^T b / s (на верхнем уровне), всё в единицах файла."""
        M = np.array(prim.fullTransform().asTupleOfTuples(), dtype=np.float64)
        A, b = M[:3, :3].T, M[3, :3]
        X = np.eye(4)
        X[:3, :3] = C.T @ A @ C
        t = C.T @ b / s_
        X[:3, 3] = ((t + gx.origin) if top else t) * factor
        # матрица импорта в double: Houdini хранит packed-трансформ во float32; если вставку не трогали
        # (совпадает в пределах float32), пишем точную
        try:
            txt = prim.attribValue("rhino_xform") if prim.geometry().findPrimAttrib("rhino_xform") else ""
        except Exception:
            txt = ""
        if txt:
            Xs = np.array([float(v) for v in txt.split()], dtype=np.float64).reshape(4, 4)
            Xs[:3, 3] *= factor
            # допуск float32: относительно сдвинутого (локального) переноса, не абсолютных координат
            tol_t = 1e-6 * (float(np.abs(t).max()) + 1.0) * factor
            if np.abs(Xs[:3, :3] - X[:3, :3]).max() < 1e-5 and np.abs(Xs[:3, 3] - X[:3, 3]).max() < tol_t:
                return Xs
        return X

    def definition(prim, depth):
        """Определение блока по geometryid packed-примитива (одно на общую геометрию; вложенные — раньше)."""
        gid = prim.intrinsicValue("geometryid")
        if gid in plan.definitions:
            return gid
        inner = prim.getEmbeddedGeometry()
        objs = []
        plan.definitions[gid] = None          # защита от зацикливания
        if inner is not None and depth < 16:
            gather(inner, to_local, objs, depth + 1)
        bname = ""
        if inner is not None and inner.findPrimAttrib("block") is not None:
            bname = next((x for x in inner.primStringAttribValues("block") if x), "")
        bname = bname or "Block_%d" % gid
        used = {d["name"] for d in plan.definitions.values() if d}
        base, k = bname, 2
        while bname in used:
            bname = "%s_%d" % (base, k)
            k += 1
        plan.definitions[gid] = {"name": bname, "objects": objs}
        plan.def_order.append(gid)
        return gid

    def gather(geo_in, to_file, objects, depth):
        top = depth == 0
        geo = prepare_geometry(geo_in, node, warn, keep_blocks)
        prims = geo.prims()
        n = len(prims)
        layer_v = _str_attr(geo, _p(node, "layerattrib", "layer") or "layer", n)
        name_v = _str_attr(geo, _p(node, "nameattrib", "name") or "name", n)
        mat_attr = _p(node, "matattrib", "material") or "material"
        mat_v = _str_attr(geo, mat_attr, n)
        if not any(mat_v) and geo.findPrimAttrib("shop_materialpath") is not None:
            mat_v = [os.path.basename(x) for x in geo.primStringAttribValues("shop_materialpath")]
        rid_v = _str_attr(geo, "rhino_id", n)
        inst_v = _str_attr(geo, "rhino_instance_id", n)
        part_v = _str_attr(geo, "rhino_part_path", n)
        cd = np.ones((n, 3))
        if geo.findPrimAttrib("Cd") is not None:
            cd = np.array(geo.primFloatAttribValues("Cd"), dtype=np.float64).reshape(n, 3)
        alpha = np.ones(n)
        if geo.findPrimAttrib("Alpha") is not None:
            alpha = np.array(geo.primFloatAttribValues("Alpha"), dtype=np.float64)
        utd = _p(node, "utdict", "user_text") or "user_text"
        ut_dict_attr = geo.findPrimAttrib(utd)
        # плоские атрибуты User Text: импортированные (карта ключей) + маски пользователя
        ut_globs = _p(node, "utattribs", "")
        flat = []
        for a in geo.primAttribs():
            nm = a.name()
            if nm in SERVICE_ATTRIBS or nm.startswith(SERVICE_PREFIXES) or SERVICE_RE.match(nm) or nm == utd:
                continue
            if nm in maps["keys"] or (ut_globs and _globs_match(nm, ut_globs)):
                flat.append(a)
        # группы
        grp_glob = _p(node, "groups", "* ^rhino_* ^h3dm_*")
        groups = [g for g in geo.primGroups() if not g.name().startswith(SERVICE_GROUP_PREFIXES + ("__",))
                  and _globs_match(g.name(), grp_glob)]
        prim_groups = [[] for _ in range(n)]
        for g in groups:
            orig = maps["groups"].get(g.name(), g.name()) if restore else g.name()
            for p in g.prims():
                prim_groups[p.number()].append(orig)

        def layer_path(i):
            L = layer_v[i] or default_layer
            if restore and L in maps["layers"]:
                return maps["layers"][L]
            return "::".join(s for s in L.split(sep if sep in L else imp_sep) if s) or default_layer

        def obj_name(i):
            nm = name_v[i]
            return maps["names"].get(nm, nm) if restore else nm

        def mat_name(i):
            m = mat_v[i]
            return maps["names"].get(m, m) if (restore and m) else m

        def user_text(i, prim):
            d = {}
            if ut_dict_attr is not None:
                try:
                    d.update({str(k): _fmt_value(v) for k, v in (prim.attribValue(utd) or {}).items()})
                except Exception:
                    pass
            for a in flat:                         # плоские атрибуты — поверх словаря (их правят чаще)
                v = prim.attribValue(a.name())
                key = maps["keys"].get(a.name(), a.name()) if restore else a.name()
                if key not in d and (v in ("", None) or (ut_dict_attr is not None and v == a.defaultValue())):
                    continue                       # у объекта такого ключа не было (атрибут со значением по умолчанию)
                d[key] = _fmt_value(v)
            return d

        # разбиение на объекты
        split = _p(node, "splitby", "auto")
        split_attr = _p(node, "splitattrib", "rhino_id") or "rhino_id"
        piece = None
        if split == "connectivity" or (split == "auto" and not all(rid_v)):
            tmp = hou.Geometry()
            _verb("connectivity", {"connecttype": 1, "attribname": "__h3dm_piece"}).execute(tmp, [geo])
            piece = list(tmp.primIntAttribValues("__h3dm_piece")) if tmp.findPrimAttrib("__h3dm_piece") else None
        split_vals = _str_attr(geo, split_attr, n) if split == "attrib" else None

        def key_of(i, prim):
            if split == "prim" or prim.type() != hou.primType.Polygon or not prim.isClosed():
                return ("prim", i)                 # кривые, поверхности: объект Rhino на примитив
            if split == "attrib":
                return ("a", split_vals[i] or ("piece", piece[i] if piece else i))
            if split == "connectivity":
                return ("c", piece[i] if piece else i)
            # auto: объект Rhino (вставка + часть блока), иначе связная часть с тем же слоем/именем
            if rid_v[i]:
                return ("r", inst_v[i] or rid_v[i], part_v[i])
            return ("c", piece[i] if piece else i, layer_v[i], name_v[i])

        P = np.array(geo.pointFloatAttribValues("P"), dtype=np.float64).reshape(-1, 3)
        has_ptcd = geo.findPointAttrib("Cd") is not None
        ptcd = np.array(geo.pointFloatAttribValues("Cd"), dtype=np.float64).reshape(-1, 3) if has_ptcd else None
        has_pw = geo.findPointAttrib("Pw") is not None
        pw = np.array(geo.pointFloatAttribValues("Pw"), dtype=np.float64) if has_pw else None

        meshes = {}                                 # ключ -> {'first': i, 'faces': [[pt...]]}
        order_keys = []

        def attrs_of(i, prim, oid=None):
            L = layer_path(i)
            plan.layers.add(L)
            m = mat_name(i)
            if m:
                plan.materials.add(m)
            for g in prim_groups[i]:
                plan.groups.add(g)
            a = {"layer": L, "name": obj_name(i), "color": tuple(cd[i]) + (float(alpha[i]),) if _p(node, "color", 1) else None,
                 "material": m, "groups": prim_groups[i], "user_text": user_text(i, prim)}
            # id объекта Rhino: сохраняем, если он ещё не занят (одна вставка = один объект)
            cand = oid if oid is not None else (rid_v[i] if not inst_v[i] else "")
            if cand and cand not in used_ids:
                a["id"] = cand
                used_ids.add(cand)
            return a

        POLY, NCURVE, NSURF = hou.primType.Polygon, hou.primType.NURBSCurve, hou.primType.NURBSSurface
        tpg = geo.findPrimGroup("__h3dm_tplane")
        tplane = {p.number() for p in tpg.prims()} if tpg is not None else set()
        for i, prim in enumerate(prims):
            t = prim.type()
            if t == POLY:
                pts = [v.point().number() for v in prim.vertices()]
                if prim.isClosed():
                    if len(pts) < 3:
                        continue
                    k = key_of(i, prim)
                    if k not in meshes:
                        meshes[k] = {"first": i, "faces": []}
                        order_keys.append(("mesh", k))
                    meshes[k]["faces"].append(pts)
                else:
                    if len(pts) < 2:
                        continue
                    order_keys.append(("obj", {"kind": "polyline", "geom": {"pts": to_file(P[pts]), "closed": False},
                                               "attrs": attrs_of(i, prim)}))
            elif keep_blocks and _is_block(geo, prim):
                gid = definition(prim, depth)
                objects.append({"kind": "instance", "def": gid, "xform": instance_xform(prim, top),
                                "attrs": attrs_of(i, prim, oid=rid_v[i] or None)})
            elif t == NCURVE:
                pts = [v.point().number() for v in prim.vertices()]
                closed = bool(prim.intrinsicValue("closed"))
                order_keys.append(("obj", {"kind": "curve", "geom": {
                    "cv": to_file(P[pts]), "w": pw[pts] if has_pw else np.ones(len(pts)),
                    "order": int(prim.intrinsicValue("order")), "knots": list(prim.intrinsicValue("knots")),
                    "closed": closed}, "attrs": attrs_of(i, prim)}))
            elif t == NSURF and i in tplane:
                objects.append({"kind": "trimmed_plane", "geom": _trimmed_plane(prim, P, to_file),
                                "attrs": attrs_of(i, prim)})
            elif t == NSURF:
                nu, nv = int(prim.intrinsicValue("nu")), int(prim.intrinsicValue("nv"))
                idx = np.array([[prim.vertex(u, v).point().number() for u in range(nu)] for v in range(nv)])
                cv = to_file(P[idx.reshape(-1)]).reshape(nv, nu, 3)
                w = pw[idx] if has_pw else np.ones((nv, nu))
                # Houdini: нормаль противоположна Rhino (u x v) — разворачиваем U обратно (см. импорт)
                ku = list(prim.intrinsicValue("uknots"))
                a0, b0 = ku[0], ku[-1]
                order_keys.append(("obj", {"kind": "surface", "geom": {
                    "cv": cv[:, ::-1], "w": w[:, ::-1], "order_u": int(prim.intrinsicValue("uorder")),
                    "order_v": int(prim.intrinsicValue("vorder")), "knots_u": [a0 + b0 - x for x in reversed(ku)],
                    "knots_v": list(prim.intrinsicValue("vknots")),
                    "wrap_u": bool(prim.intrinsicValue("uwrap")), "wrap_v": bool(prim.intrinsicValue("vwrap"))},
                    "attrs": attrs_of(i, prim)}))

        for kind, item in order_keys:
            if kind == "obj":
                objects.append(item)
                continue
            mk = meshes[item]
            first = mk["first"]
            pts_all = sorted({p for fc in mk["faces"] for p in fc})
            local = {p: j for j, p in enumerate(pts_all)}
            faces = [tuple(local[p] for p in reversed(fc)) for fc in mk["faces"]]   # Houdini по часовой -> Rhino
            colors = None
            if has_ptcd:
                c = ptcd[pts_all]
                if len(c) and float(np.ptp(c, axis=0).max()) > 1e-6:
                    colors = c
            objects.append({"kind": "mesh", "geom": {"V": to_file(P[pts_all]), "faces": faces, "colors": colors},
                                 "attrs": attrs_of(first, prims[first])})

        # точки без примитивов: текстовые метки и точки
        free = []
        if geo.findPointAttrib("__h3dm_free") is not None and (
                (geo.findPointAttrib("text") is not None and _p(node, "textdots", 1)) or _p(node, "points", 0)):
            flags = geo.pointIntAttribValues("__h3dm_free")
            free = [pt for pt, fl in zip(geo.points(), flags) if fl]
        if free:
            has_text = geo.findPointAttrib("text") is not None
            dots, others = [], []
            for pt in free:
                txt = pt.attribValue("text") if has_text else ""
                (dots if (txt and _p(node, "textdots", 1)) else others).append(pt)
            pt_attr = lambda name, pt, d="": pt.attribValue(name) if geo.findPointAttrib(name) else d  # noqa: E731
            pflat = [a.name() for a in geo.pointAttribs()
                     if not (a.name() in SERVICE_ATTRIBS or a.name().startswith(SERVICE_PREFIXES) or SERVICE_RE.match(a.name())
                             or a.name() == utd) and (a.name() in maps["keys"] or (ut_globs and _globs_match(a.name(), ut_globs)))]

            def pattrs(pt):
                at = point_attrs(geo, pt, maps, restore, sep, imp_sep, default_layer, pflat, utd)
                if not _p(node, "color", 1):
                    at["color"] = None
                plan.layers.add(at["layer"])
                if at["material"]:
                    plan.materials.add(at["material"])
                return at
            for pt in dots:
                objects.append({"kind": "textdot", "geom": {"text": pt.attribValue("text"),
                                                                 "pt": to_file([pt.position()])[0]}, "attrs": pattrs(pt)})
            if others and _p(node, "points", 0):
                byobj = {}
                for pt in others:
                    byobj.setdefault(pt_attr("rhino_id", pt) or ("pt", pt.number()), []).append(pt)
                for k, pts in byobj.items():
                    Pp = to_file([p.position() for p in pts])
                    attrs = pattrs(pts[0])
                    rid = pt_attr("rhino_id", pts[0])
                    if rid and rid not in used_ids:
                        attrs["id"] = rid
                        used_ids.add(rid)
                    if len(pts) == 1:
                        objects.append({"kind": "point", "geom": {"pt": Pp[0]}, "attrs": attrs})
                    else:
                        cols = np.array([p.attribValue("Cd") for p in pts]) if has_ptcd else None
                        if cols is not None and float(np.ptp(cols, axis=0).max()) < 1e-6:
                            cols = None
                        objects.append({"kind": "pointcloud", "geom": {"pts": Pp, "colors": cols}, "attrs": attrs})
    gather(src, to_world, plan.objects, 0)
    plan.gx = gx
    plan.factor = factor
    return plan


def _trimmed_plane(prim, P, to_file):
    """Плоская грань 2x2 + внешняя петля обрезки (UV Houdini) -> плоскость и 3D-кривые петли (точно, с весами):
    параметризация аффинная, поэтому образы управляющих точек с теми же весами и узлами — та же кривая."""
    import json
    idx = np.array([[prim.vertex(u, v).point().number() for u in range(2)] for v in range(2)])
    cv = to_file(P[idx.reshape(-1)]).reshape(2, 2, 3)[:, ::-1]           # разворот U, как у поверхностей
    ku_h = list(prim.intrinsicValue("uknots"))
    kv = list(prim.intrinsicValue("vknots"))
    ku = [ku_h[0] + ku_h[-1] - x for x in reversed(ku_h)]
    u0, u1, v0, v1 = ku[1], ku[2], kv[1], kv[2]
    P00, P10, P01 = cv[0, 0], cv[0, 1], cv[1, 0]
    loops = json.loads(prim.attribValue("rhino_trim_loops"))
    curves = []
    for c in loops[0]["c"]:
        uvw = np.array(c["p"], dtype=np.float64)
        ue = ku_h[0] + ku_h[-1] - uvw[:, 0]
        X = (P00[None, :] + ((ue - u0) / (u1 - u0))[:, None] * (P10 - P00)[None, :]
             + ((uvw[:, 1] - v0) / (v1 - v0))[:, None] * (P01 - P00)[None, :])
        curves.append({"cv": X, "w": uvw[:, 2], "order": int(c["o"]), "knots": c["k"]})
    return {"plane": (P00, P10 - P00, P01 - P00), "outer": curves}


def point_attrs(geo, pt, maps, restore, sep, imp_sep, default_layer, flat_names, utd):
    """Атрибуты объекта Rhino с точки (облака, точки, текстовые метки)."""
    def get(name, d=""):
        return pt.attribValue(name) if geo.findPointAttrib(name) else d
    L = get("layer") or default_layer
    L = maps["layers"].get(L, L) if restore else L
    L = "::".join(s for s in L.split(sep if sep in L else imp_sep) if s) or default_layer
    nm = get("name")
    nm = maps["names"].get(nm, nm) if restore else nm
    m = get("material")
    m = maps["names"].get(m, m) if (restore and m) else m
    ut = {}
    if geo.findPointAttrib(utd) is not None:
        ut.update({str(k): _fmt_value(v) for k, v in (pt.attribValue(utd) or {}).items()})
    for a in flat_names:
        if geo.findPointAttrib(a) is None:
            continue
        v = pt.attribValue(a)
        key = maps["keys"].get(a, a) if restore else a
        if key not in ut and (v in ("", None) or (geo.findPointAttrib(utd) is not None
                                                 and v == geo.findPointAttrib(a).defaultValue())):
            continue
        ut[key] = _fmt_value(v)
    col = None
    if geo.findPointAttrib("Cd") is not None:
        col = tuple(pt.attribValue("Cd")) + ((float(pt.attribValue("Alpha")),) if geo.findPointAttrib("Alpha") else (1.0,))
    return {"layer": L, "name": nm, "material": m, "user_text": ut, "color": col, "groups": []}


def obj_name_pt(pt, pt_attr, maps, restore):
    nm = pt_attr("name", pt) or ""
    return maps["names"].get(nm, nm) if restore else nm


# ---------------------------------------------------------------- запись

def target_path(node, plan):
    path = hou.text.expandString(node.parm("file").evalAsString())
    if not path:
        raise ExportError("Set Output 3dm first.")
    if not path.lower().endswith(".3dm"):
        path += ".3dm"
    path = os.path.abspath(path)
    if path in plan.source_files and not _p(node, "allowsource", 0):
        raise ExportError("Output 3dm is the file the geometry was imported from (or its prepared copy):\n%s\n\n"
                          "Choose another file, or turn on Allow Overwriting the Source File." % path)
    if os.path.exists(path) and not _p(node, "overwrite", 0):
        from .rhino_write import next_version
        path = next_version(path)
    return path


def write_plan(plan, path, node):
    from .rhino_write import Writer
    w = Writer(plan.units, plan.abs_tol, 1.0, plan.layer_props, plan.mat_props)
    if plan.doc_text:
        w.doc_strings(plan.doc_text)
    layer_color = bool(_p(node, "layercolor", 0))
    if _p(node, "alllayers", 1):
        for L in plan.layer_order:             # таблица слоёв импорта целиком, в исходном порядке
            w.layer(L)
    rules = _material_rules(node)

    def write_object(o):
        a = o["attrs"]
        if layer_color and a.get("color") is not None and a["layer"] not in w.layer_props:
            w.layer_props[a["layer"]] = {"color": a["color"]}
        mcol = mtr = None
        mname = a.get("material") or ""
        for pat, name, col, tr in rules:
            if mname and fnmatch.fnmatchcase(mname, pat):
                mname, mcol, mtr = (name or mname), col, tr
                break
        at = w.attributes(a["layer"], a.get("name", ""), a.get("color"), mname, a.get("groups", ()),
                          a.get("user_text"), a.get("id"), mcol, mtr)
        g = o.get("geom") or {}
        k = o["kind"]
        try:
            if k == "mesh":
                w.add_mesh(g["V"], g["faces"], at, g.get("colors"))
            elif k == "polyline":
                w.add_polyline(g["pts"], g.get("closed", False), at)
            elif k == "curve":
                w.add_nurbs_curve(g["cv"], g["w"], g["order"], g["knots"], at, g.get("closed", False))
            elif k == "surface":
                w.add_surface(g["cv"], g["w"], g["order_u"], g["order_v"], g["knots_u"], g["knots_v"], at,
                              g.get("wrap_u", False), g.get("wrap_v", False))
            elif k == "trimmed_plane":
                w.add_trimmed_plane(g["plane"], g["outer"], at)
            elif k == "textdot":
                w.add_textdot(g["text"], g["pt"], at)
            elif k == "point":
                w.add_point(g["pt"], at)
            elif k == "pointcloud":
                w.add_point_cloud(g["pts"], at, g.get("colors"))
            elif k == "instance":
                w.add_instance(o["def"], o["xform"], at)
        except Exception as ex:
            w.warnings.append("%s '%s' skipped: %s" % (k, a.get("name", ""), ex))

    # определения блоков (вложенные раньше внешних), затем объекты модели
    for gid in plan.def_order:
        d = plan.definitions.get(gid)
        if not d:
            continue
        w.begin_definition()
        for o in d["objects"]:
            write_object(o)
        w.end_definition(gid, d["name"])
    for o in plan.objects:
        write_object(o)
    w.write(path, int(_p(node, "version", "8")))
    return w


def _material_rules(node):
    out = []
    mp = node.parm("matrules")
    n = mp.eval() if mp is not None else 0
    for i in range(1, n + 1):
        out.append((node.parm("mat_pattern%d" % i).eval() or "*", node.parm("mat_name%d" % i).eval(),
                    tuple(node.parmTuple("mat_color%d" % i).eval()), node.parm("mat_transp%d" % i).eval()))
    return out


def report_text(plan, path=None, writer=None, back=None):
    kinds = {}
    for o in plan.objects:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    gx = plan.gx
    lines = []
    if path:
        lines.append("Written: %s" % path)
    lines.append("Objects: %d  (%s)" % (len(plan.objects), ", ".join("%s %d" % kv for kv in sorted(kinds.items()))))
    lines.append("Layers: %d   Materials: %d   Groups: %d   Block definitions: %d"
                 % (len(plan.layers), len(plan.materials), len(plan.groups), len([d for d in plan.definitions.values() if d])))
    lines.append("Units: %s   Transform: %s, origin %s, scale %g, %s"
                 % (plan.units, gx.source, " ".join("%.3f" % x for x in gx.origin), gx.s,
                    "Y-up -> Z-up" if gx.yup else "Z-up"))
    if back:
        lines.append("Read back: %d objects (%s), %d layers, %d groups, %d materials, %s"
                     % (back["objects"], ", ".join("%s %d" % kv for kv in sorted(back["kinds"].items())),
                        back["layers"], back["groups"], back["materials"], back["units"]))
    warns = list(plan.warnings) + (list(writer.warnings) if writer else [])
    if writer is not None and writer.counts.get("degenerate_faces"):
        warns.append("%d degenerate mesh faces (zero area) were removed." % writer.counts["degenerate_faces"])
    if warns:
        lines.append("")
        lines.append("Warnings:")
        lines += ["  " + w for w in warns]
    return "\n".join(lines)


def _set_report(node, text):
    p = node.parm("report")
    if p is not None:
        p.set(text)


def run(node, write=True):
    """Экспорт (write=True) или проверка. -> (текст отчёта, путь или None)."""
    plan = collect(node)
    if not write:
        return report_text(plan), None
    path = target_path(node, plan)
    w = write_plan(plan, path, node)
    back = None
    if _p(node, "verify", 1):
        from .rhino_write import summary
        back = summary(path)
        expected = len(plan.objects) + sum(len(d["objects"]) for d in plan.definitions.values() if d) \
            - sum(1 for x in w.warnings if "skipped" in x)
        if back["objects"] != expected:
            w.warnings.append("read back: %d objects, expected %d" % (back["objects"], expected))
    return report_text(plan, path, w, back), path


def export_node(kwargs):
    node = kwargs["node"]
    try:
        text, path = run(node, write=True)
    except ExportError as ex:
        _set_report(node, "ERROR: %s" % ex)
        _message(str(ex), hou.severityType.Error)
        return None
    except Exception as ex:
        import traceback
        _set_report(node, "ERROR: %s\n\n%s" % (ex, traceback.format_exc()))
        _message("Export failed: %s" % ex, hou.severityType.Error)
        return None
    _set_report(node, text)
    if hou.isUIAvailable():
        hou.ui.setStatusMessage("H3DM: exported %s" % path)
        if "Warnings:" in text:
            _message(text, hou.severityType.Warning)
    return path


def check_node(kwargs):
    node = kwargs["node"]
    try:
        text, _ = run(node, write=False)
    except Exception as ex:
        text = "ERROR: %s" % ex
    _set_report(node, text)
    _message(text, hou.severityType.Message)
    return text


def _message(text, severity):
    if hou.isUIAvailable():
        hou.ui.displayMessage(text.split("\n\n")[0] if len(text) > 1500 else text, severity=severity,
                              title="H3DM 3dm Export", details=text if len(text) > 1500 else None)
    else:
        print("H3DM export: " + text)


def reveal_file(kwargs):
    """Показать файл экспорта в Finder/Explorer."""
    node = kwargs["node"]
    path = hou.text.expandString(node.parm("file").evalAsString())
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        _message("Folder does not exist yet:\n%s" % folder, hou.severityType.Message)
        return
    import subprocess
    import sys
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if os.path.exists(path) else ["open", folder])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)] if os.path.exists(path) else ["explorer", folder])
    else:
        subprocess.Popen(["xdg-open", folder])

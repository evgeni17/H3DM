# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой импорта: .3dm -> геометрия Houdini.

Вызывается из Python SOP внутри HDA h3dm::3dm_import:
    import h3dm.sop_import as m; m.cook(hou.pwd(), output=0)   # геометрия
    import h3dm.sop_import as m; m.cook(hou.pwd(), output=1)   # Info: тексты, точки, свет...
Параметры читаются с HDA (родителя Python SOP) или с самого узла.

0.1.0: данные документа и таблицы в detail-атрибутах; геометрия — следующий этап.
"""
import os

import hou

from . import ensure_vendor_path

ensure_vendor_path()

# кэш открытых файлов: ключ (путь, mtime, размер) -> File3dm
_CACHE = {}
_CACHE_MAX = 2


def _owner(node):
    """Узел, на котором висят параметры (HDA или сам Python SOP)."""
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


def open_file(path):
    """File3dm из кэша или с диска."""
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
    if kwargs and kwargs.get("node") is not None:
        n = kwargs["node"]
        for child in ("GEO", "INFO"):
            c = n.node(child)
            if c is not None:
                c.cook(force=True)


def _detail_dict(geo, name, value):
    a = geo.findGlobalAttrib(name) or geo.addAttrib(hou.attribType.Global, name, {})
    geo.setGlobalAttribValue(a, value)


def _detail_dict_array(geo, name, values):
    a = geo.findGlobalAttrib(name) or geo.addArrayAttrib(hou.attribType.Global, name, hou.attribData.Dict)
    geo.setGlobalAttribValue(a, values)


def _detail_string(geo, name, value):
    a = geo.findGlobalAttrib(name) or geo.addAttrib(hou.attribType.Global, name, "")
    geo.setGlobalAttribValue(a, value)


def _detail_float(geo, name, value):
    a = geo.findGlobalAttrib(name) or geo.addAttrib(hou.attribType.Global, name, 0.0)
    geo.setGlobalAttribValue(a, value)


def write_document(geo, f, mapper=None):
    """Данные документа и таблицы -> detail-атрибуты."""
    from . import rhino_read
    d = rhino_read.doc_info(f)
    _detail_dict(geo, "rhino_doc", d)
    _detail_string(geo, "rhino_units", d["units"])
    _detail_float(geo, "rhino_unit_m", d["unit_m"])
    _detail_dict(geo, "rhino_doc_text", rhino_read.doc_strings(f))
    _detail_dict_array(geo, "rhino_layers", rhino_read.layers(f))
    _detail_dict_array(geo, "rhino_materials", rhino_read.materials(f))
    _detail_dict_array(geo, "rhino_groups", rhino_read.groups(f))
    _detail_dict_array(geo, "rhino_blocks", rhino_read.instance_definitions(f))
    if mapper is not None and mapper.map:
        _detail_dict(geo, "h3dm_name_map", dict(mapper.map))


def cook(node, output=0):
    geo = node.geometry()
    owner = _owner(node)
    path = hou.text.expandString(_ev(owner, "file", ""))
    if not path:
        return
    if not os.path.isfile(path):
        raise hou.NodeError("File not found: %s" % path)
    from . import has_rhino3dm
    if not has_rhino3dm():
        raise hou.NodeError("rhino3dm is not installed. Run H3DM > Install / Update rhino3dm.")
    f = open_file(path)
    if output == 0:
        write_document(geo, f)
        node.addWarning("H3DM 0.1.0: document data only, geometry import comes in the next version.")


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

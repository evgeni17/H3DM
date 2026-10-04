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

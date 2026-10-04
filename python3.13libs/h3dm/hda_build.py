# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сборка HDA плагина (h3dm::3dm_import, h3dm::3dm_export) в $H3DM/otls.

Запуск: меню H3DM > Rebuild HDAs, либо в Python Shell:
    import h3dm.hda_build as b; b.build_all()
HDA тонкие: вся логика в модуле h3dm, пересборка нужна только при изменении интерфейса.
"""
import os

import hou

from . import ROOT, __version__

OTLS = os.path.join(ROOT, "otls")

IMPORT_TYPE = "h3dm::3dm_import::1.0"
EXPORT_TYPE = "h3dm::3dm_export::1.0"

GEO_CODE = """# H3DM: чтение .3dm — геометрия (логика в модуле h3dm.sop_import)
import h3dm.sop_import as m
m.cook(hou.pwd(), output=0)
"""
INFO_CODE = """# H3DM: чтение .3dm — тексты, точки, размеры, свет (выход Info)
import h3dm.sop_import as m
m.cook(hou.pwd(), output=1)
"""
XFORM_CODE = """# H3DM: глобальный трансформ (выход Xform) — точка с d@h3dm_xform (double)
import h3dm.sop_import as m
m.cook(hou.pwd(), output=2)
"""

PY = hou.scriptLanguage.Python
HIDE = hou.parmCondType.HideWhen
DISABLE = hou.parmCondType.DisableWhen


def _menu(name, label, items, default=0, **kw):
    return hou.MenuParmTemplate(name, label, [i[0] for i in items], [i[1] for i in items], default_value=default, **kw)


def _toggle(name, label, default=True, **kw):
    return hou.ToggleParmTemplate(name, label, default_value=default, **kw)


def _folder(name, label, items):
    f = hou.FolderParmTemplate(name, label, folder_type=hou.folderType.Tabs)
    for t in items:
        f.addParmTemplate(t)
    return f


def _import_ptg():
    g = hou.ParmTemplateGroup()
    g.append(hou.StringParmTemplate("file", "3dm File", 1, string_type=hou.stringParmType.FileReference,
                                    file_type=hou.fileType.Any, tags={"filechooser_pattern": "*.3dm"}))
    g.append(hou.ButtonParmTemplate("reload", "Reload", script_callback="import h3dm.sop_import as m; m.clear_cache(kwargs)",
                                    script_callback_language=PY, join_with_next=True))
    g.append(hou.ButtonParmTemplate("info", "File Info", script_callback="import h3dm.sop_import as m; m.info_text(kwargs)",
                                    script_callback_language=PY))
    g.append(_menu("surfout", "Surface Output", [("nurbs", "NURBS Patches"), ("polys", "Polygons"), ("packed", "Packed per Object")],
                   help="How Breps, extrusions and surfaces are imported."))
    g.append(_toggle("trimnurbs", "Trimmed Faces as Untrimmed NURBS + Boundary Curves", False,
                     help="Off: trimmed faces are tessellated (exact shape). On: the full untrimmed surface is kept and "
                          "the face boundary is added as curves (group rhino_trim_curves).",
                     conditionals={HIDE: "{ surfout != nurbs }"}))

    geo = [
        _toggle("rendermesh", "Use Rhino Render Meshes", True,
                help="Use the render meshes saved in the file (they match Rhino exactly). Untrimmed faces without "
                     "one are converted by Houdini; trimmed faces without one are skipped with a warning until "
                     "H3DM 0.3 (own tessellation)."),
        _toggle("weld", "Weld Faces of One Object", True, help="Faces of one Brep share points along their edges."),
        hou.SeparatorParmTemplate("sep_geo1"),
        _menu("curves", "Curves", [("nurbs", "NURBS Curves (exact)"), ("poly", "Polylines")]),
        hou.FloatParmTemplate("curvetol", "Curve Tolerance (model units)", 1, default_value=(0.0,), min=0.0, max=100.0,
                              conditionals={HIDE: "{ curves == nurbs }"},
                              help="Maximum distance between a curve and its polyline. 0 = 1 mm in model units."),
        _menu("subd", "SubD", [("cage", "Control Net"), ("smooth", "Subdivided")]),
        hou.IntParmTemplate("subdlevel", "SubD Level", 1, default_value=(2,), min=1, max=5,
                            conditionals={HIDE: "{ subd == cage }"}),
        _menu("blocks", "Blocks", [("packed", "Packed Instances"), ("expand", "Expand to Geometry")],
              help="Packed Instances: one packed geometry per block definition (per insertion style if the block "
                   "has By Parent objects). Expand: block objects are placed in the world; with Surface Output = "
                   "Packed each of them becomes its own packed primitive."),
    ]
    g.append(_folder("geo_f", "Geometry", geo))

    flt = [
        hou.StringParmTemplate("layers", "Layers", 1, default_value=("*",),
                               help="Globs on the full layer path (original names), ^glob excludes, e.g. "
                                    "Фасад::* ^*::Окна"),
        _toggle("skiphidden", "Skip Hidden", False,
                help="Skip hidden objects and objects on hidden layers (parents included), on all outputs and "
                     "inside blocks."),
        _toggle("skiplocked", "Skip Locked", False,
                help="Skip locked objects and objects on locked layers, on all outputs and inside blocks."),
        hou.SeparatorParmTemplate("sep_flt"),
        _toggle("t_surfaces", "Surfaces / Breps / Extrusions", True),
        _toggle("t_meshes", "Meshes", True),
        _toggle("t_subd", "SubD", True),
        _toggle("t_curves", "Curves", True),
        _toggle("t_points", "Points / Point Clouds", True),
        _toggle("t_blocks", "Blocks", True),
        hou.LabelParmTemplate("flt_note", "Note", column_labels=(
            "Type filters apply to block contents too. Layer globs apply to model objects (a block insertion "
            "is judged by its own layer).",)),
    ]
    g.append(_folder("filter_f", "Filter", flt))

    nm = [
        _menu("nonlatin", "Non-Latin Names", [("keep", "Keep"), ("translit", "Transliterate"),
                                              ("translit_keep", "Transliterate, Keep Original")], default=2),
        _menu("layercase", "Layer Case", [("keep", "Keep"), ("lower", "Lower"), ("project", "Project Rule")],
              conditionals={DISABLE: "{ nonlatin == keep }"}),
        hou.StringParmTemplate("layersep", "Layer Separator", 1, default_value=("::",)),
        _toggle("pathattr", "Create path Attribute", True, help="s@path = /layer/.../name, compatible with HIFC."),
    ]
    g.append(_folder("names_f", "Names", nm))

    at = [
        _menu("colormode", "Color", [("display", "Display Color (object / layer / material)"), ("object", "Object Color Only")]),
        _toggle("usertext", "User Text Dictionary (d@user_text)", True),
        _toggle("utflat", "User Text to Attributes", True, help="Each key becomes its own primitive attribute."),
        _toggle("utnumbers", "Detect Numbers", True,
                help="Whole numbers that fit int32 (no leading zeros) become integer attributes, decimals with up to "
                     "7 significant digits become float attributes. Everything else (007, 123456789012, long "
                     "decimals) stays text, so nothing is rounded.",
                conditionals={DISABLE: "{ utflat == 0 }"}),
        hou.StringParmTemplate("uttextkeys", "Keep as Text", 1, default_value=("",),
                               help="User Text keys (globs) that always stay text, e.g. id *_id code",
                               conditionals={DISABLE: "{ utflat == 0 } { utnumbers == 0 }"}),
        _toggle("groups", "Rhino Groups to Primitive Groups", True),
        _toggle("materials", "Material Attribute", True),
    ]
    g.append(_folder("attr_f", "Attributes", at))

    inf = [
        _toggle("i_dots", "Text Dots", True),
        _toggle("i_text", "Texts", True),
        _toggle("i_dims", "Dimensions and Leaders", True),
        _toggle("i_points", "Named Points", True),
        _toggle("i_lights", "Lights", True),
        _toggle("i_blocks", "Block Insertion Points", False),
    ]
    g.append(_folder("info_f", "Info Output", inf))

    cv = [
        _toggle("yup", "Z-Up to Y-Up", True),
        hou.FloatParmTemplate("scale", "Scale (units per meter)", 1, default_value=(1.0,), min=0.0001, max=1000.0,
                              help="Rhino model units are converted to meters, then multiplied by this value."),
    ]
    g.append(_folder("conv_f", "Conversion", cv))

    gt = [
        hou.LabelParmTemplate("gt_note", "Note", column_labels=(
            "Rhino stores double precision, Houdini positions are float32. The shift is computed in double "
            "BEFORE positions are stored. A connected Xform input (from another import) overrides this tab.",)),
        _menu("xformmode", "Global Transform", [
            ("auto_far", "Auto When Far From Origin"), ("auto", "Auto (bounding box)"),
            ("basepoint", "Rhino Model Base Point"), ("manual", "Manual Origin"), ("none", "None (keep coordinates)")],
            help="Which Rhino point becomes the Houdini origin. Auto = bounding box centre in X/Y and its bottom in Z, "
                 "rounded to Round To."),
        hou.FloatParmTemplate("farthreshold", "Far Threshold (meters)", 1, default_value=(1000.0,), min=0.0, max=100000.0,
                              conditionals={HIDE: "{ xformmode != auto_far }"},
                              help="Shift only if the model extends further than this from the origin."),
        hou.FloatParmTemplate("roundto", "Round To (meters)", 1, default_value=(1.0,), min=0.0, max=10000.0,
                              conditionals={HIDE: "{ xformmode != auto_far xformmode != auto }"},
                              help="The origin is rounded to this step so the shift is a clean number. 0 = no rounding."),
        hou.FloatParmTemplate("manualorigin", "Origin (model units)", 3, default_value=(0.0, 0.0, 0.0),
                              conditionals={HIDE: "{ xformmode != manual }"},
                              help="Rhino coordinates (model units) that become the Houdini origin."),
    ]
    g.append(_folder("xform_f", "Global Transform", gt))
    return g


def _export_ptg():
    g = hou.ParmTemplateGroup()
    g.append(hou.StringParmTemplate("file", "Output 3dm", 1, default_value=("$HIP/rhino/$HIPNAME.3dm",),
                                    string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Any,
                                    tags={"filechooser_pattern": "*.3dm", "filechooser_mode": "write"}))
    g.append(hou.ButtonParmTemplate("export", "Export 3dm", script_callback="import h3dm.sop_export as m; m.export_node(kwargs)",
                                    script_callback_language=PY, join_with_next=True))
    g.append(hou.ButtonParmTemplate("check", "Check Attributes", script_callback="import h3dm.sop_export as m; m.check_node(kwargs)",
                                    script_callback_language=PY, join_with_next=True))
    g.append(hou.ButtonParmTemplate("reveal", "Reveal File", script_callback="import h3dm.sop_export as m; m.reveal_file(kwargs)",
                                    script_callback_language=PY))
    g.append(_menu("version", "Rhino Version", [("8", "Rhino 8"), ("7", "Rhino 7"), ("6", "Rhino 6")]))

    un = [
        _menu("unit", "Model Units", [("mm", "Millimeters"), ("cm", "Centimeters"), ("m", "Meters")]),
        hou.FloatParmTemplate("scale", "Scene Unit (meters)", 1, default_value=(1.0,), min=0.0001, max=1000.0),
        _toggle("yup", "Y-Up to Z-Up", True),
        _menu("xformsrc", "Global Transform", [("input2", "From Input 2 (Xform), else Input 1 Detail"),
                                               ("detail", "From Input 1 Detail (h3dm_xform)"), ("none", "None")],
              help="Puts the geometry back to its original Rhino coordinates. The shift is added in double precision."),
    ]
    g.append(_folder("units_f", "Units", un))

    st = [
        hou.StringParmTemplate("layerattrib", "Layer Attribute", 1, default_value=("layer",)),
        hou.StringParmTemplate("layersep", "Layer Separator", 1, default_value=("::",)),
        hou.StringParmTemplate("defaultlayer", "Default Layer", 1, default_value=("Houdini",)),
        hou.StringParmTemplate("nameattrib", "Name Attribute", 1, default_value=("name",)),
        _menu("splitby", "Split Objects By", [("attrib", "Attribute"), ("connectivity", "Connectivity"), ("prim", "Primitive")]),
        hou.StringParmTemplate("splitattrib", "Split Attribute", 1, default_value=("rhino_id",),
                               help="Primitives with the same value become one Rhino object. Falls back to name, then path.",
                               conditionals={HIDE: "{ splitby != attrib }"}),
        _toggle("restorenames", "Restore Original Names", True,
                help="Uses layer_orig / name_orig and detail h3dm_name_map to write the original (e.g. Cyrillic) names."),
    ]
    g.append(_folder("struct_f", "Structure", st))

    at = [
        _toggle("color", "Object Color from Cd", True),
        _toggle("layercolor", "Layer Color from First Object", False),
        hou.StringParmTemplate("groups", "Groups", 1, default_value=("* ^rhino_*",),
                               help="Primitive groups to write as Rhino groups (globs, ^ excludes)."),
        hou.StringParmTemplate("utdict", "User Text Dict Attribute", 1, default_value=("user_text",)),
        hou.StringParmTemplate("utattribs", "User Text Attributes", 1, default_value=("",),
                               help="Primitive attribute globs written as User Text, e.g. id thickness category"),
        hou.SeparatorParmTemplate("sep_mat"),
        hou.StringParmTemplate("matattrib", "Material Attribute", 1, default_value=("material",)),
    ]
    rules = hou.FolderParmTemplate("matrules", "Material Mapping", folder_type=hou.folderType.MultiparmBlock, default_value=0)
    rules.addParmTemplate(hou.StringParmTemplate("mat_pattern#", "Match", 1, default_value=("*",),
                                                 help="Glob on the material attribute or shop_materialpath."))
    rules.addParmTemplate(hou.StringParmTemplate("mat_name#", "Rhino Material", 1, default_value=("",)))
    rules.addParmTemplate(hou.FloatParmTemplate("mat_color#", "Color", 3, default_value=(0.8, 0.8, 0.8),
                                                naming_scheme=hou.parmNamingScheme.RGBA, look=hou.parmLook.ColorSquare))
    rules.addParmTemplate(hou.FloatParmTemplate("mat_transp#", "Transparency", 1, default_value=(0.0,), min=0.0, max=1.0))
    at.append(rules)
    g.append(_folder("attr_f", "Attributes", at))

    ge = [
        _toggle("trimcurves", "Write Boundary Curves (Trim Curves)", True,
                help="NURBS surfaces are written untrimmed; their boundary curves (group rhino_trim_curves, or the "
                     "surface outline) are written next to them on the same layer and in the same group."),
        _menu("curves", "Curves", [("nurbs", "NURBS Curves"), ("poly", "Polylines")]),
        _toggle("textdots", "Points with s@text to Text Dots", True),
        _toggle("points", "Other Points to Point Objects", False),
        _menu("packed", "Packed Primitives", [("blocks", "Blocks"), ("explode", "Explode to Objects")]),
    ]
    g.append(_folder("geo_f", "Geometry", ge))

    rp = [
        _toggle("verify", "Read Back After Export", True),
        hou.StringParmTemplate("report", "Report", 1, default_value=("",), tags={"editor": "1", "editorlines": "6-20"}),
    ]
    g.append(_folder("out_f", "Report", rp))
    return g


def _parent_geo():
    obj = hou.node("/obj")
    tmp = obj.node("__h3dm_build")
    if tmp is not None:
        tmp.destroy()
    return obj.createNode("geo", "__h3dm_build")


def _tool_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer"><contextNetType>SOP</contextNetType></toolMenuContext>
    <toolMenuContext name="network"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType></toolMenuContext>
    <toolSubmenu>H3DM</toolSubmenu>
    <script scriptType="python"><![CDATA[import soptoolutils
soptoolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
"""


def _finish(node, type_name, label, hda_path, ptg, min_in, max_in, icon, help_text, outputs=1, output_labels=None):
    if os.path.exists(hda_path):
        for existing in hou.hda.definitionsInFile(hda_path):
            if existing.nodeTypeName() == type_name:
                existing.destroy()
    node.setParmTemplateGroup(ptg)
    hda = node.createDigitalAsset(name=type_name, hda_file_name=hda_path, description=label,
                                  min_num_inputs=min_in, max_num_inputs=max_in, ignore_external_references=True)
    d = hda.type().definition()
    # updateFromNode не синхронизирует интерфейс — пишем его в определение явно
    d.setParmTemplateGroup(ptg)
    d.setDescription(label)
    d.setIcon(icon)
    d.setVersion(__version__)
    if outputs > 1 and hasattr(d, "setMaxNumOutputs"):
        d.setMaxNumOutputs(outputs)
    if output_labels:
        # подписи выходов (секция DialogScript читает их из extra file options)
        for i, lab in enumerate(output_labels):
            try:
                d.setExtraFileOption("outputlabel%d" % (i + 1), lab)
            except Exception:
                pass
    d.addSection("Tools.shelf", _tool_xml())
    d.addSection("Help", help_text)
    d.save(hda_path, hda)
    return hda


def build_import(otls=None):
    geo = _parent_geo()
    sub = geo.createNode("subnet", "rhino_import")
    if sub.parm("label1") is not None:
        sub.parm("label1").set("Xform (optional)")
    nodes = []
    for i, (name, code) in enumerate((("GEO", GEO_CODE), ("INFO", INFO_CODE), ("XFORM", XFORM_CODE))):
        py = sub.createNode("python", name)
        py.parm("python").set(code)
        py.setInput(0, sub.indirectInputs()[0])
        o = sub.createNode("output", "OUT_" + name)
        o.parm("outputidx").set(i)
        o.setInput(0, py)
        nodes.append(o)
    nodes[0].setDisplayFlag(True)
    path = os.path.join(otls or OTLS, "h3dm_3dm_import.hda")
    _finish(sub, IMPORT_TYPE, "H3DM 3dm Import", path, _import_ptg(), 0, 1, "SOP_file", HELP_IMPORT,
            outputs=3, output_labels=("Geometry", "Info", "Xform"))
    return path


def build_export(otls=None):
    geo = _parent_geo()
    sub = geo.createNode("subnet", "rhino_export")
    if sub.parm("label1") is not None:
        sub.parm("label1").set("Geometry")
        sub.parm("label2").set("Xform (optional)")
    out = sub.createNode("output", "OUT")
    out.setInput(0, sub.indirectInputs()[0])
    path = os.path.join(otls or OTLS, "h3dm_3dm_export.hda")
    _finish(sub, EXPORT_TYPE, "H3DM 3dm Export", path, _export_ptg(), 1, 2, "SOP_rop_geometry", HELP_EXPORT)
    return path


def build_all(kwargs=None, otls=None, install=True):
    """otls — папка назначения (по умолчанию $H3DM/otls); install=False — не подгружать в сессию."""
    otls = otls or OTLS
    if not os.path.isdir(otls):
        os.makedirs(otls)
    paths = [build_import(otls), build_export(otls)]
    tmp = hou.node("/obj/__h3dm_build")
    if tmp is not None:
        tmp.destroy()
    for p in paths:
        if install:
            hou.hda.installFile(p)
            hou.hda.reloadFile(p)
        else:
            hou.hda.uninstallFile(p)
    msg = "H3DM HDAs built:\n" + "\n".join(paths)
    print("[H3DM] " + msg)
    if hou.isUIAvailable() and kwargs is not None:
        hou.ui.displayMessage(msg, title="H3DM")
    return paths


from .help_text import HELP_EXPORT, HELP_IMPORT  # noqa: E402

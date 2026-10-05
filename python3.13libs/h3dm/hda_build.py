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
                                    script_callback_language=PY, join_with_next=True))
    g.append(hou.ButtonParmTemplate("prepare", "Prepare in Rhino",
                                    script_callback="import h3dm.prepare_ui as m; m.prepare_node(kwargs)",
                                    script_callback_language=PY,
                                    help="Send the file to a running Rhino 8: it creates render meshes, exact trim "
                                         "data and NURBS from SubD and saves <name>_h3dm_v###.3dm next to the source. "
                                         "When done, 3dm File switches to that copy. Press again to cancel waiting. "
                                         "Settings: Prepare tab."))
    g.append(_menu("geomode", "Geometry Mode", [
        ("mesh_curves", "Mesh + NURBS Curves"), ("nurbs_surfaces", "NURBS Surfaces + Mesh Solids"),
        ("all_nurbs", "All NURBS"), ("legacy", "Legacy (0.2 Surface Output)")], default=3,
        help="Mesh + NURBS Curves: surfaces and solids as meshes, curves as exact NURBS. "
             "NURBS Surfaces + Mesh Solids: open surfaces as NURBS, closed solids as meshes. "
             "All NURBS: everything that has a NURBS form. Trimmed faces are trimmed NURBS when the file was "
             "prepared in Rhino (Prepare in Rhino), otherwise untrimmed NURBS + boundary curves with a warning. "
             "Legacy keeps the 0.2 behaviour of existing scenes; new nodes start with Mesh + NURBS Curves."))
    g.append(_toggle("pack", "Pack per Object", False, help="Each Rhino object becomes one packed primitive, "
                     "its contents follow the Geometry Mode.", conditionals={HIDE: "{ geomode == legacy }"}))
    g.append(_menu("surfout", "Surface Output", [("nurbs", "NURBS Patches"), ("polys", "Polygons"), ("packed", "Packed per Object")],
                   help="Legacy: how Breps, extrusions and surfaces are imported.",
                   conditionals={HIDE: "{ geomode != legacy }"}))
    g.append(_toggle("trimnurbs", "Trimmed Faces as Untrimmed NURBS + Boundary Curves", False,
                     help="Legacy: off = trimmed faces use the render mesh; on = untrimmed surface + boundary curves.",
                     conditionals={HIDE: "{ geomode != legacy } { surfout != nurbs }"}))

    geo = [
        _toggle("rendermesh", "Use Rhino Render Meshes", True,
                help="Use the render meshes saved in the file (they match Rhino exactly). Untrimmed faces without "
                     "one are converted by Houdini; trimmed faces without one are skipped with a warning — "
                     "use Prepare in Rhino to create the meshes."),
        _toggle("weld", "Weld Faces of One Object", True, help="Faces of one Brep share points along their edges."),
        hou.SeparatorParmTemplate("sep_geo1"),
        _menu("curves", "Curves", [("nurbs", "NURBS Curves (exact)"), ("poly", "Polylines")]),
        hou.FloatParmTemplate("trimtol", "Trim Curve Tolerance (model units)", 1, default_value=(0.0,), min=0.0, max=10.0,
                              help="Rational trim curves (arcs) become polylines in Houdini (Houdini ignores trim curve "
                                   "weights): maximum deviation, measured on the surface in model units. "
                                   "0 = 0.1 mm in model units."),
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

    prep = [
        _menu("prepmesh", "Mesh Preset", [("normal", "Document Mesh Settings"), ("coarse", "Coarse (Fast Render Mesh)"),
                                          ("fine", "Fine (Quality Render Mesh)")],
              help="Document Mesh Settings = Rhino Document Properties > Mesh of the source file."),
        hou.FloatParmTemplate("preptol", "Mesh Tolerance (model units)", 1, default_value=(0.0,), min=0.0, max=10.0,
                              help="Maximum distance between mesh and surface. 0 = preset value."),
        hou.FloatParmTemplate("prepangle", "Max Angle (degrees)", 1, default_value=(0.0,), min=0.0, max=90.0,
                              help="0 = preset value."),
        hou.FloatParmTemplate("prepedge", "Max Edge Length (model units)", 1, default_value=(0.0,), min=0.0, max=1000.0,
                              help="0 = preset value (no limit)."),
        _toggle("prepforce", "Always Create New Version", False,
                help="Off: an existing copy prepared from the same file with the same settings is reused."),
        hou.FloatParmTemplate("preptimeout", "Timeout (seconds)", 1, default_value=(900.0,), min=10.0, max=7200.0,
                              help="Stop waiting after this time. Rhino itself is not interrupted."),
        hou.LabelParmTemplate("prep_note", "Note", column_labels=(
            "Needs Rhino 8 running (Mac or Windows). If several are running you are asked which one to use. "
            "Rhino's open document is not touched: the file is opened headless.",)),
    ]

    cache = [
        _toggle("diskcache", "Disk Cache", True,
                help="Store the cooked Geometry and Info outputs on disk. The key covers the file (path, size, "
                     "modification time), every parameter, the global transform (Xform input included) and the "
                     "H3DM/Houdini versions, so a changed file or parameter cooks again. Reload skips the cache once."),
        hou.StringParmTemplate("cachedir", "Cache Folder", 1, default_value=("",),
                               string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Directory,
                               conditionals={DISABLE: "{ diskcache == 0 }"},
                               help="Empty = $HOUDINI_TEMP_DIR/h3dm_cache (or $H3DM_CACHE)."),
        hou.FloatParmTemplate("cachelimit", "Size Limit (MB)", 1, default_value=(4096.0,), min=100.0, max=100000.0,
                              conditionals={DISABLE: "{ diskcache == 0 }"},
                              help="When the folder grows larger, the least recently used entries are removed."),
        hou.FloatParmTemplate("cachemin", "Cache Cooks Longer Than (s)", 1, default_value=(0.5,), min=0.0, max=60.0,
                              conditionals={DISABLE: "{ diskcache == 0 }"},
                              help="Fast cooks are not stored."),
        hou.ButtonParmTemplate("cacheclear", "Clear Disk Cache",
                               script_callback="import h3dm.sop_import as m; m.clear_disk_cache(kwargs)",
                               script_callback_language=PY),
    ]

    nm = [
        _menu("nonlatin", "Non-Latin Names", [("keep", "Keep"), ("translit", "Transliterate"),
                                              ("translit_keep", "Transliterate, Keep Original")], default=2),
        _menu("layercase", "Layer Case", [("keep", "Keep"), ("lower", "Lower"), ("project", "Project Rule")],
              conditionals={DISABLE: "{ nonlatin == keep }"}),
        hou.StringParmTemplate("layersep", "Layer Separator", 1, default_value=("::",)),
        _toggle("pathattr", "Create path Attribute", True, help="s@path = /layer/.../name, compatible with HIFC."),
        _toggle("layerlevels", "Create Layer Level Attributes", True, join_with_next=True,
                help="Split s@layer into one string attribute per level: SC::STSZ::truby -> LL0 = SC, LL1 = STSZ, "
                     "LL2 = truby. Shallower layers get empty strings on the deeper levels. Names are after "
                     "transliteration and Layer Case, like s@layer."),
        hou.StringParmTemplate("layerlevelprefix", "Prefix", 1, default_value=("LL",),
                               conditionals={DISABLE: "{ layerlevels == 0 }"},
                               help="Attribute names: <prefix>0, <prefix>1, ... User Text keys with these names get "
                                    "the ut_ prefix."),
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
    g.append(_folder("prep_f", "Prepare", prep))
    g.append(_folder("cache_f", "Cache", cache))
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
    g.append(_toggle("overwrite", "Overwrite Existing File", False, join_with_next=True,
                     help="Off: if Output 3dm exists, a new version <name>_v###.3dm is written next to it."))
    g.append(_toggle("allowsource", "Allow Overwriting the Source File", False,
                     help="The file the geometry was imported from (and its prepared copy) is protected; "
                          "turn this on to replace it anyway (needs Overwrite Existing File)."))

    un = [
        _menu("xformsrc", "Global Transform", [("input2", "From Input 2 (Xform), else Input 1 Detail"),
                                               ("detail", "From Input 1 Detail (h3dm_xform)"), ("none", "None")],
              help="Puts the geometry back to its original Rhino coordinates, units and axes in one double-precision "
                   "step. A connected input 2 always wins; if it carries no h3dm_xform the export stops. Without "
                   "a transform, Scene Unit and Y-Up below are used."),
        _menu("unit", "Model Units", [("source", "As Imported (from the transform)"), ("mm", "Millimeters"),
                                      ("cm", "Centimeters"), ("m", "Meters"), ("in", "Inches"), ("ft", "Feet")],
              help="Units of the written file. As Imported = the units of the original Rhino file (millimeters "
                   "without a transform)."),
        hou.FloatParmTemplate("scale", "Scene Unit (meters)", 1, default_value=(1.0,), min=0.0001, max=1000.0,
                              help="Only without h3dm_xform: meters per Houdini unit."),
        _toggle("yup", "Y-Up to Z-Up", True, help="Only without h3dm_xform."),
    ]
    g.append(_folder("units_f", "Units", un))

    st = [
        hou.StringParmTemplate("layerattrib", "Layer Attribute", 1, default_value=("layer",)),
        hou.StringParmTemplate("layersep", "Layer Separator", 1, default_value=("::",)),
        hou.StringParmTemplate("defaultlayer", "Default Layer", 1, default_value=("Houdini",)),
        hou.StringParmTemplate("nameattrib", "Name Attribute", 1, default_value=("name",)),
        _menu("splitby", "Split Polygons By", [("auto", "Rhino Object (rhino_id + block part), else Connectivity"),
                                                ("attrib", "Attribute"), ("connectivity", "Connectivity"),
                                                ("prim", "Primitive")],
              help="Which polygons form one Rhino mesh. Curves and NURBS surfaces are always one object each. "
                   "Rhino Object: parts of an expanded block (same rhino_id) stay separate via "
                   "rhino_instance_id + rhino_part_path; new geometry without rhino_id is split by connectivity."),
        hou.StringParmTemplate("splitattrib", "Split Attribute", 1, default_value=("rhino_id",),
                               help="Polygons with the same value become one Rhino mesh; empty values: connectivity.",
                               conditionals={HIDE: "{ splitby != attrib }"}),
        _toggle("restorenames", "Restore Original Names", True,
                help="Names that are unchanged since the import (layers, objects, materials, groups, User Text keys) "
                     "go back to the original Rhino names (e.g. Cyrillic), from detail h3dm_export_names. "
                     "Renamed or new names are written as they are."),
        _toggle("doctext", "Write Document User Text", True, help="From detail rhino_doc_text of the import."),
        _toggle("alllayers", "Keep All Imported Layers", True,
                help="Write the whole layer table of the import (with colors, visibility, locking, layer User Text), "
                     "also layers that have no objects in Houdini."),
    ]
    g.append(_folder("struct_f", "Structure", st))

    at = [
        _toggle("color", "Object Color from Cd", True),
        _toggle("layercolor", "Layer Color from First Object", False),
        hou.StringParmTemplate("groups", "Groups", 1, default_value=("* ^rhino_* ^h3dm_*",),
                               help="Primitive groups to write as Rhino groups (globs, ^ excludes). Service groups "
                                    "(h3dm_type_*, rhino_*) are never written."),
        hou.StringParmTemplate("utdict", "User Text Dict Attribute", 1, default_value=("user_text",)),
        hou.StringParmTemplate("utattribs", "User Text Attributes", 1, default_value=("",),
                               help="More primitive attributes written as User Text (globs), e.g. id thickness. "
                                    "Attributes made from User Text by the import are always written back and "
                                    "win over the dictionary; service attributes (rhino_*, h3dm_*, LL0.., *_orig) never."),
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
        _toggle("passthrough", "Unchanged Objects from Source File", True,
                help="Objects that were imported with H3DM and not modified (every face matches the source Brep "
                     "or mesh within tolerance, after the export transform) are copied from the source .3dm "
                     "(detail attribute rhino_file) exactly: trims, holes, joined faces, extrusions. Changed "
                     "objects are exported from Houdini geometry. Works when the source file is still available."),
        _menu("trimmed", "Trimmed Surfaces", [("mesh", "Convert to Mesh"), ("skip", "Skip")],
              help="Trimmed NURBS faces (group rhino_trimmed_exact) of changed objects. Planar faces with one "
                   "outer loop (no holes) are always written exactly as trimmed planes. The others are meshed "
                   "for now (Houdini Convert respects the trims); rebuilding in Rhino comes next. "
                   "Faces imported without trim data (rhino_trimmed_surfaces) are never exported."),
        hou.FloatParmTemplate("meshlod", "Mesh Level of Detail", 1, default_value=(4.0,), min=0.5, max=32.0,
                              conditionals={HIDE: "{ trimmed != mesh }"},
                              help="Convert LOD for trimmed faces (divisions per span)."),
        _toggle("textdots", "Points with s@text to Text Dots", True),
        _toggle("points", "Other Points to Point Objects", True,
                help="Points without primitives; several points with one rhino_id become a point cloud."),
        _menu("packed", "Packed Primitives", [("blocks", "Blocks"), ("explode", "Explode to Objects")],
              help="Blocks: packed primitives with their own geometry become block insertions (one definition per "
                   "shared geometry, nested blocks too, full 4x4 transform in double precision, mirrored and "
                   "non-uniformly scaled insertions included). Packed per Object of the import is always "
                   "exploded. Explode: every part becomes its own object."),
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


def _finish(node, type_name, label, hda_path, ptg, min_in, max_in, icon, help_text, outputs=1, output_labels=None,
            on_created=None):
    node.setParmTemplateGroup(ptg)
    nt = hou.nodeType(hou.sopNodeTypeCategory(), type_name)
    d = nt.definition() if nt is not None else None
    if d is not None and os.path.normcase(os.path.abspath(d.libraryFilePath())) == os.path.normcase(os.path.abspath(hda_path)):
        # определение уже загружено из этого файла: обновляем на месте. Удаление определения (как раньше)
        # отвязывало ноды сцены, и их параметры сбрасывались к значениям по умолчанию.
        d.updateFromNode(node)
        d.setMinNumInputs(min_in)
        d.setMaxNumInputs(max_in)
        hda = node
    else:
        if os.path.exists(hda_path):
            for existing in hou.hda.definitionsInFile(hda_path):
                if existing.nodeTypeName() == type_name:
                    existing.destroy()
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
    if on_created:
        d.addSection("OnCreated", on_created)
        d.setExtraFileOption("OnCreated/IsPython", True)
    d.addSection("Help", help_text)
    d.save(hda_path)
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
            outputs=3, output_labels=("Geometry", "Info", "Xform"),
            on_created="# новые ноды: режим по умолчанию (старые сцены сохраняют Legacy)\n"
                       "kwargs['node'].parm('geomode').set('mesh_curves')\n")
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


def _snapshot():
    """Значения параметров всех нод H3DM в сцене (страховка при пересборке определений)."""
    out = {}
    for tn in (IMPORT_TYPE, EXPORT_TYPE):
        nt = hou.nodeType(hou.sopNodeTypeCategory(), tn)
        if nt is None:
            continue
        for n in nt.instances():
            vals = {}
            for p in n.parms():
                try:
                    if p.parmTemplate().type() in (hou.parmTemplateType.Button, hou.parmTemplateType.Label,
                                                   hou.parmTemplateType.Folder, hou.parmTemplateType.FolderSet,
                                                   hou.parmTemplateType.Separator):
                        continue
                    try:
                        vals[p.name()] = ("expr", p.expression(), p.expressionLanguage())
                    except hou.OperationFailed:
                        vals[p.name()] = ("raw", p.rawValue() if isinstance(p.eval(), str) else p.eval())
                except Exception:
                    pass
            out[n.path()] = vals
    return out


def _restore(saved):
    """Вернуть значения, если пересборка их изменила. -> число нод, где что-то восстановлено."""
    count = 0
    for path, vals in saved.items():
        n = hou.node(path)
        if n is None:
            continue
        changed = False
        for name, v in vals.items():
            p = n.parm(name)
            if p is None:
                continue
            try:
                if v[0] == "expr":
                    try:
                        same = p.expression() == v[1]
                    except hou.OperationFailed:
                        same = False
                    if not same:
                        p.setExpression(v[1], v[2])
                        changed = True
                else:
                    cur = p.rawValue() if isinstance(v[1], str) else p.eval()
                    if cur != v[1]:
                        p.set(v[1])
                        changed = True
            except Exception:
                pass
        count += changed
    return count


def build_all(kwargs=None, otls=None, install=True):
    """otls — папка назначения (по умолчанию $H3DM/otls); install=False — не подгружать в сессию."""
    otls = otls or OTLS
    if not os.path.isdir(otls):
        os.makedirs(otls)
    saved = _snapshot()
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
    restored = _restore(saved)
    msg = "H3DM HDAs built:\n" + "\n".join(paths)
    if restored:
        msg += "\nRestored parameter values on %d node(s)." % restored
    print("[H3DM] " + msg)
    if hou.isUIAvailable() and kwargs is not None:
        hou.ui.displayMessage(msg, title="H3DM")
    return paths


from .help_text import HELP_EXPORT, HELP_IMPORT  # noqa: E402

# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Команды для полки и главного меню H3DM."""
import os

import hou

from . import __version__, ROOT, IMPORT_TYPE, EXPORT_TYPE  # noqa: F401


def _sop_parent():
    """Текущая SOP-сеть в Network Editor или None."""
    try:
        pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        net = pane.pwd() if pane else None
    except Exception:
        net = None
    if net is not None and net.childTypeCategory() == hou.sopNodeTypeCategory():
        return net
    return None


def _need_type(type_name):
    nt = hou.nodeType(hou.sopNodeTypeCategory(), type_name)
    if nt is None:
        hou.ui.displayMessage("%s is not installed. Run H3DM > Rebuild HDAs." % type_name, title="H3DM")
    return nt


def import_3dm(kwargs=None):
    """Выбрать .3dm и создать для него узел H3DM 3dm Import."""
    if _need_type(IMPORT_TYPE) is None:
        return None
    path = hou.ui.selectFile(title="H3DM: Import 3dm", pattern="*.3dm", chooser_mode=hou.fileChooserMode.Read)
    if not path:
        return None
    parent = _sop_parent()
    if parent is None:
        from .names import safe_identifier
        name = os.path.splitext(os.path.basename(hou.text.expandString(path)))[0]
        parent = hou.node("/obj").createNode("geo", safe_identifier(name, translit=True) or "rhino")
    node = parent.createNode(IMPORT_TYPE, "rhino_import")
    node.parm("file").set(path)
    node.setDisplayFlag(True)
    node.setRenderFlag(True)
    node.setSelected(True, clear_all_selected=True)
    return node


def export_selected(kwargs=None):
    """Повесить H3DM 3dm Export на выбранный SOP."""
    if _need_type(EXPORT_TYPE) is None:
        return None
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if not sel:
        hou.ui.displayMessage("Select a SOP node to export.", title="H3DM")
        return None
    src = sel[0]
    node = src.parent().createNode(EXPORT_TYPE, "rhino_export")
    node.setInput(0, src)
    node.setSelected(True, clear_all_selected=True)
    return node


def install_deps(kwargs=None):
    from . import deps, RHINO3DM_TESTED, rhino3dm_version
    cur = rhino3dm_version()
    if cur == RHINO3DM_TESTED:
        hou.ui.displayMessage("rhino3dm %s is installed — the version this H3DM was tested with." % cur, title="H3DM")
        return
    try:
        with hou.InterruptableOperation("H3DM: installing rhino3dm %s" % RHINO3DM_TESTED, open_interrupt_dialog=True):
            target = deps.install()
        hou.ui.displayMessage("rhino3dm %s installed to:\n%s\n\n%sRestart Houdini so that the new version is loaded."
                              % (RHINO3DM_TESTED, target, ("(was %s)\n" % cur) if cur else ""), title="H3DM")
    except Exception as ex:
        hou.ui.displayMessage("Install failed:\n%s" % ex, title="H3DM", severity=hou.severityType.Error)


def rebuild_hdas(kwargs=None):
    from . import hda_build
    hda_build.build_all(kwargs or {})


def about(kwargs=None):
    from . import deps
    st = deps.status()
    from . import HDA_VERSION, HOUDINI_TESTED
    msg = ("H3DM %s — Rhino .3dm import/export for Houdini (assets %s)\nRoot: %s\n\nrhino3dm: %s %s (tested: %s%s)\n"
           "vendor: %s\nPython: %s\nHoudini: %s (tested: %s)\n\nVersions of all installed assets: VERSIONS.json"
           % (__version__, HDA_VERSION, ROOT, "OK" if st["rhino3dm"] else "NOT FOUND", st["version"], st["tested"],
              "" if st["match"] else " — differs", st["vendor"], st["python"], hou.applicationVersionString(),
              HOUDINI_TESTED))
    hou.ui.displayMessage(msg, title="H3DM")


def attribute_template(kwargs=None):
    """Primitive Wrangle с шаблоном атрибутов экспорта после выбранной ноды."""
    from . import templates
    return templates.create_wrangle(kwargs)


def attribute_guide(kwargs=None):
    """Открыть справку H3DM 3dm Export (правила атрибутов)."""
    nt = _need_type(EXPORT_TYPE)
    if nt is not None:
        hou.ui.displayNodeHelp(nt)

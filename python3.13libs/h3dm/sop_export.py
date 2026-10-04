# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""SOP-слой экспорта: геометрия Houdini -> .3dm (этап 5).

Кнопки HDA h3dm::3dm_export вызывают export_node / check_node / reveal_file.
"""
import os

import hou


def _not_yet(kwargs):
    hou.ui.displayMessage("3dm export comes in H3DM 0.4. This version imports only.", title="H3DM")


def export_node(kwargs):
    _not_yet(kwargs)


def check_node(kwargs):
    _not_yet(kwargs)


def reveal_file(kwargs):
    """Показать файл экспорта в Finder/Explorer."""
    node = kwargs["node"]
    path = hou.text.expandString(node.parm("file").evalAsString())
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        hou.ui.displayMessage("Folder does not exist yet:\n%s" % folder, title="H3DM")
        return
    import subprocess
    import sys
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if os.path.exists(path) else ["open", folder])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)] if os.path.exists(path) else ["explorer", folder])
    else:
        subprocess.Popen(["xdg-open", folder])

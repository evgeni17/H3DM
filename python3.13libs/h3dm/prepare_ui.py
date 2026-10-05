# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Prepare in Rhino: кнопка на ноде импорта и пункт меню H3DM.

Ожидание идёт в цикле событий Houdini (hou.ui.addEventLoopCallback), а не в cook Python SOP:
интерфейс не блокируется. Одно задание на ноду; повторное нажатие предлагает отменить ожидание.
Поздний результат (после отмены, тайм-аута или нового задания) ноду не меняет.
"""
import os
import time

import hou

from . import rhino_bridge

_KEY = "h3dm_prepare_job"
_ACTIVE = {}          # id задания -> (state, node_path, file_raw, timeout, callback)


# ---------------------------------------------------------------- настройки и выбор Rhino

def node_settings(node):
    def f(name, default=0.0):
        p = node.parm(name)
        return p.eval() if p is not None else default
    st = {"preset": node.parm("prepmesh").evalAsString() if node.parm("prepmesh") else "normal"}
    for parm, key in (("preptol", "tolerance"), ("prepangle", "max_angle"), ("prepedge", "max_edge")):
        v = float(f(parm))
        if v > 0:
            st[key] = v
    if f("prepforce", 0):
        st["force"] = True
    return st


def choose_rhino():
    """id экземпляра Rhino или None (отмена). Ошибка BridgeError — если Rhino не запущен."""
    inst = rhino_bridge.list_instances()
    if rhino_bridge.cli_command() is None:
        raise rhino_bridge.BridgeError("Rhino 8 is not installed (RhinoCode CLI not found). "
                                       "Set H3DM_RHINOCODE to its path if Rhino is installed elsewhere.")
    if not inst:
        raise rhino_bridge.BridgeError("No running Rhino 8 found.\n\nStart Rhino 8 and press Prepare in Rhino "
                                       "again. If Rhino is running, run its command StartScriptServer.")
    if len(inst) == 1 or not hou.isUIAvailable():
        return inst[0]["id"]
    labels = ["Rhino %s  (pid %s)  %s" % (i["version"], i["pid"], i["doc"]) for i in inst]
    sel = hou.ui.selectFromList(labels, default_choices=(0,), exclusive=True, title="H3DM: Prepare in Rhino",
                                message="Several Rhino instances are running. Which one should prepare the file?")
    if not sel:
        return None
    return inst[sel[0]]["id"]


def _message(text, severity=hou.severityType.Message, details=None):
    if hou.isUIAvailable():
        hou.ui.displayMessage(text, severity=severity, title="H3DM: Prepare in Rhino", details=details,
                              details_expanded=False)
    else:
        print("H3DM: " + text + ("\n" + details if details else ""))


def _status(text, severity=hou.severityType.Message):
    if hou.isUIAvailable():
        hou.ui.setStatusMessage("H3DM: " + text, severity=severity)


def _short_error(err):
    lines = [l for l in str(err or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else "unknown error"


# ---------------------------------------------------------------- файл ноды

def _new_file_value(raw, src, output):
    """Сохранить переменные ($HIP и т.п.) в пути: заменить только имя файла, если папка та же."""
    if os.path.dirname(os.path.abspath(output)) == os.path.dirname(os.path.abspath(src)):
        base_old = os.path.basename(src)
        if raw.endswith(base_old):
            return raw[: len(raw) - len(base_old)] + os.path.basename(output)
    return output


def apply_result(node, res, file_raw, src):
    """Обновить ноду по результату. -> текст для пользователя."""
    status = res.get("status")
    out = res.get("output")
    if status in ("ok", "skipped") and out:
        cur = node.parm("file").unexpandedString()
        if cur != file_raw:
            return ("Prepared copy: %s\n3dm File was changed while Rhino was working, so it was left as is."
                    % out)
        node.parm("file").set(_new_file_value(file_raw, src, out))
        if status == "skipped":
            return "Up to date: %s (same source and settings, reused)." % os.path.basename(out)
        stt = res.get("stats") or {}
        return ("Prepared in %.1f s: %s\nFaces meshed %s / %s, SubD converted %s."
                % (res.get("elapsed") or 0, os.path.basename(out), stt.get("check_faces_meshed", "?"),
                   stt.get("check_faces", "?"), stt.get("subd_converted", 0)))
    return None


# ---------------------------------------------------------------- задание

def _finish(jid, res):
    item = _ACTIVE.pop(jid, None)
    if item is None:
        return
    state, node_path, file_raw, timeout, cb = item
    try:
        hou.ui.removeEventLoopCallback(cb)
    except Exception:
        pass
    node = hou.node(node_path) if node_path else None
    if node is not None and node.cachedUserData(_KEY) == jid:
        node.destroyCachedUserData(_KEY)
    elif node_path:
        return                              # нода удалена или ждёт уже другое задание
    status = res.get("status")
    if status == "cancelled":
        _status("waiting for Rhino cancelled (Rhino may still finish the copy).")
        return
    if status == "timeout":
        _message("Rhino did not finish within %d s. The node was not changed.\n\nCheck Rhino: a dialog may be "
                 "waiting for an answer, or the file is very large (raise Timeout on the Prepare tab). Rhino may "
                 "still write the copy next to the source — press Prepare in Rhino again later to pick it up."
                 % timeout, hou.severityType.Warning)
        return
    if status in ("ok", "skipped"):
        if node is not None:
            text = apply_result(node, res, file_raw, state["source"])
        else:
            text = "Prepared copy: %s" % res.get("output")
        # успех — только строка состояния (модальное окно мешало бы работе); без ноды — путь нужен пользователю
        _status(text.replace("\n", "  "))
        if node is None:
            _message(text)
        else:
            print("H3DM: " + text.replace("\n", "  "))
        return
    _message("Rhino could not prepare the file: %s" % _short_error(res.get("error")), hou.severityType.Error,
             details=res.get("error"))


def _make_callback(jid):
    def cb():
        item = _ACTIVE.get(jid)
        if item is None:
            return
        state, node_path, file_raw, timeout, _ = item
        res = rhino_bridge.poll(state)
        if res is None and time.time() - state["started"] > timeout:
            res = {"status": "timeout", "id": jid}
        if res is None:
            n = int(time.time() - state["started"])
            if n != state.get("_shown"):
                state["_shown"] = n
                pr = rhino_bridge.progress(state) or {}
                stage = rhino_bridge.STAGES.get(pr.get("stage"), "waiting for Rhino")
                if pr.get("n"):
                    stage += " %d/%d" % (pr.get("i", 0) + 1, pr["n"])
                _status("Rhino: %s — %s, %d:%02d (press Prepare in Rhino again to stop waiting)"
                        % (os.path.basename(state["source"]), stage, n // 60, n % 60))
            return
        _finish(jid, res)
    return cb


def start(src, settings, rhino_id, node=None, timeout=900.0):
    """Отправить задание; в UI — ждать в цикле событий, без UI — синхронно. -> state или результат."""
    from . import rhino_read
    src = rhino_read.prepare_source(src)          # подготовленная копия -> её исходник
    state = rhino_bridge.submit(src, settings, rhino_id)
    jid = state["id"]
    file_raw = node.parm("file").unexpandedString() if node is not None else None
    if node is not None:
        node.setCachedUserData(_KEY, jid)
    if not hou.isUIAvailable():
        res = rhino_bridge.wait(state, timeout)
        _ACTIVE[jid] = (state, node.path() if node is not None else None, file_raw, timeout, None)
        _finish(jid, res)
        return res
    cb = _make_callback(jid)
    _ACTIVE[jid] = (state, node.path() if node is not None else None, file_raw, timeout, cb)
    hou.ui.addEventLoopCallback(cb)
    _status("sent %s to Rhino ..." % os.path.basename(src))
    return state


def cancel_node(node):
    jid = node.cachedUserData(_KEY)
    item = _ACTIVE.get(jid)
    if item is None:
        node.destroyCachedUserData(_KEY)
        return
    rhino_bridge.cancel(item[0])
    _finish(jid, {"status": "cancelled", "id": jid})


# ---------------------------------------------------------------- кнопка и меню

def prepare_node(kwargs):
    node = kwargs["node"]
    jid = node.cachedUserData(_KEY)
    if jid and jid in _ACTIVE:
        if hou.isUIAvailable() and hou.ui.displayMessage(
                "Rhino is still preparing this node's file.\n\nStop waiting? Rhino itself keeps working and still "
                "writes the copy; press Prepare in Rhino again later to pick it up (it is reused, not rebuilt).",
                buttons=("Stop Waiting", "Keep Waiting"),
                default_choice=1, close_choice=1, title="H3DM: Prepare in Rhino") == 0:
            cancel_node(node)
        return
    path = hou.text.expandString(node.parm("file").evalAsString())
    if not path or not os.path.isfile(path):
        _message("Set 3dm File to an existing .3dm file first.", hou.severityType.Warning)
        return
    try:
        rid = choose_rhino()
        if rid is None:
            return
        start(path, node_settings(node), rid, node=node, timeout=float(node.evalParm("preptimeout")))
    except rhino_bridge.BridgeError as ex:
        _message(str(ex), hou.severityType.Error)
    except Exception as ex:
        _message("Prepare in Rhino failed: %s" % ex, hou.severityType.Error)


def prepare_file_menu(kwargs=None):
    """Меню H3DM > Prepare in Rhino...: выбранная нода импорта или файл с диска."""
    from .hda_build import IMPORT_TYPE
    for n in hou.selectedNodes():
        if n.type().name() == IMPORT_TYPE:
            prepare_node({"node": n})
            return
    path = hou.ui.selectFile(title="H3DM: 3dm file to prepare in Rhino", pattern="*.3dm",
                             chooser_mode=hou.fileChooserMode.Read)
    if not path:
        return
    path = hou.text.expandString(path)
    try:
        rid = choose_rhino()
        if rid is None:
            return
        start(path, {"preset": "normal"}, rid, node=None)
    except rhino_bridge.BridgeError as ex:
        _message(str(ex), hou.severityType.Error)


def open_rhino_folder(kwargs=None):
    """Папка со скриптом для ручного запуска в Rhino (ScriptEditor / RunPythonScript)."""
    import subprocess
    import sys
    d = os.path.dirname(rhino_bridge.PREPARE_SCRIPT)
    if sys.platform == "darwin":
        subprocess.Popen(["open", d])
    elif sys.platform == "win32":
        os.startfile(d)
    else:
        subprocess.Popen(["xdg-open", d])

# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Связь с запущенным Rhino 8 через RhinoCode CLI: подготовка .3dm (rhino/h3dm_prepare.py) по заданию.

Протокол:
  1. H3DM пишет задание JSON {id, source, settings} и скрипт-обёртку в $HOUDINI_TEMP_DIR/h3dm_jobs/;
  2. отправляет обёртку в выбранный Rhino (RhinoCode CLI: script). CLI завершается РАНЬШЕ скрипта и даёт код 0
     даже при ошибке скрипта, поэтому итог читается только из <задание>.result.json (id, статус, ошибка, путь);
  3. ожидание — в цикле событий Houdini (интерфейс не блокируется), с тайм-аутом и отменой.
     Отмена/тайм-аут не останавливают Rhino; поздний результат игнорируется.

На Mac обёртка rhinocode передаёт аргументы без кавычек ($@) и ломает пути с пробелами — поэтому вызываются
поставляемые dotnet и RhinoCode.dll напрямую, каждым аргументом отдельно. На Windows — rhinocode.exe.
Нужен запущенный Rhino 8 с сервером скриптов (обычно поднимается сам; иначе команда StartScriptServer в Rhino).
"""
import glob
import json
import os
import subprocess
import sys
import time
import uuid

from . import ROOT

PREPARE_SCRIPT = os.path.join(ROOT, "rhino", "h3dm_prepare.py")
_JOBS = {}            # id задания -> состояние (для отмены и игнорирования поздних результатов)


class BridgeError(RuntimeError):
    pass


# ---------------------------------------------------------------- RhinoCode CLI

def cli_command():
    """Команда RhinoCode CLI (список аргументов) или None."""
    env = os.environ.get("H3DM_RHINOCODE")
    if env and os.path.exists(env):
        return [env]
    if sys.platform == "darwin":
        for app in sorted(glob.glob("/Applications/Rhino 8*.app"), reverse=True):
            res = os.path.join(app, "Contents", "Frameworks", "RhCore.framework", "Versions", "Current", "Resources")
            dll = os.path.join(res, "RhinoCode.dll")
            arch = os.uname().machine
            dotnet = os.path.join(res, "dotnet", arch, "dotnet")
            if os.path.exists(dll) and os.path.exists(dotnet):
                return [dotnet, dll]
    elif sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
            exe = os.path.join(base, "Rhino 8", "System", "RhinoCode.exe")
            if os.path.exists(exe):
                return [exe]
    return None


def _run(args, timeout=30):
    cmd = cli_command()
    if cmd is None:
        raise BridgeError("Rhino 8 / RhinoCode CLI not found. Install Rhino 8 or set H3DM_RHINOCODE.")
    r = subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def list_instances():
    """Запущенные экземпляры Rhino: [{'id', 'pid', 'version', 'doc'}]."""
    try:
        code, out, err = _run(["list", "--json"])
    except BridgeError:
        return []
    except Exception:
        return []
    try:
        data = json.loads(out.strip() or "[]")
    except Exception:
        return []
    res = []
    for d in data:
        doc = (d.get("activeDoc") or {})
        res.append({"id": d.get("pipeId"), "pid": d.get("processId"), "version": d.get("processVersion", ""),
                    "doc": doc.get("title") or doc.get("location") or "(untitled)"})
    return res


# ---------------------------------------------------------------- задания

def jobs_dir():
    base = os.environ.get("HOUDINI_TEMP_DIR") or os.path.join(os.path.expanduser("~"), ".h3dm")
    d = os.path.join(base, "h3dm_jobs")
    os.makedirs(d, exist_ok=True)
    # старые задания (> 7 дней) удаляются
    now = time.time()
    for f in os.listdir(d):
        p = os.path.join(d, f)
        try:
            if now - os.path.getmtime(p) > 7 * 86400:
                os.remove(p)
        except OSError:
            pass
    return d


def submit(source, settings=None, rhino_id=None):
    """Отправить задание в Rhino. -> {'id', 'job', 'result', 'started'}. Не ждёт результата."""
    if not os.path.isfile(source):
        raise BridgeError("Source file not found: %s" % source)
    with open(source, "rb") as fh:
        if fh.read(24) != b"3D Geometry File Format ":
            raise BridgeError("Not a Rhino .3dm file: %s" % source)
    if not os.path.isfile(PREPARE_SCRIPT):
        raise BridgeError("Prepare script not found: %s" % PREPARE_SCRIPT)
    inst = list_instances()
    if not inst:
        raise BridgeError("No running Rhino 8 found. Start Rhino 8 (if it is running, run the Rhino command "
                          "StartScriptServer) and try again.")
    if rhino_id and rhino_id not in [i["id"] for i in inst]:
        raise BridgeError("Rhino instance %s is not running any more." % rhino_id)
    rid = rhino_id or inst[0]["id"]
    jid = uuid.uuid4().hex[:12]
    d = jobs_dir()
    job = os.path.join(d, "job_%s.json" % jid)
    runner = os.path.join(d, "run_%s.py" % jid)
    with open(job, "w", encoding="utf-8") as fh:
        json.dump({"id": jid, "source": os.path.abspath(source), "settings": dict(settings or {})}, fh)
    with open(runner, "w", encoding="utf-8") as fh:
        fh.write("# H3DM: задание подготовки %s\n" % jid)
        fh.write("H3DM_JOB = %r\n" % job)
        fh.write("exec(compile(open(%r, encoding='utf-8').read(), %r, 'exec'))\n" % (PREPARE_SCRIPT, PREPARE_SCRIPT))
    # CLI запускается без ожидания: dotnet стартует ~3 с, интерфейс Houdini не должен ждать
    log = open(job + ".cli.log", "w", encoding="utf-8")
    proc = subprocess.Popen(cli_command() + ["--rhino", rid, "script", runner], stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    state = {"id": jid, "job": job, "result": job + ".result.json", "started": time.time(), "rhino": rid,
             "source": os.path.abspath(source), "cancelled": False, "proc": proc, "log": log}
    _JOBS[jid] = state
    return state


def _cli_failure(state):
    """Текст ошибки, если CLI завершился неудачно до появления результата."""
    proc = state.get("proc")
    if proc is None or proc.poll() is None:
        return None
    try:
        state["log"].close()
    except Exception:
        pass
    try:
        text = open(state["job"] + ".cli.log", encoding="utf-8", errors="replace").read().strip()
    except Exception:
        text = ""
    if proc.returncode != 0:
        return "RhinoCode CLI failed (%d): %s" % (proc.returncode, text[-500:])
    low = text.lower()
    if "error" in low or "exception" in low or "not found" in low:
        return "RhinoCode CLI: %s" % text[-500:]
    return None


def poll(state):
    """None — ещё идёт; иначе словарь результата."""
    if state.get("cancelled"):
        return {"status": "cancelled", "id": state["id"]}
    p = state["result"]
    if not os.path.exists(p):
        # CLI мог упасть сразу (Rhino закрыт, сервер скриптов не отвечает); ждём ещё немного результата
        fail = _cli_failure(state)
        if fail and time.time() - state.get("cli_done", time.time()) > 5.0:
            return {"status": "error", "error": fail, "id": state["id"]}
        if fail and "cli_done" not in state:
            state["cli_done"] = time.time()
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            res = json.load(fh)
    except Exception:
        return None          # файл ещё пишется
    if res.get("id") not in (None, state["id"]):
        return {"status": "error", "error": "result belongs to another job", "id": state["id"]}
    return res


def cancel(state):
    state["cancelled"] = True


def wait(state, timeout=600.0, interval=0.25):
    """Синхронное ожидание (для тестов и hython)."""
    t_end = time.time() + timeout
    while time.time() < t_end:
        res = poll(state)
        if res is not None:
            return res
        time.sleep(interval)
    return {"status": "timeout", "id": state["id"]}

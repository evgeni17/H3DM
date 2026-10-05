# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""H3DM: подготовка .3dm в Rhino 8 (Python 3) для импорта в Houdini.

Что делает (исходный файл только читается):
  * тела (Brep, Extrusion) -> NURBS-грани (Brep.MakeValidForV2), SubD -> NURBS (SubD.ToBrep);
  * при каждом теле сохраняет 2D-кривые обрезки граней (строка геометрии "h3dm.trims", JSON+zlib+base64) —
    из них H3DM строит точные обрезанные NURBS в Houdini (rhino3dm сам их не отдаёт);
  * строит сетки отображения (пресет coarse / normal / fine или свои значения);
  * сохраняет новую версию рядом с исходником: <имя>_h3dm_v001.3dm, _v002... (чужие файлы не перезаписываются,
    запись атомарная: временный файл -> переименование);
  * повтор пропускается, если последняя версия сделана из того же исходника с теми же настройками.

Запуск:
  * из Houdini (кнопка Prepare in Rhino): H3DM пишет задание JSON и запускает в Rhino маленький скрипт,
    который задаёт H3DM_JOB = "<путь к заданию>" и выполняет этот файл; результат — <задание>.result.json;
  * вручную: в Rhino _RunPythonScript этот файл -> готовится текущий сохранённый документ (пресет normal).
"""
import base64
import hashlib
import json
import os
import time
import uuid
import traceback
import zlib

import Rhino
import Rhino.Geometry as G
import System

PREP_VERSION = 1
PRESETS = ("coarse", "normal", "fine")


# ---------------------------------------------------------------- параметры сетки

def meshing_parameters(doc, settings):
    """normal = настройки сетки документа (Свойства документа -> Сетка); coarse/fine — встроенные Rhino."""
    preset = settings.get("preset", "normal")
    if preset == "coarse":
        mp = G.MeshingParameters.FastRenderMesh
    elif preset == "fine":
        mp = G.MeshingParameters.QualityRenderMesh
    else:
        try:
            mp = doc.GetCurrentMeshingParameters()
        except Exception:
            mp = None
        if mp is None:
            mp = G.MeshingParameters.Default
    # свои значения поверх пресета (0 = не менять)
    if settings.get("tolerance"):
        mp.Tolerance = float(settings["tolerance"])
    if settings.get("max_angle"):
        mp.RefineAngle = float(settings["max_angle"]) * 3.141592653589793 / 180.0
    if settings.get("max_edge"):
        mp.MaximumEdgeLength = float(settings["max_edge"])
    return mp


def mp_summary(mp):
    return {"tolerance": mp.Tolerance, "refine_angle_deg": mp.RefineAngle * 180.0 / 3.141592653589793,
            "max_edge": mp.MaximumEdgeLength, "min_edge": mp.MinimumEdgeLength, "grid_min": mp.GridMinCount,
            "simple_planes": mp.SimplePlanes, "jagged_seams": mp.JaggedSeams}


# ---------------------------------------------------------------- кривые обрезки

def _curve_data(c):
    n = c.ToNurbsCurve()
    pts = []
    for i in range(n.Points.Count):
        p = n.Points[i]
        pts.append([p.Location.X, p.Location.Y, p.Weight])
    return {"o": n.Order, "k": [n.Knots[i] for i in range(n.Knots.Count)], "p": pts, "r": bool(n.IsRational)}


def trims_data(brep, areas=False):
    """Петли кривых обрезки всех граней (Brep уже V2: все грани — NurbsSurface).

    areas=True добавляет площадь каждой грани (AreaMassProperties) — только для проверок: на сложных
    моделях это почти всё время подготовки (3873 грани: 507 с из 527)."""
    faces = []
    for fi in range(brep.Faces.Count):
        fc = brep.Faces[fi]
        loops = []
        for lp in fc.Loops:
            loops.append({"t": str(lp.LoopType).split(".")[-1],
                          "c": [_curve_data(tr.TrimCurve) for tr in lp.Trims]})
        area = None
        if areas:
            try:
                amp = G.AreaMassProperties.Compute(fc.DuplicateFace(False))
                area = amp.Area if amp is not None else None
            except Exception:
                pass
        faces.append({"f": fi, "a": area, "l": loops,
                      "d": [fc.Domain(0).T0, fc.Domain(0).T1, fc.Domain(1).T0, fc.Domain(1).T1]})
    raw = json.dumps({"v": PREP_VERSION, "faces": faces}, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, 6)).decode("ascii")


def convert_geometry(g, stats, areas=False):
    """-> (новая геометрия или None, тип исходника). Brep/Extrusion -> V2 Brep, SubD -> NURBS Brep."""
    src = type(g).__name__
    b = None
    if isinstance(g, G.Extrusion):
        b = g.ToBrep(True)
    elif isinstance(g, G.SubD):
        try:
            b = g.ToBrep(G.SubDToBrepOptions.Default)
        except Exception:
            b = None
        if b is None:
            stats["subd_failed"] += 1
            return None, src
        stats["subd_converted"] += 1
    elif isinstance(g, G.Brep):
        b = g.DuplicateBrep()
    if b is None:
        return None, src
    if not b.MakeValidForV2():
        stats["v2_failed"] += 1
    b.SetUserString("h3dm.trims", trims_data(b, areas))
    b.SetUserString("h3dm.source_type", src)
    stats["breps"] += 1
    stats["faces"] += b.Faces.Count
    return b, src


# ---------------------------------------------------------------- версии и отпечаток

def is_3dm(path):
    """Сигнатура архива 3dm: файл начинается с "3D Geometry File Format " (иначе OpenHeadless может
    «открыть» посторонний файл как пустой документ или через импорт)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(24) == b"3D Geometry File Format "
    except OSError:
        return False


def fingerprint(path):
    st = os.stat(path)
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return {"path": os.path.abspath(path), "size": st.st_size, "mtime": st.st_mtime, "sha1": h.hexdigest()}


def versions(src):
    """Существующие версии <имя>_h3dm_vNNN.3dm рядом с исходником (по возрастанию)."""
    folder, name = os.path.split(os.path.abspath(src))
    stem = os.path.splitext(name)[0]
    out = []
    for fn in os.listdir(folder):
        if fn.startswith(stem + "_h3dm_v") and fn.endswith(".3dm"):
            num = fn[len(stem) + 7:-4]
            if num.isdigit():
                out.append((int(num), os.path.join(folder, fn)))
    return sorted(out)


def read_stamp(path):
    """Отпечаток подготовки из Document User Text готовой копии (без открытия в Rhino — через File3dm)."""
    try:
        f = Rhino.FileIO.File3dm.Read(path)
        for i in range(f.Strings.Count):
            if f.Strings.GetKey(i) == "h3dm.prepare":
                return json.loads(f.Strings.GetValue(i))
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- подготовка

def _publish(tmp, folder, stem, num):
    """Занять свободное имя <stem>_h3dm_vNNN.3dm без гонок: жёсткая ссылка не перезаписывает существующий файл."""
    for _ in range(1000):
        out = os.path.join(folder, "%s_h3dm_v%03d.3dm" % (stem, num))
        if not os.path.exists(out):
            try:
                os.link(tmp, out)
                return out
            except FileExistsError:
                pass
            except OSError:
                # файловая система без жёстких ссылок
                if not os.path.exists(out):
                    os.replace(tmp, out)
                    return out
        num += 1
    raise IOError("no free version name for %s" % stem)


def _no_progress(stage, i=0, n=0):
    pass


def prepare(src, settings=None, log=print, progress=None):
    """progress(stage, i, n) — ход работы для Houdini (stage: hash, open, convert, blocks, mesh, write, check)."""
    progress = progress or _no_progress
    settings = dict(settings or {})
    settings.setdefault("preset", "normal")
    t0 = time.time()
    progress("hash")
    fp = fingerprint(src)
    rhino_ver = str(Rhino.RhinoApp.Version)
    key = {"source_sha1": fp["sha1"], "prep_version": PREP_VERSION, "rhino": rhino_ver, "settings": settings}
    # повтор: последняя версия с тем же ключом
    vers = versions(src)
    if vers and not settings.get("force"):
        stamp = read_stamp(vers[-1][1])
        if stamp and stamp.get("key") == key:
            return {"status": "skipped", "output": vers[-1][1], "reason": "up to date", "elapsed": time.time() - t0}

    if not is_3dm(src):
        raise IOError("Not a Rhino .3dm file: %s" % src)
    areas = bool(settings.get("face_areas"))      # площади граней — только для тестов
    progress("open")
    doc = Rhino.RhinoDoc.OpenHeadless(src)
    if doc is None:
        raise IOError("Rhino could not open %s" % src)
    stats = {"objects": 0, "breps": 0, "faces": 0, "subd_converted": 0, "subd_failed": 0, "v2_failed": 0,
             "block_objects": 0, "meshed": 0, "mesh_failed": 0, "meshes_kept": 0}
    try:
        mp = meshing_parameters(doc, settings)
        # 1) объекты модели
        objs_all = list(doc.Objects)
        for k, o in enumerate(objs_all):
            progress("convert", k, len(objs_all))
            stats["objects"] += 1
            nb, src_type = convert_geometry(o.Geometry, stats, areas)
            if nb is not None:
                doc.Objects.Replace(o.Id, nb)
        # 2) объекты в определениях блоков
        for idx in range(doc.InstanceDefinitions.Count):
            progress("blocks", idx, doc.InstanceDefinitions.Count)
            d = doc.InstanceDefinitions[idx]
            if d is None or d.IsDeleted:
                continue
            objs = d.GetObjects()
            geoms, attrs, changed = [], [], False
            for o in objs:
                nb, _ = convert_geometry(o.Geometry, stats, areas)
                geoms.append(nb if nb is not None else o.Geometry)
                attrs.append(o.Attributes)
                changed = changed or nb is not None
                stats["block_objects"] += 1
            if changed:
                doc.InstanceDefinitions.ModifyGeometry(idx, geoms, attrs)
        # 3) сетки отображения: модель + определения блоков
        targets = list(doc.Objects)
        for idx in range(doc.InstanceDefinitions.Count):
            d = doc.InstanceDefinitions[idx]
            if d is not None and not d.IsDeleted:
                targets += list(d.GetObjects())
        for k, o in enumerate(targets):
            progress("mesh", k, len(targets))
            if isinstance(o.Geometry, G.Mesh):
                stats["meshes_kept"] += 1
                continue
            if isinstance(o.Geometry, (G.Brep, G.Extrusion, G.SubD, G.Surface)):
                try:
                    n = o.CreateMeshes(G.MeshType.Render, mp, False)
                    stats["meshed" if n > 0 else "mesh_failed"] += 1
                except Exception:
                    stats["mesh_failed"] += 1
        # 4) отпечаток
        stamp = {"key": key, "source": fp, "mesh": mp_summary(mp), "stats": stats,
                 "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        doc.Strings.SetString("h3dm.prepare", json.dumps(stamp))
        # 5) атомарная запись новой версии
        num = (vers[-1][0] + 1) if vers else 1
        folder, name = os.path.split(os.path.abspath(src))
        stem = os.path.splitext(name)[0]
        tmp = os.path.join(folder, ".%s_h3dm_tmp_%s.3dm" % (stem, uuid.uuid4().hex[:8]))
        opt = Rhino.FileIO.FileWriteOptions()
        opt.FileVersion = 8
        opt.IncludeRenderMeshes = True
        opt.WriteGeometryOnly = False
        opt.SuppressAllInput = True
        progress("write")
        try:
            if not doc.Write3dmFile(tmp, opt):
                raise IOError("cannot write %s (folder read-only or disk full?)" % tmp)
            out = _publish(tmp, folder, stem, num)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    finally:
        doc.Dispose()
    # проверка копии: сетки на месте
    progress("check")
    check = Rhino.FileIO.File3dm.Read(out)
    faces = meshed = 0
    for o in check.Objects:
        g = o.Geometry
        if isinstance(g, G.Brep):
            for fi in range(g.Faces.Count):
                faces += 1
                meshed += g.Faces[fi].GetMesh(G.MeshType.Render) is not None
    stats["check_faces"], stats["check_faces_meshed"] = faces, meshed
    return {"status": "ok", "output": out, "stats": stats, "elapsed": time.time() - t0, "rhino": rhino_ver}


def _progress_writer(job_path):
    """Ход работы в <задание>.progress.json (не чаще раза в 0,5 с) — Houdini показывает его в строке состояния."""
    path = job_path + ".progress.json"
    last = [0.0, None]

    def write(stage, i=0, n=0):
        now = time.time()
        if stage == last[1] and now - last[0] < 0.5:
            return
        last[0], last[1] = now, stage
        try:
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump({"stage": stage, "i": i, "n": n, "pid": os.getpid(), "time": now}, fh)
            os.replace(tmp, path)
        except Exception:
            pass
    return write


def run_job(job_path):
    """Задание от Houdini: {"id", "source", "settings"} -> <задание>.result.json."""
    res_path = job_path + ".result.json"
    result = {"id": None, "status": "error"}
    try:
        with open(job_path) as fh:
            job = json.load(fh)
        result["id"] = job.get("id")
        result["source"] = job.get("source")
        result.update(prepare(job["source"], job.get("settings"), progress=_progress_writer(job_path)))
    except Exception:
        result["error"] = traceback.format_exc()
    tmp = res_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(result, fh)
    os.replace(tmp, res_path)
    return result


def run_manual():
    doc = Rhino.RhinoDoc.ActiveDoc
    if doc is None or not doc.Path:
        print("H3DM: save the document first.")
        return None
    res = prepare(doc.Path, {"preset": "normal"})
    print("H3DM prepare: %s -> %s" % (res["status"], res.get("output")))
    return res


if __name__ == "__main__" or "H3DM_JOB" in globals():
    _job = globals().get("H3DM_JOB")
    if _job:
        run_job(_job)
    else:
        run_manual()

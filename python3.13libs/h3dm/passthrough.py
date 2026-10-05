# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Перенос неизменённых объектов из исходного .3dm без пересборки (экспорт H3DM 0.4).

Если геометрия объекта Rhino (Brep / Extrusion) в Houdini не менялась, экспорт пишет его ИСХОДНУЮ геометрию
из файла импорта: обрезанные грани с отверстиями, объединённые тела, швы — всё точно. Атрибуты (слой, имя,
материал, User Text) берутся из Houdini — их правки сохраняются.

«Не менялась» проверяется по самой геометрии: каждая грань Brep сопоставляется с примитивами Houdini с тем же
rhino_face. NURBS-поверхность — полностью: управляющие точки, веса, узлы, порядки, замкнутость, направление
и обрезка. Обрезка сверяется подписью: rhino_trim_sig = «подпись кривых обрезки, записанных импортом в
Houdini» : «отпечаток данных обрезки исходного файла». Первая часть сравнивается с текущими кривыми обрезки
примитива (читаются из .geo), вторая — с исходным файлом сейчас (файл могли изменить после импорта).
Сетка — по вершинам каждой грани сетки отображения в том же порядке (импорт сохраняет порядок).
Допуск позиций — точность float32 позиций Houdini, пересчитанная в единицы файла.
"""
import numpy as np

from . import ensure_vendor_path

ensure_vendor_path()


def _r():
    import rhino3dm
    return rhino3dm


def _faces_of(geom):
    """Brep для сравнения и исходная геометрия для записи."""
    from .rhino_read import enum_name
    k = enum_name(geom.ObjectType)
    if k == "Brep":
        return geom
    if k == "Extrusion":
        try:
            return geom.ToBrep(True)
        except Exception:
            return None
    return None


def _mesh_faces_pos(m, scale):
    """Грани сетки отображения -> список массивов позиций вершин (в порядке Rhino)."""
    V = np.array([(p.X, p.Y, p.Z) for p in m.Vertices.ToPoint3dArray()], dtype=np.float64) * scale
    out = []
    for i in range(len(m.Faces)):
        a, b, c, d = m.Faces[i]
        idx = (a, b, c) if c == d else (a, b, c, d)
        out.append(V[list(idx)])
    return out


W_TOL = 1e-6          # веса (Pw может храниться во float32)
K_TOL = 1e-6          # узлы — доля длины узлового вектора


def _knots_equal(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return False
    if not len(a):
        return True
    a, b = a - a[0], b - b[0]
    return float(np.abs(a - b).max()) <= K_TOL * max(1.0, abs(float(a[-1])))


def surface_matches(h, face, scale, tol):
    """Примитив Houdini h = {'cv' (nv, nu, 3) в координатах файла, порядок вершин Houdini; 'w' (nv, nu);
    'ku', 'kv'; 'ou', 'ov'; 'wrap'} против исходной грани — так, как её записал импорт (зажатие, разворот U)."""
    from .rhino_read import nurbs_surface_data, houdini_reverse
    d = nurbs_surface_data(face.UnderlyingSurface(), reverse=houdini_reverse(face.OrientationIsReversed))
    if d is None:
        return False
    S = np.asarray(d["cv"], dtype=np.float64) * scale
    if S.shape != h["cv"].shape or any(h["wrap"]):
        return False
    if int(d["order_u"]) != h["ou"] or int(d["order_v"]) != h["ov"]:
        return False
    if not _knots_equal(d["knots_u"], h["ku"]) or not _knots_equal(d["knots_v"], h["kv"]):
        return False
    if float(np.abs(np.asarray(d["w"], dtype=np.float64) - h["w"]).max()) > W_TOL:
        return False
    return float(np.abs(S - h["cv"]).max()) <= tol


def trims_match(src_geom, sigs):
    """Обрезка: sigs = {номер грани: (подпись из атрибута rhino_trim_sig, подпись кривых обрезки примитива
    сейчас)}. Совпадать должны обе части: кривые в Houdini не трогали и обрезка исходника та же, что при импорте."""
    from .rhino_read import brep_trims, face_trims_hash
    brep = _faces_of(src_geom)
    if brep is None:
        return False
    tr = brep_trims(brep)
    for fi, (attr, now) in sigs.items():
        if not attr or ":" not in attr:
            return False                                   # импорт старой версии — проверить нельзя
        h_sig, src_sig = attr.split(":", 1)
        if h_sig != now:
            return False
        if src_sig != face_trims_hash(tr.get(fi) if tr else None):
            return False
    return True


def mesh_matches(prim_faces_pos, src_face_mesh, scale, tol):
    """Вершины полигонов Houdini (в порядке импорта, обход развёрнут) против граней сетки отображения."""
    if src_face_mesh is None:
        return False
    src = _mesh_faces_pos(src_face_mesh, scale)
    if len(src) != len(prim_faces_pos):
        return False
    for a, b in zip(src, prim_faces_pos):
        if a.shape != b.shape or float(np.abs(a - b).max()) > tol:
            return False
    return True


def object_unchanged(src_geom, faces, scale, tol):
    """faces: {номер грани: ('nurbs', данные примитива для surface_matches) | ('mesh', [позиции вершин
    граней]) | ('other', None)}. Обрезку NURBS-граней проверяет trims_match."""
    brep = _faces_of(src_geom)
    if brep is None:
        return False
    n = len(brep.Faces)
    from .rhino_read import enum_name
    if enum_name(src_geom.ObjectType) == "Extrusion" and set(faces) == {-1}:
        # сетка экструзии целиком (импорт сетками: одна сетка без номера грани)
        kind, data = faces[-1]
        m = src_geom.GetMesh(_r().MeshType.Any)
        return kind == "mesh" and mesh_matches(data, m, scale, tol)
    if set(faces) != set(range(n)):
        return False
    for fi in range(n):
        kind, data = faces[fi]
        face = brep.Faces[fi]
        if kind == "nurbs":
            if not surface_matches(data, face, scale, tol):
                return False
        elif kind == "mesh":
            if not mesh_matches(data, face.GetMesh(_r().MeshType.Any), scale, tol):
                return False
        else:
            return False
    return True


def source_geometry(src_geom, scale):
    """Копия исходной геометрии для записи: единицы файла, без служебных строк H3DM."""
    g = src_geom.Duplicate()
    if abs(scale - 1.0) > 1e-15:
        g.Scale(scale)
    try:
        keys = [str(kv[0]) for kv in (g.GetUserStrings() or ())]
    except Exception:
        keys = ["h3dm.trims", "h3dm.source_type", "h3dm.key"]
    for key in keys:
        if key.startswith("h3dm."):
            try:
                g.SetUserString(key, "")       # пустое значение удаляет ключ
            except Exception:
                pass
    return g

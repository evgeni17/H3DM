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
K_TOL = 1e-7          # узлы — доля длины узлового вектора (нормированные; Houdini может хранить float32)


def _knots_equal(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return False
    if not len(a):
        return True
    a, b = a - a[0], b - b[0]
    ra, rb = float(a[-1]), float(b[-1])
    if ra <= 0 or rb <= 0:
        return ra == rb
    # импорт масштабирует параметр (houjson.safe_knots), поэтому сравниваются нормированные узлы
    return float(np.abs(a / ra - b / rb).max()) <= K_TOL


def _surface_pair(h, face, scale):
    """Примитив Houdini h = {'cv' (nv, nu, 3) в координатах файла, порядок вершин Houdini; 'w' (nv, nu);
    'ku', 'kv'; 'ou', 'ov'; 'wrap'} и исходная грань (как её записал импорт: зажатие, разворот U).
    Строение (размеры, порядки, узлы, веса) должно совпадать -> (точки исходника * scale, точки Houdini) или None."""
    from .rhino_read import nurbs_surface_data, houdini_reverse
    d = nurbs_surface_data(face.UnderlyingSurface(), reverse=houdini_reverse(face.OrientationIsReversed))
    if d is None:
        return None
    S = np.asarray(d["cv"], dtype=np.float64) * scale
    if S.shape != h["cv"].shape or any(h["wrap"]):
        return None
    if int(d["order_u"]) != h["ou"] or int(d["order_v"]) != h["ov"]:
        return None
    if not _knots_equal(d["knots_u"], h["ku"]) or not _knots_equal(d["knots_v"], h["kv"]):
        return None
    if float(np.abs(np.asarray(d["w"], dtype=np.float64) - h["w"]).max()) > W_TOL:
        return None
    return S.reshape(-1, 3), np.asarray(h["cv"], dtype=np.float64).reshape(-1, 3)


def surface_matches(h, face, scale, tol):
    pair = _surface_pair(h, face, scale)
    return pair is not None and float(np.abs(pair[0] - pair[1]).max()) <= tol


def trims_match(src_geom, sigs, check_source=True):
    """Обрезка: sigs = {номер грани: (подпись из атрибута rhino_trim_sig, подпись кривых обрезки примитива
    сейчас)}. Совпадать должны обе части: кривые в Houdini не трогали и обрезка исходника та же, что при импорте."""
    from .rhino_read import brep_trims, face_trims_hash
    brep = _faces_of(src_geom)
    if brep is None:
        return False
    # исходный файл тот же, что при импорте (отпечаток содержимого) — его обрезку не пересчитываем
    tr = brep_trims(brep) if check_source else None
    for fi, (attr, now) in sigs.items():
        if not attr or ":" not in attr:
            return False                                   # импорт старой версии — проверить нельзя
        h_sig, src_sig = attr.split(":", 1)
        if h_sig != now:
            return False
        if check_source and src_sig != face_trims_hash(tr.get(fi) if tr else None):
            return False
    return True


def _mesh_pair(prim_faces_pos, src_face_mesh, scale):
    """Вершины полигонов Houdini (в порядке импорта, обход развёрнут) и грани сетки отображения ->
    (точки исходника, точки Houdini) или None, если строение разное."""
    if src_face_mesh is None:
        return None
    src = _mesh_faces_pos(src_face_mesh, scale)
    if len(src) != len(prim_faces_pos):
        return None
    if any(a.shape != b.shape for a, b in zip(src, prim_faces_pos)):
        return None
    if not src:
        return np.zeros((0, 3)), np.zeros((0, 3))
    return np.concatenate(src), np.concatenate([np.asarray(b, dtype=np.float64) for b in prim_faces_pos])


def mesh_matches(prim_faces_pos, src_face_mesh, scale, tol):
    pair = _mesh_pair(prim_faces_pos, src_face_mesh, scale)
    return pair is not None and (not len(pair[0]) or float(np.abs(pair[0] - pair[1]).max()) <= tol)


def _object_pairs(src_geom, faces, scale):
    """Все пары точек (исходник * scale, Houdini) объекта или None, если строение граней не совпадает."""
    from .rhino_read import enum_name
    brep = _faces_of(src_geom)
    if brep is None:
        return None
    if enum_name(src_geom.ObjectType) == "Extrusion" and set(faces) == {-1}:
        # сетка экструзии целиком (импорт сетками: одна сетка без номера грани)
        kind, data = faces[-1]
        return _mesh_pair(data, src_geom.GetMesh(_r().MeshType.Any), scale) if kind == "mesh" else None
    n = len(brep.Faces)
    if set(faces) != set(range(n)):
        return None
    A, B = [], []
    for fi in range(n):
        kind, data = faces[fi]
        face = brep.Faces[fi]
        if kind == "nurbs":
            pair = _surface_pair(data, face, scale)
        elif kind == "mesh":
            pair = _mesh_pair(data, face.GetMesh(_r().MeshType.Any), scale)
        else:
            pair = None
        if pair is None:
            return None
        A.append(pair[0])
        B.append(pair[1])
    return np.concatenate(A), np.concatenate(B)


def fit_affine(A, B):
    """Аффинное преобразование X -> M[:3,:3] X + M[:3,3], переводящее точки A в B (наименьшие квадраты, double).
    -> (4x4, наибольшее отклонение) или None, если точки вырождены (лежат в плоскости)."""
    if len(A) < 4:
        return None
    c = A.mean(axis=0)
    X = np.column_stack([A - c, np.ones(len(A))])
    if np.linalg.matrix_rank(X[:, :3], tol=1e-9 * max(1.0, float(np.abs(A - c).max()))) < 3:
        return None
    sol, *_ = np.linalg.lstsq(X, B, rcond=None)          # (4, 3): строки — оси и сдвиг для A - c
    L = sol[:3].T
    # шум float32 позиций Houdini даёт ложный малый масштаб/сдвиг осей: близкое к повороту (или повороту с
    # равномерным масштабом) приводится к нему точно
    U, sv, Vt = np.linalg.svd(L)
    R = U @ Vt
    k = float(sv.mean())
    if float(np.abs(sv - 1.0).max()) < 1e-5:
        L = R
    elif float(sv.max() - sv.min()) < 1e-5 * k:
        L = R * k
    t = B.mean(axis=0) - L @ c
    M = np.eye(4)
    M[:3, :3] = L
    M[:3, 3] = t
    err = float(np.abs(A @ L.T + t - B).max())
    return M, err


def object_match(src_geom, faces, scale, tol):
    """-> 'same' (геометрия совпадает), матрица 4x4 (тот же объект, перенесённый/повёрнутый/масштабированный
    в Houdini — точно с точностью float) или None. Обрезку NURBS-граней проверяет trims_match."""
    pairs = _object_pairs(src_geom, faces, scale)
    if pairs is None:
        return None
    A, B = pairs
    if not len(A):
        return None
    if float(np.abs(A - B).max()) <= tol:
        return "same"
    fit = fit_affine(A, B)
    if fit is None:
        return None
    M, err = fit
    if err > tol or abs(np.linalg.det(M[:3, :3])) < 1e-12:
        return None
    return M


def object_unchanged(src_geom, faces, scale, tol):
    m = object_match(src_geom, faces, scale, tol)
    return isinstance(m, str) and m == "same"


def source_geometry(src_geom, scale, xform=None):
    """Копия исходной геометрии для записи: единицы файла, преобразование из Houdini (4x4, double), без
    служебных строк H3DM."""
    g = src_geom.Duplicate()
    if abs(scale - 1.0) > 1e-15:
        g.Scale(scale)
    if xform is not None:
        xf = _r().Transform(1.0)
        M = np.asarray(xform, dtype=np.float64)
        for i in range(4):
            for j in range(4):
                setattr(xf, "M%d%d" % (i, j), float(M[i, j]))
        g.Transform(xf)
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

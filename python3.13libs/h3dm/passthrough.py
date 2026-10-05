# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Перенос неизменённых объектов из исходного .3dm без пересборки (экспорт H3DM 0.4).

Если геометрия объекта Rhino (Brep / Extrusion) в Houdini не менялась, экспорт пишет его ИСХОДНУЮ геометрию
из файла импорта: обрезанные грани с отверстиями, объединённые тела, швы — всё точно. Атрибуты (слой, имя,
материал, User Text) берутся из Houdini — их правки сохраняются.

«Не менялась» проверяется по самой геометрии, без отпечатков при импорте: каждая грань Brep сопоставляется
с примитивами Houdini с тем же rhino_face — NURBS-поверхность по управляющим точкам, сетка — по вершинам
каждой грани сетки отображения в том же порядке (импорт сохраняет порядок). Допуск — точность float32
позиций Houdini, пересчитанная в единицы файла.
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


def surface_matches(prim_cv, src_surface, scale, tol):
    """CV примитива (nv, nu, 3, уже в координатах файла, U развёрнут как при экспорте) против поверхности
    исходной грани (с зажатием как при импорте); U может быть развёрнут (грани OrientationIsReversed)."""
    from .rhino_read import nurbs_surface_data
    d = nurbs_surface_data(src_surface, reverse=False)
    if d is None:
        return False
    S = np.asarray(d["cv"], dtype=np.float64) * scale
    if S.shape != prim_cv.shape:
        return False
    return min(float(np.abs(S - prim_cv).max()), float(np.abs(S[:, ::-1] - prim_cv).max())) <= tol


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
    """faces: {номер грани: ('nurbs', cv) | ('mesh', [позиции вершин граней]) | ('other', None)}."""
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
            if not surface_matches(data, face.UnderlyingSurface(), scale, tol):
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
    for key in ("h3dm.trims", "h3dm.source_type"):
        try:
            if g.GetUserString(key):
                g.SetUserString(key, "")       # пустое значение удаляет ключ
        except Exception:
            pass
    return g

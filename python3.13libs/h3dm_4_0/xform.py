# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Глобальный трансформ Rhino <-> Houdini. Без hou, только numpy (тестируется обычным Python).

Rhino хранит координаты в double (float64), Houdini — позиции P во float32 (~7 значащих цифр).
Модель в сотнях километров от нуля во float32 теряет миллиметры и сантиметры, поэтому:

    P_houdini = C * s * (P_rhino - origin)          — считается ЦЕЛИКОМ в float64,
                                                      во float32 переводится только результат (уже у нуля)
    P_rhino   = origin + C^-1 * P_houdini / s       — обратно, тоже в float64

origin — точка в единицах модели Rhino (double), s = метров_в_единице * единиц_сцены_на_метр,
C — смена осей Z-up -> Y-up: (x, y, z) -> (x, z, -y).

Точные значения (double) хранятся в словаре h3dm_xform (dict-атрибуты Houdini держат float64).
4@global_xform — та же матрица во float32: удобна для Transform By Attribute, но для далёких моделей неточна.
"""
import math

import numpy as np

C_YUP = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
VERSION = 1


class GlobalXform(object):
    def __init__(self, origin=(0.0, 0.0, 0.0), unit_m=1.0, scale=1.0, yup=True, source="none", units=""):
        self.origin = np.asarray(origin, dtype=np.float64).reshape(3)
        self.unit_m = float(unit_m)     # метров в единице модели Rhino
        self.scale = float(scale)       # единиц сцены Houdini на метр
        self.yup = bool(yup)
        self.source = source
        self.units = units

    # ---------- основное ----------
    @property
    def s(self):
        return self.unit_m * self.scale

    @property
    def C(self):
        return C_YUP if self.yup else np.eye(3)

    def to_houdini(self, pts):
        """Точки Rhino (N,3 float64) -> Houdini (N,3 float64; приводить к float32 только после)."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        return np.einsum("ij,nj->ni", self.C, (p - self.origin) * self.s)

    def to_rhino(self, pts):
        """Точки Houdini (N,3) -> Rhino (N,3 float64)."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        return np.einsum("ji,nj->ni", self.C, p) / self.s + self.origin

    def vectors_to_houdini(self, v):
        """Направления (без сдвига и масштаба): нормали, оси плоскостей."""
        return np.einsum("ij,nj->ni", self.C, np.asarray(v, dtype=np.float64).reshape(-1, 3))

    def placement(self, m4):
        """Матрица Rhino 4x4 (столбцовые векторы, в мировых координатах модели) -> (A 3x3, b 3)
        для packed-примитива: локальная геометрия в осях/единицах сцены (C*s*p_local),
        её размещение: A * p + b. Перенос считается в double до вычитания origin."""
        m = np.asarray(m4, dtype=np.float64).reshape(4, 4)
        C = self.C
        A = C @ m[:3, :3] @ C.T
        b = self.s * (C @ (m[:3, 3] - self.origin))
        return A, b

    def local_to_houdini(self, pts):
        """Точки в локальной системе блока (без origin) -> оси/единицы сцены."""
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        return np.einsum("ij,nj->ni", self.C, p * self.s)

    # ---------- матрицы ----------
    def matrix_rhino_to_houdini(self):
        """4x4 (столбцовые векторы): P_h = M * [P_r, 1]."""
        M = np.eye(4)
        M[:3, :3] = self.C * self.s
        M[:3, 3] = -self.s * (self.C @ self.origin)
        return M

    def global_xform_houdini(self):
        """4@global_xform в соглашении Houdini (вектор-строка): переводит локальные P обратно
        в «мировые» координаты Houdini (без сдвига): P_world_h = P_h * M. 16 чисел по строкам."""
        M = np.eye(4)
        M[3, :3] = self.s * (self.C @ self.origin)
        return [float(x) for x in M.reshape(16)]

    # ---------- сериализация ----------
    def as_dict(self):
        return {
            "version": VERSION, "origin": [float(x) for x in self.origin], "units": self.units,
            "unit_m": self.unit_m, "scale": self.scale, "yup": int(self.yup), "source": self.source,
            "origin_text": "%.9f %.9f %.9f" % tuple(self.origin),
            "matrix_rhino_to_houdini": [float(x) for x in self.matrix_rhino_to_houdini().reshape(16)],
        }

    @classmethod
    def from_dict(cls, d):
        if not d:
            return None
        origin = d.get("origin")
        txt = d.get("origin_text")
        if txt:   # строка — самый надёжный носитель double
            try:
                origin = [float(x) for x in txt.split()]
            except Exception:
                pass
        return cls(origin or (0, 0, 0), d.get("unit_m", 1.0), d.get("scale", 1.0), bool(d.get("yup", 1)),
                   d.get("source", "input"), d.get("units", ""))

    def __repr__(self):
        return "GlobalXform(origin=%s, s=%g, yup=%s, source=%s)" % (list(self.origin), self.s, self.yup, self.source)


def round_origin(p, step):
    """Округлить точку к сетке step (в единицах модели), чтобы сдвиг был «круглым»."""
    p = np.asarray(p, dtype=np.float64)
    if step and step > 0:
        return np.round(p / step) * step
    return p


def choose_origin(mode, bbox, unit_m, round_m=1.0, far_m=1000.0, base_point=None, manual=None):
    """Точка origin (единицы модели) и её источник.

    mode: none | auto_far | auto | basepoint | manual
    bbox: (min[3], max[3]) в единицах модели или None.
    auto — центр по X/Y, низ по Z габарита, округлённый до round_m метров.
    auto_far — то же, но только если габарит дальше far_m метров от нуля.
    """
    zero = np.zeros(3)
    if mode == "manual" and manual is not None:
        return np.asarray(manual, dtype=np.float64), "manual"
    if mode == "basepoint" and base_point is not None:
        return np.asarray(base_point, dtype=np.float64), "basepoint"
    if mode in ("auto", "auto_far") and bbox is not None:
        mn, mx = np.asarray(bbox[0], dtype=np.float64), np.asarray(bbox[1], dtype=np.float64)
        c = np.array([(mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, mn[2]])
        if mode == "auto_far":
            far = max(np.abs(mn).max(), np.abs(mx).max()) * unit_m
            if far < far_m:
                return zero, "none"
        step = round_m / unit_m if unit_m > 0 else 0.0
        return round_origin(c, step), mode
    return zero, "none"


def float32_error(pts_rhino, gx):
    """Максимальная ошибка (в метрах) при записи точек во float32 после трансформа gx и обратно."""
    h = gx.to_houdini(pts_rhino).astype(np.float32).astype(np.float64)
    back = gx.to_rhino(h)
    return float(np.abs(back - np.asarray(pts_rhino, dtype=np.float64)).max() * gx.unit_m) if len(back) else 0.0


def ulp_m(coord_units, unit_m, scale=1.0):
    """Шаг float32 (в метрах) для координаты такой величины."""
    v = abs(coord_units) * unit_m * scale
    return float(np.spacing(np.float32(v))) / scale if v else 0.0

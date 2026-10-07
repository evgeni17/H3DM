# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""NURBS на numpy: зажатие периодических (незажатых) NURBS и вычисление точек. Без hou.

Rhino хранит периодические кривые и поверхности с незажатым узловым вектором. Houdini такой вектор
в .geo трактует иначе (кривая «открывается» и меняет форму), поэтому перед записью мы превращаем
их в ЭКВИВАЛЕНТНЫЕ зажатые NURBS вставкой узлов (алгоритм Бёма): форма на всей области определения
остаётся той же, первый и последний CV совпадают с концами.

Обозначения: p — степень, U — полный узловой вектор (длина n+p+1, как в Houdini), Pw — однородные
контрольные точки (x*w, y*w, z*w, w) по оси 0 (дальние оси — например, ряды поверхности).
"""
import numpy as np


def _insert(Pw, U, p, u):
    """Вставка узла u один раз. Pw: (n, ..., 4)."""
    U = np.asarray(U, dtype=np.float64)
    n = Pw.shape[0]
    k = int(np.searchsorted(U, u, side="right") - 1)        # U[k] <= u < U[k+1]
    k = min(max(k, p), n - 1)
    Q = np.empty((n + 1,) + Pw.shape[1:], dtype=np.float64)
    Q[:k - p + 1] = Pw[:k - p + 1]
    for i in range(k - p + 1, k + 1):
        den = U[i + p] - U[i]
        a = (u - U[i]) / den if den != 0 else 0.0
        Q[i] = a * Pw[i] + (1.0 - a) * Pw[i - 1]
    Q[k + 1:] = Pw[k:]
    return Q, np.concatenate([U[:k + 1], [u], U[k + 1:]])


def is_clamped(U, p):
    U = np.asarray(U, dtype=np.float64)
    a, b = U[p], U[len(U) - p - 1]
    return np.count_nonzero(U[:p + 1] == a) >= p + 1 or (np.count_nonzero(U == a) >= p and
                                                          np.count_nonzero(U == b) >= p and
                                                          U[0] == a and U[-1] == b)


def clamp(Pw, U, p):
    """Незажатый NURBS -> эквивалентный зажатый на области [U[p], U[n]]. -> (Pw', U')."""
    Pw = np.asarray(Pw, dtype=np.float64)
    U = np.asarray(U, dtype=np.float64)
    a, b = U[p], U[len(U) - p - 1]
    # довести кратность концов области до p
    while np.count_nonzero(np.isclose(U, a, rtol=0, atol=1e-12)) < p:
        Pw, U = _insert(Pw, U, p, a)
    while np.count_nonzero(np.isclose(U, b, rtol=0, atol=1e-12)) < p:
        Pw, U = _insert(Pw, U, p, b)
    L = int(np.nonzero(np.isclose(U, a, rtol=0, atol=1e-12))[0][-1])   # последний узел = a
    F = int(np.nonzero(np.isclose(U, b, rtol=0, atol=1e-12))[0][0])    # первый узел = b
    P2 = Pw[L - p:F]
    U2 = np.concatenate([[a] * (p + 1), U[L + 1:F], [b] * (p + 1)])
    return P2, U2


def needs_clamp(U, p):
    """True, если концы области не зажаты (кратность < p+1 с учётом крайних узлов)."""
    U = np.asarray(U, dtype=np.float64)
    a, b = U[p], U[len(U) - p - 1]
    return not (np.all(U[:p + 1] == a) and np.all(U[len(U) - p - 1:] == b))


def clamp_curve(cv, w, U, order):
    """Кривая: cv (n,3), w (n,), U полный -> зажатые (cv, w, U)."""
    p = order - 1
    if not needs_clamp(U, p):
        return cv, w, list(U)
    Pw = np.column_stack([cv * w[:, None], w])
    Q, U2 = clamp(Pw, U, p)
    return Q[:, :3] / Q[:, 3:4], Q[:, 3].copy(), list(U2)


def clamp_surface(cv, w, Uu, Uv, order_u, order_v):
    """Поверхность: cv (nv, nu, 3), w (nv, nu) -> зажатые по U и V."""
    pu, pv = order_u - 1, order_v - 1
    Pw = np.concatenate([cv * w[..., None], w[..., None]], axis=-1)       # (nv, nu, 4)
    if needs_clamp(Uu, pu):
        Q, Uu = clamp(np.swapaxes(Pw, 0, 1), Uu, pu)                       # ось 0 = U
        Pw = np.swapaxes(Q, 0, 1)
    if needs_clamp(Uv, pv):
        Pw, Uv = clamp(Pw, Uv, pv)                                         # ось 0 = V
    return Pw[..., :3] / Pw[..., 3:4], Pw[..., 3].copy(), list(Uu), list(Uv)


# ---------- вычисление (для тестов и собственной тесселяции) ----------

def _basis(U, p, t):
    """Ненулевые базисные функции в t: (span k, N[0..p])."""
    U = np.asarray(U, dtype=np.float64)
    n = len(U) - p - 1
    if t >= U[n]:
        k = n - 1
    else:
        k = int(np.searchsorted(U, t, side="right") - 1)
    k = min(max(k, p), n - 1)
    N = np.zeros(p + 1)
    N[0] = 1.0
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    for j in range(1, p + 1):
        left[j] = t - U[k + 1 - j]
        right[j] = U[k + j] - t
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            tmp = N[r] / den if den != 0 else 0.0
            N[r] = saved + right[r + 1] * tmp
            saved = left[j - r] * tmp
        N[j] = saved
    return k, N


def eval_curve(cv, w, U, order, t):
    p = order - 1
    k, N = _basis(U, p, t)
    Pw = np.column_stack([cv * w[:, None], w])[k - p:k + 1]
    h = N @ Pw
    return h[:3] / h[3]


def eval_surface(cv, w, Uu, Uv, order_u, order_v, u, v):
    pu, pv = order_u - 1, order_v - 1
    ku, Nu = _basis(Uu, pu, u)
    kv, Nv = _basis(Uv, pv, v)
    Pw = np.concatenate([cv * w[..., None], w[..., None]], axis=-1)[kv - pv:kv + 1, ku - pu:ku + 1]
    h = np.einsum("i,j,ijk->k", Nv, Nu, Pw)
    return h[:3] / h[3]

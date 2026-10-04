# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тесты глобального трансформа (обычный Python + numpy): python tests/test_xform.py"""
import importlib.util
import os
import sys

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("xform", os.path.join(here, "..", "python3.13libs", "h3dm", "xform.py"))
X = importlib.util.module_from_spec(spec)
spec.loader.exec_module(X)

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


# модель в 350 км от нуля, единицы — миллиметры: детали 1 мм
rng = np.random.default_rng(1)
far = np.array([350_000_000.0, 8_200_000_000.0, 120_000.0])          # мм
pts = far + rng.uniform(-50_000, 50_000, size=(1000, 3)) + np.array([0.0, 0.0, 0.25])
bbox = (pts.min(0), pts.max(0))

# без сдвига float32 теряет сотни миллиметров
g0 = X.GlobalXform((0, 0, 0), unit_m=0.001, scale=1.0, yup=True)
e0 = X.float32_error(pts, g0)
check(e0 > 0.1, "без сдвига ошибка должна быть большой, а она %g м" % e0)

# авто-сдвиг: ошибка — микроны
o, src = X.choose_origin("auto_far", bbox, unit_m=0.001, round_m=1.0, far_m=1000.0)
g = X.GlobalXform(o, unit_m=0.001, scale=1.0, yup=True, source=src)
e = X.float32_error(pts, g)
check(src == "auto_far", "источник origin: %s" % src)
check(e < 1e-5, "ошибка после сдвига %g м (ожидалось < 10 мкм)" % e)
check(np.allclose(o % 1000.0, 0.0), "origin округлён до 1 м: %s" % o)

# обратимость в double
h = g.to_houdini(pts)
check(np.abs(g.to_rhino(h) - pts).max() < 1e-6, "to_rhino(to_houdini(p)) != p")

# оси: Z Rhino -> Y Houdini
up = g.to_houdini(o + np.array([0.0, 0.0, 1000.0]))[0]
check(np.allclose(up, [0.0, 1.0, 0.0]), "Z-up -> Y-up: %s" % up)

# сериализация через dict сохраняет double без потерь
g2 = X.GlobalXform.from_dict(g.as_dict())
check(np.array_equal(g2.origin, g.origin) and g2.s == g.s and g2.yup == g.yup, "as_dict/from_dict")

# рядом с нулём auto_far ничего не сдвигает
o3, s3 = X.choose_origin("auto_far", (np.array([0.0, 0, 0]), np.array([5000.0, 5000, 3000])), 0.001)
check(s3 == "none" and not o3.any(), "auto_far у нуля")

# размещение блока: перенос в double
m4 = np.eye(4)
m4[:3, 3] = far + np.array([1.0, 2.0, 3.0])
A, b = g.placement(m4)
expect = g.to_houdini(far + np.array([1.0, 2.0, 3.0]))[0]
check(np.allclose(b, expect, atol=1e-9), "placement: перенос %s vs %s" % (b, expect))

if FAIL:
    print("FAILED (%d):" % len(FAIL))
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("test_xform: OK  (float32 error without shift %.3f m, with auto shift %.2e m)" % (e0, e))

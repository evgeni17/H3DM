# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Геометрия Houdini в формате JSON (.geo) для NURBS-кривых и поверхностей (в том числе обрезанных). Без hou.

HOM не позволяет задать узлы (knots) NURBS и кривые обрезки, а формат .geo — позволяет: строим JSON и
загружаем его через hou.Geometry.loadFromFile. Позиции — уже в осях/единицах сцены, веса — атрибут Pw.

Особенности Houdini, учтённые здесь (проверено на Houdini 22.0.429):
  * узловой вектор, начинающийся с отрицательного числа, ломает вычисление на краю (бесконечность,
    Convert не работает) — все узлы сдвигаются так, чтобы начинались с 0; кривые обрезки — на тот же сдвиг;
  * обрезка: у NURBMesh вложенная геометрия "profiles" — кривые в координатах узлового домена поверхности
    (точки (u, v, 1), тип hpoint) и "trimregions" — замкнутые области из нескольких кривых;
    внешняя петля против часовой стрелки, отверстия по часовой (как в Rhino); altitude 0;
  * веса кривых обрезки Houdini не учитывает — рациональные кривые обрезки приходят сюда уже ломаными.

Запись — двоичный JSON Houdini (.bgeo): числа массивами (uniform array) без текстового преобразования.
На 5 млн управляющих точек: ~1 с вместо ~60 с у текстового .geo (json + разбор в Houdini).
Формат (как пишет сам Houdini 22): магия 0x7f "NSJb"; [ ] { } — 0x5b 0x5d 0x7b 0x7d; строка 0x27+длина+UTF-8;
целые 0x11/0x12/0x13/0x14 (8/16/32/64 бит), вещественное 0x1a (64 бит), true/false 0x31/0x30;
однородный массив 0x40 + тип + длина + данные; длина: 1 байт (< 0xf0), 0xf2+uint16, 0xf4+uint32, 0xf8+uint64.
"""
import json
import struct

import numpy as np

# ---------------------------------------------------------------- двоичный JSON Houdini

_MAGIC = b"\x7fNSJb"


def _len(n):
    if n < 0xF0:
        return bytes((n,))
    if n < 0x10000:
        return b"\xf2" + struct.pack("<H", n)
    if n < 0x100000000:
        return b"\xf4" + struct.pack("<I", n)
    return b"\xf8" + struct.pack("<Q", n)


def _enc(o, out):
    if isinstance(o, np.ndarray):
        a = o.reshape(-1)
        if a.dtype.kind == "f":
            a = np.ascontiguousarray(a, dtype="<f8")
            out.append(b"\x40\x1a" + _len(len(a)))
        else:
            a = np.ascontiguousarray(a, dtype="<i4")
            out.append(b"\x40\x13" + _len(len(a)))
        out.append(a.tobytes())
    elif isinstance(o, bool) or isinstance(o, np.bool_):
        out.append(b"\x31" if o else b"\x30")
    elif isinstance(o, (int, np.integer)):
        o = int(o)
        if -128 <= o < 128:
            out.append(b"\x11" + struct.pack("<b", o))
        elif -32768 <= o < 32768:
            out.append(b"\x12" + struct.pack("<h", o))
        elif -2147483648 <= o < 2147483648:
            out.append(b"\x13" + struct.pack("<i", o))
        else:
            out.append(b"\x14" + struct.pack("<q", o))
    elif isinstance(o, (float, np.floating)):
        out.append(b"\x1a" + struct.pack("<d", float(o)))
    elif isinstance(o, str):
        b = o.encode("utf-8")
        out.append(b"\x27" + _len(len(b)) + b)
    elif isinstance(o, dict):
        out.append(b"\x7b")
        for k, v in o.items():
            _enc(str(k), out)
            _enc(v, out)
        out.append(b"\x7d")
    elif isinstance(o, (list, tuple)):
        out.append(b"\x5b")
        for v in o:
            _enc(v, out)
        out.append(b"\x5d")
    elif o is None:
        out.append(b"\x00")
    else:
        raise TypeError("houjson: cannot encode %r" % type(o))


def binary(doc):
    out = [_MAGIC]
    _enc(doc, out)
    return b"".join(out)


def _ascii_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o))


# ---------------------------------------------------------------- документ геометрии

def _values(arr, size):
    """Значения атрибута точек: плоский массив float64 (страницы по 1024 точки, компоненты подряд)."""
    return ["size", size, "storage", "fpreal64", "pagesize", 1024, "rawpagedata",
            np.ascontiguousarray(arr, dtype=np.float64).reshape(-1)]


def _points_doc(P, prims, W=None, ptype=None, extra=None):
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    n = len(P)
    popt = {"type": {"type": "string", "value": ptype}} if ptype else {}
    attrs = [[["scope", "public", "type", "numeric", "name", "P", "options", popt],
              ["size", 3, "storage", "fpreal64", "values", _values(P, 3)]]]
    if W is not None:
        attrs.append([["scope", "public", "type", "numeric", "name", "Pw", "options", {}],
                      ["size", 1, "storage", "fpreal64", "values", _values(W, 1)]])
    doc = ["fileversion", "22.0", "hasindex", False,
           "pointcount", n, "vertexcount", n, "primitivecount", len(prims),
           "topology", ["pointref", ["indices", np.arange(n, dtype=np.int32)]],
           "attributes", ["pointattributes", attrs],
           "primitives", prims]
    return doc + (extra or [])


MIN_SPAN = 1e-3   # Houdini отбрасывает узловой вектор с интервалом < ~1e-5 (абсолютно) и ставит [0..0 1..1]


def knot_scale(knots):
    """Множитель параметра, при котором наименьший ненулевой интервал узлов >= MIN_SPAN. Линейная
    перепараметризация не меняет форму кривой/поверхности; обрезка масштабируется тем же множителем."""
    k = np.asarray(knots, dtype=np.float64).reshape(-1)
    if len(k) < 2:
        return 1.0
    d = np.diff(k)
    d = d[d > 0]
    if not len(d):
        return 1.0
    m = float(d.min())
    return 1.0 if m >= MIN_SPAN else MIN_SPAN / m


def safe_knots(knots):
    """Узлы от 0, масштабированные для Houdini. -> (узлы, множитель)."""
    k = np.asarray(knots, dtype=np.float64).reshape(-1)
    k = k - k[0]
    f = knot_scale(k)
    return (k * f if f != 1.0 else k), f


def _curve_prim(start, n, order, knots):
    knots = np.asarray(knots, dtype=np.float64)
    clamped = len(knots) >= 2 and knots[0] == knots[1]
    return [["type", "NURBCurve"], [
        "vertex", np.arange(start, start + n, dtype=np.int32), "closed", False,
        "basis", ["type", "NURBS", "order", int(order), "endinterpolation", bool(clamped), "knots", knots]]]


def _profile_regions(loops, su, sv, fu=1.0, fv=1.0):
    """Петли кривых обрезки (UV в домене поверхности) -> области в том виде, как они пишутся в profiles:
    [[(порядок, узлы от 0, точки (n, 3) = ((u - su) * fu, (v - sv) * fv, 1), u0, u1), ...], ...] — одна область на
    петлю; fu, fv — множители параметра поверхности (knot_scale), узлы кривых — тоже безопасные для Houdini."""
    regions = []
    for loop in loops or ():
        faces = []
        for c in loop:
            uv = np.asarray(c["cv"], dtype=np.float64).reshape(-1, 2)
            P = np.column_stack([(uv[:, 0] - su) * fu, (uv[:, 1] - sv) * fv, np.ones(len(uv))])
            kn, _ = safe_knots(c["knots"])
            faces.append((int(c["order"]), kn, P, float(kn[0]), float(kn[-1])))
        if faces:
            regions.append(faces)
    return regions


def _profiles(loops, su, sv, fu=1.0, fv=1.0):
    """Петли кривых обрезки (UV в домене поверхности) -> вложенная геометрия profiles."""
    P, prims, regions, n = [], [], [], 0
    for region in _profile_regions(loops, su, sv, fu, fv):
        faces = []
        for order, kn, pts, u0, u1 in region:
            P.append(pts)
            prims.append(_curve_prim(n, len(pts), order, kn))
            n += len(pts)
            faces.append(["face", len(prims) - 1, "u0", u0, "u1", u1])
        regions.append(["opencasual", False, "faces", faces])
    P = np.concatenate(P) if P else np.zeros((0, 3))
    return _points_doc(P, prims, ptype="hpoint", extra=["altitude", 0, "trimregions", regions])


# ---------------------------------------------------------------- подпись обрезки (экспорт: менялась ли обрезка)

def _signature(regions):
    """Подпись областей обрезки. Числа — в float32: Houdini может хранить или печатать их с потерей
    последнего бита double, а изменение обрезки в пределах float32 геометрически ничтожно."""
    import hashlib
    h = hashlib.sha1()
    h.update(b"H3DM-trims-1")
    for faces in regions:
        h.update(b"R" + np.int32(len(faces)).tobytes())
        for order, kn, P, u0, u1 in faces:
            kn = np.asarray(kn, dtype=np.float64).reshape(-1)
            P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
            h.update(np.int32([order, len(kn), len(P)]).tobytes())
            h.update(kn.astype(np.float32).tobytes())
            h.update(P.astype(np.float32).tobytes())
            h.update(np.float32([u0, u1]).tobytes())
    return h.hexdigest()[:20]


def profiles_signature(loops, su, sv, fu=1.0, fv=1.0):
    """Подпись обрезки, которую импорт записывает в profiles (loops = None — без обрезки)."""
    return _signature(_profile_regions(loops, su, sv, fu, fv))


def _kv(lst):
    """Список JSON Houdini [ключ, значение, ключ, значение, ...] -> dict."""
    if isinstance(lst, dict):
        return lst
    return {lst[i]: lst[i + 1] for i in range(0, len(lst) - 1, 2)}


def _iter_prims(prims):
    """Примитивы .geo -> (тип, поля). Houdini пишет одинаковые примитивы «прогоном» (run): заголовок
    {type: run, runtype, varyingfields, uniformfields}, тело — список значений varyingfields на примитив."""
    for pr in prims or ():
        head = _kv(pr[0])
        if head.get("type") == "run":
            names = list(head.get("varyingfields", []))
            uni = _kv(head.get("uniformfields", {}))
            for vals in pr[1]:
                f = dict(uni)
                f.update(zip(names, vals))
                yield head.get("runtype"), f
        else:
            yield head.get("type"), _kv(pr[1])


def _attr_values(vals, size):
    """Значения атрибута точек из .geo (tuples / arrays / rawpagedata) -> массив (n, size)."""
    v = _kv(vals)
    if "tuples" in v:
        return np.asarray(v["tuples"], dtype=np.float64).reshape(-1, size)
    if "arrays" in v:
        return np.asarray(v["arrays"], dtype=np.float64).reshape(size, -1).T
    if "rawpagedata" in v:
        raw = np.asarray(v["rawpagedata"], dtype=np.float64).reshape(-1)
        pagesize = int(v.get("pagesize", 1024))
        packing = v.get("packing")
        if size == 1 or not packing or list(packing) == [size]:
            return raw.reshape(-1, size)
        # упаковка по компонентам внутри страницы: [[x...][y...][z...]] на страницу
        out, i = [], 0
        while i < len(raw):
            n = min(pagesize, (len(raw) - i) // size)
            page = []
            for w in packing:
                page.append(raw[i:i + n * int(w)].reshape(n, int(w)))
                i += n * int(w)
            out.append(np.hstack(page))
        return np.vstack(out) if out else np.zeros((0, size))
    raise ValueError("unsupported attribute values")


def profiles_signature_doc(doc):
    """Вложенная геометрия profiles NURBMesh из .geo Houdini (None — без обрезки) -> подпись,
    сравнимая с profiles_signature()."""
    return _signature(profile_regions_doc(doc))


def profile_regions_doc(doc):
    """Вложенная геометрия profiles из .geo -> области [[(порядок, узлы, точки (n, 3) = (u, v, w), u0, u1)]]
    в параметрах примитива (как в Houdini)."""
    if not doc:
        return []
    d = _kv(doc)
    P = np.zeros((0, 3))
    for a in _kv(d.get("attributes", [])).get("pointattributes", []):
        head, body = _kv(a[0]), _kv(a[1])
        if head.get("name") == "P":
            P = _attr_values(body["values"], int(body.get("size", 3)))
    topo = _kv(d.get("topology", []))
    ref = _kv(topo.get("pointref", []))
    idx = np.asarray(ref.get("indices", []), dtype=np.int64)
    curves = []
    for _, body in _iter_prims(d.get("primitives", [])):
        basis = _kv(body.get("basis", []))
        vtx = np.asarray(body.get("vertex", []), dtype=np.int64).reshape(-1)
        kn = np.asarray(basis.get("knots", []), dtype=np.float64)
        curves.append((int(basis.get("order", 0)), kn, P[idx[vtx]] if len(vtx) else np.zeros((0, 3))))
    regions = []
    for reg in d.get("trimregions", []):
        faces = []
        for f in _kv(reg).get("faces", []):
            fk = _kv(f)
            order, kn, pts = curves[int(fk["face"])]
            faces.append((order, kn, pts, float(fk.get("u0", kn[0] if len(kn) else 0.0)),
                          float(fk.get("u1", kn[-1] if len(kn) else 0.0))))
        if faces:
            regions.append(faces)
    return regions


def surface_profiles_checked(geo_doc):
    """.geo -> [(profiles или None, надёжно)] по NURBMesh в порядке примитивов. Houdini 22 при записи «прогона»
    (run) берёт набор полей по первому примитиву: если у него нет обрезки, обрезка остальных примитивов прогона
    в файл НЕ попадает. Надёжно — примитив вне прогона, первый в прогоне или прогон с полем profiles."""
    d = _kv(geo_doc)
    out = []
    for pr in d.get("primitives", []):
        head = _kv(pr[0])
        if head.get("type") == "run":
            if head.get("runtype") != "NURBMesh":
                continue
            names = list(head.get("varyingfields", []))
            uni = _kv(head.get("uniformfields", {}))
            has = "profiles" in names or "profiles" in uni
            for j, vals in enumerate(pr[1]):
                f = dict(uni)
                f.update(zip(names, vals))
                out.append((f.get("profiles"), has or j == 0))
        elif head.get("type") == "NURBMesh":
            out.append((_kv(pr[1]).get("profiles"), True))
    return out


def surface_profiles(geo_doc):
    """.geo Houdini (JSON) -> [вложенная геометрия profiles или None] по NURBMesh в порядке примитивов."""
    d = _kv(geo_doc)
    return [body.get("profiles") for t, body in _iter_prims(d.get("primitives", [])) if t == "NURBMesh"]


def nurbs_geo(items):
    """items: [{'kind': 'curve'|'surface', 'cv': (n,3) или (nv,nu,3), 'w': ..., 'order'/'order_u','order_v',
    'knots'/'knots_u','knots_v', 'trims' (необязательно, для поверхностей)}] -> JSON-объект геометрии Houdini
    (числовые массивы — numpy).

    Порядок примитивов = порядок items.
    """
    P, W, prims = [], [], []
    base = 0
    for it in items:
        cv = np.asarray(it["cv"], dtype=np.float64)
        w = np.asarray(it["w"], dtype=np.float64)
        if it["kind"] == "surface":
            nv, nu = cv.shape[:2]
            P.append(cv.reshape(-1, 3))
            W.append(w.reshape(-1))
            rows = list(np.arange(base, base + nv * nu, dtype=np.int32).reshape(nv, nu))
            su, sv = float(it["knots_u"][0]), float(it["knots_v"][0])
            ku, fu = safe_knots(it["knots_u"])
            kv, fv = safe_knots(it["knots_v"])
            body = ["vertex", rows, "surface", "quads", "uwrap", False, "vwrap", False,
                    "ubasis", ["type", "NURBS", "order", int(it["order_u"]), "endinterpolation", True, "knots", ku],
                    "vbasis", ["type", "NURBS", "order", int(it["order_v"]), "endinterpolation", True, "knots", kv]]
            if it.get("trims"):
                body += ["profiles", _profiles(it["trims"], su, sv, fu, fv)]
            prims.append([["type", "NURBMesh"], body])
            base += nv * nu
        else:
            cv = cv.reshape(-1, 3)
            P.append(cv)
            W.append(w.reshape(-1))
            kn, _ = safe_knots(it["knots"])
            prims.append(_curve_prim(base, len(cv), it["order"], kn))
            base += len(cv)
    P = np.concatenate(P) if P else np.zeros((0, 3))
    W = np.concatenate(W) if W else np.zeros(0)
    return _points_doc(P, prims, W=W)


def dump(items, path):
    """Записать NURBS в файл: .bgeo — двоичный JSON (быстро), иначе текстовый .geo (для отладки)."""
    doc = nurbs_geo(items)
    if path.endswith(".bgeo"):
        with open(path, "wb") as fh:
            fh.write(binary(doc))
    else:
        with open(path, "w") as fh:
            fh.write(json.dumps(doc, separators=(",", ":"), default=_ascii_default))
    return path

# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Дисковый кэш результата ноды импорта (.bgeo.sc + предупреждения).

Ключ — SHA-1 от: версии H3DM и Houdini, пути/размера/времени изменения файла, номера выхода, всех параметров
извлечения и итогового глобального трансформа (он учитывает вход Xform). Изменение чего угодно из этого
даёт новый ключ; старые записи вытесняются по размеру папки (сначала давно не читанные).
"""
import hashlib
import json
import os
import time

import hou

from . import __version__

DEFAULT_LIMIT_MB = 4096


def cache_dir(custom=""):
    d = custom or os.environ.get("H3DM_CACHE") or os.path.join(
        os.environ.get("HOUDINI_TEMP_DIR") or os.path.join(os.path.expanduser("~"), ".h3dm"), "h3dm_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _jsonable(v):
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, tuple):
        return list(v)
    return v


def make_key(path, output, opt, input_xform=None):
    """input_xform — словарь трансформа со входа Xform (или None). Итоговый трансформ однозначно следует из
    файла, параметров и входа, поэтому файл для ключа читать не нужно."""
    st = os.stat(path)
    data = {"h3dm": __version__, "houdini": hou.applicationVersionString(),
            "file": os.path.abspath(path), "size": st.st_size, "mtime": st.st_mtime_ns, "output": output,
            "options": {k: _jsonable(v) for k, v in sorted(vars(opt).items())},
            "input_xform": input_xform}
    s = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _paths(d, key):
    return os.path.join(d, key + ".bgeo.sc"), os.path.join(d, key + ".json")


def load(geo, key, custom=""):
    """True, если результат загружен; meta (предупреждения) -> второй элемент."""
    d = cache_dir(custom)
    gpath, mpath = _paths(d, key)
    if not (os.path.exists(gpath) and os.path.exists(mpath)):
        return False, None
    try:
        with open(mpath, encoding="utf-8") as fh:
            meta = json.load(fh)
        geo.loadFromFile(gpath)
        now = time.time()
        os.utime(mpath, (now, now))
        os.utime(gpath, (now, now))
        return True, meta
    except Exception:
        return False, None


def save(geo, key, meta, custom="", limit_mb=DEFAULT_LIMIT_MB):
    d = cache_dir(custom)
    gpath, mpath = _paths(d, key)
    tmp = gpath + ".%d.tmp.bgeo.sc" % os.getpid()
    try:
        geo.saveToFile(tmp)
        os.replace(tmp, gpath)
        with open(mpath + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
        os.replace(mpath + ".tmp", mpath)
    except Exception:
        for p in (tmp, mpath + ".tmp"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return False
    prune(d, limit_mb)
    return True


def prune(d, limit_mb=DEFAULT_LIMIT_MB):
    """Удалять давно не читанные записи, пока папка больше лимита."""
    entries = []
    total = 0
    for f in os.listdir(d):
        if f.endswith(".bgeo.sc") and ".tmp." not in f:
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            total += st.st_size
            entries.append((st.st_mtime, p, st.st_size))
    limit = max(0.0, float(limit_mb)) * 1024 * 1024
    for _, p, size in sorted(entries):
        if total <= limit:
            break
        for q in (p, p[: -len(".bgeo.sc")] + ".json"):
            try:
                os.remove(q)
            except OSError:
                pass
        total -= size


def stats(custom=""):
    d = cache_dir(custom)
    n = size = 0
    for f in os.listdir(d):
        if f.endswith(".bgeo.sc"):
            n += 1
            size += os.path.getsize(os.path.join(d, f))
    return d, n, size


def clear(custom=""):
    d = cache_dir(custom)
    removed = 0
    for f in os.listdir(d):
        if f.endswith(".bgeo.sc") or f.endswith(".json") or f.endswith(".tmp"):
            try:
                os.remove(os.path.join(d, f))
                removed += 1
            except OSError:
                pass
    return removed

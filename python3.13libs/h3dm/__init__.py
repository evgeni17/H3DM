# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""H3DM — импорт/экспорт файлов Rhino .3dm для Houdini на базе rhino3dm (openNURBS).

Пакет подключается через packages/H3DM.json (переменная $H3DM указывает на корень плагина).
Зависимость rhino3dm лежит внутри плагина: $H3DM/vendor/<py-версия>-<платформа>/.
"""
import os
import platform
import sys

__version__ = "0.4.0.dev8"

# Версия ассетов (часть имени типа ноды h3dm::3dm_import::<версия>). Правило (docs: README, раздел Versions):
#   релиз 0.N  -> ассеты ::N.0 (0.4 -> 4.0); исправление релиза, меняющее поведение, -> ::N.1 и т.д.;
#   после 1.0: релиз M.N -> ::(10*M+N).0.
# Выпущенная версия замораживается (freeze.py): копия этого пакета h3dm_<версия> и свои файлы HDA — ноды
# в рабочих сценах считаются тем же кодом всегда; разработка идёт в h3dm со следующей версией ассетов.
HDA_VERSION = "4.0"
FROZEN = False            # True в замороженной копии
IMPORT_TYPE = "h3dm::3dm_import::" + HDA_VERSION
EXPORT_TYPE = "h3dm::3dm_export::" + HDA_VERSION

# Проверенное окружение этой версии (полная таблица по версиям ассетов — VERSIONS.json в корне плагина).
# Меню H3DM > Install / Update rhino3dm ставит именно RHINO3DM_TESTED; при другой установленной версии ноды
# предупреждают. В одной сессии Houdini загружается одна rhino3dm на все версии ассетов.
RHINO3DM_TESTED = "8.35.0"
HOUDINI_TESTED = "22.0.429"

# корень плагина: .../H3DM  (этот файл: .../H3DM/python3.13libs/h3dm/__init__.py)
ROOT = os.environ.get("H3DM") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def platform_tag():
    """Тег платформы для папки vendor, например 'py313-macos-arm64'."""
    py = "py%d%d" % sys.version_info[:2]
    sysname = {"darwin": "macos", "win32": "win", "linux": "linux"}.get(sys.platform, sys.platform)
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return "%s-%s-%s" % (py, sysname, machine)


def vendor_dir():
    return os.path.join(ROOT, "vendor", platform_tag())


def ensure_vendor_path():
    """Добавляет vendor-папку в sys.path (один раз)."""
    d = vendor_dir()
    if os.path.isdir(d) and d not in sys.path:
        sys.path.insert(0, d)
    return d


ensure_vendor_path()


def has_rhino3dm():
    try:
        import rhino3dm  # noqa: F401
        return True
    except Exception:
        return False


def rhino3dm_version():
    """Установленная версия rhino3dm ('' — нет)."""
    try:
        from importlib import metadata
        return metadata.version("rhino3dm")
    except Exception:
        pass
    try:
        import rhino3dm
        return str(getattr(rhino3dm, "__version__", "") or "")
    except Exception:
        return ""


def rhino3dm_warning():
    """Текст предупреждения, если установлена не та rhino3dm, с которой проверена эта версия H3DM."""
    v = rhino3dm_version()
    if v and v != RHINO3DM_TESTED:
        return ("rhino3dm %s is installed; H3DM %s (assets %s) was tested with %s. Results may differ — "
                "H3DM > Install / Update rhino3dm installs the tested version." % (v, __version__, HDA_VERSION,
                                                                                  RHINO3DM_TESTED))
    return ""

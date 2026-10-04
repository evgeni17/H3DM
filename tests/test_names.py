# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Тесты модуля h3dm.names (обычный Python, без Houdini): python tests/test_names.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python3.13libs"))
import importlib.util
spec = importlib.util.spec_from_file_location("names", os.path.join(sys.path[0], "h3dm", "names.py"))
names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(names)

FAIL = []


def eq(got, exp, what):
    if got != exp:
        FAIL.append("%s: got %r, expected %r" % (what, got, exp))


# транслит слов
for src, exp in [
    ("СЦЮ", "STSYU"), ("ПA1", "PA1"), ("ПА3", "PA3"), ("Жилой дом", "Zhiloy_dom"), ("щи", "shchi"),
    ("Объект", "Obekt"), ("ВО1-3К", "VO1-3K"), ("Уровень пола", "Uroven_pola"), ("Имена 01", "Imena_01"),
    ("Ёлка", "Yolka"), ("ЁЛКА", "YOLKA"), ("Щит", "Shchit"), ("AXIS", "AXIS"), ("Layer 1", "Layer_1"),
    ("Отметка +3.500", "Otmetka_+3.500"), ("Я", "Ya"), ("ПА2 верх", "PA2_verkh"), ("Фасад-Юг", "Fasad-Yug"),
]:
    eq(names.translit(src), exp, "translit %s" % src)

# правило регистра проекта (верхний уровень и подслои)
eq(names.apply_case(["PA2_verkh"], "project"), ["PA2_verkh"], "project code_tail")
eq(names.apply_case(["Uroven_pola"], "project"), ["uroven_pola"], "project non-code")
eq(names.apply_case(["Imena_01"], "project"), ["imena_01"], "project non-code digits")
eq(names.apply_case(["PA1"], "project"), ["PA1"], "project code")
eq(names.apply_case(["VO1-3K"], "project"), ["VO1-3K"], "project code hyphen")
eq(names.apply_case(["SVZ", "Paneli", "Okna_Sever"], "project"), ["SVZ", "paneli", "okna_sever"], "project sublayers")
eq(names.apply_case(["AXIS", "Os_A"], "project"), ["AXIS", "Os_A"], "AXIS untouched")
eq(names.apply_case(["Fasad", "Paneli"], "lower"), ["fasad", "paneli"], "lower")

# безопасные идентификаторы
eq(names.safe_identifier("Группа фасад"), "Gruppa_fasad", "safe group")
eq(names.safe_identifier("1-й этаж"), "_1-y_etazh".replace("-", "_"), "safe digit start")
eq(names.safe_identifier("Марка"), "Marka", "safe attrib")

# слои и коллизии
m = names.NameMapper(names.MODE_TRANSLIT_KEEP, names.CASE_KEEP)
eq(m.layer("Фасад::Панели"), "Fasad::Paneli", "layer path")
eq(m.layer("Фасад::Окна"), "Fasad::Okna", "layer path 2")
eq(m.map.get("Fasad"), "Фасад", "map original")
# «Ель» и «Эль» дают разные имена; «Е» и «Э» -> E — коллизия
m2 = names.NameMapper()
a = m2.layer("Корень::Еда")
b = m2.layer("Корень::Эда")
eq(a, "Koren::Eda", "collision first")
eq(b, "Koren::Eda_2", "collision second")
eq(len(m2.warnings), 1, "collision warning")
# режим keep
m3 = names.NameMapper(names.MODE_KEEP)
eq(m3.layer("Фасад::Панели"), "Фасад::Панели", "keep mode")
eq(m3.group("Группа 1"), "Gruppa_1", "group always safe")

if FAIL:
    print("FAILED (%d):" % len(FAIL))
    for f in FAIL:
        print("  " + f)
    sys.exit(1)
print("test_names: OK")

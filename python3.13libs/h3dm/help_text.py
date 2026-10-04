# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Справка HDA (Houdini help wiki). Язык: переменная H3DM_HELP_LANG ("en" по умолчанию, "ru")."""

HELP_IMPORT_EN = u"""= H3DM 3dm Import =

#type: node
#context: sop
#internal: h3dm::3dm_import
#icon: SOP/file

\"\"\"Reads Rhino .3dm files with rhino3dm (openNURBS). Layers, names, colours, groups, User Text and materials become attributes.\"\"\"

The output uses the same attributes that H3DM 3dm Export understands, so import -> edit -> export keeps the structure.

Output 1 is the geometry. Output 2 (*Info*) holds points for text dots, texts, dimensions, leaders, named points, lights and block insertion points.

@parameters

3dm File:
    Rhino 3–8 file.
File Info:
    Object counts by type, units, render meshes, trimmed faces, Cyrillic names and the layer tree.
Surface Output:
    *NURBS Patches* — every Brep face becomes a Houdini NURBS surface with the exact degree, knots and weights.
    Trimmed faces are tessellated, or (with __Trimmed Faces as Untrimmed NURBS + Boundary Curves__) kept as the full
    untrimmed surface plus their boundary curves. *Polygons* — render meshes stored in the file, or H3DM's own
    tessellation when the file has none. *Packed* — one packed primitive per Rhino object; blocks become packed instances.
Non-Latin Names:
    *Keep*, *Transliterate* or *Transliterate, Keep Original* (`layer_orig`, `name_orig`, detail `h3dm_name_map`).
    Group names and attribute names made from User Text keys are always transliterated, because Houdini allows only
    `A-Z a-z 0-9 _` there.
Layer Case:
    *Keep*, *Lower*, or *Project Rule*: sublayers lower case; at the top level a code stays as is (PA1, VO1-3K),
    "code_tail" becomes CODE_tail, everything else lower case; the AXIS branch is not changed.

@attributes

`s@layer` (full path with `::`), `s@name`, `v@Cd`, `f@Alpha`, `s@material`, `d@user_text`, `s@rhino_id`, `s@rhino_type`,
`i@rhino_face`, `s@block`, `s@path` (`/layer/.../name`, compatible with HIFC). Rhino groups become primitive groups.

Detail: `d@rhino_doc` (units, tolerances, authors, earth anchor), `s@rhino_units`, `f@rhino_unit_m`,
`d@rhino_doc_text` (Document User Text), `d[]@rhino_layers`, `d[]@rhino_materials`, `d[]@rhino_groups`,
`d[]@rhino_blocks`, `d@h3dm_name_map`.
"""

HELP_IMPORT_RU = u"""= H3DM 3dm Import =

#type: node
#context: sop
#internal: h3dm::3dm_import
#icon: SOP/file

\"\"\"Читает файлы Rhino .3dm через rhino3dm (openNURBS). Слои, имена, цвета, группы, User Text и материалы становятся атрибутами.\"\"\"

Выход использует те же атрибуты, что понимает H3DM 3dm Export: импорт -> правка -> экспорт сохраняет структуру.

Выход 1 — геометрия. Выход 2 (*Info*) — точки текстовых меток, текстов, размеров, выносок, именованных точек, источников света и вставок блоков.

@parameters

3dm File:
    Файл Rhino 3–8.
File Info:
    Число объектов по типам, единицы, наличие render mesh, обрезанные грани, кириллические имена и дерево слоёв.
Surface Output:
    *NURBS Patches* — каждая грань Brep становится NURBS-поверхностью Houdini с точными степенью, узлами и весами.
    Обрезанные грани разбиваются на полигоны или (галочка __Trimmed Faces as Untrimmed NURBS + Boundary Curves__)
    остаются полной необрезанной поверхностью плюс кривые границ. *Polygons* — сетки отображения из файла или
    собственное разбиение H3DM, если сеток в файле нет. *Packed* — по packed-примитиву на объект Rhino, блоки — packed-экземпляры.
Non-Latin Names:
    *Keep* (оставить), *Transliterate* (транслит) или *Transliterate, Keep Original* (транслит + оригинал в
    `layer_orig`, `name_orig`, detail `h3dm_name_map`). Имена групп и атрибутов из ключей User Text транслитерируются
    всегда — Houdini допускает в них только `A-Z a-z 0-9 _`.
Layer Case:
    *Keep*, *Lower* или *Project Rule*: подслои строчными; на верхнем уровне код остаётся как есть (PA1, VO1-3K),
    «код_хвост» -> КОД_хвост, остальное строчными; ветка AXIS не меняется.

@attributes

`s@layer` (полный путь через `::`), `s@name`, `v@Cd`, `f@Alpha`, `s@material`, `d@user_text`, `s@rhino_id`, `s@rhino_type`,
`i@rhino_face`, `s@block`, `s@path` (`/слой/.../имя`, совместим с HIFC). Группы Rhino становятся группами примитивов.

Detail: `d@rhino_doc` (единицы, допуски, авторы, гео-привязка), `s@rhino_units`, `f@rhino_unit_m`,
`d@rhino_doc_text` (Document User Text), `d[]@rhino_layers`, `d[]@rhino_materials`, `d[]@rhino_groups`,
`d[]@rhino_blocks`, `d@h3dm_name_map`.
"""

HELP_EXPORT_EN = u"""= H3DM 3dm Export =

#type: node
#context: sop
#internal: h3dm::3dm_export
#icon: SOP/rop_geometry

\"\"\"Writes Houdini geometry to a Rhino .3dm file (export arrives in H3DM 0.4).\"\"\"

@attributes

| Houdini | Rhino |
|---|---|
| `s@layer` | layer with hierarchy (`Parent::Child`) |
| `s@name` | object name |
| `v@Cd` | object colour |
| primitive groups | Rhino groups |
| `d@user_text` and listed attributes (`id`, `thickness`, `category`...) | User Text |
| `s@material` | Rhino material (mapping table on the node) |
| `s@text` on points | Text dots |

NURBS surfaces are written as untrimmed surfaces; with __Trim Curves__ their boundary curves are written next to them.
Use __H3DM > Create Attribute Template__ for a ready-made Primitive Wrangle.
"""

HELP_EXPORT_RU = u"""= H3DM 3dm Export =

#type: node
#context: sop
#internal: h3dm::3dm_export
#icon: SOP/rop_geometry

\"\"\"Записывает геометрию Houdini в файл Rhino .3dm (экспорт появится в H3DM 0.4).\"\"\"

@attributes

| Houdini | Rhino |
|---|---|
| `s@layer` | слой с иерархией (`Родитель::Потомок`) |
| `s@name` | имя объекта |
| `v@Cd` | цвет объекта |
| группы примитивов | группы Rhino |
| `d@user_text` и перечисленные атрибуты (`id`, `thickness`, `category`...) | User Text |
| `s@material` | материал Rhino (таблица соответствий на ноде) |
| `s@text` на точках | текстовые метки (TextDot) |

NURBS-поверхности пишутся необрезанными; с галочкой __Trim Curves__ рядом пишутся кривые их границ.
Готовый Primitive Wrangle — __H3DM > Create Attribute Template__.
"""


def _lang():
    import os
    return (os.environ.get("H3DM_HELP_LANG") or "en").lower()[:2]


HELP_EXPORT = HELP_EXPORT_RU if _lang() == "ru" else HELP_EXPORT_EN
HELP_IMPORT = HELP_IMPORT_RU if _lang() == "ru" else HELP_IMPORT_EN

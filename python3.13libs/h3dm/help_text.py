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

@inputs

Xform:
    Optional. The *Xform* output of another H3DM 3dm Import. Its shift is used instead of the Global Transform tab,
    so several Rhino files of one project land in the same Houdini coordinates.

@outputs

Geometry:
    Surfaces, meshes, curves, point clouds, blocks.
Info:
    Points for text dots, texts, dimensions, leaders, named points, lights and (optionally) block insertion points:
    `s@info_type`, `s@text`, `s@text2`, `s@rich_text`, `f@text_height`, `f@measurement` (meters), `N`/`up`
    (text plane), `3@transform` (blocks), lights: `s@light_style`, `v@light_color`, `f@intensity`, `v@direction`.
Xform:
    One point with the global transform: `d@h3dm_xform` (exact, double precision), `s@h3dm_origin`,
    `4@global_xform`. Connect it to the second input of H3DM 3dm Export to write back to the original coordinates,
    or to the input of another import.

@global Global transform (models far from the origin)

Rhino stores coordinates in double precision, Houdini stores positions in float32 (about 7 significant digits).
A model 300 km from the origin loses centimetres in float32. H3DM subtracts an origin point *in double precision*
before positions are stored:

    P_houdini = axes * scale * (P_rhino - origin)

*Auto When Far From Origin* (default) shifts only models that extend further than __Far Threshold__; the origin is the
bounding box centre in X/Y and its bottom in Z, rounded to __Round To__ (1 m), so the shift is a clean number.
The exact origin is kept in `d@h3dm_xform` / `s@h3dm_origin` (dictionary and string attributes keep double
precision). `4@global_xform` is the same move as a float32 matrix for Transform By Attribute — fine for viewing,
not exact for far models.
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

@inputs

Xform:
    Необязательный. Выход *Xform* другого H3DM 3dm Import. Его сдвиг используется вместо вкладки Global Transform —
    несколько файлов Rhino одного проекта встают в одни и те же координаты Houdini.

@outputs

Geometry:
    Поверхности, сетки, кривые, облака точек, блоки.
Info:
    Точки текстовых меток, текстов, размеров, выносок, именованных точек, источников света и (по выбору) вставок
    блоков: `s@info_type`, `s@text`, `s@text2`, `s@rich_text`, `f@text_height`, `f@measurement` (метры), `N`/`up`
    (плоскость текста), `3@transform` (блоки), свет: `s@light_style`, `v@light_color`, `f@intensity`, `v@direction`.
Xform:
    Одна точка с глобальным трансформом: `d@h3dm_xform` (точно, double), `s@h3dm_origin`, `4@global_xform`.
    Подключите её ко второму входу H3DM 3dm Export — экспорт вернёт исходные координаты; или ко входу другого импорта.

@global Глобальный трансформ (модели далеко от нуля)

Rhino хранит координаты в double (64 бита), Houdini — позиции во float32 (32 бита, ~7 значащих цифр).
Модель в 300 км от нуля теряет во float32 сантиметры. H3DM вычитает точку origin *в двойной точности*
до записи позиций:

    P_houdini = оси * масштаб * (P_rhino - origin)

*Auto When Far From Origin* (по умолчанию) сдвигает только модели дальше __Far Threshold__; origin — центр габарита
по X/Y и его низ по Z, округлённый до __Round To__ (1 м), чтобы сдвиг был «круглым». Точный origin хранится в
`d@h3dm_xform` / `s@h3dm_origin` (dict- и строковые атрибуты держат double). `4@global_xform` — тот же сдвиг
матрицей float32 для Transform By Attribute: годится для просмотра, но для далёких моделей неточен.
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

Input 2 (*Xform*, optional): the *Xform* output of H3DM 3dm Import. The shift is added back in double precision,
so the file lands in the original Rhino coordinates.
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

Вход 2 (*Xform*, необязательный): выход *Xform* ноды H3DM 3dm Import. Сдвиг возвращается в двойной точности —
файл встаёт в исходные координаты Rhino.
Готовый Primitive Wrangle — __H3DM > Create Attribute Template__.
"""


def _lang():
    import os
    return (os.environ.get("H3DM_HELP_LANG") or "en").lower()[:2]


HELP_EXPORT = HELP_EXPORT_RU if _lang() == "ru" else HELP_EXPORT_EN
HELP_IMPORT = HELP_IMPORT_RU if _lang() == "ru" else HELP_IMPORT_EN

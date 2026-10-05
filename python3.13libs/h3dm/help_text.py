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
    Object counts by type, units, render meshes, trimmed faces, Cyrillic names, the layer tree and, for a prepared
    copy, the Prepare in Rhino stamp (Rhino version, mesh settings, source file).
Prepare in Rhino:
    Sends the file to a running Rhino 8 (Mac or Windows). Rhino opens it headless (your open document is not
    touched), creates render meshes for every face, stores the exact 2D trim curves, converts SubD to NURBS and
    saves `<name>_h3dm_v###.3dm` next to the source; then 3dm File switches to that copy. The same source with the
    same settings reuses the existing copy. Houdini is not blocked while Rhino works; press the button again to stop
    waiting. Settings are on the *Prepare* tab. Without Rhino at hand, run `rhino/h3dm_prepare.py` in Rhino
    (H3DM > Open Rhino Tools Folder) — it prepares the active document.
Geometry Mode:
    *Mesh + NURBS Curves* (new nodes) — surfaces and solids as polygons (Rhino render meshes), curves as exact NURBS.
    *NURBS Surfaces + Mesh Solids* — open surfaces as NURBS, closed solids as polygons.
    *All NURBS* — everything that has a NURBS form: curves, surfaces, trimmed faces as exact trimmed NURBS (prepared
    files), SubD as NURBS (prepared files). Rhino meshes stay meshes with a warning. Without preparation trimmed
    faces become untrimmed NURBS + boundary curves (group `rhino_trimmed_surfaces`) and a warning names
    Prepare in Rhino.
    *Legacy* keeps the 0.2 behaviour (Surface Output) of older scenes.
Pack per Object:
    One packed primitive per Rhino object, contents follow the mode. Independent of the mode.
Type groups:
    Every output primitive is in exactly one of `h3dm_type_polygon`, `h3dm_type_nurbs_curve`,
    `h3dm_type_nurbs_surface`, `h3dm_type_packed_geometry`, `h3dm_type_other` (real type after all conversions).
    Exact trimmed faces are also in `rhino_trimmed_exact`.
Trim Curve Tolerance:
    Houdini ignores the weights of trim curves, so rational trims (arcs) become polylines within this deviation.
    0 = 0.1 mm in model units.
Skip Hidden / Skip Locked:
    Applied the same way to the Geometry and Info outputs and to objects inside blocks (an object on a hidden or
    locked layer is skipped; block objects follow their own layer, as in Rhino).
User Text:
    `d@user_text` keeps every value as text. With __User Text to Attributes__ each key becomes an attribute;
    __Detect Numbers__ makes integers (int32, no leading zeros) and short decimals (up to 7 digits) numeric,
    everything else stays text, so IDs like `007` or `123456789012` are never rounded. __Keep as Text__ forces keys
    to text. Keys that clash with Houdini names get the prefix `ut_` (`name` -> `ut_name`), clashes get `_2`.
Non-Latin Names:
    *Keep*, *Transliterate* or *Transliterate, Keep Original* (`layer_orig`, `name_orig`, detail `h3dm_name_map`).
    Group names and attribute names made from User Text keys are always transliterated, because Houdini allows only
    `A-Z a-z 0-9 _` there.
Layer Case:
    *Keep*, *Lower*, or *Project Rule*: sublayers lower case; at the top level a code stays as is (PA1, VO1-3K),
    "code_tail" becomes CODE_tail, everything else lower case; the AXIS branch is not changed.
Create Layer Level Attributes:
    On by default. One string attribute per level of `s@layer`: `SC::STSZ::truby` gives `LL0` = `SC`,
    `LL1` = `STSZ`, `LL2` = `truby`; shallower layers get empty strings on deeper levels. Written on primitives,
    point clouds and Info points; names follow transliteration and Layer Case. __Prefix__ changes `LL`.

@attributes

`s@layer` (full path with `::`), `s@name`, `v@Cd`, `f@Alpha`, `s@material`, `d@user_text`, `s@rhino_id`, `s@rhino_type`,
`i@rhino_face`, `s@block`, `s@path` (`/layer/.../name`, compatible with HIFC), `s@LL0`, `s@LL1`, ... (layer levels). Rhino groups become primitive groups.

Detail: `d@rhino_doc` (units, tolerances, authors, earth anchor), `s@rhino_units`, `f@rhino_unit_m`,
`d@rhino_doc_text` (Document User Text), `d[]@rhino_layers`, `d[]@rhino_materials`, `d[]@rhino_groups`,
`d[]@rhino_blocks`, `d@h3dm_name_map`, `d@h3dm_prepare` (stamp of a prepared copy), `s[]@h3dm_warnings`.

@inputs

Xform:
    Optional. The *Xform* output of another H3DM 3dm Import. Its shift, scale and axes are used instead of the
    Global Transform tab, so several Rhino files of one project land in the same Houdini coordinates. If the input
    is connected but carries no H3DM transform, the node stops with an error; if its scale or axes differ from this
    node's settings, the input wins and a warning says so.

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

@cache Disk cache

With __Disk Cache__ (Cache tab) the cooked Geometry and Info outputs are stored as `.bgeo.sc` in
`$HOUDINI_TEMP_DIR/h3dm_cache` (or __Cache Folder__ / `$H3DM_CACHE`). The key covers the file (path, size, time),
every parameter, the global transform (Xform input included) and the H3DM and Houdini versions, so any change cooks
again; the least recently used entries are removed above __Size Limit__. *Reload* skips the cache once,
*Clear Disk Cache* empties the folder.
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
    Число объектов по типам, единицы, наличие render mesh, обрезанные грани, кириллические имена, дерево слоёв и
    для подготовленной копии — штамп Prepare in Rhino (версия Rhino, настройки сетки, исходный файл).
Prepare in Rhino:
    Отправляет файл в запущенный Rhino 8 (Mac или Windows). Rhino открывает его без окна (открытый документ не
    трогается), строит сетки отображения для всех граней, сохраняет точные 2D-кривые обрезки, переводит SubD в NURBS
    и пишет `<имя>_h3dm_v###.3dm` рядом с исходником; затем 3dm File переключается на эту копию. Тот же исходник
    с теми же настройками берёт уже готовую копию. Houdini не блокируется, пока Rhino работает; повторное нажатие
    прекращает ожидание. Настройки — вкладка *Prepare*. Можно и вручную: `rhino/h3dm_prepare.py` в Rhino
    (H3DM > Open Rhino Tools Folder) готовит активный документ.
Geometry Mode:
    *Mesh + NURBS Curves* (новые ноды) — поверхности и тела полигонами (сетки отображения Rhino), кривые точными NURBS.
    *NURBS Surfaces + Mesh Solids* — открытые поверхности NURBS, замкнутые тела полигонами.
    *All NURBS* — всё, что имеет NURBS-форму: кривые, поверхности, обрезанные грани — точными обрезанными NURBS
    (подготовленные файлы), SubD — NURBS (подготовленные файлы). Сетки Rhino остаются сетками с предупреждением.
    Без подготовки обрезанные грани приходят необрезанной NURBS + кривые границ (группа `rhino_trimmed_surfaces`),
    предупреждение предлагает Prepare in Rhino.
    *Legacy* сохраняет поведение 0.2 (Surface Output) в старых сценах.
Pack per Object:
    По packed-примитиву на объект Rhino, содержимое — по режиму. Не зависит от режима.
Группы типов:
    Каждый примитив выхода входит ровно в одну из групп `h3dm_type_polygon`, `h3dm_type_nurbs_curve`,
    `h3dm_type_nurbs_surface`, `h3dm_type_packed_geometry`, `h3dm_type_other` (фактический тип после всех
    преобразований). Точные обрезанные грани — ещё и в `rhino_trimmed_exact`.
Trim Curve Tolerance:
    Houdini не учитывает веса кривых обрезки, поэтому рациональные кривые (дуги) становятся ломаными в пределах
    этого отклонения. 0 = 0,1 мм в единицах модели.
Skip Hidden / Skip Locked:
    Одинаково для выходов Geometry и Info и для объектов внутри блоков (объект на скрытом или заблокированном слое
    пропускается; объекты блока подчиняются своему слою, как в Rhino).
User Text:
    `d@user_text` хранит все значения текстом. С __User Text to Attributes__ каждый ключ — отдельный атрибут;
    __Detect Numbers__ делает числами только целые (int32, без ведущих нулей) и короткие дроби (до 7 цифр), остальное
    остаётся текстом — идентификаторы вроде `007` или `123456789012` не округляются. __Keep as Text__ принудительно
    оставляет ключи текстом. Ключи, совпадающие с именами Houdini, получают префикс `ut_` (`name` -> `ut_name`),
    совпадения — суффикс `_2`.
Non-Latin Names:
    *Keep* (оставить), *Transliterate* (транслит) или *Transliterate, Keep Original* (транслит + оригинал в
    `layer_orig`, `name_orig`, detail `h3dm_name_map`). Имена групп и атрибутов из ключей User Text транслитерируются
    всегда — Houdini допускает в них только `A-Z a-z 0-9 _`.
Layer Case:
    *Keep*, *Lower* или *Project Rule*: подслои строчными; на верхнем уровне код остаётся как есть (PA1, VO1-3K),
    «код_хвост» -> КОД_хвост, остальное строчными; ветка AXIS не меняется.
Create Layer Level Attributes:
    Включено по умолчанию. По строковому атрибуту на каждый уровень `s@layer`: `SC::STSZ::truby` даёт
    `LL0` = `SC`, `LL1` = `STSZ`, `LL2` = `truby`; у слоёв меньшей глубины более глубокие уровни — пустые строки.
    Пишется на примитивы, точки облаков и точки Info; имена — после транслита и Layer Case. __Prefix__ меняет `LL`.

@attributes

`s@layer` (полный путь через `::`), `s@name`, `v@Cd`, `f@Alpha`, `s@material`, `d@user_text`, `s@rhino_id`, `s@rhino_type`,
`i@rhino_face`, `s@block`, `s@path` (`/слой/.../имя`, совместим с HIFC), `s@LL0`, `s@LL1`, ... (уровни слоя). Группы Rhino становятся группами примитивов.

Detail: `d@rhino_doc` (единицы, допуски, авторы, гео-привязка), `s@rhino_units`, `f@rhino_unit_m`,
`d@rhino_doc_text` (Document User Text), `d[]@rhino_layers`, `d[]@rhino_materials`, `d[]@rhino_groups`,
`d[]@rhino_blocks`, `d@h3dm_name_map`, `d@h3dm_prepare` (штамп подготовленной копии), `s[]@h3dm_warnings`.

@inputs

Xform:
    Необязательный. Выход *Xform* другого H3DM 3dm Import. Его сдвиг, масштаб и оси используются вместо вкладки
    Global Transform — несколько файлов Rhino одного проекта встают в одни и те же координаты Houdini. Если вход
    подключён, но не несёт трансформа H3DM, нода останавливается с ошибкой; если масштаб или оси входа отличаются
    от настроек ноды, побеждает вход, и об этом говорит предупреждение.

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

@cache Дисковый кэш

С __Disk Cache__ (вкладка Cache) готовые выходы Geometry и Info сохраняются как `.bgeo.sc` в
`$HOUDINI_TEMP_DIR/h3dm_cache` (или __Cache Folder__ / `$H3DM_CACHE`). Ключ учитывает файл (путь, размер, время),
все параметры, глобальный трансформ (с входом Xform) и версии H3DM и Houdini — любое изменение готовит заново;
при превышении __Size Limit__ удаляются давно не читанные записи. *Reload* один раз пропускает кэш,
*Clear Disk Cache* очищает папку.
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

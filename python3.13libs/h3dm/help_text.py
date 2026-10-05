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
    *All NURBS* — everything that has a NURBS form: curves, surfaces, trimmed faces as trimmed NURBS (prepared
    files), SubD as NURBS (prepared files). Rhino meshes stay meshes with a warning. Without preparation trimmed
    faces become untrimmed NURBS + boundary curves (group `rhino_trimmed_surfaces`) and a warning names
    Prepare in Rhino.
    *Legacy* keeps the 0.2 behaviour (Surface Output) of older scenes.
Pack per Object:
    One packed primitive per Rhino object, contents follow the mode. Independent of the mode.
Type groups:
    Every output primitive is in exactly one of `h3dm_type_polygon`, `h3dm_type_nurbs_curve`,
    `h3dm_type_nurbs_surface`, `h3dm_type_packed_geometry`, `h3dm_type_other` (real type after all conversions).
    Trimmed faces built from the prepared trim curves are also in `rhino_trimmed_exact` (non-rational trims
    exact, rational ones within Trim Curve Tolerance).
Trim Curve Tolerance:
    Houdini ignores the weights of trim curves, so rational trims (arcs) become polylines. The deviation is
    measured on the surface in model units (not in UV), so it holds for stretched surfaces too.
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
`i@rhino_face`, `s@block`, `s@path` (`/layer/.../name`, compatible with HIFC), `s@LL0`, `s@LL1`, ... (layer levels). Expanded blocks: `s@rhino_id` is the insertion, `s@rhino_instance_id`, `s@rhino_object_id`,
`s@rhino_part_path` (definition objects from the insertion down) and `s@rhino_block_path` tell its parts apart. Rhino groups become primitive groups.

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
    *All NURBS* — всё, что имеет NURBS-форму: кривые, поверхности, обрезанные грани — обрезанными NURBS
    (подготовленные файлы), SubD — NURBS (подготовленные файлы). Сетки Rhino остаются сетками с предупреждением.
    Без подготовки обрезанные грани приходят необрезанной NURBS + кривые границ (группа `rhino_trimmed_surfaces`),
    предупреждение предлагает Prepare in Rhino.
    *Legacy* сохраняет поведение 0.2 (Surface Output) в старых сценах.
Pack per Object:
    По packed-примитиву на объект Rhino, содержимое — по режиму. Не зависит от режима.
Группы типов:
    Каждый примитив выхода входит ровно в одну из групп `h3dm_type_polygon`, `h3dm_type_nurbs_curve`,
    `h3dm_type_nurbs_surface`, `h3dm_type_packed_geometry`, `h3dm_type_other` (фактический тип после всех
    преобразований). Обрезанные грани по кривым из подготовки — ещё и в `rhino_trimmed_exact` (нерациональные кривые
    точно, рациональные — в пределах Trim Curve Tolerance).
Trim Curve Tolerance:
    Houdini не учитывает веса кривых обрезки, поэтому рациональные кривые (дуги) становятся ломаными. Отклонение
    меряется на поверхности в единицах модели (не в UV) — допуск держится и на растянутых поверхностях. 0 = 0,1 мм в единицах модели.
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
`i@rhino_face`, `s@block`, `s@path` (`/слой/.../имя`, совместим с HIFC), `s@LL0`, `s@LL1`, ... (уровни слоя). Раскрытые блоки: `s@rhino_id` — вставка; части различают `s@rhino_instance_id`, `s@rhino_object_id`,
`s@rhino_part_path` (объекты определений от вставки вниз) и `s@rhino_block_path`. Группы Rhino становятся группами примитивов.

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

\"\"\"Writes Houdini geometry to a Rhino .3dm file: meshes, curves, NURBS surfaces, points, layers, names, colours, materials, groups and User Text.\"\"\"

Press __Export 3dm__ (the node does not write on cook). __Check Attributes__ shows what would be written without
writing. The report (and the read-back check) is on the *Report* tab.

@attributes

| Houdini | Rhino |
|---|---|
| `s@layer` | layer with hierarchy (`Parent::Child`); unchanged imported layers go back to their original names |
| `s@name` | object name |
| `v@Cd`, `f@Alpha` | object colour (equal to the layer colour -> "By Layer") |
| primitive groups | Rhino groups (service groups `h3dm_type_*`, `rhino_*` never) |
| `d@user_text` and User Text attributes of the import, plus __User Text Attributes__ | User Text (attributes win over the dictionary) |
| `s@material` | Rhino material (mapping table on the node, else the imported material) |
| `s@text` on points | Text dots |
| `s@rhino_id` | object id kept when it is still unique |

@objects What becomes a Rhino object

* Unchanged objects (__Unchanged Objects from Source File__, on by default): a Brep or extrusion imported with
  H3DM whose faces still match the source file (control points of NURBS faces, vertices of mesh faces, after the
  export transform, within float precision) is copied from the source .3dm (`rhino_file`) exactly: holes, joined
  faces and solids stay as they were. Layer, name, material, User Text and the other attributes still come from
  Houdini, so renaming or moving to another layer keeps the exact geometry. Works for block definitions too.
  Any change of the shape (moving a point, a transform) exports the object from the Houdini geometry instead.
* Closed polygons: one mesh per Rhino object of the import (`rhino_id`, or `rhino_instance_id` + `rhino_part_path`
  for parts of blocks); new geometry is split by connectivity. Polygons with more than 4 sides are divided.
* Open polygons: polylines. NURBS curves: exact NURBS curves (closed Houdini curves become periodic).
* NURBS surfaces: exact untrimmed NURBS surfaces (normals as shown in Houdini).
* Trimmed NURBS faces (`rhino_trimmed_exact`): planar faces with one outer loop (no holes) are written exactly
  as trimmed planes (arcs stay arcs; the trim loop is kept from the import in `rhino_trim_loops`, so moving or
  rotating the face is fine). Changed faces with holes and changed curved trimmed faces are meshes for now
  (Houdini Convert respects the trims); rebuilding them in Rhino comes next.
* Faces imported without trim data (`rhino_trimmed_surfaces`) are not exported: re-import after Prepare in Rhino.
* Packed primitives (__Packed Primitives__ = *Blocks*): block definitions (one per shared geometry, nested blocks
  too) and insertions with their full 4x4 transform; an insertion that was not moved keeps the exact double
  matrix of the import (`rhino_xform`). *Pack per Object* of the import is always exploded. *Explode*: every part
  is its own object.
* Points without primitives: text dots (`s@text`), points or point clouds (one per `rhino_id`).

@xform Coordinates and units

The geometry goes back to the Rhino coordinates in one double-precision step: origin, axes and scale from
`h3dm_xform`, then the file units. Input 2 (*Xform* output of the import) always wins; if it is connected but
carries no `h3dm_xform`, the export stops. Without input 2 the `h3dm_xform` detail of input 1 is used; without
any transform, __Scene Unit__ and __Y-Up__ apply (no shift). __Model Units__ = *As Imported* keeps the units of
the original file.

@safety Writing

The file is written to a temporary file next to the target and then renamed. An existing file is not replaced:
a new version `<name>_v###.3dm` is written unless __Overwrite Existing File__ is on. The imported file and its
prepared copy are protected separately (__Allow Overwriting the Source File__).
"""

HELP_EXPORT_RU = u"""= H3DM 3dm Export =

#type: node
#context: sop
#internal: h3dm::3dm_export
#icon: SOP/rop_geometry

\"\"\"Записывает геометрию Houdini в файл Rhino .3dm: сетки, кривые, NURBS-поверхности, точки, слои, имена, цвета, материалы, группы и User Text.\"\"\"

Запись — кнопкой __Export 3dm__ (нода не пишет файл при готовке). __Check Attributes__ показывает, что будет
записано, ничего не записывая. Отчёт (и контрольное чтение) — на вкладке *Report*.

@attributes

| Houdini | Rhino |
|---|---|
| `s@layer` | слой с иерархией (`Родитель::Потомок`); неизменённые слои импорта получают исходные имена |
| `s@name` | имя объекта |
| `v@Cd`, `f@Alpha` | цвет объекта (совпадает с цветом слоя -> «По слою») |
| группы примитивов | группы Rhino (служебные `h3dm_type_*`, `rhino_*` — никогда) |
| `d@user_text` и атрибуты User Text импорта, плюс __User Text Attributes__ | User Text (атрибуты важнее словаря) |
| `s@material` | материал Rhino (таблица на ноде, иначе материал импорта) |
| `s@text` на точках | текстовые метки (TextDot) |
| `s@rhino_id` | id объекта сохраняется, пока он уникален |

@objects Что становится объектом Rhino

* Неизменённые объекты (__Unchanged Objects from Source File__, включено по умолчанию): Brep или экструзия из
  импорта H3DM, грани которых совпадают с исходным файлом (управляющие точки NURBS-граней, вершины сеток граней —
  после трансформа экспорта, с точностью float), копируются из исходного .3dm (`rhino_file`) точно: отверстия,
  объединённые грани и тела остаются как были. Слой, имя, материал, User Text и прочие атрибуты берутся из
  Houdini — переименование и перенос на другой слой сохраняют точную геометрию. Работает и для определений
  блоков. Любое изменение формы (сдвиг точки, трансформ) — объект пишется из геометрии Houdini.
* Замкнутые полигоны: одна сетка на объект Rhino импорта (`rhino_id`, у частей блоков — `rhino_instance_id` +
  `rhino_part_path`); новая геометрия делится по связности. Многоугольники больше 4 сторон разбиваются.
* Открытые полигоны — полилинии. NURBS-кривые — точные NURBS (замкнутые кривые Houdini — периодические).
* NURBS-поверхности — точные необрезанные NURBS (нормали — как в Houdini).
* Обрезанные NURBS-грани (`rhino_trimmed_exact`): плоские грани с одной внешней петлёй (без отверстий) пишутся
  точно — обрезанной плоскостью (дуги остаются дугами; петля хранится с импорта в `rhino_trim_loops`, поэтому
  перенос и поворот грани допустимы). Изменённые грани с отверстиями и криволинейные обрезанные — пока сетками
  (Convert Houdini учитывает обрезку); пересборка в Rhino — следующий шаг.
* Грани, импортированные без данных обрезки (`rhino_trimmed_surfaces`), не экспортируются: импортируйте файл
  после Prepare in Rhino.
* Packed-примитивы (__Packed Primitives__ = *Blocks*): определения блоков (одно на общую геометрию, вложенные
  тоже) и вставки с полной матрицей 4x4; несдвинутая вставка сохраняет точную матрицу импорта в double
  (`rhino_xform`). *Pack per Object* импорта всегда раскрывается. *Explode* — каждая часть отдельным объектом.
* Точки без примитивов: текстовые метки (`s@text`), точки или облака точек (одно на `rhino_id`).

@xform Координаты и единицы

Геометрия возвращается в координаты Rhino одним шагом в двойной точности: origin, оси и масштаб из `h3dm_xform`,
затем единицы файла. Вход 2 (выход *Xform* импорта) главнее всего; если он подключён без `h3dm_xform`, экспорт
останавливается. Без входа 2 берётся detail `h3dm_xform` входа 1; без трансформа — __Scene Unit__ и __Y-Up__
(без сдвига). __Model Units__ = *As Imported* сохраняет единицы исходного файла.

@safety Запись

Файл пишется во временный рядом и затем переименовывается. Существующий файл не заменяется: пишется новая версия
`<имя>_v###.3dm`, если не включено __Overwrite Existing File__. Импортированный файл и его подготовленная копия
защищены отдельно (__Allow Overwriting the Source File__).
"""


def _lang():
    import os
    return (os.environ.get("H3DM_HELP_LANG") or "en").lower()[:2]


HELP_EXPORT = HELP_EXPORT_RU if _lang() == "ru" else HELP_EXPORT_EN
HELP_IMPORT = HELP_IMPORT_RU if _lang() == "ru" else HELP_IMPORT_EN

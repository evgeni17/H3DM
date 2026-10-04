# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Шаблоны VEX для подготовки атрибутов перед H3DM 3dm Export."""

# Primitive Wrangle: все атрибуты, которые понимает экспорт в Rhino
PRIM_WRANGLE = r'''// ============================================================
// H3DM: атрибуты для 3dm Export (Run Over: Primitives)
// Один объект Rhino = одно уникальное значение s@rhino_id (или s@name / s@path,
// см. параметр Split Objects By на ноде экспорта).
// ============================================================

// --- исходные данные (заменить на свои атрибуты) ---
string category = prim(0, "category", @primnum);
int    part_id  = prim(0, "part_id", @primnum);

// --- 1. СЛОЙ: полный путь через "::" (как в Rhino) ---
s@layer = sprintf("Model::%s", category);              // "Фасад::Панели" — кириллица допустима

// --- 2. ИМЯ ОБЪЕКТА ---
s@name = sprintf("%s_%04d", category, part_id);

// --- 3. ЦВЕТ ОБЪЕКТА (ObjectColor, ColorFromObject) ---
// v@Cd = {0.8, 0.4, 0.1};

// --- 4. МАТЕРИАЛ (имя материала Rhino; таблица соответствий — на ноде экспорта) ---
s@material = (category == "Glass") ? "Стекло" : "Бетон";

// --- 5. ГРУППЫ: обычные группы примитивов Houdini -> группы Rhino ---
// (параметр Groups на ноде экспорта: какие группы переносить)

// --- 6. USER TEXT (ключ -> значение, всё пишется строками) ---
// а) отдельные атрибуты — перечислить в параметре User Text Attributes (напр. "id thickness category")
s@id        = sprintf("P-%03d", part_id);
f@thickness = 200;
// б) словарь — любые ключи, в том числе кириллические
dict ut;
ut["Марка"] = sprintf("П-%d", part_id);
d@user_text = ut;

// --- 7. ТЕКСТ НА ТОЧКАХ -> TextDot (для точек, Run Over: Points) ---
// s@text = "Марка П-1";
'''


def create_wrangle(kwargs=None):
    """Создать Primitive Wrangle с шаблоном после выбранной SOP-ноды."""
    import hou
    sel = [n for n in hou.selectedNodes() if n.type().category() == hou.sopNodeTypeCategory()]
    if not sel:
        hou.ui.displayMessage("Select a SOP node first.", title="H3DM")
        return None
    src = sel[0]
    w = src.parent().createNode("attribwrangle", "rhino_attributes")
    w.setInput(0, src)
    w.parm("class").set(1)  # 1 = Primitives
    w.parm("snippet").set(PRIM_WRANGLE)
    w.setSelected(True, clear_all_selected=True)
    return w

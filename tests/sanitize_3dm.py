# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Копия .3dm без метаданных автора и путей (для публикации тестовых файлов).

    python tests/sanitize_3dm.py in.3dm out.3dm

Переносит: единицы и допуски, слои (иерархия, цвета, видимость, User Text слоя), материалы, группы,
определения блоков (в том числе вложенные), объекты с атрибутами и сетками отображения, Document User Text.
Не переносит: автора, пути, данные плагинов, виды, гео-привязку.
"""
import sys

import rhino3dm as r


def sanitize(src, dst, version=8):
    f = r.File3dm.Read(src)
    if f is None:
        raise IOError("cannot read %s" % src)
    o = r.File3dm()
    o.Settings.ModelUnitSystem = f.Settings.ModelUnitSystem
    o.Settings.ModelAbsoluteTolerance = f.Settings.ModelAbsoluteTolerance
    o.Settings.ModelAngleToleranceRadians = f.Settings.ModelAngleToleranceRadians
    o.Settings.ModelRelativeTolerance = f.Settings.ModelRelativeTolerance
    for i in range(len(f.Strings)):
        k, v = f.Strings[i]
        o.Strings[k] = v
    # материалы: индексы сохраняются, т.к. добавляем по порядку
    for m in f.Materials:
        o.Materials.Add(m)
    # слои: Id и ParentLayerId копируются вместе с объектом слоя
    for l in f.Layers:
        o.Layers.Add(l)
    for g in f.Groups:
        ng = r.Group()
        ng.Name = g.Name
        o.Groups.Add(ng)
    # блоки: сначала те, что не ссылаются на другие блоки
    idefs = list(f.InstanceDefinitions)
    id_map = {}

    def geom_of(oid):
        ob = f.Objects.FindId(oid)
        return (ob.Geometry, ob.Attributes) if ob is not None else (None, None)

    pending = list(idefs)
    while pending:
        progress = False
        for d in list(pending):
            items = [geom_of(x) for x in d.GetObjectIds()]
            if any(isinstance(gm, r.InstanceReference) and str(gm.ParentIdefId) not in id_map for gm, _ in items):
                continue
            geoms, attrs = [], []
            for gm, at in items:
                if gm is None:
                    continue
                if isinstance(gm, r.InstanceReference):
                    gm = r.InstanceReference(id_map[str(gm.ParentIdefId)], gm.Xform)
                geoms.append(gm)
                attrs.append(at)
            idx = o.InstanceDefinitions.Add(d.Name, d.Description or "", "", "", r.Point3d(0, 0, 0),
                                            tuple(geoms), tuple(attrs))
            id_map[str(d.Id)] = o.InstanceDefinitions.FindIndex(idx).Id
            pending.remove(d)
            progress = True
        if not progress:
            raise RuntimeError("cyclic block definitions")
    for ob in f.Objects:
        a = ob.Attributes
        if a.IsInstanceDefinitionObject:
            continue
        g = ob.Geometry
        if isinstance(g, r.InstanceReference):
            o.Objects.AddInstanceObject(r.InstanceReference(id_map[str(g.ParentIdefId)], g.Xform), a)
        else:
            o.Objects.Add(g, a)
    if not o.Write(dst, version):
        raise IOError("cannot write %s" % dst)
    return dst


if __name__ == "__main__":
    sanitize(sys.argv[1], sys.argv[2])
    print("written", sys.argv[2])

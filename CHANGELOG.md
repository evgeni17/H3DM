# Changelog

## 0.1.0 — 2026-10-05
* Package skeleton in the HIFC layout: `H3DM.json`, main menu **H3DM**, shelf, thin HDAs
  `h3dm::3dm_import` (outputs *Geometry* and *Info*) and `h3dm::3dm_export`, built by `h3dm.hda_build`.
* **Install / Update rhino3dm** installs rhino3dm 8.x into `vendor/<py>-<os>-<arch>` with Houdini's own pip.
* Import reads the document and its tables into detail attributes: `d@rhino_doc` (units, tolerances, authors,
  earth anchor), `s@rhino_units`, `f@rhino_unit_m`, `d@rhino_doc_text`, `d[]@rhino_layers`, `d[]@rhino_materials`,
  `d[]@rhino_groups`, `d[]@rhino_blocks`.
* **File Info**: objects by type, render meshes, trimmed faces, Cyrillic names, layer tree.
* `h3dm.names`: transliteration of Cyrillic names (the author's rule for project layers), layer case rules,
  safe group/attribute names, collision handling with a name map for round-trips. `tests/test_names.py`.
* Test fixtures made in Rhino 8 (`tests/rhino_make_fixtures.py`): every object type, Cyrillic nested layers,
  groups, nested blocks, User Text, materials; with and without render meshes.

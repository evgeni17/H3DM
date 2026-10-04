# H3DM — Rhino .3dm import / export for Houdini

H3DM adds Rhino `.3dm` import and export to SideFX Houdini as two SOP nodes. It uses
[rhino3dm](https://github.com/mcneel/rhino3dm) (openNURBS, MIT) and does not need Rhino.

> **Status: 0.1.0 — early development.** The package, menu, nodes, installer and the document/table import
> (units, layers, materials, groups, blocks, Document User Text, File Info) work. Geometry import and export
> are being built, see the roadmap below.

Русская версия: [README.ru.md](README.ru.md).

## What it transfers

| Houdini | Rhino |
|---|---|
| primitive `s@layer` | layer, including the hierarchy (`Parent::Child`) |
| primitive `s@name` | object name |
| primitive `v@Cd` | object colour |
| primitive groups | Rhino groups |
| `d@user_text`, `id`, `thickness`, `category` and other attributes | **User Text** (key → value) |
| `s@material` | Rhino material, by a mapping table |
| points of the *Info* output | text dots, texts, dimensions, leaders, named points, lights, block insertion points |

* **NURBS:** Brep faces become Houdini NURBS surfaces with the exact degree, knots and weights. Trimmed faces are
  tessellated, or kept as the untrimmed surface plus boundary curves (switch). Export writes NURBS surfaces
  untrimmed, with their boundary curves next to them.
* **Polygons:** render meshes stored in the file, or H3DM's own tessellation for files saved without them.
* **Non-Latin names:** Cyrillic layer, object, group and material names can be transliterated; the originals are
  kept and restored on export.

## Requirements

* Houdini 22 (Python 3.13).
* rhino3dm 8.x, installed into the plugin's `vendor/` folder (see below). macOS wheels need macOS 14+.

## Installation

1. Clone or download this repository (`git clone https://github.com/evgeni17/H3DM.git`).
2. Copy `H3DM.json` to your Houdini packages folder
   (macOS `~/Library/Preferences/houdini/22.0/packages/`,
   Windows `%USERPROFILE%/Documents/houdini22.0/packages/`,
   Linux `~/houdini22.0/packages/`) and set `"H3DM"` to the path of the cloned folder.
   `"H3DM_HELP_LANG"` can be `en` or `ru`.
3. Start Houdini and run **H3DM › Install / Update rhino3dm** (or install it manually, see `vendor/README.md`).
4. Run **H3DM › Rebuild HDAs** once.

## Repository layout

```
H3DM.json               Houdini package file (template)
MainMenuCommon.xml      "H3DM" main menu
toolbar/h3dm.shelf      H3DM shelf
otls/                   h3dm::3dm_import / h3dm::3dm_export digital assets (thin wrappers)
python3.13libs/h3dm/    all logic: rhino_read / rhino_write (pure rhino3dm), sop_import / sop_export (Houdini layer)
vendor/                 rhino3dm per platform (not in git)
tests/                  fixtures made in Rhino 8, unit and Houdini tests
```

## Roadmap

| Version | Content |
|---|---|
| 0.1 | package, menu, shelf, installer, HDAs, document data and tables, File Info |
| 0.1.x | import: layers, names, colours, groups, User Text, materials, Cyrillic names, meshes, curves, points |
| 0.2 | *Info* output: texts, dots, dimensions, leaders, named points, lights, block insertion points |
| 0.3 | exact NURBS surfaces and curves, trimmed-face tessellation, blocks as packed instances |
| 0.4 | export of everything above |
| 0.5 | tests, documentation, first public release |

## License

Copyright 2026 EOK. H3DM is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (rhino3dm is MIT and is installed separately).

H3DM is an independent project and is not affiliated with SideFX or Robert McNeel & Associates.
Houdini is a trademark of Side Effects Software Inc.; Rhinoceros, Rhino and openNURBS are trademarks of
Robert McNeel & Associates.

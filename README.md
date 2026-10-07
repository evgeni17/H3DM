# H3DM — Rhino .3dm import / export for Houdini

![H3DM: Rhino → Houdini → Rhino](docs/h3dm_banner.png)

H3DM adds Rhino `.3dm` import and export to SideFX Houdini as two SOP nodes. It uses
[rhino3dm](https://github.com/mcneel/rhino3dm) (openNURBS, MIT) and does not need Rhino to read files; an optional
*Prepare in Rhino* step uses a running Rhino 8 for files saved without render meshes and for trimmed NURBS surfaces.

> **Status: 0.4.0 released — import works; export writes meshes, curves, NURBS surfaces, blocks, points and all attributes back to the original coordinates; unchanged Breps go back exactly from the source file, changed trimmed Breps are rebuilt exactly in a running Rhino 8 (meshes without Rhino). Next: 0.5 — clean-install and no-Rhino tests, documentation, first public release.** Geometry modes (meshes, NURBS, trimmed NURBS),
> attributes, Cyrillic names, the *Info* output, the global transform for far-away models, Prepare in Rhino and a
> disk cache are done.

Русская версия: [README.ru.md](README.ru.md).

## What it transfers

| Houdini | Rhino |
|---|---|
| primitive `s@layer` | layer, including the hierarchy (`Parent::Child`) |
| primitive `s@LL0`, `s@LL1`, … | layer levels (`SC::STSZ::truby` → `SC`, `STSZ`, `truby`), import only |
| primitive `s@name` | object name |
| primitive `v@Cd` | object colour |
| primitive groups | Rhino groups |
| `d@user_text`, `id`, `thickness`, `category` and other attributes | **User Text** (key → value) |
| `s@material` | Rhino material, by a mapping table |
| points of the *Info* output | text dots, texts, dimensions, leaders, named points, lights, block insertion points |

* **Geometry modes:** *Mesh + NURBS Curves* (default) — surfaces and solids as Rhino render meshes, curves as exact
  NURBS; *NURBS Surfaces + Mesh Solids*; *All NURBS* — curves, surfaces, trimmed faces as trimmed NURBS and
  SubD as NURBS. Trim curves are exact when they are non-rational; rational ones (arcs) become polylines
  within *Trim Curve Tolerance* measured on the surface in model units (Houdini ignores trim weights). *Pack per Object* works with every mode. Every primitive is in one type group
  (`h3dm_type_polygon`, `h3dm_type_nurbs_curve`, `h3dm_type_nurbs_surface`, `h3dm_type_packed_geometry`,
  `h3dm_type_other`).
* **NURBS:** Brep faces become Houdini NURBS surfaces with the exact degree, knots and weights (knot vectors with
  spans Houdini cannot hold are reparametrized linearly — the shape does not change).
* **Export back to Rhino:** objects that were not changed in Houdini are copied from the source file exactly; objects
  moved, rotated or scaled as a whole get the source Brep with the exact transform; changed trimmed Breps are
  rebuilt in a running Rhino 8 (holes, joined faces, solids; a warning if a solid opens) — without Rhino they
  become exact trimmed planes and meshes with a warning. Untrimmed surfaces, curves, meshes, blocks, points and all
  attributes are written directly.
* **Files without render meshes, trims, SubD:** rhino3dm cannot tessellate and does not expose trim curves.
  The **Prepare in Rhino** button sends the file to a running Rhino 8: it meshes every face, stores the 2D trim
  curves, converts SubD to NURBS and writes `<name>_h3dm_v###.3dm` next to the source; the node then switches to it.
  Without it, trimmed faces without a mesh are skipped and All NURBS gives untrimmed surfaces + boundary curves,
  each with a warning.
* **Far from the origin:** the shift to the origin is computed in double precision before positions become float32;
  the import has an *Xform* output, the export an *Xform* input that writes back to the original coordinates.
* **Non-Latin names:** Cyrillic layer, object, group and material names can be transliterated; the originals are
  kept and restored on export.

## Limits of the Rhino rebuild

The rebuild in Rhino is used only for **changed** objects with trimmed faces (unchanged ones and ones moved,
rotated or scaled as a whole are copied from the source file, also when the export *Xform* differs from the
import). What to expect from it:

* Every face is rebuilt on its own from the Houdini surface (control points in float32 — after the shift to the
  origin, about 0.001 mm at 10 m) and its trims (exactly as imported unless edited in Houdini; edited trims come
  from Houdini's curves, arcs as polylines within *Trim Curve Tolerance*). The faces are then joined in Rhino at the
  join tolerance — the larger of the file's tolerance and twice the float32 precision of the object's coordinates —
  retried up to 20× that. On large or far-away objects this limit can be well above 20× the file's tolerance
  (on the test model: 0.0516 mm with a file tolerance of 0.001 mm).
* Faces that do not meet within that limit are **not** moved or patched: the object comes out as several
  Breps or an open Brep, and the report names it with the number of pieces and naked edges ("are OPEN after rebuilding",
  "did not join into one Brep"). Example: on a 114-object test model one valid solid came back as 15 Breps
  with 78 naked edges when everything was forced through the rebuild; in a normal export it is copied from the
  source.
* Checked automatically: Brep validity, solid / open compared with the source, naked edges. Not checked: the
  distance between the rebuilt faces and the Houdini surfaces.
* Objects that are already invalid in the source file are exported as meshes, with a warning.
* Speed: about 55 s for 3873 faces when every Brep is rebuilt; a normal export rebuilds only the changed ones.
* Without a running Rhino 8: exact trimmed planes for planar faces with one outer loop, meshes for the rest.

## Asset versions

The node types carry a version: `h3dm::3dm_import::5.0`, `h3dm::3dm_export::5.0` (in development; 0.4 is `::4.0`). Houdini keeps every installed
version side by side; the Tab menu creates the newest one, and nodes already in a scene stay on their version
([SideFX: asset versioning](https://www.sidefx.com/docs/houdini/assets/versioning_systems.html)).

* **Numbering:** release `0.N` -> assets `::N.0` (0.4 -> `::4.0`); a fix of a released version that changes its
  behaviour -> `::N.1`; after 1.0, release `M.N` -> `::(10*M+N).0`. Release 0.4 starts with `::4.0`.
* **Frozen versions:** a released asset version never changes. Its Python code is a frozen copy
  (`python3.13libs/h3dm_4_0/`, with its own Rhino scripts) and its HDA files (`otls/h3dm_3dm_import_4.0.hda`)
  call only that copy, so scenes made with it cook the same with any later H3DM. `FROZEN.sha256` and
  `tests/test_frozen.py` guard this.
* `::4.0` — H3DM 0.4.0 (export), frozen with the 0.4.0 code.
* `::1.0` — all nodes made before versioning (H3DM 0.3.x – 0.4.0-dev.6), frozen with the 0.4.0-dev.6 code.
* To move a node to a newer version: create the new node and copy the parameters; Houdini does not upgrade it
  silently. The frozen versions share `vendor/rhino3dm`; the versions each one was tested with are in
  `VERSIONS.json`.

## Requirements

* Houdini 22 (Python 3.13).
* rhino3dm, installed into the plugin's `vendor/` folder (see below). macOS wheels need macOS 14+. Each asset version
  records the rhino3dm and Houdini it was tested with in [`VERSIONS.json`](VERSIONS.json) (assets 4.0 / H3DM 0.4:
  **rhino3dm 8.35.0**, Houdini 22.0.429). **H3DM › Install / Update rhino3dm** installs exactly that version, and the
  nodes show a warning if another one is installed. One rhino3dm is loaded per Houdini session for all asset
  versions, so use the one listed for the newest version you work with.
* Optional, for *Prepare in Rhino*: Rhino 8 (Mac or Windows) running on the same computer. If the button cannot
  find it while Rhino is open, run the Rhino command `StartScriptServer`. `rhino/h3dm_prepare.py` can also be run
  by hand in Rhino's Script Editor: it prepares the active document.

## Disk cache

The import node stores its cooked outputs as `.bgeo.sc` in `$HOUDINI_TEMP_DIR/h3dm_cache` (Cache tab; folder,
size limit, *Clear Disk Cache*). The key covers the file, every parameter, the Xform input and the versions, so a
change always cooks again. On the 225 MB test model a cached cook takes 1–2 s instead of 4–9 s.

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
python3.13libs/h3dm/    all logic: rhino_read / rhino_write (pure rhino3dm), sop_import / sop_export (Houdini layer),
                        rhino_bridge / prepare_ui (Prepare in Rhino), geocache (disk cache)
rhino/                  scripts that run inside Rhino 8 (h3dm_prepare.py)
vendor/                 rhino3dm per platform (not in git)
tests/                  fixtures made in Rhino 8, unit and Houdini tests
```

## Roadmap

| Version | Content |
|---|---|
| 0.1 ✓ | package, menu, shelf, installer, HDAs, document data and tables, File Info |
| 0.2 ✓ | import: NURBS, meshes, curves, points, blocks, attributes, Cyrillic names, *Info* output, global transform |
| 0.3 ✓ | geometry modes, trimmed NURBS, Prepare in Rhino, type groups, strict Xform input, disk cache, speed |
| 0.4 ✓ | export of everything above (assets `::4.0`) |
| 0.5 | tests, documentation, first public release |

## License

Copyright 2026 EOK. H3DM is licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (rhino3dm is MIT and is installed separately).

H3DM is an independent project and is not affiliated with SideFX or Robert McNeel & Associates.
Houdini is a trademark of Side Effects Software Inc.; Rhinoceros, Rhino and openNURBS are trademarks of
Robert McNeel & Associates.

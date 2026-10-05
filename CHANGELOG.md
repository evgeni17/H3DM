# Changelog

## 0.3.1 — 2026-10-05
Prepare in Rhino on a real model (123 MB, 114 Breps, 3873 faces) took 9 minutes and looked frozen.
* **35× faster preparation:** the face areas (`AreaMassProperties`, used only by the tests) took 507 of 527 s.
  They are off now (`"face_areas": true` in the job settings turns them on). The same model: 527 s → 18 s.
* **Progress:** Rhino writes `<job>.progress.json`; the status bar shows the stage and counter
  (`converting objects 57/114`, `meshing`, `writing the copy`) and the elapsed time.
* **Rhino closed while working:** detected at once (the job used to wait for the full timeout).
* *Stop Waiting* explains that Rhino keeps working and the finished copy is picked up by the next press.

## 0.3.0 — 2026-10-05
Requirements from the 0.2.1 review: geometry modes, exact trimmed NURBS, preparation in Rhino, strict Xform input,
disk cache and speed.
* **Geometry Mode** replaces Surface Output for new nodes: *Mesh + NURBS Curves* (default), *NURBS Surfaces + Mesh
  Solids*, *All NURBS*; *Legacy* keeps 0.2 scenes unchanged. *Pack per Object* is a separate toggle for every mode.
  Closed curves are NURBS in every mode.
* **Exact trimmed NURBS:** prepared files carry the 2D trim curves; faces become Houdini trimmed NURBS surfaces
  (profiles + trim regions). Areas match Rhino within 0.04 % on the test fixture. Rational trims become polylines
  within *Trim Curve Tolerance* (Houdini ignores trim weights). Knot vectors start at 0 (Houdini returns infinities
  at the edge of a surface whose knots start below 0).
* **Prepare in Rhino** (button, menu *H3DM › Prepare in Rhino…*): a running Rhino 8 opens the file headless,
  meshes every face (document mesh settings, coarse or fine, overrides), stores trim curves, converts SubD and
  extrusions to NURBS and writes `<name>_h3dm_v###.3dm` next to the source with a stamp (source hash, settings,
  Rhino version). Houdini waits outside the cook and stays responsive; a second press stops waiting; late results,
  a changed *3dm File* or a deleted node are never overwritten. Same source + settings reuse the existing copy.
  Paths with spaces and Cyrillic work (RhinoCode is called without the shell wrapper). Several Rhino instances:
  you pick one. Non-3dm files are refused before Rhino sees them. `rhino/h3dm_prepare.py` also runs by hand in Rhino.
* **Type groups** `h3dm_type_polygon / nurbs_curve / nurbs_surface / packed_geometry / other`: every primitive is
  in exactly one, by its real type after all conversions. `rhino_trimmed_exact` marks exact trimmed faces.
* **Strict Xform input:** a connected input without `h3dm_xform` is an error; scale and axes come from the input
  (a warning tells when they differ from the node).
* **Warnings** are collected into one message (Houdini shows only the last `addWarning`) and stored in
  `s[]@h3dm_warnings`; they name *Prepare in Rhino* where it helps.
* **Disk cache** (Cache tab, on by default): `.bgeo.sc` per output with a key over file, parameters, Xform input and
  versions; LRU size limit; *Reload* skips it once, *Clear Disk Cache* empties it. The file is not read on a hit.
* **Speed** (225 MB test model, separate `hython` runs, cold / repeated cook): Polygons 10.8 / 9.7 s → 5.6 / 4.5 s,
  Packed 6.5 / 5.5 s → 4.7 / 3.7 s, NURBS Patches 11.1 / 10.5 s → 5.5 / 4.4 s; All NURBS 9.7 / 8.7 s; from the disk
  cache 1–2 s. User Text dictionaries are written once per object and spread with Attribute Copy (4.8 s → 0.04 s),
  one value per packed object becomes an attribute default, faces are re-indexed with NumPy, and NURBS go to
  Houdini as binary JSON (`.bgeo`, written by `h3dm.houjson`) instead of text `.geo` (load 19 s → 0.6 s on 5.3 M
  control points).
* File Info shows the preparation stamp; detail `d@h3dm_prepare` holds it; `h3dm.*` Document User Text keys are
  no longer copied into `rhino_doc_text`.
* Help, README: modes, type groups, Prepare in Rhino, strict Xform, disk cache.

## 0.2.1 — 2026-10-05
Fixes from the independent test report of 0.1–0.2. Every item has a regression test
(`tests/make_edgecases.py` builds `h3dm_edgecases_v001.3dm`; checks in `test_read.py`, `test_names.py`,
`houdini_regression.py`).
* **Periodic NURBS** curves and surfaces changed shape and opened up. They are now converted to the equivalent
  clamped NURBS by knot insertion (`h3dm.nurbs`): error against Rhino 1e-12, closed curves stay closed.
* **User Text keys** `name` and `ut_name` no longer merge: the `ut_` prefix is applied before the uniqueness check.
* **Names:** Latin names already in the file are reserved before transliteration (`Еда` no longer takes `Eda`);
  layers per parent, in file order, so results are the same on every cook.
* **Detect Numbers** no longer rounds: integers become int attributes (int32, no leading zeros), decimals only with
  up to 7 significant digits; `007`, `123456789012` stay text. New **Keep as Text** (key globs).
* **By Parent** colour/material of block objects follow their insertion, in Expand and Packed (one packed
  definition per insertion style when needed).
* **Colours:** vertex colours survive in Packed; point clouds keep their colours next to coloured meshes; points
  without own colours take their object's colour, so point `Cd` never hides primitive colours.
* **Point clouds** carry the full object attribute set (names, originals, path, material, User Text).
* **Filters:** Skip Hidden / Skip Locked act the same on Geometry, Info and block contents (hidden or locked objects
  and layers); type filters apply to block contents too.
* **Packed + Blocks = Expand** now expands block objects into separate packed primitives.
* **Curve Tolerance** works (adaptive polylines, 0 = 1 mm). Chord Tolerance, Max Angle and Max Edge Length were
  removed from the interface until the own tessellation in 0.3 — they had no effect.
* A broken file gives a short node error instead of a Python traceback.
* The installer pins `rhino3dm>=8,<9`. Transforms use `einsum` instead of `@` (no spurious NumPy warnings).
* Docs, File Info and node help describe what 0.2 really does with files saved without render meshes.
* Known: Packed per Object is slower on large files (attributes are now written inside every packed object as
  well); speed is part of 0.3.

## 0.2.0 — 2026-10-05
* **Geometry import.** Breps and extrusions as exact NURBS faces (*NURBS Patches*: degree, knots and weights via
  Houdini JSON geometry, normals oriented like Rhino), render meshes (*Polygons*) or one packed primitive per
  object (*Packed*). Trimmed faces: polygons from the file's render mesh, or with
  **Trimmed Faces as Untrimmed NURBS + Boundary Curves** the full surface (group `rhino_trimmed_surfaces`) plus
  its edge curves (group `rhino_trim_curves`). Untrimmed faces of files without render meshes are converted by Houdini.
  Meshes (vertex colours), SubD control nets (optionally subdivided), curves (exact NURBS or polylines),
  point clouds (colours). Faces of one object are welded.
* **Blocks** as packed instances sharing one geometry per definition (nested blocks too), or expanded.
* **Attributes:** `s@layer` (`Parent::Child`), `s@name`, `v@Cd` (display or object colour), `f@Alpha`,
  `s@material`, `d@user_text` and one attribute per User Text key (numbers detected), Rhino groups as primitive
  groups, `s@rhino_id`, `s@rhino_type`, `i@rhino_face`, `s@block`, `s@path` (HIFC-compatible).
  Filters by layer globs, hidden/locked layers and object types.
* **Cyrillic names** transliterated (layers, objects, materials; groups and User Text keys always), originals in
  `s@layer_orig`, `s@name_orig`, detail `d@h3dm_name_map`.
* **Global transform** for models far from the origin: the shift is computed in double precision before positions
  are stored in float32 (`h3dm.xform`). Modes: auto when far (default, bbox centre rounded to 1 m), auto, Rhino
  base point, manual, none. Exact origin in `d@h3dm_xform` / `s@h3dm_origin`, plus `4@global_xform`.
  On the user's test model (8 km from the origin, mm) float32 error drops from 0.3 mm to 0.006 mm.
* **Import node:** optional input *Xform* (share one shift between several files) and three outputs:
  *Geometry*, *Info* (text dots, texts, dimensions with measurement, leaders, named points, lights, block
  insertion points) and *Xform* (one point with the global transform). **Export node:** second input *Xform*
  (export itself arrives in 0.4).
* Install layout: development checkout + `deploy.py` copying to `~/tools_houdini/H3DM`.
* Tests: `test_xform.py`, `test_read.py`, `houdini_regression.py`.

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

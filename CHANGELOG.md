# Changelog

## 0.4.0 — 2026-10-07
Release 0.4: export to Rhino. Assets `::4.0` are frozen with this code (`python3.13libs/h3dm_4_0`).
Checked on the user's real model (114 Breps, 3873 faces, 113 solids): Rhino -> Houdini -> Rhino in Mesh + Curves and
All NURBS keeps every Brep exact and every solid closed (export 6–8 s); objects moved as a whole, a changed
global Xform and edits that keep the vertices (opened polygons) are handled; models made in Houdini from scratch
export as exact NURBS where possible. Known limits of the Rhino rebuild are documented in README.
Development of 0.4 in detail: 0.4.0-dev.1 … dev.10 below.

## 0.4.0-dev.10 — 2026-10-07
* **Fix: the geometry-signature fast path missed edits that keep every vertex.** Opening the polygons of a meshed
  Brep (they became polylines) still matched the import signature, so the source Brep was written instead of the
  curves, without a warning. The signature now also covers open polygons and primitive types other than polygons /
  NURBS (signature version 2: geometry imported by older builds is compared in full, not trusted).
* Test `run_export_sig_edits` (opened polygons of a meshed solid -> polylines; fails on dev.9).
* README / node help: the join limit of the Rhino rebuild is 20× max(file tolerance, 2× float32 precision of the
  object's coordinates), so it can exceed 20× the file tolerance on large or far objects.

## 0.4.0-dev.9 — 2026-10-07
* **Fix (regression of dev.8): unchanged Breps ignored a changed export transform.** The geometry-signature fast
  path copied the source Brep to its old place even when the *Xform* input (origin, scene scale or axes) differed
  from the import, so Breps stayed while curves, meshes and points moved. The import now also stores its
  Rhino -> Houdini matrix (`rhino_geo_sig_xform`); the export composes it with its own transform and writes the
  source Brep with the exact difference. Signatures without the matrix (imports by dev.8) are not trusted — the
  full comparison runs. Report line renamed: "placed with an exact transform (... or another global Xform than at
  import)".
* Test `run_export_xform_override`: origin +1000 mm, scene scale ×2, Y-up/Z-up switched — every object (Brep,
  curve, mesh, points) lands where the new transform puts it; fails on dev.8.
* **Limits of the Rhino rebuild** documented (README, node help): join tolerance up to 20× the file's, objects that
  stay split or open are reported, not patched; what is and is not checked.

## 0.4.0-dev.8 — 2026-10-07
Faster export (real model, 114 Breps / 3873 faces, everything copied from the source file):
All NURBS 20 s -> 7.4 s, Mesh + Curves 35 s -> 8.7 s; of that, about 4.5 s is rhino3dm writing the 128 MB file.
* **Geometry signatures:** the import writes `rhino_geo_sig` on every primitive of a Rhino object (vertex counts,
  face numbers, positions and weights in float32, NURBS orders and knots) and `rhino_file_sig` (content hash of
  the source .3dm). The export computes the same signature from arrays; when it matches and the source file is
  the same, the object is known unchanged without comparing its points with the source (report: "checked by
  geometry signature"). Otherwise the full comparison runs as before (moved objects, edits).
* **Trim curves read in binary:** `hou.Geometry.data()` + a binary JSON reader instead of writing and parsing a
  text .geo (3 s -> 0.2 s on 3873 faces, identical results).
* **No per-vertex HOM calls:** vertex -> point tables come in one go (`geosig.topology`, attribute promotion);
  used for passthrough, Rhino rebuild, free points, n-gon detection and writing.
* Groups are added/removed as whole groups, other primitive types are looked for only when they exist, the
  passthrough mask is read as an attribute.
* Mesh + Curves without passthrough also gets faster (23 s -> 8 s).

Models made in Houdini from scratch (checked: trimmed NURBS, spheres, tubes, circles, Bezier curves and surfaces,
metaballs, polysoups, scatter, packed copies, thousands of separate pieces):
* **NURBS surfaces trimmed in Houdini** (Trim, Profile ...) lost their trims and holes — they were written as the
  untrimmed surface. Their trim curves are now read and they go the way of trimmed import faces (rebuilt in Rhino,
  else planes / meshes).
* **Closed NURBS from Houdini** (spheres, tubes, closed curves with clamped ends, e.g. converted from Bezier) were
  skipped ("knots do not match"): the closing control points are now added per knot layout (periodic: order-1,
  clamped closed: one), before U is reversed.
* **Other primitive types** are converted exactly where possible: Bezier curves and circles -> NURBS curves,
  Bezier surfaces, spheres and tubes -> NURBS surfaces (a sphere comes back as an exact rational surface,
  radius 1000.000 mm); the rest -> polygons as before.
* **Points made in Houdini** (scatter ...) become one point cloud per layer and name instead of one object per point.
* Test `run_export_scratch`.

## 0.4.0-dev.7 — 2026-10-07
Asset versions follow the release; nodes in working scenes never change.
* Node types are versioned by release: release 0.N -> `h3dm::3dm_import::N.0` (0.4 -> `::4.0`); Houdini keeps all
  versions installed, the Tab menu creates the newest one, existing nodes stay on theirs.
* **`::1.0` is frozen** with the 0.4.0-dev.6 code (everything made before versioning): its HDAs
  (`otls/h3dm_3dm_import_1.0.hda`, `..._export_1.0.hda`) call only the frozen copy `python3.13libs/h3dm_1_0/` with
  its own Rhino scripts, so working scenes cook exactly as before whatever changes in development.
* `freeze.py` (freeze / `--seal` / `--verify`) makes and guards frozen versions; `tests/test_frozen.py` checks the
  checksums and that the development version is above all frozen ones; Houdini regression `run_versions`.
* **Dependency versions:** `RHINO3DM_TESTED` (8.35.0) and `HOUDINI_TESTED` (22.0.429) in `h3dm/__init__.py`;
  `VERSIONS.json` lists, for every asset version, the plugin version, rhino3dm, Houdini and Python it was tested
  with (`freeze.py --seal` records frozen versions). **H3DM › Install / Update rhino3dm** installs exactly the tested
  rhino3dm (no silent upgrade to the newest 8.x); import and export warn if another version is installed;
  *About* shows tested vs installed.
* Development continues as `::4.0`; the old unversioned HDA files `h3dm_3dm_import.hda` / `h3dm_3dm_export.hda`
  are replaced by the versioned files.

## 0.4.0-dev.6 — 2026-10-05
Fixes from the real-model round trip (test.3dm of AA_LIK_KonZal: 114 Breps, 3873 faces, 113 solids).
* **Knot vectors Houdini rejects:** Houdini 22 drops a knot vector with a span below ~1e-5 (absolute) and puts
  `[0 0 0 0 1 1 1 1]` instead — the surface or trim curve was silently broken in Houdini, its trim signature never
  matched and 78 unchanged objects were rebuilt. The import now reparametrizes such knot vectors linearly (shape
  unchanged) so the smallest span is >= 1e-3, with the trims, the exact loops and the signature in the same
  parameter; knots are compared normalized.
* **Houdini .geo writer loses trims:** in a primitive "run" Houdini writes the fields of the first primitive only,
  so trims of later primitives vanish when the first one is untrimmed. The trim reader puts a trimmed helper
  primitive first and re-reads anything not covered.
* **Moved / rotated / scaled objects** (one affine transform for all control points / vertices within float
  precision, near-rotations snapped) are written as the source Brep with that transform in double precision —
  exact and still solid. Real model: a 105-face solid moved by 100 mm comes back closed, 100 mm higher.
* **Rebuilding in Rhino:** all changed Brep objects with two or more NURBS faces are sent (also those without
  trims, so boxes join into solids); faces are joined with a tolerance that starts at the float precision of the
  Houdini positions and grows up to 20x until the source solid closes (the valid result with the fewest naked
  edges wins; otherwise the faces are written separately); singular trims get their N/S/E/W side; an edge that
  Pushup cannot build is interpolated on the surface; an open edge never shares one vertex at both ends.
  The source file is opened for this even when passthrough is off. New warnings: a source solid that is open
  after rebuilding (naked edge count) and an object written as several Breps.
* **Fallback meshes:** Convert LOD is capped per face (no more than 64 divisions per direction) and can be
  interrupted — before, faces with hundreds of spans took minutes.
* Real model, All NURBS: unchanged — 114 Breps copied, 113 solids (17 s); everything rebuilt in Rhino (passthrough
  off) — 113 of 114 objects, 111 of 113 solids (96 s); the remaining ones are reported (one Brep is already
  invalid in the source). Tests: `run_export_real` (optional, private file), moved objects in the passthrough
  and Rhino sections, Houdini-safe knots in `test_houjson`.

## 0.4.0-dev.5 — 2026-10-05
Export, step 4: changed trimmed Breps are rebuilt in Rhino.
* **Trimmed Surfaces = Rebuild in Rhino** (new default): every NURBS face of a changed object with trimmed faces
  is sent to a running Rhino 8 (`rhino/h3dm_retrim.py`, same RhinoCode bridge as Prepare in Rhino) — the surface
  as it is in Houdini (positions in the export coordinates, weights, knots) and its trim loops: the exact loops of
  the import when the trim signature shows the trims were not edited in Houdini, otherwise Houdini's current trim
  curves (read from .geo). Rhino builds each face Brep by hand (2D trims, pushed-up edges, shared vertices,
  singular trims at poles, seams joined), sorts loops by nesting (outer CCW, holes CW; several outer loops — several
  faces), checks IsValidWithLog, joins the faces (JoinBreps) and writes them to a temporary .3dm that the export
  copies. Objects Rhino cannot rebuild — or all of them when Rhino is not running — fall back to exact trimmed
  planes and meshes with a warning; objects whose faces no longer meet are written as several Breps with a warning.
* Trimmed planes without Rhino now also use the trim signature: if the trims were edited in Houdini, the current
  Houdini loop is used instead of the stored import loop.
* `rhino_bridge.submit_script` — generic jobs for scripts in Rhino.
* Tests (`run_export_rhino`, needs Rhino 8): all four trimmed objects of the prepared fixture rebuilt from Houdini
  match the source (faces, edges, loops, solids, bounding box; in Rhino also equal areas and volumes); a column moved
  by 0.1 m comes back 100 mm higher and still solid while the rest is copied; a hole removed in Houdini is gone;
  deformed faces give valid Breps and the warning for an open column; without Rhino — planes, meshes and a warning.

## 0.4.0-dev.4 — 2026-10-05
Fixes from the 0.4.0-dev.3 review (both reproduced; not a release yet).
* **Edits of NURBS faces were lost:** the unchanged-object check compared only control point positions, so a
  changed weight (36.95 mm shape difference in the review) or a removed hole was replaced by the source Brep.
  Now NURBS faces are compared completely: positions, weights (`Pw`), knots, orders, wrap and trims. Trims are
  checked with the new prim attribute `rhino_trim_sig` written at import: the signature of the trim curves the
  import wrote into Houdini (compared with the primitive's current trim curves, read from .geo because HOM has no
  trim access) and the hash of the source file's trim data (compared with the source file now — it may have been
  edited after the import). Objects imported by older versions have no signature and are not copied (warning).
* **Source file protection** compares the physical file (realpath + samefile): a link to the source folder or
  file, a hard link and a different letter case no longer bypass *Allow Overwriting the Source File*.
* Tests (`run_export_changes`): a changed weight, a changed knot, a removed hole and source trims edited after
  the import are exported from Houdini (the rest is still copied); writing through a folder link, a hard link or
  `SOURCE.3dm` is refused.

## 0.4.0-dev.3 — 2026-10-05
Export, step 3: unchanged Breps go back exactly.
* **Unchanged objects from the source file** (new toggle, on by default): a Brep or extrusion imported with H3DM
  whose faces still match the source file is copied from it (detail `rhino_file`) instead of being rebuilt from
  Houdini geometry: holes, joined faces, solids and seams stay exact. The check needs no fingerprints at import:
  every face is compared by its `rhino_face` primitives — NURBS faces by control points (U may be reversed),
  mesh faces by the vertices of each render-mesh face in import order — after the export transform, within float32
  precision of the Houdini positions. Works in every geometry mode and for block definitions. Attributes (layer,
  name, material, User Text, id) still come from Houdini. Service user strings `h3dm.*` are removed.
* Test: the prepared fixture (all NURBS and meshes) — all 6 Breps come back with the same faces, edges, loops and
  bounding box; a renamed layer is kept; a moved object is exported from Houdini; the toggle off disables it.
  Checked in Rhino 8: all valid, solids stay solids, the panel with a hole keeps 2 loops, areas identical.

## 0.4.0-dev.2 — 2026-10-05
Export, step 2: blocks and exact trimmed planes.
* **Blocks:** packed primitives become block definitions and insertions (one definition per shared geometry,
  nested blocks, mirrored / non-uniformly scaled insertions via the full 4x4). Insertions keep the exact double
  matrix of the import (new prim attribute `rhino_xform`) unless they were moved in Houdini (float32 packed
  transform). Insertion attributes (layer, name, material, User Text, id) and definition object attributes are
  written separately. Test: the fixture's insertions come back with identical matrices (1e-9) and definition
  names; an insertion moved by 1 m in Houdini is moved by 1000 mm in Rhino. *Packed Primitives = Explode* keeps
  the old behaviour.
* **Trimmed faces without Rhino:** planar faces with a single outer loop (no holes) on an affine planar surface are
  written exactly with `Brep.CreateTrimmedPlane` (rhino3dm has no multi-loop trimming, so faces with holes and
  curved trimmed faces stay meshes until the Rhino step). The exact loops (with weights) are stored at import
  in `rhino_trim_loops`; the face may be moved or rotated. Checked in Rhino: the column caps (circles) have the
  same area as the originals.
* Material equal to the layer material is written "By Layer"; the layer material is set on the layer.
* Read-back count includes block definition objects; report lists block definitions.

## 0.4.0-dev.1 — 2026-10-05
Export, step 1 of 0.4 (decisions from the 0.3.0 review): meshes, curves, untrimmed surfaces, attributes and the
global transform. Not a release yet: blocks, exact Breps and rebuilding trimmed faces in Rhino follow.
* **H3DM 3dm Export works** (button *Export 3dm*, *Check Attributes*, report with read-back check):
  closed polygons -> meshes (one per Rhino object: `rhino_id`, block parts by `rhino_instance_id` +
  `rhino_part_path`, new geometry by connectivity; n-gons divided), open polygons -> polylines, NURBS curves ->
  exact NURBS (closed -> periodic), NURBS surfaces -> exact untrimmed surfaces, points -> text dots / points /
  point clouds. Other primitive types are converted to polygons; packed primitives are unpacked (each part its own
  object).
* **Trimmed faces** are meshed for now (Houdini Convert respects the trims, warning in the report); faces imported
  without trim data (`rhino_trimmed_surfaces`) are never written as untrimmed surfaces. "Surface + boundary
  curves" is gone from the export.
* **Coordinates:** one inverse transform in double precision (origin, axes, scale) plus the file units; a connected
  input 2 always wins and must carry `h3dm_xform`; otherwise the detail of input 1; otherwise scene units by
  parameters. Mesh vertices are written in double precision (`AddPoint3d`; `Add` rounded far models to cm).
  Test: a model 2,267 km away comes back within 0.01 mm; the same in meters.
* **Attributes:** unchanged imported names (layers, objects, materials, groups, User Text keys) go back to the
  originals via the new detail `h3dm_export_names`; renamed or new names are written as they are. User Text
  attributes of the import win over `d@user_text`; numeric attributes at their default are not added to objects
  that did not have the key. Service attributes and groups (`h3dm_type_*`, `rhino_*`, `h3dm_*`, `LL*`, `*_orig`)
  are never exported. The whole imported layer table is kept (colors, visibility, locking, layer User Text);
  object colour equal to the layer colour is written "By Layer"; Document User Text is restored.
* **Safe writing:** temporary file + rename; an existing file gets a new version `_v###` unless *Overwrite*; the
  imported file and its prepared copy need *Allow Overwriting the Source File*. Degenerate mesh faces are removed.
* **Fix (import, since 0.3.0):** string and dictionary attributes with one value for all elements (one layer in
  the file, *Pack per Object*, block definitions) came out empty: Houdini does not apply string/dict attribute
  defaults. Values are written explicitly again; regression `run_constant_attribs`.
* Tests: `tests/rt_compare.py` (attributes, boxes from render meshes, shape deviation of curves/surfaces incl.
  block insertions), regression sections `export` and `export new geometry`.

## 0.3.2 — 2026-10-05
Fixes from the review of 0.3.0 (export 0.4 preconditions).
* **Trim Curve Tolerance in model space.** Rational trims were sampled by their deviation in UV, so a stretched
  surface (1000 mm per UV unit) gave 20.78 mm instead of 0.1 mm. The deviation is now measured on the surface
  (surface point on the curve vs. on the UV chord, at 1/4, 1/2, 3/4 of each segment); test: 0.1 and 0.01 mm hold
  on that surface. Docs no longer call these faces "exact": non-rational trims are exact, rational ones are
  polylines within the tolerance.
* **Prepare: partial result.** Faces left without a render mesh (or meshing failures) give the status `partial`:
  the node gets the copy with a warning listing the objects, and such a copy is not reused on the next press.
* **Expanded blocks:** parts of one insertion share `rhino_id` (the insertion), so they also get
  `s@rhino_instance_id`, `s@rhino_object_id`, `s@rhino_part_path` (chain of definition objects, unique even for
  nested repeats) and `s@rhino_block_path` — the key for splitting objects on export.

## 0.3.1 — 2026-10-05
Prepare in Rhino on a real model (123 MB, 114 Breps, 3873 faces) took 9 minutes and looked frozen.
* **35× faster preparation:** the face areas (`AreaMassProperties`, used only by the tests) took 507 of 527 s.
  They are off now (`"face_areas": true` in the job settings turns them on). The same model: 527 s → 18 s.
* **Progress:** Rhino writes `<job>.progress.json`; the status bar shows the stage and counter
  (`converting objects 57/114`, `meshing`, `writing the copy`) and the elapsed time.
* **Rhino closed while working:** detected at once (the job used to wait for the full timeout).
* *Stop Waiting* explains that Rhino keeps working and the finished copy is picked up by the next press.
* **Layer level attributes** (Names tab, on by default): `s@layer` split into `LL0`, `LL1`, ... —
  `SC::STSZ::truby` gives `LL0 = SC`, `LL1 = STSZ`, `LL2 = truby`; on primitives, point clouds and Info points;
  prefix configurable; User Text keys with these names get `ut_`.
* **Rebuild HDAs keeps parameter values** of nodes in the open scene: the loaded definition is updated in place
  instead of being destroyed and created again (that reset every node to defaults); values are also checked and
  restored after the rebuild.

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

# Tests

* `fixtures/` — small files made with Rhino 8 by `rhino_make_fixtures.py` (run it in an empty Rhino document):
  every object type, Cyrillic nested layers, groups, nested blocks, User Text, materials, Document User Text.
  `h3dm_fixture_v001.3dm` has render meshes, `h3dm_fixture_small_v001.3dm` has none (like *Save Small*).
  `h3dm_trimmed_v001.igs` — the same trimmed Breps as IGES, for comparison with Houdini's `giges`.
  The published fixtures were passed through `sanitize_3dm.py` (no author, paths or plug-in data).
* `sanitize_3dm.py in.3dm out.3dm` — copies a file without author/path metadata, e.g. before sharing a test file.
* `make_edgecases.py` — builds `fixtures/h3dm_edgecases_v001.3dm` with rhino3dm only: periodic NURBS, name and
  User Text collisions, long numeric IDs, By Parent blocks, coloured clouds next to coloured meshes, hidden/locked
  objects and layers.
* `private/` — your own files for local testing (git-ignored).

```bash
python tests/test_names.py      # transliteration and name rules (plain Python)
python tests/test_xform.py      # global transform, float32 precision far from the origin (numpy)
python tests/test_read.py       # reading the fixtures (rhino3dm + numpy)
python tests/test_houjson.py    # binary JSON (.bgeo) writer for NURBS and trims (numpy)
```

In Houdini (Python Shell or `hython`):

```python
exec(open("<H3DM>/tests/houdini_regression.py").read())   # HDA modes, normals, groups, Info, Xform input
```

The *prepare* section of the Houdini regression needs a running Rhino 8 (otherwise it is skipped): it prepares a
copy of the small fixture in a folder with spaces and Cyrillic, checks meshes, the stamp, reuse of an up-to-date
copy, exact trims, and refusal of non-3dm files and unknown Rhino instances.
* `fixtures/h3dm_fixture_prepared_v001.3dm` — the small fixture after `rhino/h3dm_prepare.py` (sanitized).

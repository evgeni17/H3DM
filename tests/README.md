# Tests

* `fixtures/` — small files made with Rhino 8 by `rhino_make_fixtures.py` (run it in an empty Rhino document):
  every object type, Cyrillic nested layers, groups, nested blocks, User Text, materials, Document User Text.
  `h3dm_fixture_v001.3dm` has render meshes, `h3dm_fixture_small_v001.3dm` has none (like *Save Small*).
  `h3dm_trimmed_v001.igs` — the same trimmed Breps as IGES, for comparison with Houdini's `giges`.
  The published fixtures were passed through `sanitize_3dm.py` (no author, paths or plug-in data).
* `sanitize_3dm.py in.3dm out.3dm` — copies a file without author/path metadata, e.g. before sharing a test file.
* `private/` — your own files for local testing (git-ignored).

```bash
python tests/test_names.py      # transliteration and name rules (plain Python)
python tests/test_xform.py      # global transform, float32 precision far from the origin (numpy)
python tests/test_read.py       # reading the fixtures (rhino3dm + numpy)
```

In Houdini (Python Shell or `hython`):

```python
exec(open("<H3DM>/tests/houdini_regression.py").read())   # HDA modes, normals, groups, Info, Xform input
```

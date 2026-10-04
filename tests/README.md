# Tests

* `fixtures/` — small files made with Rhino 8 by `rhino_make_fixtures.py` (run it in an empty Rhino document):
  every object type, Cyrillic nested layers, groups, nested blocks, User Text, materials, Document User Text.
  `h3dm_fixture_v001.3dm` has render meshes, `h3dm_fixture_small_v001.3dm` has none (like *Save Small*).
  `h3dm_trimmed_v001.igs` — the same trimmed Breps as IGES, for comparison with Houdini's `giges`.
* `private/` — your own files for local testing (git-ignored).

```bash
python tests/test_names.py      # transliteration and name rules (plain Python)
```

# Third-party software

H3DM's own code is Apache-2.0 (see `LICENSE`). The repository contains **no**
third-party source code or binaries. H3DM imports the libraries below at runtime.
They are installed by the user into `vendor/<python>-<os>-<arch>/`
(menu **H3DM › Install / Update rhino3dm**, or `pip install --target`),
and each keeps its own licence.

| Package | Licence | Project |
|---|---|---|
| rhino3dm (with openNURBS) | MIT | https://github.com/mcneel/rhino3dm |
| numpy (shipped with Houdini) | BSD-3-Clause | https://numpy.org |

rhino3dm is MIT-licensed, so a ready-to-use zip that includes `vendor/` only needs
to keep the `rhino3dm-*.dist-info` folder (it contains the licence text).

## Test data

`tests/fixtures/` contains small files made for H3DM with Rhino 8 (`tests/rhino_make_fixtures.py`).
They are part of H3DM and covered by its licence.

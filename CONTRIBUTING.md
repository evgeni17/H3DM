# Contributing

Contributions are welcome under the Apache License 2.0. By submitting a pull request you agree that your
contribution is licensed under the same terms (Apache-2.0, section 5). Please add your name to `AUTHORS`.

Do not submit code copied from GPL projects or third-party binaries.
Keep third-party libraries out of the repository (`vendor/` is git-ignored).

Conventions: names and labels visible in Houdini are in English; code comments may be in Russian.
All logic lives in `python3.13libs/h3dm/`; the HDAs are thin wrappers rebuilt with **H3DM › Rebuild HDAs**.

## Development layout

Develop in the git checkout and install a copy for Houdini:

```bash
python deploy.py                 # copies changed files to ~/tools_houdini/H3DM (or pass another folder)
python deploy.py --clean         # also removes files that no longer exist in the checkout
```

`packages/H3DM.json` points `H3DM` to the installed copy. After changing the node interface, rebuild the HDAs
into the checkout (`h3dm.hda_build.build_all(otls="<checkout>/otls")`) and deploy again.

The banner `docs/h3dm_banner.png` stays in both READMEs right after the title — keep it when editing them
(`tests/test_repo.py` checks it).

## Asset versions and releases

Development happens in `python3.13libs/h3dm/` with the asset version `HDA_VERSION` from `h3dm/__init__.py`
(see README, *Asset versions*). Released versions are frozen and never edited:

```bash
python freeze.py 4.0             # h3dm -> h3dm_4_0 (module references rewritten, own Rhino scripts)
# in Houdini, once:  import h3dm_4_0.hda_build as b; b.build_all(force=True)
#                    -> otls/h3dm_3dm_import_4.0.hda, otls/h3dm_3dm_export_4.0.hda
python freeze.py --seal 4.0      # checksums -> h3dm_4_0/FROZEN.sha256
# then raise HDA_VERSION in h3dm/__init__.py (5.0, or 4.1 for a behaviour-changing fix) and rebuild its HDAs
python tests/test_frozen.py      # frozen versions unchanged, current version above all of them
```

A fix that must reach scenes already made with a released version is a new asset version, never an edit of the
frozen copy.

**Dependencies.** `RHINO3DM_TESTED` / `HOUDINI_TESTED` in `h3dm/__init__.py` say what the current version was tested
with; `VERSIONS.json` keeps that for every asset version (`freeze.py --seal` records it; `tests/test_frozen.py`
checks it). The install menu installs exactly `RHINO3DM_TESTED`, and nodes warn about another version. To move to a
new rhino3dm: install it, run the whole Houdini regression (it cooks every installed asset version), then raise
`RHINO3DM_TESTED` and add `"also_tested": ["<version>"]` to the frozen entries that passed.

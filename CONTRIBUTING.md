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

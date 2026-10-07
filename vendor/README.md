# vendor/

rhino3dm is installed here per platform, e.g.
`vendor/py313-macos-arm64/`, `vendor/py313-win-x64/`, `vendor/py313-linux-x64/`.

Install from Houdini: **H3DM › Install / Update rhino3dm** — it installs the rhino3dm version this H3DM was tested
with (`RHINO3DM_TESTED` in `python3.13libs/h3dm/__init__.py`; per asset version in `../VERSIONS.json`).

Or manually (Houdini 22 uses Python 3.13; pick the folder name for your platform; H3DM 0.4 / assets 4.0 —
`rhino3dm==8.35.0`):

```bash
# macOS (Apple Silicon or Intel; wheels need macOS 14+)
pip install --target vendor/py313-macos-arm64 --platform macosx_14_0_universal2 \
    --python-version 3.13 --only-binary=:all: --implementation cp --no-deps rhino3dm==8.35.0
# Windows x64
pip install --target vendor/py313-win-x64 --platform win_amd64 \
    --python-version 3.13 --only-binary=:all: --implementation cp --no-deps rhino3dm==8.35.0
# Linux x64
pip install --target vendor/py313-linux-x64 --platform manylinux_2_28_x86_64 \
    --python-version 3.13 --only-binary=:all: --implementation cp --no-deps rhino3dm==8.35.0
```

Everything in this folder is third-party software under its own licence
(see `../THIRD_PARTY_NOTICES.md`). It is excluded from git.

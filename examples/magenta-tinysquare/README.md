# magenta-tinysquare-test — the visible unsigned-`*_P` test

The visible test for whether the game accepts an unsigned `*_P` container:
`T_TinySquare`, a 2×2 white UI texture, recoloured magenta. If the game
boots with this pack installed and the texture shows magenta, unsigned
`*_P` containers are accepted on that setup. It proves nothing about
gameplay mods until that launch test passes.

**No game files ship in this repo.** Recreate the pack from your own
extracted originals:

```bash
# 1. Extract the original asset (needs your AES key — see the repo README)
python3 ../mf_patch.py extract \
  MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uasset \
  -o /tmp/tinysquare/T_TinySquare.uasset

# 2. Convert it to legacy form
python3 ../mf_patch.py to-legacy T_TinySquare -o /tmp/tinysquare-legacy

# 3. Recolour the 2x2 texture magenta in the legacy files
#    (the PoC's modified files differ from the originals in exactly the
#    texture payload; `verify` prints the read-back hash, which should
#    start 0d6e8874… — the Oct 24 PoC magenta hash)

# 4. Stage the edited legacy files at their exact game paths
mkdir -p my-magenta/files/MaximumFootball/Content/MaximumFootball/UI/Textures/Common
cp /tmp/tinysquare-legacy/.../T_TinySquare.uasset \
   /tmp/tinysquare-legacy/.../T_TinySquare.uexp \
   my-magenta/files/MaximumFootball/Content/MaximumFootball/UI/Textures/Common/
cp manifest.json my-magenta/manifest.json

# 5. Build, verify, install
python3 ../mf_patch.py build my-magenta -o my-magenta/built
python3 ../mf_patch.py verify my-magenta/built
python3 ../mf_patch.py install my-magenta/built \
  --target <game>/MaximumFootball/Content/Paks
```

Then launch the game **offline** on your play setup and confirm it boots
with the `*_P` present. If it crashes or rejects the patch, run
`uninstall` — the shipped containers were never touched, so removal
restores stock.

`manifest.json` (this folder) is the pack manifest for the mod:

```json
{"name": "magenta-tinysquare-test", "version": "1.0",
 "description": "Visible test patch: T_TinySquare (2x2 white UI texture) recoloured magenta. Built from the Oct 24 2026 overnight PoC modified legacy files. Use ONLY to test whether the game accepts an unsigned *_P container — it proves nothing about gameplay mods until that launch test passes."}
```

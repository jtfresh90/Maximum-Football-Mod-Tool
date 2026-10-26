# mfmod — sandbox test log

## Oct 26, 2026 run (this repo, after the publication refactor)

**Date:** Oct 26, 2026 (~13:20–13:30 EDT)
**Tester:** subagent build run (automated)
**Sandbox:** `/tmp/mfmod-pub-test/` — a copy of the shipping exe (167 MB,
copied, not symlinked, so `exe apply` writes only the sandbox copy) plus a
minimal `MaximumFootball/Content/Paks/` containing **symlinks** to the real
containers (read-only use, same pattern as the Oct 25 tests). All other
test outputs in `/tmp/mfmod-pub-out/` (ephemeral).
**Environment for the run** (all tool locations via env vars — the point of
the refactor; no author-workspace default was relied on):

```bash
export MF_GAME_DIR=/tmp/mfmod-pub-test
export MF_RETOC=<retoc 0.1.5 binary>
export MF_MFTOOL=<MFTool binary>
export MF_DOTNET_ROOT=<.NET SDK dir>
export MF_AES_KEY_FILE=<local AES key report>   # key never printed; see below
```

**Real install:** verified untouched at the end (exe sha256 still the
original `fe19cd1f…`; 0 `*_P` files in the real Paks folder; no `.bak`
files in the real Binaries/Win64 folder).

**Note on hashes in this log:** only the two public exe hashes are written
in full here. All other hashes are shown as 16-char prefixes; the full
values live in the sandbox `build.json` / `bulk_build.json` files under
`/tmp/mfmod-pub-out/` (ephemeral, not in this repo).

## Results table

| # | Command | Expected | Result |
| - | ------- | -------- | ------ |
| 1 | `mfmod.py --help` / `mf_patch.py --help` / `bulk --help` | usage text, bulk subcommands listed | **PASS** |
| 2 | `mfmod.py doctor` (sandbox) | all OK except .usmap MISS; AES source = MF_AES_KEY_FILE | **PASS** |
| 3 | `mfmod.py status` (sandbox) | T4 READY, T1/T2/T3/T5 BLOCKED, `.usmap present: NO`, exe original | **PASS** |
| 4 | `mfmod.py list stadiums` | 36 pairs | **PASS** |
| 5 | `mfmod.py list rosters` | 186 tables | **PASS** |
| 6 | `mfmod.py list logos` | 3 decals + MF_LogoProjection note | **PASS** |
| 7 | `mfmod.py mods list` | both bundled mods; magenta marked "no pre-built container ships" | **PASS** |
| 8 | `mfmod.py exe verify` (sandbox, before apply) | original, 3 sites all `original` | **PASS** |
| 9 | `mfmod.py exe apply` (sandbox) | patched sha `cee7a2f7…`, 9 bytes differ | **PASS** |
| 10 | `cmp -l` sandbox exe vs real original | exactly 9 differing bytes, same size | **PASS** |
| 11 | patched sandbox exe vs known patched exe | byte-identical (`cmp` silent) | **PASS** |
| 12 | `mfmod.py exe verify` (sandbox, after apply) | patched, 3 sites all `patched` | **PASS** |
| 13 | `mfmod.py exe apply` again | no-op, already patched | **PASS** |
| 14 | `mfmod.py exe restore` (sandbox) | original sha restored | **PASS** |
| 15 | `mfmod.py exe verify` (sandbox, after restore) | original | **PASS** |
| 16 | `mfmod.py pak build` magenta (via wrapper, files staged in /tmp only) | exit 0, utoc sha `0eee432f…` = pre-built example | **PASS** |
| 17 | `mfmod.py pak verify` magenta build (via wrapper) | exit 0, read-back hash `0d6e8874…` = PoC magenta hash | **PASS** |
| 18 | `mfmod.py pak status` sandbox Paks | no `*_P` installed | **PASS** |
| 19 | `mfmod.py pak install` → `pak status` | PATCH INSTALLED (515/609/347 B) | **PASS** |
| 20 | `mfmod.py pak uninstall` → `pak status` | back to stock, no `*_P` | **PASS** |
| 21 | `mf_patch.py to-legacy T_NoiseShape` | Extracted 2 (0 failed) — Oodle works | **PASS** |
| 22 | `mf_patch.py to-legacy T_Sky_Blue` | Extracted 1 (0 failed) | **PASS** |
| 23 | `mf_patch.py bulk list-chunks pakchunk0 --filter T_NoiseShape` | 4 chunks (T_NoiseShape + T_NoiseShape64, uasset + ubulk) | **PASS** |
| 24 | `mfmod.py pak bulk list-chunks ... --filter T_NoiseShape` (wrapper) | same 4 chunks | **PASS** |
| 25 | `mf_patch.py bulk unpack-raw` magenta container | 2 chunks + manifest.json | **PASS** (after bug fix — see below) |
| 26 | `mf_patch.py bulk pack-raw` unpacked dir | verify passes; list shows same 2 chunks | **PASS** |
| 27 | `mf_patch.py bulk pack-raw` single modified `.ubulk` chunk | .ucas sha = modified hash `1463f916…` (== Oct 25 report) | **PASS** |
| 28 | MFTool raw read-back, staging dir + noise patch | returns modified bytes `1463f916…`, NOT original `625a751c…` | **PASS** |
| 29 | `mf_patch.py install` bulk (no-.pak) container → `uninstall` | installs .utoc+.ucas only; uninstall removes both | **PASS** |
| 30 | AES precedence unit check (import, no values printed) | env wins over file; file fallback works; invalid env refused (exit 1); source labels only | **PASS** |
| 31 | `mfmod.py status` with no game configured | prints table, `.usmap present: NO`, exit 0 | **PASS** |
| 32 | `mfmod.py doctor` / `exe verify` with no game configured | clean error naming `--game` / `MF_GAME_DIR`, exit 1 | **PASS** |

## Bug found during testing (fixed, then re-tested)

**`bulk unpack-raw` failed on a fresh output dir.** The first version of
`cmd_bulk_unpack_raw` pre-created the output directory with
`mkdir(parents=True, exist_ok=True)`; retoc refuses to unpack into an
existing directory (`Error: failed to create directory ...: File exists
(os error 17)`), so the command failed and the follow-on `pack-raw`
correctly refused (no manifest.json). **Fix:** `cmd_bulk_unpack_raw`
now only creates the output directory's *parent* and lets retoc create
the directory itself; it refuses only when the target already exists and
is non-empty. Re-ran #25–#26 after the fix — both pass, and the
round-trip `pack-raw` rebuild verifies and lists the same 2 chunks.

## Key verbatim outputs

### 2. `doctor` (sandbox)

```
Game dir: /tmp/mfmod-pub-test
  [OK  ] game folder exists
  [OK  ] shipping exe present — 174789704 bytes, sha256 fe19cd1f7c255673…, state=original
  [OK  ] Paks folder present
  [OK  ] pakchunk0-Windows.utoc present
  [OK  ] retoc present — <retoc 0.1.5 binary>
  [OK  ] MFTool present — <MFTool binary>
  [OK  ] mf-patch tool present (bundled)
  [OK  ] AES key source present (key never printed) — MF_AES_KEY_FILE=<local key report>
  [MISS] .usmap — none found under the game dir, this repo's dir, or MF_USMAP_DIR
        T1/T2/T3/T5 stay BLOCKED until one is produced from a Windows run (Dumper-7/UE4SS, or a full-memory minidump).
doctor: some checks missing — see above (the .usmap is the expected miss)
```

### 9–11. `exe apply`, byte-diff, byte-identical check

```
Backed up original exe -> MaximumFootball-Win64-Shipping.exe.20261026T132619Z.bak (sha256 fe19cd1f7c255673…)
Patched exe sha256: cee7a2f78513b727c7078fff06085c1dee466a1ae3e7f05eef1ca917b1edd119
Bytes differing from the backed-up original: 9 (expected 9 across 3 sites)
Patched and verified: tier=100 + status PremiumActive. Claimed arrays are NOT forced (see README).

$ cmp -l <real original> <sandbox patched> | wc -l
9
$ sha256sum <sandbox patched> <known patched exe>
cee7a2f78513b727c7078fff06085c1dee466a1ae3e7f05eef1ca917b1edd119  <sandbox patched>
cee7a2f78513b727c7078fff06085c1dee466a1ae3e7f05eef1ca917b1edd119  <known patched exe>
BYTE-IDENTICAL-TO-KNOWN-PATCHED
```

### 16–17. `pak build` + `pak verify` (magenta, via wrapper)

The magenta pack was built from the original example files staged in
`/tmp/mfmod-pub-out/magenta-src/` — **no game files were copied into
this repo** to make the test pass.

```
mfmod: delegating to mf-patch: build /tmp/mfmod-pub-out/magenta-src -o /tmp/mfmod-pub-out/magenta-built
Building patch for mod 'magenta-tinysquare-test' v1.0
  files: 2 staged file(s)
Built: /tmp/mfmod-pub-out/magenta-built/pakchunk999-Mods_P.utoc (+ .ucas, .pak)
  utoc sha256: 0eee432f100f857b…
  ucas sha256: f561fdf4664b376c…
```

(The utoc sha matches the Oct 25 pre-built example — the build is
reproducible through the refactored wrapper.)

```
  mount check: patch container mounts alongside the originals
  read-back OK: MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uasset (529 bytes, sha256 0d6e8874e47099b…)
Verify done. Note: this proves build + mount-in-tools only — the in-game acceptance test is still required (see README).
```

The read-back hash `0d6e8874…` is exactly the Oct 24 overnight PoC
magenta hash.

### 23–24. `bulk list-chunks` (pakchunk0, filter T_NoiseShape)

```
pakchunk0-Windows  0ac644b551c2fa6600000002 BulkData        86016  ../../../Engine/Content/EngineSky/VolumetricClouds/T_NoiseShape.ubulk
pakchunk0-Windows  0ac644b551c2fa6600000001 ExportBundleData 3220  ../../../Engine/Content/EngineSky/VolumetricClouds/T_NoiseShape.uasset
pakchunk0-Windows  a996adcfa357ed2d00000001 ExportBundleData 2104  ../../../Engine/Content/EngineSky/VolumetricClouds/T_NoiseShape64.uasset
pakchunk0-Windows  a996adcfa357ed2d00000002 BulkData       174080  ../../../Engine/Content/EngineSky/VolumetricClouds/T_NoiseShape64.ubulk
```

### 27–28. Single modified `.ubulk` chunk (transport test — NOT a mod)

The `.ubulk` was extracted with `mf_patch.py extract` into `/tmp` only,
its first 16 bytes replaced with `deadbeefcafebabe0123456789abcdef`
(modified sha `1463f916…`), packed alone with `bulk pack-raw`:

```
Built (pack-raw): /tmp/mfmod-pub-out/stage-noise/pakchunk999-NoiseTest_P.utoc
  .utoc: 422 bytes, sha256 d2a3448da91468be…
  .ucas: 86016 bytes, sha256 1463f91638f46432…
```

MFTool read-back from a staging dir (symlinked real Paks + the noise
patch) returned the **modified** bytes:

```
wrote /tmp/mfmod-pub-out/readback-mod.ubulk (86016 bytes) from Engine/Content/EngineSky/VolumetricClouds/T_NoiseShape.ubulk
1463f91638f46432…  /tmp/mfmod-pub-out/readback-mod.ubulk
```

Original would have been `625a751c…` — the patch wins for that chunk in
tooling. The marker-byte container was uninstalled and deleted after the
test; it is not in this repo.

## Oct 25, 2026 run (carried over, pre-refactor)

The previous tool version passed all 22 sandbox checks on Oct 25, 2026
(doctor/status/lists/mods, exe verify/apply/re-apply/restore, pak
build/verify/install/uninstall — see the Oct 25 log in the author's
working copy). The Oct 26 run above re-runs that full suite against the
refactored, portable code (checks #1–#22 cover the same ground, plus
#23–#32 for the new bulk lane, AES precedence, and no-game behaviour).
The one bug found Oct 25 (`.usmap` false positive from searching the
CUE4Parse tree) stays fixed: `find_usmap()` searches only the game dir,
this repo's dir, and `MF_USMAP_DIR`.

## Not tested (cannot be tested in this VM)

- In-game acceptance of the patched exe or of an unsigned `*_P` (either
  the to-zen magenta pack or a pack-raw bulk container) — needs the play
  setup. The magenta launch test and the exe test remain the acceptance
  gates.
- A *meaningful* pixel edit of a real bulk texture (field/stadium art) —
  the bulk lane's transport is verified, but no real texture has been
  edited yet; that is T2 follow-up work, not part of this tool.
- `exe apply` refusal path on an unknown exe hash (would need a
  deliberately corrupted exe; the guard is the same byte-check logic
  already exercised by the verified apply/restore cycle, and the refusal
  branch is code-reviewed, not run).
- `exe restore --backup <explicit file>` (the default latest-backup path
  was tested and works).
- The `.usmap`-gated commands (T1/T2/T3/T5) — no `.usmap` exists, so
  there is nothing to test them against; `doctor`/`status` correctly
  report the gate.

## Cleanup

Sandbox `/tmp/mfmod-pub-test/` and outputs `/tmp/mfmod-pub-out/` are
ephemeral `/tmp` and were left for inspection. The real game install was
never written to: final check showed the real exe still at the original
sha256, 0 `*_P` files in the real Paks folder, and no `.bak` files in
the real Binaries/Win64 folder. The sandbox exe was restored to the
original (its timestamped `.bak` lives in the sandbox only).

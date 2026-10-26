# mfmod — Maximum Football modding tool

One entry point for modding **Maximum Football** (free on Steam, app 1691280,
Unreal Engine 5.3, no longer supported by the publisher). It unifies the two
mod lanes that exist today — the **exe patch** (Season Pass equipment unlock)
and the **pak overrides** (texture/asset mods) — plus an experimental
**bulk lane** for single-chunk `.ubulk` overrides, honest per-target status,
and the verified registries recovered from the game files.

Python 3, standard library only. No install step, no bundled game files,
no game binaries, no AES key in this repo.

## What it is — and what it is not

- It **is** the tool for the two lanes that have actually been built and
  byte-verified in tooling: the T4 exe patch and the unsigned `*_P` pak
  pipeline (plus the experimental bulk lane).
- It **is not** a magic unlocker for the other four targets. T1/T2/T3/T5 are
  hard-blocked on a `.usmap` (see "Per-target status" below), and this tool
  says so on every run rather than pretending otherwise. It invents no patch
  points and fakes no `.usmap`.

## Quick start

```bash
# 1. Point the tool at your game install (or set MF_GAME_DIR once)
export MF_GAME_DIR="/path/to/Steam/steamapps/common/Maximum Football"

# 2. Check the setup (game layout, exe state, tools, .usmap, AES key source)
python3 mfmod.py doctor

# 3. See which targets are actually doable right now
python3 mfmod.py status

# 4. See the bundled mods
python3 mfmod.py mods list
```

`--game <dir>` works on every subcommand that needs the game, and overrides
`MF_GAME_DIR`. If neither is given, the tool looks in the usual Steam
library locations (`~/.local/share/Steam/...`, `~/.steam/...`,
`C:\Program Files (x86)\Steam\...`).

## Requirements

- **The game** — Maximum Football, Steam app 1691280 (UE 5.3). Point the
  tool at it with `--game` / `MF_GAME_DIR`.
- **retoc v0.1.5** — for the pak lane (`build`, `to-legacy`, `bulk`).
  Get it from the [retoc releases](https://github.com/trumank/retoc/releases).
  The tool finds it via `MF_RETOC`, then `PATH`, then
  `<repo>/tools/retoc/retoc_cli-x86_64-unknown-linux-gnu/retoc`.
- **MFTool (CUE4Parse CLI)** — for `verify` mount/read-back checks and
  `extract`. The tool finds it via `MF_MFTOOL`, then `PATH`, then
  `<repo>/tools/cue4parse/MFTool/bin/Release/net10.0/MFTool`. It needs a
  .NET runtime; set `MF_DOTNET_ROOT` / `DOTNET_ROOT` if yours is not on
  `PATH`.
- **Oodle library (for `.ubulk` textures only)** — `retoc to-legacy`
  converts `.ubulk` textures only when `liboo2corelinux64.so.9` sits
  **next to the retoc binary**. Get it from the public
  [WorkingRobot/OodleUE](https://github.com/WorkingRobot/OodleUE) repo
  (the `liboo2corelinux64.so.9` file); the expected sha256 is
  `ed7e98f70be1254a80644efd3ae442ff61f854a2fe9debb0b978b95289884e9c`
  — the same hash embedded in the retoc binary, which is how retoc
  authenticates it. The library is **not** bundled in this repo. Without
  it, `to-legacy` extracts 0 assets from `.ubulk` textures; with it,
  verified Oct 25 2026: T_NoiseShape 2/2, T_Sky_Blue 1/1,
  T_Default_Normal 1/1.
- **A `.usmap`** — only for T1/T2/T3/T5 data-level editing (see below).
  Not needed for the exe lane or the pak lane.

### Environment variables

| Variable | What it does |
| --- | --- |
| `MF_GAME_DIR` | Game install dir (Steam `Maximum Football` folder) |
| `MF_GAME_PAKS` | `Content/Paks` dir directly (overrides `MF_GAME_DIR`) |
| `MF_RETOC` | Path to the `retoc` binary |
| `MF_MFTOOL` | Path to the `MFTool` binary |
| `MF_DOTNET_ROOT` / `DOTNET_ROOT` | .NET runtime root for MFTool |
| `MF_AES_KEY` | AES key, `0x` + 64 hex chars (see below) |
| `MF_AES_KEY_FILE` | File containing the AES key |
| `MF_USMAP_DIR` | Extra dir to search for a `.usmap` |

## The AES key — yours, not ours

The game's IoStore containers are encrypted, so the pak lane needs the
AES key to read the originals (retoc/MFTool take it as an argument or
env var). **This repo contains no key and no key file.** Supply your own:

1. **Obtain it from your own copy of the game.** The key is recoverable
   from your own game binary (`MaximumFootball-Win64-Shipping.exe`) with
   standard Unreal AES-key recovery — a static scan of the binary for the
   key slot, verified against the containers with CUE4Parse's key test.
   Use only your own copy of the game; do **not** fetch a key from
   third-party key-sharing sites.
2. **Enter it** one of two ways (never paste it into a file in this repo):
   ```bash
   export MF_AES_KEY=0x<64 hex characters>        # in your shell only
   # or
   export MF_AES_KEY_FILE=~/.config/mfmod/aes_key.txt
   ```
   The key is never printed, logged, or written into any output file by
   this tool — commands that carry it are masked in the tool's own
   `  $ ...` echo. `mfmod.py doctor` reports only *which source* the key
   would come from, never the value.

Some commands need no key at all (`bulk pack-raw`, `exe verify/apply/
restore`, `doctor`, `status`, `list`, `mods list`).

## Exe lane — T4, unlock all Season Pass equipment

The patch is **9 bytes across 3 sites** in the BattlePass data loader
(`0x144e832af`) of `MaximumFootball-Win64-Shipping.exe`: the cached tier
is forced to 100 and the status string forced to `"PremiumActive"`.

```bash
# Check the exe: original / patched / unknown, with all 3 sites listed
python3 mfmod.py exe verify --game <game dir>

# Patch it (backs the original up first; refuses to write unless the
# bytes at all 3 sites match the known original)
python3 mfmod.py exe apply --game <game dir>

# Put the original back (from the timestamped .bak next to the exe)
python3 mfmod.py exe restore --game <game dir>
# ...or from a specific backup:
python3 mfmod.py exe restore --game <game dir> --backup <file>.bak
```

Known hashes (the tool checks these, it does not trust file size alone):

| exe | sha256 |
| --- | --- |
| Original | `fe19cd1f7c255673a62f7889c5824d9c67e1994659bbde6fa44202e619e7f03f` |
| Patched  | `cee7a2f78513b727c7078fff06085c1dee466a1ae3e7f05eef1ca917b1edd119` |

Note: the original patch manifest says `"bytes_changed": 18` — that is the
total length of the three patch sites, not the number of differing bytes.
The true count is **9** (`cmp -l` verified; the tool reports 9 after apply).

## Pak lane — texture / asset overrides

A thin wrapper around the bundled `mf_patch.py` (same repo, no other
dependency). A mod pack is a directory with `manifest.json` plus a
`files/` tree of edited legacy files at their **exact** game paths:

```
my-mod/
  manifest.json            # {"name": ..., "version": ..., "description": ...}
  files/
    MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uasset
    MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uexp
```

```bash
# Build a mod pack into an unsigned *_P container
python3 mfmod.py pak build <mod_dir> -o <out_dir>

# Verify a built pack (retoc verify + mount + read-back against the real containers)
python3 mfmod.py pak verify <built_dir>

# Install / remove / check a pack in a Paks folder
python3 mfmod.py pak install <built_dir> --target <game>/MaximumFootball/Content/Paks
python3 mfmod.py pak uninstall --target <game>/MaximumFootball/Content/Paks
python3 mfmod.py pak status --target <game>/MaximumFootball/Content/Paks

# Research helpers (need the AES key for the originals)
python3 mfmod.py pak extract <game_path> -o <out>
python3 mfmod.py pak to-legacy <filter> -o <out_dir>
```

A patch container sits **next to** the game's own containers and only
overrides the exact paths it carries. It never modifies
pakchunk0/1/optional. Removing it restores stock.

The bundled example is the magenta-T_TinySquare test pack — a 2×2 UI
texture recoloured magenta, the visible test for whether the game accepts
an unsigned `*_P`. **No pre-built container ships in this repo** (game-
derived binaries are never committed). Recreate it from your own extracted
originals; see `examples/magenta-tinysquare/README.md`.

## Bulk lane — experimental single-chunk `.ubulk` overrides

`mf_patch.py bulk ...` (also via `mfmod.py pak bulk ...`) wraps retoc's
raw-chunk commands. It exists because bulk-data textures used to be
unreachable: `to-legacy` failed on them before the Oodle library was
installed, and even now a full conversion is heavyweight for a one-chunk
change. The bulk lane skips conversion entirely.

```bash
# List the chunks in a container (with their game paths and sizes)
python3 mf_patch.py bulk list-chunks <game>/MaximumFootball/Content/Paks/pakchunk0-Windows.utoc --filter T_NoiseShape

# Unpack a container's raw chunks (manifest.json + chunks/<chunk-id>)
python3 mf_patch.py bulk unpack-raw <container>.utoc -o /tmp/chunks

# Edit ONE chunk file in chunks/, then pack just that dir back into a _P
python3 mf_patch.py bulk pack-raw /tmp/chunks -o /tmp/pakchunk999-Noise_P.utoc

# Then verify / install it like any other pack
python3 mf_patch.py verify /tmp/pakchunk999-Noise_P.utoc
python3 mf_patch.py install /tmp --target <game>/MaximumFootball/Content/Paks
```

Verified Oct 25 2026, in tooling: a `_P` holding **only** a modified
`.ubulk` chunk (T_NoiseShape, chunk `0ac644b551c2fa6600000002`, first 16
bytes changed) overrides pakchunk0 for that chunk — CUE4Parse read-back
from a mounted staging dir returned the modified bytes, not the originals.
`pack-raw` produces `.utoc` + `.ucas` only (no `.pak`); `install`
accepts that. **In-game acceptance is unproven** — same honesty box as
the rest of the pak lane. Do not ship a marker-byte test as a mod; use
this only for real bulk edits (e.g. a field/stadium texture, once its
format is read from its legacy `.uasset`).

## Research lists (read-only)

These print registries recovered from the game files on Oct 23–24, 2026.
They are data, not mods — no `.usmap` pretending.

```bash
python3 mfmod.py list stadiums   # 36 DA_Stadiums name <-> STADIUM-ID pairs
python3 mfmod.py list rosters    # 186 DT_RosterTeamData_* tables
python3 mfmod.py list logos      # 3 UniformPartSymbols decals + MF_LogoProjection note
```

The underlying data lives in `targets/` (`stadiums.json`, `rosters.json`,
`logos.json`, `targets.json`). The roster census is **186** tables
(178 under `GameFramework/DataTables/Rosters/` + 8 under
`GameFramework/DataTables/`), not 181 as earlier notes said.

## Per-target status

Run `mfmod.py status` any time for the current table. As of Oct 26, 2026:

| ID | Target | Status | Gate |
| -- | ------ | ------ | ---- |
| T1 | Custom teams in Exhibition | **BLOCKED** | `.usmap` |
| T2 | In-depth stadium editing (fields, configs, custom models, surface art) | **BLOCKED** | `.usmap` (data edits only) |
| T3 | In-depth editing of DEFAULT teams | **BLOCKED** | `.usmap` |
| T4 | Unlock all Season Pass equipment | **READY** (pending in-game test) | in-game test only |
| T5 | FREE LOGO PLACEMENT on equipment (any piece, any size, any position) | **BLOCKED** | `.usmap` |

- **T1:** the Exhibition panel is not stripped and mentions no custom teams
  at all (verified negative). The gate lives in the HUB/team-data objects
  (e.g. `WBP_Team_Select_Team_Data`). Dumping those needs a `.usmap`.
- **T2:** registry recovered (36 stadiums, grass/seat colour axes). Data-
  level edits need a `.usmap`. Field surface art is **no longer** blocked
  on `.ubulk`: the Oodle library closes that gap (see Requirements), and
  the bulk lane covers single-chunk overrides — a real visible texture
  edit is the next step, gated on the in-game unsigned-`*_P` test.
- **T3:** 186 `DT_RosterTeamData_*` tables are real player data (plaintext
  names, ~87 players/team), but row/field names and attribute boundaries
  are unrecoverable without a `.usmap`. Raw binary row editing is not sane.
- **T4:** exe patch built Oct 24, 2026 (9 bytes, 3 sites). See "Exe lane".
- **T5:** `DA_CustomizationUniformPartSymbols` holds only 3 decals, no
  slot/UV data. The constraint is in the class/struct definition or
  materials/UI (`MF_LogoProjection`) — needs a `.usmap` to read.

## Safety rules

- **Backups first.** `exe apply` copies the original exe to
  `<name>.<UTC timestamp>.bak` next to it before writing anything, and
  verifies the patched exe (bytes + sha256) after the write; if
  verification fails it restores the backup and exits non-zero.
- **Refuse on mismatch.** `exe apply` writes nothing unless the exe's
  bytes match the known original at all 3 patch sites (or it is already
  patched, in which case it is a no-op). An unknown exe hash aborts
  unless `--force` is given — and even then the 3 sites must still match
  the original bytes.
- **Pak installs only ever add/remove `*_P` files.** They never touch
  `pakchunk0`/`pakchunk1`/`optional`. Replacing an existing `*_P` backs it
  up first.
- **The real install is never written to by `doctor`, `status`, `list`,
  `mods list`, `exe verify`, or `pak verify`.**
- **The AES key value is never printed, logged, or written to any output.**

## Honest limits — read before trusting any of this in-game

1. **Unsigned `*_P` acceptance is unproven in-game.** The pak lane proves
   build + mount-in-tools only. Whether the game (especially on an
   iPhone/Madeira/BCD/Playport setup) boots with an unsigned `*_P` is
   settled by the ~2-minute magenta launch test on the play setup.
2. **The exe patch is byte-verified, not game-verified.** Whether the play
   setup accepts a modified exe — or verifies/re-downloads it — is
   settled only by an in-game test (launch online, check Customization +
   the BattlePass screen).
3. **Claimed arrays are NOT forced** by the exe patch (`+0x560`/`+0x570`).
   If items show as claimable rather than unlocked, that is the next step
   (code-cave fill), and PlayFab server-side claim validation may still
   reject claims.
4. **The `.usmap` is a hard gate** for T1/T2/T3/T5. It can only be produced
   from one Windows run of the game (Dumper-7/UE4SS, or a full-memory
   minidump — ~5 minutes). CUE4Parse's own test-fixture `.usmap` files do
   not count; `doctor` deliberately does not search the CUE4Parse tree.
5. **The `.ubulk` gap is closed at the tooling level** (Oodle library +
   bulk lane, both verified Oct 25 2026). What remains unproven is a
   *meaningful* pixel edit of a real bulk texture in-game, and the
   unsigned-`*_P` question above.
6. **Season Pass ownership lives in PlayFab (server-side).** A pak edit to
   the catalog cannot mint it; the exe patch works around the local
   cached copy instead.

## Files

```
mfmod.py                    # single entry point (stdlib Python only)
mf_patch.py                 # pak/bulk lane (bundled; mfmod forwards to it)
README.md                   # this file
TEST_LOG.md                 # sandbox test results, Oct 25 + Oct 26 2026
LICENSE                     # MIT
.gitignore
targets/
  targets.json              # per-target status / gate / unblocks (T1–T5)
  stadiums.json             # 36 DA_Stadiums name <-> ID pairs
  rosters.json              # 186 DT_RosterTeamData_* tables
  logos.json                # 3 UniformPartSymbols decals + MF_LogoProjection note
examples/
  magenta-tinysquare/
    manifest.json           # the magenta test pack's manifest (no binaries)
    README.md               # how to recreate it from your own game files
```

## History

- **Oct 23, 2026** — texture `*_P` pipeline proven in tooling (magenta
  T_TinySquare PoC); registries recovered; `.usmap` verdict.
- **Oct 24, 2026** — mf-patch tool built; T4 exe patch built (9 bytes,
  3 sites).
- **Oct 25, 2026** — mfmod unified tool built (22 sandbox checks pass);
  `.ubulk` gap closed (Oodle library + retoc `pack-raw` chunk surgery,
  transport verified in tooling).
- **Oct 26, 2026** — this repo prepared for publication: portable paths,
  bundled mf_patch.py, experimental bulk lane, stale `.ubulk` claims
  corrected, no game binaries or keys in the tree.

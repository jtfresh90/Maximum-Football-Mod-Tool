#!/usr/bin/env python3
"""
mfmod — unified Maximum Football (UE 5.3, Steam app 1691280) modding tool.

One entry point for both mod lanes plus honest per-target status:

  * exe lane (T4, Season Pass equipment unlock): apply / verify / restore
    a 9-byte patch in the BattlePass data loader of
    MaximumFootball-Win64-Shipping.exe. The patch is verified byte-for-byte
    before it is written, the original is backed up first, and `restore`
    puts the original back.
  * pak lane (texture / asset overrides): thin wrapper around the bundled
    mf_patch.py in this repo. mfmod does NOT reimplement it — it forwards
    the call and surfaces its output + exit code. The pak lane also has an
    experimental `bulk` lane (retoc pack-raw / unpack-raw) for single-chunk
    .ubulk overrides — see mf_patch.py and README.md.
  * research helpers: `list stadiums|rosters|logos` print the verified
    registries recovered from the game files (no .usmap pretending).
  * `doctor` / `status` / `mods list`: environment checks and the
    per-target readiness table. Blocked targets are reported BLOCKED with
    the exact gate named — never presented as working.

Safety rules baked in:
  * The real game install is never written to except by `exe apply` (which
    only replaces the exe, after a timestamped backup) and `pak install`
    (via mf-patch, which only adds/removes *_P files — never
    pakchunk0/1/optional).
  * `exe apply` refuses to write unless the exe's bytes match the known
    original at all 3 patch sites (or it is already patched, in which
    case it is a no-op). A hash/bytes mismatch aborts with no write.
  * The AES key is never printed, logged, or written into any output by
    this tool. The pak lane delegates key handling to mf-patch, which
    reads it from MF_AES_KEY, then MF_AES_KEY_FILE, then (local-only
    fallback) the author's recovery report — never from the repo.

Honest limits (do not over-claim):
  1. The exe patch is built + byte-verified only. Whether the game
     accepts a modified exe — especially on an iPhone/Madeira/BCD/Playport
     setup that may verify or re-download it — is settled only by a real
     in-game test on the play setup.
  2. The claimed arrays (+0x560/+0x570) are NOT forced by the exe patch.
     If items show as claimable rather than unlocked, that is the next
     step (code-cave fill), and PlayFab server-side claim validation may
     still reject claims.
  3. Unsigned *_P acceptance in-game is unproven (build + mount-in-tools
     only). retoc v0.1.5 `to-legacy` now converts .ubulk textures, since
     the Oodle library (liboo2corelinux64.so.9) was installed next to
     retoc on Oct 25 2026 (T_NoiseShape: Extracted 2, 0 failed; T_Sky_Blue
     and T_Default_Normal: 1 each, 0 failed). The Oodle library is NOT
     bundled in this repo — see README.md for where to get it.
     The experimental bulk lane (pack-raw) additionally lets a single
     modified .ubulk chunk override pakchunk0 without any to-legacy step;
     that transport is verified in tooling only, in-game acceptance is
     still unproven.
  4. Full asset editing (T1/T2/T3/T5) is hard-blocked on a .usmap, which
     can only be generated from one Windows run of the game.

Python 3, standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
REPO_DIR = TOOL_DIR
TARGETS_DIR = TOOL_DIR / "targets"

# The bundled pak tool lives in this repo, so the pak lane works from a
# plain checkout with no dependency on any other tool directory.
MF_PATCH = REPO_DIR / "mf_patch.py"
MAGENTA_EXAMPLE = REPO_DIR / "examples/magenta-tinysquare"

# Game location. Priority: --game, then MF_GAME_DIR, then the Steam
# library locations below. There is deliberately NO default pointing at
# any author's home directory — pass --game or set MF_GAME_DIR.
STEAM_GAME_CANDIDATES = [
    Path.home() / ".local/share/Steam/steamapps/common/Maximum Football",
    Path.home() / ".steam/steam/steamapps/common/Maximum Football",
    Path.home() / "snap/steam/common/.local/share/Steam/steamapps/common/Maximum Football",
    Path("C:/Program Files (x86)/Steam/steamapps/common/Maximum Football"),
    Path("C:/Program Files/Steam/steamapps/common/Maximum Football"),
]

# LOCAL-ONLY fallback for the AES key (see mf_patch.aes_key): the author's
# recovery report, if it happens to exist on this machine. It is not part
# of the repo and is never required — MF_AES_KEY / MF_AES_KEY_FILE win.
LEGACY_KEY_REPORT = (
    Path.home() / "workspace/recon/maximum-football"
    / "AES_KEY_RECOVERY_2026-10-23.md"
)


def discover_game_dir():
    env = os.environ.get("MF_GAME_DIR")
    if env:
        return Path(env)
    for cand in STEAM_GAME_CANDIDATES:
        if (cand / "MaximumFootball/Binaries/Win64"
                / "MaximumFootball-Win64-Shipping.exe").exists():
            return cand
    return None


def resolve_game(args, required=True):
    if getattr(args, "game", None):
        return Path(args.game)
    found = discover_game_dir()
    if found is not None:
        return found
    if not required:
        return None
    die("game install dir not found — pass --game <dir> or set MF_GAME_DIR "
        "(e.g. your Steam library's 'Maximum Football' folder)")

EXE_REL = Path("MaximumFootball/Binaries/Win64/MaximumFootball-Win64-Shipping.exe")
PAKS_REL = Path("MaximumFootball/Content/Paks")
EXE_SIZE = 174789704
ORIGINAL_SHA256 = "fe19cd1f7c255673a62f7889c5824d9c67e1994659bbde6fa44202e619e7f03f"
PATCHED_SHA256 = "cee7a2f78513b727c7078fff06085c1dee466a1ae3e7f05eef1ca917b1edd119"
IMAGE_BASE = 0x140000000

# The T4 exe patch. Three sites inside the BattlePass data loader
# (fn 0x144e832af). "bytes_changed" in the original patch manifest is 18 —
# that is the total length of the three patch sites; the number of bytes
# that actually DIFFER between original and patched is 9 (4 + 4 + 1), which
# is what this tool reports and verifies. Do not copy 18 into user text.
PATCH_SITES = [
    {"id": "P1-tier-100", "va": 0x144E83315,
     "orig": bytes.fromhex("f20f2cc0"), "new": bytes.fromhex("31c0b064"),
     "desc": "cvttsd2si eax,xmm0 -> xor eax,eax; mov al,0x64  (cached tier = 100)"},
    {"id": "P2a-status-string", "va": 0x144E8340C,
     "orig": bytes.fromhex("488d1545995d02"), "new": bytes.fromhex("488d15f527b503"),
     "desc": 'lea rdx,"Inactive" -> lea rdx,"PremiumActive"'},
    {"id": "P2b-status-dest", "va": 0x144E83422,
     "orig": bytes.fromhex("498d9e50050000"), "new": bytes.fromhex("498d9e30050000"),
     "desc": "lea rbx,[r14+0x550] -> lea rbx,[r14+0x530]  (status field)"},
]


def die(msg, code=1):
    print(f"mfmod: error: {msg}", file=sys.stderr)
    sys.exit(code)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- PE helpers

def pe_sections(exe_path):
    """Parse the PE section table (stdlib only). Returns list of dicts."""
    with open(exe_path, "rb") as f:
        data = f.read(4096)
    if data[:2] != b"MZ":
        die(f"{exe_path} is not a PE file (no MZ header)")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    with open(exe_path, "rb") as f:
        f.seek(e_lfanew)
        hdr = f.read(24 + 240)
    if hdr[:4] != b"PE\0\0":
        die(f"{exe_path} is not a PE file (no PE signature)")
    num_sections = struct.unpack_from("<H", hdr, 6)[0]
    opt_size = struct.unpack_from("<H", hdr, 20)[0]
    sect_off = e_lfanew + 24 + opt_size
    sections = []
    with open(exe_path, "rb") as f:
        f.seek(sect_off)
        raw = f.read(40 * num_sections)
    for i in range(num_sections):
        name = raw[i * 40:i * 40 + 8].rstrip(b"\0").decode("ascii", "replace")
        vs, va, rawsize, rawptr = struct.unpack_from("<IIII", raw, i * 40 + 8)
        sections.append({"name": name, "va": va, "vs": vs,
                         "raw": rawptr, "rawsize": rawsize})
    return sections


def va_to_off(va, sections):
    rva = va - IMAGE_BASE
    for s in sections:
        if s["va"] <= rva < s["va"] + max(s["vs"], s["rawsize"]):
            return s["raw"] + (rva - s["va"])
    raise ValueError(f"VA 0x{va:x} not in any PE section")


def find_exe(game_dir):
    game = Path(game_dir)
    exe = game / EXE_REL
    if exe.exists():
        return exe
    # Tolerate being handed Binaries/Win64 itself, or the exe directly.
    if game.is_file() and game.name == EXE_REL.name:
        return game
    if (game / EXE_REL.name).exists():
        return game / EXE_REL.name
    return exe  # caller reports the miss with this expected path


def exe_state(exe_path):
    """Return (state, data, sections): state in original/patched/unknown."""
    data = Path(exe_path).read_bytes()
    h = hashlib.sha256(data).hexdigest()
    if h == ORIGINAL_SHA256:
        state = "original"
    elif h == PATCHED_SHA256:
        state = "patched"
    else:
        state = "unknown"
    return state, data, h


def site_bytes(data, sections):
    """Per-site (id, va, file_off, actual_bytes, match) for the exe bytes."""
    out = []
    for p in PATCH_SITES:
        try:
            off = va_to_off(p["va"], sections)
        except ValueError:
            out.append((p, None, None, "VA not in any section"))
            continue
        actual = bytes(data[off:off + len(p["orig"])])
        if actual == p["orig"]:
            match = "original"
        elif actual == p["new"]:
            match = "patched"
        else:
            match = "MISMATCH"
        out.append((p, off, actual, match))
    return out


def count_differing(orig_data, new_data):
    return sum(1 for a, b in zip(orig_data, new_data) if a != b)


# ---------------------------------------------------------------- doctor

def find_retoc():
    env = os.environ.get("MF_RETOC")
    if env and Path(env).exists():
        return Path(env)
    which = shutil.which("retoc")
    if which:
        return Path(which)
    candidates = [
        REPO_DIR / "tools/retoc/retoc_cli-x86_64-unknown-linux-gnu/retoc",
        REPO_DIR / "tools/retoc/retoc",
        Path.home() / ".local/bin/retoc",
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return None


def find_mftool():
    env = os.environ.get("MF_MFTOOL")
    if env and Path(env).exists():
        return Path(env)
    which = shutil.which("MFTool")
    if which:
        return Path(which)
    candidates = [
        REPO_DIR / "tools/cue4parse/MFTool/bin/Release/net10.0/MFTool",
        Path.home() / ".local/bin/MFTool",
    ]
    for c in candidates:
        if c.exists() and os.access(c, os.X_OK):
            return c
    return None


def aes_key_source():
    """Label (never the value) for where the AES key would come from."""
    if os.environ.get("MF_AES_KEY"):
        return "MF_AES_KEY env var"
    if os.environ.get("MF_AES_KEY_FILE"):
        return f"MF_AES_KEY_FILE={os.environ['MF_AES_KEY_FILE']}"
    if LEGACY_KEY_REPORT.exists():
        return "local-only legacy key report (not in repo)"
    return None


def find_usmap(game_dir):
    """Search for a Maximum Football *.usmap where Joshua would put one.

    Roots are deliberately narrow: the game dir itself, this repo's dir,
    and MF_USMAP_DIR if set. A wider tools tree is NOT searched — it may
    contain CUE4Parse's own test-fixture .usmap files, which are not a
    Maximum Football mapping and must never count as "present".
    """
    roots = [Path(game_dir), TOOL_DIR]
    env_dir = os.environ.get("MF_USMAP_DIR")
    if env_dir:
        roots.append(Path(env_dir))
    found = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.usmap"):
            found.append(p)
            if len(found) >= 20:
                return found
    return found


def cmd_doctor(args):
    game = resolve_game(args)
    print(f"Game dir: {game}")
    ok = True

    def check(label, good, detail=""):
        nonlocal ok
        print(f"  [{'OK  ' if good else 'MISS'}] {label}" + (f" — {detail}" if detail else ""))
        if not good:
            ok = False

    check("game folder exists", game.is_dir(), str(game) if not game.is_dir() else "")
    exe = find_exe(game)
    if exe.exists():
        state, _, h = exe_state(exe)
        check("shipping exe present", True,
              f"{exe.stat().st_size} bytes, sha256 {h[:16]}…, state={state}")
        if state == "unknown":
            print("        NOTE: exe hash matches neither the known original nor the "
                  "known patched build — it may be a different game version.")
    else:
        check("shipping exe present", False, f"expected {exe}")
    paks = game / PAKS_REL
    check("Paks folder present", paks.is_dir())
    check("pakchunk0-Windows.utoc present",
          (paks / "pakchunk0-Windows.utoc").exists())
    retoc = find_retoc()
    check("retoc present", retoc is not None,
          str(retoc) if retoc else "set MF_RETOC or put retoc on PATH (see README)")
    mftool = find_mftool()
    check("MFTool present", mftool is not None,
          str(mftool) if mftool else "set MF_MFTOOL or put MFTool on PATH (see README)")
    check("mf-patch tool present (bundled)", MF_PATCH.exists())
    key_src = aes_key_source()
    check("AES key source present (key never printed)", key_src is not None,
          key_src if key_src else "set MF_AES_KEY or MF_AES_KEY_FILE (see README)")
    usmaps = find_usmap(game)
    if usmaps:
        for u in usmaps:
            print(f"  [OK  ] .usmap found: {u}")
    else:
        print("  [MISS] .usmap — none found under the game dir, this repo's dir, "
              "or MF_USMAP_DIR")
        print("        T1/T2/T3/T5 stay BLOCKED until one is produced from a "
              "Windows run (Dumper-7/UE4SS, or a full-memory minidump).")
        ok = False
    print("doctor: " + ("all checks passed" if ok else
                         "some checks missing — see above (the .usmap is the expected miss)"))
    return 0 if game.is_dir() else 1


# ---------------------------------------------------------------- status

def cmd_status(args):
    game = resolve_game(args, required=False)
    targets = load_json(TARGETS_DIR / "targets.json")["targets"]
    usmaps = find_usmap(game) if game is not None else []
    exe = find_exe(game) if game is not None else None
    exe_note = ""
    if exe is not None and exe.exists():
        state, _, _ = exe_state(exe)
        exe_note = f" (exe in this game dir is currently: {state})"
    print("Maximum Football mod targets — readiness (Oct 26 2026)")
    print(f".usmap present: {'yes' if usmaps else 'NO'}{exe_note}")
    print()
    print(f"{'ID':<4} {'Target':<62} {'Status':<28} Gate")
    print("-" * 120)
    for t in targets:
        print(f"{t['id']:<4} {t['name']:<62} {t['status']:<28} {t['gate']}")
    print()
    for t in targets:
        print(f"{t['id']} — {t['name']}")
        print(f"    Why: {t['why']}")
        print(f"    Unblocks: {t['unblocks']}")
    print()
    print("Honest summary: only T4 has a built patch, and it is still pending "
          "its in-game test. T1/T2/T3/T5 are BLOCKED on the .usmap "
          "(T2 surface art is no longer blocked on .ubulk since Oct 25 2026 "
          "— only its data-level edits still need the .usmap). Nothing here "
          "pretends otherwise.")
    return 0


# ---------------------------------------------------------------- exe lane

def cmd_exe_verify(args):
    game = resolve_game(args)
    exe = find_exe(game)
    if not exe.exists():
        die(f"exe not found — expected {exe}")
    state, data, h = exe_state(exe)
    print(f"Exe: {exe}")
    print(f"  size: {len(data)} bytes (expected {EXE_SIZE})")
    print(f"  sha256: {h}")
    print(f"  state: {state}")
    sections = pe_sections(exe)
    print("  patch sites (BattlePass loader 0x144e832af):")
    for p, off, actual, match in site_bytes(data, sections):
        if off is None:
            print(f"    {p['id']:<20} VA 0x{p['va']:x}: {match}")
            continue
        print(f"    {p['id']:<20} VA 0x{p['va']:x} file off 0x{off:x}")
        print(f"      expected original: {p['orig'].hex()}")
        print(f"      expected patched:  {p['new'].hex()}")
        print(f"      actual:            {actual.hex()}  -> {match}")
    if state == "patched":
        print("  -> patched exe (tier=100 + status PremiumActive). "
              "In-game behaviour still unproven — test on the play setup.")
    elif state == "original":
        print("  -> stock exe. Run `mfmod.py exe apply --game <dir>` to patch it.")
    else:
        print("  -> UNKNOWN exe: hash matches neither known build. Do not patch "
              "it — verify the game version first.")
    return 0


def cmd_exe_apply(args):
    game = resolve_game(args)
    exe = find_exe(game)
    if not exe.exists():
        die(f"exe not found — expected {exe}")
    state, data, h = exe_state(exe)
    if state == "patched":
        print("Exe is already patched (sha256 matches the known patched build). "
              "Nothing to do.")
        return 0
    if state == "unknown" and not args.force:
        die("exe hash matches neither the known original nor the known patched "
            "build — refusing to patch a different game version. "
            "Use --force only if you have verified the bytes yourself.")
    sections = pe_sections(exe)
    sites = site_bytes(data, sections)
    for p, off, actual, match in sites:
        if match != "original":
            die(f"site {p['id']} at VA 0x{p['va']:x}: expected original bytes "
                f"{p['orig'].hex()}, found {actual.hex() if actual else '?'} "
                f"({match}) — refusing to write anything.")
    # Backup first (timestamped, next to the exe).
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = exe.with_name(f"{exe.name}.{stamp}.bak")
    shutil.copy2(exe, backup)
    print(f"Backed up original exe -> {backup.name} (sha256 {h[:16]}…)")
    patched = bytearray(data)
    for p, off, _actual, _m in sites:
        patched[off:off + len(p["new"])] = p["new"]
    # Write via a temp file in the same directory, then atomic replace.
    tmp = exe.with_name(exe.name + ".mfmod-tmp")
    tmp.write_bytes(bytes(patched))
    os.replace(tmp, exe)
    # Verify after the write.
    new_state, new_data, new_h = exe_state(exe)
    n_diff = count_differing(data, new_data)
    print(f"Patched exe sha256: {new_h}")
    print(f"Bytes differing from the backed-up original: {n_diff} "
          f"(expected 9 across 3 sites)")
    if new_state != "patched" or n_diff != 9 or len(new_data) != len(data):
        print("VERIFY FAILED after write — restoring the backup.", file=sys.stderr)
        shutil.copy2(backup, exe)
        sys.exit(1)
    print("Patched and verified: tier=100 + status PremiumActive. "
          "Claimed arrays are NOT forced (see README).")
    print("Next step (only you can do this): launch the game ONLINE on your "
          "play setup and check Customization + the BattlePass screen. "
          "If anything is wrong, run `mfmod.py exe restore --game <dir>`.")
    return 0


def cmd_exe_restore(args):
    game = resolve_game(args)
    exe = find_exe(game)
    if args.backup:
        backup = Path(args.backup)
    else:
        cands = sorted(exe.parent.glob(exe.name + ".*.bak"),
                       key=lambda p: p.stat().st_mtime)
        if not cands:
            die(f"no backup found next to {exe} (looked for "
                f"{exe.name}.*.bak) — nothing to restore from")
        backup = cands[-1]
    if not backup.exists():
        die(f"backup not found: {backup}")
    bh = sha256(backup)
    if bh != ORIGINAL_SHA256:
        die(f"backup {backup.name} sha256 {bh[:16]}… does not match the known "
            f"original ({ORIGINAL_SHA256[:16]}…) — refusing to restore it")
    shutil.copy2(backup, exe)
    state, _, h = exe_state(exe)
    print(f"Restored {exe.name} from {backup.name}")
    print(f"  sha256: {h}  state: {state}")
    if state != "original":
        die("restore did not produce the original exe — check the backup")
    print("Exe is back to stock. The backup file was left in place.")
    return 0


# ---------------------------------------------------------------- pak lane (wrapper)

def cmd_pak(args):
    if not MF_PATCH.exists():
        die(f"mf-patch not found at {MF_PATCH}")
    if not args.pak_args:
        print("mfmod pak — forwards to mf-patch. Usage:")
        print("  mfmod.py pak build <mod_dir> -o <out_dir> [--name pakchunk999-Mods_P]")
        print("  mfmod.py pak verify <built_dir|.utoc> [--game-paks <dir>]")
        print("  mfmod.py pak install <built_dir> --target <Paks dir> [--force] [--dry-run]")
        print("  mfmod.py pak uninstall --target <Paks dir> [--name pakchunk999-Mods_P]")
        print("  mfmod.py pak status [--target <Paks dir>]")
        print("  mfmod.py pak extract <game_path> -o <out> [--game-paks <dir>]")
        print("  mfmod.py pak to-legacy <filter> -o <out_dir> [--game-paks <dir>]")
        print("  mfmod.py pak bulk list-chunks <patch.utoc|game.utoc> [--filter <text>]")
        print("  mfmod.py pak bulk unpack-raw <utoc> -o <out_dir>")
        print("  mfmod.py pak bulk pack-raw <chunk_dir> -o <out.utoc>")
        print("      (experimental: single-chunk .ubulk overrides via retoc")
        print("       pack-raw — transport verified in tooling only, in-game")
        print("       acceptance unproven; see README 'Bulk lane')")
        return 0
    cmd = [sys.executable, str(MF_PATCH)] + args.pak_args
    print(f"mfmod: delegating to mf-patch: {' '.join(args.pak_args)}", flush=True)
    r = subprocess.run(cmd)
    return r.returncode


# ---------------------------------------------------------------- research lists

def cmd_list(args):
    kind = args.kind
    if kind == "stadiums":
        d = load_json(TARGETS_DIR / "stadiums.json")
        print(f"Stadiums ({d['count']} pairs) — source: {d['source']}")
        print(f"Note: {d['note']}")
        for s in d["stadiums"]:
            print(f"  {s['id']:<12} {s['name']}")
    elif kind == "rosters":
        d = load_json(TARGETS_DIR / "rosters.json")
        print(f"Roster tables ({d['count']} .uasset tables) — source: {d['source']}")
        print(f"Note: {d['note']}")
        for t in d["tables"]:
            print(f"  {t['name']:<24} {t['path']}")
    elif kind == "logos":
        d = load_json(TARGETS_DIR / "logos.json")
        print("Uniform-part symbols in DA_CustomizationUniformPartSymbols "
              f"({len(d['symbols'])} decals) — source: {d['source']}")
        for s in d["symbols"]:
            print(f"  {s['name']:<22} {s['path']}")
        print(f"Note: {d['note']}")
        print("Related: " + "; ".join(d["related"]))
    return 0


def cmd_mods(args):
    print("Bundled mods (ready to use through mfmod):")
    print()
    print("1. magenta-tinysquare-test (pak lane) — v1.0")
    man_path = MAGENTA_EXAMPLE / "manifest.json"
    if man_path.exists():
        man = load_json(man_path)
        print(f"   {man.get('description', '')}")
    print(f"   (no pre-built container ships in this repo — game-derived")
    print(f"    binaries are never committed. Recreate it from your own")
    print(f"    extracted originals; see {MAGENTA_EXAMPLE}/README.md)")
    print("   Purpose: the visible in-game test for unsigned *_P acceptance. "
          "It proves nothing about gameplay mods until the launch test passes.")
    print()
    print("2. season-pass-unlock (exe lane, T4) — T4 patch, 9 bytes, 3 sites")
    print("   Loader 0x144e832af: cached tier forced to 100, status forced to "
          '"PremiumActive".')
    print(f"   Original sha256: {ORIGINAL_SHA256}")
    print(f"   Patched  sha256: {PATCHED_SHA256}")
    print("   Apply:   mfmod.py exe apply --game <game dir>")
    print("   Verify:  mfmod.py exe verify --game <game dir>")
    print("   Restore: mfmod.py exe restore --game <game dir>")
    print("   Limit: claimed arrays (+0x560/+0x570) are NOT forced; PlayFab "
          "server-side claim validation may still reject claims.")
    return 0


# ---------------------------------------------------------------- CLI

def _add_game_arg(p):
    # SUPPRESS so a --game given before the subcommand is not clobbered
    # by this subparser's default.
    p.add_argument("--game", default=argparse.SUPPRESS,
                   help="game install dir (default: MF_GAME_DIR or Steam library)")


def main():
    ap = argparse.ArgumentParser(
        prog="mfmod",
        description="Unified Maximum Football modding tool: exe patch (T4) + "
                    "pak overrides + per-target status. See README.md.")
    ap.add_argument("--game", default=None,
                    help="game install dir (default: MF_GAME_DIR or Steam library)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="check game layout, exe, tools, .usmap")
    _add_game_arg(p)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("status", help="per-target readiness table")
    _add_game_arg(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("exe", help="exe patch lane (T4)")
    _add_game_arg(p)
    esub = p.add_subparsers(dest="exe_cmd", required=True)
    q = esub.add_parser("apply", help="patch the exe (backs up the original first)")
    _add_game_arg(q)
    q.add_argument("--force", action="store_true",
                   help="allow patching when the exe hash is unknown (bytes at the "
                        "3 sites must still match the original)")
    q.set_defaults(func=cmd_exe_apply)
    q = esub.add_parser("verify", help="report exe state + the 3 patch sites")
    _add_game_arg(q)
    q.set_defaults(func=cmd_exe_verify)
    q = esub.add_parser("restore", help="restore the original exe from backup")
    _add_game_arg(q)
    q.add_argument("--backup", default=None, help="explicit backup file to restore")
    q.set_defaults(func=cmd_exe_restore)

    p = sub.add_parser("pak", help="pak lane — forwards to mf-patch")
    p.add_argument("pak_args", nargs=argparse.REMAINDER,
                   help="mf-patch subcommand and args, e.g. build/verify/install/...")
    p.set_defaults(func=cmd_pak)

    p = sub.add_parser("list", help="print a verified registry from the game files")
    p.add_argument("kind", choices=["stadiums", "rosters", "logos"])
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("mods", help="list the bundled example mods")
    p.add_argument("list", nargs="?", default="list")
    p.set_defaults(func=cmd_mods)

    args = ap.parse_args()
    # --game is a global option; subcommand funcs read args.game.
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

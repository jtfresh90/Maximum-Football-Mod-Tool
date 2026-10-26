#!/usr/bin/env python3
"""
mf-patch — build, verify, install and uninstall Maximum Football (UE 5.3,
Steam app 1691280) IoStore patch containers (*_P).

What it does, in one line: it turns a folder of edited legacy-format
(.uasset + .uexp) game files into an unsigned pakchunk999-Mods_P.utoc/.ucas
that sits NEXT TO the game's own containers in Content/Paks, and it can put
that container there (and take it back out) without ever touching the
shipped pakchunk0/1/optional files.

Pipeline (proven in the Oct 24 2026 overnight PoC):
    game Zen packages --(retoc to-legacy)--> legacy .uasset/.uexp
    edited legacy files --(retoc to-zen --version UE5_3)--> *_P container
    MFTool/CUE4Parse mounts the *_P alongside the originals; patch
    precedence makes the *_P copy win for every path it carries.

A mod pack (input to `build`) is a directory:
    <mod>/
      manifest.json            # {"name": ..., "version": ..., "description": ...}
      files/                   # legacy files at their EXACT game paths, e.g.
        MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uasset
        MaximumFootball/Content/MaximumFootball/UI/Textures/Common/T_TinySquare.uexp
  Every .uasset should normally have a matching .uexp (and any .ubulk, if the
  asset has one). Paths are case-sensitive and must match the shipped game
  exactly, or the game will simply ignore the override.

Commands:
    build    <mod_dir> -o <out_dir> [--name pakchunk999-Mods_P]
    verify   <built_dir|patch.utoc> [--game-paks <dir>]
    install  <built_dir> --target <Content/Paks dir> [--force] [--dry-run]
    uninstall --target <Content/Paks dir> [--name pakchunk999-Mods_P]
    status   [--target <Content/Paks dir>]
    extract  <game_path> -o <out_file> [--game-paks <dir>]
    to-legacy <filter> -o <out_dir> [--game-paks <dir>]

Safety rules baked in:
  * The real game install is never written to except by `install`, and
    `install` only ever adds/removes *_P files — never pakchunk0/1/optional.
  * `install` refuses a target that does not contain pakchunk0-Windows.utoc
    (so it cannot be pointed at a random folder).
  * An existing *_P with a different hash is backed up (timestamped .bak)
    before being replaced, unless --force is given (then it is still backed
    up — --force only skips the "are you sure" refusal).
  * The AES key is read from MF_AES_KEY, then MF_AES_KEY_FILE, then
    (local-only fallback) the author's recovery report. It is passed only
    via environment/CLI expansion to retoc/MFTool. It is NEVER printed,
    logged, or written into any output file by this tool.
  * Known limits (do not over-claim): (1) this proves build + mount-in-
    tools only — whether the game itself accepts an unsigned *_P, especially
    on an iPhone/Madeira/BCD/Playport setup, is settled only by a real
    in-game launch test. (2) retoc v0.1.5 `to-legacy` NOW converts
    .ubulk textures, provided the Oodle library (liboo2corelinux64.so.9)
    sits next to the retoc binary (verified Oct 25 2026: T_NoiseShape 2/2,
    T_Sky_Blue 1/1, T_Default_Normal 1/1 — previously 0/2, 0/1, 0/1).
    The library is NOT bundled here; see README.md for where to get it.
  * Experimental bulk lane: `bulk list-chunks|unpack-raw|pack-raw` wraps
    retoc's raw-chunk commands so a single modified .ubulk chunk can be
    packed into an unsigned _P without any to-legacy step. Transport is
    verified in tooling (CUE4Parse read-back returns the modified bytes);
    in-game acceptance is unproven. Do NOT ship a marker-byte test as a mod.

Python 3, standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_PATCH_NAME = "pakchunk999-Mods_P"
UE_VERSION = "UE5_3"

# Game location. Priority: --game-paks, then MF_GAME_PAKS, then MF_GAME_DIR,
# then the Steam library locations. No default points at any author's
# your own install — pass --game-paks or set MF_GAME_DIR / MF_GAME_PAKS.
STEAM_GAME_CANDIDATES = [
    Path.home() / ".local/share/Steam/steamapps/common/Maximum Football",
    Path.home() / ".steam/steam/steamapps/common/Maximum Football",
    Path.home() / "snap/steam/common/.local/share/Steam/steamapps/common/Maximum Football",
    Path("C:/Program Files (x86)/Steam/steamapps/common/Maximum Football"),
    Path("C:/Program Files/Steam/steamapps/common/Maximum Football"),
]

# LOCAL-ONLY fallback for the AES key (see aes_key): the author's recovery
# report, if it happens to exist on this machine. Not part of the repo,
# never required — MF_AES_KEY / MF_AES_KEY_FILE win.
LEGACY_KEY_REPORT = (
    Path.home() / "workspace/recon/maximum-football"
    / "AES_KEY_RECOVERY_2026-10-23.md"
)


def discover_game_paks():
    env = os.environ.get("MF_GAME_PAKS")
    if env:
        return Path(env)
    game = os.environ.get("MF_GAME_DIR")
    if game:
        return Path(game) / "MaximumFootball/Content/Paks"
    for cand in STEAM_GAME_CANDIDATES:
        paks = cand / "MaximumFootball/Content/Paks"
        if (paks / "pakchunk0-Windows.utoc").exists():
            return paks
    return None


def optional_game_paks(explicit=None):
    """Game Paks dir, or None — for commands that can run without a game."""
    if explicit:
        return Path(explicit)
    return discover_game_paks()


def resolve_game_paks(explicit=None):
    if explicit:
        return Path(explicit)
    found = discover_game_paks()
    if found is not None:
        return found
    die("game Paks folder not found — pass --game-paks <dir> or set "
        "MF_GAME_PAKS / MF_GAME_DIR (your Steam library's "
        "'Maximum Football' folder)")


def find_dotnet_root():
    for var in ("MF_DOTNET_ROOT", "DOTNET_ROOT"):
        v = os.environ.get(var)
        if v and Path(v).exists():
            return Path(v)
    which = shutil.which("dotnet")
    if which:
        return Path(which).resolve().parent
    return None


def die(msg, code=1):
    print(f"mf-patch: error: {msg}", file=sys.stderr)
    sys.exit(code)


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
    die("retoc not found — set MF_RETOC to its path, put it on PATH, or "
        "place it under <repo>/tools/retoc/ (see README)")


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


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


KEY_RE = re.compile(r"0x[0-9a-fA-F]{64}")


def aes_key():
    """Return the AES key (never print it). Precedence:
    1. MF_AES_KEY env var (with or without the 0x prefix).
    2. MF_AES_KEY_FILE — a local file containing the key.
    3. Local-only fallback: the author's recovery report, if present on
       this machine. It is NOT in the repo and is never required.
    Returns None when no source is available (some commands, e.g. bulk
    pack-raw, do not need a key at all).
    """
    env = os.environ.get("MF_AES_KEY", "").strip()
    if env:
        if not env.startswith("0x"):
            env = "0x" + env
        if KEY_RE.fullmatch(env):
            return env
        die("MF_AES_KEY is not a 0x + 64 hex character key")
    key_file = os.environ.get("MF_AES_KEY_FILE")
    if key_file:
        p = Path(key_file)
        if not p.exists():
            die(f"MF_AES_KEY_FILE not found: {p}")
        m = KEY_RE.search(p.read_text(errors="ignore"))
        return m.group(0) if m else None
    if LEGACY_KEY_REPORT.exists():
        m = KEY_RE.search(LEGACY_KEY_REPORT.read_text(errors="ignore"))
        return m.group(0) if m else None
    return None


def aes_key_source():
    if os.environ.get("MF_AES_KEY"):
        return "MF_AES_KEY"
    if os.environ.get("MF_AES_KEY_FILE"):
        return "MF_AES_KEY_FILE"
    if LEGACY_KEY_REPORT.exists():
        return "local-only legacy key report"
    return None


def run(cmd, env_extra=None, check=True):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    # Never echo a command that carries the key.
    printable = [c if "0x" not in str(c) or len(str(c)) != 66 else "<aes-key>"
                 for c in cmd]
    print(f"  $ {' '.join(str(c) for c in printable)}")
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.stdout:
        print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
    if r.stderr:
        print(r.stderr, file=sys.stderr, end="" if r.stderr.endswith("\n") else "\n")
    if check and r.returncode != 0:
        die(f"command failed (exit {r.returncode})")
    return r


def mftool_env():
    env = {}
    dotnet = find_dotnet_root()
    if dotnet is not None:
        env["DOTNET_ROOT"] = str(dotnet)
        env["PATH"] = f"{dotnet}:{os.environ.get('PATH', '')}"
    key = aes_key()
    if key:
        env["MFTOOL_AESKEY"] = key
    return env


def mftool_or_die():
    tool = find_mftool()
    if tool is None:
        die("MFTool not found — set MF_MFTOOL, put it on PATH, or place it "
            "under <repo>/tools/cue4parse/ (see README)")
    return tool


def list_files(root):
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file())


# ---------------------------------------------------------------- build

def cmd_build(args):
    mod_dir = Path(args.mod_dir)
    manifest_path = mod_dir / "manifest.json"
    files_dir = mod_dir / "files"
    if not manifest_path.exists():
        die(f"{mod_dir} has no manifest.json (see --help / README for the format)")
    if not files_dir.is_dir() or not list_files(files_dir):
        die(f"{mod_dir}/files/ is empty or missing — nothing to patch with")
    manifest = json.loads(manifest_path.read_text())
    name = manifest.get("name", "unnamed-mod")
    version = manifest.get("version", "0.1")
    print(f"Building patch for mod '{name}' v{version}")
    print(f"  files: {len(list_files(files_dir))} staged file(s)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_name = args.name
    utoc = out_dir / f"{patch_name}.utoc"

    retoc = find_retoc()
    run([str(retoc), "to-zen", str(files_dir), str(utoc), "--version", UE_VERSION])
    for suffix in (".utoc", ".ucas", ".pak"):
        p = out_dir / f"{patch_name}{suffix}"
        if not p.exists():
            die(f"retoc did not produce {p} — build failed")
    run([str(retoc), "verify", str(utoc)])

    build_info = {
        "tool": "mf-patch",
        "mod": {"name": name, "version": version,
                "description": manifest.get("description", "")},
        "patch_name": patch_name,
        "ue_version": UE_VERSION,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": list_files(files_dir),
        "outputs": {s: {"size": (out_dir / f"{patch_name}{s}").stat().st_size,
                        "sha256": sha256(out_dir / f"{patch_name}{s}")}
                    for s in (".utoc", ".ucas", ".pak")},
    }
    (out_dir / "build.json").write_text(json.dumps(build_info, indent=2) + "\n")
    print(f"Built: {utoc} (+ .ucas, .pak)")
    print(f"  utoc sha256: {build_info['outputs']['.utoc']['sha256']}")
    print(f"  ucas sha256: {build_info['outputs']['.ucas']['sha256']}")
    print(f"  manifest: {out_dir / 'build.json'}")
    return 0


# ---------------------------------------------------------------- verify

def cmd_verify(args):
    target = Path(args.target)
    if target.is_file() and target.suffix == ".utoc":
        utoc, patch_dir = target, target.parent
    else:
        patch_dir = target
        candidates = sorted(patch_dir.glob("*.utoc"))
        if not candidates:
            die(f"no .utoc found in {patch_dir}")
        utoc = candidates[0]
    patch_name = utoc.stem
    print(f"Verifying {utoc}")

    retoc = find_retoc()
    run([str(retoc), "verify", str(utoc)])
    info = subprocess.run([str(retoc), "info", str(utoc)],
                          capture_output=True, text=True)
    print(info.stdout)
    if "Signed" in info.stdout:
        print("  WARNING: container reports Signed — expected unsigned for *_P")
    mftool = find_mftool()
    if mftool is not None:
        run([str(mftool), "containers", str(patch_dir)], env_extra=mftool_env(),
            check=False)
    else:
        print("  (MFTool not found — skipping mount check)")

    game_paks = optional_game_paks(args.game_paks)
    build_info = None
    build_json = patch_dir / "build.json"
    if build_json.exists():
        build_info = json.loads(build_json.read_text())

    if game_paks is not None and game_paks.exists() and mftool is not None:
        # Full-staging mount: symlinks to the real containers + the patch.
        # The patch must win for every path it carries.
        with tempfile.TemporaryDirectory(prefix="mf-patch-verify-") as td:
            stage = Path(td)
            for f in game_paks.iterdir():
                if f.is_file():
                    os.symlink(f, stage / f.name)
            for suffix in (".utoc", ".ucas", ".pak"):
                src = patch_dir / f"{patch_name}{suffix}"
                if src.exists():
                    shutil.copy2(src, stage / src.name)
            lst = run([str(mftool), "list", str(stage), str(stage / "list.csv")],
                      env_extra=mftool_env(), check=False)
            if lst.returncode == 0:
                print("  mount check: patch container mounts alongside the originals")
                if build_info:
                    for rel in build_info["files"]:
                        # In the Zen/IoStore view there is no separate .uexp
                        # file — export data lives inside the .uasset — so
                        # only .uasset paths can be read back. The path
                        # MFTool expects is the full staged path, exactly as
                        # in the overnight PoC (e.g.
                        # MaximumFootball/Content/MaximumFootball/UI/...).
                        if not rel.endswith(".uasset"):
                            continue
                        r = subprocess.run(
                            [str(mftool), "raw", str(stage), rel,
                             str(stage / "readback.bin")],
                            env=mftool_env(), capture_output=True, text=True)
                        if r.returncode == 0:
                            print(f"  read-back OK: {rel} "
                                  f"({(stage / 'readback.bin').stat().st_size} bytes, "
                                  f"sha256 {sha256(stage / 'readback.bin')})")
                        else:
                            print(f"  read-back FAILED for {rel}")
    print("Verify done. Note: this proves build + mount-in-tools only — the "
          "in-game acceptance test is still required (see README).")
    return 0


# ---------------------------------------------------------------- install / uninstall / status

def check_target(target):
    target = Path(target)
    if not (target / "pakchunk0-Windows.utoc").exists():
        die(f"{target} does not look like a Maximum Football Content/Paks "
            f"folder (no pakchunk0-Windows.utoc) — refusing to install there")
    return target


def installed_patch_files(target, patch_name):
    # .pak is optional: retoc pack-raw builds (bulk lane) produce only
    # .utoc + .ucas, while to-zen builds also produce a .pak.
    return [target / f"{patch_name}{s}" for s in (".utoc", ".ucas", ".pak")
            if (target / f"{patch_name}{s}").exists()]


def cmd_install(args):
    built = Path(args.built)
    if built.is_file():
        built = built.parent
    build_json = built / "build.json"
    patch_name = None
    if build_json.exists():
        patch_name = json.loads(build_json.read_text())["patch_name"]
    if not patch_name:
        cands = sorted(built.glob("*_P.utoc"))
        patch_name = cands[0].stem if cands else DEFAULT_PATCH_NAME
    srcs = {s: built / f"{patch_name}{s}" for s in (".utoc", ".ucas", ".pak")
            if (built / f"{patch_name}{s}").exists()}
    missing = [s for s in (".utoc", ".ucas") if s not in srcs]
    if missing:
        die(f"built patch incomplete, missing: {', '.join(missing)}")

    target = check_target(Path(args.target))
    existing = installed_patch_files(target, patch_name)
    if existing and not args.force:
        die(f"{patch_name} already installed in {target} "
            f"({', '.join(p.name for p in existing)}) — use --force to replace "
            f"(old files are backed up first) or `uninstall` first")
    if args.dry_run:
        print(f"[dry-run] would install {patch_name} into {target}:")
        for p in srcs.values():
            print(f"  {p.name} ({p.stat().st_size} bytes)")
        return 0
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for p in existing:
            bak = p.with_name(f"{p.name}.{stamp}.bak")
            shutil.move(str(p), str(bak))
            print(f"  backed up existing {p.name} -> {bak.name}")
    for p in srcs.values():
        shutil.copy2(p, target / p.name)
        print(f"  installed {p.name} ({p.stat().st_size} bytes)")
    receipt = {"tool": "mf-patch", "patch_name": patch_name,
               "installed_at_utc": datetime.now(timezone.utc).isoformat(),
               "target": str(target),
               "files": {s: sha256(p) for s, p in srcs.items()}}
    (built / "install_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Receipt: {built / 'install_receipt.json'}")
    print("Next step (only you can do this): launch the game OFFLINE on your "
          "play setup and confirm it boots with the *_P present. If it "
          "crashes or rejects the patch, run `uninstall` — the shipped "
          "containers were never touched, so removal restores stock.")
    return 0


def cmd_uninstall(args):
    target = check_target(Path(args.target))
    patch_name = args.name
    existing = installed_patch_files(target, patch_name)
    if not existing:
        print(f"No {patch_name} installed in {target} — nothing to remove.")
        return 0
    for p in existing:
        p.unlink()
        print(f"  removed {p.name}")
    baks = sorted(target.glob(f"{patch_name}.*.bak"))
    if baks:
        print(f"  note: {len(baks)} backup(s) left in place "
              f"({baks[-1].name} is the newest) — delete manually if unwanted")
    print("Uninstalled. The game is back to stock containers.")
    return 0


def cmd_status(args):
    target = Path(args.target) if args.target else resolve_game_paks()
    print(f"Paks folder: {target}")
    if not target.exists():
        print("  (folder does not exist here)")
        return 0
    for f in sorted(target.glob("*.utoc")):
        print(f"  {f.name} ({f.stat().st_size} bytes)")
    patches = sorted(target.glob("*_P.utoc"))
    if patches:
        for p in patches:
            print(f"  PATCH INSTALLED: {p.name} "
                  f"(sha256 {sha256(p)[:16]}…, "
                  f"ucas present: {(target / (p.stem + '.ucas')).exists()})")
    else:
        print("  no *_P patch containers installed")
    return 0


# ---------------------------------------------------------------- helpers

def cmd_extract(args):
    game_paks = resolve_game_paks(args.game_paks)
    mftool = mftool_or_die()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run([str(mftool), "raw", str(game_paks), args.game_path, str(out)],
        env_extra=mftool_env())
    print(f"Extracted {args.game_path} -> {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_to_legacy(args):
    game_paks = resolve_game_paks(args.game_paks)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    retoc = find_retoc()
    key = aes_key()
    cmd = [str(retoc)]
    if key:
        cmd += ["-a", key]
    cmd += ["to-legacy", str(game_paks), str(out),
            "--filter", args.filter, "--no-shaders"]
    # Key is expanded in argv (retoc needs it there); run() masks 66-char hex.
    run(cmd)
    print(f"Legacy output in {out}")
    print("NOTE: .ubulk textures convert since Oct 25 2026, but ONLY if the "
          "Oodle library (liboo2corelinux64.so.9) sits next to the retoc "
          "binary. If this extracted 0 assets, check for that library "
          "first (see README) — do not assume your files are at fault.")
    return 0


# ---------------------------------------------------------------- bulk lane
# Experimental. Wraps retoc's raw-chunk commands (verified Oct 25 2026):
# a _P container holding ONLY a modified .ubulk chunk overrides pakchunk0
# for that chunk when mounted together (CUE4Parse read-back returns the
# modified bytes). No to-legacy step is needed. In-game acceptance is
# UNPROVEN — same honesty box as the rest of the pak lane. Do NOT ship a
# marker-byte test as a mod; use this only for real bulk edits.

def cmd_bulk_list_chunks(args):
    return _bulk_list_filtered(args.utoc, args.filter)


def _bulk_list_filtered(utoc, filt):
    """Run retoc list capturing output so --filter can narrow it."""
    retoc = find_retoc()
    cmd = [str(retoc)]
    key = aes_key()
    if key:
        cmd += ["-a", key]
    cmd += ["list", "--path", "--size", str(utoc)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.splitlines()
    if filt:
        lines = [l for l in lines if filt.lower() in l.lower()]
    print("\n".join(lines))
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    return r.returncode


def cmd_bulk_unpack_raw(args):
    retoc = find_retoc()
    out = Path(args.out)
    # retoc refuses to unpack into an existing directory, so do NOT
    # create it here — only make sure its parent exists.
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and any(out.iterdir()):
        die(f"{out} already exists and is not empty — unpack into a fresh "
            f"directory (or empty it first)")
    run([str(retoc), "unpack-raw", str(args.utoc), str(out)])
    manifest = out / "manifest.json"
    chunks_dir = out / "chunks"
    n = len(list(chunks_dir.iterdir())) if chunks_dir.is_dir() else 0
    print(f"Unpacked {n} raw chunk(s) into {out}")
    if manifest.exists():
        print(f"  manifest: {manifest}")
        print("  To repack after editing a chunk: "
              f"mf_patch.py bulk pack-raw {out} -o <out.utoc>")
    return 0


def cmd_bulk_pack_raw(args):
    src = Path(args.chunk_dir)
    manifest = src / "manifest.json"
    chunks_dir = src / "chunks"
    if not manifest.exists():
        die(f"{src} has no manifest.json — run `bulk unpack-raw` first, "
            f"or build the dir in that shape (manifest.json + chunks/<chunk-id>)")
    if not chunks_dir.is_dir() or not list(chunks_dir.iterdir()):
        die(f"{src}/chunks/ is empty — nothing to pack")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    retoc = find_retoc()
    run([str(retoc), "pack-raw", str(src), str(out)])
    run([str(retoc), "verify", str(out)])
    info = {
        "tool": "mf-patch bulk pack-raw",
        "source_dir": str(src),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "chunks": sorted(p.name for p in chunks_dir.iterdir() if p.is_file()),
        "outputs": {s: {"size": (out.with_suffix(s)).stat().st_size,
                        "sha256": sha256(out.with_suffix(s))}
                    for s in (".utoc", ".ucas")
                    if out.with_suffix(s).exists()},
    }
    (out.parent / "bulk_build.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"Built (pack-raw): {out}")
    for s, v in info["outputs"].items():
        print(f"  {s}: {v['size']} bytes, sha256 {v['sha256']}")
    print(f"  manifest: {out.parent / 'bulk_build.json'}")
    print("NOTE: pack-raw produces .utoc + .ucas only (no .pak). `install` "
          "accepts that. In-game acceptance of this container is UNPROVEN.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        prog="mf-patch",
        description="Build / verify / install / uninstall Maximum Football "
                    "IoStore *_P patch containers (UE 5.3).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="build a *_P container from a mod pack")
    p.add_argument("mod_dir")
    p.add_argument("-o", "--out", required=True, help="output directory")
    p.add_argument("--name", default=DEFAULT_PATCH_NAME)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="verify a built patch container")
    p.add_argument("target", help="built dir or .utoc file")
    p.add_argument("--game-paks", default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("install", help="install a built patch into a Paks folder")
    p.add_argument("built", help="built dir (from `build`)")
    p.add_argument("--target", required=True)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="remove a *_P patch from a Paks folder")
    p.add_argument("--target", required=True)
    p.add_argument("--name", default=DEFAULT_PATCH_NAME)
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("status", help="list containers / installed patches")
    p.add_argument("--target", default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("bulk", help="experimental raw-chunk lane (.ubulk overrides)")
    bsub = p.add_subparsers(dest="bulk_cmd", required=True)
    q = bsub.add_parser("list-chunks", help="list chunks in a container")
    q.add_argument("utoc")
    q.add_argument("--filter", default=None, help="substring to narrow the listing")
    q.set_defaults(func=cmd_bulk_list_chunks)
    q = bsub.add_parser("unpack-raw", help="extract raw chunks from a container")
    q.add_argument("utoc")
    q.add_argument("-o", "--out", required=True, help="output directory")
    q.set_defaults(func=cmd_bulk_unpack_raw)
    q = bsub.add_parser("pack-raw", help="pack a chunk dir (manifest.json + chunks/) into a _P container")
    q.add_argument("chunk_dir")
    q.add_argument("-o", "--out", required=True, help="output .utoc path")
    q.set_defaults(func=cmd_bulk_pack_raw)

    p = sub.add_parser("extract", help="extract one original asset (Zen bytes)")
    p.add_argument("game_path")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--game-paks", default=None)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("to-legacy", help="convert original assets to legacy form")
    p.add_argument("filter")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--game-paks", default=None)
    p.set_defaults(func=cmd_to_legacy)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

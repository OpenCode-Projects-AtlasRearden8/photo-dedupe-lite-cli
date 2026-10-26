#!/usr/bin/env python3
"""photodedupe: safely tighten a camera roll.

Pure-stdlib CLI that:
  1. Finds byte-exact duplicates by hashing (no uploads, no image analysis).
  2. Groups look-alike NAMES (IMG_2341 (1).jpg vs IMG_2341.jpg).
  3. Always shows a dry-run preview first.
  4. Moves (never deletes) duplicates into a dated archive folder,
     writing an undo manifest so everything can be restored.

Keeps the earliest, or the best-labeled copy, per your rules file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- hashing ---

_CHUNK = 1 << 20


def hash_file(path: Path, algo: str = "sha256") -> str:
    """Return hex digest of a file, reading in chunks."""
    h = hashlib.new(algo)
    with path.open("rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------ name groups ---


def base_stem(name: str) -> str:
    """Strip common duplicate-creator suffixes so look-alikes group together.

    IMG_2341 (1).jpg, IMG_2341-2.jpg, IMG_2341_copy.jpg -> IMG_2341
    """
    stem = Path(name).stem
    stem = re.sub(r"\s*\(\d+\)$", "", stem)
    stem = re.sub(r"[-_ ]*(?:copy|kopie|duplicat\d*|dup\d*)\d*[-_ ]*\d*$", "", stem, flags=re.I)
    # strip copy-tool indexes like "file-2.jpg" / "file 2.jpg"; keep camera stems
    # like "IMG_2341" intact (the digits there are part of the name)
    stem = re.sub(r"[- ]+\d{1,4}$", "", stem)
    return stem.lower()


def name_groups(files: Sequence[Path]) -> List[List[Path]]:
    """Group files whose base stems and sizes match (look-alike names)."""
    groups: Dict[Tuple[str, int], List[Path]] = defaultdict(list)
    for f in files:
        groups[(base_stem(f.name), f.stat().st_size)].append(f)
    return [sorted(v, key=lambda p: p.name) for v in groups.values() if len(v) > 1]


# --------------------------------------------------------------- rules ------
# rules file (JSON, optional):
# {
#   "keep": "earliest" | "best_labeled",   # default: earliest
#   "preferred_names": ["edited", "best", "original", "favorite"],
#   "min_size_bytes": 0                   # skip files smaller than this
# }


def load_rules(path: Optional[Path]) -> dict:
    if path is None:
        return {"keep": "earliest", "preferred_names": [], "min_size_bytes": 0}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    keep = data.get("keep", "earliest")
    if keep not in ("earliest", "best_labeled"):
        raise ValueError(f"rules: 'keep' must be 'earliest' or 'best_labeled', got {keep!r}")
    return {
        "keep": keep,
        "preferred_names": [n.lower() for n in data.get("preferred_names", [])],
        "min_size_bytes": int(data.get("min_size_bytes", 0)),
    }


def choose_keeper(group: Sequence[Path], rules: dict) -> Tuple[Path, List[Path]]:
    """Pick the file to keep from a duplicate group; return (keep, dupes)."""
    if rules["keep"] == "best_labeled":
        prefs = rules["preferred_names"]
        if prefs:
            def score(p: Path) -> int:
                low = p.name.lower()
                best = len(prefs)
                for i, tag in enumerate(prefs):
                    if tag in low:
                        best = i
                        break
                return best
            keeper = min(group, key=lambda p: (score(p), mtime_of(p)))
        else:
            keeper = min(group, key=mtime_of)
    else:
        keeper = min(group, key=mtime_of)
    dupes = [p for p in group if p != keeper]
    return keeper, dupes


def mtime_of(path: Path) -> float:
    return path.stat().st_mtime


# ----------------------------------------------------------------- plan -----


def plan(
    root: Path,
    rules: dict,
    include_hash_groups: bool = True,
    include_name_groups: bool = True,
) -> List[dict]:
    """Build the move plan: list of {keep, dupes:[...]} actions."""
    files = _collect_files(root, rules)
    actions: Dict[Path, dict] = {}

    if include_hash_groups:
        by_hash: Dict[str, List[Path]] = defaultdict(list)
        for f in files:
            by_hash[hash_file(f)].append(f)
        for members in by_hash.values():
            if len(members) > 1:
                keeper, dupes = choose_keeper(sorted(members, key=mtime_of), rules)
                for d in dupes:
                    actions[d] = {"keep": str(keeper), "dupe": d}

    # Look-alike names that are NOT byte-equal: flag same-content-size name groups
    # only as informational extras, still moved under the archive rule.
    if include_name_groups:
        for grp in name_groups(files):
            # skip groups already fully covered by byte-exact hashing
            remaining = [p for p in grp if p not in actions]
            if len(remaining) > 1:
                keeper, dupes = choose_keeper(grp, rules)
                for d in dupes:
                    if d not in actions:
                        actions[d] = {"keep": str(keeper), "dupe": d, "fuzzy": True}

    return [{"keep": a["keep"], "dupe": a["dupe"], "fuzzy": a.get("fuzzy", False)}
            for a in actions.values()]


def _collect_files(root: Path, rules: dict) -> List[Path]:
    out: List[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            if p.stat().st_size < rules["min_size_bytes"]:
                continue
            out.append(p)
    return out


def _default_archive_name() -> str:
    return dt.datetime.now().strftime("duplicates-%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- apply -----

MANIFEST_NAME = "undo-manifest.json"


def apply_plan(items: Sequence[dict], archive: Path, dry: bool) -> dict:
    """Move dupes into archive folder. Returns summary of what happened."""
    archive.mkdir(parents=True, exist_ok=True)
    moved: List[Tuple[Path, Path]] = []
    for item in items:
        src = Path(item["dupe"])
        dest = archive / src.name
        # avoid collisions inside archive
        n = 1
        while dest.exists():
            dest = archive / f"{src.stem}_{n}{src.suffix}"
            n += 1
        if dry:
            print(f"  DRY-RUN would move: {src} -> {dest}")
        else:
            src.replace(dest)
            print(f"  moved: {src} -> {dest}")
        moved.append((src, dest))

    manifest = {
        "version": 1,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "move": [{"from": str(s), "to": str(d)} for s, d in moved]
    }
    manifest_path = archive / MANIFEST_NAME
    if dry:
        print(f"  DRY-RUN would write manifest: {manifest_path}")
    else:
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        print(f"  manifest: {manifest_path}")
    return {"moved": len(moved), "manifest": str(manifest_path)}


def undo(archive: Path, dry: bool) -> int:
    manifest_path = archive / MANIFEST_NAME
    if not manifest_path.exists():
        print(f"no {MANIFEST_NAME} in {archive}", file=sys.stderr)
        return 1
    with manifest_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    ported = 0
    for entry in data.get("move", []):
        src, dest = Path(entry["to"]), Path(entry["from"])
        if not src.exists():
            continue
        if dry:
            print(f"  DRY-RUN would move back: {src} -> {dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dest)
            print(f"  moved back: {src} -> {dest}")
        ported += 1
    return 0


# ----------------------------------------------------------------- CLI ------


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="photodedupe",
        description="Safely tighten a camera roll: byte-exact duplicate "
        "detection, look-alike name grouping, dry-run preview, then "
        "MOVES duplicates into a dated archive folder with an undo "
        "manifest. Never deletes.",
    )
    ap.add_argument("directory", type=Path, nargs="?", default=None,
                    help="camera roll / folder to scan (not needed with --undo)")
    ap.add_argument("--rules", type=Path, default=None,
                    help="JSON rules file (see README)")
    ap.add_argument("--apply", action="store_true",
                    help="actually move duplicates (default: dry-run)")
    ap.add_argument("--undo", metavar="ARCHIVE_DIR",
                    help="restore files from an archive folder's manifest")
    ap.add_argument("--manifest-only", action="store_true",
                    help="write plan preview to stdout as JSON")
    args = ap.parse_args(argv)

    if args.undo:
        return undo(Path(args.undo), dry=not args.apply)

    root = args.directory
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    try:
        rules = load_rules(args.rules)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"rules error: {e}", file=sys.stderr)
        return 2

    print(f"scanning {root} ...")
    items = plan(root, rules)
    if not items:
        print("no duplicates found. camera roll is already tight.")
        return 0

    print(f"\n{len(items)} duplicate file(s) found:\n")
    for it in items:
        tag = " [look-alike name]" if it.get("fuzzy") else ""
        print(f"  dupe:   {it['dupe']}{tag}")
        print(f"  keep:   {it['keep']}")
    print(f"\nkeeper rule: {rules['keep']}")

    if args.manifest_only:
        print(json.dumps(items, indent=2, ensure_ascii=False, default=str))
        return 0

    if not args.apply:
        print("\nDRY-RUN only. Re-run with --apply to move duplicates.")
        return 0

    archive = root / _default_archive_name()
    result = apply_plan(items, archive, dry=False)
    print(f"\ndone. moved {result['moved']} file(s) to {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

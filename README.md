# photo-dedupe-lite-cli

A tiny, safe Python CLI that tightens a cluttered camera roll. Pure
standard library — no uploads, no cloud, no image analysis, no fancy
image voodoo. Just careful, undoable housekeeping.

Part of the beginner-friendly tool family from [Dylan Asdale](https://dylanasdale.github.io)
and **Asdale Dynamics, LLC**.

## What it does

1. **Byte-exact duplicate detection** — every file is hashed (SHA-256).
   Files with identical hashes are true duplicates.
2. **Look-alike name grouping** — `IMG_2341 (1).jpg` and `IMG_2341.jpg`
   are grouped even if contents differ slightly.
3. **Mandatory dry-run preview** — by default it *shows* what it would
   do and touches nothing. Moving files always requires `--apply`.
4. **Moves, never deletes** — duplicates are moved (never deleted) into
   a dated archive folder like `duplicates-20261026-093000/`.
5. **Undo manifest** — each archive run writes `undo-manifest.json`;
   re-run with `--undo ARCHIVE_DIR --apply` to move files back.
6. **Your rules** — decide whether to keep the *earliest* copy or the
   *best-labeled* copy (e.g. `edited`, `favorite`) via a rules file.

## Requirements

- Python 3.9+ (tested on 3.13). Nothing else — it is stdlib-only.

## Quick start

```bash
# preview what would happen (nothing is moved)
python3 photodedupe.py ~/Pictures/camera-roll

# do it for real — duplicates moved into a dated folder
python3 photodedupe.py ~/Pictures/camera-roll --apply

# whoops, put everything back
python3 photodedupe.py --undo ~/Pictures/camera-roll/duplicates-20261026-093000 --apply
```

## The rules file

Pass `--rules rules.json` to customize keeper selection:

```json
{
  "keep": "earliest",
  "preferred_names": ["edited", "best", "favorite", "original"],
  "min_size_bytes": 0
}
```

- `keep: "earliest"` (default) — keep the oldest file (by modification
  time); newer copies are treated as duplicates.
- `keep: "best_labeled"` — keep the highest file whose name contains
  the first matching `preferred_names` tag; ties fall back to earliest.
- `min_size_bytes` — ignore files smaller than this (thumbnails, etc.).

A sample `rules.example.json` is included.

## Safety checklist

- Dry-run is the default; moving requires `--apply`.
- Files are `shutil`-style **moved** into the archive folder inside your
  scan root — nothing leaves the drive, nothing is deleted.
- Every run writes an `undo-manifest.json` into the archive folder —
  see `--undo`.
- Never points at system folders on purpose: it only does what you
  point it at.

## Tests

```bash
pip install pytest  # dev-only dependency
python3 -m pytest tests/ -v
```

The test suite uses `tmp_path` fixtures so it never touches your real
photos.

## Complements these guides

- *photo-library-comfort-guide* — building calm, curated photo habits
- *backup-basics-handbook* — the 3-2-1 backup rhythm everyone can do

Run a backup **first**, then dedupe. That order matters.

## License & credit

MIT — Copyright (c) 2026 Asdale Dynamics, LLC. See `LICENSE`.

No secrets, API keys, or personal data are ever read from outside the
folder you point the tool at, and nothing is uploaded anywhere.

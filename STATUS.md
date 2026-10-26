# STATUS.md

## What was built

`photo-dedupe-lite-cli` — a pure-stdlib Python CLI that safely tightens a
camera roll. It:

- Finds byte-exact duplicates via SHA-256 hashing (chunked reads for
  memory safety).
- Groups look-alike names (`IMG_2341 (1).jpg` vs `IMG_2341.jpg`,
  `-2` / `_copy` suffixes).
- Defaults to a mandatory dry-run preview; moving files requires `--apply`.
- Moves (never deletes) duplicates into a dated archive folder
  (`duplicates-YYYYMMDD-HHMMSS/`) inside the scanned root.
- Writes an `undo-manifest.json` in the archive folder; `--undo
  ARCHIVE_DIR` restores files.
- Reads a JSON rules file (`rules.example.json`) to pick a keeper:
  `earliest` (oldest file wins, default) or `best_labeled` (first
  matching tag from `preferred_names`, e.g. `edited`, `favorite`),
  plus an optional `min_size_bytes` filter.

No uploads, no image analysis, nothing leaves the machine.

## Files

- `photodedupe.py` — the CLI (single-file tool)
- `rules.example.json` — sample rules
- `tests/test_photodedupe.py` — pytest suite (tmp_path fixtures)
- `README.md`, `LICENSE` (MIT, Asdale Dynamics, LLC), `pytest.ini`

## How to run

```bash
# preview (nothing is touched)
python3 photodedupe.py /path/to/photos

# move duplicates into a dated archive folder
python3 photodedupe.py /path/to/photos --apply

# put things back
python3 photodedupe.py --undo /path/to/photos/duplicates-20261026-091020 --apply

# with custom rules
python3 photodedupe.py /path/to/photos --rules rules.example.json
```

## Verification

- `python3 -m pytest tests/ -q` → **11 passed**
- Manual end-to-end smoke run (dry-run → apply → undo) on a scratch
  folder: correct keeper chosen, duplicates moved, manifest written,
  undo restored all files.
- `python3 photodedupe.py --help` runs cleanly; invalid rules files
  produce a clear error (exit code 2).
- Python 3.13, stdlib only (pytest is a dev/test dependency only).

## Known gaps

- Look-alike name grouping is name/size-based, not content-based: an
  `IMG_2341 (1).jpg` with different bytes is grouped and moved as a
  "fuzzy" duplicate even if the images are visually distinct. flagged
  `fuzzy: true` in output. Most test-club users want this; strict users
  may want an opt-out flag.
- No EXIF/date taken consideration — keep/earliest uses modification
  time only.
- No scheduled/recursing multi-root scanning; one root per run.
- Archive folders created by previous runs inside the root are scanned
  too; run the tool before archiving or remove the folder temporarily
  if re-running repeatedly.
- No packaging (pyproject wheel) yet — it is a single-file tool by
  design.

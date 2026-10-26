import json
from pathlib import Path

import pytest

import photodedupe as pd


def write(path, data: bytes, mtime: float | None = None):
    path.write_bytes(data)
    if mtime is not None:
        import os

        os.utime(path, (mtime, mtime))
    return path


def test_hash_identical_bytes(tmp_path):
    a = write(tmp_path / "a.jpg", b"same")
    b = write(tmp_path / "b.jpg", b"same")
    assert pd.hash_file(a) == pd.hash_file(b)
    c = write(tmp_path / "c.jpg", b"different")
    assert pd.hash_file(c) != pd.hash_file(a)


def test_base_stem_lookalikes(tmp_path):
    assert pd.base_stem("IMG_2341 (1).jpg") == "img_2341"
    assert pd.base_stem("IMG_2341.jpg") == "img_2341"
    assert pd.base_stem("IMG_2341-2.jpg") == "img_2341"
    assert pd.base_stem("IMG_2341_copy.jpg") == "img_2341"
    assert pd.base_stem("vacation copy 2.jpg") == "vacation"


def test_dry_run_is_default(tmp_path):
    a = write(tmp_path / "a.jpg", b"x", 1700000000)
    b = write(tmp_path / "b.jpg", b"x", 1700000100)
    items = pd.plan(tmp_path, pd.load_rules(None))
    assert len(items) == 1
    # nothing moved yet
    assert a.exists() and b.exists()
    result = pd.apply_plan(items, tmp_path / "archive", dry=True)
    assert a.exists() and b.exists()
    assert result["moved"] == 1


def test_apply_moves_earliest_kept(tmp_path):
    a = write(tmp_path / "a.jpg", b"x", 1700000000)
    b = write(tmp_path / "b.jpg", b"x", 1700000100)
    items = pd.plan(tmp_path, pd.load_rules(None))
    pd.apply_plan(items, tmp_path / "duplicates-x", dry=False)
    assert a.exists()
    assert not b.exists()
    assert (tmp_path / "duplicates-x" / "b.jpg").exists()
    manifest = json.loads((tmp_path / "duplicates-x" / pd.MANIFEST_NAME).read_text())
    assert manifest["move"][0]["from"].endswith("b.jpg")


def test_undo_restores(tmp_path):
    a = write(tmp_path / "a.jpg", b"x", 1700000000)
    b = write(tmp_path / "b.jpg", b"x", 1700000100)
    archive = tmp_path / "duplicates-x"
    items = pd.plan(tmp_path, pd.load_rules(None))
    pd.apply_plan(items, archive, dry=False)
    assert not b.exists()
    pd.undo(archive, dry=False)
    assert b.exists()
    assert (archive / "b.jpg").exists() is False


def test_best_labeled_rule(tmp_path):
    rules = pd.load_rules(None)
    rules["keep"] = "best_labeled"
    rules["preferred_names"] = ["edited", "favorite"]
    base = write(tmp_path / "IMG_1.jpg", b"x", 1700000000)
    edited = write(tmp_path / "IMG_1_edited.jpg", b"x", 1700000500)
    keeper, dupes = pd.choose_keeper([base, edited], rules)
    assert keeper == edited
    assert dupes == [base]


def test_hash_groups_content_differs_kept(tmp_path):
    a = write(tmp_path / "IMG_1.jpg", b"AAA", 1700000000)
    b = write(tmp_path / "IMG_1 (1).jpg", b"BBB", 1700000100)
    items = pd.plan(tmp_path, pd.load_rules(None))
    # byte contents differ: only the fuzzy name group matches
    assert len(items) == 1
    assert items[0]["fuzzy"] is True
    keeper = Path(items[0]["keep"])
    assert keeper == a  # earliest kept
    dupe = Path(items[0]["dupe"])
    assert dupe == b


def test_min_size_skips_tiny_files(tmp_path):
    write(tmp_path / "a.jpg", b"x", 1700000000)
    write(tmp_path / "b.jpg", b"x", 1700000100)
    rules = pd.load_rules(None)
    rules["min_size_bytes"] = 10
    items = pd.plan(tmp_path, rules)
    assert items == []


def test_cli_dry_run_no_moves(tmp_path, capsys):
    write(tmp_path / "a.jpg", b"x", 1700000000)
    write(tmp_path / "b.jpg", b"x", 1700000100)
    rc = pd.main([str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "b.jpg").exists()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out


def test_cli_apply_and_undo_roundtrip(tmp_path, capsys):
    write(tmp_path / "a.jpg", b"x", 1700000000)
    write(tmp_path / "b.jpg", b"x", 1700000100)
    rc = pd.main([str(tmp_path), "--apply"])
    assert rc == 0
    assert (tmp_path / "b.jpg").exists() is False
    archive = sorted(p for p in tmp_path.iterdir() if p.is_dir())[0]
    rc = pd.main(["--undo", str(archive), "--apply"])
    assert rc == 0
    assert (tmp_path / "b.jpg").exists()


def test_rules_file_invalid_keep(tmp_path):
    rf = tmp_path / "rules.json"
    rf.write_text(json.dumps({"keep": "smallest"}))
    with pytest.raises(ValueError):
        pd.load_rules(rf)

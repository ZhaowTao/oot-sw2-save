"""CLI smoke tests against synthetic saves."""

import json
import os

import pytest

from ootsw2.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_list_shows_named_fields(slot_dir, capsys):
    code, out, _ = run(capsys, "list", str(slot_dir), "--named")
    assert code == 0
    assert "PlayerStatus.CurrentRupee" in out
    assert "105" in out  # newest slot


def test_list_json_is_parseable(slot_dir, capsys):
    code, out, _ = run(capsys, "list", str(slot_dir), "--named", "--json")
    assert code == 0
    rows = json.loads(out)
    assert all("name" in row and "value" in row for row in rows)


def test_get_prints_requested_fields(slot_dir, capsys):
    code, out, _ = run(capsys, "get", str(slot_dir), "PlayerStatus.DiveDepth")
    assert code == 0
    assert "PlayerStatus.DiveDepth" in out
    assert "6" in out


def test_get_reports_absent_fields(slot_dir, capsys):
    code, out, _ = run(capsys, "get", str(slot_dir), "PlayerStatus.MaxLife")
    assert code == 0
    assert "absent" in out


def test_set_dry_run_does_not_write(slot_dir, capsys):
    code, out, _ = run(
        capsys, "set", str(slot_dir), "PlayerStatus.CurrentRupee", "999", "--dry-run"
    )
    assert code == 0
    assert "dry-run" in out
    from ootsw2.savedir import SaveDirectory

    directory = SaveDirectory(str(slot_dir))
    assert directory.open_slot(directory.active_slot().index).get_int(
        "PlayerStatus.CurrentRupee"
    ) == 105


def test_set_all_slots_writes_everywhere(slot_dir, capsys):
    code, out, _ = run(
        capsys,
        "set", str(slot_dir), "PlayerStatus.DiveDepth", "9",
        "--type", "float", "--all-slots", "--no-backup",
    )
    assert code == 0
    from ootsw2.savedir import SaveDirectory

    directory = SaveDirectory(str(slot_dir))
    for index in range(6):
        assert directory.open_slot(index).get_float("PlayerStatus.DiveDepth") == 9.0
        assert directory.open_slot(index, source="save.work").get_float(
            "PlayerStatus.DiveDepth"
        ) == 9.0


def test_set_makes_a_backup_by_default(slot_dir, capsys):
    run(capsys, "set", str(slot_dir), "PlayerStatus.CurrentRupee", "42", "--all-slots")
    parent = os.path.dirname(str(slot_dir))
    assert any("before-edit" in name for name in os.listdir(parent))


def test_probe_reports_hits_and_misses(slot_dir, capsys):
    code, out, _ = run(
        capsys, "probe", str(slot_dir), "PlayerStatus.DiveDepth", "PlayerStatus.NoSuchField"
    )
    assert code == 0
    assert "hit" in out
    assert "miss" in out
    assert "1/2 present" in out


def test_probe_returns_2_when_nothing_matches(slot_dir, capsys):
    code, _out, _ = run(capsys, "probe", str(slot_dir), "PlayerStatus.NoSuchField")
    assert code == 2


def test_names_search(capsys):
    code, out, _ = run(capsys, "names", "--search", "DiveDepth")
    assert code == 0
    assert "PlayerStatus.DiveDepth" in out


def test_slots_command_marks_the_active_slot(slot_dir, capsys):
    code, out, _ = run(capsys, "slots", str(slot_dir))
    assert code == 0
    assert "ACTIVE" in out
    assert "slot_05" in out


def test_verify_dict_reports_legacy_aliases(capsys):
    code, out, _ = run(capsys, "verify-dict")
    assert code == 0
    assert "dictionary entries" in out


def test_bad_file_reports_an_error(tmp_path, capsys):
    path = tmp_path / "junk.sav"
    path.write_bytes(b"not a save file at all")
    code, _out, err = run(capsys, "get", str(path), "PlayerStatus.Life")
    assert code == 1
    assert "error" in err

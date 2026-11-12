"""Container parsing and editing, against synthetic saves only."""

import struct

import pytest

from ootsw2.container import MAGIC, SaveFile, SaveFormatError, is_inline_scalar
from ootsw2.hash import field_id

from conftest import FREE, build_save


def test_header_is_parsed(sample_bytes):
    save = SaveFile(str(sample_bytes))
    assert len(save) == 4
    assert save.header_end == 40 + 6 * 8
    assert save.free_slots == 2
    assert save.data[:4] == b"\x04\x03\x02\x01"


def test_unmodified_file_round_trips_byte_for_byte(sample_bytes):
    original = sample_bytes.read_bytes()
    save = SaveFile(str(sample_bytes))
    assert save.to_bytes() == original


def test_read_ints_and_floats(sample_bytes):
    save = SaveFile(str(sample_bytes))
    assert save.get_int("PlayerStatus.CurrentRupee") == 666
    assert save.get_int("PlayerStatus.Life") == 48
    # DiveDepth is stored as the bit pattern of 9.0f
    assert save.get_float("PlayerStatus.DiveDepth") == 9.0
    assert save.get_raw("PlayerStatus.DiveDepth") == 0x41100000


def test_read_string_from_pool(sample_bytes):
    save = SaveFile(str(sample_bytes))
    assert save.get_str("PlayerStatus.EquipWeapon") == "Weapon_Sword_Master"
    assert save.is_string("PlayerStatus.EquipWeapon")
    assert not save.is_string("PlayerStatus.Life")


def test_absent_field_returns_none(sample_bytes):
    save = SaveFile(str(sample_bytes))
    assert save.get_raw("PlayerStatus.MaxLife") is None
    assert "PlayerStatus.MaxLife" not in save


def test_set_int_in_place_keeps_size(sample_bytes):
    before = len(sample_bytes.read_bytes())
    save = SaveFile(str(sample_bytes))
    previous = save.set_int("PlayerStatus.CurrentRupee", 999)
    assert previous == 666
    save.save()
    assert len(sample_bytes.read_bytes()) == before
    assert SaveFile(str(sample_bytes)).get_int("PlayerStatus.CurrentRupee") == 999


def test_set_float(sample_bytes):
    save = SaveFile(str(sample_bytes))
    save.set_float("PlayerStatus.DiveDepth", 6.0)
    assert save.get_raw("PlayerStatus.DiveDepth") == 0x40C00000
    assert save.get_float("PlayerStatus.DiveDepth") == 6.0


def test_set_string_in_place_when_it_fits(sample_bytes):
    before = len(sample_bytes.read_bytes())
    save = SaveFile(str(sample_bytes))
    save.set_str("PlayerStatus.EquipWeapon", "Weapon_Sword_Kokiri")  # same length
    assert len(save.data) == before
    assert save.get_str("PlayerStatus.EquipWeapon") == "Weapon_Sword_Kokiri"


def test_set_string_grows_file_when_longer(sample_bytes):
    save = SaveFile(str(sample_bytes))
    before = len(save.data)
    save.set_str("PlayerStatus.EquipWeapon", "Weapon_Sword_Giant_Knife_Extra")
    assert len(save.data) > before
    assert save.get_str("PlayerStatus.EquipWeapon") == "Weapon_Sword_Giant_Knife_Extra"


def test_add_uses_a_free_slot(sample_bytes):
    save = SaveFile(str(sample_bytes))
    save.add("PlayerStatus.MaxLife", 48)
    assert save.get_int("PlayerStatus.MaxLife") == 48
    assert save.free_slots == 1
    assert len(save) == 5


def test_add_fails_when_table_is_full():
    data = build_save([("PlayerStatus.Life", 48)], spare_slots=0)
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".sav", delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        save = SaveFile(path)
        with pytest.raises(SaveFormatError):
            save.add("PlayerStatus.MaxLife", 48)
    finally:
        os.unlink(path)


def test_remove_frees_the_slot(sample_bytes):
    save = SaveFile(str(sample_bytes))
    save.remove("PlayerStatus.Life")
    assert "PlayerStatus.Life" not in save
    assert save.free_slots == 3
    save.add("PlayerStatus.MaxLife", 48)
    assert save.get_int("PlayerStatus.MaxLife") == 48


def test_bad_magic_is_rejected(tmp_path):
    bad = build_save([("PlayerStatus.Life", 48)], magic=0xDEADBEEF)
    path = tmp_path / "bad.sav"
    path.write_bytes(bad)
    with pytest.raises(SaveFormatError, match="magic"):
        SaveFile(str(path))


def test_bad_version_is_rejected(tmp_path):
    bad = build_save([("PlayerStatus.Life", 48)], version=0x12345678)
    path = tmp_path / "bad.sav"
    path.write_bytes(bad)
    with pytest.raises(SaveFormatError, match="version"):
        SaveFile(str(path))


def test_truncated_file_is_rejected(tmp_path):
    path = tmp_path / "short.sav"
    path.write_bytes(b"\x04\x03\x02\x01")
    with pytest.raises(SaveFormatError, match="too short"):
        SaveFile(str(path))


def test_string_offset_vs_inline_scalar(sample_bytes):
    save = SaveFile(str(sample_bytes))
    weapon = save.get_raw("PlayerStatus.EquipWeapon")
    assert not is_inline_scalar(save.data, save.header_end, weapon)
    assert is_inline_scalar(save.data, save.header_end, 48)


def test_diff_reports_changes_added_and_removed(sample_bytes, tmp_path):
    before = SaveFile(str(sample_bytes))
    after = SaveFile(str(sample_bytes))
    after.set_int("PlayerStatus.CurrentRupee", 999)
    after.add("PlayerStatus.MaxLife", 48)
    after.remove("PlayerStatus.Life")

    changes = before.diff(after)
    kinds = {(change.field_id, change.kind) for change in changes}
    assert (field_id("PlayerStatus.CurrentRupee"), "changed") in kinds
    assert (field_id("PlayerStatus.MaxLife"), "added") in kinds
    assert (field_id("PlayerStatus.Life"), "removed") in kinds

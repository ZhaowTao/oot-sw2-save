"""Save directory behaviour: the six rotating slots and the save.work mirror."""

import os

from ootsw2.savedir import SaveDirectory


def test_slots_are_sorted_by_index(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    slots = directory.slots()
    assert [slot.index for slot in slots] == [0, 1, 2, 3, 4, 5]
    assert slots[0].label == "slot_00"


def test_active_slot_is_the_newest(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    # conftest writes slot_05 most recently
    assert directory.active_slot().index == 5


def test_accepts_the_save_subdirectory_too(slot_dir):
    directory = SaveDirectory(os.path.join(str(slot_dir), "save"))
    assert directory.root == str(slot_dir)


def test_reads_all_slots(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    saves = directory.open_all()
    assert sorted(saves) == [0, 1, 2, 3, 4, 5]
    assert saves[0].get_int("PlayerStatus.CurrentRupee") == 100
    assert saves[5].get_int("PlayerStatus.CurrentRupee") == 105


def test_shared_files_are_reachable(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    option = directory.open_shared("option.sav")
    assert option is not None
    assert option.get_str("Option.Language") == "Lang_English"


def test_edit_all_slots_and_mirror(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    saves = directory.open_all()
    for save in saves.values():
        save.set_float("PlayerStatus.DiveDepth", 9.0)
    written = directory.save_all(saves)
    assert len(written) == 6

    for index in range(6):
        reloaded = directory.open_slot(index)
        assert reloaded.get_float("PlayerStatus.DiveDepth") == 9.0
        mirrored = directory.open_slot(index, source="save.work")
        assert mirrored.get_float("PlayerStatus.DiveDepth") == 9.0


def test_backup_copies_the_whole_tree(slot_dir):
    directory = SaveDirectory(str(slot_dir))
    target = directory.backup(tag="test")
    assert os.path.isdir(target)
    assert sorted(os.listdir(target)) == sorted(os.listdir(directory.save_dir))
    assert os.path.isfile(os.path.join(target, "slot_00", "progress.sav"))


def test_missing_work_dir_is_tolerated(tmp_path):
    root = tmp_path / "0400486024DEC000"
    (root / "save").mkdir(parents=True)
    directory = SaveDirectory(str(root))
    assert directory.has_work_copy is False
    assert directory.mirror_to_work() is False


def test_unknown_directory_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        SaveDirectory(str(tmp_path / "nope"))
